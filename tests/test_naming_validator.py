"""Tests for file naming convention validation."""

from __future__ import annotations

import pytest

from src.validators.naming_validator import validate_filename, generate_filename


class TestValidateFilename:
    """Test the validate_filename function."""

    # ── Valid cases ──

    def test_valid_choice_question(self):
        result = validate_filename("第1讲_选择题_例1-3_间断点个数判定.md")
        assert result["valid"], f"Should be valid, got errors: {result['errors']}"
        assert result["parsed"]["lecture_num"] == "第1讲"
        assert result["parsed"]["question_type"] == "选择题"
        assert result["parsed"]["example_id"] == "例1-3"
        assert result["parsed"]["short_description"] == "间断点个数判定"

    def test_valid_fill_in_question(self):
        result = validate_filename("第5讲_填空题_例5-2_定积分计算.md")
        assert result["valid"], f"Should be valid, got errors: {result['errors']}"

    def test_valid_proof_question(self):
        result = validate_filename("第13讲_解答题_例13-8_中值定理证明.md")
        assert result["valid"], f"Should be valid, got errors: {result['errors']}"

    def test_valid_with_hyphen_in_example_id(self):
        result = validate_filename("第9讲_解答题_例9-15_二次型正定判定.md")
        assert result["valid"], f"Should be valid, got errors: {result['errors']}"

    def test_valid_with_path_prefix(self):
        """Filename validation strips directory paths."""
        result = validate_filename(
            "高等数学/第1讲_函数极限与连续/选择题/第1讲_选择题_例1-3_间断点个数判定.md"
        )
        assert result["valid"], f"Should be valid with path prefix, got errors: {result['errors']}"

    def test_valid_minimal_description(self):
        """A single character description should be valid."""
        result = validate_filename("第1讲_选择题_例1-1_题.md")
        assert result["valid"], f"Should be valid: {result['errors']}"

    def test_valid_max_description_15_chars(self):
        """A 15-character description should be valid."""
        result = validate_filename("第1讲_选择题_例1-1_一二三四五六七八九十一二三四五.md")
        assert result["valid"], f"Should be valid: {result['errors']}"

    # ── Invalid cases ──

    def test_invalid_wrong_extension(self):
        result = validate_filename("第1讲_选择题_例1-3_间断点.txt")
        assert not result["valid"]

    def test_invalid_no_md_extension(self):
        result = validate_filename("第1讲_选择题_例1-3_间断点")
        assert not result["valid"]

    def test_invalid_wrong_type(self):
        result = validate_filename("第1讲_问答题_例1-3_间断点个数判定.md")
        assert not result["valid"]

    def test_invalid_latex_in_description(self):
        result = validate_filename("第1讲_选择题_例1-3_含$x$的判定.md")
        assert not result["valid"]
        assert any("LaTeX" in e for e in result["errors"])

    def test_invalid_description_too_long(self):
        """A description longer than 15 chars should fail."""
        result = validate_filename("第1讲_选择题_例1-3_这是一个超过十五个字的超长描述内容.md")
        assert not result["valid"]

    def test_invalid_wrong_lecture_format(self):
        result = validate_filename("Chapter1_选择题_例1-3_间断点.md")
        assert not result["valid"]

    # ── Knowledge tree cross-validation ──

    def test_warns_when_lecture_not_in_tree(self, knowledge_tree):
        """Should warn (not error) when lecture number not in knowledge tree."""
        result = validate_filename("第99讲_选择题_例99-1_未知讲次.md", knowledge_tree)
        assert result["valid"]  # Still valid as a filename
        assert len(result["warnings"]) > 0  # But warns

    def test_no_warning_when_lecture_in_tree(self, knowledge_tree):
        """Should not warn when lecture number exists in knowledge tree."""
        result = validate_filename("第1讲_选择题_例1-3_间断点判定.md", knowledge_tree)
        assert result["valid"]
        # 第1讲_ should match 第1讲_函数极限与连续 in knowledge tree
        assert len(result["warnings"]) == 0


class TestGenerateFilename:
    """Test the generate_filename function."""

    def test_generates_correct_format(self):
        meta = {
            "lecture": "第1讲_函数极限与连续",
            "question_type": "选择题",
            "source": {"example_id": "例1.3"},
        }
        filename = generate_filename(meta, "设函数 f(x) 在 x=0 处的连续性与可导性")
        assert filename.startswith("第1讲_选择题_例1.3_")
        assert filename.endswith(".md")

    def test_extracts_chinese_description(self):
        meta = {
            "lecture": "第5讲_导数的应用",
            "question_type": "解答题",
            "source": {"example_id": "例5-8"},
        }
        filename = generate_filename(meta, "证明不等式：对于任意x>0，有ln(1+x)<x")
        # Should extract Chinese: 证明不等式对于任意有
        assert "证明不等式对于任意有" in filename

    def test_fallback_when_no_chinese(self):
        meta = {
            "lecture": "第3讲_导数与微分",
            "question_type": "填空题",
            "source": {"example_id": "例3.1"},
        }
        filename = generate_filename(meta, "Calculate d/dx sin(x^2)")
        assert filename.endswith(".md")
        # Should not error even with no Chinese characters
