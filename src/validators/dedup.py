"""Deduplication utilities.

Provides content-based deduplication using SHA256 hashing of problem text,
as specified in planning doc §10.3.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_problem_hash(problem_text: str) -> str:
    """Compute SHA256 hash of normalized problem text.

    Normalization: strip whitespace, normalize LaTeX spacing.
    This ensures minor formatting differences don't cause false duplicates.

    Args:
        problem_text: The raw problem text (may include LaTeX).

    Returns:
        Hex-encoded SHA256 digest string.
    """
    # Normalize: collapse whitespace, strip
    normalized = " ".join(problem_text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def check_duplicate(
    problem_text: str,
    lecture_dir: Path,
    *,
    known_hashes: dict[str, str] | None = None,
) -> dict:
    """Check if a problem already exists in a lecture directory.

    Scans all .md files in the lecture directory (and its question_type
    subdirectories), computing SHA256 of each problem text found.

    Args:
        problem_text: The problem text to check.
        lecture_dir: Path to the lecture directory (e.g., 高等数学/第1讲_函数极限与连续/).
        known_hashes: Optional pre-computed dict of {filepath: sha256_hash}
                      to avoid re-scanning.

    Returns:
        Dict with keys:
            is_duplicate: bool
            matching_files: list of file paths with matching content
            hash: the SHA256 hash of the input
    """
    target_hash = compute_problem_hash(problem_text)
    matching_files: list[str] = []

    if known_hashes is not None:
        for filepath_str, file_hash in known_hashes.items():
            if file_hash == target_hash:
                matching_files.append(filepath_str)
    elif lecture_dir.exists():
        for md_file in lecture_dir.rglob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8")
                file_hash = compute_problem_hash(content)
                if file_hash == target_hash:
                    matching_files.append(str(md_file.relative_to(lecture_dir)))
            except Exception:
                continue  # Skip unreadable files

    return {
        "is_duplicate": len(matching_files) > 0,
        "matching_files": matching_files,
        "hash": target_hash,
    }


def build_hash_index(lecture_dir: Path) -> dict[str, str]:
    """Build a hash index of all problem files in a lecture directory.

    Returns:
        Dict mapping relative file paths to their SHA256 hashes.
    """
    index: dict[str, str] = {}
    if not lecture_dir.exists():
        return index

    for md_file in lecture_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            file_hash = compute_problem_hash(content)
            index[str(md_file.relative_to(lecture_dir))] = file_hash
        except Exception:
            continue

    return index
