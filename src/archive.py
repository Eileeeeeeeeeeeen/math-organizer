"""Archive engine — renders MD files, manages directory structure & MOC indices."""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader

from src.models import ProblemRecord
from src.validators.naming_validator import generate_filename

# Jinja2 environment pointing to templates/ directory
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_jinja_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=False)

# Expected subject → lecture mapping
EXPECTED_SUBJECTS = {"高等数学", "线性代数", "概率统计"}
EXPECTED_QUESTION_TYPES = {"选择题", "填空题", "解答题"}


class ArchiveEngine:
    """Handles all file-system operations for the math problem vault.

    Responsibilities:
      - Directory auto-creation (subject/lecture/question_type)
      - MD rendering via Jinja2
      - MOC (_index.md) auto-updates at subject, lecture, and root levels
      - Asset image copying to assets/images/
      - Dedup detection via SHA256
    """

    def __init__(self, vault_root: str | Path = "./考研数学题库"):
        self.vault_root = Path(vault_root).resolve()
        self.assets_dir = self.vault_root / "assets" / "images"

    # ── Public API ──────────────────────────────────────────────────────────

    def archive(
        self,
        record: ProblemRecord,
        source_image: Optional[Path] = None,
    ) -> dict:
        """Archive a validated ProblemRecord to the vault.

        Args:
            record: Validated ProblemRecord from the LLM pipeline.
            source_image: Optional path to the original image (copied to assets/).

        Returns:
            Dict with keys: success, file_path, filename, errors, warnings.
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 1. Ensure directory structure
        try:
            target_dir = self._ensure_directories(record)
        except Exception as e:
            return {"success": False, "file_path": None, "filename": None,
                    "errors": [f"Directory creation failed: {e}"], "warnings": []}

        # 2. Generate filename
        meta_dict = record.model_dump(mode="json")["meta"]
        filename = generate_filename(meta_dict, record.problem)

        # 3. Dedup check
        target_path = target_dir / filename
        if target_path.exists():
            warnings.append(f"File already exists: {target_path}")

        # 4. Render MD content
        try:
            md_content = self._render_md(record)
        except Exception as e:
            return {"success": False, "file_path": None, "filename": filename,
                    "errors": [f"MD rendering failed: {e}"], "warnings": warnings}

        # 5. Write MD file
        target_path.write_text(md_content, encoding="utf-8")

        # 6. Copy source image
        if source_image and source_image.exists():
            self._save_asset(source_image)

        # 7. Update MOC indices
        try:
            self._update_mocs(record, filename)
        except Exception as e:
            warnings.append(f"MOC update failed: {e}")

        return {
            "success": True,
            "file_path": str(target_path),
            "filename": filename,
            "errors": errors,
            "warnings": warnings,
        }

    # ── Directory Management ─────────────────────────────────────────────────

    def _ensure_directories(self, record: ProblemRecord) -> Path:
        """Create subject/lecture/question_type dirs, return target directory."""
        subject = record.meta.subject.value
        lecture = record.meta.lecture
        qtype = record.meta.question_type.value

        target_dir = self.vault_root / subject / lecture / qtype
        target_dir.mkdir(parents=True, exist_ok=True)

        # Ensure _index.md files exist at each level
        self._ensure_index(self.vault_root, f"# 📚 考研数学题库 · 总索引\n")
        self._ensure_index(
            self.vault_root / subject,
            f"# {subject}\n\n```dataview\nTABLE question_type AS \"题型\"\nFROM \"{subject}\"\nSORT lecture ASC\n```\n",
        )
        self._ensure_index(
            self.vault_root / subject / lecture,
            f"# {lecture}\n\n```dataview\nTABLE question_type AS \"题型\"\nFROM \"{subject}/{lecture}\"\nSORT question_type ASC\n```\n",
        )

        # Ensure assets dir
        self.assets_dir.mkdir(parents=True, exist_ok=True)

        return target_dir

    def _ensure_index(self, directory: Path, default_content: str) -> None:
        """Create _index.md if it doesn't exist."""
        directory.mkdir(parents=True, exist_ok=True)
        index_file = directory / "_index.md"
        if not index_file.exists():
            index_file.write_text(default_content, encoding="utf-8")

    # ── MD Rendering ─────────────────────────────────────────────────────────

    def _render_md(self, record: ProblemRecord) -> str:
        """Render ProblemRecord to a complete Obsidian-compatible MD string."""
        template = _jinja_env.get_template("md_template.j2")
        meta = record.meta
        today = date.today().isoformat()

        # Build a clean summary (strip LaTeX, limit 100 chars)
        summary = self._clean_summary(record.solution.approach)

        # Build display title
        title = record.meta.source.example_id or "题目"

        # Use mode='json' so enums serialize to their Chinese values
        return template.render(
            meta=meta.model_dump(mode="json"),
            problem=record.problem,
            answer=record.answer,
            solution=record.solution.model_dump(),
            related=record.related.model_dump(),
            summary=summary,
            title=title,
            created=today,
            updated=today,
        )

    @staticmethod
    def _clean_summary(text: str, max_chars: int = 100) -> str:
        """Strip LaTeX and truncate to produce a clean Chinese summary."""
        # Remove LaTeX formulas
        cleaned = re.sub(r"\$\$?[^$]+\$\$?", "", text)
        cleaned = re.sub(r"\\[a-zA-Z]+(\{[^}]*\})*", "", cleaned)
        # Keep only Chinese + common punctuation
        chinese = re.findall(r"[一-鿿，。；：、！？]", cleaned)
        result = "".join(chinese)
        return result[:max_chars]

    # ── Delete ───────────────────────────────────────────────────────────────

    def delete_problem(self, record: ProblemRecord, filename: str) -> dict:
        """Delete an archived problem: .md file, referenced images, update _index.md.

        Args:
            record: The ProblemRecord whose meta identifies subject/lecture/qtype.
            filename: The .md filename to delete.

        Returns:
            Dict with keys: success, errors, warnings, deleted_md, deleted_images.
        """
        errors: list[str] = []
        warnings: list[str] = []
        deleted_images: list[str] = []

        subject = record.meta.subject.value
        lecture = record.meta.lecture
        qtype = record.meta.question_type.value

        target_dir = self.vault_root / subject / lecture / qtype
        md_path = target_dir / filename

        # 1. Parse image references from .md before deleting
        if md_path.exists():
            try:
                content = md_path.read_text(encoding="utf-8")
                # Match ![](assets/images/xxx.png) or ![alt](assets/images/xxx.png)
                img_pattern = re.compile(r'!\[.*?\]\(assets/images/([^)]+)\)')
                referenced = img_pattern.findall(content)
            except Exception as e:
                warnings.append(f"Could not read .md for image extraction: {e}")
                referenced = []
        else:
            warnings.append(f".md file not found: {md_path}")
            referenced = []

        # 2. Delete .md file
        try:
            if md_path.exists():
                md_path.unlink()
            else:
                errors.append(f"File not found: {md_path}")
        except Exception as e:
            errors.append(f"Failed to delete .md: {e}")
            return {"success": False, "errors": errors, "warnings": warnings,
                    "deleted_md": str(md_path), "deleted_images": deleted_images}

        # 3. Delete referenced images (best-effort)
        for img_name in referenced:
            img_path = self.assets_dir / img_name
            try:
                if img_path.exists():
                    img_path.unlink()
                    deleted_images.append(str(img_path))
            except Exception as e:
                warnings.append(f"Could not delete image {img_name}: {e}")

        # 4. Update _index.md — remove the link line
        try:
            lecture_index = self.vault_root / subject / lecture / "_index.md"
            if lecture_index.exists():
                content = lecture_index.read_text(encoding="utf-8")
                display_name = filename.replace(".md", "")
                # Match format used in _update_mocs: [[filename|display_name]]
                link_line = f"- [[{filename}|{display_name}]]"
                # Remove exact line (with optional trailing newline)
                content = content.replace(link_line + "\n", "")
                content = content.replace(link_line, "")
                lecture_index.write_text(content, encoding="utf-8")
        except Exception as e:
            warnings.append(f"Could not update _index.md: {e}")

        return {
            "success": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "deleted_md": str(md_path),
            "deleted_images": deleted_images,
        }

    def delete_by_path(self, relative_path: str) -> dict:
        """Delete a vault file by its path relative to vault_root.

        Path format: subject/lecture/question_type/filename.md

        This is used by the vault browser — no ProblemRecord needed.
        """
        errors: list[str] = []
        warnings: list[str] = []
        deleted_images: list[str] = []

        parts = relative_path.replace("\\", "/").split("/")
        if len(parts) != 4:
            return {"success": False, "errors": [f"Invalid path: {relative_path}"],
                    "warnings": [], "deleted_md": "", "deleted_images": []}

        subject, lecture, qtype, filename = parts
        md_path = self.vault_root / subject / lecture / qtype / filename

        # Security: ensure path is inside vault_root
        try:
            resolved = md_path.resolve()
            if not str(resolved).startswith(str(self.vault_root.resolve())):
                return {"success": False, "errors": ["Path traversal denied"],
                        "warnings": [], "deleted_md": "", "deleted_images": []}
        except Exception:
            return {"success": False, "errors": ["Invalid path"],
                    "warnings": [], "deleted_md": "", "deleted_images": []}

        # 1. Parse image references from .md before deleting
        if md_path.exists():
            try:
                content = md_path.read_text(encoding="utf-8")
                img_pattern = re.compile(r'!\[.*?\]\(assets/images/([^)]+)\)')
                referenced = img_pattern.findall(content)
            except Exception as e:
                warnings.append(f"Could not read .md: {e}")
                referenced = []
        else:
            return {"success": False, "errors": [f"File not found: {md_path}"],
                    "warnings": warnings, "deleted_md": str(md_path), "deleted_images": []}

        # 2. Delete .md file
        try:
            md_path.unlink()
        except Exception as e:
            errors.append(f"Failed to delete .md: {e}")
            return {"success": False, "errors": errors, "warnings": warnings,
                    "deleted_md": str(md_path), "deleted_images": deleted_images}

        # 3. Delete referenced images (best-effort)
        for img_name in referenced:
            img_path = self.assets_dir / img_name
            try:
                if img_path.exists():
                    img_path.unlink()
                    deleted_images.append(str(img_path))
            except Exception as e:
                warnings.append(f"Could not delete image {img_name}: {e}")

        # 4. Update _index.md — remove the link line
        try:
            lecture_index = self.vault_root / subject / lecture / "_index.md"
            if lecture_index.exists():
                content = lecture_index.read_text(encoding="utf-8")
                display_name = filename.replace(".md", "")
                link_line = f"- [[{filename}|{display_name}]]"
                content = content.replace(link_line + "\n", "")
                content = content.replace(link_line, "")
                lecture_index.write_text(content, encoding="utf-8")
        except Exception as e:
            warnings.append(f"Could not update _index.md: {e}")

        return {
            "success": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
            "deleted_md": str(md_path),
            "deleted_images": deleted_images,
        }

    # ── Vault Tree ───────────────────────────────────────────────────────────

    def get_vault_tree(self) -> dict:
        """Scan the vault directory and return a browsable tree.

        Returns a dict:
            {subject: {lecture: {question_type: [{filename, path, size}]}}}
        All .md files except _index.md are included.
        File sizes in bytes for display.
        """
        tree: dict = {}
        if not self.vault_root.exists():
            return tree

        for md_file in sorted(self.vault_root.rglob("*.md")):
            if md_file.name.startswith("_"):  # skip _index.md
                continue
            rel = md_file.relative_to(self.vault_root)
            parts = rel.parts
            # Expected: subject/lecture/question_type/filename.md
            if len(parts) != 4:
                continue
            subject, lecture, qtype, filename = parts
            entry = {
                "filename": filename,
                "path": str(rel),  # relative to vault_root
            }
            tree.setdefault(subject, {}) \
                .setdefault(lecture, {}) \
                .setdefault(qtype, []) \
                .append(entry)

        return tree

    # ── Asset Management ─────────────────────────────────────────────────────

    def _save_asset(self, source_path: Path) -> Path:
        """Copy an image to assets/images/ with a timestamped name."""
        import time
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        ext = source_path.suffix or ".png"
        dest_name = f"{timestamp}{ext}"
        dest_path = self.assets_dir / dest_name
        shutil.copy2(source_path, dest_path)
        return dest_path

    # ── MOC Management ───────────────────────────────────────────────────────

    def _update_mocs(self, record: ProblemRecord, filename: str) -> None:
        """Append a link to the new file in the lecture-level _index.md."""
        subject = record.meta.subject.value
        lecture = record.meta.lecture
        qtype = record.meta.question_type.value

        lecture_index = self.vault_root / subject / lecture / "_index.md"

        # Build the link entry
        display_name = filename.replace(".md", "")
        link_entry = f"- [[{filename}|{display_name}]]"

        # Append under the question_type heading if it exists
        content = lecture_index.read_text(encoding="utf-8")
        heading = f"## {qtype}"

        if heading in content:
            # Insert after the heading
            parts = content.split(heading, 1)
            content = f"{parts[0]}{heading}\n{link_entry}{parts[1]}"
        else:
            # Append heading + link
            content += f"\n\n{heading}\n{link_entry}\n"

        lecture_index.write_text(content, encoding="utf-8")
