"""Pipeline orchestration — wires OCR → LLM → Archive together.

Provides a clean Pipeline class callable from both the Gradio GUI and CLI.
API keys and endpoints are loaded from config/settings.yml.
"""

from __future__ import annotations

import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Callable

import requests
import yaml

from src.archive import ArchiveEngine
from src.config import load_settings
from src.models import ProblemRecord, Settings, QueueItem, QueueStatus
from src.validators.frontmatter_validator import validate_frontmatter
from src.validators.naming_validator import generate_filename, validate_filename
from src.validators.dedup import compute_problem_hash


class Pipeline:
    """Orchestrates the full math problem processing pipeline.

    Usage:
        pipeline = Pipeline()
        ocr_text = pipeline.run_ocr(Path("screenshot.png"))
        record = pipeline.run_llm(ocr_text)
        result = pipeline.run_archive(record, source_image=Path("screenshot.png"))
    """

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or load_settings()
        self._archive: Optional[ArchiveEngine] = None

    @property
    def archive_engine(self) -> ArchiveEngine:
        if self._archive is None:
            self._archive = ArchiveEngine(vault_root=self.settings.paths.vault_root)
        return self._archive

    # ── Public API ──────────────────────────────────────────────────────────

    def run_ocr(self, image_path: Path) -> str:
        """OCR a single image file, return Markdown text (may contain LaTeX).

        Raises RuntimeError on API failure.
        """
        print(f"📷 OCR: processing {image_path.name}")
        return _call_paddleocr(image_path)

    def run_llm(self, ocr_text: str) -> ProblemRecord:
        """Send OCR text to LLM, return a validated ProblemRecord.

        The LLM is configured with the full knowledge tree + OPD system
        via Tool Calling with JSON Schema enforcement.

        Raises RuntimeError on API failure, ValidationError on bad output.
        """
        print(f"🤖 LLM: processing {len(ocr_text)} chars of OCR text")
        llm_json = _call_deepseek(ocr_text, self.settings)
        record = ProblemRecord(**llm_json)
        return record

    def run_archive(
        self,
        record: ProblemRecord,
        source_image: Optional[Path] = None,
    ) -> dict:
        """Archive a validated ProblemRecord to the vault.

        Returns the result dict from ArchiveEngine.archive().
        """
        print(f"📁 Archive: saving to vault")
        return self.archive_engine.archive(record, source_image=source_image)

    def run_full(
        self,
        image_path: Path,
        text_input: Optional[str] = None,
    ) -> dict:
        """Run the full pipeline: OCR → LLM → Archive.

        If text_input is provided, skip OCR and use the text directly.

        Returns a dict with all intermediate results for GUI display.
        """
        result = {
            "success": False,
            "ocr_text": "",
            "llm_json": None,
            "record": None,
            "filename": "",
            "archive_result": None,
            "errors": [],
            "warnings": [],
        }

        try:
            # Phase 1: OCR (or skip if text provided)
            if text_input and text_input.strip():
                result["ocr_text"] = text_input.strip()
                result["warnings"].append("OCR skipped — using manual text input")
            else:
                result["ocr_text"] = self.run_ocr(image_path)
        except Exception as e:
            result["errors"].append(f"OCR failed: {e}")
            return result

        try:
            # Phase 2: LLM
            result["llm_json"] = self.run_llm(result["ocr_text"]).model_dump()
            result["record"] = ProblemRecord(**result["llm_json"])
        except Exception as e:
            result["errors"].append(f"LLM failed: {e}")
            return result

        try:
            # Phase 3: Validation checks
            record = result["record"]
            meta_dict = result["llm_json"]["meta"]
            filename = generate_filename(meta_dict, record.problem)
            result["filename"] = filename

            # Validate naming
            name_check = validate_filename(filename)
            if not name_check["valid"]:
                result["warnings"].append(f"Naming issue: {name_check['errors']}")

            # Compute content hash
            result["content_hash"] = compute_problem_hash(record.problem)

        except Exception as e:
            result["warnings"].append(f"Validation warning: {e}")

        try:
            # Phase 4: Archive
            result["archive_result"] = self.run_archive(record, source_image=image_path)
            result["success"] = result["archive_result"]["success"]
        except Exception as e:
            result["errors"].append(f"Archive failed: {e}")

        return result

    # ── Batch Operations ────────────────────────────────────────────────────

    def run_ocr_batch(
        self,
        image_paths: list[Path],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> list[dict]:
        """Run OCR on multiple images concurrently.

        Submits all jobs, then polls all in parallel via ThreadPoolExecutor.

        Args:
            image_paths: List of image file paths.
            progress_callback: Optional fn(done, total, status_msg) called on each completion.

        Returns:
            List of dicts with {image_path, ocr_text, success, error}.
        """
        jobs: list[dict] = []  # {image_path, job_id}
        results: list[dict] = []

        # Phase 1: Submit all jobs
        for i, path in enumerate(image_paths):
            if progress_callback:
                progress_callback(i, len(image_paths), f"Submitting OCR job {i+1}/{len(image_paths)}")
            try:
                job_id = _submit_ocr_job(path, self.settings)
                jobs.append({"image_path": path, "job_id": job_id, "index": i})
            except Exception as e:
                results.append({"image_path": path, "ocr_text": "", "success": False, "error": str(e)})

        # Phase 2: Poll all jobs concurrently
        def poll_one(job_info: dict) -> dict:
            path = job_info["image_path"]
            job_id = job_info["job_id"]
            idx = job_info["index"]
            try:
                text = _poll_ocr_job(job_id, self.settings)
                if progress_callback:
                    progress_callback(idx + 1, len(image_paths), f"OCR done {idx+1}/{len(image_paths)}")
                return {"image_path": path, "ocr_text": text, "success": True, "error": ""}
            except Exception as e:
                if progress_callback:
                    progress_callback(idx + 1, len(image_paths), f"OCR failed {idx+1}")
                return {"image_path": path, "ocr_text": "", "success": False, "error": str(e)}

        with ThreadPoolExecutor(max_workers=min(len(jobs), self.settings.pipeline.max_concurrency)) as pool:
            futures = {pool.submit(poll_one, j): j["index"] for j in jobs}
            batch_results = [None] * len(jobs)
            for future in as_completed(futures):
                idx = futures[future]
                batch_results[idx] = future.result()

        # Merge: submitted jobs + already-failed submissions
        merged = []
        batch_idx = 0
        for i in range(len(image_paths)):
            submitted = any(j["index"] == i for j in jobs)
            if submitted:
                merged.append(batch_results[batch_idx])
                batch_idx += 1
            else:
                merged.append(results[i - batch_idx])
        return merged

    def run_llm_concurrent(
        self,
        items: list[QueueItem],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> list[QueueItem]:
        """Process multiple QueueItems through LLM concurrently.

        Uses ThreadPoolExecutor with max_concurrency cap.

        Args:
            items: QueueItems with ocr_text populated (status=OCR_DONE).
            progress_callback: Optional fn(done, total, status_msg).

        Returns:
            Same QueueItems with record populated (status=LLM_DONE or ERROR_LLM).
        """
        max_workers = min(len(items), self.settings.pipeline.max_concurrency)
        results: list[QueueItem] = [None] * len(items)

        def process_one(item: QueueItem) -> QueueItem:
            item.status = QueueStatus.LLM_RUNNING
            try:
                record = self.run_llm(item.ocr_text)
                item.record = record
                item.status = QueueStatus.LLM_DONE
                item.error_msg = ""
            except Exception as e:
                item.status = QueueStatus.ERROR_LLM
                item.error_msg = str(e)
            return item

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(process_one, item): item.id for item in items}
            for future in as_completed(futures):
                result = future.result()
                results[result.id] = result
                done = sum(1 for r in results if r is not None)
                if progress_callback:
                    progress_callback(done, len(items), f"LLM {done}/{len(items)}")

        return results

    def run_ocr_for_items(
        self,
        items: list[QueueItem],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> list[QueueItem]:
        """OCR each QueueItem's images (may have multiple per item).

        For items with N images: OCR all images, concatenate results
        with separators, then append user_notes.
        """
        # Flatten: collect all (item_id, image_path) pairs
        jobs: list[tuple[int, int, Path]] = []  # (item_id, img_idx, path)
        for item in items:
            for img_idx, img_path in enumerate(item.image_paths):
                if img_path and Path(img_path).exists():
                    jobs.append((item.id, img_idx, Path(img_path)))

        if not jobs:
            return items

        total_jobs = len(jobs)
        if progress_callback:
            progress_callback(0, total_jobs, f"Submitting {total_jobs} OCR jobs...")

        # Submit all
        submitted: dict[tuple[int, int], str] = {}  # (item_id, img_idx) → job_id
        failed_submissions: list[tuple[int, int, str]] = []

        for item_id, img_idx, path in jobs:
            try:
                jid = _submit_ocr_job(path, self.settings)
                submitted[(item_id, img_idx)] = jid
            except Exception as e:
                failed_submissions.append((item_id, img_idx, str(e)))

        # Poll concurrently
        def poll_key(key: tuple[int, int]) -> tuple[int, int, str, str]:
            item_id, img_idx = key
            jid = submitted[key]
            text = _poll_ocr_job(jid, self.settings)
            return (item_id, img_idx, text, "")

        ocr_results: dict[int, dict[int, str]] = {}  # item_id → {img_idx: text}
        errors: dict[int, list[str]] = {}

        if submitted:
            with ThreadPoolExecutor(max_workers=min(len(submitted), self.settings.pipeline.max_concurrency)) as pool:
                futures = {
                    pool.submit(poll_key, k): k for k in submitted
                }
                done_count = 0
                for future in as_completed(futures):
                    item_id, img_idx, text, err = future.result()
                    ocr_results.setdefault(item_id, {})[img_idx] = text
                    if err:
                        errors.setdefault(item_id, []).append(err)
                    done_count += 1
                    if progress_callback:
                        progress_callback(done_count, total_jobs,
                                          f"OCR {done_count}/{total_jobs}")

        # Assemble results per item
        for item in items:
            per_img = ocr_results.get(item.id, {})
            if not per_img and item.id in [f[0] for f in failed_submissions]:
                item.status = QueueStatus.ERROR_OCR
                item.error_msg = "; ".join(e for iid, _, e in failed_submissions if iid == item.id)
                continue

            # Concatenate images in order
            parts = []
            for i in range(len(item.image_paths)):
                if i in per_img and per_img[i]:
                    parts.append(per_img[i])
            if not parts:
                item.status = QueueStatus.ERROR_OCR
                item.error_msg = "No OCR text extracted"
                continue

            ocr_text = "\n\n---\n\n".join(parts)
            if item.user_notes:
                ocr_text = f"{ocr_text}\n\n📝 补充信息：{item.user_notes}"
            item.ocr_text = ocr_text
            item.status = QueueStatus.OCR_DONE

        return items

    def run_full_batch(
        self,
        items: list[QueueItem],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> list[QueueItem]:
        """Full batch pipeline: OCR all items → LLM all concurrently.

        Each QueueItem may have multiple images (concatenated per item).
        Returns items ready for review (status=LLM_DONE or ERROR_*).
        """
        n = len(items)

        # Phase 1: OCR
        if progress_callback:
            progress_callback(0, n, "Starting batch OCR...")
        items = self.run_ocr_for_items(items, _batch_progress(progress_callback, "OCR"))

        # Phase 2: LLM for successful OCR items
        ready = [it for it in items if it.status == QueueStatus.OCR_DONE]
        if ready:
            if progress_callback:
                progress_callback(0, len(ready),
                                  f"Starting LLM ({self.settings.pipeline.max_concurrency} concurrent)...")
            processed = self.run_llm_concurrent(
                ready, _batch_progress(progress_callback, "LLM"),
            )
            for p in processed:
                items[p.id] = p

        if progress_callback:
            done = sum(1 for it in items if it.status == QueueStatus.LLM_DONE)
            progress_callback(done, n, f"Batch complete: {done}/{n} succeeded")

        return items


def _batch_progress(
    cb: Optional[Callable[[int, int, str], None]],
    prefix: str,
) -> Optional[Callable[[int, int, str], None]]:
    """Wrap a progress callback to add a prefix."""
    if cb is None:
        return None
    return lambda done, total, msg: cb(done, total, f"[{prefix}] {msg}")


# ── Internal API callers ─────────────────────────────────────────────────────


def _submit_ocr_job(image_path: Path, settings: Settings) -> str:
    """Submit an OCR job, return job_id."""
    api_key = _get_api_key("PADDLEOCR_API_KEY", settings)
    headers = {"Authorization": f"bearer {api_key}"}

    data = {
        "model": settings.ocr.model,
        "optionalPayload": json.dumps({
            "useDocOrientationClassify": False,
            "useDocUnwarping": False,
            "useChartRecognition": False,
        }),
    }

    with open(image_path, "rb") as f:
        response = requests.post(
            settings.ocr.api_endpoint,
            headers=headers,
            data=data,
            files={"file": f},
            timeout=settings.ocr.timeout,
        )

    if response.status_code != 200:
        raise RuntimeError(f"OCR job submission failed: {response.text[:300]}")
    return response.json()["data"]["jobId"]


def _poll_ocr_job(job_id: str, settings: Settings) -> str:
    """Poll OCR job until done, return markdown text."""
    api_key = _get_api_key("PADDLEOCR_API_KEY", settings)
    headers = {"Authorization": f"bearer {api_key}"}
    poll_url = f"{settings.ocr.api_endpoint}/{job_id}"

    for _ in range(60):
        time.sleep(5)
        resp = requests.get(poll_url, headers=headers, timeout=30)
        if resp.status_code != 200:
            continue
        data = resp.json()["data"]
        if data["state"] == "done":
            jsonl_url = data["resultUrl"]["jsonUrl"]
            break
        elif data["state"] == "failed":
            raise RuntimeError(f"OCR job failed: {data.get('errorMsg', 'unknown')}")
    else:
        raise RuntimeError(f"OCR job {job_id} timed out")

    # Download JSONL
    jsonl_resp = requests.get(jsonl_url, timeout=60)
    jsonl_resp.raise_for_status()
    parts = []
    for line in jsonl_resp.text.strip().split("\n"):
        if not line.strip():
            continue
        page = json.loads(line)
        for lr in page["result"]["layoutParsingResults"]:
            if lr["markdown"]["text"]:
                parts.append(lr["markdown"]["text"])
    return "\n\n".join(parts)

def _call_paddleocr(image_path: Path) -> str:
    """Call PaddleOCR VL-1.6 API (v2 job-based), return Markdown text."""
    settings = load_settings()
    api_key = _get_api_key("PADDLEOCR_API_KEY", settings)
    job_url = settings.ocr.api_endpoint

    headers = {"Authorization": f"bearer {api_key}"}
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }

    # Submit job with multipart upload
    data = {
        "model": settings.ocr.model,
        "optionalPayload": json.dumps(optional_payload),
    }

    with open(image_path, "rb") as f:
        response = requests.post(
            job_url,
            headers=headers,
            data=data,
            files={"file": f},
            timeout=settings.ocr.timeout,
        )

    if response.status_code != 200:
        raise RuntimeError(f"PaddleOCR job submission failed: {response.text[:500]}")

    job_id = response.json()["data"]["jobId"]

    # Poll for completion
    poll_url = f"{job_url}/{job_id}"
    for _ in range(60):
        time.sleep(5)
        poll_resp = requests.get(poll_url, headers=headers, timeout=30)
        if poll_resp.status_code != 200:
            continue
        state = poll_resp.json()["data"]["state"]
        if state == "done":
            jsonl_url = poll_resp.json()["data"]["resultUrl"]["jsonUrl"]
            break
        elif state == "failed":
            raise RuntimeError(f"OCR job failed: {poll_resp.json()['data'].get('errorMsg')}")
    else:
        raise RuntimeError(f"OCR job {job_id} timed out")

    # Download and parse JSONL result
    jsonl_resp = requests.get(jsonl_url, timeout=60)
    jsonl_resp.raise_for_status()

    parts = []
    for line in jsonl_resp.text.strip().split("\n"):
        if not line.strip():
            continue
        page = json.loads(line)
        for lr in page["result"]["layoutParsingResults"]:
            if lr["markdown"]["text"]:
                parts.append(lr["markdown"]["text"])

    return "\n\n".join(parts)


def _call_deepseek(ocr_text: str, settings: Settings) -> dict:
    """Call DeepSeek API with Tool Calling to get structured JSON."""
    api_key = _get_api_key("DEEPSEEK_API_KEY", settings)

    # Load JSON Schema
    schema_path = Path(__file__).resolve().parent.parent / "templates" / "LLM 输出 JSON Schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        json_schema = json.load(f)

    # Load knowledge tree + OPD for system prompt
    kt_path = Path(__file__).resolve().parent.parent / "config" / "knowledge_tree.yml"
    opd_path = Path(__file__).resolve().parent.parent / "config" / "opd_markers.yml"
    with open(kt_path, "r", encoding="utf-8") as f:
        knowledge_tree = f.read()
    with open(opd_path, "r", encoding="utf-8") as f:
        opd_markers = f.read()

    system_prompt = _build_system_prompt(knowledge_tree, opd_markers)
    tool_parameters = {k: v for k, v in json_schema.items() if k != "$schema"}

    payload = {
        "model": settings.llm.model_default,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"请整理以下考研数学题目：\n\n{ocr_text}"},
        ],
        "tools": [{
            "type": "function",
            "function": {
                "name": "organize_math_problem",
                "description": "整理考研数学题目，输出结构化 JSON",
                "parameters": tool_parameters,
            },
        }],
        "reasoning_effort": settings.llm.reasoning_effort,
        "temperature": settings.llm.temperature,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    response = requests.post(
        f"{settings.llm.api_base}/chat/completions",
        json=payload,
        headers=headers,
        timeout=120,
    )

    if response.status_code != 200:
        raise RuntimeError(f"DeepSeek API failed: {response.text[:500]}")

    result = response.json()
    message = result["choices"][0]["message"]

    # Extract tool call result
    if "tool_calls" in message and len(message["tool_calls"]) > 0:
        raw = message["tool_calls"][0]["function"]["arguments"]
    else:
        # Fallback: parse content as JSON
        content = message.get("content", "")
        if content:
            m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
            raw = m.group(1) if m else content
        else:
            raise RuntimeError("No tool call or parseable JSON in LLM response")

    parsed = _safe_json_loads(raw)

    # Unwrap {"input": {...}} / {"params": {...}} / ... wrapper keys
    # DeepSeek tool calling may nest output under various keys.
    if isinstance(parsed, dict) and "meta" not in parsed:
        for key in ("input", "params", "data", "result", "output", "arguments"):
            if key in parsed and isinstance(parsed[key], dict):
                parsed = parsed[key]
                break
        # Generic fallback: single-key dict whose value is a dict → unwrap
        if "meta" not in parsed and len(parsed) == 1:
            only_value = next(iter(parsed.values()))
            if isinstance(only_value, dict):
                parsed = only_value

    return parsed


def _safe_json_loads(raw: str) -> dict:
    """Parse JSON, fixing LaTeX backslash escapes if DeepSeek omits them.

    DeepSeek should output \\\\sum but often outputs single-backslash LaTeX
    like \\sum, \\frac, \\{, \\$, \\% etc. — these are invalid JSON escapes
    (or worse, valid but wrong: \\f → form-feed, \\t → tab, \\n → newline).

    We escape ALL single backslashes except valid JSON structural escapes:
    \\\\, \\", \\/, and \\uXXXX (unicode).  Everything else is treated as
    a LaTeX command and gets its backslash doubled.

    This is safe because Chinese math problems contain no legitimate
    JSON control characters (form-feed, tab, etc.) in the text content.
    """
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Step 1: Fix \\X for any X that is NOT a valid JSON structural escape.
    # Preserve: \\, \", \/, \u (unicode handled in step 2).
    fixed = re.sub(
        r'(?<!\\)\\([^"\\/u])',
        r'\\\\\1',
        raw,
    )

    # Step 2: Fix \\u not followed by exactly 4 hex digits.
    # LaTeX commands like \\under, \\cup start with \\u but are NOT unicode.
    fixed = re.sub(
        r'(?<!\\)\\u(?![\da-fA-F]{4})',
        r'\\\\u',
        fixed,
    )

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        # Last resort: escape every remaining single backslash
        fixed2 = re.sub(r'(?<!\\)\\(.)', r'\\\\\1', fixed)
        return json.loads(fixed2)


def _build_system_prompt(knowledge_tree: str, opd_markers: str) -> str:
    return f"""你是考研数学辅导专家，精通考研数学知识体系。你的任务是将用户提供的数学题目整理为结构化的 JSON 格式。

## 知识体系（只能从中选择知识点）

{knowledge_tree}

## 解题方法论（OPD）记号体系（只能从中选择 O/P/D 代码）

{opd_markers}

## 输出要求

1. 使用 organize_math_problem 函数输出结构化 JSON
2. 所有数学公式必须使用 LaTeX 格式
3. subject 必须从 [高等数学, 线性代数, 概率统计] 中选择
4. lecture 必须从知识体系中的讲次名称中选择
5. question_type 必须从 [选择题, 填空题, 解答题] 中选择
6. OPD 标记只能从上述记号体系中选择
7. key_ability 从 [概念辨析, 计算能力, 证明推理, 综合应用] 中选择
8. solution.key_insight 直截了当指出该题的核心关键（如"极限转化为导数定义""利用对称性消去交叉项""构造辅助函数应用罗尔定理"）
9. 解题步骤清晰，每步一个字符串元素"""


def _get_api_key(env_var: str, settings: Optional[Settings] = None) -> str:
    """Get API key: settings → env var → api.md fallback."""
    import os

    # 1. Check settings (primary source)
    if settings is not None:
        if env_var == "PADDLEOCR_API_KEY" and settings.ocr.api_key:
            return settings.ocr.api_key
        if env_var == "DEEPSEEK_API_KEY" and settings.llm.api_key:
            return settings.llm.api_key

    # 2. Check environment variable
    key = os.environ.get(env_var)
    if key:
        return key

    # 3. Fallback: tests/api.md (legacy, for backward compatibility)
    api_file = Path(__file__).resolve().parent.parent / "tests" / "api.md"
    if api_file.exists():
        content = api_file.read_text(encoding="utf-8")
        if env_var == "PADDLEOCR_API_KEY":
            for line in content.split("\n"):
                if len(line.strip()) == 40 and not line.startswith("sk-"):
                    return line.strip()
        elif env_var == "DEEPSEEK_API_KEY":
            for line in content.split("\n"):
                if line.strip().startswith("sk-"):
                    return line.strip()

    raise RuntimeError(
        f"API key not found for {env_var}. "
        f"Set it in config/settings.yml, environment variable, or tests/api.md"
    )
