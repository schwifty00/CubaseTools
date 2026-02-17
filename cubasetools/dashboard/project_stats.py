"""Per-project statistics computation."""

from __future__ import annotations

from pathlib import Path

from cubasetools.cleanup.audio_cleanup import (
    analyze_project as analyze_audio,
    find_cpr_file,
)
from cubasetools.core.models import CubaseProject, ProjectStats
from cubasetools.utils.file_utils import folder_size


def compute_project_stats(project: CubaseProject) -> ProjectStats:
    """Compute detailed statistics for a single parsed project."""
    stats = ProjectStats(project=project)

    project_dir = project.file_path.parent

    # Audio analysis
    try:
        used, unused, _, audio_dir = analyze_audio(project_dir)
        stats.used_files = used
        stats.unused_files = unused
        stats.used_audio_files = len(used)
        stats.unused_audio_files = len(unused)
        stats.total_audio_files = len(used) + len(unused)
        stats.total_audio_size = sum(f.stat().st_size for f in used + unused)
        stats.unused_audio_size = sum(f.stat().st_size for f in unused)
        stats.audio_dir = audio_dir
    except (FileNotFoundError, OSError):
        pass

    return stats
