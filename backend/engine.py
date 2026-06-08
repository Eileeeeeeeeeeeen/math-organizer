"""Backend engine — pure Python class with ThreadPoolExecutor for async pipeline.

Replaces the over-engineered Redis+Celery+FastAPI stack:
  - State: in-memory list + threading.RLock (not Redis)
  - Async: ThreadPoolExecutor (not Celery)
  - Communication: direct Python calls (not HTTP)

The Gradio GUI calls Backend methods directly — same process, zero overhead.
"""

from __future__ import annotations

import tempfile
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from src.archive import ArchiveEngine
from src.config import load_settings
from src.models import (
    ProblemRecord, QueueItem, QueueStatus, Settings,
    Subject, QuestionType,
)
from src.pipeline import Pipeline


class Backend:
    """Pure-Python backend managing queue state and async pipeline execution.

    All queue mutations are protected by a reentrant lock (RLock).
    OCR and LLM batch work runs on a ThreadPoolExecutor so the GUI
    stays responsive.  The polling timer (every 1.5 s) picks up
    status changes automatically.

    Usage:
        backend = Backend()
        backend.add_images(["/path/to/img.png"], notes="...")
        backend.run_ocr_batch()
        backend.run_llm_batch()
        state = backend.get_state()   # polled by GUI
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or load_settings()
        self._queue: list[QueueItem] = []
        self._selected_idx: int = 0
        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(
            max_workers=max(self.settings.pipeline.max_concurrency, 3),
        )
        self._auto_ocr: bool = False
        self._auto_llm: bool = False
        self._auto_add: bool = False
        self._auto_archive: bool = False
        self._concurrency: int = self.settings.pipeline.max_concurrency
        self._queue_page: int = 0
        self.page_size: int = 10
        self._pipeline = Pipeline(self.settings)
        self._archive_engine = ArchiveEngine(
            vault_root=self.settings.paths.vault_root,
        )

    # ── Queue management ───────────────────────────────────────────────────

    def get_all(self) -> list[QueueItem]:
        """Return a snapshot of all queue items (safe to iterate)."""
        with self._lock:
            return list(self._queue)

    def get_item(self, index: int) -> Optional[QueueItem]:
        """Return a single item by index, or None."""
        with self._lock:
            if 0 <= index < len(self._queue):
                return self._queue[index]
            return None

    def get_selected(self) -> Optional[QueueItem]:
        """Return the currently-selected item, or None."""
        with self._lock:
            idx = self._selected_idx
            if 0 <= idx < len(self._queue):
                return self._queue[idx]
            return None

    def select_item(self, index: int) -> None:
        """Set the selected queue index."""
        with self._lock:
            if 0 <= index < len(self._queue):
                self._selected_idx = index

    def set_queue_page(self, page: int) -> None:
        """Set the current queue page (0-based)."""
        with self._lock:
            total = max(1, (len(self._queue) + self.page_size - 1) // self.page_size)
            self._queue_page = max(0, min(page, total - 1))

    def get_selected_idx(self) -> int:
        with self._lock:
            return self._selected_idx

    def add_images(self, files: list[str], notes: str = "") -> QueueItem:
        """Add one or more images as a new queue item.

        Returns the newly-created QueueItem.
        Auto-triggers OCR if auto_ocr is enabled.
        """
        valid_paths = [str(Path(f).resolve()) for f in files
                       if f and Path(f).exists()]
        if not valid_paths:
            raise ValueError("No valid image files found")

        with self._lock:
            item = QueueItem(
                id=len(self._queue),
                image_paths=valid_paths,
                user_notes=notes.strip() if notes else "",
            )
            self._queue.append(item)
            item_id = item.id
            auto_ocr = self._auto_ocr

        # Auto-trigger OCR outside the lock
        if auto_ocr:
            self.run_ocr_batch(notes)

        return self._queue[item_id]

    def clear(self) -> None:
        """Remove all queue items."""
        with self._lock:
            self._queue.clear()
            self._selected_idx = 0
            self._queue_page = 0

    # ── Pipeline triggers (fire-and-forget via ThreadPoolExecutor) ─────────

    def run_ocr_batch(self, notes: str = "") -> dict:
        """Trigger batch OCR for all IDLE items. Non-blocking.

        Returns a summary dict immediately; actual work runs in background.
        """
        with self._lock:
            idle = [it for it in self._queue if it.status == QueueStatus.IDLE]
            if not idle:
                return {"status": "no_idle_items", "idle_count": 0}

            for it in idle:
                if notes.strip() and not it.user_notes:
                    it.user_notes = notes.strip()
                it.status = QueueStatus.OCR_RUNNING

            idle_count = len(idle)
            # Snapshot the items we need to process
            idle_snapshot = [self._queue[it.id] for it in idle]
            auto_llm = self._auto_llm

        self._executor.submit(self._do_ocr_batch, idle_snapshot, auto_llm)
        return {"status": "ok", "idle_count": idle_count}

    def run_llm_batch(self) -> dict:
        """Trigger batch LLM for all OCR_DONE items. Non-blocking.

        Returns a summary dict immediately; actual work runs in background.
        """
        with self._lock:
            ready = [it for it in self._queue
                     if it.status == QueueStatus.OCR_DONE]
            if not ready:
                return {"status": "no_ocr_done_items", "ready_count": 0}

            for it in ready:
                it.status = QueueStatus.LLM_RUNNING

            ready_count = len(ready)
            ready_snapshot = [self._queue[it.id] for it in ready]

        self._executor.submit(self._do_llm_batch, ready_snapshot)
        return {"status": "ok", "ready_count": ready_count}

    def review(self, action: str, adjustments: dict | None = None) -> dict:
        """Handle a review action on the selected item.

        Actions:
          - "accept":  archive the item (synchronous — fast file I/O)
          - "skip":    mark as skipped, navigate to next waiting
          - "delete":  delete from vault + mark as DELETED
          - "reprocess": re-queue for LLM and trigger batch
        """
        adj = adjustments or {}
        with self._lock:
            idx = self._selected_idx
            if idx < 0 or idx >= len(self._queue):
                return {"status": "error", "msg": "No item selected"}
            item = self._queue[idx]

        if action == "accept":
            return self._do_archive(idx, adj)

        elif action == "skip":
            with self._lock:
                self._queue[idx].status = QueueStatus.SKIPPED
                self._nav_next_waiting()
            return {"status": "ok"}

        elif action == "delete":
            return self.delete_from_vault(idx)

        elif action == "reprocess":
            with self._lock:
                self._queue[idx].status = QueueStatus.LLM_QUEUED
            return self.run_llm_batch()

        return {"status": "error", "msg": f"Unknown action: {action}"}

    # ── Background workers (run on ThreadPoolExecutor) ────────────────────

    def _do_ocr_batch(self, items: list[QueueItem], auto_llm: bool) -> None:
        """Run OCR on items via Pipeline. Updates queue after each completion.

        Processes images concurrently within Pipeline.run_ocr_for_items,
        then writes results back in one batch (OCR polling is async anyway).
        """
        try:
            results = self._pipeline.run_ocr_for_items(items)
            with self._lock:
                for r in results:
                    if 0 <= r.id < len(self._queue):
                        self._queue[r.id] = r
        except Exception as exc:
            print(f"❌ OCR batch failed: {exc}", flush=True)
            with self._lock:
                for it in items:
                    if 0 <= it.id < len(self._queue):
                        self._queue[it.id].status = QueueStatus.ERROR_OCR
                        self._queue[it.id].error_msg = str(exc)

        # Chain to LLM if auto mode is on
        if auto_llm:
            self.run_llm_batch()

    def _do_llm_batch(self, items: list[QueueItem]) -> None:
        """Run LLM on items concurrently, updating queue after EACH completion.

        This lets the polling timer show incremental progress — items appear
        as WAITING_REVIEW one by one, so the user can start reviewing while
        remaining items are still processing.

        If auto_archive is enabled, successful items skip WAITING_REVIEW
        and are archived immediately.
        """
        max_workers = min(len(items), max(self._concurrency, 1))
        auto_archive = self._auto_archive  # snapshot at start

        def process_one(item: QueueItem) -> QueueItem:
            item.status = QueueStatus.LLM_RUNNING
            try:
                record = self._pipeline.run_llm(item.ocr_text)
                item.record = record
                item.status = QueueStatus.LLM_DONE
                item.error_msg = ""
            except Exception as exc:
                print(f"❌ LLM failed (item #{item.id}): {exc}", flush=True)
                item.status = QueueStatus.ERROR_LLM
                item.error_msg = str(exc)

            # Decide auto-archive BEFORE changing status to WAITING_REVIEW
            # (item.status is the same object reference as self._queue[id].status)
            should_auto_archive = (item.status == QueueStatus.LLM_DONE and auto_archive)

            # Update queue immediately — polling timer picks this up in ≤1.5s
            with self._lock:
                if 0 <= item.id < len(self._queue):
                    self._queue[item.id] = item
                    if item.status == QueueStatus.LLM_DONE and not auto_archive:
                        self._queue[item.id].status = QueueStatus.WAITING_REVIEW

            # Auto-archive: skip review, archive immediately
            if should_auto_archive:
                self._auto_archive_one(item.id)

            return item

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(process_one, item) for item in items]
            for future in as_completed(futures):
                future.result()  # exceptions are handled inside process_one

        # After all done, auto-select first waiting item if current isn't one
        with self._lock:
            waiting = [it for it in self._queue
                       if it.status == QueueStatus.WAITING_REVIEW]
            if waiting:
                current = (self._queue[self._selected_idx]
                           if 0 <= self._selected_idx < len(self._queue)
                           else None)
                if current is None or current.status != QueueStatus.WAITING_REVIEW:
                    self._selected_idx = waiting[0].id

    def _auto_archive_one(self, idx: int) -> None:
        """Archive a single item without navigation (for auto-archive)."""
        with self._lock:
            if idx < 0 or idx >= len(self._queue):
                return
            item = self._queue[idx]
            if item.record is None:
                return
            record = item.record
            img_path = Path(item.image_paths[0]) if item.image_paths else None

        try:
            result = self._archive_engine.archive(record, source_image=img_path)
            with self._lock:
                if 0 <= idx < len(self._queue):
                    if result["success"]:
                        self._queue[idx].status = QueueStatus.ARCHIVED
                        self._queue[idx].filename = result.get("filename", "")
                        self._queue[idx].archive_result = result
                    else:
                        self._queue[idx].status = QueueStatus.ERROR_ARCHIVE
                        self._queue[idx].error_msg = "; ".join(
                            result.get("errors", ["Unknown archive error"]))
        except Exception as e:
            print(f"❌ Auto-archive failed (item #{idx}): {e}", flush=True)
            with self._lock:
                if 0 <= idx < len(self._queue):
                    self._queue[idx].status = QueueStatus.ERROR_ARCHIVE
                    self._queue[idx].error_msg = str(e)

    def _do_archive(self, idx: int, adjustments: dict) -> dict:
        """Archive a reviewed item (called synchronously — fast file I/O)."""
        with self._lock:
            if idx < 0 or idx >= len(self._queue):
                return {"status": "error", "msg": f"Item {idx} out of range"}
            item = self._queue[idx]

        if item.record is None:
            return {"status": "error", "msg": "Item has no LLM record"}

        # Apply adjustments
        try:
            if adjustments.get("subject_adj"):
                item.record.meta.subject = Subject(adjustments["subject_adj"])
            if adjustments.get("lecture_adj"):
                item.record.meta.lecture = adjustments["lecture_adj"]
            if adjustments.get("qtype_adj"):
                item.record.meta.question_type = QuestionType(adjustments["qtype_adj"])
            if adjustments.get("opd_adj", "").strip():
                item.record.meta.opd.target = adjustments["opd_adj"].strip()
        except ValueError as e:
            return {"status": "error", "msg": f"Invalid adjustment: {e}"}

        # Archive
        img_path = Path(item.image_paths[0]) if item.image_paths else None
        try:
            result = self._archive_engine.archive(item.record, source_image=img_path)
            with self._lock:
                if result["success"]:
                    self._queue[idx].status = QueueStatus.ARCHIVED
                    self._queue[idx].filename = result.get("filename", "")
                    self._queue[idx].archive_result = result
                else:
                    self._queue[idx].status = QueueStatus.ERROR_ARCHIVE
                    self._queue[idx].error_msg = "; ".join(
                        result.get("errors", ["Unknown archive error"]))
                self._nav_next_waiting()
            error_msg = "; ".join(result.get("errors", ["Unknown archive error"]))
            return {"status": "ok" if result["success"] else "error",
                    "filename": result.get("filename", ""),
                    "msg": "" if result["success"] else error_msg}
        except Exception as e:
            print(f"❌ Archive failed (item #{idx}): {e}", flush=True)
            with self._lock:
                self._queue[idx].status = QueueStatus.ERROR_ARCHIVE
                self._queue[idx].error_msg = str(e)
                self._nav_next_waiting()
            return {"status": "error", "msg": str(e)}

    def delete_from_vault(self, idx: int) -> dict:
        """Delete an archived/reviewable item from the vault.

        Only items with ARCHIVED or WAITING_REVIEW status can be deleted.
        The .md file, referenced images, and _index.md link are removed.
        Queue item is marked DELETED.
        """
        with self._lock:
            if idx < 0 or idx >= len(self._queue):
                return {"status": "error", "msg": f"Item {idx} out of range"}
            item = self._queue[idx]

            if item.status not in (QueueStatus.ARCHIVED, QueueStatus.WAITING_REVIEW):
                return {"status": "error",
                        "msg": f"只能删除已归档或待审核的题目 (当前: {item.status.value})"}

            if item.record is None:
                return {"status": "error", "msg": "Item has no record to delete"}

            filename = item.filename
            record = item.record

        if not filename:
            return {"status": "error", "msg": "Item has no filename — not yet archived"}

        # Delete from filesystem via ArchiveEngine
        try:
            del_result = self._archive_engine.delete_problem(record, filename)
            with self._lock:
                if del_result["success"]:
                    self._queue[idx].status = QueueStatus.DELETED
                else:
                    # Leave current status, report errors
                    pass
                self._nav_next_waiting()
            return {
                "status": "ok" if del_result["success"] else "error",
                "msg": "; ".join(del_result.get("errors", [])
                                + del_result.get("warnings", [])),
                "deleted_md": del_result.get("deleted_md", ""),
                "deleted_images": del_result.get("deleted_images", []),
            }
        except Exception as e:
            print(f"❌ Delete failed (item #{idx}): {e}", flush=True)
            with self._lock:
                self._nav_next_waiting()
            return {"status": "error", "msg": str(e)}

    # ── Navigation ─────────────────────────────────────────────────────────

    def nav_prev(self) -> int:
        """Navigate to the previous WAITING_REVIEW item (wraps around)."""
        with self._lock:
            current = self._selected_idx
            # Search backwards from current-1 to 0
            for i in range(current - 1, -1, -1):
                if self._queue[i].status == QueueStatus.WAITING_REVIEW:
                    self._selected_idx = i
                    return i
            # Wrap: search backwards from end to current+1
            for i in range(len(self._queue) - 1, current, -1):
                if self._queue[i].status == QueueStatus.WAITING_REVIEW:
                    self._selected_idx = i
                    return i
            return current

    def nav_next(self) -> int:
        """Navigate to the next WAITING_REVIEW item."""
        with self._lock:
            current = self._selected_idx
            for i in range(current + 1, len(self._queue)):
                if self._queue[i].status == QueueStatus.WAITING_REVIEW:
                    self._selected_idx = i
                    return i
            for i in range(0, current):
                if self._queue[i].status == QueueStatus.WAITING_REVIEW:
                    self._selected_idx = i
                    return i
            return current

    def _nav_next_waiting(self) -> None:
        """Internal: navigate to next WAITING_REVIEW after current index.
        Must be called while holding self._lock.
        """
        current = self._selected_idx
        for i in range(current + 1, len(self._queue)):
            if self._queue[i].status == QueueStatus.WAITING_REVIEW:
                self._selected_idx = i
                return
        for i in range(0, current):
            if self._queue[i].status == QueueStatus.WAITING_REVIEW:
                self._selected_idx = i
                return

    # ── Auto-mode config ───────────────────────────────────────────────────

    def get_auto_ocr(self) -> bool:
        return self._auto_ocr

    def set_auto_ocr(self, value: bool) -> None:
        self._auto_ocr = value

    def get_auto_llm(self) -> bool:
        return self._auto_llm

    def set_auto_llm(self, value: bool) -> None:
        self._auto_llm = value

    def get_auto_add(self) -> bool:
        return self._auto_add

    def set_auto_add(self, value: bool) -> None:
        self._auto_add = value

    def get_auto_archive(self) -> bool:
        return self._auto_archive

    def set_auto_archive(self, value: bool) -> None:
        self._auto_archive = value

    def get_concurrency(self) -> int:
        return self._concurrency

    def set_concurrency(self, value: int) -> None:
        self._concurrency = value
        self.settings.pipeline.max_concurrency = value

    def get_vault_tree(self) -> dict:
        """Return the vault directory tree for the GUI vault browser."""
        return self._archive_engine.get_vault_tree()

    def delete_vault_file(self, relative_path: str) -> dict:
        """Delete a file from the vault by its relative path.

        Args:
            relative_path: e.g. '高等数学/第3讲_导数与微分/填空题/xxx.md'
        """
        return self._archive_engine.delete_by_path(relative_path)

    def read_vault_file(self, relative_path: str) -> str:
        """Read a .md file from the vault and return its content.

        Args:
            relative_path: Path relative to vault_root, e.g.
                           '高等数学/第3讲_导数与微分/填空题/xxx.md'

        Returns:
            The file content as a string, or an error message.
        """
        file_path = self._archive_engine.vault_root / relative_path
        # Security: ensure the resolved path is inside vault_root
        try:
            resolved = file_path.resolve()
            if not str(resolved).startswith(str(self._archive_engine.vault_root.resolve())):
                return "*⛔ 路径越界*"
        except Exception:
            return "*⛔ 路径无效*"

        if not resolved.exists() or not resolved.is_file():
            return f"*❌ 文件不存在: {relative_path}*"

        try:
            return resolved.read_text(encoding="utf-8")
        except Exception as e:
            return f"*❌ 读取失败: {e}*"

    # ── Full state snapshot (for GUI polling) ──────────────────────────────

    def create_vault_zip(self) -> str:
        """Create a zip archive of the entire vault directory.

        Returns the path to a temporary zip file. Gradio's DownloadButton
        will serve this file and the browser will download it.
        """
        vault_path = Path(self.settings.paths.vault_root).resolve()
        if not vault_path.exists():
            raise FileNotFoundError(f"题库目录不存在: {vault_path}")

        # Create temp zip file (delete=False so Gradio can serve it)
        tmp = tempfile.NamedTemporaryFile(
            suffix=".zip", prefix="math_vault_", delete=False
        )
        zip_path = tmp.name
        tmp.close()

        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for file in sorted(vault_path.rglob("*")):
                    if file.is_file():
                        # arcname relative to vault_root's parent,
                        # so the zip contains "考研数学题库/..." at top level
                        arcname = str(file.relative_to(vault_path.parent))
                        zf.write(file, arcname)
        except Exception:
            # Clean up partial zip on failure
            Path(zip_path).unlink(missing_ok=True)
            raise

        return zip_path

    def get_state(self) -> dict:
        """Return the full session state as a dict.

        Called by the GUI polling timer every 1.5 s.
        Returns the same structure the old /api/state endpoint returned,
        so gui/app.py needs minimal changes.
        """
        with self._lock:
            items = list(self._queue)
            idx = self._selected_idx
            item = items[idx] if 0 <= idx < len(items) else None
            return {
                "queue": [it.model_dump() for it in items],
                "selected_idx": idx,
                "selected_item": item.model_dump() if item else None,
                "auto_ocr": self._auto_ocr,
                "auto_llm": self._auto_llm,
                "auto_add": self._auto_add,
                "auto_archive": self._auto_archive,
                "concurrency": self._concurrency,
                "total": len(items),
                "queue_page": self._queue_page,
                "total_pages": max(1, (len(items) + self.page_size - 1) // self.page_size),
                "page_size": self.page_size,
                "waiting_review": sum(
                    1 for it in items
                    if it.status == QueueStatus.WAITING_REVIEW),
                "accepted": sum(
                    1 for it in items
                    if it.status in (QueueStatus.ACCEPTED, QueueStatus.ARCHIVED)),
                "skipped": sum(
                    1 for it in items
                    if it.status == QueueStatus.SKIPPED),
                "deleted": sum(
                    1 for it in items
                    if it.status == QueueStatus.DELETED),
                "errors": sum(
                    1 for it in items
                    if it.status in (QueueStatus.ERROR_OCR,
                                     QueueStatus.ERROR_LLM,
                                     QueueStatus.ERROR_ARCHIVE)),
            }
