"""Compressor analysis - extract and compare compressor settings."""

from __future__ import annotations

from cubasetools.core.models import CompressorSettings, CubaseProject, Track


def get_all_compressor_data(
    project: CubaseProject,
) -> list[tuple[Track, CompressorSettings]]:
    """Get compressor settings from all tracks."""
    results = []
    for track in project.tracks:
        for plugin in track.plugins:
            if plugin.compressor:
                results.append((track, plugin.compressor))
    return results


def compressor_summary(settings: CompressorSettings) -> dict[str, str]:
    """Create a human-readable summary of compressor settings."""
    return {
        "Plugin": settings.plugin_name,
        "Threshold": f"{settings.threshold:.1f} dB",
        "Ratio": f"{settings.ratio:.1f}:1",
        "Attack": f"{settings.attack:.1f} ms",
        "Release": f"{settings.release:.1f} ms",
        "Makeup": f"{settings.makeup_gain:.1f} dB",
    }
