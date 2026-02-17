"""Cross-project aggregation and analysis."""

from __future__ import annotations

from dataclasses import dataclass, field

from cubasetools.core.models import CubaseProject


@dataclass
class CrossProjectStats:
    total_projects: int = 0
    total_tracks: int = 0
    total_plugins: int = 0
    total_file_size: int = 0
    avg_tracks_per_project: float = 0.0
    avg_plugins_per_project: float = 0.0
    most_used_plugins: dict[str, int] = field(default_factory=dict)
    track_type_distribution: dict[str, int] = field(default_factory=dict)


def compute_cross_project_stats(
    projects: list[CubaseProject],
) -> CrossProjectStats:
    """Aggregate statistics across all projects."""
    stats = CrossProjectStats()
    stats.total_projects = len(projects)

    plugin_counts: dict[str, int] = {}
    track_types: dict[str, int] = {}

    for project in projects:
        stats.total_tracks += project.track_count
        stats.total_plugins += project.plugin_count
        stats.total_file_size += project.file_size

        for track in project.tracks:
            tt = track.track_type.value
            track_types[tt] = track_types.get(tt, 0) + 1

            for plugin in track.plugins:
                name = plugin.name or "Unknown"
                plugin_counts[name] = plugin_counts.get(name, 0) + 1

    if projects:
        stats.avg_tracks_per_project = stats.total_tracks / len(projects)
        stats.avg_plugins_per_project = stats.total_plugins / len(projects)

    stats.most_used_plugins = dict(
        sorted(plugin_counts.items(), key=lambda x: x[1], reverse=True)
    )
    stats.track_type_distribution = dict(
        sorted(track_types.items(), key=lambda x: x[1], reverse=True)
    )

    return stats
