"""Shared audio filename extraction from binary .cpr data.

Used by both the CPR parser (in-memory) and audio cleanup (from file).
"""

from __future__ import annotations

import re


def find_audio_references(data: bytes) -> set[str]:
    """Extract all audio filenames from binary Cubase project data.

    Searches for filenames in both UTF-8 and UTF-16-LE encodings.
    Supports: .wav, .mp3, .flac, .aif, .aiff, .ogg, .m4a
    Returns lowercased filenames for case-insensitive matching.
    """
    referenced: set[str] = set()

    # UTF-8 .wav references — include () for Cubase duplicate suffixes
    # First char must be alphanumeric to avoid matching stray parentheses
    for match in re.finditer(rb'(\w[\w\-\. ()]*\.wav)', data, re.IGNORECASE):
        name = match.group(1).decode("utf-8", errors="ignore").strip()
        if name and len(name) > 4:
            referenced.add(name.lower())

    # UTF-16-LE .wav references
    for match in re.finditer(
        rb'(\w\x00(?:[\w\-\. ()]\x00)*w\x00a\x00v\x00)', data, re.IGNORECASE
    ):
        try:
            name = match.group(1).decode("utf-16-le", errors="ignore").strip()
            if name and len(name) > 4:
                referenced.add(name.lower())
        except (UnicodeDecodeError, ValueError):
            continue

    # Other audio formats (UTF-8)
    for ext in [b"mp3", b"flac", b"aif", b"aiff", b"ogg", b"m4a"]:
        pattern = rb'(\w[\w\-\. ()]*\.' + ext + rb')'
        for match in re.finditer(pattern, data, re.IGNORECASE):
            name = match.group(1).decode("utf-8", errors="ignore").strip()
            if name and len(name) > 4:
                referenced.add(name.lower())

    return referenced
