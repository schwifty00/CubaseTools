"""Compare mix settings between projects."""

from __future__ import annotations

from dataclasses import dataclass, field

from cubasetools.core.models import CubaseProject


@dataclass
class ProjectComparison:
    project_a: str = ""
    project_b: str = ""
    shared_plugins: list[str] = field(default_factory=list)
    unique_to_a: list[str] = field(default_factory=list)
    unique_to_b: list[str] = field(default_factory=list)
    track_count_a: int = 0
    track_count_b: int = 0


def compare_projects(a: CubaseProject, b: CubaseProject) -> ProjectComparison:
    """Compare two projects' plugin usage and structure."""
    plugins_a = set()
    plugins_b = set()

    for track in a.tracks:
        for plugin in track.plugins:
            if plugin.name:
                plugins_a.add(plugin.name)

    for track in b.tracks:
        for plugin in track.plugins:
            if plugin.name:
                plugins_b.add(plugin.name)

    return ProjectComparison(
        project_a=a.project_name,
        project_b=b.project_name,
        shared_plugins=sorted(plugins_a & plugins_b),
        unique_to_a=sorted(plugins_a - plugins_b),
        unique_to_b=sorted(plugins_b - plugins_a),
        track_count_a=a.track_count,
        track_count_b=b.track_count,
    )
