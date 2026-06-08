"""Directory structure validator.

Validates that the vault directory (考研数学题库/) follows the
prescribed 3-level structure:
    考研数学题库/
    ├── _index.md
    ├── 高等数学/
    │   ├── _index.md
    │   └── 第N讲_XXX/
    │       ├── _index.md
    │       ├── 选择题/
    │       ├── 填空题/
    │       └── 解答题/
    ├── 线性代数/
    │   └── ...
    ├── 概率统计/
    │   └── ...
    └── assets/
        └── images/
"""

from __future__ import annotations

from pathlib import Path

EXPECTED_SUBJECTS = {"高等数学", "线性代数", "概率统计"}
EXPECTED_QUESTION_TYPES = {"选择题", "填空题", "解答题"}


def validate_directory_structure(vault_root: Path | str) -> dict:
    """Validate the directory structure of the vault.

    Args:
        vault_root: Path to the 考研数学题库/ directory.

    Returns:
        Dict with keys: valid, errors, warnings, structure (dict of what was found)
    """
    errors: list[str] = []
    warnings: list[str] = []
    structure: dict[str, list[str]] = {}

    root = Path(vault_root)

    if not root.exists():
        return {
            "valid": False,
            "errors": [f"Vault root does not exist: {root}"],
            "warnings": [],
            "structure": {},
        }

    if not root.is_dir():
        return {
            "valid": False,
            "errors": [f"Vault root is not a directory: {root}"],
            "warnings": [],
            "structure": {},
        }

    # Check root _index.md
    root_index = root / "_index.md"
    if not root_index.exists():
        warnings.append(f"Missing root _index.md: {root_index}")

    # Check assets/images/
    assets_images = root / "assets" / "images"
    if not assets_images.exists():
        warnings.append(f"Missing assets/images/ directory: {assets_images}")

    # Check each subject directory
    for subject in EXPECTED_SUBJECTS:
        subject_dir = root / subject
        structure[subject] = []

        if not subject_dir.exists():
            errors.append(f"Missing subject directory: {subject_dir}")
            continue

        if not subject_dir.is_dir():
            errors.append(f"Subject path is not a directory: {subject_dir}")
            continue

        # Subject _index.md
        subject_index = subject_dir / "_index.md"
        if not subject_index.exists():
            warnings.append(f"Missing _index.md in {subject_dir}")

        # Look for lecture directories
        found_lectures = False
        for item in sorted(subject_dir.iterdir()):
            if item.is_dir() and not item.name.startswith("_"):
                found_lectures = True
                structure[subject].append(item.name)

                # Lecture _index.md
                lecture_index = item / "_index.md"
                if not lecture_index.exists():
                    warnings.append(f"Missing _index.md in lecture dir: {item}")

                # Question type directories
                lecture_qtypes_found = set()
                for sub_item in item.iterdir():
                    if sub_item.is_dir():
                        lecture_qtypes_found.add(sub_item.name)

                unexpected = lecture_qtypes_found - EXPECTED_QUESTION_TYPES
                if unexpected:
                    warnings.append(
                        f"Unexpected subdirectories in {item.name}: {unexpected}"
                    )

        if not found_lectures:
            warnings.append(f"No lecture directories found under {subject_dir}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "structure": structure,
    }
