"""CubaseTools - Cubase Project Analyzer & Cleanup Suite.

Double-click CubaseTools.bat or run: python main.py
"""

import sys
from pathlib import Path

# Ensure package is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from cubasetools.gui.app import CubaseToolsApp


def main():
    app = CubaseToolsApp()
    app.run()


if __name__ == "__main__":
    main()
