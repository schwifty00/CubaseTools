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
