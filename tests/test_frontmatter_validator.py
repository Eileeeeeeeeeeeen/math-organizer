"""Tests for frontmatter validation."""

from __future__ import annotations

import pytest

from src.validators.frontmatter_validator import validate_frontmatter, parse_frontmatter


class TestParseFrontmatter:
    """Test YAML frontmatter extraction."""

    def test_parses_valid_frontmatter(self, valid_md_content):
        """Should extract frontmatter from valid MD content."""
        data, errors = parse_frontmatter(valid_md_content)
        assert errors == [], f"Parse errors: {errors}"
        assert data is not None
        assert data["subject"] == "高等数学"
        assert data["opd_target"] == "O_极限"

    def test_no_frontmatter_returns_error(self):
        content = "# Just a title\n\nNo frontmatter here."
        data, errors = parse_frontmatter(content)
        assert data is None
        assert len(errors) > 0

    def test_empty_frontmatter_returns_error(self):
        content = "---\n---\n\n# Title"
        data, errors = parse_frontmatter(content)
        assert data is None
        assert len(errors) > 0

    def test_invalid_yaml_returns_error(self):
        content = "---\nsubject: [unclosed\n---\n\n# Title"
        data, errors = parse_frontmatter(content)
        assert data is None
        assert len(errors) > 0


class TestValidateFrontmatter:
    """Test full frontmatter validation."""

    def test_valid_frontmatter_passes(self, valid_md_content, config_dir):
        """A valid frontmatter should pass all checks."""
        result = validate_frontmatter(valid_md_content, config_dir)
        assert result["valid"], f"Should be valid, got errors: {result['errors']}"

    def test_invalid_opd_target(self, test_data_dir, config_dir):
        """Invalid OPD target should be detected."""
        content = (test_data_dir / "invalid_frontmatter_bad_opd.md").read_text("utf-8")
        result = validate_frontmatter(content, config_dir)
        assert not result["valid"]
        assert any("OPD target" in e for e in result["errors"])

    def test_invalid_opd_procedure(self, test_data_dir, config_dir):
        """Invalid OPD procedure should be detected."""
        content = (test_data_dir / "invalid_frontmatter_bad_opd.md").read_text("utf-8")
        result = validate_frontmatter(content, config_dir)
        assert any("OPD procedure" in e for e in result["errors"])

    def test_invalid_summary_with_latex(self, test_data_dir, config_dir):
        """Summary containing LaTeX should be detected."""
        content = (test_data_dir / "invalid_frontmatter_bad_summary.md").read_text("utf-8")
        result = validate_frontmatter(content, config_dir)
        assert not result["valid"]
        assert any("LaTeX" in e or "long" in e for e in result["errors"])

    def test_invalid_summary_too_long(self, test_data_dir, config_dir):
        """Summary > 100 chars should be detected."""
        content = (test_data_dir / "invalid_frontmatter_bad_summary.md").read_text("utf-8")
        result = validate_frontmatter(content, config_dir)
        assert any("long" in e or "100" in e for e in result["errors"])

    def test_missing_required_field(self, config_dir):
        """Missing required frontmatter field should be detected."""
        content = """---
subject: 高等数学
lecture: 第1讲_函数极限与连续
---

# Just a title
"""
        result = validate_frontmatter(content, config_dir)
        assert not result["valid"]
        assert any("question_type" in e for e in result["errors"])

    def test_invalid_enum_value(self, config_dir):
        """Invalid enum value should be detected."""
        content = """---
subject: 高等化学
lecture: 第1讲_函数极限与连续
question_type: 选择题
opd_target: O_极限
opd_procedures: []
opd_details: []
key_ability: []
source_book: test
source_example: test
tags: []
summary: 测试摘要
created: 2026-01-01
---

# Test
"""
        result = validate_frontmatter(content, config_dir)
        assert not result["valid"]
        assert any("subject" in e for e in result["errors"])

    def test_invalid_date_format(self, config_dir):
        """Invalid date format should be detected."""
        content = """---
subject: 高等数学
lecture: 第1讲_函数极限与连续
question_type: 选择题
opd_target: O_极限
opd_procedures: []
opd_details: []
key_ability: []
source_book: test
source_example: test
tags: []
summary: 测试摘要
created: not-a-date
---

# Test
"""
        result = validate_frontmatter(content, config_dir)
        assert not result["valid"]
        assert any("date" in e.lower() for e in result["errors"])
