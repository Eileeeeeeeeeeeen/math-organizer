"""Tests for Pydantic models in src/models.py."""

from __future__ import annotations

import json
from datetime import date

import pytest
from pydantic import ValidationError

from src.models import (
    ProblemRecord,
    Frontmatter,
    Meta,
    Solution,
    OpdMarkers,
    Source,
    Settings,
)


class TestProblemRecord:
    """Tests for the ProblemRecord model (LLM JSON output)."""

    def test_valid_record_passes(self, valid_problem_json):
        """A complete valid JSON should parse without errors."""
        record = ProblemRecord(**valid_problem_json)
        assert record.meta.subject == "高等数学"
        assert record.meta.lecture == "第1讲_函数极限与连续"
        assert record.meta.question_type == "解答题"
        assert record.meta.opd.target == "O_极限"
        assert len(record.solution.steps) == 3

    def test_missing_required_field_raises(self, valid_problem_json):
        """Missing required fields should raise ValidationError."""
        data = valid_problem_json.copy()
        del data["problem"]
        with pytest.raises(ValidationError):
            ProblemRecord(**data)

    def test_lecture_empty_raises(self):
        """Empty lecture should raise ValidationError (min_length=1)."""
        with pytest.raises(ValidationError):
            Meta(
                subject="高等数学",
                lecture="",  # empty string violates min_length
                question_type="解答题",
            )

    def test_approach_long_accepted(self):
        """Approach exceeding 200 chars should be accepted (no hard cap)."""
        s = Solution(approach="x" * 300, steps=["step1"])
        assert len(s.approach) == 300


class TestFrontmatter:
    """Tests for the Frontmatter model (MD YAML frontmatter)."""

    def test_valid_frontmatter_passes(self):
        """A well-formed Frontmatter should parse without errors."""
        fm = Frontmatter(
            subject="高等数学",
            lecture="第1讲_函数极限与连续",
            question_type="选择题",
            opd_target="O_极限",
            opd_procedures=["P11_正向思路"],
            opd_details=["D22_转换等价表述"],
            key_ability=["概念辨析", "计算能力"],
            source_book="考研数学基础教程",
            source_example="例1.3",
            tags=["函数极限"],
            summary="考察分段函数在分段点处的连续性与可导性判定",
            created=date(2026, 1, 15),
        )
        assert fm.subject == "高等数学"

    def test_summary_too_long_raises(self):
        """Summary > 100 chars should raise ValidationError."""
        with pytest.raises(ValidationError):
            Frontmatter(
                subject="高等数学",
                lecture="第1讲_函数极限与连续",
                question_type="选择题",
                opd_target="O_极限",
                summary="这是一个超过了规定字数限制的超长摘要内容" * 10,  # way over 100
            )

    def test_invalid_opd_target_pattern_raises(self):
        """opd_target not matching O_ pattern should raise ValidationError."""
        with pytest.raises(ValidationError):
            Frontmatter(
                subject="高等数学",
                lecture="第1讲_函数极限与连续",
                question_type="选择题",
                opd_target="invalid_target",  # doesn't start with O_
            )


class TestSettings:
    """Tests for the Settings config model."""

    def test_default_settings_parse(self):
        """Default settings with minimal values should parse."""
        s = Settings()
        assert s.ocr.provider == "paddleocr_vl"
        assert s.llm.temperature == 0.1
        assert s.gui.port == 7860
