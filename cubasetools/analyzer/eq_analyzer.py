"""EQ analysis - extract EQ curves and band data from plugins."""

from __future__ import annotations

import math

from cubasetools.core.models import CubaseProject, EQBand, EQBandType, Track


def get_all_eq_data(
    project: CubaseProject,
) -> list[tuple[Track, str, list[EQBand]]]:
    """Get EQ band data for all tracks that have EQ plugins.

    Returns list of (track, plugin_name, bands).
    """
    results = []
    for track in project.tracks:
        for plugin in track.plugins:
            if plugin.eq_bands:
                results.append((track, plugin.name, plugin.eq_bands))
    return results


def compute_eq_curve(
    bands: list[EQBand],
    sample_rate: int = 48000,
    num_points: int = 200,
) -> tuple[list[float], list[float]]:
    """Compute an approximate EQ frequency response curve.

    Returns (frequencies_hz, gains_db) for plotting.
    Each band's contribution is summed in dB (simplified model).
    """
    # Logarithmic frequency range: 20 Hz to 20 kHz
    freqs = [
        20.0 * (20000.0 / 20.0) ** (i / (num_points - 1))
        for i in range(num_points)
    ]
    gains = [0.0] * num_points

    for band in bands:
        if not band.enabled:
            continue
        for i, freq in enumerate(freqs):
            gains[i] += _band_response(band, freq)

    return freqs, gains


def _band_response(band: EQBand, freq: float) -> float:
    """Approximate a single EQ band's gain at a given frequency."""
    if band.gain == 0.0 and band.band_type == EQBandType.PEAK:
        return 0.0

    ratio = freq / band.frequency if band.frequency > 0 else 1.0
    log_ratio = math.log2(ratio) if ratio > 0 else 0.0

    if band.band_type == EQBandType.PEAK:
        # Bell curve: gain * exp(-width * (log_ratio)^2)
        width = max(band.q, 0.1) * 2.0
        return band.gain * math.exp(-width * log_ratio * log_ratio)

    elif band.band_type == EQBandType.LOW_SHELF:
        # Low shelf: transition around center frequency
        transition = -log_ratio * max(band.q, 0.5) * 3.0
        return band.gain / (1.0 + math.exp(transition))

    elif band.band_type == EQBandType.HIGH_SHELF:
        transition = log_ratio * max(band.q, 0.5) * 3.0
        return band.gain / (1.0 + math.exp(transition))

    elif band.band_type == EQBandType.LOW_CUT:
        # High-pass filter approximation
        if ratio < 1.0:
            return -48.0 * (1.0 - ratio)  # Steep rolloff
        return 0.0

    elif band.band_type == EQBandType.HIGH_CUT:
        if ratio > 1.0:
            return -48.0 * (1.0 - 1.0 / ratio)
        return 0.0

    elif band.band_type == EQBandType.NOTCH:
        width = max(band.q, 1.0) * 4.0
        return -24.0 * math.exp(-width * log_ratio * log_ratio)

    return 0.0
