"""Binary .cpr file parser for Cubase projects.

Extracts track structure, plugin chains, EQ bands, compressor settings,
audio references, tempo, and other project metadata from binary .cpr files.

The parser is composed of domain-specific extractor mixins:
- MetadataExtractor: version, sample rate, tempo, bit depth, time signature, transport
- TrackExtractor: channel strips, classification, dedup, folders, colors
- PluginExtractor: VST3 plugins, PresetChunkXMLTree, presets, dedup
- MixerExtractor: volume, pan, mute, solo, monitor, routing, sends
- MediaExtractor: audio references, markers, automation, MIDI
"""

from __future__ import annotations

import logging
from pathlib import Path

from cubasetools.core.extractors import (
    MediaExtractor,
    MetadataExtractor,
    MixerExtractor,
    PluginExtractor,
    TrackExtractor,
)
from cubasetools.core.models import (
    CubaseProject,
    Track,
    TrackType,
)

logger = logging.getLogger(__name__)


class CprParser(
    MetadataExtractor,
    TrackExtractor,
    PluginExtractor,
    MixerExtractor,
    MediaExtractor,
):
    """Parser for Cubase .cpr binary project files.

    Composes domain-specific extractor mixins. Shared state accessed by
    all mixins via self: data, project, _track_positions, _preset_chunk_data.
    """

    def __init__(self, cpr_path: Path):
        self.path = cpr_path
        self.data = b""
        self.project = CubaseProject(file_path=cpr_path)
        self._track_positions: list[tuple[Track, int]] = []
        # PresetChunkXMLTree data indexed by position for merging
        self._preset_chunk_data: dict[int, PluginInstance] = {}

    def parse(self) -> CubaseProject:
        """Parse the .cpr file and return a CubaseProject."""
        with open(self.path, "rb") as f:
            self.data = f.read()

        self.project.file_size = len(self.data)
        self.project.project_name = self.path.stem

        self._extract_version()
        self._extract_sample_rate()
        self._extract_bit_depth()
        self._extract_tempo()
        self._extract_time_signature()
        self._extract_transport()
        self._extract_tracks()
        self._extract_audio_references()
        self._extract_plugins()
        self._extract_plugin_presets()
        self._extract_markers()
        bus_table = self._build_bus_uid_table()
        self._extract_routing(bus_table)
        self._extract_sends(bus_table)
        self._extract_audio_per_track()
        self._extract_volume_pan()
        self._extract_mute_solo()
        self._extract_monitor()
        self._extract_track_colors()
        self._extract_folder_hierarchy()
        self._extract_automation()
        self._extract_midi()
        self._postprocess()

        return self.project

    # ── Post-processing ──────────────────────────────────────────────────

    def _postprocess(self):
        """Global deduplication and filtering after all parsing is complete.

        1. Remove self-reference plugins (plugin name == track name)
        2. Global dedup: merge same-name tracks, keeping the one with best data
        3. Filter out binary artifacts and empty non-structural tracks
        """
        # Step 1: Remove self-reference plugins from all tracks
        for track in self.project.tracks:
            track.plugins = [
                p for p in track.plugins
                if p.name.lower() != track.name.lower()
            ]

        # Step 2: Global dedup by track name
        best_by_name: dict[str, Track] = {}
        for track in self.project.tracks:
            key = track.name
            existing = best_by_name.get(key)
            if existing is None:
                best_by_name[key] = track
            else:
                # Keep the one with more plugin data
                existing_score = _track_score(existing)
                new_score = _track_score(track)
                if new_score > existing_score:
                    best_by_name[key] = track
                elif new_score == existing_score and new_score > 0:
                    # Same score, merge plugins (avoid duplicates)
                    existing_names = {p.name for p in existing.plugins}
                    for p in track.plugins:
                        if p.name not in existing_names:
                            existing.plugins.append(p)

        deduped = list(best_by_name.values())

        # Step 3: Filter artifacts and classify
        filtered: list[Track] = []
        for track in deduped:
            if not any(c.isalpha() for c in track.name):
                continue
            if len(track.name) < 3 and not track.plugins:
                continue
            if _is_binary_artifact(track.name):
                continue

            filtered.append(track)

        # Step 4: Determine content status and filter empty tracks
        final: list[Track] = []
        for track in filtered:
            if track.audio_files:
                track.has_content = True
            elif track.track_type in (TrackType.INSTRUMENT, TrackType.MIDI):
                track.has_content = True
            elif track.track_type in (
                TrackType.GROUP, TrackType.FX, TrackType.MASTER,
                TrackType.AUDIO,
            ):
                track.has_content = True

            if not track.has_content and not track.plugins:
                continue

            final.append(track)

        # Step 5: Reassign indices
        for i, track in enumerate(final):
            track.index = i
            for j, plugin in enumerate(track.plugins):
                plugin.slot_index = j

        self.project.tracks = final


# ── Helpers ──────────────────────────────────────────────────────────────

def _track_score(track: Track) -> int:
    """Score a track by how much useful data it has."""
    score = len(track.plugins)
    for p in track.plugins:
        score += len(p.eq_bands)
        score += len(p.parameters)
        if p.compressor:
            score += 2
    return score


def _is_binary_artifact(name: str) -> bool:
    """Check if a name looks like binary garbage rather than a real track name."""
    artifacts = {
        "aLoC", "daPN", "shtE", "DILT", "braF", "dpxE", "oloS",
        "sklC", "iCVT", "BuTT", "BlTT", "kcoL", "adcn", "Pler", "GLFX",
        "TDRH", "IVffO", "CmArray", "CmContainer", "BaSE", "mAsT",
    }
    return name in artifacts


def parse_cpr(cpr_path: Path) -> CubaseProject:
    """Convenience function to parse a .cpr file."""
    parser = CprParser(cpr_path)
    return parser.parse()
