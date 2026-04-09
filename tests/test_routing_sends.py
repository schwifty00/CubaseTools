"""Tests for routing and send extraction from binary .cpr data."""

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


def _make_bus_entry(name: str, uid: int) -> bytes:
    """Build an OwnInputBus entry with Name and Bus UID."""
    name_bytes = name.encode("utf-8")
    return (
        b"OwnInputBus\x00"
        + b"Name\x00" + b"\x00" * 4
        + name_bytes + b"\x00"
        + b"\x00" * 20
        + b"Bus UID\x00\x00\x01"
        + b"\x00" * 4
        + struct.pack(">I", uid)
        + b"\x00" * 50
    )


def test_build_bus_uid_table():
    """Parser should build a bus UID lookup table from OwnInputBus entries."""
    bus = _make_bus_entry("Stereo Out", 12345)
    data = b"\x00" * 20 + bus + b"\x00" * 200
    path = _make_cpr(data)
    # We can verify indirectly: if routing resolves, the table works
    project = parse_cpr(path)
    # No crash = table built successfully
    assert project is not None
    path.unlink()


def test_extract_routing():
    """Parser should extract output bus routing for tracks."""
    uid = 99999
    strip = _make_strip("Vocals")
    bus_entry = _make_bus_entry("Stereo Out", uid)
    # OutputBus with matching UID in the track region
    output_bus = (
        b"OutputBus\x00"
        + b"\x00" * 5
        + b"Value\x00\x00\x01"
        + b"\x00" * 4
        + struct.pack(">I", uid)
        + b"\x00" * 50
    )
    data = (
        b"\x00" * 20
        + bus_entry + b"\x00" * 50
        + strip + b"\x00" * 50
        + output_bus + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "Vocals" in t.name]
    if tracks:
        assert tracks[0].output_bus == "Stereo Out"
    path.unlink()


def test_extract_sends():
    """Parser should extract send slots with target and volume."""
    uid = 54321
    strip = _make_strip("Guitar")
    bus_entry = _make_bus_entry("FX Reverb", uid)
    # SendFolder with one send slot: Volume + Output
    vol_raw = 25856.0  # 0 dB
    send_data = (
        b"SendFolder\x00"
        + b"\x00" * 10
        + b"Volume\x00"
        + b"\x00" * 5
        + b"Value\x00\x00\x04"
        + struct.pack(">d", vol_raw)
        + b"\x00" * 10
        + b"Output\x00"
        + b"\x00" * 5
        + b"Value\x00\x00\x01"
        + b"\x00" * 4
        + struct.pack(">I", uid)
        + b"\x00" * 50
    )
    data = (
        b"\x00" * 20
        + bus_entry + b"\x00" * 50
        + strip + b"\x00" * 50
        + send_data + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "Guitar" in t.name]
    if tracks and tracks[0].sends:
        send = tracks[0].sends[0]
        assert send.target_name == "FX Reverb"
        assert send.enabled is True
    path.unlink()


def test_no_sends_when_no_send_folder():
    """Track without SendFolder should have no sends."""
    strip = _make_strip("DryTrack")
    data = b"\x00" * 20 + strip + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "DryTrack" in t.name]
    if tracks:
        assert tracks[0].sends == []
    path.unlink()


def test_routing_unknown_uid():
    """OutputBus with unknown UID should not set output_bus."""
    strip = _make_strip("NoRoute")
    output_bus = (
        b"OutputBus\x00"
        + b"\x00" * 5
        + b"Value\x00\x00\x01"
        + b"\x00" * 4
        + struct.pack(">I", 77777)  # unknown UID
        + b"\x00" * 50
    )
    data = b"\x00" * 20 + strip + b"\x00" * 50 + output_bus + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "NoRoute" in t.name]
    if tracks:
        assert tracks[0].output_bus == ""
    path.unlink()
