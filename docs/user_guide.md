# User Guide

## Starting CubaseTools

Double-click `CubaseTools.bat` or run `python main.py`.

## Tabs

### Dashboard
- Set scan directory (default: `C:\DeepArt`)
- Click **Scannen** to find and parse all .cpr files
- View overview cards: total projects, tracks, plugins, data size
- Project table shows per-project stats
- Top Plugins panel shows most-used plugins across all projects

### Mix Analyzer
- Select a .cpr file and click **Analysieren**
- **Plugin-Chain**: Tree view of all tracks with their plugin chains
- **EQ-Kurven**: Overlaid EQ frequency response curves
- **Kompressor**: Table of compressor settings per track
- **Plugin-Statistik**: Plugin usage counts with track assignments
- **JSON Export**: Save mix data as JSON file

### Audio Cleanup
- Select a project folder or parent directory
- Click **Analysieren** to find unused audio files
- **Verschieben**: Moves files to `_unused/` subfolder (reversible)
- **Loeschen**: Permanently deletes files (with double confirmation)

### Backup Cleanup
- Scan for `.bak` and `.peak` files
- Review and delete to free disk space
