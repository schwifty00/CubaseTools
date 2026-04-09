"""Diagnostic tool: scan a .cpr file for MIDI and Automation binary markers.

Usage: python tools/diagnose_midi_auto.py <path_to.cpr>

Reports what markers exist, how many, and dumps hex around each match
so we can verify the correct struct offsets.
"""

import struct
import sys
import re
from pathlib import Path


def hexdump(data: bytes, offset: int = 0, length: int = 128) -> str:
    """Produce a readable hex dump of a byte region."""
    lines = []
    for i in range(0, min(length, len(data)), 16):
        hex_part = " ".join(f"{b:02x}" for b in data[i : i + 16])
        ascii_part = "".join(
            chr(b) if 32 <= b < 127 else "." for b in data[i : i + 16]
        )
        lines.append(f"  {offset + i:08x}  {hex_part:<48s}  {ascii_part}")
    return "\n".join(lines)


def scan_markers(data: bytes, pattern: bytes, label: str):
    """Find all occurrences of a binary pattern and report positions."""
    matches = list(re.finditer(re.escape(pattern), data))
    print(f"\n{'=' * 70}")
    print(f"{label}: {len(matches)} matches found")
    print(f"{'=' * 70}")
    for i, m in enumerate(matches):
        if i >= 10:
            print(f"  ... and {len(matches) - 10} more")
            break
        print(f"\n  Match {i + 1} at offset 0x{m.start():08x} ({m.start()}):")
        # Show 200 bytes starting from match
        region = data[m.start() : m.start() + 200]
        print(hexdump(region, m.start(), 200))
    return matches


def analyze_automation(data: bytes):
    """Analyze automation data structure."""
    matches = list(re.finditer(rb'MAutomationTrackEvent\x00', data))
    print(f"\n{'=' * 70}")
    print(f"MAutomationTrackEvent: {len(matches)} matches")
    print(f"{'=' * 70}")

    for i, m in enumerate(matches[:5]):
        pos = m.start()
        region = data[pos : pos + 5000]
        print(f"\n--- Automation Lane {i + 1} at 0x{pos:08x} ---")

        # Try to find parameter name
        name_match = re.search(
            rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
            region,
        )
        if name_match:
            name = name_match.group(1).decode("utf-8", errors="ignore")
            print(f"  Parameter name: {name}")
        else:
            print("  Parameter name: NOT FOUND (name pattern didn't match)")
            # Show first 200 bytes for manual inspection
            print("  First 200 bytes:")
            print(hexdump(region, pos, 200))

        # Look for VffO markers
        vffo_matches = list(re.finditer(rb'VffO', region))
        print(f"  VffO markers in region: {len(vffo_matches)}")
        for j, vm in enumerate(vffo_matches[:5]):
            vpos = vm.start()
            after = region[vpos : vpos + 20]
            print(f"    VffO at +{vpos}: {after.hex()}")
            # Try to read value
            if len(after) >= 14:
                try:
                    val = struct.unpack(">d", after[6:14])[0]
                    print(f"      Value (>d at +6): {val}")
                except struct.error:
                    pass

        # Look for TDRH markers
        tdrh_matches = list(re.finditer(rb'TDRH', region))
        print(f"  TDRH markers in region: {len(tdrh_matches)}")
        for j, tm in enumerate(tdrh_matches[:5]):
            tpos = tm.start()
            after = region[tpos : tpos + 20]
            print(f"    TDRH at +{tpos}: {after.hex()}")
            if len(after) >= 14:
                try:
                    val = struct.unpack(">d", after[6:14])[0]
                    print(f"      Time (>d at +6): {val}")
                except struct.error:
                    pass


def analyze_midi(data: bytes):
    """Analyze MIDI data structure."""
    matches = list(re.finditer(rb'MMidiPartEvent\x00', data))
    print(f"\n{'=' * 70}")
    print(f"MMidiPartEvent: {len(matches)} matches")
    print(f"{'=' * 70}")

    for i, m in enumerate(matches[:5]):
        pos = m.start()
        region = data[pos : pos + 2000]
        print(f"\n--- MIDI Part {i + 1} at 0x{pos:08x} ---")

        # Try to find part name
        name_match = re.search(
            rb'\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf',
            region[:300],
        )
        if name_match:
            name = name_match.group(1).decode("utf-8", errors="ignore")
            print(f"  Part name: {name}")
        else:
            print("  Part name: NOT FOUND")
            print("  First 200 bytes:")
            print(hexdump(region, pos, 200))

        # Look for adcn markers (MIDI note data)
        adcn_matches = list(re.finditer(rb'adcn', region))
        print(f"  adcn markers in region: {len(adcn_matches)}")

        for j, am in enumerate(adcn_matches[:5]):
            apos = am.start()
            after = region[apos : apos + 60]
            print(f"\n    adcn at +{apos}:")
            print(hexdump(after, pos + apos, 60))

            # Try current offset assumptions
            if len(after) >= 53:
                try:
                    # Current parser: adcn\x00\x01 + 8 bytes match group
                    # Then block starts at nm.end() (= apos + 6 + 8 = apos + 14)
                    block_start = 14  # after adcn\x00\x01 + 8 bytes
                    block = after[block_start:]
                    if len(block) >= 45:
                        note_len = struct.unpack_from(">d", block, 8)[0]
                        pitch = block[32]
                        status = block[33]
                        note_pos = struct.unpack_from(">d", block, 34)[0]
                        off_vel = block[43]
                        on_vel = block[44]
                        print(f"      [Current offsets] length={note_len:.1f} pitch={pitch} status=0x{status:02x} pos={note_pos:.1f} vel={on_vel}")
                except (struct.error, IndexError):
                    print("      [Current offsets] Failed to parse")

        # Also look for note-on bytes (0x90) in the region
        note_on_positions = [i for i, b in enumerate(region[:500]) if b == 0x90]
        if note_on_positions:
            print(f"\n  0x90 (note-on) bytes found at offsets: {note_on_positions[:20]}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/diagnose_midi_auto.py <path_to.cpr>")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    data = path.read_bytes()
    print(f"File: {path}")
    print(f"Size: {len(data):,} bytes")

    # Scan for key markers
    scan_markers(data, b'MMidiPartEvent', "MMidiPartEvent")
    scan_markers(data, b'MAutomationTrackEvent', "MAutomationTrackEvent")
    scan_markers(data, b'adcn', "adcn (MIDI note marker)")
    scan_markers(data, b'VffO', "VffO (automation value)")
    scan_markers(data, b'TDRH', "TDRH (automation time)")

    # Detailed analysis
    analyze_automation(data)
    analyze_midi(data)

    # Also scan for alternative markers that might exist in newer Cubase versions
    alt_markers = [
        b'MidiEvent', b'NoteEvent', b'MTrackEvent',
        b'MAutomation', b'AutomationEvent',
        b'MListNode', b'MRangeMarkerEvent',
    ]
    print(f"\n{'=' * 70}")
    print("Alternative markers scan:")
    print(f"{'=' * 70}")
    for marker in alt_markers:
        count = len(re.findall(re.escape(marker), data))
        if count > 0:
            print(f"  {marker.decode('ascii', errors='replace')}: {count} matches")


if __name__ == "__main__":
    main()
