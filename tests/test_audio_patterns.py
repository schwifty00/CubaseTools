"""Tests for the shared audio filename extraction logic."""

from cubasetools.core.audio_patterns import find_audio_references


def test_utf8_wav():
    """Should find UTF-8 encoded .wav filenames."""
    data = b"\x00" * 20 + b"vocal_take_01.wav" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "vocal_take_01.wav" in refs


def test_utf8_wav_with_parentheses():
    """Should handle Cubase duplicate suffixes like (D)."""
    data = b"\x00" * 20 + b"Audio 02 (D)_18.wav" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "audio 02 (d)_18.wav" in refs


def test_utf16le_wav():
    """Should find UTF-16-LE encoded .wav filenames."""
    name = "MyAudio.wav".encode("utf-16-le")
    data = b"\x00" * 20 + name + b"\x00" * 20
    refs = find_audio_references(data)
    assert "myaudio.wav" in refs


def test_mp3_format():
    """Should find .mp3 filenames."""
    data = b"\x00" * 20 + b"background_music.mp3" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "background_music.mp3" in refs


def test_flac_format():
    """Should find .flac filenames."""
    data = b"\x00" * 20 + b"master_export.flac" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "master_export.flac" in refs


def test_aif_format():
    """Should find .aif filenames."""
    data = b"\x00" * 20 + b"sample_loop.aif" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "sample_loop.aif" in refs


def test_ogg_format():
    """Should find .ogg filenames."""
    data = b"\x00" * 20 + b"effect_sound.ogg" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "effect_sound.ogg" in refs


def test_case_insensitive():
    """Should normalize filenames to lowercase."""
    data = b"\x00" * 20 + b"VOCAL_TAKE.WAV" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "vocal_take.wav" in refs


def test_short_names_rejected():
    """Names with 4 or fewer chars should be rejected (too short to be real)."""
    # ".wav" alone is 4 chars -> rejected; "a.wav" is 5 chars -> accepted
    data = b"\x00" * 20 + b".wav" + b"\x00" * 20
    refs = find_audio_references(data)
    assert len(refs) == 0


def test_multiple_files():
    """Should find multiple different audio files."""
    data = (
        b"\x00" * 20
        + b"vocals.wav\x00"
        + b"drums.wav\x00"
        + b"bass_track.mp3\x00"
        + b"\x00" * 20
    )
    refs = find_audio_references(data)
    assert "vocals.wav" in refs
    assert "drums.wav" in refs
    assert "bass_track.mp3" in refs


def test_empty_data():
    """Should return empty set for empty data."""
    refs = find_audio_references(b"")
    assert refs == set()


def test_no_audio_files():
    """Should return empty set when no audio files present."""
    data = b"\x00" * 100 + b"some random binary data" + b"\x00" * 100
    refs = find_audio_references(data)
    assert refs == set()


def test_hyphens_and_spaces():
    """Should handle filenames with hyphens and spaces."""
    data = b"\x00" * 20 + b"vocal - lead take 3.wav" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "vocal - lead take 3.wav" in refs


def test_dots_in_filename():
    """Should handle dots before the extension."""
    data = b"\x00" * 20 + b"v1.2.final.wav" + b"\x00" * 20
    refs = find_audio_references(data)
    assert "v1.2.final.wav" in refs
