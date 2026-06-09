"""File naming convention validator.

Enforces the naming format: {讲次编号}_{题目类型}_{例号或序号}_{简短描述}.md

Rules:
  - 讲次编号 must match knowledge tree lecture names
  - 题目类型 must be one of the configured question types
  - 简短描述 must be ≤ 15 Chinese characters
  - No underscores in the description part (underscores only as separators)
  - Valid question types are read from config/subject.yml
"""

from __future__ import annotations

import re
from pathlib import Path

from src.config import load_subject_config

# Regex for the full filename pattern (question types patched at runtime)
#  第N讲_题型_例号_简短描述.md
# The question-type alternation is built dynamically from SubjectConfig.
_FILENAME_REGEX_TEMPLATE = (
    r"^(第\d+讲)_"            # 讲次编号 (e.g., 第1讲)
    r"({qtypes})_"            # 题目类型 (from config)
    r"([^_]+)_"               # 例号或序号 (no underscores allowed)
    r"(.{{1,15}})"            # 简短描述 (1-15 chars) — doubled braces for format()
    r"\.md$"                  # .md extension
)


def _build_filename_pattern() -> re.Pattern:
    """Build a filename regex from the current SubjectConfig question types."""
    subject = load_subject_config()
    alt = "|".join(re.escape(t) for t in subject.question_types)
    return re.compile(_FILENAME_REGEX_TEMPLATE.format(qtypes=alt))


def validate_filename(filename: str, knowledge_tree: dict | None = None) -> dict:
    """Validate a filename against the naming convention.

    Args:
        filename: The filename to validate (e.g., '第1讲_选择题_例1-3_间断点个数判定.md')
        knowledge_tree: Optional knowledge tree dict for cross-validation of lecture names.

    Returns:
        Dict with keys: valid, errors, warnings, parsed (dict of extracted parts)
    """
    subject = load_subject_config()
    valid_qtypes = set(subject.question_types)
    errors: list[str] = []
    warnings: list[str] = []
    parsed: dict = {}

    # Strip path if present
    basename = Path(filename).name

    pattern = _build_filename_pattern()
    match = pattern.match(basename)
    if not match:
        errors.append(
            f"Filename '{basename}' does not match pattern: "
            f"{{讲次编号}}_{{题目类型}}_{{例号}}_{{简短描述}}.md"
        )
        return {"valid": False, "errors": errors, "warnings": warnings, "parsed": parsed}

    lecture_num, qtype, example_id, short_desc = match.groups()

    parsed = {
        "lecture_num": lecture_num,
        "question_type": qtype,
        "example_id": example_id,
        "short_description": short_desc,
    }

    # Validate question type
    if qtype not in valid_qtypes:
        errors.append(f"Invalid question type: '{qtype}'")

    # Validate short description is mostly Chinese (no LaTeX)
    if "$" in short_desc:
        errors.append("Short description must not contain LaTeX ($)")

    # Cross-validate lecture number against knowledge tree
    if knowledge_tree is not None:
        all_lectures: set[str] = set()
        for subject_lectures in knowledge_tree.values():
            all_lectures.update(subject_lectures.keys())

        matching = [l for l in all_lectures if l.startswith(lecture_num)]
        if not matching:
            warnings.append(
                f"Lecture '{lecture_num}' not found in knowledge tree"
            )

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "parsed": parsed,
    }


def generate_filename(meta: dict, problem: str = "") -> str:
    """Generate a compliant filename from metadata.

    Args:
        meta: Dict with keys: lecture (e.g., '第1讲_函数极限与连续'),
              question_type (e.g., '选择题'),
              source.example_id (e.g., '例1.3')
        problem: Optional problem text, used to generate short description.

    Returns:
        A filename string matching the convention.
    """
    subject = load_subject_config()
    default_qtype = subject.question_types[0] if subject.question_types else "解答题"

    lecture_full = meta.get("lecture", "第X讲")
    # Extract just the lecture number part
    lecture_num = lecture_full.split("_")[0] if "_" in lecture_full else lecture_full

    qtype = meta.get("question_type", default_qtype)

    source = meta.get("source", {})
    if isinstance(source, dict):
        example_id = source.get("example_id", "自录001")
    else:
        example_id = "自录001"

    # Generate short description from problem text
    short_desc = _generate_short_description(problem)

    filename = f"{lecture_num}_{qtype}_{example_id}_{short_desc}.md"
    return filename


def _generate_short_description(problem: str, max_chars: int = 15) -> str:
    """Extract a short Chinese description from problem text.

    Strips LaTeX, punctuation, and whitespace. Takes first max_chars
    Chinese characters.
    """
    if not problem:
        return "题目"

    # Remove LaTeX formulas ($...$, $$...$$)
    cleaned = re.sub(r"\$\$?[^$]+\$\$?", "", problem)
    # Remove remaining LaTeX commands
    cleaned = re.sub(r"\\[a-zA-Z]+(\{[^}]*\})*", "", cleaned)
    # Keep only Chinese characters
    chinese = re.findall(r"[一-鿿]", cleaned)
    desc = "".join(chinese[:max_chars])

    if not desc:
        # Fallback: use alphanumeric characters
        alnum = re.findall(r"[a-zA-Z0-9一-鿿]", cleaned)
        desc = "".join(alnum[:max_chars])

    return desc if desc else "题目"
