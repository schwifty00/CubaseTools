# StudioTrack Integration

## Overview

CubaseTools exports project structure data that complements StudioTrack's audio analysis.

| StudioTrack | CubaseTools |
|-------------|------------|
| Analyzes exported WAV/MP3 | Analyzes .cpr project files |
| LUFS, True Peak, Spectogram | Plugin chains, EQ, compression |
| Stem separation (Demucs) | Signal routing, send effects |
| "How does the mix sound?" | "How was the mix built?" |

## Setup on a new machine

### 1. Clone CubaseTools

```bash
cd C:\Github
git clone https://github.com/schwifty00/CubaseTools.git
```

The path `C:\Github\CubaseTools` is hardcoded in StudioTrack's `route.ts` as `CUBASETOOLS_PATH`. If you use a different location, update that constant.

### 2. Python requirements

CubaseTools needs Python 3.10+ (no extra pip packages for parsing).

```bash
# Verify it works:
cd C:\Github\CubaseTools
py -m cubasetools.cli_export "path\to\project.cpr"
```

This should output JSON to stdout.

### 3. StudioTrack integration

StudioTrack automatically detects CubaseTools:

1. When analyzing a WAV/MP3, it searches for a `.cpr` file nearby (same dir, parent, grandparent)
2. It calls `py -m cubasetools.cli_export <cpr_path>` and parses the JSON output
3. The JSON data (routing, plugins, sends) is included in the AI analysis prompt

**No manual config needed** — if CubaseTools is at the expected path and Python works, it's active.

## How it works (architecture)

```
StudioTrack (Next.js)                    CubaseTools (Python)
========================                 ========================
route.ts                                 cli_export.py
  findCprFile(audioPath)                   parse_cpr(cpr_path)
  → parseCprFile(cprPath)  ──spawns──→     to_studiotrack_format()
  ← JSON stdout                            → JSON to stdout
  buildCprSection(cprData)
  → AI prompt with routing/sends/plugins
```

The data flow:
1. **StudioTrack** receives a WAV path from the user
2. **findCprFile()** searches for a `.cpr` file near the WAV (Mixdown folder → parent → grandparent)
3. **parseCprFile()** spawns `py -m cubasetools.cli_export <path>` with `cwd=CUBASETOOLS_PATH`
4. **CubaseTools** parses the binary `.cpr` file and outputs JSON
5. **buildCprSection()** formats the JSON into readable text for the AI prompt:
   - Signal routing tree (which track routes where)
   - Send effects with levels
   - FX return routing (where FX channels send back to)
   - Full routing chains (Track → Subgroup → Group → Stereo Out)
   - Plugin chains with EQ/compressor details
6. **AI prompt** instructs the model to analyze routing structure, send usage, parallel processing, and plugin chains in context of the routing hierarchy

## JSON Schema (v1.1)

```json
{
  "schema_version": "1.0",
  "source": "CubaseTools",
  "project": {
    "name": "25-7",
    "cubase_version": "Cubase 15",
    "sample_rate": 44100,
    "bit_depth": 24,
    "tempo_bpm": 120.0,
    "time_signature": "4/4"
  },
  "tracks": [
    {
      "name": "Kick Tentsuyu 3",
      "type": "instrument",
      "output_bus": "drums",
      "sends": [
        { "target": "Drums NY", "level_db": 0.0, "enabled": true }
      ],
      "audio_files": [],
      "signal_chain": [
        {
          "plugin_name": "SSLEQ Stereo",
          "vendor": "",
          "bypassed": false,
          "slot": 0,
          "eq": {
            "bands": [
              { "enabled": true, "type": "peak", "freq_hz": 41.0, "gain_db": 1.97, "q": 1.0 }
            ]
          }
        },
        {
          "plugin_name": "FabFilter Pro-C 2",
          "vendor": "",
          "bypassed": false,
          "slot": 1
        }
      ]
    },
    {
      "name": "drums",
      "type": "group",
      "output_bus": "Stereo Out",
      "sends": [],
      "audio_files": [],
      "signal_chain": []
    }
  ],
  "summary": {
    "total_tracks": 61,
    "total_plugins": 90,
    "audio_tracks": 12,
    "referenced_files": 580
  }
}
```

### New fields (v1.1)

| Field | Type | Description |
|-------|------|-------------|
| `output_bus` | string | Name of the bus this track routes to (e.g. "drums", "Stereo Out") |
| `sends` | array | Send effect slots with target FX channel name and level in dB |
| `sends[].target` | string | Name of the FX channel receiving the send |
| `sends[].level_db` | number | Send level in dB (0.0 = unity gain, negative = attenuated) |
| `audio_files` | array | Audio file names found in this track's region of the .cpr binary |

These fields enable StudioTrack's AI to analyze:
- **Routing hierarchy** — bus structure, group organization
- **Send/return patterns** — which FX are used as sends vs. inserts
- **Parallel compression** — detection of NY-style buses
- **Cumulative compression** — how many compression stages exist in a routing chain
