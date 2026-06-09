"""Knowledge tree validator.

Validates that the knowledge tree YAML conforms to the expected structure.
Subject names are cross-validated against config/subject.yml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import load_knowledge_tree, load_subject_config


def validate_knowledge_tree(config_dir: Path | None = None) -> dict[str, Any]:
    """Load and fully validate the knowledge tree.

    Returns a dict with validation results:
        {
            "valid": bool,
            "subjects": list[str],
            "lecture_count": int,
            "point_count": int,
            "errors": list[str],
            "warnings": list[str],
        }
    """
    errors: list[str] = []
    warnings: list[str] = []
    subjects: list[str] = []
    lecture_count = 0
    point_count = 0

    try:
        subject_cfg = load_subject_config(config_dir)
        tree = load_knowledge_tree(config_dir)
    except (FileNotFoundError, ValueError) as e:
        return {
            "valid": False,
            "subjects": [],
            "lecture_count": 0,
            "point_count": 0,
            "errors": [str(e)],
            "warnings": [],
        }

    subjects = list(tree.keys())

    for subject, lectures in tree.items():
        for lecture_name, points in lectures.items():
            lecture_count += 1
            point_count += len(points)

            # Check lecture naming pattern
            if not lecture_name.startswith("第") or "讲" not in lecture_name:
                errors.append(f"Invalid lecture name: '{lecture_name}' in {subject}")

            # Check for duplicate points within a lecture
            seen = set()
            for pt in points:
                if pt in seen:
                    warnings.append(
                        f"Duplicate knowledge point '{pt}' in {subject}/{lecture_name}"
                    )
                seen.add(pt)

    # Cross-validate: check subject names match SubjectConfig.categories
    expected = set(subject_cfg.categories)
    actual = set(subjects)
    if actual != expected:
        missing = expected - actual
        extra = actual - expected
        if missing:
            errors.append(f"Missing subjects: {missing}")
        if extra:
            errors.append(f"Unexpected subjects: {extra}")

    return {
        "valid": len(errors) == 0,
        "subjects": subjects,
        "lecture_count": lecture_count,
        "point_count": point_count,
        "errors": errors,
        "warnings": warnings,
    }
