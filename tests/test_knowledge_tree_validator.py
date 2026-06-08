"""Tests for knowledge tree validation (config & validators)."""

from __future__ import annotations

import pytest

from src.config import load_knowledge_tree
from src.validators.knowledge_tree import validate_knowledge_tree


class TestKnowledgeTreeLoading:
    """Test that the real knowledge_tree.yml loads correctly."""

    def test_loads_without_error(self, config_dir):
        """The config knowledge_tree.yml should load and validate."""
        tree = load_knowledge_tree(config_dir)
        assert tree is not None
        assert len(tree) == 3

    def test_has_three_subjects(self, knowledge_tree):
        """Must have exactly 高等数学, 线性代数, 概率统计."""
        assert set(knowledge_tree.keys()) == {"高等数学", "线性代数", "概率统计"}

    def test_all_lecture_names_match_pattern(self, knowledge_tree):
        """Every lecture name must start with 第N讲_."""
        for subject, lectures in knowledge_tree.items():
            for lecture_name in lectures:
                assert lecture_name.startswith("第"), \
                    f"Lecture '{lecture_name}' in {subject} doesn't start with 第"
                assert "讲" in lecture_name, \
                    f"Lecture '{lecture_name}' in {subject} doesn't contain 讲"
                assert "_" in lecture_name, \
                    f"Lecture '{lecture_name}' in {subject} missing _ separator"

    def test_no_empty_knowledge_points(self, knowledge_tree):
        """No knowledge point should be empty or whitespace-only."""
        for subject, lectures in knowledge_tree.items():
            for lecture_name, points in lectures.items():
                for i, point in enumerate(points):
                    assert isinstance(point, str), \
                        f"Point {i} in {subject}/{lecture_name} is not a string"
                    assert point.strip(), \
                        f"Point {i} in {subject}/{lecture_name} is empty"

    def test_lecture_counts(self, knowledge_tree):
        """Verify lecture counts per subject."""
        gao_shu_lectures = len(knowledge_tree["高等数学"])
        xian_dai_lectures = len(knowledge_tree["线性代数"])
        gai_lv_lectures = len(knowledge_tree["概率统计"])

        assert gao_shu_lectures == 18, f"Expected 18 高等数学 lectures, got {gao_shu_lectures}"
        assert xian_dai_lectures == 9, f"Expected 9 线性代数 lectures, got {xian_dai_lectures}"
        assert gai_lv_lectures == 9, f"Expected 9 概率统计 lectures, got {gai_lv_lectures}"

    def test_no_duplicate_lecture_names_across_subjects(self, knowledge_tree):
        """Lecture names should not be duplicated across different subjects."""
        all_names: list[tuple[str, str]] = []
        for subject, lectures in knowledge_tree.items():
            for name in lectures:
                all_names.append((name, subject))

        names_by_subject: dict[str, list[str]] = {}
        for name, subject in all_names:
            names_by_subject.setdefault(name, []).append(subject)

        duplicates = {n: s for n, s in names_by_subject.items() if len(s) > 1}
        assert not duplicates, f"Duplicate lecture names across subjects: {duplicates}"


class TestValidateKnowledgeTree:
    """Test the validator function."""

    def test_validate_real_tree_passes(self, config_dir):
        """The real knowledge tree should pass validation."""
        result = validate_knowledge_tree(config_dir)
        assert result["valid"], f"Validation failed: {result['errors']}"
        assert result["lecture_count"] == 36
        assert result["point_count"] > 0

    def test_validate_nonexistent_file(self, tmp_path):
        """A nonexistent file should return invalid."""
        result = validate_knowledge_tree(tmp_path)
        assert not result["valid"]
        assert len(result["errors"]) > 0
