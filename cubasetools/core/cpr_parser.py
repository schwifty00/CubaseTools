"""Binary .cpr file parser for Cubase projects.

Extracts track structure, plugin chains, EQ bands, compressor settings,
audio references, tempo, and other project metadata from binary .cpr files.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from cubasetools.core.constants import (
    TRACK_MARKERS,
    VERSION_MARKERS,
)
from cubasetools.core.models import (
    CubaseProject,
    Marker,
    PluginInstance,
    Track,
    TrackType,
)
from cubasetools.core.plugin_registry import interpret_plugin_parameters

# VST3 built-in channel components (not user plugins)
_BUILTIN_PLUGINS = frozenset({
    "Standard Panner", "Stereo Combined Panner", "Input Filter", "EQ",
    "Mono Panner", "Surround Panner", "Sampler Track",
})


class CprParser:
    """Parser for Cubase .cpr binary project files."""

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
        self._extract_tempo()
        self._extract_tracks()
        self._extract_audio_references()
        self._extract_plugins()
        self._extract_markers()
        self._postprocess()

        return self.project

    # ── Metadata extraction ──────────────────────────────────────────────

    def _extract_version(self):
        """Find Cubase version string."""
        for marker in VERSION_MARKERS:
            pos = self.data.find(marker)
            if pos != -1:
                end = self.data.find(b"\x00", pos)
                if end != -1 and end - pos < 50:
                    self.project.cubase_version = self.data[pos:end].decode(
                        "utf-8", errors="ignore"
                    )
                    return

    def _extract_sample_rate(self):
        """Try to find sample rate."""
        known_rates = [44100, 48000, 88200, 96000, 176400, 192000]
        for marker in [b"SampleRate", b"Record Format", b"SRateForAudioIO"]:
            pos = self.data.find(marker)
            if pos == -1:
                continue
            region = self.data[pos : pos + 100]
            for rate in known_rates:
                if struct.pack("<I", rate) in region or struct.pack(">I", rate) in region:
                    self.project.sample_rate = rate
                    return

    def _extract_tempo(self):
        """Try to extract tempo from the project."""
        for marker in [b"TempoEvent", b"MTempoTrackEvent"]:
            pos = self.data.find(marker)
            if pos == -1:
                continue
            region = self.data[pos : pos + 200]
            for offset in range(0, len(region) - 8, 4):
                try:
                    val = struct.unpack_from("<d", region, offset)[0]
                    if 30.0 < val < 300.0:
                        self.project.tempo = round(val, 2)
                        return
                except struct.error:
                    continue

    # ── Track extraction ─────────────────────────────────────────────────

    def _extract_tracks(self):
        """Extract track entries from binary data.

        Primary strategy: MixerChannel strip definitions detected via
        Name...String...TRACKNAME...InputFilter pattern.
        Fallback: legacy MAudioTrackEvent etc. markers.
        """
        strips = self._extract_channel_strips()

        if strips:
            deduped = self._deduplicate_strips(strips)
            # Filter out hardware I/O channels (stored in a separate section
            # at the end of the file with a large gap before them).
            # Only keep "Stereo Out" from that section.
            filtered = self._filter_io_section(deduped)
            for track, pos in filtered:
                track.index = len(self.project.tracks)
                self.project.tracks.append(track)
                self._track_positions.append((track, pos))
        else:
            self._extract_legacy_tracks()

    def _filter_io_section(
        self, strips: list[tuple[Track, int]]
    ) -> list[tuple[Track, int]]:
        """Remove hardware I/O channels, keeping only Stereo Out."""
        if len(strips) < 2:
            return strips

        # Find the gap: if distance between consecutive strips > 1MB,
        # everything after the gap is the I/O section
        result: list[tuple[Track, int]] = []
        io_start = None

        for i in range(len(strips) - 1):
            _, pos_a = strips[i]
            _, pos_b = strips[i + 1]
            if pos_b - pos_a > 1_000_000:
                io_start = i + 1
                break

        if io_start is None:
            return strips  # No gap found, keep all

        # Keep everything before the gap
        result = strips[:io_start]

        # From the I/O section, only keep Stereo Out
        for track, pos in strips[io_start:]:
            if track.name.lower() in ("stereo out", "master", "main out"):
                result.append((track, pos))

        return result

    def _extract_channel_strips(self) -> list[tuple[Track, int]]:
        """Find MixerChannel strip definitions.

        Each channel strip in Cubase has: Name -> String -> TRACKNAME -> Type -> InputFilter
        This pattern captures every mixer channel including sub-tracks within groups.
        Also specifically detects Stereo Out / master bus.
        """
        pattern = rb'Name\x00.{0,20}?String\x00.{0,10}?([\x20-\x7e]{2,50})\x00.{0,30}?Type\x00.{0,20}?InputFilter'
        results: list[tuple[Track, int]] = []

        for m in re.finditer(pattern, self.data, re.DOTALL):
            pos = m.start()
            name = m.group(1).decode("utf-8", errors="ignore").strip()
            if not name or len(name) < 2:
                continue

            track = Track(name=name)
            track.track_type = _classify_track_type(name)
            results.append((track, pos))

        return results

    def _deduplicate_strips(
        self, strips: list[tuple[Track, int]]
    ) -> list[tuple[Track, int]]:
        """Remove duplicate channel strips (same name within 40KB = same track).

        Cubase stores channel definitions twice in some cases.
        Entries further apart (>40KB) are kept as separate channels,
        since they likely contain different plugin chains.
        """
        strips.sort(key=lambda x: x[1])
        deduped: list[tuple[Track, int]] = []
        seen: dict[str, int] = {}  # name -> last position

        for track, pos in strips:
            prev_pos = seen.get(track.name)
            if prev_pos is not None and pos - prev_pos < 40_000:
                continue  # Skip duplicate
            seen[track.name] = pos
            deduped.append((track, pos))

        return deduped

    def _extract_legacy_tracks(self):
        """Fallback: extract tracks using MAudioTrackEvent etc. markers."""
        raw_tracks: list[tuple[int, str, bytes]] = []

        for marker_bytes, track_type_str in TRACK_MARKERS.items():
            for match in re.finditer(re.escape(marker_bytes), self.data):
                raw_tracks.append((match.start(), track_type_str, marker_bytes))

        raw_tracks.sort(key=lambda x: x[0])

        for pos, track_type_str, marker_bytes in raw_tracks:
            track = Track()
            try:
                track.track_type = TrackType(track_type_str)
            except ValueError:
                track.track_type = TrackType.UNKNOWN
            track.index = len(self.project.tracks)

            name = self._extract_nearby_string(pos + len(marker_bytes))
            if name:
                track.name = name
            else:
                track.name = f"{track_type_str.title()} {track.index + 1}"

            self.project.tracks.append(track)
            self._track_positions.append((track, pos))

    def _extract_nearby_string(self, pos: int) -> str:
        """Try to extract a meaningful string near a binary position."""
        search_end = min(pos + 500, len(self.data))
        region = self.data[pos:search_end]

        for m in re.finditer(rb'((?:[^\x00\x01-\x1f]\x00){3,50})', region):
            try:
                decoded = m.group(1).decode("utf-16-le", errors="ignore").strip()
                if (
                    decoded
                    and len(decoded) >= 2
                    and len(decoded) <= 80
                    and not decoded.startswith(("MTrack", "MAudio", "MInstr", "MSampl", "MMidi", "MFX", "MGroup"))
                    and any(c.isalpha() for c in decoded)
                ):
                    return decoded
            except (UnicodeDecodeError, ValueError):
                continue
        return ""

    # ── Audio references ─────────────────────────────────────────────────

    def _extract_audio_references(self):
        """Extract all referenced audio filenames."""
        referenced: set[str] = set()

        for match in re.finditer(rb'([\w\-\. ]+\.wav)', self.data, re.IGNORECASE):
            name = match.group(1).decode("utf-8", errors="ignore").strip()
            if name and len(name) > 4:
                referenced.add(name.lower())

        for match in re.finditer(
            rb'((?:[\w\-\. ]\x00)+w\x00a\x00v\x00)', self.data, re.IGNORECASE
        ):
            try:
                name = match.group(1).decode("utf-16-le", errors="ignore").strip()
                if name and len(name) > 4:
                    referenced.add(name.lower())
            except (UnicodeDecodeError, ValueError):
                continue

        for ext in [b"mp3", b"flac", b"aif", b"aiff", b"ogg", b"m4a"]:
            pattern = rb'([\w\-\. ]+\.' + ext + rb')'
            for match in re.finditer(pattern, self.data, re.IGNORECASE):
                name = match.group(1).decode("utf-8", errors="ignore").strip()
                if name and len(name) > 4:
                    referenced.add(name.lower())

        self.project.referenced_audio = referenced

    # ── Plugin extraction ────────────────────────────────────────────────

    def _extract_plugins(self):
        """Extract plugins using two sources and merge them.

        1. VST3 'Plugin Name' entries - finds ALL plugins (FabFilter, Steinberg, Waves, etc.)
        2. PresetChunkXMLTree blocks - provides parameter values for Waves plugins
        """
        # Step 1: Index PresetChunkXMLTree data by position for parameter merging
        self._index_preset_chunk_data()

        # Step 2: Extract all user plugins via VST3 Plugin Name pattern
        plugins_with_pos = self._extract_vst3_plugins()

        # Step 3: Deduplicate
        deduped = self._deduplicate_plugins(plugins_with_pos)

        # Step 4: Assign to tracks
        self._assign_plugins_to_tracks(deduped)

    def _index_preset_chunk_data(self):
        """Parse PresetChunkXMLTree blocks and index them by position.

        These blocks contain parameter values for Waves/SSL plugins.
        They are merged with the corresponding VST3 Plugin Name entries.
        """
        pattern = rb'PresetChunkXMLTree[^>]*>'
        for match in re.finditer(pattern, self.data):
            pos = match.start()
            region = self.data[pos : pos + 5000]

            pn_match = re.search(rb'<PluginName>([^<]+)</PluginName>', region)
            if not pn_match:
                continue

            plugin_name = pn_match.group(1).decode("utf-8", errors="ignore")

            preset_name = ""
            preset_match = re.search(rb'<Preset\s+Name="([^"]*)"', region)
            if preset_match:
                preset_name = preset_match.group(1).decode("utf-8", errors="ignore")

            plugin = PluginInstance(name=plugin_name)

            # Extract RealWorld parameters from active Setup A
            rw_match = re.search(
                rb'<PresetData\s+Setup="SETUP_A"[^>]*>\s*<Parameters\s+Type="RealWorld">\s*([^<]+)</Parameters>',
                region,
            )
            if rw_match:
                raw_params = rw_match.group(1).decode("utf-8", errors="ignore").strip()
                values = _parse_realworld_params(raw_params)
                _interpret_realworld(plugin, plugin_name, values, preset_name)

            # Fallback: XML attribute-based params
            if not plugin.parameters and not plugin.eq_bands and not plugin.compressor:
                for param_match in re.finditer(
                    rb'<(\w+)\s+[^>]*?(?:name|Name)="([^"]+)"[^>]*?(?:value|Value)="([^"]+)"',
                    region,
                ):
                    param_name = param_match.group(2).decode("utf-8", errors="ignore")
                    try:
                        param_val = float(param_match.group(3).decode("utf-8", errors="ignore"))
                        plugin.parameters[param_name] = param_val
                    except ValueError:
                        pass
                if plugin.parameters:
                    interpret_plugin_parameters(plugin)

            self._preset_chunk_data[pos] = plugin

    def _extract_vst3_plugins(self) -> list[tuple[PluginInstance, int]]:
        """Extract all user plugins from VST3 'Plugin Name' entries."""
        results: list[tuple[PluginInstance, int]] = []

        for m in re.finditer(rb'Plugin Name\x00', self.data):
            pos = m.start()
            after = self.data[pos + 12 : pos + 100]
            name_match = re.match(rb'.{0,8}?([\x20-\x7e]{2,50})', after)
            if not name_match:
                continue

            plugin_name = name_match.group(1).decode("utf-8", errors="ignore").strip()

            if plugin_name in _BUILTIN_PLUGINS:
                continue

            # Only process insert plugins (preceded by 'Slot' or 'Bay Program')
            before = self.data[max(0, pos - 300) : pos]
            is_insert = b'Slot\x00' in before or b'Bay Program\x00' in before

            plugin = PluginInstance(name=plugin_name)

            # Try to merge with PresetChunkXMLTree data (for Waves plugins)
            merged = self._merge_preset_data(plugin, pos)
            if merged:
                plugin = merged

            # Mark non-insert plugins but still include them
            if not is_insert:
                # These might be secondary references; skip if we already
                # found this plugin as an INSERT nearby
                results.append((plugin, pos))
            else:
                results.append((plugin, pos))

        return results

    def _merge_preset_data(
        self, plugin: PluginInstance, vst3_pos: int
    ) -> PluginInstance | None:
        """Try to find matching PresetChunkXMLTree data for a VST3 plugin entry."""
        # Normalize names for matching: "SSLEQ Mono" -> "SSLEQ", "SSLChannel Stereo" -> "SSLChannel"
        base_name = plugin.name.replace(" Mono", "").replace(" Stereo", "")
        base_name = base_name.replace(" Mono/Stereo", "")

        # Search within ±5000 bytes for matching PresetChunkXMLTree data
        for chunk_pos, chunk_plugin in self._preset_chunk_data.items():
            if abs(chunk_pos - vst3_pos) > 5000:
                continue
            chunk_base = chunk_plugin.name.replace(" Mono", "").replace(" Stereo", "")
            if chunk_base == base_name:
                # Merge: use VST3 name but PresetChunkXMLTree parameters
                merged = PluginInstance(name=plugin.name)
                merged.eq_bands = chunk_plugin.eq_bands
                merged.compressor = chunk_plugin.compressor
                merged.parameters = chunk_plugin.parameters
                merged.bypassed = chunk_plugin.bypassed
                return merged

        return None

    def _deduplicate_plugins(
        self, plugins: list[tuple[PluginInstance, int]]
    ) -> list[tuple[PluginInstance, int]]:
        """Remove duplicate plugin entries.

        VST3 plugins may appear twice: once as INSERT (in Slot context)
        and once as 'other' (secondary reference). Keep the one with more data.
        Also handles Cubase storing editor + processor states.
        """
        if not plugins:
            return []

        plugins.sort(key=lambda x: x[1])

        deduped: list[tuple[PluginInstance, int]] = []
        i = 0
        while i < len(plugins):
            current_plugin, current_pos = plugins[i]
            best = current_plugin
            best_pos = current_pos

            j = i + 1
            while j < len(plugins):
                next_plugin, next_pos = plugins[j]
                if next_pos - current_pos > 20000:
                    break
                # Normalize names for comparison
                cur_base = current_plugin.name.replace(" Mono", "").replace(" Stereo", "").replace(" Mono/Stereo", "")
                next_base = next_plugin.name.replace(" Mono", "").replace(" Stereo", "").replace(" Mono/Stereo", "")
                if next_base == cur_base:
                    # Keep the one with more parameter data
                    best_score = len(best.parameters) + len(best.eq_bands) + (1 if best.compressor else 0)
                    next_score = len(next_plugin.parameters) + len(next_plugin.eq_bands) + (1 if next_plugin.compressor else 0)
                    if next_score > best_score:
                        best = next_plugin
                        best_pos = next_pos
                    j += 1
                else:
                    break

            deduped.append((best, best_pos))
            i = j if j > i + 1 else i + 1

        return deduped

    def _assign_plugins_to_tracks(
        self, plugins: list[tuple[PluginInstance, int]]
    ):
        """Assign plugins to tracks based on binary position."""
        if not self._track_positions or not plugins:
            if plugins and not self.project.tracks:
                default_track = Track(name="Master", track_type=TrackType.MASTER, index=0)
                self.project.tracks.append(default_track)
                for plugin, _ in plugins:
                    plugin.slot_index = len(default_track.plugins)
                    default_track.plugins.append(plugin)
            return

        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])

        for plugin, plugin_pos in plugins:
            assigned_track = sorted_tracks[0][0]
            for track, track_pos in sorted_tracks:
                if track_pos <= plugin_pos:
                    assigned_track = track
                else:
                    break

            plugin.slot_index = len(assigned_track.plugins)
            assigned_track.plugins.append(plugin)

    # ── Markers ──────────────────────────────────────────────────────────

    def _extract_markers(self):
        """Extract markers from the project."""
        for match in re.finditer(rb'MMarkerEvent', self.data):
            pos = match.start()
            marker = Marker()
            marker.marker_id = len(self.project.markers) + 1

            name = self._extract_nearby_string(pos)
            if name:
                marker.name = name
            else:
                marker.name = f"Marker {marker.marker_id}"

            self.project.markers.append(marker)

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
                    # Merge: take plugins from the better entry
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
            # Skip binary artifacts (non-alphanumeric names, too short)
            if not any(c.isalpha() for c in track.name):
                continue
            if len(track.name) < 3 and not track.plugins:
                continue
            # Skip names that look like binary garbage
            if _is_binary_artifact(track.name):
                continue

            # Re-classify track type with full context (only for AUDIO,
            # since Group/FX/Instrument/Master were already classified correctly)
            if track.track_type == TrackType.AUDIO:
                track.track_type = _classify_track_type(track.name, has_plugins=bool(track.plugins))

            filtered.append(track)

        # Step 4: Reassign indices
        for i, track in enumerate(filtered):
            track.index = i
            for j, plugin in enumerate(track.plugins):
                plugin.slot_index = j

        self.project.tracks = filtered


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
    # Known binary artifacts found in .cpr files (reversed 4-byte markers etc.)
    artifacts = {
        "gITI", "aLoC", "daPN", "shtE", "DILT", "braF", "dpxE", "oloS",
        "sklC", "iCVT", "BuTT", "BlTT", "kcoL", "adcn", "Pler", "GLFX",
        "TDRH", "IVffO", "CmArray", "CmContainer", "BaSE", "mAsT",
    }
    return name in artifacts


# ── Track type classification ────────────────────────────────────────────

def _classify_track_type(name: str, has_plugins: bool = True) -> TrackType:
    """Classify track type from its name and context."""
    lower = name.lower()
    if lower in ("stereo out", "master", "main out"):
        return TrackType.MASTER
    if lower in ("stereo in", "mono in") or re.match(r"^mono in \d+$", lower):
        return TrackType.AUDIO
    if lower.startswith(("group", "groupchannel")):
        return TrackType.GROUP
    if any(kw in lower for kw in ("grp", "gruppe", "bus", " ny")):
        return TrackType.GROUP
    # Multi-word names ending in a group keyword
    if lower.endswith((" vocal", " vocals")):
        return TrackType.GROUP
    if any(kw in lower for kw in ("hall", "verb", "delay", "flanger", "chorus", "fx ", "breit", "parallel")):
        return TrackType.FX
    if any(kw in lower for kw in ("kontakt", "omnisphere", "diva", "retrologue", "beep", "omnivocal")):
        return TrackType.INSTRUMENT
    # Single-word generic names without plugins are typically group/folder channels
    # (e.g., "drums", "bass", "Keys", "vocals", "Sinti", "FX", "Samples")
    if not has_plugins and " " not in name and lower not in ("stereo out",):
        # Known group/folder names in German/English studio context
        group_names = {
            "drums", "bass", "keys", "gitarre", "guitar", "guitars",
            "vocals", "vox", "sinti", "strings", "synths", "pads",
            "samples", "percussion", "perc", "horns", "brass",
            "woodwinds", "fx", "effects", "master",
        }
        if lower in group_names:
            return TrackType.GROUP
    return TrackType.AUDIO


# ── RealWorld parameter parsing (Waves plugins) ─────────────────────────

def _parse_realworld_params(raw: str) -> list[float | None]:
    """Parse a RealWorld parameter string into a list of values.

    Values are space-separated floats; '*' means unused/default (None).
    """
    values: list[float | None] = []
    for token in raw.split():
        if token == "*":
            values.append(None)
        else:
            try:
                values.append(float(token))
            except ValueError:
                values.append(None)
    return values


def _rw(values: list[float | None], idx: int, default: float = 0.0) -> float:
    """Safely get a RealWorld parameter value."""
    if idx < len(values) and values[idx] is not None:
        return values[idx]
    return default


def _interpret_realworld(
    plugin: PluginInstance,
    plugin_name: str,
    values: list[float | None],
    preset_name: str = "",
) -> None:
    """Interpret RealWorld parameter arrays for known plugins."""
    from cubasetools.core.models import CompressorSettings, EQBand, EQBandType

    if plugin_name == "SSLEQ":
        bands = [
            EQBand(
                enabled=_rw(values, 0) > 0.5,
                band_type=EQBandType.PEAK if _rw(values, 1) > 0.5 else EQBandType.LOW_SHELF,
                frequency=_rw(values, 2, 60.0),
                gain=_rw(values, 4),
                q=1.0,
            ),
            EQBand(
                enabled=True,
                band_type=EQBandType.PEAK,
                frequency=_rw(values, 5, 200.0),
                gain=_rw(values, 8),
                q=_rw(values, 9, 0.5),
            ),
            EQBand(
                enabled=True,
                band_type=EQBandType.PEAK,
                frequency=_rw(values, 14, 3.5) * 1000,
                gain=_rw(values, 13),
                q=_rw(values, 10, 2.5),
            ),
            EQBand(
                enabled=_rw(values, 16) > 0.5,
                band_type=EQBandType.HIGH_SHELF,
                frequency=_rw(values, 18, 8.0) * 1000,
                gain=_rw(values, 17),
                q=1.0,
            ),
        ]
        plugin.eq_bands = [b for b in bands if b.gain != 0.0 or b.enabled]
        plugin.parameters["Output Trim"] = _rw(values, 19)

    elif plugin_name == "SSLChannel":
        if len(values) > 24:
            bands = [
                EQBand(
                    enabled=True,
                    band_type=EQBandType.LOW_SHELF,
                    frequency=_rw(values, 15, 60.0),
                    gain=_rw(values, 16),
                    q=1.0,
                ),
                EQBand(
                    enabled=True,
                    band_type=EQBandType.PEAK,
                    frequency=_rw(values, 18, 2.5) * 1000,
                    gain=_rw(values, 19),
                    q=_rw(values, 17, 0.5),
                ),
                EQBand(
                    enabled=True,
                    band_type=EQBandType.PEAK,
                    frequency=_rw(values, 20, 3.5) * 1000,
                    gain=_rw(values, 22),
                    q=_rw(values, 21, 1.5),
                ),
                EQBand(
                    enabled=True,
                    band_type=EQBandType.HIGH_SHELF,
                    frequency=_rw(values, 24, 8.0) * 1000,
                    gain=_rw(values, 23),
                    q=1.0,
                ),
            ]
            plugin.eq_bands = [b for b in bands if b.gain != 0.0]

        comp_thresh = _rw(values, 0)
        if comp_thresh < 0:
            plugin.compressor = CompressorSettings(
                plugin_name=plugin_name,
                threshold=comp_thresh,
                release=_rw(values, 3),
            )

    elif plugin_name in ("CLA-76", "CLA76"):
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            input_gain=_rw(values, 0),
            output_gain=_rw(values, 1),
            attack=_rw(values, 2),
            release=_rw(values, 3),
            ratio=4.0,
        )
        if preset_name:
            plugin.parameters["Preset"] = 0
            plugin.compressor.raw_parameters["preset_name"] = preset_name  # type: ignore[assignment]

    elif plugin_name in ("CLA-2A", "CLA2A"):
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            threshold=_rw(values, 0),
            output_gain=_rw(values, 1),
        )

    elif plugin_name == "C1Comp":
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            threshold=_rw(values, 17),
            ratio=_rw(values, 18, 1.0),
            attack=_rw(values, 0, 0.01),
        )

    elif plugin_name == "DeEsser":
        plugin.parameters["Frequency"] = _rw(values, 0, 5500)
        plugin.parameters["Threshold"] = _rw(values, 2)

    else:
        for i, v in enumerate(values[:20]):
            if v is not None:
                plugin.parameters[f"Param_{i}"] = v


def parse_cpr(cpr_path: Path) -> CubaseProject:
    """Convenience function to parse a .cpr file."""
    parser = CprParser(cpr_path)
    return parser.parse()
