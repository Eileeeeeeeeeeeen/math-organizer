"""OPD (解题方法论) marker validator.

Validates that config/opd_markers.yml conforms to:
  - All O_ codes start with 'O_' and are unique
  - All P_ codes start with 'P' (P2-P12) and are unique
  - All D_ codes start with 'D' (D1-D53) and are unique

Also provides lookup functions for validating individual codes.
"""

from __future__ import annotations

from pathlib import Path

from src.config import get_opd_sets


# Module-level cache for the OPD sets
_o_cache: set[str] | None = None
_p_cache: set[str] | None = None
_d_cache: set[str] | None = None


def _get_cached_sets(config_dir: Path | None = None) -> tuple[set[str], set[str], set[str]]:
    """Load and cache OPD code sets."""
    global _o_cache, _p_cache, _d_cache
    if _o_cache is None or config_dir is not None:
        _o_cache, _p_cache, _d_cache = get_opd_sets(config_dir)
    return _o_cache, _p_cache, _d_cache


def validate_opd_markers(config_dir: Path | None = None) -> dict:
    """Validate the OPD markers configuration.

    Returns a dict with validation results.
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        o_set, p_set, d_set = _get_cached_sets(config_dir)
    except (FileNotFoundError, ValueError) as e:
        return {
            "valid": False,
            "o_count": 0, "p_count": 0, "d_count": 0,
            "errors": [str(e)],
            "warnings": [],
        }

    # Validate O codes
    for code in o_set:
        if not code.startswith("O_"):
            errors.append(f"O_ code must start with 'O_', got: {code}")

    # Validate P codes
    for code in p_set:
        if not code.startswith("P"):
            errors.append(f"P_ code must start with 'P', got: {code}")

    # Validate D codes
    for code in d_set:
        if not code.startswith("D"):
            errors.append(f"D_ code must start with 'D', got: {code}")

    return {
        "valid": len(errors) == 0,
        "o_count": len(o_set),
        "p_count": len(p_set),
        "d_count": len(d_set),
        "errors": errors,
        "warnings": warnings,
    }


def is_valid_o_code(code: str, config_dir: Path | None = None) -> bool:
    """Check if a given O_ code exists in the configured OPD markers."""
    if not code or not code.startswith("O_"):
        return False
    o_set, _, _ = _get_cached_sets(config_dir)
    return code in o_set


def is_valid_p_code(code: str, config_dir: Path | None = None) -> bool:
    """Check if a given P_ code exists in the configured OPD markers."""
    if not code or not code.startswith("P"):
        return False
    _, p_set, _ = _get_cached_sets(config_dir)
    return code in p_set


def is_valid_d_code(code: str, config_dir: Path | None = None) -> bool:
    """Check if a given D_ code exists in the configured OPD markers."""
    if not code or not code.startswith("D"):
        return False
    _, _, d_set = _get_cached_sets(config_dir)
    return code in d_set


def clear_cache() -> None:
    """Clear the module-level OPD cache (useful for testing)."""
    global _o_cache, _p_cache, _d_cache
    _o_cache = None
    _p_cache = None
    _d_cache = None
