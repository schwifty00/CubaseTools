"""Metadata extraction mixin: version, sample rate, tempo, bit depth,
time signature, transport."""

from __future__ import annotations

import logging
import re
import struct

from cubasetools.core.constants import (
    POSITION_LIMIT,
    TEMPO_MAX,
    TEMPO_MIN,
    VERSION_MARKERS,
)

logger = logging.getLogger(__name__)


class MetadataExtractor:
    """Mixin for extracting project metadata from binary .cpr data."""

    def _extract_version(self):
        """Find Cubase version string.

        Two formats:
        - Modern (Cubase 12+): 'Version NN.N.N\\x00' in the file header
        - Legacy: 'Cubase NN\\x00' ASCII markers
        """
        try:
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
        except Exception:
            logger.warning("Failed to extract Cubase version", exc_info=True)

    def _extract_sample_rate(self):
        """Try to find sample rate.

        Modern Cubase stores sample rate as a BE double in a 'Float' sub-field
        within the binary SampleRate structure (not in XML preset data).
        Falls back to int32 search.
        """
        try:
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
        except Exception:
            logger.warning("Failed to extract sample rate", exc_info=True)

    def _extract_tempo(self):
        """Try to extract tempo from the project.

        Strategy 1: Find MTempoEvent with a BPM named-field double.
        Strategy 2: Scan MTempoTrackEvent header for embedded BPM double.
        Strategy 3: MusicalTempo media attribute (audio file tempo tag).
        If none finds a value, the project uses the default 120 BPM.
        """
        try:
            # Strategy 1: MTempoEvent > BPM named field (most reliable)
            m = re.search(
                rb'MTempoEvent.*?BPM\x00\x00\x04(.{8})',
                self.data,
                re.DOTALL,
            )
            if m:
                val = struct.unpack(">d", m.group(1))[0]
                if TEMPO_MIN < val < TEMPO_MAX:
                    self.project.tempo = round(val, 2)
                    return

            # Strategy 2: Scan MTempoTrackEvent header for embedded double
            pos = self.data.find(b"MTempoTrackEvent")
            if pos != -1:
                region = self.data[pos : pos + 500]
                for offset in range(17, len(region) - 8):
                    val = struct.unpack_from(">d", region, offset)[0]
                    if TEMPO_MIN < val < TEMPO_MAX:
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
                if TEMPO_MIN < val < TEMPO_MAX:
                    self.project.tempo = round(val, 1)
                    return
        except Exception:
            logger.warning("Failed to extract tempo", exc_info=True)

    def _extract_time_signature(self):
        """Extract time signature from TimeSignatureEvent entries."""
        try:
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
        except Exception:
            logger.warning("Failed to extract time signature", exc_info=True)

    def _extract_bit_depth(self):
        """Extract bit depth from AudioSampleSize / SampleSize structure."""
        try:
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
        except Exception:
            logger.warning("Failed to extract bit depth", exc_info=True)

    def _extract_transport(self):
        """Extract transport state: cursor, cycle, punch positions."""
        try:
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
                    if 0 <= val < POSITION_LIMIT:
                        setattr(self.project, attr, round(val, 4))

            # Cursor position (first Time compound)
            time_match = re.search(
                rb'Time\x00\x00\x02.+?Time\x00\x00\x04(.{8})',
                region[:200],
                re.DOTALL,
            )
            if time_match:
                val = struct.unpack(">d", time_match.group(1))[0]
                if 0 <= val < POSITION_LIMIT:
                    self.project.cursor_position = round(val, 4)
        except Exception:
            logger.warning("Failed to extract transport data", exc_info=True)
