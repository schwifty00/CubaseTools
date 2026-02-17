# .cpr File Format Notes

## Overview

Cubase .cpr files are binary project files containing all project data: track structure, plugin settings, audio references, tempo, markers, and more. The format is proprietary and undocumented.

## Known Structure

### Track Markers

Track entries are identified by ASCII markers in the binary stream:

| Marker | Track Type |
|--------|-----------|
| `MAudioTrackEvent` | Audio Track |
| `MInstrumentTrackEvent` | Instrument Track |
| `MMidiTrackEvent` | MIDI Track |
| `MFXChannelTrackEvent` | FX Channel |
| `MGroupChannelTrackEvent` | Group Channel |
| `MVCATrackEvent` | VCA Fader |
| `MMixerTrackEvent` | Master/Mixer |
| `MFolderTrackEvent` | Folder Track |

### Audio References

Audio file names appear in both UTF-8 and UTF-16-LE encoding:
- UTF-8: Direct ASCII `.wav` filenames
- UTF-16-LE: Alternating byte + `\x00` patterns ending with `w\x00a\x00v\x00`

### Plugin Data

Plugin settings are stored in two ways:
1. **Binary chunks** with raw parameter data
2. **XML chunks** (`PresetChunkXMLTree`) containing structured preset data

XML chunks start with `<?xml` and contain plugin parameters in attribute or element form.

### Version String

Cubase version appears as ASCII string (e.g., `Cubase 15\x00`).

### Sample Rate

Stored as 4-byte integer (LE or BE) near `SampleRate` or `SRateForAudioIO` markers.

### Tempo

Stored as 8-byte double near `TempoEvent` or `MTempoTrackEvent` markers.
