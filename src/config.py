"""Configuration loader — reads and validates YAML config files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.models import Settings, SubjectConfig

# Default paths relative to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_DIR = PROJECT_ROOT / "config"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict if it doesn't exist."""
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"Config file is empty: {path}")
    return data


# ── Subject config (new — replaces hard-coded enums) ──────────────────────────

_subject_config: SubjectConfig | None = None


def load_subject_config(config_dir: Path | None = None) -> SubjectConfig:
    """Load subject.yml and return a validated SubjectConfig.

    The result is cached so repeated calls don't re-read the file.
    Use invalidate_subject_cache() to force a reload.

    Args:
        config_dir: Path to the config directory. Defaults to PROJECT_ROOT/config.

    Returns:
        A validated SubjectConfig instance.

    Raises:
        FileNotFoundError: If config/subject.yml doesn't exist.
        ValidationError: If the YAML doesn't match the SubjectConfig schema.
    """
    global _subject_config
    if _subject_config is not None and config_dir is None:
        return _subject_config

    if config_dir is None:
        config_dir = DEFAULT_CONFIG_DIR

    raw = _load_yaml(config_dir / "subject.yml")
    subject_data = raw.get("subject", raw)
    _subject_config = SubjectConfig(**subject_data)
    return _subject_config


def invalidate_subject_cache() -> None:
    """Clear the cached SubjectConfig so load_subject_config() re-reads the file."""
    global _subject_config
    _subject_config = None


# ── Settings ──────────────────────────────────────────────────────────────────


def load_settings(config_dir: Path | None = None) -> Settings:
    """Load settings.yml and validate against the Settings model.

    Args:
        config_dir: Path to the config directory. Defaults to PROJECT_ROOT/config.

    Returns:
        A validated Settings instance.

    Raises:
        FileNotFoundError: If settings.yml doesn't exist.
        ValidationError: If the YAML doesn't match the Settings schema.
    """
    if config_dir is None:
        config_dir = DEFAULT_CONFIG_DIR
    data = _load_yaml(config_dir / "settings.yml")
    return Settings(**data)


# ── Knowledge tree ────────────────────────────────────────────────────────────


def load_knowledge_tree(config_dir: Path | None = None) -> dict[str, dict[str, list[str]]]:
    """Load knowledge_tree.yml and return the typed tree.

    Validates against the subject categories from SubjectConfig.

    Returns:
        Dict of shape: {category: {lecture: [knowledge_points]}}

    Raises:
        FileNotFoundError: If knowledge_tree.yml doesn't exist.
        ValueError: If the structure is invalid.
    """
    if config_dir is None:
        config_dir = DEFAULT_CONFIG_DIR
    data = _load_yaml(config_dir / "knowledge_tree.yml")
    subject = load_subject_config(config_dir)
    _validate_knowledge_tree_structure(data, subject.categories)
    return data


def _validate_knowledge_tree_structure(
    data: dict[str, Any],
    expected_subjects: set[str] | list[str] | None = None,
) -> None:
    """Validate the knowledge tree has the expected structure.

    Args:
        data: Parsed knowledge tree YAML.
        expected_subjects: Valid top-level keys. If None, inferred from SubjectConfig.
    """
    if expected_subjects is None:
        subject = load_subject_config()
        expected_subjects = set(subject.categories)
    elif not isinstance(expected_subjects, set):
        expected_subjects = set(expected_subjects)

    actual_subjects = set(data.keys())

    if actual_subjects != expected_subjects:
        missing = expected_subjects - actual_subjects
        extra = actual_subjects - expected_subjects
        msg = f"Knowledge tree subjects mismatch. Missing: {missing}, Extra: {extra}"
        raise ValueError(msg)

    for subject_name, lectures in data.items():
        if not isinstance(lectures, dict):
            raise ValueError(
                f"Expected dict of lectures under '{subject_name}', "
                f"got {type(lectures).__name__}"
            )
        for lecture_name, points in lectures.items():
            if not lecture_name.startswith("第") or "讲" not in lecture_name:
                raise ValueError(
                    f"Invalid lecture name '{lecture_name}' under '{subject_name}'. "
                    f"Expected format: '第N讲_XXX'"
                )
            if not isinstance(points, list):
                raise ValueError(
                    f"Expected list of knowledge points under "
                    f"'{subject_name}/{lecture_name}', got {type(points).__name__}"
                )
            for i, point in enumerate(points):
                if not isinstance(point, str) or not point.strip():
                    raise ValueError(
                        f"Empty or non-string knowledge point at "
                        f"'{subject_name}/{lecture_name}[{i}]'"
                    )


# ── OPD markers ───────────────────────────────────────────────────────────────


def load_opd_markers(config_dir: Path | None = None) -> dict[str, list[str]]:
    """Load opd_markers.yml and return O/P/D code lists.

    Returns:
        Dict with keys 'O', 'P', 'D', each mapping to a list of code strings.

    Raises:
        FileNotFoundError: If opd_markers.yml doesn't exist.
        ValueError: If the structure is invalid.
    """
    if config_dir is None:
        config_dir = DEFAULT_CONFIG_DIR
    data = _load_yaml(config_dir / "opd_markers.yml")
    _validate_opd_structure(data)
    return data


def _validate_opd_structure(data: dict[str, Any]) -> None:
    """Validate the OPD markers have the expected structure."""
    for key in ("O", "P", "D"):
        if key not in data:
            raise ValueError(f"OPD markers missing required key: '{key}'")
        if not isinstance(data[key], list):
            raise ValueError(f"OPD '{key}' must be a list, got {type(data[key]).__name__}")
        if len(data[key]) == 0:
            raise ValueError(f"OPD '{key}' list is empty")


def get_opd_sets(config_dir: Path | None = None) -> tuple[set[str], set[str], set[str]]:
    """Convenience: return (o_set, p_set, d_set) for fast lookup."""
    markers = load_opd_markers(config_dir)
    return (
        set(markers["O"]),
        set(markers["P"]),
        set(markers["D"]),
    )
