# CubaseTools

Reads Cubase project files (`.cpr`) and extracts mix data: plugin chains, EQ settings, compressor parameters, track structure, routing, and audio references.

Works with **Cubase 10 through 15** (Elements, Artist, Pro).

## Features

- **Mix Analyzer** — Plugin chains per track, EQ curves, compressor settings, routing and sends
- **Dashboard** — Scan all projects, cross-project plugin statistics
- **Audio Cleanup** — Find and remove unused audio files
- **Backup Cleanup** — Remove `.bak` and `.peak` files
- **JSON Export** — Export mix data as JSON (CLI or GUI)

## Installation

### Prerequisites

- **Python 3.12+** — [Download](https://www.python.org/downloads/)
  - During installation: check **"Add Python to PATH"**
- **OS:** Windows 10/11 (primary), Linux and macOS also work (GUI requires tkinter)

### Setup

```bash
git clone https://github.com/schwifty00/CubaseTools.git
cd CubaseTools
python -m venv venv
```

Activate the virtual environment:

```bash
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Windows (CMD)
venv\Scripts\activate.bat

# Linux / macOS
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### tkinter on Linux

If the GUI fails to start (`No module named 'tkinter'`):

```bash
# Ubuntu / Debian
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter
```

## Usage

### Launch the GUI

```bash
python main.py
```

On Windows you can also double-click `CubaseTools.bat`.

### CLI (JSON Export)

Print a single project as JSON to stdout:

```bash
python -m cubasetools.cli_export "C:\Projects\MySong\MySong.cpr"
```

Save to file:

```bash
python -m cubasetools.cli_export "MySong.cpr" > mix_data.json
```

### Example JSON Output

```json
{
  "schema_version": "1.0",
  "source": "CubaseTools",
  "project": {
    "name": "MySong",
    "cubase_version": "Cubase 13",
    "sample_rate": 48000,
    "bit_depth": 24,
    "tempo_bpm": 120.0
  },
  "tracks": [
    {
      "name": "Vocals",
      "type": "audio",
      "output_bus": "Stereo Out",
      "signal_chain": [
        {
          "plugin_name": "SSL E-Channel",
          "vendor": "Solid State Logic",
          "bypassed": false,
          "slot": 0,
          "eq": {
            "bands": [
              {
                "enabled": true,
                "type": "high_pass",
                "freq_hz": 80.0,
                "gain_db": 0.0,
                "q": 0.707
              },
              {
                "enabled": true,
                "type": "bell",
                "freq_hz": 3200.0,
                "gain_db": 2.5,
                "q": 1.2
              }
            ]
          },
          "compressor": {
            "threshold_db": -18.0,
            "ratio": 4.0,
            "attack_ms": 3.0,
            "release_ms": 150.0
          }
        }
      ]
    }
  ],
  "summary": {
    "total_tracks": 42,
    "total_plugins": 87,
    "audio_tracks": 28,
    "referenced_files": 156
  }
}
```

## GUI Tabs

### Dashboard

Choose a scan directory (default: `C:\DeepArt`), click **Scan**. Shows:

- Overview: number of projects, tracks, plugins, total file size
- Project table with per-project stats
- Top plugins across all projects

### Mix Analyzer

Load a `.cpr` file, click **Analyze**. Shows:

- **Plugin Chain** — Tree view of all tracks with their insert plugins
- **EQ Curves** — Overlaid frequency response curves
- **Compressor** — Table with threshold, ratio, attack, release per track
- **Plugin Stats** — Usage counts with track assignments
- **JSON Export** — Save mix data to file

### Audio Cleanup

Choose a project folder, click **Analyze**. Finds audio files not referenced in the `.cpr`.

- **Move** — Moves files to an `_unused/` subfolder (reversible)
- **Delete** — Permanently deletes files (with double confirmation)

### Backup Cleanup

Scans for `.bak` and `.peak` files that take up disk space.

## Supported Plugins

The parser recognizes plugin parameters from common audio plugins and extracts EQ/compressor settings for:

| Vendor            | Plugins                                   |
| ----------------- | ----------------------------------------- |
| Solid State Logic | SSL Native Channel Strip 2, SSL E-Channel |
| Waves             | CLA-76, CLA-2A                            |
| FabFilter         | Pro-Q 3 (band types)                      |
| Steinberg         | Stock plugins                             |

All other VST2/VST3 plugins are detected with name, vendor, and bypass status — without specific parameter interpretation.

## Project Structure

```
cubasetools/
  core/         CPR parser, data models, plugin registry
  cleanup/      Audio & backup cleanup logic
  analyzer/     Mix analysis (EQ, compressor, plugin stats)
  dashboard/    Project scanner & cross-project stats
  export/       JSON export (generic + StudioTrack format)
  gui/          CustomTkinter GUI (dark theme)
  utils/        File utilities, config
docs/           Technical documentation (CPR format, architecture)
tests/          Unit tests for the parser
```

## Known Limitations

- **Proprietary format** — `.cpr` is undocumented. The parser uses reverse engineering and works well with Cubase 10–15, but not every project feature is covered.
- **No MIDI data** — MIDI events are not extracted, only track structure and plugins.
- **Plugin parameters** — Detailed parameter interpretation only for the plugins listed above. All others are detected with basic info.
- **Large projects** — Projects with 200+ tracks may take a few seconds to parse.

## StudioTrack Integration

CubaseTools works as a standalone tool but is also integrated into [StudioTrack](https://github.com/schwifty00/studio-track-commercial). StudioTrack calls the CLI export as a subprocess to include Cubase project data in its AI-powered mix analysis.

## License

MIT License — see [LICENSE](LICENSE).
