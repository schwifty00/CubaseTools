"""RealWorld parameter parsing for Waves/SSL plugins.

Waves plugins store their parameters as space-separated float arrays
in PresetChunkXMLTree blocks under <Parameters Type="RealWorld">.
This module parses those arrays and interprets them for known plugins.
"""

from __future__ import annotations

from cubasetools.core.models import (
    CompressorSettings,
    EQBand,
    EQBandType,
    PluginInstance,
)


def parse_realworld_params(raw: str) -> list[float | None]:
    """Parse a RealWorld parameter string into a list of values.

    Values are space-separated floats; '*' means unused/default (None).
    """
    values: list[float | None] = []
    for token in raw.split():
        if token == "*":
            values.append(None)
        else:
            try:
                values.append(float(token))
            except ValueError:
                values.append(None)
    return values


def _rw(values: list[float | None], idx: int, default: float = 0.0) -> float:
    """Safely get a RealWorld parameter value."""
    if idx < len(values) and values[idx] is not None:
        return values[idx]
    return default


def interpret_realworld(
    plugin: PluginInstance,
    plugin_name: str,
    values: list[float | None],
    preset_name: str = "",
) -> None:
    """Interpret RealWorld parameter arrays for known plugins."""
    if plugin_name == "SSLEQ":
        bands = [
            EQBand(
                enabled=_rw(values, 0) > 0.5,
                band_type=EQBandType.PEAK if _rw(values, 1) > 0.5 else EQBandType.LOW_SHELF,
                frequency=_rw(values, 2, 60.0),
                gain=_rw(values, 4),
                q=1.0,
            ),
            EQBand(
                enabled=True,
                band_type=EQBandType.PEAK,
                frequency=_rw(values, 5, 200.0),
                gain=_rw(values, 8),
                q=_rw(values, 9, 0.5),
            ),
            EQBand(
                enabled=True,
                band_type=EQBandType.PEAK,
                frequency=_rw(values, 14, 3.5) * 1000,
                gain=_rw(values, 13),
                q=_rw(values, 10, 2.5),
            ),
            EQBand(
                enabled=_rw(values, 16) > 0.5,
                band_type=EQBandType.HIGH_SHELF,
                frequency=_rw(values, 18, 8.0) * 1000,
                gain=_rw(values, 17),
                q=1.0,
            ),
        ]
        plugin.eq_bands = [b for b in bands if b.gain != 0.0 or b.enabled]
        plugin.parameters["Output Trim"] = _rw(values, 19)

    elif plugin_name == "SSLChannel":
        if len(values) > 24:
            bands = [
                EQBand(
                    enabled=True,
                    band_type=EQBandType.LOW_SHELF,
                    frequency=_rw(values, 15, 60.0),
                    gain=_rw(values, 16),
                    q=1.0,
                ),
                EQBand(
                    enabled=True,
                    band_type=EQBandType.PEAK,
                    frequency=_rw(values, 18, 2.5) * 1000,
                    gain=_rw(values, 19),
                    q=_rw(values, 17, 0.5),
                ),
                EQBand(
                    enabled=True,
                    band_type=EQBandType.PEAK,
                    frequency=_rw(values, 20, 3.5) * 1000,
                    gain=_rw(values, 22),
                    q=_rw(values, 21, 1.5),
                ),
                EQBand(
                    enabled=True,
                    band_type=EQBandType.HIGH_SHELF,
                    frequency=_rw(values, 24, 8.0) * 1000,
                    gain=_rw(values, 23),
                    q=1.0,
                ),
            ]
            plugin.eq_bands = [b for b in bands if b.gain != 0.0]

        comp_thresh = _rw(values, 0)
        if comp_thresh < 0:
            plugin.compressor = CompressorSettings(
                plugin_name=plugin_name,
                threshold=comp_thresh,
                release=_rw(values, 3),
            )

    elif plugin_name in ("CLA-76", "CLA76"):
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            input_gain=_rw(values, 0),
            output_gain=_rw(values, 1),
            attack=_rw(values, 2),
            release=_rw(values, 3),
            ratio=4.0,
        )
        if preset_name:
            plugin.parameters["Preset"] = 0
            plugin.compressor.raw_parameters["preset_name"] = preset_name  # type: ignore[assignment]

    elif plugin_name in ("CLA-2A", "CLA2A"):
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            threshold=_rw(values, 0),
            output_gain=_rw(values, 1),
        )

    elif plugin_name == "C1Comp":
        plugin.compressor = CompressorSettings(
            plugin_name=plugin_name,
            threshold=_rw(values, 17),
            ratio=_rw(values, 18, 1.0),
            attack=_rw(values, 0, 0.01),
        )

    elif plugin_name == "DeEsser":
        plugin.parameters["Frequency"] = _rw(values, 0, 5500)
        plugin.parameters["Threshold"] = _rw(values, 2)

    else:
        for i, v in enumerate(values[:20]):
            if v is not None:
                plugin.parameters[f"Param_{i}"] = v
