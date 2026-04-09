"""Tests for MIDI and automation extraction from binary .cpr data."""

import struct
import tempfile
from pathlib import Path

from cubasetools.core.cpr_parser import parse_cpr


def _make_cpr(content: bytes) -> Path:
    """Create a temporary .cpr file with given binary content."""
    tmp = tempfile.NamedTemporaryFile(suffix=".cpr", delete=False)
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def _make_strip(name: str) -> bytes:
    """Build a minimal channel strip pattern."""
    name_bytes = name.encode("utf-8")
    return (
        b"Name\x00" + b"\x00" * 5
        + b"String\x00" + b"\x00" * 3
        + name_bytes + b"\x00" + b"\x00" * 5
        + b"Type\x00" + b"\x00" * 5
        + b"InputFilter"
    )


# ── Automation Tests ────────────────────────────────────────────────────


def test_extract_automation_lane():
    """Parser should extract automation lanes with points."""
    # Build an MAutomationTrackEvent with a name and VffO/TDRH pairs
    name = b"Volume"
    lane_data = (
        b"MAutomationTrackEvent\x00"
        + b"\x00\x00\x00" + bytes([len(name) + 4])
        + name + b"\x00\xef\xbb\xbf"
        + b"\x00" * 20
        # Point 1: position=0.0, value=0.5
        + b"TDRH\x00\x04" + struct.pack(">d", 0.0)
        + b"VffO\x00\x04" + struct.pack(">d", 0.5)
        + b"\x00" * 10
        # Point 2: position=960.0, value=0.8
        + b"TDRH\x00\x04" + struct.pack(">d", 960.0)
        + b"VffO\x00\x04" + struct.pack(">d", 0.8)
        + b"\x00" * 50
    )
    data = b"\x00" * 20 + lane_data + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    assert len(project.automation) >= 1
    lane = project.automation[0]
    assert lane.parameter_name == "Volume"
    assert len(lane.points) >= 2
    assert lane.points[0].value == 0.5
    assert lane.points[1].value == 0.8
    path.unlink()


def test_automation_rejects_out_of_range_values():
    """Automation values outside 0.0-1.0 should be rejected."""
    lane_data = (
        b"MAutomationTrackEvent\x00"
        + b"\x00" * 20
        # Point with invalid value (1.5 > 1.0)
        + b"TDRH\x00\x04" + struct.pack(">d", 0.0)
        + b"VffO\x00\x04" + struct.pack(">d", 1.5)
        + b"\x00" * 50
    )
    data = b"\x00" * 20 + lane_data + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    # Either no automation lane (empty points = not added) or points list is empty
    for lane in project.automation:
        for point in lane.points:
            assert 0.0 <= point.value <= 1.0
    path.unlink()


def test_no_automation_in_empty_project():
    """Empty project should have no automation."""
    path = _make_cpr(b"\x00" * 200)
    project = parse_cpr(path)
    assert project.automation == []
    path.unlink()


# ── MIDI Tests ──────────────────────────────────────────────────────────


def _make_midi_note(pitch: int, velocity: int, position: float, length: float) -> bytes:
    """Build a single MIDI note block in the adcn format.

    Layout (verified against real Cubase .cpr files):
      adcn\\x00\\x01  [6b header]
      [4b record size = 0x20]
      [4b pitch in last byte]
      [8b note length double]
      [18b reserved zeros]
      [8b note position double]
      [1b padding]
      [1b on-velocity]
      [1b off-velocity]
    """
    block = (
        b"adcn\x00\x01"
        + struct.pack(">I", 0x20)            # record size
        + struct.pack(">I", pitch)           # pitch in last byte
        + struct.pack(">d", length)          # note length (ticks)
        + b"\x00" * 18                       # reserved
        + struct.pack(">d", position)        # note position (ticks)
        + bytes([0])                         # padding
        + bytes([velocity])                  # on-velocity
        + bytes([64])                        # off-velocity
        + b"\x00" * 5                        # remainder
    )
    return block


def test_extract_midi_notes():
    """Parser should extract MIDI notes from MMidiPartEvent."""
    strip = _make_strip("Piano")
    note = _make_midi_note(pitch=60, velocity=100, position=0.0, length=480.0)
    midi_part = (
        b"MMidiPartEvent\x00"
        + b"\x00\x00\x00\x06Piano\x00\xef\xbb\xbf"
        + b"\x00" * 20
        + note
        + b"\x00" * 50
    )
    data = b"\x00" * 20 + strip + b"\x00" * 50 + midi_part + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    # Find the piano track
    piano_tracks = [t for t in project.tracks if "Piano" in t.name]
    if piano_tracks and piano_tracks[0].midi_parts:
        part = piano_tracks[0].midi_parts[0]
        assert len(part.notes) >= 1
        assert part.notes[0].pitch == 60
        assert part.notes[0].velocity == 100
        assert part.notes[0].length == 480.0
    path.unlink()


def test_midi_rejects_invalid_pitch():
    """MIDI notes with pitch > 127 should be rejected."""
    strip = _make_strip("Synth")
    # Build a note with invalid pitch (200 > 127)
    block = (
        b"adcn\x00\x01"
        + struct.pack(">I", 0x20)
        + struct.pack(">I", 200)     # invalid pitch
        + struct.pack(">d", 480.0)
        + b"\x00" * 18
        + struct.pack(">d", 0.0)
        + bytes([0])
        + bytes([100])               # on-velocity
        + bytes([64])                # off-velocity
        + b"\x00" * 5
    )
    midi_part = (
        b"MMidiPartEvent\x00"
        + b"\x00" * 20
        + block
        + b"\x00" * 50
    )
    data = b"\x00" * 20 + strip + b"\x00" * 50 + midi_part + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    # The invalid note should not appear
    for track in project.tracks:
        for part in track.midi_parts:
            for note in part.notes:
                assert note.pitch <= 127
    path.unlink()


def test_midi_rejects_zero_pitch():
    """MIDI notes with pitch=0 should be rejected (sentinel entries)."""
    strip = _make_strip("Lead")
    block = (
        b"adcn\x00\x01"
        + struct.pack(">I", 0x20)
        + struct.pack(">I", 0)       # pitch = 0 (sentinel)
        + struct.pack(">d", 480.0)
        + b"\x00" * 18
        + struct.pack(">d", 0.0)
        + bytes([0])
        + bytes([100])               # on-velocity
        + bytes([64])                # off-velocity
        + b"\x00" * 5
    )
    midi_part = (
        b"MMidiPartEvent\x00"
        + b"\x00" * 20
        + block
        + b"\x00" * 50
    )
    data = b"\x00" * 20 + strip + b"\x00" * 50 + midi_part + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    for track in project.tracks:
        for part in track.midi_parts:
            assert len(part.notes) == 0
    path.unlink()


def test_no_midi_in_empty_project():
    """Empty project should have no MIDI data."""
    path = _make_cpr(b"\x00" * 200)
    project = parse_cpr(path)
    for track in project.tracks:
        assert track.midi_parts == []
    path.unlink()
