"""Track extraction mixin: channel strips, deduplication, classification,
I/O filtering, legacy tracks, folder hierarchy, colors."""

from __future__ import annotations

import logging
import re
import struct

from cubasetools.core.constants import (
    COLOR_ASSIGN_DISTANCE,
    IO_GAP_THRESHOLD,
    STRIP_DEDUP_THRESHOLD,
    TRACK_MARKERS,
)
from cubasetools.core.models import Track, TrackType

logger = logging.getLogger(__name__)


class TrackExtractor:
    """Mixin for extracting tracks from binary .cpr data."""

    def _extract_tracks(self):
        """Extract track entries from binary data.

        Primary strategy: MixerChannel strip definitions detected via
        Name...String...TRACKNAME...InputFilter pattern, with track types
        determined from IDString entries (GroupChannel, FxChannel, Audio, etc.).
        Fallback: legacy MAudioTrackEvent etc. markers.
        """
        try:
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
        except Exception:
            logger.warning("Failed to extract tracks", exc_info=True)

    def _find_channel_idstrings(self) -> list[tuple[int, str]]:
        """Find all channel type IDString entries in the binary data."""
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
        """Classify track types using IDString entries from the binary data."""
        idstrings = self._find_channel_idstrings()
        if not idstrings:
            for track, _ in strips:
                track.track_type = _classify_track_type(track.name)
            return

        strips_sorted = sorted(strips, key=lambda x: x[1])

        # Step 1: Assign IDStrings to strips.
        strip_type_map: dict[int, str] = {}
        id_idx = 0

        for i, (_, strip_pos) in enumerate(strips_sorted):
            next_strip_pos = (
                strips_sorted[i + 1][1] if i + 1 < len(strips_sorted) else float("inf")
            )

            while id_idx < len(idstrings) and idstrings[id_idx][0] <= strip_pos:
                id_idx += 1

            for j in range(id_idx, len(idstrings)):
                id_pos, id_val = idstrings[j]
                if id_pos >= next_strip_pos:
                    break
                strip_type_map[strip_pos] = id_val
                break

        # Step 2: Infer types for unmapped strips from neighbors.
        for i, (_, strip_pos) in enumerate(strips_sorted):
            if strip_pos in strip_type_map:
                continue

            next_type = None
            for j in range(i + 1, len(strips_sorted)):
                npos = strips_sorted[j][1]
                if npos in strip_type_map:
                    next_type = strip_type_map[npos]
                    break

            prev_type = None
            for j in range(i - 1, -1, -1):
                ppos = strips_sorted[j][1]
                if ppos in strip_type_map:
                    prev_type = strip_type_map[ppos]
                    break

            if next_type:
                strip_type_map[strip_pos] = next_type
            elif prev_type:
                strip_type_map[strip_pos] = prev_type

        # Step 3: Apply classifications
        for track, strip_pos in strips:
            lower_name = track.name.lower()

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
                track.track_type = _classify_track_type(track.name)

    def _filter_io_section(
        self, strips: list[tuple[Track, int]]
    ) -> list[tuple[Track, int]]:
        """Remove hardware I/O channels, keeping only Stereo Out."""
        if len(strips) < 2:
            return strips

        max_gap = 0
        max_gap_idx = -1
        for i in range(len(strips) - 1):
            _, pos_a = strips[i]
            _, pos_b = strips[i + 1]
            gap = pos_b - pos_a
            if gap > max_gap:
                max_gap = gap
                max_gap_idx = i

        if max_gap < IO_GAP_THRESHOLD:
            return strips

        io_start = max_gap_idx + 1
        result = strips[:io_start]

        for track, pos in strips[io_start:]:
            if track.name.lower() in ("stereo out", "master", "main out"):
                result.append((track, pos))

        return result

    def _extract_channel_strips(self) -> list[tuple[Track, int]]:
        """Find MixerChannel strip definitions."""
        pattern = rb'Name\x00.{0,20}?String\x00.{0,10}?([\x20-\x7e]{2,50})\x00.{0,30}?Type\x00.{0,20}?InputFilter'
        results: list[tuple[Track, int]] = []

        for m in re.finditer(pattern, self.data, re.DOTALL):
            pos = m.start()
            name = m.group(1).decode("utf-8", errors="ignore").strip()
            if not name or len(name) < 2:
                continue

            track = Track(name=name)
            results.append((track, pos))

        return results

    def _deduplicate_strips(
        self, strips: list[tuple[Track, int]]
    ) -> list[tuple[Track, int]]:
        """Remove duplicate channel strips (same name within threshold = same track)."""
        strips.sort(key=lambda x: x[1])
        deduped: list[tuple[Track, int]] = []
        seen: dict[str, int] = {}

        for track, pos in strips:
            prev_pos = seen.get(track.name)
            if prev_pos is not None and pos - prev_pos < STRIP_DEDUP_THRESHOLD:
                continue
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
            track.has_content = True

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

    # ── Track Colors ────────────────────────────────────────────────────

    def _extract_track_colors(self):
        """Extract track colors from the project color palette."""
        try:
            palette = self._extract_color_palette()
            if not palette:
                return

            sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
            if not sorted_tracks:
                return

            color_map = self._extract_color_indices()

            for track, strip_pos in sorted_tracks:
                best_idx = -1
                best_dist = float("inf")
                for cpos, cidx in color_map:
                    dist = abs(cpos - strip_pos)
                    if dist < best_dist and dist < COLOR_ASSIGN_DISTANCE:
                        best_dist = dist
                        best_idx = cidx

                if 1 <= best_idx < len(palette):
                    track.color = palette[best_idx]
        except Exception:
            logger.warning("Failed to extract track colors", exc_info=True)

    def _extract_color_palette(self) -> list[str]:
        """Extract the project color palette from UColorSet."""
        palette: list[str] = []
        for m in re.finditer(rb'Color 16\x00\xef\xbb\xbf(.{4})', self.data, re.DOTALL):
            argb = struct.unpack(">I", m.group(1))[0]
            r = (argb >> 16) & 0xFF
            g = (argb >> 8) & 0xFF
            b = argb & 0xFF
            palette.append(f"#{r:02X}{g:02X}{b:02X}")
        return palette

    def _extract_color_indices(self) -> list[tuple[int, int]]:
        """Find track color indices from legacy track event headers."""
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
                region = self.data[pos : pos + 500]
                bom_pos = region.find(b'\xef\xbb\xbf')
                if bom_pos != -1 and bom_pos + 7 <= len(region):
                    idx_bytes = region[bom_pos + 3 : bom_pos + 7]
                    color_idx = struct.unpack(">i", idx_bytes)[0]
                    results.append((pos, color_idx))
        return results

    # ── Folder Hierarchy ────────────────────────────────────────────────

    def _extract_folder_hierarchy(self):
        """Extract folder track structure and assign folder names to child tracks."""
        try:
            folders: list[tuple[int, str, int]] = []

            for m in re.finditer(rb'MFolderTrack\x00', self.data):
                pos = m.start()
                region = self.data[pos : pos + 500]

                name_match = re.search(
                    rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                    region,
                )
                if not name_match:
                    continue

                folder_name = name_match.group(1).decode("utf-8", errors="ignore")
                bom_end = name_match.end()

                after_bom = region[bom_end : bom_end + 30]
                child_count = 0
                for off in range(4, min(25, len(after_bom) - 1)):
                    val = struct.unpack_from(">H", after_bom, off)[0]
                    if 1 <= val <= 50:
                        child_count = val
                        break

                if child_count > 0:
                    folders.append((pos, folder_name, child_count))

            if not folders:
                return

            track_events: list[tuple[int, str]] = []
            for marker_bytes, track_type_str in TRACK_MARKERS.items():
                for tm in re.finditer(re.escape(marker_bytes), self.data):
                    track_events.append((tm.start(), track_type_str))
            track_events.sort()

            for folder_pos, folder_name, child_count in folders:
                children_found = 0
                for event_pos, _ in track_events:
                    if event_pos <= folder_pos:
                        continue
                    if children_found >= child_count:
                        break

                    for track in self.project.tracks:
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
        except Exception:
            logger.warning("Failed to extract folder hierarchy", exc_info=True)


# ── Track type classification (module-level helpers) ─────────────────────

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
    if lower.endswith((" vocal", " vocals")):
        return TrackType.GROUP
    if any(kw in lower for kw in ("hall", "verb", "delay", "flanger", "chorus", "fx ", "breit", "parallel")):
        return TrackType.FX
    if any(kw in lower for kw in ("kontakt", "omnisphere", "diva", "retrologue", "beep", "omnivocal")):
        return TrackType.INSTRUMENT
    if not has_plugins and " " not in name and lower not in ("stereo out",):
        group_names = {
            "drums", "bass", "keys", "gitarre", "guitar", "guitars",
            "vocals", "vox", "sinti", "strings", "synths", "pads",
            "samples", "percussion", "perc", "horns", "brass",
            "woodwinds", "fx", "effects", "master",
        }
        if lower in group_names:
            return TrackType.GROUP
    return TrackType.AUDIO
