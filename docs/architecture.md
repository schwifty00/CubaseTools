# Architecture

## Overview

CubaseTools follows a layered architecture separating data parsing, analysis logic, and GUI presentation.

```
┌─────────────────────────────────┐
│           GUI Layer             │
│  (CustomTkinter, Dark Theme)    │
│  app.py → tabs → widgets        │
├─────────────────────────────────┤
│       Analysis / Logic          │
│  analyzer/  dashboard/  export/ │
│  cleanup/                       │
├─────────────────────────────────┤
│          Core Layer             │
│  cpr_parser.py  models.py       │
│  plugin_registry.py             │
└─────────────────────────────────┘
```

## Data Flow

1. **CprParser** reads binary .cpr → produces **CubaseProject** dataclass
2. **Analyzer modules** consume CubaseProject → extract EQ, compressor, stats
3. **Dashboard** scans directory → parses all .cpr → aggregates stats
4. **GUI tabs** display results using widgets (tables, charts, trees)
5. **Export** serializes CubaseProject → JSON (generic or StudioTrack format)

## Key Design Decisions

- **No GUI in logic layers**: All cleanup/analysis modules are pure functions returning data
- **Dataclass-based models**: CubaseProject, Track, PluginInstance are plain dataclasses
- **Plugin registry pattern**: Known plugins (SSL, CLA-76, Pro-Q) get dedicated parameter interpreters; unknown plugins get generic interpretation
- **Threading**: Long operations (scan, parse) run in background threads with `parent.after()` UI updates
