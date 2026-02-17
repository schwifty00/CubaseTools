"""Export CubaseProject data to JSON."""

from __future__ import annotations

import json
from pathlib import Path

from cubasetools.core.models import CubaseProject, EQBandType, TrackType


def project_to_dict(project: CubaseProject) -> dict:
    """Convert a CubaseProject to a serializable dict."""
    return {
        "project_name": project.project_name,
        "file_path": str(project.file_path),
        "cubase_version": project.cubase_version,
        "sample_rate": project.sample_rate,
        "bit_depth": project.bit_depth,
        "tempo": project.tempo,
        "time_signature": project.time_signature,
        "file_size": project.file_size,
        "track_count": project.track_count,
        "plugin_count": project.plugin_count,
        "referenced_audio": sorted(project.referenced_audio),
        "tracks": [_track_to_dict(t) for t in project.tracks],
        "markers": [
            {"name": m.name, "position": m.position, "id": m.marker_id}
            for m in project.markers
        ],
    }


def _track_to_dict(track) -> dict:
    return {
        "name": track.name,
        "type": track.track_type.value,
        "index": track.index,
        "volume": track.volume,
        "pan": track.pan,
        "muted": track.muted,
        "solo": track.solo,
        "plugins": [_plugin_to_dict(p) for p in track.plugins],
    }


def _plugin_to_dict(plugin) -> dict:
    result = {
        "name": plugin.name,
        "vendor": plugin.vendor,
        "slot_index": plugin.slot_index,
        "bypassed": plugin.bypassed,
        "parameters": plugin.parameters,
    }

    if plugin.eq_bands:
        result["eq_bands"] = [
            {
                "enabled": b.enabled,
                "type": b.band_type.value,
                "frequency": b.frequency,
                "gain": b.gain,
                "q": b.q,
            }
            for b in plugin.eq_bands
        ]

    if plugin.compressor:
        c = plugin.compressor
        result["compressor"] = {
            "plugin_name": c.plugin_name,
            "threshold": c.threshold,
            "ratio": c.ratio,
            "attack": c.attack,
            "release": c.release,
            "knee": c.knee,
            "makeup_gain": c.makeup_gain,
            "input_gain": c.input_gain,
            "output_gain": c.output_gain,
        }

    return result


def export_project_json(project: CubaseProject, output_path: Path):
    """Export a project to a JSON file."""
    data = project_to_dict(project)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def export_projects_json(projects: list[CubaseProject], output_path: Path):
    """Export multiple projects to a single JSON file."""
    data = {
        "export_version": "1.0",
        "project_count": len(projects),
        "projects": [project_to_dict(p) for p in projects],
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
