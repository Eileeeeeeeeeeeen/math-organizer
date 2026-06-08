"""Tests for directory structure validation and deduplication."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.validators.directory_validator import validate_directory_structure
from src.validators.dedup import compute_problem_hash, check_duplicate, build_hash_index


class TestDirectoryValidator:
    """Test the directory structure validator."""

    def test_valid_temp_vault_passes(self, temp_vault):
        """The temp vault fixture should pass validation."""
        result = validate_directory_structure(temp_vault)
        assert result["valid"], f"Should be valid, got errors: {result['errors']}"

    def test_nonexistent_root_fails(self, tmp_path):
        """A nonexistent vault root should fail."""
        result = validate_directory_structure(tmp_path / "nonexistent")
        assert not result["valid"]

    def test_not_a_directory_fails(self, tmp_path):
        """A file instead of directory should fail."""
        file_path = tmp_path / "not_a_dir"
        file_path.write_text("hello")
        result = validate_directory_structure(file_path)
        assert not result["valid"]

    def test_detects_missing_subject(self, tmp_path):
        """Should error when a subject directory is missing."""
        root = tmp_path / "vault"
        root.mkdir()
        (root / "_index.md").write_text("# Test")
        # Missing all 3 subject dirs
        result = validate_directory_structure(root)
        assert not result["valid"]
        assert any("高等数学" in e or "线性代数" in e for e in result["errors"])

    def test_warns_missing_root_index(self, tmp_path):
        """Should warn when root _index.md is missing."""
        root = tmp_path / "vault"
        root.mkdir()
        # No _index.md
        for subject in ["高等数学", "线性代数", "概率统计"]:
            (root / subject).mkdir()
        result = validate_directory_structure(root)
        # Subjects exist but no _index.md — should still be valid with warnings
        assert len(result["warnings"]) > 0
        assert any("_index.md" in w for w in result["warnings"])

    def test_warns_missing_lecture_index(self, temp_vault):
        """Should warn when a lecture _index.md is missing."""
        # Remove lecture _index.md
        lecture_index = temp_vault / "高等数学" / "第1讲_函数极限与连续" / "_index.md"
        lecture_index.unlink()
        result = validate_directory_structure(temp_vault)
        assert len(result["warnings"]) > 0
        assert any("_index.md" in w for w in result["warnings"])

    def test_warns_unexpected_subdirs(self, temp_vault):
        """Should warn about unexpected subdirectories in lecture dir."""
        lecture_dir = temp_vault / "高等数学" / "第1讲_函数极限与连续"
        (lecture_dir / "问答题").mkdir()
        result = validate_directory_structure(temp_vault)
        assert len(result["warnings"]) > 0
        assert any("问答题" in w for w in result["warnings"])


class TestDedup:
    """Test deduplication utilities."""

    def test_compute_hash_deterministic(self):
        """Same input should produce same hash."""
        h1 = compute_problem_hash("设函数 f(x) 在 x=0 处连续")
        h2 = compute_problem_hash("设函数 f(x) 在 x=0 处连续")
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex digest

    def test_compute_hash_different_inputs(self):
        """Different inputs should produce different hashes."""
        h1 = compute_problem_hash("题目A")
        h2 = compute_problem_hash("题目B")
        assert h1 != h2

    def test_compute_hash_normalizes_whitespace(self):
        """Extra whitespace should not affect hash."""
        h1 = compute_problem_hash("设函数  f(x)  在 x=0 处连续")
        h2 = compute_problem_hash("设函数 f(x) 在 x=0 处连续")
        assert h1 == h2

    def test_check_duplicate_empty_dir(self, tmp_path):
        """An empty directory should have no duplicates."""
        result = check_duplicate("some problem text", tmp_path)
        assert not result["is_duplicate"]
        assert result["hash"] is not None

    def test_check_duplicate_with_known_hashes(self):
        """Should detect duplicates via known_hashes dict."""
        problem = "设函数 f(x) 在 x=0 处连续"
        target_hash = compute_problem_hash(problem)
        known = {"file1.md": target_hash, "file2.md": "other_hash"}
        result = check_duplicate(problem, Path("/fake"), known_hashes=known)
        assert result["is_duplicate"]
        assert "file1.md" in result["matching_files"]

    def test_check_duplicate_no_match_with_known_hashes(self):
        """Should not flag non-matching hashes."""
        problem = "新题目"
        known = {"file1.md": "abc123", "file2.md": "def456"}
        result = check_duplicate(problem, Path("/fake"), known_hashes=known)
        assert not result["is_duplicate"]

    def test_build_hash_index(self, tmp_path):
        """Should build a hash index of MD files."""
        (tmp_path / "problem1.md").write_text("题目一的内容", encoding="utf-8")
        (tmp_path / "problem2.md").write_text("题目二的内容", encoding="utf-8")
        index = build_hash_index(tmp_path)
        assert len(index) == 2
        assert "problem1.md" in index
        assert "problem2.md" in index
