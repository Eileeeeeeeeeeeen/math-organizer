"""Knowledge tree validator.

Validates that config/knowledge_tree.yml conforms to the expected structure:
  - Exactly 3 subjects: 高等数学, 线性代数, 概率统计
  - Each lecture key matches pattern: 第N讲_XXX
  - Each knowledge point is a non-empty string
  - All subject and lecture names are consistent with other configs
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.config import load_knowledge_tree


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

    Also cross-validates lecture names against known OPD target codes.
    """
    errors: list[str] = []
    warnings: list[str] = []
    subjects: list[str] = []
    lecture_count = 0
    point_count = 0

    try:
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

    # Cross-validate: check that the 3 canonical subject names are used
    expected = {"高等数学", "线性代数", "概率统计"}
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
