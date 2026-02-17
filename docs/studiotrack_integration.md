# StudioTrack Integration

## Overview

CubaseTools exports project structure data that complements StudioTrack's audio analysis.

| StudioTrack | CubaseTools |
|-------------|------------|
| Analyzes exported WAV/MP3 | Analyzes .cpr project files |
| LUFS, True Peak, Spectogram | Plugin chains, EQ, compression |
| "How does the mix sound?" | "How was the mix built?" |

## JSON Schema (v1.0)

```json
{
  "schema_version": "1.0",
  "source": "CubaseTools",
  "project": {
    "name": "string",
    "cubase_version": "string",
    "sample_rate": 48000,
    "bit_depth": 24,
    "tempo_bpm": 120.0,
    "time_signature": "4/4"
  },
  "tracks": [
    {
      "name": "Vocal",
      "type": "audio",
      "signal_chain": [
        {
          "plugin_name": "SSL E-Channel",
          "vendor": "SSL",
          "bypassed": false,
          "slot": 0,
          "eq": {
            "bands": [
              {
                "enabled": true,
                "type": "peak",
                "freq_hz": 3000.0,
                "gain_db": 2.5,
                "q": 1.2
              }
            ]
          },
          "compressor": {
            "threshold_db": -18.0,
            "ratio": 4.0,
            "attack_ms": 10.0,
            "release_ms": 100.0,
            "knee_db": 0.0,
            "makeup_db": 3.0
          }
        }
      ]
    }
  ],
  "summary": {
    "total_tracks": 24,
    "total_plugins": 48,
    "audio_tracks": 16,
    "referenced_files": 32
  }
}
```

## Usage in StudioTrack

StudioTrack can import this JSON to display alongside its audio analysis, showing both the technical mix decisions and their audible results.
