# CubaseTools

Cubase Project Analyzer & Cleanup Suite. Parses binary `.cpr` project files to extract mix data: plugin chains, EQ settings, compressor parameters, track structure, and audio references.

## Features

- **Mix Analyzer** - Plugin chains per track, EQ curves, compressor settings
- **Dashboard** - Scan all projects, cross-project plugin statistics
- **Audio Cleanup** - Find and remove unused audio files
- **Backup Cleanup** - Remove .bak and .peak files
- **JSON Export** - Export mix data for StudioTrack integration

## Quick Start

```
pip install -r requirements.txt
python main.py
```

Or double-click `CubaseTools.bat`.

## Default Scan Path

`C:\DeepArt` - configurable in the GUI.

## Requirements

- Python 3.12+
- customtkinter
- matplotlib

## Project Structure

```
cubasetools/
  core/         CPR parser, models, plugin registry
  cleanup/      Audio & backup cleanup logic
  analyzer/     Mix analysis (EQ, compressor, plugin stats)
  dashboard/    Project scanning & cross-project stats
  export/       JSON export (generic + StudioTrack format)
  gui/          CustomTkinter GUI with dark theme
  utils/        File utilities, config
```

## StudioTrack Integration

CubaseTools exports project structure data as JSON. StudioTrack analyzes the exported audio. Together they provide the complete picture: how the mix was built (CubaseTools) and how it sounds (StudioTrack).
