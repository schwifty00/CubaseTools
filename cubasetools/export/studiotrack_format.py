"""StudioTrack-compatible JSON export format.

Produces a JSON schema designed to complement StudioTrack's audio analysis
with Cubase project structure data (plugin chains, EQ, compression).
"""

from __future__ import annotations

import json
from pathlib import Path

from cubasetools.core.models import CubaseProject


def to_studiotrack_format(project: CubaseProject) -> dict:
    """Convert a CubaseProject to StudioTrack-compatible JSON.

    Schema designed so StudioTrack can display:
    - What plugins were used on each track
    - EQ decisions (frequency/gain per band)
    - Compression settings
    - Project metadata (tempo, sample rate)
    """
    tracks = []
    for track in project.tracks:
        track_data: dict = {
            "name": track.name,
            "type": track.track_type.value,
            "signal_chain": [],
        }

        # Routing info
        if track.output_bus:
            track_data["output_bus"] = track.output_bus

        # Send effects
        if track.sends:
            track_data["sends"] = [
                {
                    "target": s.target_name,
                    "level_db": s.level_db,
                    "enabled": s.enabled,
                }
                for s in track.sends
            ]

        # Audio files on this track
        if track.audio_files:
            track_data["audio_files"] = track.audio_files

        for plugin in track.plugins:
            plugin_data: dict = {
                "plugin_name": plugin.name,
                "vendor": plugin.vendor,
                "bypassed": plugin.bypassed,
                "slot": plugin.slot_index,
            }

            # EQ data in a normalized format
            if plugin.eq_bands:
                plugin_data["eq"] = {
                    "bands": [
                        {
                            "enabled": b.enabled,
                            "type": b.band_type.value,
                            "freq_hz": round(b.frequency, 1),
                            "gain_db": round(b.gain, 2),
                            "q": round(b.q, 3),
                        }
                        for b in plugin.eq_bands
                    ]
                }

            # Compressor data normalized
            if plugin.compressor:
                c = plugin.compressor
                plugin_data["compressor"] = {
                    "threshold_db": round(c.threshold, 1),
                    "ratio": round(c.ratio, 1),
                    "attack_ms": round(c.attack, 1),
                    "release_ms": round(c.release, 1),
                    "knee_db": round(c.knee, 1),
                    "makeup_db": round(c.makeup_gain, 1),
                }

            track_data["signal_chain"].append(plugin_data)

        tracks.append(track_data)

    return {
        "schema_version": "1.0",
        "source": "CubaseTools",
        "project": {
            "name": project.project_name,
            "cubase_version": project.cubase_version,
            "sample_rate": project.sample_rate,
            "bit_depth": project.bit_depth,
            "tempo_bpm": project.tempo,
            "time_signature": project.time_signature,
        },
        "tracks": tracks,
        "summary": {
            "total_tracks": project.track_count,
            "total_plugins": project.plugin_count,
            "audio_tracks": project.audio_track_count,
            "referenced_files": len(project.referenced_audio),
        },
    }


def export_studiotrack_json(project: CubaseProject, output_path: Path):
    """Export project in StudioTrack-compatible format."""
    data = to_studiotrack_format(project)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
