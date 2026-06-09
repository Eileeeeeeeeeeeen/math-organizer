"""Shared pytest fixtures for math-organizer tests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

# Project root for resolving config paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
TEST_DATA_DIR = Path(__file__).resolve().parent / "data"


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def config_dir() -> Path:
    """Return the config directory."""
    return CONFIG_DIR


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Return the test data directory."""
    return TEST_DATA_DIR


@pytest.fixture(scope="session")
def settings(config_dir):
    """Load and return validated settings."""
    from src.config import load_settings
    return load_settings(config_dir)


@pytest.fixture(scope="session")
def knowledge_tree(config_dir):
    """Load and return the validated knowledge tree."""
    from src.config import load_knowledge_tree
    return load_knowledge_tree(config_dir)


@pytest.fixture(scope="session")
def opd_markers(config_dir):
    """Load and return the validated OPD markers."""
    from src.config import load_opd_markers
    return load_opd_markers(config_dir)


@pytest.fixture
def valid_problem_json(test_data_dir):
    """Load the valid problem JSON fixture."""
    with open(test_data_dir / "valid_problem.json", "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def valid_md_content(test_data_dir):
    """Load the valid frontmatter MD fixture."""
    return (test_data_dir / "valid_frontmatter.md").read_text(encoding="utf-8")


@pytest.fixture
def temp_vault():
    """Create a temporary vault directory structure matching 考研数学题库.

    Cleans up after the test.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Create structure from SubjectConfig
        from src.config import load_subject_config
        cfg = load_subject_config()
        (root / "_index.md").write_text("# Test Vault", encoding="utf-8")
        (root / "assets" / "images").mkdir(parents=True)

        first_subject = cfg.categories[0] if cfg.categories else "默认科目"
        for subject in cfg.categories:
            subject_dir = root / subject
            subject_dir.mkdir()
            (subject_dir / "_index.md").write_text(f"# {subject}", encoding="utf-8")

            # Create one lecture with question type dirs for the first subject
            if subject == first_subject:
                lecture_dir = subject_dir / "第1讲_函数极限与连续"
                lecture_dir.mkdir()
                (lecture_dir / "_index.md").write_text("# 第1讲", encoding="utf-8")
                for qtype in cfg.question_types:
                    (lecture_dir / qtype).mkdir()

        yield root
