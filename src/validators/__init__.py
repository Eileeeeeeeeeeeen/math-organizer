"""Validators package — enforcement of all project regulations."""

from src.validators.knowledge_tree import validate_knowledge_tree
from src.validators.opd_validator import (
    validate_opd_markers,
    is_valid_o_code,
    is_valid_p_code,
    is_valid_d_code,
)
from src.validators.naming_validator import validate_filename, generate_filename
from src.validators.frontmatter_validator import validate_frontmatter, parse_frontmatter
from src.validators.directory_validator import validate_directory_structure
from src.validators.dedup import compute_problem_hash, check_duplicate

__all__ = [
    # knowledge_tree
    "validate_knowledge_tree",
    # opd
    "validate_opd_markers",
    "is_valid_o_code",
    "is_valid_p_code",
    "is_valid_d_code",
    # naming
    "validate_filename",
    "generate_filename",
    # frontmatter
    "validate_frontmatter",
    "parse_frontmatter",
    # directory
    "validate_directory_structure",
    # dedup
    "compute_problem_hash",
    "check_duplicate",
]
