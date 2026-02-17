"""Tests for the audio cleanup module."""

import tempfile
from pathlib import Path

from cubasetools.cleanup.audio_cleanup import (
    extract_referenced_audio,
    find_audio_folder,
    find_cpr_file,
    is_single_project,
)
from cubasetools.cleanup.backup_cleanup import (
    categorize_backup_files,
    find_backup_files,
)


def test_extract_referenced_audio_utf8():
    """Should find UTF-8 .wav references."""
    tmp = tempfile.NamedTemporaryFile(suffix=".cpr", delete=False)
    tmp.write(b"\x00" * 10 + b"test_audio.wav" + b"\x00" * 10)
    tmp.close()

    refs = extract_referenced_audio(Path(tmp.name))
    assert "test_audio.wav" in refs
    Path(tmp.name).unlink()


def test_find_cpr_file():
    """Should find the most recent .cpr file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        (p / "old.cpr").write_bytes(b"\x00" * 10)
        (p / "new.cpr").write_bytes(b"\x00" * 10)

        result = find_cpr_file(p)
        assert result is not None
        assert result.suffix == ".cpr"


def test_is_single_project():
    """Should detect a directory as a project if it contains .cpr files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        assert not is_single_project(p)

        (p / "test.cpr").write_bytes(b"\x00" * 10)
        assert is_single_project(p)


def test_find_audio_folder():
    """Should find standard audio folder names."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        audio_dir = p / "Audio"
        audio_dir.mkdir()
        (audio_dir / "test.wav").write_bytes(b"\x00" * 10)

        result = find_audio_folder(p)
        assert result is not None
        assert result.name == "Audio"


def test_find_backup_files():
    """Should find .bak and .peak files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        (p / "test.bak").write_bytes(b"\x00" * 10)
        (p / "test.peak").write_bytes(b"\x00" * 10)
        (p / "test.wav").write_bytes(b"\x00" * 10)

        files = find_backup_files(p)
        assert len(files) == 2
        exts = {f.suffix for f in files}
        assert ".bak" in exts
        assert ".peak" in exts


def test_categorize_backup_files():
    """Should group files by extension."""
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        (p / "a.bak").write_bytes(b"\x00")
        (p / "b.bak").write_bytes(b"\x00")
        (p / "c.peak").write_bytes(b"\x00")

        files = find_backup_files(p)
        cats = categorize_backup_files(files)
        assert len(cats.get(".bak", [])) == 2
        assert len(cats.get(".peak", [])) == 1
