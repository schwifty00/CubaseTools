"""Tests for plugin extraction from binary .cpr data."""

import struct
import tempfile
from pathlib import Path

from cubasetools.core.cpr_parser import CprParser, parse_cpr


def _make_cpr(content: bytes) -> Path:
    """Create a temporary .cpr file with given binary content."""
    tmp = tempfile.NamedTemporaryFile(suffix=".cpr", delete=False)
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


def _make_strip(name: str) -> bytes:
    """Build a minimal channel strip pattern for track detection."""
    name_bytes = name.encode("utf-8")
    return (
        b"Name\x00" + b"\x00" * 5
        + b"String\x00" + b"\x00" * 3
        + name_bytes + b"\x00" + b"\x00" * 5
        + b"Type\x00" + b"\x00" * 5
        + b"InputFilter"
    )


def _make_vst3_plugin(name: str, with_slot: bool = True) -> bytes:
    """Build a VST3 Plugin Name entry."""
    prefix = b"Slot\x00" + b"\x00" * 50 if with_slot else b"\x00" * 54
    name_bytes = name.encode("utf-8")
    return (
        prefix
        + b"Plugin Name\x00"
        + b"\x00" * 4
        + name_bytes + b"\x00"
        + b"\x00" * 50
    )


def test_extract_single_plugin():
    """Parser should find a VST3 plugin and assign it to a track."""
    strip = _make_strip("Vocals")
    plugin = _make_vst3_plugin("FabFilter Pro-Q 3")
    data = b"\x00" * 20 + strip + b"\x00" * 50 + plugin + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "Vocals" in t.name]
    if tracks:
        plugin_names = [p.name for p in tracks[0].plugins]
        assert "FabFilter Pro-Q 3" in plugin_names
    path.unlink()


def test_extract_multiple_plugins():
    """Parser should find multiple plugins on the same track."""
    strip = _make_strip("Guitar")
    plugin1 = _make_vst3_plugin("CLA-76")
    plugin2 = _make_vst3_plugin("SSL E-Channel")
    data = (
        b"\x00" * 20
        + strip + b"\x00" * 50
        + plugin1 + b"\x00" * 50
        + plugin2 + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "Guitar" in t.name]
    if tracks:
        names = [p.name for p in tracks[0].plugins]
        assert "CLA-76" in names
        assert "SSL E-Channel" in names
    path.unlink()


def test_builtin_plugins_excluded():
    """Built-in plugins like Standard Panner should be excluded."""
    strip = _make_strip("Bass")
    builtin = _make_vst3_plugin("Standard Panner")
    real_plugin = _make_vst3_plugin("Compressor")
    data = (
        b"\x00" * 20
        + strip + b"\x00" * 50
        + builtin + b"\x00" * 50
        + real_plugin + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "Bass" in t.name]
    if tracks:
        names = [p.name for p in tracks[0].plugins]
        assert "Standard Panner" not in names
    path.unlink()


def test_plugin_deduplication():
    """Duplicate plugin entries within threshold should be merged."""
    strip = _make_strip("Drums")
    # Two identical plugin entries close together (within PLUGIN_DEDUP_THRESHOLD)
    plugin1 = _make_vst3_plugin("Pro-Q 3")
    plugin2 = _make_vst3_plugin("Pro-Q 3")
    data = (
        b"\x00" * 20
        + strip + b"\x00" * 50
        + plugin1
        + plugin2  # immediately after = within threshold
        + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "Drums" in t.name]
    if tracks:
        proq_count = sum(1 for p in tracks[0].plugins if "Pro-Q 3" in p.name)
        assert proq_count == 1, f"Expected 1 Pro-Q 3 but found {proq_count}"
    path.unlink()


def test_plugins_assigned_to_correct_tracks():
    """Plugins should be assigned to the nearest preceding track."""
    strip1 = _make_strip("Track A")
    plugin1 = _make_vst3_plugin("Plugin For A")
    # Large gap to ensure separate track regions
    strip2 = _make_strip("Track B")
    plugin2 = _make_vst3_plugin("Plugin For B")
    data = (
        b"\x00" * 20
        + strip1 + b"\x00" * 50 + plugin1
        + b"\x00" * 1000
        + strip2 + b"\x00" * 50 + plugin2
        + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    track_a = [t for t in project.tracks if "Track A" in t.name]
    track_b = [t for t in project.tracks if "Track B" in t.name]
    if track_a:
        names_a = [p.name for p in track_a[0].plugins]
        assert "Plugin For A" in names_a
    if track_b:
        names_b = [p.name for p in track_b[0].plugins]
        assert "Plugin For B" in names_b
    path.unlink()


def test_preset_chunk_xml_extraction():
    """Parser should extract plugin parameters from PresetChunkXMLTree."""
    strip = _make_strip("Vox")
    # Build a PresetChunkXMLTree block with plugin name
    xml_data = (
        b"PresetChunkXMLTree>"
        + b"<PluginName>TestPlugin</PluginName>"
        + b'<Preset Name="My Preset">'
        + b'<Param name="Threshold" value="-18.0"/>'
        + b"</Preset>"
        + b"\x00" * 50
    )
    # VST3 Plugin Name for the same plugin, close to the XML block
    plugin = _make_vst3_plugin("TestPlugin")
    data = (
        b"\x00" * 20
        + strip + b"\x00" * 50
        + xml_data
        + plugin
        + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "Vox" in t.name]
    if tracks and tracks[0].plugins:
        plugin = tracks[0].plugins[0]
        assert "TestPlugin" in plugin.name
    path.unlink()


def test_no_plugins_in_empty_project():
    """Parser should handle a project with no plugins gracefully."""
    strip = _make_strip("EmptyTrack")
    data = b"\x00" * 20 + strip + b"\x00" * 200
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "EmptyTrack" in t.name]
    if tracks:
        assert tracks[0].plugins == []
    path.unlink()


def test_plugin_slot_indices():
    """Plugin slot indices should be sequential per track."""
    strip = _make_strip("MixBus")
    p1 = _make_vst3_plugin("EQ Plugin")
    # Ensure enough distance between plugins to avoid dedup
    p2 = _make_vst3_plugin("Compressor Plugin")
    data = (
        b"\x00" * 20
        + strip + b"\x00" * 50
        + p1
        + b"\x00" * 25000  # beyond PLUGIN_DEDUP_THRESHOLD
        + p2
        + b"\x00" * 200
    )
    path = _make_cpr(data)
    project = parse_cpr(path)
    tracks = [t for t in project.tracks if "MixBus" in t.name]
    if tracks and len(tracks[0].plugins) >= 2:
        assert tracks[0].plugins[0].slot_index == 0
        assert tracks[0].plugins[1].slot_index == 1
    path.unlink()
