"""Integration tests — end-to-end validation of the full regulation layer."""

from __future__ import annotations

import json

import pytest


class TestConfigIntegration:
    """Test that all config files load and cross-validate correctly."""

    def test_settings_load(self, settings):
        """Settings should load with correct structure."""
        assert settings.ocr.provider == "paddleocr_vl"
        assert settings.llm.provider == "deepseek"
        assert settings.llm.temperature == 0.1

    def test_knowledge_tree_load(self, knowledge_tree):
        """Knowledge tree should pass all validations."""
        from src.validators.knowledge_tree import validate_knowledge_tree
        result = validate_knowledge_tree()
        assert result["valid"], f"Knowledge tree invalid: {result['errors']}"

    def test_opd_markers_load(self, opd_markers):
        """OPD markers should pass all validations."""
        from src.validators.opd_validator import validate_opd_markers, clear_cache
        clear_cache()
        result = validate_opd_markers()
        assert result["valid"], f"OPD markers invalid: {result['errors']}"

    def test_all_configs_consistent(self, knowledge_tree, opd_markers):
        """Cross-validate: OPD targets should reference real math topics."""
        o_codes = set(opd_markers["O"])

        # Check that O codes are reasonable — they should map to real math topics
        # At minimum, we should have the expected set of core topics
        core_topics = {
            "O_极限", "O_导数", "O_微分方程", "O_矩阵",
            "O_参数估计", "O_随机事件与概率",
        }
        missing = core_topics - o_codes
        assert not missing, f"Core OPD topics missing: {missing}"


class TestJsonSchemaIntegration:
    """Test that the JSON Schema and Pydantic models are consistent."""

    def test_valid_json_matches_pydantic(self, valid_problem_json):
        """The valid_problem.json fixture should parse as ProblemRecord."""
        from src.models import ProblemRecord
        record = ProblemRecord(**valid_problem_json)
        assert record.meta.subject.value == "高等数学"

    def test_missing_field_json_fails(self, test_data_dir):
        """Invalid JSON should fail Pydantic validation."""
        from src.models import ProblemRecord
        from pydantic import ValidationError

        with open(test_data_dir / "invalid_missing_field.json", "r") as f:
            data = json.load(f)

        with pytest.raises(ValidationError):
            ProblemRecord(**data)

    def test_bad_enum_json_fails(self, test_data_dir):
        """Invalid enum values should fail Pydantic validation."""
        from src.models import ProblemRecord
        from pydantic import ValidationError

        with open(test_data_dir / "invalid_bad_enum.json", "r") as f:
            data = json.load(f)

        with pytest.raises(ValidationError):
            ProblemRecord(**data)


class TestFrontmatterIntegration:
    """Test full frontmatter flow: parse → validate → cross-check."""

    def test_valid_frontmatter_full_flow(self, valid_md_content, config_dir):
        """Valid frontmatter should pass parse + validate + OPD cross-check."""
        from src.validators.frontmatter_validator import validate_frontmatter

        result = validate_frontmatter(valid_md_content, config_dir)
        assert result["valid"], f"Full flow failed: {result['errors']}"

        # Verify parsed data
        assert result["data"]["subject"] == "高等数学"
        assert result["data"]["opd_target"] == "O_极限"
        assert "P11_正向思路" in result["data"]["opd_procedures"]

    def test_invalid_opd_frontmatter_fails(self, test_data_dir, config_dir):
        """Frontmatter with invalid OPD codes should fail."""
        from src.validators.frontmatter_validator import validate_frontmatter

        content = (test_data_dir / "invalid_frontmatter_bad_opd.md").read_text("utf-8")
        result = validate_frontmatter(content, config_dir)
        assert not result["valid"]

    def test_invalid_summary_frontmatter_fails(self, test_data_dir, config_dir):
        """Frontmatter with invalid summary should fail."""
        from src.validators.frontmatter_validator import validate_frontmatter

        content = (test_data_dir / "invalid_frontmatter_bad_summary.md").read_text("utf-8")
        result = validate_frontmatter(content, config_dir)
        assert not result["valid"]


class TestNamingIntegration:
    """Test that naming conventions align with knowledge tree."""

    def test_all_valid_filenames_from_fixtures(self, knowledge_tree):
        """Test a representative set of valid filenames."""
        from src.validators.naming_validator import validate_filename

        valid_names = [
            "第1讲_选择题_例1-3_间断点个数判定.md",
            "第5讲_解答题_例5-8_中值定理证明不等式.md",
            "第13讲_填空题_例13-2_二元函数全微分.md",
            "第9讲_解答题_例9-15_二次型正定判定.md",
        ]
        for name in valid_names:
            result = validate_filename(name, knowledge_tree)
            assert result["valid"], f"'{name}' should be valid: {result['errors']}"

    def test_invalid_filenames_rejected(self):
        """Test that invalid filenames are rejected."""
        from src.validators.naming_validator import validate_filename

        invalid_names = [
            "1讲_选择题_例1_间断点.md",           # Missing 第
            "第1讲_问答题_例1_间断点.md",          # Wrong type
            "test.md",                            # Completely wrong
            "第1讲_选择题_例1_$latex$.md",         # LaTeX in desc
        ]
        for name in invalid_names:
            result = validate_filename(name)
            assert not result["valid"], f"'{name}' should be invalid"


class TestEndToEnd:
    """Full end-to-end test: a single problem flows through all validators."""

    def test_complete_flow(self, valid_problem_json, valid_md_content, config_dir, temp_vault):
        """Simulate the full processing pipeline for one problem."""
        from src.models import ProblemRecord
        from src.validators.frontmatter_validator import validate_frontmatter
        from src.validators.naming_validator import generate_filename, validate_filename
        from src.validators.dedup import compute_problem_hash, check_duplicate
        from src.validators.directory_validator import validate_directory_structure

        # 1. Validate LLM JSON output
        record = ProblemRecord(**valid_problem_json)
        assert record.meta.subject.value == "高等数学"

        # 2. Validate vault directory structure
        dir_result = validate_directory_structure(temp_vault)
        assert dir_result["valid"], f"Directory invalid: {dir_result['errors']}"

        # 3. Generate a compliant filename
        meta_dict = valid_problem_json["meta"]
        filename = generate_filename(meta_dict, valid_problem_json["problem"])
        assert filename.endswith(".md")

        # 4. Validate the generated filename
        name_result = validate_filename(filename)
        assert name_result["valid"], f"Generated filename invalid: {name_result['errors']}"

        # 5. Compute hash for dedup
        problem_hash = compute_problem_hash(valid_problem_json["problem"])
        assert len(problem_hash) == 64

        # 6. Validate frontmatter of the final MD
        fm_result = validate_frontmatter(valid_md_content, config_dir)
        assert fm_result["valid"], f"Frontmatter invalid: {fm_result['errors']}"
