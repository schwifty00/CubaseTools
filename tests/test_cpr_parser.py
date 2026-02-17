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
