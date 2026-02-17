"""Dataclasses for all CubaseTools data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TrackType(Enum):
    AUDIO = "audio"
    INSTRUMENT = "instrument"
    MIDI = "midi"
    FX = "fx"
    GROUP = "group"
    VCA = "vca"
    MASTER = "master"
    FOLDER = "folder"
    UNKNOWN = "unknown"


class EQBandType(Enum):
    LOW_CUT = "low_cut"
    LOW_SHELF = "low_shelf"
    PEAK = "peak"
    HIGH_SHELF = "high_shelf"
    HIGH_CUT = "high_cut"
    NOTCH = "notch"


@dataclass
class EQBand:
    enabled: bool = True
    band_type: EQBandType = EQBandType.PEAK
    frequency: float = 1000.0
    gain: float = 0.0
    q: float = 1.0


@dataclass
class CompressorSettings:
    plugin_name: str = ""
    threshold: float = 0.0
    ratio: float = 1.0
    attack: float = 10.0
    release: float = 100.0
    knee: float = 0.0
    makeup_gain: float = 0.0
    input_gain: float = 0.0
    output_gain: float = 0.0
    raw_parameters: dict[str, float] = field(default_factory=dict)


@dataclass
class SendSlot:
    target_name: str = ""
    level_db: float = 0.0
    enabled: bool = True


@dataclass
class PluginInstance:
    name: str = ""
    vendor: str = ""
    uid: str = ""
    slot_index: int = 0
    bypassed: bool = False
    eq_bands: list[EQBand] = field(default_factory=list)
    compressor: CompressorSettings | None = None
    parameters: dict[str, float] = field(default_factory=dict)
    raw_chunk: bytes = field(default_factory=bytes, repr=False)


@dataclass
class Track:
    name: str = ""
    track_type: TrackType = TrackType.UNKNOWN
    index: int = 0
    volume: float = 0.0
    pan: float = 0.0
    muted: bool = False
    solo: bool = False
    color: str = ""
    plugins: list[PluginInstance] = field(default_factory=list)
    audio_files: list[str] = field(default_factory=list)
    output_bus: str = ""
    sends: list[SendSlot] = field(default_factory=list)
    has_content: bool = False


@dataclass
class Marker:
    name: str = ""
    position: float = 0.0
    marker_id: int = 0


@dataclass
class CubaseProject:
    file_path: Path = field(default_factory=Path)
    project_name: str = ""
    cubase_version: str = ""
    sample_rate: int = 44100
    bit_depth: int = 24
    tempo: float = 120.0
    time_signature: str = "4/4"
    tracks: list[Track] = field(default_factory=list)
    markers: list[Marker] = field(default_factory=list)
    referenced_audio: set[str] = field(default_factory=set)
    file_size: int = 0

    @property
    def track_count(self) -> int:
        return len(self.tracks)

    @property
    def plugin_count(self) -> int:
        return sum(len(t.plugins) for t in self.tracks)

    @property
    def audio_track_count(self) -> int:
        return sum(1 for t in self.tracks if t.track_type == TrackType.AUDIO)

    def all_plugins(self) -> list[tuple[Track, PluginInstance]]:
        result = []
        for track in self.tracks:
            for plugin in track.plugins:
                result.append((track, plugin))
        return result

    def plugins_by_name(self) -> dict[str, list[tuple[Track, PluginInstance]]]:
        by_name: dict[str, list[tuple[Track, PluginInstance]]] = {}
        for track, plugin in self.all_plugins():
            by_name.setdefault(plugin.name, []).append((track, plugin))
        return by_name


@dataclass
class ProjectStats:
    project: CubaseProject = field(default_factory=CubaseProject)
    total_audio_files: int = 0
    used_audio_files: int = 0
    unused_audio_files: int = 0
    total_audio_size: int = 0
    unused_audio_size: int = 0
    audio_dir: Path | None = None
    unused_files: list[Path] = field(default_factory=list)
    used_files: list[Path] = field(default_factory=list)
