"""Backup file cleanup - finds and removes .bak and .peak files."""

from pathlib import Path

BACKUP_EXTENSIONS = {".bak", ".peak"}


def find_backup_files(base_dir: Path) -> list[Path]:
    """Find all .bak and .peak files recursively."""
    results: list[Path] = []
    for ext in BACKUP_EXTENSIONS:
        results.extend(base_dir.rglob(f"*{ext}"))
    results.sort(key=lambda f: f.name)
    return results


def categorize_backup_files(files: list[Path]) -> dict[str, list[Path]]:
    """Group backup files by extension."""
    categories: dict[str, list[Path]] = {}
    for f in files:
        ext = f.suffix.lower()
        categories.setdefault(ext, []).append(f)
    return categories


def delete_backup_files(files: list[Path]) -> tuple[int, int]:
    """Delete backup files. Returns (deleted_count, total_bytes_freed)."""
    deleted = 0
    freed = 0
    for f in files:
        try:
            size = f.stat().st_size
            f.unlink()
            deleted += 1
            freed += size
        except OSError:
            pass
    return deleted, freed
