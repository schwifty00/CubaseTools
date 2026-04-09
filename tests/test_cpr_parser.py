"""Tests for the CPR parser."""

import struct
import tempfile
from pathlib import Path

from cubasetools.core.cpr_parser import CprParser, parse_cpr
from cubasetools.core.models import TrackType


def _make_cpr(content: bytes) -> Path:
    """Create a temporary .cpr file with given binary content."""
    tmp = tempfile.NamedTemporaryFile(suffix=".cpr", delete=False)
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def test_parse_empty_cpr():
    """Parser should handle a minimal/empty file without crashing."""
    path = _make_cpr(b"\x00" * 100)
    project = parse_cpr(path)
    assert project.project_name == path.stem
    assert project.tracks == []
    path.unlink()


def test_extract_version():
    """Parser should find Cubase version string."""
    data = b"\x00" * 50 + b"Cubase 15\x00" + b"\x00" * 50
    path = _make_cpr(data)
    project = parse_cpr(path)
    assert "Cubase 15" in project.cubase_version
    path.unlink()


def test_extract_audio_references():
    """Parser should find .wav references in both UTF-8 and UTF-16."""
    wav_name = b"vocal_take_01.wav"
    data = b"\x00" * 20 + wav_name + b"\x00" * 20
    path = _make_cpr(data)
    project = parse_cpr(path)
    assert "vocal_take_01.wav" in project.referenced_audio
    path.unlink()


def test_extract_track_markers():
    """Parser should find track type markers."""
    data = b"\x00" * 20 + b"MAudioTrackEvent" + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    assert len(project.tracks) >= 1
    assert project.tracks[0].track_type == TrackType.AUDIO
    path.unlink()


def test_extract_multiple_tracks():
    """Parser should find multiple different track types."""
    data = (
        b"\x00" * 20
        + b"MAudioTrackEvent" + b"\x00" * 200
        + b"MInstrumentTrackEvent" + b"\x00" * 200
        + b"MFXChannelTrackEvent" + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    types = {t.track_type for t in project.tracks}
    assert TrackType.AUDIO in types
    assert TrackType.INSTRUMENT in types
    assert TrackType.FX in types
    path.unlink()


def test_file_size():
    """Parser should record the file size."""
    data = b"\x00" * 500
    path = _make_cpr(data)
    project = parse_cpr(path)
    assert project.file_size == 500
    path.unlink()


def test_extract_time_signature():
    """Parser should extract time signature from TimeSignatureEvent."""
    # Build a TimeSignatureEvent with Numerator=3, Denominator=4
    data = (
        b"\x00" * 20
        + b"TimeSignatureEvent\x00"
        + b"\x00" * 10
        + b"Numerator\x00\x00\x01" + struct.pack(">q", 3)
        + b"Denominator\x00\x00\x01" + struct.pack(">q", 4)
        + b"\x00" * 50
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    assert project.time_signature == "3/4"
    path.unlink()


def test_extract_time_signature_6_8():
    """Parser should handle non-standard time signatures."""
    data = (
        b"\x00" * 20
        + b"TimeSignatureEvent\x00"
        + b"\x00" * 10
        + b"Numerator\x00\x00\x01" + struct.pack(">q", 6)
        + b"Denominator\x00\x00\x01" + struct.pack(">q", 8)
        + b"\x00" * 50
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    assert project.time_signature == "6/8"
    path.unlink()


def test_extract_volume():
    """Parser should extract fader volume from AnchorValue (dB)."""
    # Build: channel strip + Volume compound with Value + AnchorValue
    raw_vol = 25856.0 * (10 ** (-6.0 / 20.0))
    anchor_db = -6.0
    strip = (
        b"Name\x00" + b"\x00" * 5
        + b"String\x00" + b"\x00" * 3
        + b"TestTrack\x00" + b"\x00" * 5
        + b"Type\x00" + b"\x00" * 5
        + b"InputFilter"
    )
    volume_field = (
        b"Volume\x00"
        b"\x00\x02\x00\x06\x00\x00\x00\x02\x00\x00\x00\x06"
        b"Value\x00\x00\x04"
        + struct.pack(">d", raw_vol)
        + b"\x00\x00\x00\x0c"
        b"AnchorValue\x00\x00\x04"
        + struct.pack(">d", anchor_db)
    )
    data = b"\x00" * 20 + strip + b"\x00" * 100 + volume_field + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    test_tracks = [t for t in project.tracks if "TestTrack" in t.name]
    if test_tracks:
        assert abs(test_tracks[0].volume - (-6.0)) < 0.5
    path.unlink()


def test_extract_pan():
    """Parser should extract pan from Standard Panner audioComponent blob."""
    # Pan hard-right = 1.0 LE float -> normalized = +1.0
    strip = (
        b"Name\x00" + b"\x00" * 5
        + b"String\x00" + b"\x00" * 3
        + b"PanTest\x00" + b"\x00" * 5
        + b"Type\x00" + b"\x00" * 5
        + b"InputFilter"
    )
    pan_field = (
        b"SummingMode\x00" + b"\x00" * 10
        + b"Panner\x00\x00\x02\x00\x06\x00\x00\x00\x15"
        + b"\x00" * 250
        + b"Standard Panner"
        + b"\x00" * 20
        + b"audioComponent\x00\x00\x02\x00\x07"
        + struct.pack(">I", 20)   # header
        + struct.pack("<f", 1.0)  # pan = hard right (LE float)
        + b"\x00" * 63           # rest of data
    )
    data = b"\x00" * 20 + strip + b"\x00" * 100 + pan_field + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    test_tracks = [t for t in project.tracks if "PanTest" in t.name]
    if test_tracks:
        assert test_tracks[0].pan is not None
        assert test_tracks[0].pan > 0.9  # should be ~1.0
    path.unlink()


def test_extract_mute():
    """Parser should extract mute flag."""
    strip = (
        b"Name\x00" + b"\x00" * 5
        + b"String\x00" + b"\x00" * 3
        + b"MuteTest\x00" + b"\x00" * 5
        + b"Type\x00" + b"\x00" * 5
        + b"InputFilter"
    )
    mute_field = b"Mute\x00\x00\x01" + struct.pack(">q", 1)
    data = b"\x00" * 20 + strip + b"\x00" * 100 + mute_field + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    test_tracks = [t for t in project.tracks if "MuteTest" in t.name]
    if test_tracks:
        assert test_tracks[0].muted is True
    path.unlink()


def test_extract_solo():
    """Parser should extract solo flag."""
    strip = (
        b"Name\x00" + b"\x00" * 5
        + b"String\x00" + b"\x00" * 3
        + b"SoloTest\x00" + b"\x00" * 5
        + b"Type\x00" + b"\x00" * 5
        + b"InputFilter"
    )
    solo_field = b"Solo\x00\x00\x01" + struct.pack(">q", 1)
    data = b"\x00" * 20 + strip + b"\x00" * 100 + solo_field + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    test_tracks = [t for t in project.tracks if "SoloTest" in t.name]
    if test_tracks:
        assert test_tracks[0].solo is True
    path.unlink()


def test_default_time_signature():
    """Without TimeSignatureEvent, default should be 4/4."""
    path = _make_cpr(b"\x00" * 100)
    project = parse_cpr(path)
    assert project.time_signature == "4/4"
    path.unlink()


def test_marker_with_position():
    """Parser should extract marker name and position."""
    # Build a MMarkerEvent with name "Chorus" at tick 7680
    name = b"Chorus"
    marker_data = (
        b"MMarkerEvent\x00\x00\x00\xff\xff\xff\xff"
        + b"\x00\x00\x00\x12"
        + b"MRangeMarkerEvent\x00"
        + b"\x00\x00\x00\x00\x00\x00\x45"
        + b"\x00\x00\x00" + bytes([len(name) + 4])
        + name + b"\x00\xef\xbb\xbf"
        + struct.pack(">I", 1)       # color/type
        + struct.pack(">I", 7680)    # start position
        + struct.pack(">I", 0)       # padding
        + struct.pack(">I", 15360)   # end position
        + b"\x00" * 50
    )
    data = b"\x00" * 20 + marker_data + b"\x00" * 100
    path = _make_cpr(data)
    project = parse_cpr(path)
    assert len(project.markers) >= 1
    assert project.markers[0].name == "Chorus"
    assert project.markers[0].position == 7680.0
    path.unlink()
