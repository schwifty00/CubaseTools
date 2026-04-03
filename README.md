# CubaseTools

Liest Cubase-Projektdateien (`.cpr`) und extrahiert Mix-Daten: Plugin-Chains, EQ-Einstellungen, Kompressor-Parameter, Track-Struktur, Routing und Audio-Referenzen.

Funktioniert mit **Cubase 10 bis 15** (Elements, Artist, Pro).

## Features

- **Mix Analyzer** — Plugin-Chains pro Track, EQ-Kurven, Kompressor-Settings, Routing und Sends
- **Dashboard** — Alle Projekte scannen, projektuebergreifende Plugin-Statistiken
- **Audio Cleanup** — Unbenutzte Audio-Dateien finden und aufraumen
- **Backup Cleanup** — `.bak` und `.peak` Dateien entfernen
- **JSON Export** — Mix-Daten als JSON exportieren (CLI oder GUI)

## Installation

### Voraussetzungen

- **Python 3.12+** — [Download](https://www.python.org/downloads/)
  - Bei der Installation: **"Add Python to PATH"** aktivieren
- **Betriebssystem:** Windows 10/11 (primaer), Linux und macOS funktionieren ebenfalls (GUI benoetigt tkinter)

### Setup

```bash
git clone https://github.com/schwifty00/CubaseTools.git
cd CubaseTools
python -m venv venv
```

Virtuelle Umgebung aktivieren:

```bash
# Windows (PowerShell)
.\venv\Scripts\Activate.ps1

# Windows (CMD)
venv\Scripts\activate.bat

# Linux / macOS
source venv/bin/activate
```

Dependencies installieren:

```bash
pip install -r requirements.txt
```

### tkinter auf Linux

Falls die GUI nicht startet (`No module named 'tkinter'`):

```bash
# Ubuntu / Debian
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter
```

## Nutzung

### GUI starten

```bash
python main.py
```

Auf Windows alternativ: Doppelklick auf `CubaseTools.bat`.

### CLI (JSON Export)

Einzelnes Projekt als JSON auf stdout ausgeben:

```bash
python -m cubasetools.cli_export "C:\Projekte\MeinSong\MeinSong.cpr"
```

In Datei speichern:

```bash
python -m cubasetools.cli_export "MeinSong.cpr" > mix_data.json
```

### Beispiel JSON-Output

```json
{
  "schema_version": "1.0",
  "source": "CubaseTools",
  "project": {
    "name": "MeinSong",
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

## GUI-Tabs im Detail

### Dashboard

Scan-Verzeichnis waehlen (Standard: `C:\DeepArt`), **Scannen** klicken. Zeigt:

- Uebersicht: Anzahl Projekte, Tracks, Plugins, Dateigroesse
- Projekt-Tabelle mit Einzelstatistiken
- Top-Plugins ueber alle Projekte hinweg

### Mix Analyzer

`.cpr`-Datei laden, **Analysieren** klicken. Zeigt:

- **Plugin-Chain** — Baumansicht aller Tracks mit Insert-Plugins
- **EQ-Kurven** — Ueberlagerte Frequenzgang-Darstellung
- **Kompressor** — Tabelle mit Threshold, Ratio, Attack, Release pro Track
- **Plugin-Statistik** — Haeufigkeit + Track-Zuordnung
- **JSON Export** — Mix-Daten als Datei speichern

### Audio Cleanup

Projektordner waehlen, **Analysieren** klicken. Findet Audio-Dateien die im `.cpr` nicht referenziert werden.

- **Verschieben** — Verschiebt in `_unused/` Unterordner (umkehrbar)
- **Loeschen** — Permanentes Loeschen (mit doppelter Bestaetigung)

### Backup Cleanup

Scannt nach `.bak` und `.peak` Dateien die Speicherplatz belegen.

## Unterstuetzte Plugins

Der Parser erkennt Plugin-Parameter von gaengigen Audio-Plugins und extrahiert EQ/Kompressor-Einstellungen fuer:

| Hersteller        | Plugins                                   |
| ----------------- | ----------------------------------------- |
| Solid State Logic | SSL Native Channel Strip 2, SSL E-Channel |
| Waves             | CLA-76, CLA-2A                            |
| FabFilter         | Pro-Q 3 (Band-Typen)                      |
| Steinberg         | Stock-Plugins                             |

Alle anderen VST2/VST3 Plugins werden mit Name, Vendor und Bypass-Status erkannt — ohne spezifische Parameter-Interpretation.

## Projektstruktur

```
cubasetools/
  core/         CPR-Parser, Datenmodelle, Plugin-Registry
  cleanup/      Audio- & Backup-Cleanup-Logik
  analyzer/     Mix-Analyse (EQ, Kompressor, Plugin-Statistiken)
  dashboard/    Projekt-Scanner & projektuebergreifende Stats
  export/       JSON-Export (generisch + StudioTrack-Format)
  gui/          CustomTkinter GUI (Dark Theme)
  utils/        Datei-Utilities, Konfiguration
docs/           Technische Dokumentation (CPR-Format, Architektur)
tests/          Unit-Tests fuer den Parser
```

## Bekannte Einschraenkungen

- **Proprietaeres Format** — `.cpr` ist undokumentiert. Der Parser nutzt Reverse-Engineering und funktioniert gut mit Cubase 10–15, aber nicht jedes Projekt-Feature wird abgedeckt.
- **Keine MIDI-Daten** — MIDI-Events werden nicht extrahiert, nur Track-Struktur und Plugins.
- **Plugin-Parameter** — Detaillierte Parameter-Interpretation nur fuer die oben gelisteten Plugins. Alle anderen werden mit Basis-Infos erkannt.
- **Grosse Projekte** — Bei Projekten mit 200+ Tracks kann das Parsen einige Sekunden dauern.

## StudioTrack Integration

CubaseTools kann als Standalone-Tool genutzt werden, ist aber auch in [StudioTrack](https://github.com/schwifty00/studio-track-commercial) integriert. StudioTrack ruft den CLI-Export als Subprocess auf um Cubase-Projektdaten in die KI-gestuetzte Mix-Analyse einzubeziehen.

## Lizenz

MIT License — siehe [LICENSE](LICENSE).
