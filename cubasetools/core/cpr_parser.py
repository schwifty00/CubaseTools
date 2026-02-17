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


class CprParser:
    """Parser for Cubase .cpr binary project files."""

    def __init__(self, cpr_path: Path):
        self.path = cpr_path
        self.data = b""
        self.project = CubaseProject(file_path=cpr_path)
        # Track positions in binary for plugin assignment
        self._track_positions: list[tuple[Track, int]] = []

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

        return self.project

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

    def _extract_tracks(self):
        """Extract track entries from binary data."""
        # Collect all track markers with positions, then sort by position
        raw_tracks: list[tuple[int, str, bytes]] = []

        for marker_bytes, track_type_str in TRACK_MARKERS.items():
            for match in re.finditer(re.escape(marker_bytes), self.data):
                raw_tracks.append((match.start(), track_type_str, marker_bytes))

        # Sort by position in file to maintain track order
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

        # Try UTF-16-LE strings (common in Cubase)
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

    def _extract_plugins(self):
        """Extract plugins from both PresetChunkXMLTree blocks and <?xml blocks."""
        plugins_with_pos: list[tuple[PluginInstance, int]] = []

        # 1) PresetChunkXMLTree blocks - these contain <PluginName> elements
        self._extract_preset_chunk_plugins(plugins_with_pos)

        # 2) Standalone <?xml blocks (e.g., ValhallaVintageVerb, FabFilter)
        self._extract_standalone_xml_plugins(plugins_with_pos)

        # Deduplicate: same plugin at very close positions are likely duplicates
        deduped = self._deduplicate_plugins(plugins_with_pos)

        # Assign plugins to tracks based on binary position proximity
        self._assign_plugins_to_tracks(deduped)

    def _extract_preset_chunk_plugins(
        self, results: list[tuple[PluginInstance, int]]
    ):
        """Parse PresetChunkXMLTree blocks for Waves/SSL style plugins."""
        pattern = rb'PresetChunkXMLTree[^>]*>'
        for match in re.finditer(pattern, self.data):
            pos = match.start()
            region = self.data[pos : pos + 5000]

            # Extract PluginName
            pn_match = re.search(rb'<PluginName>([^<]+)</PluginName>', region)
            if not pn_match:
                continue

            plugin_name = pn_match.group(1).decode("utf-8", errors="ignore")

            # Extract preset name
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

            # Fallback: try XML attribute-based params
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

            results.append((plugin, pos))

    def _extract_standalone_xml_plugins(
        self, results: list[tuple[PluginInstance, int]]
    ):
        """Parse standalone <?xml blocks (Valhalla, FabFilter, etc.)."""
        search_pos = 0
        max_chunks = 200

        while max_chunks > 0:
            pos = self.data.find(b"<?xml", search_pos)
            if pos == -1:
                break

            # Find end: look for /> or closing tag within 5KB
            window = self.data[pos : pos + 5000]

            # Try to find the self-closing root element end
            # Most of these are single-element XML: <TagName ... />
            end_offset = None

            # Check for self-closing tag
            sc = window.find(b"/>")
            if sc != -1:
                end_offset = sc + 2

            # Check for closing tag
            # Find root tag name
            tag_match = re.search(rb'<\?xml[^>]*\?>\s*<(\w+)', window)
            if tag_match:
                close_tag = b"</" + tag_match.group(1) + b">"
                ct = window.find(close_tag)
                if ct != -1:
                    ct += len(close_tag)
                    if end_offset is None or ct < end_offset:
                        end_offset = ct

            if end_offset is None:
                search_pos = pos + 5
                max_chunks -= 1
                continue

            xml_bytes = window[:end_offset]
            search_pos = pos + end_offset
            max_chunks -= 1

            try:
                xml_str = xml_bytes.decode("utf-8", errors="ignore")
                root = ET.fromstring(xml_str)
            except ET.ParseError:
                continue

            plugin = PluginInstance()

            # Root tag is often the plugin name (e.g., <ValhallaVintageVerb>)
            tag_name = root.tag
            if tag_name and tag_name not in ("state", "xml", "plugin", "preset"):
                plugin.name = tag_name

            # Check common name attributes
            for attr in ["pluginName", "name", "Name", "preset"]:
                val = root.get(attr)
                if val and len(val) > 2:
                    if not plugin.name or plugin.name in ("state", "PluginState"):
                        plugin.name = val
                    break

            if not plugin.name:
                continue

            # All attributes on the root element are likely parameters
            for attr_name, attr_val in root.attrib.items():
                if attr_name in ("pluginVersion", "presetName", "version", "preset", "bank"):
                    continue
                try:
                    plugin.parameters[attr_name] = float(attr_val)
                except ValueError:
                    pass

            # Child element parameters
            for child in root:
                if child.text:
                    try:
                        plugin.parameters[child.tag] = float(child.text)
                    except ValueError:
                        pass
                for attr_name, attr_val in child.attrib.items():
                    try:
                        plugin.parameters[f"{child.tag}.{attr_name}"] = float(attr_val)
                    except ValueError:
                        pass

            if plugin.parameters:
                interpret_plugin_parameters(plugin)

            results.append((plugin, pos))

    def _deduplicate_plugins(
        self, plugins: list[tuple[PluginInstance, int]]
    ) -> list[tuple[PluginInstance, int]]:
        """Remove duplicate plugins that appear at very close positions.

        Cubase often stores plugin data twice (editor + processor state).
        Keep the one with more parameters.
        """
        if not plugins:
            return []

        # Sort by position
        plugins.sort(key=lambda x: x[1])

        deduped: list[tuple[PluginInstance, int]] = []
        i = 0
        while i < len(plugins):
            current_plugin, current_pos = plugins[i]
            best = current_plugin
            best_pos = current_pos

            # Look ahead for duplicates (same name within 20KB)
            j = i + 1
            while j < len(plugins):
                next_plugin, next_pos = plugins[j]
                if next_pos - current_pos > 20000:
                    break
                if next_plugin.name == current_plugin.name:
                    # Keep the one with more parameters
                    if len(next_plugin.parameters) > len(best.parameters):
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
            # No tracks found - create a default track
            if plugins and not self.project.tracks:
                default_track = Track(name="Master", track_type=TrackType.MASTER, index=0)
                self.project.tracks.append(default_track)
                for plugin, _ in plugins:
                    plugin.slot_index = len(default_track.plugins)
                    default_track.plugins.append(plugin)
            return

        # Sort track positions
        sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])

        for plugin, plugin_pos in plugins:
            # Find the track whose position is closest before this plugin
            assigned_track = sorted_tracks[0][0]  # default to first track
            for track, track_pos in sorted_tracks:
                if track_pos <= plugin_pos:
                    assigned_track = track
                else:
                    break

            plugin.slot_index = len(assigned_track.plugins)
            assigned_track.plugins.append(plugin)

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
        # SSL EQ: 4 bands (LF, LMF, HMF, HF)
        # Pos: 0=LF_on, 1=LF_bell, 2=LF_freq, 4=LF_gain
        #      5=LMF_freq, 8=LMF_gain, 9=LMF_Q
        #      10=HMF_Q, 13=HMF_gain, 14=HMF_freq_kHz
        #      16=HF_on, 17=HF_gain, 18=HF_freq_kHz
        #      19=Output_trim
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
                frequency=_rw(values, 14, 3.5) * 1000,  # kHz -> Hz
                gain=_rw(values, 13),
                q=_rw(values, 10, 2.5),
            ),
            EQBand(
                enabled=_rw(values, 16) > 0.5,
                band_type=EQBandType.HIGH_SHELF,
                frequency=_rw(values, 18, 8.0) * 1000,  # kHz -> Hz
                gain=_rw(values, 17),
                q=1.0,
            ),
        ]
        plugin.eq_bands = [b for b in bands if b.gain != 0.0 or b.enabled]
        plugin.parameters["Output Trim"] = _rw(values, 19)

    elif plugin_name == "SSLChannel":
        # SSL Channel Strip: EQ + Compressor + Gate
        # Verified mapping from RealWorld parameter dumps:
        # Pos 0: Comp Threshold (dB)  Pos 3: Comp Release (s)
        # EQ section at pos 15-24:
        #   15=LF_freq(Hz) 16=LF_gain 17=LMF_Q 18=LMF_freq(kHz)
        #   19=LMF_gain 20=HMF_freq(kHz) 21=HMF_Q 22=HMF_gain
        #   23=HF_gain 24=HF_freq(kHz)
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
                    frequency=_rw(values, 18, 2.5) * 1000,  # kHz -> Hz
                    gain=_rw(values, 19),
                    q=_rw(values, 17, 0.5),
                ),
                EQBand(
                    enabled=True,
                    band_type=EQBandType.PEAK,
                    frequency=_rw(values, 20, 3.5) * 1000,  # kHz -> Hz
                    gain=_rw(values, 22),
                    q=_rw(values, 21, 1.5),
                ),
                EQBand(
                    enabled=True,
                    band_type=EQBandType.HIGH_SHELF,
                    frequency=_rw(values, 24, 8.0) * 1000,  # kHz -> Hz
                    gain=_rw(values, 23),
                    q=1.0,
                ),
            ]
            plugin.eq_bands = [b for b in bands if b.gain != 0.0]

        # Compressor section
        comp_thresh = _rw(values, 0)
        if comp_thresh < 0:
            plugin.compressor = CompressorSettings(
                plugin_name=plugin_name,
                threshold=comp_thresh,
                release=_rw(values, 3),
            )

    elif plugin_name in ("CLA-76", "CLA76"):
        # CLA-76: Pos 0=Input, 1=Output, 2=Attack, 3=Release, 4-7=Ratio buttons
        # Pos 8=Mix?
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            input_gain=_rw(values, 0),
            output_gain=_rw(values, 1),
            attack=_rw(values, 2),
            release=_rw(values, 3),
            ratio=4.0,  # Ratio is button-based (4, 8, 12, 20, All)
        )
        if preset_name:
            plugin.parameters["Preset"] = 0  # Store name separately
            plugin.compressor.raw_parameters["preset_name"] = preset_name  # type: ignore[assignment]

    elif plugin_name in ("CLA-2A", "CLA2A"):
        # CLA-2A: Pos 0=Peak Reduction, 1=Output Gain
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            threshold=_rw(values, 0),
            output_gain=_rw(values, 1),
        )

    elif plugin_name == "C1Comp":
        # C1 Comp: Pos 17=Threshold, 18=Ratio
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            threshold=_rw(values, 17),
            ratio=_rw(values, 18, 1.0),
            attack=_rw(values, 0, 0.01),
        )

    elif plugin_name == "DeEsser":
        # DeEsser: Pos 0=Freq, 2=Threshold
        plugin.parameters["Frequency"] = _rw(values, 0, 5500)
        plugin.parameters["Threshold"] = _rw(values, 2)

    else:
        # Generic: store raw values as numbered parameters
        for i, v in enumerate(values[:20]):
            if v is not None:
                plugin.parameters[f"Param_{i}"] = v


def parse_cpr(cpr_path: Path) -> CubaseProject:
    """Convenience function to parse a .cpr file."""
    parser = CprParser(cpr_path)
    return parser.parse()
