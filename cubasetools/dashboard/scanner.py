"""Recursive scanner for Cubase projects in a directory tree."""

from __future__ import annotations

from pathlib import Path

from cubasetools.core.cpr_parser import parse_cpr
from cubasetools.core.models import CubaseProject


def find_all_cpr_files(base_dir: Path) -> list[Path]:
    """Find all .cpr files recursively, sorted by path."""
    return sorted(base_dir.rglob("*.cpr"))


def scan_projects(
    base_dir: Path,
    progress_callback: callable | None = None,
) -> list[CubaseProject]:
    """Scan all .cpr files and parse them into CubaseProject objects.

    progress_callback(current, total, project_name) is called for each file.
    """
    cpr_files = find_all_cpr_files(base_dir)
    projects: list[CubaseProject] = []

    for i, cpr_path in enumerate(cpr_files):
        if progress_callback:
            progress_callback(i + 1, len(cpr_files), cpr_path.stem)

        try:
            project = parse_cpr(cpr_path)
            projects.append(project)
        except Exception:
            # Skip files that can't be parsed
            pass

    return projects
