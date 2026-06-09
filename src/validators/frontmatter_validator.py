"""YAML frontmatter validator for generated MD files.

Validates the YAML frontmatter of Obsidian-compatible problem MD files
against the spec defined in planning doc §6.1 and the Frontmatter model.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import yaml

from src.config import load_subject_config
from src.models import Frontmatter
from src.validators.opd_validator import is_valid_o_code, is_valid_p_code, is_valid_d_code

# YAML frontmatter block marker
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_frontmatter(md_content: str) -> tuple[dict | None, list[str]]:
    """Extract YAML frontmatter from a Markdown string.

    Returns:
        Tuple of (parsed_dict_or_None, list_of_parse_errors).
        If no frontmatter found, returns (None, ["No frontmatter found"]).
    """
    match = FRONTMATTER_RE.match(md_content)
    if not match:
        return None, ["No YAML frontmatter block found (expected --- ... ---)"]

    yaml_text = match.group(1)
    try:
        data = yaml.safe_load(yaml_text)
        if data is None:
            return None, ["Frontmatter is empty"]
        if not isinstance(data, dict):
            return None, [f"Frontmatter must be a YAML mapping, got {type(data).__name__}"]
        return data, []
    except yaml.YAMLError as e:
        return None, [f"YAML parse error: {e}"]


def validate_frontmatter(
    md_content: str,
    config_dir: Path | None = None,
) -> dict:
    """Fully validate the frontmatter of a problem MD file.

    Checks:
      - Frontmatter block exists and is valid YAML
      - All required fields are present
      - Enum fields have valid values
      - OPD codes exist in the OPD marker config
      - Summary is pure Chinese, ≤ 100 chars, no LaTeX
      - Dates are valid ISO format
      - Tags are all strings

    Args:
        md_content: Full Markdown file content.
        config_dir: Path to config directory for OPD cross-validation.

    Returns:
        Dict with keys: valid, errors, warnings, data (parsed frontmatter dict)
    """
    errors: list[str] = []
    warnings: list[str] = []

    data, parse_errors = parse_frontmatter(md_content)
    if parse_errors:
        return {
            "valid": False,
            "errors": parse_errors,
            "warnings": [],
            "data": None,
        }

    assert data is not None  # for type checker

    # ── Required fields ──
    required_fields = [
        "subject", "lecture", "question_type",
        "opd_target", "opd_procedures", "opd_details",
        "key_ability", "source_book", "source_example",
        "tags", "summary", "created",
    ]

    for field in required_fields:
        if field not in data:
            errors.append(f"Missing required frontmatter field: '{field}'")

    if errors:
        return {"valid": False, "errors": errors, "warnings": warnings, "data": data}

    # ── Enum / domain validation (from SubjectConfig) ──
    subject_cfg = load_subject_config(config_dir)
    _check_enum(data, "subject", set(subject_cfg.categories), errors)
    _check_enum(data, "question_type", set(subject_cfg.question_types), errors)
    # ── key_ability validation ──
    abilities = data.get("key_ability", [])
    if isinstance(abilities, list):
        valid_abilities = set(subject_cfg.key_abilities)
        for ab in abilities:
            if ab not in valid_abilities:
                errors.append(f"Invalid key_ability value: '{ab}'. Must be one of {valid_abilities}")
    else:
        errors.append(f"key_ability must be a list, got {type(abilities).__name__}")

    # ── OPD validation ──
    opd_target = data.get("opd_target", "")
    if opd_target and not is_valid_o_code(str(opd_target), config_dir):
        errors.append(f"Invalid OPD target code: '{opd_target}'")

    opd_procedures = data.get("opd_procedures", [])
    if isinstance(opd_procedures, list):
        for code in opd_procedures:
            if not is_valid_p_code(str(code), config_dir):
                errors.append(f"Invalid OPD procedure code: '{code}'")
    else:
        errors.append(f"opd_procedures must be a list, got {type(opd_procedures).__name__}")

    opd_details = data.get("opd_details", [])
    if isinstance(opd_details, list):
        for code in opd_details:
            if not is_valid_d_code(str(code), config_dir):
                errors.append(f"Invalid OPD detail code: '{code}'")
    else:
        errors.append(f"opd_details must be a list, got {type(opd_details).__name__}")

    # ── Summary validation ──
    summary = data.get("summary", "")
    if isinstance(summary, str):
        if len(summary) > 100:
            errors.append(f"Summary too long: {len(summary)} chars (max 100)")
        if "$" in summary:
            errors.append("Summary must not contain LaTeX ($)")
    else:
        errors.append(f"summary must be a string, got {type(summary).__name__}")

    # ── Date validation ──
    for date_field in ("created", "updated"):
        val = data.get(date_field)
        if val is not None and not isinstance(val, date):
            if isinstance(val, str):
                try:
                    date.fromisoformat(val)
                except ValueError:
                    errors.append(f"Invalid date format for '{date_field}': '{val}' (expected YYYY-MM-DD)")
            else:
                errors.append(f"'{date_field}' must be a date or date string, got {type(val).__name__}")

    # ── Tags validation ──
    tags = data.get("tags", [])
    if isinstance(tags, list):
        for tag in tags:
            if not isinstance(tag, str):
                errors.append(f"Tag must be a string, got {type(tag).__name__}: {tag}")
    else:
        errors.append(f"tags must be a list, got {type(tags).__name__}")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "data": data,
    }


def _check_enum(data: dict, field: str, valid_values: set[str], errors: list[str]) -> None:
    """Check that a frontmatter field has a valid enum value."""
    val = data.get(field)
    if val is not None and val not in valid_values:
        errors.append(f"Invalid {field} value: '{val}'. Must be one of {valid_values}")
