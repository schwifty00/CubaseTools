"""CLI entry point for StudioTrack integration.

Usage: py -m cubasetools.cli_export "C:\\path\\to\\project.cpr"

Outputs JSON to stdout for consumption by StudioTrack's Node.js backend.
"""

import json
import sys
from pathlib import Path

from cubasetools.core.cpr_parser import parse_cpr
from cubasetools.export.studiotrack_format import to_studiotrack_format


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No .cpr path provided"}))
        sys.exit(1)

    cpr_path = Path(sys.argv[1])
    if not cpr_path.exists() or cpr_path.suffix.lower() != ".cpr":
        print(json.dumps({"error": f"File not found or not .cpr: {cpr_path}"}))
        sys.exit(1)

    try:
        project = parse_cpr(cpr_path)
        data = to_studiotrack_format(project)
        print(json.dumps(data, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
