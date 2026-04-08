"""Binary .cpr file parser for Cubase projects.

Extracts track structure, plugin chains, EQ bands, compressor settings,
audio references, tempo, and other project metadata from binary .cpr files.
"""

from __future__ import annotations

import math
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

from cubasetools.core.constants import (
    TRACK_MARKERS,
    VERSION_MARKERS,
)
from cubasetools.core.models import (
    AutomationLane,
    AutomationPoint,
    CubaseProject,
    Marker,
    MidiNote,
    MidiPart,
    PluginInstance,
    SendSlot,
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

    # ── Metadata extraction ──────────────────────────────────────────────

    def _extract_version(self):
        """Find Cubase version string.

        Two formats:
        - Modern (Cubase 12+): 'Version NN.N.N\\x00' in the file header
        - Legacy: 'Cubase NN\\x00' ASCII markers
        """
        # Modern format: "Version X.Y.Z" near start of file
        vm = re.search(rb'Version (\d+\.\d+\.\d+)\x00', self.data[:2000])
        if vm:
            ver_num = vm.group(1).decode("utf-8", errors="ignore")
            self.project.cubase_version = f"Cubase {ver_num}"
            return

        # Legacy format: "Cubase 10" etc.
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
        """Try to find sample rate.

        Modern Cubase stores sample rate as a BE double in a 'Float' sub-field
        within the binary SampleRate structure (not in XML preset data).
        Falls back to int32 search.
        """
        known_rates = [44100, 48000, 88200, 96000, 176400, 192000]

        # Search ALL SampleRate occurrences, skip XML ones
        for m in re.finditer(rb'SampleRate', self.data):
            pos = m.start()
            after = self.data[pos : pos + 30]
            # Skip XML occurrences (contain > or < nearby)
            if b'>' in after[:15] or b'<' in after[:15]:
                continue
            region = self.data[pos : pos + 200]
            float_match = re.search(
                rb'Float\x00\x00\x04(.{8})', region, re.DOTALL
            )
            if float_match:
                val = struct.unpack(">d", float_match.group(1))[0]
                rounded = int(round(val))
                if rounded in known_rates:
                    self.project.sample_rate = rounded
                    return
            # Legacy: int32 near this marker
            for rate in known_rates:
                if struct.pack("<I", rate) in region or struct.pack(">I", rate) in region:
                    self.project.sample_rate = rate
                    return

    def _extract_tempo(self):
        """Try to extract tempo from the project.

        Strategy 1: Find MTempoEvent with a BPM named-field double.
        Strategy 2: Scan MTempoTrackEvent header for embedded BPM double.
        Strategy 3: MusicalTempo media attribute (audio file tempo tag).
        If none finds a value, the project uses the default 120 BPM.
        """
        # Strategy 1: MTempoEvent > BPM named field (most reliable)
        m = re.search(
            rb'MTempoEvent.*?BPM\x00\x00\x04(.{8})',
            self.data,
            re.DOTALL,
        )
        if m:
            val = struct.unpack(">d", m.group(1))[0]
            if 20.0 < val < 400.0:
                self.project.tempo = round(val, 2)
                return

        # Strategy 2: Scan MTempoTrackEvent header for embedded double
        pos = self.data.find(b"MTempoTrackEvent")
        if pos != -1:
            region = self.data[pos : pos + 500]
            for offset in range(17, len(region) - 8):
                val = struct.unpack_from(">d", region, offset)[0]
                if 20.0 < val < 400.0:
                    self.project.tempo = round(val, 2)
                    return

        # Strategy 3: MusicalTempo media attribute as fallback
        m = re.search(
            rb'MusicalTempo.*?Float\x00\x00\x04(.{8})',
            self.data,
            re.DOTALL,
        )
        if m:
            val = struct.unpack(">d", m.group(1))[0]
            if 20.0 < val < 400.0:
                self.project.tempo = round(val, 1)
                return

    # ── Track extraction ─────────────────────────────────────────────────

    def _extract_tracks(self):
        """Extract track entries from binary data.

        Primary strategy: MixerChannel strip definitions detected via
        Name...String...TRACKNAME...InputFilter pattern, with track types
        determined from IDString entries (GroupChannel, FxChannel, Audio, etc.).
        Fallback: legacy MAudioTrackEvent etc. markers.
        """
        strips = self._extract_channel_strips()

        if strips:
            deduped = self._deduplicate_strips(strips)
            filtered = self._filter_io_section(deduped)

            # Classify track types using IDString binary markers
            self._classify_by_idstring(filtered)

            for track, pos in filtered:
                track.index = len(self.project.tracks)
                self.project.tracks.append(track)
                self._track_positions.append((track, pos))
        else:
            self._extract_legacy_tracks()

    def _find_channel_idstrings(self) -> list[tuple[int, str]]:
        """Find all channel type IDString entries in the binary data.

        Each mixer channel in Cubase has an IDString field identifying its type:
        GroupChannel, FxChannel, Audio, SamplerChannel, Synth, MidiChannel,
        InputChannel, OutputChannel. These are internal engine identifiers
        that are language/version independent.
        """
        results: list[tuple[int, str]] = []
        known_prefixes = (
            b"GroupChannel", b"FxChannel", b"Audio",
            b"SamplerChannel", b"Synth", b"MidiChannel",
            b"InputChannel", b"OutputChannel",
        )

        for m in re.finditer(rb'IDString\x00', self.data):
            pos = m.start()
            after = self.data[pos + 9 : pos + 60]
            sm = re.match(rb'.{0,8}?([\x20-\x7e]{3,40})', after)
            if sm:
                val = sm.group(1)
                if any(val.startswith(p) for p in known_prefixes):
                    results.append((pos, val.decode("latin-1")))

        results.sort()
        return results

    def _classify_by_idstring(
        self, strips: list[tuple[Track, int]]
    ) -> None:
        """Classify track types using IDString entries from the binary data.

        Algorithm: walk strips and IDStrings in position order. Each IDString
        is assigned to the most recent preceding strip. Strips without an
        IDString are inferred from their neighbors.
        """
        idstrings = self._find_channel_idstrings()
        if not idstrings:
            # No IDStrings found - fall back to name heuristics
            for track, _ in strips:
                track.track_type = _classify_track_type(track.name)
            return

        strips_sorted = sorted(strips, key=lambda x: x[1])

        # Step 1: Assign IDStrings to strips.
        # For each strip, find the first typed IDString between it and the
        # next strip. The IDString belongs to the strip that precedes it.
        strip_type_map: dict[int, str] = {}  # strip_pos -> idstring_value
        id_idx = 0

        for i, (_, strip_pos) in enumerate(strips_sorted):
            next_strip_pos = (
                strips_sorted[i + 1][1] if i + 1 < len(strips_sorted) else float("inf")
            )

            # Advance past IDStrings that are before/at this strip
            while id_idx < len(idstrings) and idstrings[id_idx][0] <= strip_pos:
                id_idx += 1

            # Find first typed IDString before the next strip
            for j in range(id_idx, len(idstrings)):
                id_pos, id_val = idstrings[j]
                if id_pos >= next_strip_pos:
                    break
                strip_type_map[strip_pos] = id_val
                break

        # Step 2: Infer types for unmapped strips from neighbors.
        # An unmapped strip between GroupChannel and FxChannel sections
        # gets inferred from the next mapped strip's type.
        for i, (_, strip_pos) in enumerate(strips_sorted):
            if strip_pos in strip_type_map:
                continue

            # Look forward for nearest mapped strip
            next_type = None
            for j in range(i + 1, len(strips_sorted)):
                npos = strips_sorted[j][1]
                if npos in strip_type_map:
                    next_type = strip_type_map[npos]
                    break

            # Look backward for nearest mapped strip
            prev_type = None
            for j in range(i - 1, -1, -1):
                ppos = strips_sorted[j][1]
                if ppos in strip_type_map:
                    prev_type = strip_type_map[ppos]
                    break

            # Prefer the next mapped type (boundary strip belongs to next section)
            if next_type:
                strip_type_map[strip_pos] = next_type
            elif prev_type:
                strip_type_map[strip_pos] = prev_type

        # Step 3: Apply classifications
        for track, strip_pos in strips:
            lower_name = track.name.lower()

            # Special case: master bus
            if lower_name in ("stereo out", "master", "main out"):
                track.track_type = TrackType.MASTER
                continue

            id_val = strip_type_map.get(strip_pos, "")

            if id_val.startswith("GroupChannel"):
                track.track_type = TrackType.GROUP
            elif id_val.startswith("FxChannel"):
                track.track_type = TrackType.FX
            elif id_val.startswith(("SamplerChannel", "Synth")):
                track.track_type = TrackType.INSTRUMENT
            elif id_val.startswith("OutputChannel"):
                track.track_type = TrackType.MASTER
            elif id_val.startswith("MidiChannel"):
                track.track_type = TrackType.MIDI
            elif id_val.startswith("Audio"):
                track.track_type = TrackType.AUDIO
            else:
                # No IDString - fall back to name heuristics
                track.track_type = _classify_track_type(track.name)

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
            # Track type will be set by _classify_by_section after dedup
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
            track.has_content = True  # legacy markers imply actual events

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
        """Extract all referenced audio filenames.

        Filenames can contain parentheses (e.g., 'Audio 02 (D)_18.wav'),
        hyphens, spaces, dots, and other common characters. The regex must
        be broad enough to capture the full filename.
        """
        referenced: set[str] = set()

        # UTF-8 .wav references — include () for Cubase duplicate suffixes
        # First char must be alphanumeric to avoid matching stray parentheses
        for match in re.finditer(rb'(\w[\w\-\. ()]*\.wav)', self.data, re.IGNORECASE):
            name = match.group(1).decode("utf-8", errors="ignore").strip()
            if name and len(name) > 4:
                referenced.add(name.lower())

        # UTF-16-LE .wav references
        for match in re.finditer(
            rb'(\w\x00(?:[\w\-\. ()]\x00)*w\x00a\x00v\x00)', self.data, re.IGNORECASE
        ):
            try:
                name = match.group(1).decode("utf-16-le", errors="ignore").strip()
                if name and len(name) > 4:
                    referenced.add(name.lower())
            except (UnicodeDecodeError, ValueError):
                continue

        # Other audio formats
        for ext in [b"mp3", b"flac", b"aif", b"aiff", b"ogg", b"m4a"]:
            pattern = rb'(\w[\w\-\. ()]*\.' + ext + rb')'
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
        """Extract markers from the project.

        Marker structure after the event header:
          - name_len (4 bytes) + name + null + BOM
          - color/type (4 bytes BE int32)
          - start position (4 bytes BE uint32, in PPQ ticks)
          - padding (4 bytes, zero)
          - end position (4 bytes BE uint32, for range markers)

        The name is found via regex between the event header and BOM.
        """
        for match in re.finditer(rb'MMarkerEvent', self.data):
            pos = match.start()
            region = self.data[pos : pos + 200]

            marker = Marker()
            marker.marker_id = len(self.project.markers) + 1

            # Extract name: look for string before BOM marker
            name_match = re.search(
                rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                region,
            )
            if name_match:
                marker.name = name_match.group(1).decode("utf-8", errors="ignore")
                # Position data follows BOM + 4 bytes after the name
                after_bom = region[name_match.end():]
                if len(after_bom) >= 8:
                    # Skip color/type (4 bytes), read start position
                    start_ticks = struct.unpack(">I", after_bom[4:8])[0]
                    marker.position = float(start_ticks)
            else:
                name = self._extract_nearby_string(pos)
                marker.name = name if name else f"Marker {marker.marker_id}"

            self.project.markers.append(marker)

    # ── Bus UID table, Routing, Sends, Audio per track ─────────────────

    def _build_bus_uid_table(self) -> dict[int, str]:
        """Build a lookup table mapping bus UIDs to track/bus names.

        Scans for OwnInputBus entries in the binary data. Each entry has a
        Name (the bus/track name) and a Bus UID (4-byte BE uint32).
        Returns {uid: name} dict.
        """
        table: dict[int, str] = {}

        for m in re.finditer(rb'OwnInputBus\x00', self.data):
            pos = m.start()
            region = self.data[pos : pos + 500]

            # Find the Name field — in OwnInputBus it's: Name\x00 + header + ASCII name\x00
            name_match = re.search(
                rb'Name\x00.{0,12}?([\x20-\x7e]{2,50})\x00',
                region,
                re.DOTALL,
            )
            if not name_match:
                continue
            bus_name = name_match.group(1).decode("utf-8", errors="ignore").strip()

            # Find Bus UID: pattern is "Bus UID\x00\x00\x01" + 4 zero bytes + 4 bytes UID
            uid_match = re.search(
                rb'Bus UID\x00\x00\x01\x00{4}(.{4})',
                region,
                re.DOTALL,
            )
            if not uid_match:
                continue
            uid = struct.unpack(">I", uid_match.group(1))[0]
            if uid != 0:
                table[uid] = bus_name

        return table

    def _extract_routing(self, bus_table: dict[int, str]) -> None:
        """Extract output routing for each track.

        Searches for OutputBusValue near each track's strip position and
        resolves the target UID via the bus table.
        """
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        if not sorted_tracks:
            return

        for i, (track, strip_pos) in enumerate(sorted_tracks):
            # Region: from this strip to the next strip (or +200KB)
            next_pos = (
                sorted_tracks[i + 1][1]
                if i + 1 < len(sorted_tracks)
                else strip_pos + 200_000
            )
            region_end = min(next_pos, strip_pos + 200_000, len(self.data))
            region = self.data[strip_pos : region_end]

            # Look for OutputBusValue -> Value\x00\x00\x01\x00\x00\x00\x00 + 4 bytes UID
            for obv in re.finditer(rb'OutputBus', region):
                after = region[obv.start() : obv.start() + 200]
                val_match = re.search(
                    rb'Value\x00\x00\x01\x00{4}(.{4})',
                    after,
                    re.DOTALL,
                )
                if val_match:
                    uid = struct.unpack(">I", val_match.group(1))[0]
                    if uid in bus_table:
                        track.output_bus = bus_table[uid]
                    break

    def _extract_sends(self, bus_table: dict[int, str]) -> None:
        """Extract send slots for each track.

        Searches for SendFolder within each track's region and extracts
        up to 8 send slots with target UID and volume.
        """
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        if not sorted_tracks:
            return

        for i, (track, strip_pos) in enumerate(sorted_tracks):
            next_pos = (
                sorted_tracks[i + 1][1]
                if i + 1 < len(sorted_tracks)
                else strip_pos + 200_000
            )
            region_end = min(next_pos, strip_pos + 200_000, len(self.data))
            region = self.data[strip_pos : region_end]

            sf_match = re.search(rb'SendFolder\x00', region)
            if not sf_match:
                continue

            # Search within SendFolder region (up to 10KB for 8 slots)
            send_region = region[sf_match.start() : sf_match.start() + 10240]

            # Each send slot has: Volume -> Value\x00\x00\x04[8 bytes BE double]
            #                     Output -> Value\x00\x00\x01\x00{4}[4 bytes UID]
            # Volume appears BEFORE Output in each slot.
            # Strategy: find each Volume, read the double, then find the next Output.
            vol_positions = [
                m.start() for m in re.finditer(rb'Volume\x00', send_region)
            ]
            out_positions = [
                m.start() for m in re.finditer(rb'Output\x00', send_region)
            ]

            for vol_pos in vol_positions:
                # Extract BE double: Volume\x00 + header + Value\x00\x00\x04 + 8 bytes
                vol_area = send_region[vol_pos : vol_pos + 40]
                dbl_match = re.search(
                    rb'Value\x00\x00\x04(.{8})', vol_area, re.DOTALL
                )
                if not dbl_match:
                    continue
                vol_val = struct.unpack(">d", dbl_match.group(1))[0]

                level_db = 0.0
                if vol_val > 0:
                    level_db = round(20.0 * math.log10(vol_val / 25856.0), 1) + 0.0

                # Find the next Output after this Volume
                uid = 0
                for out_pos in out_positions:
                    if out_pos > vol_pos:
                        out_area = send_region[out_pos : out_pos + 40]
                        uid_match = re.search(
                            rb'Value\x00\x00\x01\x00{4}(.{4})',
                            out_area,
                            re.DOTALL,
                        )
                        if uid_match:
                            uid = struct.unpack(">I", uid_match.group(1))[0]
                        break

                if uid == 0 or uid not in bus_table:
                    continue

                send = SendSlot(
                    target_name=bus_table[uid],
                    level_db=level_db,
                    enabled=True,
                )
                track.sends.append(send)

                if len(track.sends) >= 8:
                    break

    def _extract_audio_per_track(self) -> None:
        """Assign audio file references to their respective tracks.

        For each track region (between consecutive strip positions), find
        .wav references. Excludes the Pool area (after the Pool marker).
        """
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        if not sorted_tracks:
            return

        # Find Pool area start to exclude it
        pool_pos = self.data.find(b'Pool\x00')
        if pool_pos == -1:
            pool_pos = len(self.data)

        for i, (track, strip_pos) in enumerate(sorted_tracks):
            next_pos = (
                sorted_tracks[i + 1][1]
                if i + 1 < len(sorted_tracks)
                else pool_pos
            )
            # Don't search past the Pool area
            region_end = min(next_pos, pool_pos, len(self.data))
            if strip_pos >= pool_pos:
                continue

            region = self.data[strip_pos : region_end]
            audio_files: list[str] = []

            for wav_match in re.finditer(
                rb'(\w[\w\-\. ()]*\.wav)\x00', region, re.IGNORECASE
            ):
                name = wav_match.group(1).decode("utf-8", errors="ignore").strip()
                if len(name) > 4 and name not in audio_files:
                    audio_files.append(name)

            track.audio_files = audio_files

    # ── Time Signature ──────────────────────────────────────────────────

    def _extract_time_signature(self):
        """Extract time signature from TimeSignatureEvent entries.

        Structure: TimeSignatureEvent contains Numerator and Denominator
        fields as int64 values following the standard named-field encoding.
        """
        pos = self.data.find(b'TimeSignatureEvent')
        if pos == -1:
            return

        region = self.data[pos : pos + 300]

        num_match = re.search(
            rb'Numerator\x00\x00\x01(.{8})',
            region,
            re.DOTALL,
        )
        den_match = re.search(
            rb'Denominator\x00\x00\x01(.{8})',
            region,
            re.DOTALL,
        )

        if num_match and den_match:
            numerator = struct.unpack(">q", num_match.group(1))[0]
            denominator = struct.unpack(">q", den_match.group(1))[0]
            if 1 <= numerator <= 32 and denominator in (1, 2, 4, 8, 16, 32):
                self.project.time_signature = f"{numerator}/{denominator}"

    # ── Volume, Pan, Mute, Solo ─────────────────────────────────────────

    _VOLUME_UNITY = 25856.0  # 0 dB fader position
    _PAN_CENTER = 16383.5    # center pan position

    def _extract_volume_pan(self):
        """Extract fader volume and pan for each track.

        Volume: compound field with Value as BE double (0..32767, unity=25856)
        Pan: compound field with Value as BE double (0..32767, center=16383.5)
        """
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        if not sorted_tracks:
            return

        for i, (track, strip_pos) in enumerate(sorted_tracks):
            next_pos = (
                sorted_tracks[i + 1][1]
                if i + 1 < len(sorted_tracks)
                else strip_pos + 200_000
            )
            region_end = min(next_pos, strip_pos + 200_000, len(self.data))
            region = self.data[strip_pos : region_end]

            # Volume: compound with fixed header then Value double
            # Pattern: Volume\x00 \x00\x02 \x00\x06 \x00\x00\x00\x02
            #          \x00\x00\x00\x06 Value\x00 \x00\x04 <8 bytes>
            vol_match = re.search(
                rb'Volume\x00\x00\x02\x00\x06\x00\x00\x00\x02\x00\x00\x00\x06Value\x00\x00\x04(.{8})',
                region,
                re.DOTALL,
            )
            if vol_match:
                raw = struct.unpack(">d", vol_match.group(1))[0]
                if raw > 0:
                    track.volume = round(
                        20.0 * math.log10(raw / self._VOLUME_UNITY), 1
                    )
                elif raw == 0:
                    track.volume = -100.0  # -inf dB

            # Pan: compound with fixed header then Value double
            # Pattern: Pan\x00 \x00\x02 \x00\x06 \x00\x00\x00\x01
            #          \x00\x00\x00\x06 Value\x00 \x00\x04 <8 bytes>
            pan_match = re.search(
                rb'Pan\x00\x00\x02\x00\x06\x00\x00\x00\x01\x00\x00\x00\x06Value\x00\x00\x04(.{8})',
                region,
                re.DOTALL,
            )
            if pan_match:
                raw = struct.unpack(">d", pan_match.group(1))[0]
                track.pan = round(
                    (raw - self._PAN_CENTER) / self._PAN_CENTER, 3
                )

    def _extract_mute_solo(self):
        """Extract mute and solo status for each track.

        Mute/Solo: int field (0=off, 1=on) following the named-field pattern.
        """
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        if not sorted_tracks:
            return

        for i, (track, strip_pos) in enumerate(sorted_tracks):
            next_pos = (
                sorted_tracks[i + 1][1]
                if i + 1 < len(sorted_tracks)
                else strip_pos + 200_000
            )
            region_end = min(next_pos, strip_pos + 200_000, len(self.data))
            region = self.data[strip_pos : region_end]

            mute_match = re.search(
                rb'Mute\x00\x00\x01(.{8})',
                region,
                re.DOTALL,
            )
            if mute_match:
                val = struct.unpack(">q", mute_match.group(1))[0]
                track.muted = val == 1

            solo_match = re.search(
                rb'Solo\x00\x00\x01(.{8})',
                region,
                re.DOTALL,
            )
            if solo_match:
                val = struct.unpack(">q", solo_match.group(1))[0]
                track.solo = val == 1

    # ── Track Colors ────────────────────────────────────────────────────

    def _extract_track_colors(self):
        """Extract track colors from the project color palette.

        The palette is stored in UColorSet as repeated ARGB entries.
        Track color indices are embedded in legacy track event headers
        (after the BOM marker). Index -1 means default/no color.
        """
        palette = self._extract_color_palette()
        if not palette:
            return

        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        if not sorted_tracks:
            return

        # Build (position, color_index) from legacy track markers
        color_map = self._extract_color_indices()

        for track, strip_pos in sorted_tracks:
            # Find the closest color index before or near this strip
            best_idx = -1
            best_dist = float("inf")
            for cpos, cidx in color_map:
                dist = abs(cpos - strip_pos)
                if dist < best_dist and dist < 200_000:
                    best_dist = dist
                    best_idx = cidx

            # Only assign if the index is valid and not the default (0)
            # Index 0 is often just "no explicit color set" in Cubase
            if 1 <= best_idx < len(palette):
                track.color = palette[best_idx]

    def _extract_color_palette(self) -> list[str]:
        """Extract the project color palette from UColorSet.

        Returns list of hex color strings like '#E63737'.
        """
        palette: list[str] = []
        for m in re.finditer(rb'Color 16\x00\xef\xbb\xbf(.{4})', self.data, re.DOTALL):
            argb = struct.unpack(">I", m.group(1))[0]
            r = (argb >> 16) & 0xFF
            g = (argb >> 8) & 0xFF
            b = argb & 0xFF
            palette.append(f"#{r:02X}{g:02X}{b:02X}")
        return palette

    def _extract_color_indices(self) -> list[tuple[int, int]]:
        """Find track color indices from legacy track event headers.

        Returns list of (position, color_index) tuples.
        """
        results: list[tuple[int, int]] = []
        track_event_markers = [
            b'MAudioTrackEvent', b'MInstrumentTrackEvent',
            b'MMidiTrackEvent', b'MFXChannelTrackEvent',
            b'MGroupChannelTrackEvent', b'MSamplerTrackEvent',
            b'MFolderTrackEvent',
        ]
        for marker in track_event_markers:
            for m in re.finditer(re.escape(marker), self.data):
                pos = m.start()
                # Search for BOM marker after the event name
                region = self.data[pos : pos + 500]
                bom_pos = region.find(b'\xef\xbb\xbf')
                if bom_pos != -1 and bom_pos + 7 <= len(region):
                    idx_bytes = region[bom_pos + 3 : bom_pos + 7]
                    color_idx = struct.unpack(">i", idx_bytes)[0]
                    results.append((pos, color_idx))
        return results

    # ── Bit Depth ────────────────────────────────────────────────────────

    def _extract_bit_depth(self):
        """Extract bit depth from AudioSampleSize / SampleSize structure.

        Pattern: SampleSize > Long field as int64 (16, 24, or 32).
        """
        for m in re.finditer(rb'SampleSize', self.data):
            pos = m.start()
            region = self.data[pos : pos + 200]
            long_match = re.search(
                rb'Long\x00\x00\x01(.{8})', region, re.DOTALL
            )
            if long_match:
                val = struct.unpack(">q", long_match.group(1))[0]
                if val in (16, 24, 32, 64):
                    self.project.bit_depth = val
                    return

    # ── Transport (Locators, Cycle, Cursor) ─────────────────────────────

    def _extract_transport(self):
        """Extract transport state: cursor, cycle, punch positions.

        The Transport container holds Time, Cycle Left/Right, Punch Left/Right
        as compound fields with a Time double child (position in beats).
        """
        pos = self.data.find(b'Transport\x00\x00\x02')
        if pos == -1:
            return

        region = self.data[pos : pos + 2000]

        # CycleOn flag
        cycle_match = re.search(
            rb'CycleOn\x00\x00\x01(.{8})', region, re.DOTALL
        )
        if cycle_match:
            self.project.cycle_on = struct.unpack(">q", cycle_match.group(1))[0] == 1

        # Extract position doubles from compound fields
        for field_name, attr in [
            (b'Cycle Left', 'cycle_left'),
            (b'Cycle Right', 'cycle_right'),
            (b'Punch Left', 'punch_left'),
            (b'Punch Right', 'punch_right'),
        ]:
            fm = re.search(
                re.escape(field_name) + rb'\x00\x00\x02.+?Time\x00\x00\x04(.{8})',
                region,
                re.DOTALL,
            )
            if fm:
                val = struct.unpack(">d", fm.group(1))[0]
                if 0 <= val < 1e8:
                    setattr(self.project, attr, round(val, 4))

        # Cursor position (first Time compound)
        time_match = re.search(
            rb'Time\x00\x00\x02.+?Time\x00\x00\x04(.{8})',
            region[:200],
            re.DOTALL,
        )
        if time_match:
            val = struct.unpack(">d", time_match.group(1))[0]
            if 0 <= val < 1e8:
                self.project.cursor_position = round(val, 4)

    # ── Monitor ─────────────────────────────────────────────────────────

    def _extract_monitor(self):
        """Extract monitor enable status for each track.

        Monitor is a compound field with Value as int (0=off, 1=on, 2=tape).
        """
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        if not sorted_tracks:
            return

        for i, (track, strip_pos) in enumerate(sorted_tracks):
            next_pos = (
                sorted_tracks[i + 1][1]
                if i + 1 < len(sorted_tracks)
                else strip_pos + 200_000
            )
            region_end = min(next_pos, strip_pos + 200_000, len(self.data))
            region = self.data[strip_pos : region_end]

            mon_match = re.search(
                rb'Monitor\x00\x00\x02\x00\x06.{4}\x00\x00\x00\x06Value\x00\x00\x01(.{8})',
                region,
                re.DOTALL,
            )
            if mon_match:
                val = struct.unpack(">q", mon_match.group(1))[0]
                track.monitor = val >= 1

    # ── Plugin Presets ──────────────────────────────────────────────────

    def _extract_plugin_presets(self):
        """Extract preset names from XML Preset entries and assign to plugins.

        Pattern: <Preset Name="preset_name"> in PresetChunkXMLTree blocks.
        """
        # Build list of (position, preset_name)
        presets: list[tuple[int, str]] = []
        for m in re.finditer(rb'<Preset\s+Name="([^"]*)"', self.data):
            name = m.group(1).decode("utf-8", errors="ignore")
            if name:
                presets.append((m.start(), name))

        if not presets:
            return

        # Assign to nearest plugin by position
        all_plugins: list[tuple[PluginInstance, int]] = []
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        for track, track_pos in sorted_tracks:
            for plugin in track.plugins:
                all_plugins.append((plugin, track_pos))

        for preset_pos, preset_name in presets:
            best_plugin = None
            best_dist = float("inf")
            for plugin, plugin_pos in all_plugins:
                dist = abs(preset_pos - plugin_pos)
                if dist < best_dist and dist < 50_000:
                    best_dist = dist
                    best_plugin = plugin
            if best_plugin and not best_plugin.preset_name:
                best_plugin.preset_name = preset_name

    # ── Folder Hierarchy ────────────────────────────────────────────────

    def _extract_folder_hierarchy(self):
        """Extract folder track structure and assign folder names to child tracks.

        MFolderTrack entries contain a child count after the BOM marker.
        Child tracks follow immediately in file order.
        """
        folders: list[tuple[int, str, int]] = []  # (position, name, child_count)

        for m in re.finditer(rb'MFolderTrack\x00', self.data):
            pos = m.start()
            region = self.data[pos : pos + 500]

            # Extract folder name
            name_match = re.search(
                rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                region,
            )
            if not name_match:
                continue

            folder_name = name_match.group(1).decode("utf-8", errors="ignore")
            bom_end = name_match.end()

            # Child count: after BOM + some header bytes, read as int16
            # Scan for child count in the area after BOM
            after_bom = region[bom_end : bom_end + 30]
            child_count = 0
            # Look for a small int16 (1-50) after some header bytes
            for off in range(4, min(25, len(after_bom) - 1)):
                val = struct.unpack_from(">H", after_bom, off)[0]
                if 1 <= val <= 50:
                    child_count = val
                    break

            if child_count > 0:
                folders.append((pos, folder_name, child_count))

        if not folders:
            return

        # Sort folders and track events by position
        track_events: list[tuple[int, str]] = []
        for marker_bytes, track_type_str in TRACK_MARKERS.items():
            for tm in re.finditer(re.escape(marker_bytes), self.data):
                track_events.append((tm.start(), track_type_str))
        track_events.sort()

        # For each folder, find child track events that follow it
        for folder_pos, folder_name, child_count in folders:
            # Find track events after this folder
            children_found = 0
            for event_pos, _ in track_events:
                if event_pos <= folder_pos:
                    continue
                if children_found >= child_count:
                    break

                # Assign folder name to the matching project track
                for track in self.project.tracks:
                    # Match by name proximity — find track name near event_pos
                    event_region = self.data[event_pos : event_pos + 300]
                    name_m = re.search(
                        rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                        event_region,
                    )
                    if name_m:
                        event_name = name_m.group(1).decode("utf-8", errors="ignore")
                        if track.name == event_name and not track.folder:
                            track.folder = folder_name
                            break

                children_found += 1

    # ── Automation ──────────────────────────────────────────────────────

    def _extract_automation(self):
        """Extract automation lanes from MAutomationTrackEvent entries.

        Each automation track has a name and contains point data with
        position (PPQ) and value (normalized 0.0–1.0) pairs.
        """
        for m in re.finditer(rb'MAutomationTrackEvent\x00', self.data):
            pos = m.start()
            region = self.data[pos : pos + 5000]

            # Extract automation track name
            name_match = re.search(
                rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                region,
            )
            name = name_match.group(1).decode("utf-8", errors="ignore") if name_match else ""

            lane = AutomationLane(parameter_name=name)

            # Extract automation points: look for VffO (value) and TDRH (time) pairs
            # These appear as reversed 4-char markers with double values
            points: list[AutomationPoint] = []
            for pm in re.finditer(rb'VffO\x00\x04(.{8})', region, re.DOTALL):
                value = struct.unpack(">d", pm.group(1))[0]
                if not (0.0 <= value <= 1.0):
                    continue

                # Find the preceding TDRH (position)
                before = region[max(0, pm.start() - 30) : pm.start()]
                tm = re.search(rb'TDRH\x00\x04(.{8})', before, re.DOTALL)
                if tm:
                    time_val = struct.unpack(">d", tm.group(1))[0]
                    points.append(AutomationPoint(position=time_val, value=value))

            lane.points = points
            if points:
                self.project.automation.append(lane)

    # ── MIDI ────────────────────────────────────────────────────────────

    def _extract_midi(self):
        """Extract MIDI note data from MMidiPartEvent entries.

        Each MIDI part contains note events with position, length, pitch,
        and velocity stored in a fixed-size per-note block.
        """
        for m in re.finditer(rb'MMidiPartEvent\x00', self.data):
            pos = m.start()
            region = self.data[pos : pos + 50000]  # MIDI parts can be large

            # Part name
            name_match = re.search(
                rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                region[:300],
            )
            part_name = name_match.group(1).decode("utf-8", errors="ignore") if name_match else ""

            midi_part = MidiPart(name=part_name)

            # Find note data blocks: each note has adcn marker followed by
            # fixed-size data containing length, pitch, position, velocity
            for nm in re.finditer(rb'adcn\x00\x01(.{8})', region, re.DOTALL):
                note_start = nm.end()
                # After adcn value: 4-byte flags + 4-byte reserved + 8-byte length
                # + 16 zero bytes + 1-byte pitch + 1-byte status + 8-byte position
                # + 1-byte pad + 1-byte off_vel + 1-byte on_vel
                block = region[note_start : note_start + 50]
                if len(block) < 45:
                    continue

                try:
                    # flags(4) + reserved(4) = 8 bytes, then length double
                    note_length = struct.unpack_from(">d", block, 8)[0]
                    if note_length <= 0 or note_length > 100000:
                        continue

                    # After length(8) + 16 zeros = offset 32
                    pitch = block[32]
                    status = block[33]

                    # Only process note-on events (0x90)
                    if status != 0x90:
                        continue

                    # Position double at offset 34
                    note_pos = struct.unpack_from(">d", block, 34)[0]

                    # Velocities at offset 43 and 44
                    off_vel = block[43]
                    on_vel = block[44]

                    if 0 <= pitch <= 127 and 0 <= on_vel <= 127:
                        midi_part.notes.append(MidiNote(
                            position=round(note_pos, 2),
                            length=round(note_length, 2),
                            pitch=pitch,
                            velocity=on_vel,
                            off_velocity=off_vel,
                        ))
                except (struct.error, IndexError):
                    continue

            if midi_part.notes:
                # Assign to nearest track
                self._assign_midi_to_track(midi_part, pos)

    def _assign_midi_to_track(self, midi_part: MidiPart, part_pos: int):
        """Assign a MIDI part to the nearest preceding track."""
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
        assigned = None
        for track, track_pos in sorted_tracks:
            if track_pos <= part_pos:
                assigned = track
            else:
                break
        if assigned:
            assigned.midi_parts.append(midi_part)

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

            filtered.append(track)

        # Step 4: Determine content status and filter empty tracks
        final: list[Track] = []
        for track in filtered:
            # Determine has_content
            if track.audio_files:
                track.has_content = True
            elif track.track_type in (TrackType.INSTRUMENT, TrackType.MIDI):
                track.has_content = True  # always have MIDI data
            elif track.track_type in (TrackType.GROUP, TrackType.FX, TrackType.MASTER):
                track.has_content = True  # mix busses, no "content" needed

            # Filter: skip empty audio tracks without plugins
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
    # Known binary artifacts found in .cpr files (reversed 4-byte markers etc.)
    artifacts = {
        "aLoC", "daPN", "shtE", "DILT", "braF", "dpxE", "oloS",
        "sklC", "iCVT", "BuTT", "BlTT", "kcoL", "adcn", "Pler", "GLFX",
        "TDRH", "IVffO", "CmArray", "CmContainer", "BaSE", "mAsT",
    }
    return name in artifacts


# ── Track type classification ────────────────────────────────────────────

def _classify_track_type(name: str, has_plugins: bool = True) -> TrackType:
    """Classify track type from its name (legacy fallback only)."""
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
