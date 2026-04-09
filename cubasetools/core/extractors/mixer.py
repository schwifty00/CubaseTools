"""Mixer extraction mixin: volume, pan, mute, solo, monitor, routing, sends."""

from __future__ import annotations

import logging
import math
import re
import struct

from cubasetools.core.constants import (
    MAX_SEND_SLOTS,
    PER_TRACK_REGION_SIZE,
    SEND_FOLDER_REGION_SIZE,
    VOLUME_UNITY,
)
from cubasetools.core.models import SendSlot

logger = logging.getLogger(__name__)


class MixerExtractor:
    """Mixin for extracting mixer state from binary .cpr data."""

    def _extract_volume_pan(self):
        """Extract fader volume and pan for each track.

        Volume: compound field with Value as BE double (0..32767, unity=25856)
        Pan: compound field with Value as BE double (0..32767, center=16383.5)
        """
        try:
            sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
            if not sorted_tracks:
                return

            for i, (track, strip_pos) in enumerate(sorted_tracks):
                next_pos = (
                    sorted_tracks[i + 1][1]
                    if i + 1 < len(sorted_tracks)
                    else strip_pos + PER_TRACK_REGION_SIZE
                )
                region_end = min(next_pos, strip_pos + PER_TRACK_REGION_SIZE, len(self.data))
                region = self.data[strip_pos : region_end]

                vol_match = re.search(
                    rb'Volume\x00\x00\x02\x00\x06\x00\x00\x00\x02'
                    rb'\x00\x00\x00\x06Value\x00\x00\x04(.{8})'
                    rb'\x00\x00\x00\x0cAnchorValue\x00\x00\x04(.{8})',
                    region,
                    re.DOTALL,
                )
                if vol_match:
                    anchor = struct.unpack(">d", vol_match.group(2))[0]
                    if -150 < anchor < 20:
                        track.volume = round(anchor, 1)
                    else:
                        raw = struct.unpack(">d", vol_match.group(1))[0]
                        if raw > 0:
                            track.volume = round(
                                20.0 * math.log10(raw / VOLUME_UNITY), 1
                            )
                        elif raw == 0:
                            track.volume = -100.0

                pan_match = re.search(
                    rb'SummingMode\x00.{0,30}?'
                    rb'Panner\x00\x00\x02\x00\x06\x00\x00\x00\x15'
                    rb'.{200,600}?Standard Panner'
                    rb'.+?audioComponent\x00\x00\x02\x00\x07.{4}(.{4})',
                    region,
                    re.DOTALL,
                )
                if pan_match:
                    raw = struct.unpack("<f", pan_match.group(1))[0]
                    track.pan = round((raw - 0.5) * 2.0, 3)
        except Exception:
            logger.warning("Failed to extract volume/pan", exc_info=True)

    def _extract_mute_solo(self):
        """Extract mute and solo status for each track."""
        try:
            sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
            if not sorted_tracks:
                return

            for i, (track, strip_pos) in enumerate(sorted_tracks):
                next_pos = (
                    sorted_tracks[i + 1][1]
                    if i + 1 < len(sorted_tracks)
                    else strip_pos + PER_TRACK_REGION_SIZE
                )
                region_end = min(next_pos, strip_pos + PER_TRACK_REGION_SIZE, len(self.data))
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
        except Exception:
            logger.warning("Failed to extract mute/solo", exc_info=True)

    def _extract_monitor(self):
        """Extract monitor enable status for each track."""
        try:
            sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
            if not sorted_tracks:
                return

            for i, (track, strip_pos) in enumerate(sorted_tracks):
                next_pos = (
                    sorted_tracks[i + 1][1]
                    if i + 1 < len(sorted_tracks)
                    else strip_pos + PER_TRACK_REGION_SIZE
                )
                region_end = min(next_pos, strip_pos + PER_TRACK_REGION_SIZE, len(self.data))
                region = self.data[strip_pos : region_end]

                mon_match = re.search(
                    rb'Monitor\x00\x00\x02\x00\x06.{4}\x00\x00\x00\x06Value\x00\x00\x01(.{8})',
                    region,
                    re.DOTALL,
                )
                if mon_match:
                    val = struct.unpack(">q", mon_match.group(1))[0]
                    track.monitor = val >= 1
        except Exception:
            logger.warning("Failed to extract monitor status", exc_info=True)

    def _build_bus_uid_table(self) -> dict[int, str]:
        """Build a lookup table mapping bus UIDs to track/bus names."""
        table: dict[int, str] = {}

        try:
            for m in re.finditer(rb'OwnInputBus\x00', self.data):
                pos = m.start()
                region = self.data[pos : pos + 500]

                name_match = re.search(
                    rb'Name\x00.{0,12}?([\x20-\x7e]{2,50})\x00',
                    region,
                    re.DOTALL,
                )
                if not name_match:
                    continue
                bus_name = name_match.group(1).decode("utf-8", errors="ignore").strip()

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
        except Exception:
            logger.warning("Failed to build bus UID table", exc_info=True)

        return table

    def _extract_routing(self, bus_table: dict[int, str]) -> None:
        """Extract output routing for each track."""
        try:
            sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
            if not sorted_tracks:
                return

            for i, (track, strip_pos) in enumerate(sorted_tracks):
                next_pos = (
                    sorted_tracks[i + 1][1]
                    if i + 1 < len(sorted_tracks)
                    else strip_pos + PER_TRACK_REGION_SIZE
                )
                region_end = min(next_pos, strip_pos + PER_TRACK_REGION_SIZE, len(self.data))
                region = self.data[strip_pos : region_end]

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
        except Exception:
            logger.warning("Failed to extract routing", exc_info=True)

    def _extract_sends(self, bus_table: dict[int, str]) -> None:
        """Extract send slots for each track."""
        try:
            sorted_tracks = sorted(self._track_positions, key=lambda x: x[1])
            if not sorted_tracks:
                return

            for i, (track, strip_pos) in enumerate(sorted_tracks):
                next_pos = (
                    sorted_tracks[i + 1][1]
                    if i + 1 < len(sorted_tracks)
                    else strip_pos + PER_TRACK_REGION_SIZE
                )
                region_end = min(next_pos, strip_pos + PER_TRACK_REGION_SIZE, len(self.data))
                region = self.data[strip_pos : region_end]

                sf_match = re.search(rb'SendFolder\x00', region)
                if not sf_match:
                    continue

                send_region = region[sf_match.start() : sf_match.start() + SEND_FOLDER_REGION_SIZE]

                vol_positions = [
                    m.start() for m in re.finditer(rb'Volume\x00', send_region)
                ]
                out_positions = [
                    m.start() for m in re.finditer(rb'Output\x00', send_region)
                ]

                for vol_pos in vol_positions:
                    vol_area = send_region[vol_pos : vol_pos + 40]
                    dbl_match = re.search(
                        rb'Value\x00\x00\x04(.{8})', vol_area, re.DOTALL
                    )
                    if not dbl_match:
                        continue
                    vol_val = struct.unpack(">d", dbl_match.group(1))[0]

                    level_db = 0.0
                    if vol_val > 0:
                        level_db = round(20.0 * math.log10(vol_val / VOLUME_UNITY), 1) + 0.0

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

                    if len(track.sends) >= MAX_SEND_SLOTS:
                        break
        except Exception:
            logger.warning("Failed to extract sends", exc_info=True)
