"""Tests for pipeline orchestration and archive engine."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from src.archive import ArchiveEngine
from src.models import (
    ProblemRecord, Meta, Solution, Related, OpdMarkers, Source,
)
from src.validators.dedup import compute_problem_hash


@pytest.fixture
def sample_record() -> ProblemRecord:
    """A valid ProblemRecord for testing archive."""
    return ProblemRecord(
        meta=Meta(
            subject="高等数学",
            lecture="第1讲_函数极限与连续",
            question_type="选择题",
            source=Source(
                book="考研数学基础教程",
                year="2026",
                example_id="例1.3",
            ),
            opd=OpdMarkers(
                target="O_极限",
                procedures=["P11_正向思路"],
                details=["D22_转换等价表述"],
            ),
            key_ability=["概念辨析", "计算能力"],
            tags=["函数极限", "无穷小比较"],
        ),
        problem=r"设函数 $f(x) = x^2\sin\frac{1}{x}$，讨论 $f(x)$ 在 $x=0$ 处的连续性与可导性。",
        answer=r"$f(x)$ 在 $x=0$ 处连续且可导，且 $f'(0) = 0$。",
        solution=Solution(
            approach="利用夹逼准则证明连续性，利用导数定义判定可导性。",
            key_insight="分段函数在分段点处必须用导数定义判定可导性",
            steps=[
                "第一步：证明连续性",
                "第二步：利用导数定义证明可导性",
            ],
        ),
        related=Related(
            knowledge_points=["函数极限的定义与性质", "连续与间断的判定"],
            linked_examples=["例1.1"],
        ),
    )


class TestArchiveEngine:
    """Test the ArchiveEngine file-system operations."""

    def test_archive_creates_directories(self, sample_record, tmp_path):
        """Archiving should create the full directory tree."""
        engine = ArchiveEngine(vault_root=str(tmp_path))
        result = engine.archive(sample_record)

        assert result["success"], f"Archive failed: {result['errors']}"
        assert result["file_path"] is not None
        assert Path(result["file_path"]).exists()

        # Verify directory structure
        assert (tmp_path / "高等数学").exists()
        assert (tmp_path / "高等数学" / "第1讲_函数极限与连续").exists()
        assert (tmp_path / "高等数学" / "第1讲_函数极限与连续" / "选择题").exists()
        assert (tmp_path / "assets" / "images").exists()

    def test_archive_creates_index_files(self, sample_record, tmp_path):
        """Archiving should create _index.md files at each level."""
        engine = ArchiveEngine(vault_root=str(tmp_path))
        engine.archive(sample_record)

        assert (tmp_path / "_index.md").exists()
        assert (tmp_path / "高等数学" / "_index.md").exists()
        lecture_index = tmp_path / "高等数学" / "第1讲_函数极限与连续" / "_index.md"
        assert lecture_index.exists()

        # Lecture index should contain the archived file link
        content = lecture_index.read_text(encoding="utf-8")
        assert "选择题" in content

    def test_archive_md_file_is_valid(self, sample_record, tmp_path):
        """The generated MD file should have valid frontmatter."""
        engine = ArchiveEngine(vault_root=str(tmp_path))
        result = engine.archive(sample_record)

        md_path = Path(result["file_path"])
        content = md_path.read_text(encoding="utf-8")

        # Check frontmatter
        assert content.startswith("---")
        assert "subject: 高等数学" in content
        assert "## ❓ 题目" in content
        assert "## ✅ 答案" in content
        assert "## 📝 解题思路" in content
        assert "## 🔍 解题过程" in content
        assert "## 🔗 相关知识点" in content

    def test_archive_dedup_detection(self, sample_record, tmp_path):
        """Archiving the same record twice should warn about existing file."""
        engine = ArchiveEngine(vault_root=str(tmp_path))
        engine.archive(sample_record)
        result2 = engine.archive(sample_record)

        assert result2["success"]  # Still succeeds
        assert any("already exists" in w.lower() for w in result2["warnings"])

    def test_archive_with_source_image(self, sample_record, tmp_path):
        """Archiving with a source image should copy it to assets/."""
        # Create a fake source image
        source_img = tmp_path / "source.png"
        source_img.write_bytes(b"fake png data")

        engine = ArchiveEngine(vault_root=str(tmp_path))
        result = engine.archive(sample_record, source_image=source_img)

        assert result["success"]
        # Should have copied the image
        assets = list((tmp_path / "assets" / "images").glob("*.png"))
        assert len(assets) >= 1

    def test_clean_summary_strips_latex(self):
        """The _clean_summary method should strip LaTeX from text."""
        text = r"考察 $\lim_{x\to 0} \frac{\sin x}{x} = 1$ 的应用"
        cleaned = ArchiveEngine._clean_summary(text, max_chars=100)
        assert "$" not in cleaned
        assert "\\lim" not in cleaned
        assert "考察" in cleaned
        assert "的应用" in cleaned


class TestPipelineSmoke:
    """Smoke tests for the Pipeline class (without API calls)."""

    def test_pipeline_init(self):
        """Pipeline should initialize with settings."""
        from src.pipeline import Pipeline
        p = Pipeline()
        assert p.settings is not None
        assert p.archive_engine is not None
        assert p.archive_engine.vault_root.name == "考研数学题库"

    def test_pipeline_run_full_with_text_no_api(self, sample_record, tmp_path):
        """run_full with text input should skip OCR and archive successfully."""
        from src.pipeline import Pipeline
        import types

        p = Pipeline()
        # Mock the LLM call by replacing the bound method
        p.run_llm = types.MethodType(lambda self, text: sample_record, p)
        p._archive = ArchiveEngine(vault_root=str(tmp_path))

        result = p.run_full(
            image_path=Path("/nonexistent.png"),
            text_input="test problem text",
        )
        assert result["success"], f"Errors: {result['errors']}"
        assert result["record"] is not None
