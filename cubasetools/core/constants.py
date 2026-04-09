"""Known binary markers and patterns found in .cpr files."""

# Track type markers found in Cubase .cpr binary data
TRACK_MARKERS = {
    b"MAudioTrackEvent": "audio",
    b"MInstrumentTrackEvent": "instrument",
    b"MMidiTrackEvent": "midi",
    b"MFXChannelTrackEvent": "fx",
    b"MGroupChannelTrackEvent": "group",
    b"MVCATrackEvent": "vca",
    b"MMixerTrackEvent": "master",
    b"MFolderTrackEvent": "folder",
    b"MMarkerTrackEvent": "unknown",  # markers extracted separately
    b"MSamplerTrackEvent": "instrument",
}

# Plugin-related markers
PLUGIN_MARKERS = {
    b"PluginProgram": "plugin_program",
    b"VSTPluginURI": "vst_uri",
    b"PresetChunkXMLTree": "preset_xml",
    b"editController": "edit_controller",
    b"audioProcessor": "audio_processor",
}

# XML chunk boundaries
XML_START_MARKER = b"<?xml"
XML_END_MARKERS = [b"</pluginProgram>", b"</MetaInfo>", b"</VstPreset>"]

# Audio file extensions for reference matching
AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".aif", ".aiff", ".ogg", ".m4a"}

# Known Cubase audio folder names
AUDIO_FOLDER_NAMES = ["Audio", "audio", "Aufnahmen", "Recordings"]

# Plugin vendor identifiers commonly found in .cpr data
KNOWN_VENDORS = {
    "Waves": "Waves",
    "FabFilter": "FabFilter",
    "Steinberg": "Steinberg",
    "SSL": "Solid State Logic",
    "Universal Audio": "Universal Audio",
    "iZotope": "iZotope",
    "Softube": "Softube",
    "Plugin Alliance": "Plugin Alliance",
    "Slate Digital": "Slate Digital",
    "Sonnox": "Sonnox",
    "Valhalla": "Valhalla DSP",
    "Tokyo Dawn": "Tokyo Dawn Labs",
}

# Cubase version markers
VERSION_MARKERS = [
    b"Cubase 15",
    b"Cubase 14",
    b"Cubase 13",
    b"Cubase 12",
    b"Cubase 11",
    b"Cubase 10",
]

# ── Parser numeric constants ────────────────────────────────────────────
# These values are derived from Cubase's internal binary representation.

# Fader position for 0 dB (unity gain) in Cubase's mixer
VOLUME_UNITY = 25856.0
# Pan center value in Cubase's panner (0..32767 range, center = midpoint)
PAN_CENTER = 16383.5

# Deduplication distance thresholds (bytes): entries closer than this
# with the same name are considered duplicates of the same channel/plugin.
STRIP_DEDUP_THRESHOLD = 40_000
PLUGIN_DEDUP_THRESHOLD = 20_000
# Max distance (bytes) between VST3 Plugin Name and PresetChunkXMLTree
# for them to be considered the same plugin instance.
PRESET_MERGE_DISTANCE = 5_000

# Minimum gap (bytes) between consecutive strips to be considered the
# I/O section boundary. Large VSTi plugins can create multi-MB gaps
# within the normal track section, so this must be conservative.
IO_GAP_THRESHOLD = 5_000_000

# Default region size (bytes) when scanning per-track data (volume, pan,
# mute, solo, monitor, routing). Limits search to the area between
# consecutive strip positions.
PER_TRACK_REGION_SIZE = 200_000

# Valid tempo range (BPM) — values outside are rejected as parse errors.
TEMPO_MIN = 20.0
TEMPO_MAX = 400.0

# Maximum valid PPQ position — values above are rejected as binary noise.
POSITION_LIMIT = 1e8

# Maximum distance (bytes) between a preset name and a plugin for
# preset-to-plugin assignment.
PRESET_ASSIGN_DISTANCE = 50_000

# Maximum distance (bytes) between a color index and a strip position
# for color assignment.
COLOR_ASSIGN_DISTANCE = 200_000

# Maximum number of send slots per track in Cubase.
MAX_SEND_SLOTS = 8

# Region size (bytes) to scan within a SendFolder for send slot data.
SEND_FOLDER_REGION_SIZE = 10_240
