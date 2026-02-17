"""Plugin chain analysis - extract and display plugin chains per track."""

from __future__ import annotations

from cubasetools.core.models import CubaseProject, PluginInstance, Track


def get_plugin_chains(project: CubaseProject) -> list[tuple[Track, list[PluginInstance]]]:
    """Get plugin chain for each track that has plugins."""
    chains = []
    for track in project.tracks:
        if track.plugins:
            chains.append((track, track.plugins))
    return chains


def get_plugin_usage_stats(project: CubaseProject) -> dict[str, int]:
    """Count how often each plugin is used across all tracks."""
    stats: dict[str, int] = {}
    for track in project.tracks:
        for plugin in track.plugins:
            name = plugin.name or "Unknown"
            stats[name] = stats.get(name, 0) + 1
    return dict(sorted(stats.items(), key=lambda x: x[1], reverse=True))


def get_tracks_for_plugin(
    project: CubaseProject, plugin_name: str
) -> list[tuple[Track, PluginInstance]]:
    """Find all tracks using a specific plugin."""
    results = []
    for track in project.tracks:
        for plugin in track.plugins:
            if plugin.name == plugin_name:
                results.append((track, plugin))
    return results
