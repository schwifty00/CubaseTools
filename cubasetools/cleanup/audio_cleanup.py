"""Audio cleanup logic - refactored from cubase_cleanup.py.

Pure logic, no GUI. Returns data structures for the GUI layer to display.
"""

import re
import shutil
from pathlib import Path

from cubasetools.core.constants import AUDIO_EXTENSIONS, AUDIO_FOLDER_NAMES


def extract_referenced_audio(cpr_path: Path) -> set[str]:
    """Extract all audio file references from a .cpr binary file."""
    with open(cpr_path, "rb") as f:
        data = f.read()

    referenced: set[str] = set()

    # UTF-8 encoded .wav references
    for match in re.finditer(rb'([\w\-\. ]+\.wav)', data, re.IGNORECASE):
        name = match.group(1).decode("utf-8", errors="ignore").strip()
        if name and len(name) > 4:
            referenced.add(name.lower())

    # UTF-16-LE encoded .wav references
    for match in re.finditer(
        rb'((?:[\w\-\. ]\x00)+w\x00a\x00v\x00)', data, re.IGNORECASE
    ):
        try:
            name = match.group(1).decode("utf-16-le", errors="ignore").strip()
            if name and len(name) > 4:
                referenced.add(name.lower())
        except (UnicodeDecodeError, ValueError):
            continue

    # Other audio formats (UTF-8)
    for ext in [b"mp3", b"flac", b"aif", b"aiff", b"ogg", b"m4a"]:
        pattern = rb'([\w\-\. ]+\.' + ext + rb')'
        for match in re.finditer(pattern, data, re.IGNORECASE):
            name = match.group(1).decode("utf-8", errors="ignore").strip()
            if name and len(name) > 4:
                referenced.add(name.lower())

    return referenced


def find_audio_folder(project_dir: Path) -> Path | None:
    """Locate the audio folder within a Cubase project directory."""
    for name in AUDIO_FOLDER_NAMES:
        audio_dir = project_dir / name
        if audio_dir.is_dir():
            return audio_dir

    # Fallback: find directory with most audio files
    best = None
    best_count = 0
    for item in project_dir.iterdir():
        if item.is_dir() and not item.name.startswith("_"):
            count = sum(1 for f in item.glob("*.wav"))
            if count > best_count:
                best = item
                best_count = count
    return best


def find_cpr_file(project_dir: Path) -> Path | None:
    """Find the most recently modified .cpr file in a directory."""
    cpr_files = list(project_dir.glob("*.cpr"))
    if not cpr_files:
        return None
    cpr_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return cpr_files[0]


def analyze_project(project_dir: Path) -> tuple[list[Path], list[Path], str, Path]:
    """Analyze a project and return (used_files, unused_files, cpr_name, audio_dir)."""
    cpr_file = find_cpr_file(project_dir)
    if not cpr_file:
        raise FileNotFoundError("Keine .cpr-Datei gefunden!")

    audio_dir = find_audio_folder(project_dir)
    if not audio_dir:
        raise FileNotFoundError("Kein Audio-Ordner gefunden!")

    referenced = extract_referenced_audio(cpr_file)

    all_audio_files = [
        f for f in audio_dir.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    ]

    unused_files = []
    used_files = []
    for audio_file in all_audio_files:
        if audio_file.name.lower() in referenced:
            used_files.append(audio_file)
        else:
            unused_files.append(audio_file)

    unused_files.sort(key=lambda f: f.name)
    return used_files, unused_files, cpr_file.name, audio_dir


def find_all_projects(base_dir: Path) -> list[Path]:
    """Find all Cubase project directories recursively."""
    projects: list[Path] = []
    for cpr_file in base_dir.rglob("*.cpr"):
        project_dir = cpr_file.parent
        if project_dir not in projects:
            projects.append(project_dir)
    return sorted(projects)


def is_single_project(path: Path) -> bool:
    """Check if a directory is directly a Cubase project."""
    return any(path.glob("*.cpr"))


def move_files_to_unused(entries: list[tuple[Path, Path]]) -> int:
    """Move files to _unused subdirectory. Returns count of moved files."""
    moved = 0
    for file_path, audio_dir in entries:
        unused_dir = audio_dir / "_unused"
        unused_dir.mkdir(exist_ok=True)
        dest = unused_dir / file_path.name
        counter = 1
        while dest.exists():
            dest = unused_dir / f"{file_path.stem}_{counter}{file_path.suffix}"
            counter += 1
        shutil.move(str(file_path), str(dest))
        moved += 1
    return moved


def delete_files(entries: list[tuple[Path, Path]]) -> int:
    """Permanently delete files. Returns count of deleted files."""
    deleted = 0
    for file_path, _ in entries:
        file_path.unlink()
        deleted += 1
    return deleted
