"""Plugin usage statistics across single or multiple projects."""

from __future__ import annotations

from cubasetools.core.models import CubaseProject


def plugin_frequency(project: CubaseProject) -> dict[str, int]:
    """Count plugin usage in a single project."""
    counts: dict[str, int] = {}
    for track in project.tracks:
        for plugin in track.plugins:
            name = plugin.name or "Unknown"
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))


def aggregate_plugin_stats(projects: list[CubaseProject]) -> dict[str, int]:
    """Aggregate plugin usage across multiple projects."""
    totals: dict[str, int] = {}
    for project in projects:
        for name, count in plugin_frequency(project).items():
            totals[name] = totals.get(name, 0) + count
    return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))


def plugin_per_project(projects: list[CubaseProject]) -> dict[str, list[str]]:
    """Map each plugin to the list of projects that use it."""
    mapping: dict[str, list[str]] = {}
    for project in projects:
        for name in plugin_frequency(project):
            mapping.setdefault(name, []).append(project.project_name)
    return mapping
