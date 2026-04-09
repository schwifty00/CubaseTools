# .cpr File Format – Complete Reference

## Overview

Cubase .cpr files are binary project files containing all project data: track
structure, plugin settings, audio references, tempo, markers, routing, and more.
The format is proprietary and undocumented by Steinberg.

This document describes the binary patterns we have reverse-engineered and
currently parse in CubaseTools. All findings are verified against real Cubase
projects (versions 10–15).

---

## General Binary Encoding

The CPR format uses a consistent **named-field** encoding throughout:

```
FieldName\x00  <type: 2 bytes BE>  <value>
```

### Type Tags

| Tag (BE) | Type | Value Layout |
|----------|------|-------------|
| `0x0001` | Integer | 8 bytes BE int64 |
| `0x0002` | Compound | 2 bytes flags + 4 bytes child count, then children |
| `0x0004` | Double | 8 bytes BE double |
| `0x0008` | String | 4 bytes BE uint32 length + string bytes |

### Compound Fields

Compound fields contain child fields, each prefixed by:
```
<4 bytes BE uint32 name_length> <name\x00> <type: 2 bytes> <value>
```

### BOM Marker

The UTF-8 BOM `\xef\xbb\xbf` appears as a separator/terminator in some
contexts, particularly after track event names and before color indices.

### Reversed 4-char Markers

Some internal markers are stored as reversed ASCII strings:

| Binary | Decoded | Meaning |
|--------|---------|---------|
| `kcoL` | Lock | Lock flag |
| `shtE` | Etsh | Part of embedded event data |
| `BlTT` | TTlB | Tempo lower bound |
| `BuTT` | TTuB | Tempo upper bound |
| `iCVT` | TVCi | Tempo curve variant |

---

## Metadata

### Cubase Version

Two formats exist depending on Cubase version:

**Modern (Cubase 12+):** `Version X.Y.Z\x00` in the file header (first ~2000
bytes).

```
\x00\x00\x00\x0fVersion 15.0.6\x00
```

Parsed with regex: `Version (\d+\.\d+\.\d+)`

**Legacy (Cubase 10–11):** ASCII marker like `Cubase 10\x00`.

The file header also contains the build date and platform:
```
Cubase\x00 ... Version 15.0.6\x00 ... Nov 25 2025\x00 ... WIN64\x00
```

### Sample Rate

**⚠ Important:** The `SampleRate` keyword appears in BOTH binary structures
AND XML plugin preset data. XML occurrences (containing `>` or `<` nearby)
must be skipped.

**Binary pattern:** `SampleRate` → `Float\x00\x00\x04` + 8 bytes BE double.

Full structure:
```
SampleRate\x00
  \x00\x00\x00\x05
  Type\x00  \x00\x01  <8 bytes int64>    ← type code (4 = float)
  \x00\x00\x00\x04
  Flags\x00 \x00\x01  <8 bytes int64>    ← flags
  \x00\x00\x00\x02
  Float\x00 \x00\x04  <8 bytes BE double> ← sample rate value
```

**Known rates:** 44100, 48000, 88200, 96000, 176400, 192000

**Pitfall:** If `data.find(b"SampleRate")` is used, it may find the XML
occurrence first (e.g., `SampleRate">48000</Descriptor>`), which does NOT
have the `Float` sub-field. Always iterate ALL occurrences and skip XML ones.

### Tempo (BPM)

Tempo is stored in two possible locations:

**Strategy 1 — MTempoEvent (most reliable):**

The `MTempoEvent` structure contains a `BPM` named field:

```
MTempoEvent ... BPM\x00\x00\x04 <8 bytes BE double>
```

Regex: `MTempoEvent.*?BPM\x00\x00\x04(.{8})` with `re.DOTALL`

This is the **initial tempo** of the project (what's shown in the transport
bar). Found in all Cubase versions that use a fixed tempo.

**Strategy 2 — MTempoTrackEvent header (embedded double):**

For projects with tempo track automation, the first tempo event's BPM value
is embedded as a BE double within the first ~500 bytes of the
`MTempoTrackEvent` header. A byte-by-byte scan finds the first double in the
range 20–400.

**Default:** If neither strategy finds a value, the project uses **120 BPM**
(Cubase default).

**⚠ Not tempo data:**
- `Tempo\x00\x00\x04` fields inside `PGridDefinition` / `GridDef` — these are
  grid overlay presets, not the project tempo.
- `RehearsalTempo` — this is the tap tempo rehearsal setting.
- Doubles in the TempoTrack `Node` area — these are PPQ positions, not BPM
  values (typically > 100,000).

### Time Signature

**Pattern:** `TimeSignatureEvent` inside `SignatureTrackEvent`.

**Structure:**
```
TimeSignatureEvent
  ├── Flags      : int64  = 0
  ├── Start      : double = 0.0  (position in PPQ)
  ├── Length     : double = 1.0
  ├── Bar        : int64  = bar number (0-based)
  ├── Numerator  : int64  = e.g. 4
  └── Denominator: int64  = e.g. 4
```

**Field encoding:** Each sub-field follows the standard named-field pattern:
`Numerator\x00` + `\x00\x01` (type int) + 8 bytes BE int64.

**Multiple events** can exist for time signature changes mid-song. Only the
first event (position 0) is used as the project time signature.

**Default:** 4/4 if no `TimeSignatureEvent` is found.

---

## Tracks

### Primary Strategy: Channel Strips

Each mixer channel has a strip definition with this pattern:

```
Name\x00 .{0,20} String\x00 .{0,10} TRACKNAME\x00 .{0,30} Type\x00 .{0,20} InputFilter
```

**Regex:** `Name\x00.{0,20}?String\x00.{0,10}?([\x20-\x7e]{2,50})\x00.{0,30}?Type\x00.{0,20}?InputFilter`

### Track Type Classification (IDString)

Each mixer channel has an `IDString\x00` entry identifying its engine type:

| IDString Value | Track Type |
|----------------|-----------|
| `Audio` | Audio Track |
| `GroupChannel` | Group Channel |
| `FxChannel` | FX Channel |
| `SamplerChannel` | Instrument (Sampler) |
| `Synth` | Instrument (VSTi) |
| `MidiChannel` | MIDI Track |
| `InputChannel` | Hardware Input |
| `OutputChannel` | Master/Output Bus |

**Algorithm:** IDStrings are assigned to the nearest preceding channel strip by
binary position. Unmatched strips inherit the type of the nearest neighbor.

### Fallback Strategy: Legacy Track Markers

Used when no channel strips are found (very old Cubase versions):

| Marker | Track Type |
|--------|-----------|
| `MAudioTrackEvent` | Audio |
| `MInstrumentTrackEvent` | Instrument |
| `MMidiTrackEvent` | MIDI |
| `MFXChannelTrackEvent` | FX |
| `MGroupChannelTrackEvent` | Group |
| `MVCATrackEvent` | VCA |
| `MMixerTrackEvent` | Master |
| `MFolderTrackEvent` | Folder |
| `MSamplerTrackEvent` | Instrument |

### Deduplication

- Channel strips within 40 KB of each other with the same name are duplicates
  (Cubase stores editor + processor states separately).
- A gap > 1 MB between consecutive strips marks the I/O section boundary.
  Everything after the gap is hardware I/O (filtered out, except Stereo Out).
- Global post-processing deduplicates by track name, keeping the entry with
  the most plugin data.

### Track Color

**⚠ Not working for Cubase 12+.** The color index extraction relies on
legacy track event markers (`MAudioTrackEvent`, `MFolderTrack`, etc.) which
are barely present in Cubase 12+ projects (typically only 1–4 per file, vs
dozens of channel strips). The color palette IS extracted correctly, but the
per-track color index mapping fails because the track event headers don't
exist for most tracks.

**Legacy approach (Cubase 10–11):** Color palette index stored as 4 bytes
BE int32 after the BOM (`\xef\xbb\xbf`) following the track name in the
event header.

- Value `-1` (0xFFFFFFFF) = default / no color
- Value `0` = typically default (not assigned explicitly)
- Value `1..N` = index into the project color palette

**Color palette:** Stored in `UColorSet` as repeated entries:
`Color 16\x00\xef\xbb\xbf` + 4 bytes ARGB (BE). This works correctly
across all Cubase versions.

**TODO:** Reverse-engineer how Cubase 12+ stores per-track color assignments.
The palette is present but the index-to-track mapping is in an unknown
location (not in channel strips, not in legacy event headers).

---

## Channel Strip Parameters

All parameters below are found within each track's binary region (from its
strip position to the next strip, max 200 KB).

### Volume (Fader)

**Pattern:** `Volume\x00` compound field with 2 children: `Value` (raw fader
position) and `AnchorValue` (the actual dB reading shown in Cubase's mixer).

**Full binary pattern:**
```
Volume\x00
  \x00\x02          (type = compound)
  \x00\x06          (flags)
  \x00\x00\x00\x02  (2 children)
  \x00\x00\x00\x06  (name_len = 6)
  Value\x00
    \x00\x04        (type = double)
    <8 bytes BE double>   ← raw fader position (non-linear curve)
  \x00\x00\x00\x0c  (name_len = 12)
  AnchorValue\x00
    \x00\x04        (type = double)
    <8 bytes BE double>   ← actual dB value shown in Cubase
```

**Regex (with AnchorValue):**
```
Volume\x00\x00\x02\x00\x06\x00\x00\x00\x02
\x00\x00\x00\x06Value\x00\x00\x04(.{8})
\x00\x00\x00\x0cAnchorValue\x00\x00\x04(.{8})
```

**AnchorValue** is the **correct volume in dB** — use it directly.

**Value (raw fader):** 0.0 – ~32767.0 with unity at 25856.0. Cubase uses a
non-linear fader curve, so `20 * log10(value / 25856)` gives incorrect results.
Only use Value as a fallback if AnchorValue is missing.

**⚠ Note:** There are many `Volume` fields per track (main fader, send levels,
insert-slot panners). The first match within the track region is the channel
fader. Send volumes are inside the `SendFolder` region and are handled
separately.

### Pan

**Pan is NOT stored in a `Pan\x00` compound field** for individual tracks
(those only exist for output channels with value 16383.5 = center). Per-track
pan is stored inside the **Standard Panner** plugin's `audioComponent` blob.

**Channel strip structure (simplified):**
```
[Track strip]
  Volume → Value + AnchorValue    ← track fader
  Output → Value
  Panner (21 children)            ← track's main panner section
    Standard Panner               ← panner plugin
      audioComponent              ← contains pan for INSERT SLOTS (always center)
    Volume → Output → Panner      ← nested, repeats for each insert slot
      ...
    SummingMode                   ← marks the MAIN channel panner
    Panner (21 children)          ← the ACTUAL channel panner
      Standard Panner
        audioComponent            ← PAN VALUE IS HERE
```

**The main channel panner** is distinguished from insert-slot panners by appearing
after a `SummingMode` field, followed by a `Panner` compound with 21 children.

**audioComponent layout:**
```
audioComponent\x00
  \x00\x02\x00\x07   (type = compound, subtype = 0x07)
  <4 bytes BE uint32>  ← header (typically 20)
  <4 bytes LE float>   ← PAN VALUE (0.0=left, 0.5=center, 1.0=right)
```

**Regex:**
```
SummingMode\x00.{0,30}?
Panner\x00\x00\x02\x00\x06\x00\x00\x00\x15
.{200,600}?Standard Panner
.+?audioComponent\x00\x00\x02\x00\x07.{4}(.{4})
```

**Pan value:** 4-byte **little-endian float**
- **Hard left** = 0.0 → normalized -1.0
- **Center** = 0.5 → normalized 0.0
- **Hard right** = 1.0 → normalized +1.0

**Normalized:** `pan_normalized = (le_float - 0.5) * 2.0`

**⚠ Important:** Each channel strip contains **many** Standard Panner
`audioComponent` blobs (one per insert slot + sends). Only the one following
`SummingMode → Panner(21 children)` contains the actual track pan position.
The insert-slot panners always read 0.5 (center).

#### Legacy Pan compound (output channels only)

The `Pan\x00` compound field with a double `Value` only exists for output
channels (Stereo Out). It uses the range 0–32767 with center at 16383.5.

### Mute

**⚠ Not working for Cubase 12+.** The `Mute\x00\x00\x01` pattern matches
MIDI pitch mutes and plugin bypass states, not the track mute button. The
per-track mute state in Cubase 12 is stored in an unknown location — it is
NOT in the channel strip section and NOT in the legacy track event headers.

**Legacy pattern (Cubase 10–11):** `Mute\x00\x00\x01` + 8 bytes BE int64 (0=off, 1=on).

### Solo

**⚠ Not saved in .cpr files.** Solo is a live mixer state in Cubase and
resets when the project is reopened. No `Solo=1` values were found in
any tested project file, even with tracks actively soloed at save time.

---

## Audio References

Audio file names appear in both encodings:

- **UTF-8:** Direct ASCII pattern `([\w\-\. ]+\.wav)`
- **UTF-16-LE:** Alternating `byte\x00` pattern ending in `w\x00a\x00v\x00`
- **Other formats:** Same UTF-8 pattern with `.mp3`, `.flac`, `.aif`, `.aiff`,
  `.ogg`, `.m4a` extensions

### Per-Track Audio Assignment

Each track's region (from its strip position to the next strip) contains audio
references for that track. The Pool area (after `Pool\x00` marker) is excluded
to avoid double-counting global references.

---

## Plugins

### VST3 Plugin Detection

**Pattern:** `Plugin Name\x00` + 0–8 header bytes + ASCII plugin name (2–50 chars).

**Context check:** Must be preceded by `Slot\x00` or `Bay Program\x00` within
300 bytes to qualify as an insert plugin.

**Built-in plugins** (filtered out): Standard Panner, Stereo Combined Panner,
Input Filter, EQ, Mono Panner, Surround Panner, Sampler Track.

### Plugin Parameters (PresetChunkXMLTree)

Waves/SSL plugins store parameters in XML format:

```xml
<PresetChunkXMLTree>
  <PluginName>SSLChannel</PluginName>
  <Preset Name="My Preset">
    <PresetData Setup="SETUP_A">
      <Parameters Type="RealWorld">1.0 2.5 * 0.0 ...</Parameters>
    </PresetData>
  </Preset>
</PresetChunkXMLTree>
```

**RealWorld parameters:** Space-separated float values, `*` = unused/default.

**Supported plugins with parameter interpretation:**
- **SSLEQ:** 4-band EQ (LF, LMF, HMF, HF)
- **SSLChannel:** 4-band EQ + compressor
- **CLA-76 / CLA76:** Compressor (input, output, attack, release)
- **CLA-2A / CLA2A:** Compressor (threshold, output)
- **C1Comp:** Compressor (threshold, ratio, attack)
- **DeEsser:** Frequency + threshold
- **FabFilter Pro-Q 3:** Multi-band EQ via generic parameter detection

### Plugin Deduplication

- Entries within 20 KB with normalized-matching names are duplicates.
- The entry with more parameter data is kept.
- Name normalization: strip ` Mono`, ` Stereo`, ` Mono/Stereo`.
- Self-reference plugins (plugin name == track name) are removed.

### Plugin-to-Track Assignment

Plugins are assigned to the closest preceding track by binary position in the
sorted track list.

---

## Routing

### Bus UID Table

**Pattern:** `OwnInputBus\x00` entries containing:
- `Name\x00` + header + ASCII bus name
- `Bus UID\x00\x00\x01\x00\x00\x00\x00` + 4 bytes BE uint32 UID

Returns a `{uid: name}` mapping used by routing and send extraction.

### Output Routing

**Pattern:** `OutputBus` within a track's region, followed by
`Value\x00\x00\x01\x00\x00\x00\x00` + 4 bytes BE uint32 UID.

The UID is resolved to a bus name via the bus table.

### Send Effects

**Pattern:** `SendFolder\x00` within a track's region, containing up to 8 slots.

Each slot has:
- `Volume\x00` → `Value\x00\x00\x04` + 8 bytes BE double (send level)
- `Output\x00` → `Value\x00\x00\x01\x00\x00\x00\x00` + 4 bytes BE uint32 UID

**Send level dB:** `dB = 20 * log10(value / 25856.0)`

Strategy: Find each `Volume` position, extract the double, then find the next
`Output` after it for the target UID.

---

## Markers

**Pattern:** `MMarkerEvent` entries containing `MRangeMarkerEvent` children.

**Structure:**
```
MMarkerEvent\x00
  \x00\x00\xff\xff\xff\xff          (header)
  \x00\x00\x00\x12                  (child name length)
  MRangeMarkerEvent\x00             (child type)
  <header bytes>
  \x00\x00\x00<name_len>            (4 bytes)
  <marker_name>\x00\xef\xbb\xbf    (name + BOM)
  <4 bytes BE int32>                (color/type: 1 = range marker)
  <4 bytes BE uint32>               (start position in PPQ ticks)
  <4 bytes padding = 0>
  <4 bytes BE uint32>               (end position, for range markers)
```

**Name extraction:** Regex `\x00\x00\x00[\x02-\x40]([\x20-\x7e]+)\x00\xef\xbb\xbf`
finds the marker name between the length prefix and BOM.

**Position:** 4 bytes BE uint32 after BOM + 4 bytes color/type. Position is
in PPQ ticks (typically 480 PPQ per quarter note).

---

## MTempoTrackEvent Header Structure

The `MTempoTrackEvent` block at the beginning of the file contains the tempo
track configuration. Structure (offsets from `MTempoTrackEvent`):

```
+0    MTempoTrackEvent\x00        (17 bytes)
+17   \x00\x03                    (flags)
+19   \x00\x00\x00<size>          (4 bytes)
+23   \x00\x00\x00\x01            (version?)
+27   <8 bytes>                   (timing data)
+35   <zeros/padding>
+48   \x42\xa0...                 (fixed value = 8796093022208.0)
+58   BlTT\x00\x01 + 8 bytes     (tempo lower bound, int)
+72   BuTT\x00\x01 + 8 bytes     (tempo upper bound, int)
+86   DILT\x00\x01 + 8 bytes     (flags)
+100  iCVT\x00\x22               (tempo curve variant, compound)
...
+~200 MTrackVariation             (track variation collection)
+~230 kcoL (Lock field)           (lock flag + value)
+~245 <embedded tempo double>     (may contain first BPM if tempo track has events)
+~260 MSignatureTrackEvent        (time signature track follows)
```

**⚠ The embedded tempo double** (Strategy 2 for tempo extraction) only exists
when the project has a tempo track with explicit events. Projects using a
fixed tempo store the BPM in `MTempoEvent` > `BPM` elsewhere in the file.

---

## Data Model Summary

| Field | Status | Source Pattern |
|-------|--------|---------------|
| Cubase version | ✅ Parsed | `Version X.Y.Z` (modern) or `Cubase NN` (legacy) |
| Sample rate | ✅ Parsed | Binary `SampleRate` > `Float` double (skip XML!) |
| Tempo | ✅ Parsed | `MTempoEvent` > `BPM` double, fallback header scan |
| Time signature | ✅ Parsed | `TimeSignatureEvent` > `Numerator`/`Denominator` |
| Track names | ✅ Parsed | Channel strip pattern |
| Track types | ✅ Parsed | `IDString` entries |
| Track volume | ✅ Parsed | `Volume` compound > `AnchorValue` double (dB) |
| Track pan | ✅ Parsed | Standard Panner `audioComponent` LE float (after `SummingMode`) |
| Track mute | ⚠ Legacy only | `Mute` int field — Cubase 12+ stores mute elsewhere (unknown) |
| Track solo | ❌ Not saved | Solo is a live mixer state, not persisted in .cpr files |
| Track color | ⚠ Legacy only | Palette index in legacy event headers — Cubase 12+ uses unknown format |
| Plugins | ✅ Parsed | `Plugin Name\x00` + `PresetChunkXMLTree` |
| EQ bands | ✅ Parsed | Plugin parameter interpretation |
| Compressor | ✅ Parsed | Plugin parameter interpretation |
| Audio refs | ✅ Parsed | Regex on `.wav`/`.mp3` etc. (UTF-8 + UTF-16-LE) |
| Output routing | ✅ Parsed | `OutputBus` + bus UID table |
| Sends | ✅ Parsed | `SendFolder` + Volume/Output |
| Markers | ✅ Parsed | `MMarkerEvent` + position in PPQ ticks |

### Known Pitfalls

| Issue | Solution |
|-------|----------|
| `SampleRate` in XML vs binary | Skip occurrences with `>` or `<` nearby |
| `Tempo` fields in `GridDef` | These are grid overlay presets, not project tempo |
| `RehearsalTempo` field | Tap tempo rehearsal setting, not project tempo |
| Track color index 0 | Treat as "no color set" (most tracks default to 0) |
| Volume = -1.0 | Unused/bypass slot, not silence |
| Volume `Value` vs `AnchorValue` | `AnchorValue` is the real dB; `Value` uses a non-linear fader curve |
| Pan not in `Pan\x00` compound | Per-track pan is in Standard Panner `audioComponent`, not the named field |
| Multiple Standard Panners per track | Insert-slot panners are always center; main panner follows `SummingMode` |
| Audio tracks without audio refs | Don't filter out — audio ref detection is incomplete |
| Duplicate channel strips | Same name within 40 KB = duplicate |
| I/O section after 1 MB gap | Hardware I/O channels, filter out |

### Not Yet Parsed (Future)

| Field | Pattern | Complexity |
|-------|---------|-----------|
| Automation data | `MAutomationTrackEvent` + curve nodes | High |
| MIDI events | `MMidiTrackEvent` data | High |
| Folder hierarchy | `MFolderTrackEvent` nesting | Medium |
| Cycle/Locators | Left/Right Locator positions | Low |
| Record enable | `RecordEnable` flag | Low |
| Monitor enable | `Monitor` flag | Low |
| Plugin presets | `PString` / VST3 preset names | Medium |
| Bit depth | Possibly near `Record Format` or in project header | Low |
