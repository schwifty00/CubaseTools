"""Media extraction mixin: audio references, audio per track, markers,
automation, MIDI."""

from __future__ import annotations

import logging
import re
import struct

from cubasetools.core.audio_patterns import find_audio_references
from cubasetools.core.models import (
    AutomationLane,
    AutomationPoint,
    Marker,
    MidiNote,
    MidiPart,
)

logger = logging.getLogger(__name__)


class MediaExtractor:
    """Mixin for extracting media data from binary .cpr data."""

    def _extract_audio_references(self):
        """Extract all referenced audio filenames from the binary data."""
        try:
            self.project.referenced_audio = find_audio_references(self.data)
        except Exception:
            logger.warning("Failed to extract audio references", exc_info=True)

    def _extract_audio_per_track(self) -> None:
        """Assign audio file references to their respective tracks."""
        try:
            sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
            if not sorted_tracks:
                return

            pool_pos = self.data.find(b'Pool\x00')
            if pool_pos == -1:
                pool_pos = len(self.data)

            for i, (track, strip_pos) in enumerate(sorted_tracks):
                next_pos = (
                    sorted_tracks[i + 1][1]
                    if i + 1 < len(sorted_tracks)
                    else pool_pos
                )
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
        except Exception:
            logger.warning("Failed to extract audio per track", exc_info=True)

    # ── Markers ─────────────────────────────────────────────────────────

    def _extract_markers(self):
        """Extract markers from the project."""
        try:
            for match in re.finditer(rb'MMarkerEvent', self.data):
                pos = match.start()
                region = self.data[pos : pos + 200]

                marker = Marker()
                marker.marker_id = len(self.project.markers) + 1

                name_match = re.search(
                    rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                    region,
                )
                if name_match:
                    marker.name = name_match.group(1).decode("utf-8", errors="ignore")
                    after_bom = region[name_match.end():]
                    if len(after_bom) >= 8:
                        start_ticks = struct.unpack(">I", after_bom[4:8])[0]
                        marker.position = float(start_ticks)
                else:
                    name = self._extract_nearby_string(pos)
                    marker.name = name if name else f"Marker {marker.marker_id}"

                self.project.markers.append(marker)
        except Exception:
            logger.warning("Failed to extract markers", exc_info=True)

    # ── Automation ──────────────────────────────────────────────────────

    def _extract_automation(self):
        """Extract automation lanes from MAutomationTrackEvent entries."""
        try:
            for m in re.finditer(rb'MAutomationTrackEvent\x00', self.data):
                pos = m.start()
                region = self.data[pos : pos + 5000]

                name_match = re.search(
                    rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                    region,
                )
                name = name_match.group(1).decode("utf-8", errors="ignore") if name_match else ""

                lane = AutomationLane(parameter_name=name)

                points: list[AutomationPoint] = []
                for pm in re.finditer(rb'VffO\x00\x04(.{8})', region, re.DOTALL):
                    value = struct.unpack(">d", pm.group(1))[0]
                    if not (0.0 <= value <= 1.0):
                        continue

                    before = region[max(0, pm.start() - 30) : pm.start()]
                    tm = re.search(rb'TDRH\x00\x04(.{8})', before, re.DOTALL)
                    if tm:
                        time_val = struct.unpack(">d", tm.group(1))[0]
                        points.append(AutomationPoint(position=time_val, value=value))

                lane.points = points
                if points:
                    self.project.automation.append(lane)
        except Exception:
            logger.warning("Failed to extract automation", exc_info=True)

    # ── MIDI ────────────────────────────────────────────────────────────

    def _extract_midi(self):
        """Extract MIDI note data from MMidiPartEvent entries."""
        try:
            for m in re.finditer(rb'MMidiPartEvent\x00', self.data):
                pos = m.start()
                region = self.data[pos : pos + 50000]

                name_match = re.search(
                    rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
                    region[:300],
                )
                part_name = name_match.group(1).decode("utf-8", errors="ignore") if name_match else ""

                midi_part = MidiPart(name=part_name)

                # adcn record layout (verified against real .cpr files):
                #   adcn\x00\x01  [6b header]
                #   captured[0:4] = record size (uint32 BE, typically 0x20)
                #   captured[4:8] = pitch in last byte (captured[7])
                #   block[0:8]    = note length (float64 BE, in ticks)
                #   block[8:24]   = reserved zeros
                #   block[24]     = pitch (alternative location)
                #   block[25]     = status byte (0x90 = note-on)
                #   block[26:34]  = note position (float64 BE, in ticks)
                #   block[34]     = padding
                #   block[35]     = on-velocity (0-127)
                #   block[36]     = off-velocity (0-127)
                # Pitch is stored at captured[7] OR block[24] depending
                # on Cubase version. Determine which has real data.
                adcn_matches = list(
                    re.finditer(rb'adcn\x00\x01(.{8})', region, re.DOTALL)
                )
                cap7_set = {m.group(1)[7] for m in adcn_matches}
                use_block24 = cap7_set == {0}

                for nm in adcn_matches:
                    captured = nm.group(1)

                    block = region[nm.end() : nm.end() + 37]
                    if len(block) < 37:
                        continue

                    try:
                        pitch = block[24] if use_block24 else captured[7]

                        note_length = struct.unpack_from(">d", block, 0)[0]
                        if note_length <= 0 or note_length > 100000:
                            continue

                        note_pos = struct.unpack_from(">d", block, 26)[0]
                        on_vel = block[35]
                        off_vel = block[36]

                        if 0 < pitch <= 127 and 0 < on_vel <= 127:
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
                    self._assign_midi_to_track(midi_part, pos)
        except Exception:
            logger.warning("Failed to extract MIDI data", exc_info=True)

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
