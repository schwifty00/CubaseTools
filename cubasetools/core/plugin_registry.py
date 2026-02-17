"""Plugin parameter mappings for known plugins.

Maps raw parameter names/values to meaningful musical parameters
for SSL, Waves, FabFilter, and other common mixing plugins.
"""

from __future__ import annotations

from cubasetools.core.models import (
    CompressorSettings,
    EQBand,
    EQBandType,
    PluginInstance,
)


# ── SSL Native Channel Strip 2 / SSL E-Channel ─────────────
SSL_EQ_BANDS = {
    "EQ LF": {"type": EQBandType.LOW_SHELF, "default_freq": 60.0},
    "EQ LMF": {"type": EQBandType.PEAK, "default_freq": 400.0},
    "EQ HMF": {"type": EQBandType.PEAK, "default_freq": 3000.0},
    "EQ HF": {"type": EQBandType.HIGH_SHELF, "default_freq": 12000.0},
}

SSL_EQ_PARAM_MAP = {
    # Band: (on_key, freq_key, gain_key, q_key)
    "LF": ("LF Bell", "LF Freq", "LF Gain", None),
    "LMF": ("LMF On", "LMF Freq", "LMF Gain", "LMF Q"),
    "HMF": ("HMF On", "HMF Freq", "HMF Gain", "HMF Q"),
    "HF": ("HF Bell", "HF Freq", "HF Gain", None),
}

SSL_COMP_PARAMS = {
    "threshold": ["Comp Threshold", "CompThresh", "Threshold"],
    "ratio": ["Comp Ratio", "CompRatio", "Ratio"],
    "attack": ["Comp Attack", "CompAttack", "Attack"],
    "release": ["Comp Release", "CompRelease", "Release"],
}


# ── Waves CLA-76 ───────────────────────────────────────────
CLA76_PARAM_MAP = {
    "input_gain": ["Input", "input"],
    "output_gain": ["Output", "output"],
    "attack": ["Attack", "attack"],
    "release": ["Release", "release"],
    "ratio": ["Ratio", "ratio"],
}


# ── Waves CLA-2A ───────────────────────────────────────────
CLA2A_PARAM_MAP = {
    "threshold": ["Peak Reduction", "PeakReduction"],
    "output_gain": ["Output Gain", "Gain"],
}


# ── FabFilter Pro-Q 3 ──────────────────────────────────────
PROQ_BAND_TYPES = {
    0: EQBandType.PEAK,
    1: EQBandType.LOW_SHELF,
    2: EQBandType.LOW_CUT,
    3: EQBandType.HIGH_SHELF,
    4: EQBandType.HIGH_CUT,
    5: EQBandType.NOTCH,
}


def _match_param(params: dict[str, float], keys: list[str]) -> float | None:
    """Find a parameter value by trying multiple key names."""
    for key in keys:
        if key in params:
            return params[key]
        # Case-insensitive fallback
        for pname, pval in params.items():
            if pname.lower() == key.lower():
                return pval
    return None


def _interpret_ssl(plugin: PluginInstance):
    """Interpret SSL Channel / EQ parameters."""
    params = plugin.parameters

    # EQ Bands
    for band_label, (on_key, freq_key, gain_key, q_key) in SSL_EQ_PARAM_MAP.items():
        band_info = SSL_EQ_BANDS.get(f"EQ {band_label}", {})
        band = EQBand()
        band.band_type = band_info.get("type", EQBandType.PEAK)
        band.frequency = band_info.get("default_freq", 1000.0)

        if on_key and on_key in params:
            band.enabled = params[on_key] > 0.5

        freq = _match_param(params, [freq_key]) if freq_key else None
        if freq is not None:
            band.frequency = freq

        gain = _match_param(params, [gain_key]) if gain_key else None
        if gain is not None:
            band.gain = gain

        q = _match_param(params, [q_key]) if q_key else None
        if q is not None:
            band.q = q

        # Only add band if it has meaningful data
        if gain is not None or freq is not None:
            plugin.eq_bands.append(band)

    # Compressor
    threshold = _match_param(params, SSL_COMP_PARAMS["threshold"])
    if threshold is not None:
        comp = CompressorSettings(plugin_name=plugin.name)
        comp.threshold = threshold
        ratio = _match_param(params, SSL_COMP_PARAMS["ratio"])
        if ratio is not None:
            comp.ratio = ratio
        attack = _match_param(params, SSL_COMP_PARAMS["attack"])
        if attack is not None:
            comp.attack = attack
        release = _match_param(params, SSL_COMP_PARAMS["release"])
        if release is not None:
            comp.release = release
        comp.raw_parameters = {k: v for k, v in params.items() if "Comp" in k or "comp" in k}
        plugin.compressor = comp


def _interpret_cla76(plugin: PluginInstance):
    """Interpret Waves CLA-76 compressor parameters."""
    params = plugin.parameters
    comp = CompressorSettings(plugin_name=plugin.name)

    input_g = _match_param(params, CLA76_PARAM_MAP["input_gain"])
    if input_g is not None:
        comp.input_gain = input_g

    output_g = _match_param(params, CLA76_PARAM_MAP["output_gain"])
    if output_g is not None:
        comp.output_gain = output_g

    attack = _match_param(params, CLA76_PARAM_MAP["attack"])
    if attack is not None:
        comp.attack = attack

    release = _match_param(params, CLA76_PARAM_MAP["release"])
    if release is not None:
        comp.release = release

    ratio = _match_param(params, CLA76_PARAM_MAP["ratio"])
    if ratio is not None:
        comp.ratio = ratio

    comp.raw_parameters = dict(params)
    plugin.compressor = comp


def _interpret_cla2a(plugin: PluginInstance):
    """Interpret Waves CLA-2A compressor parameters."""
    params = plugin.parameters
    comp = CompressorSettings(plugin_name=plugin.name)

    threshold = _match_param(params, CLA2A_PARAM_MAP["threshold"])
    if threshold is not None:
        comp.threshold = threshold

    output_g = _match_param(params, CLA2A_PARAM_MAP["output_gain"])
    if output_g is not None:
        comp.output_gain = output_g

    comp.raw_parameters = dict(params)
    plugin.compressor = comp


def _interpret_proq(plugin: PluginInstance):
    """Interpret FabFilter Pro-Q 3 parameters."""
    params = plugin.parameters

    # Pro-Q stores bands as numbered parameters: Band 1 Freq, Band 1 Gain, etc.
    band_nums = set()
    for key in params:
        for prefix in ["Band ", "band "]:
            if key.startswith(prefix):
                parts = key[len(prefix):].split(" ", 1)
                if parts[0].isdigit():
                    band_nums.add(int(parts[0]))

    for num in sorted(band_nums):
        band = EQBand()

        freq = _match_param(params, [f"Band {num} Freq", f"Band {num} Frequency"])
        if freq is not None:
            band.frequency = freq

        gain = _match_param(params, [f"Band {num} Gain"])
        if gain is not None:
            band.gain = gain

        q = _match_param(params, [f"Band {num} Q"])
        if q is not None:
            band.q = q

        shape = _match_param(params, [f"Band {num} Shape", f"Band {num} Type"])
        if shape is not None:
            band.band_type = PROQ_BAND_TYPES.get(int(shape), EQBandType.PEAK)

        enabled = _match_param(params, [f"Band {num} Enabled"])
        if enabled is not None:
            band.enabled = enabled > 0.5

        plugin.eq_bands.append(band)


def _interpret_generic_compressor(plugin: PluginInstance):
    """Try to interpret generic compressor parameters."""
    params = plugin.parameters
    comp_keywords = ["threshold", "ratio", "attack", "release", "knee", "makeup"]

    has_comp_params = any(
        any(kw in key.lower() for kw in comp_keywords)
        for key in params
    )

    if not has_comp_params:
        return

    comp = CompressorSettings(plugin_name=plugin.name)

    for key, val in params.items():
        kl = key.lower()
        if "threshold" in kl or "thresh" in kl:
            comp.threshold = val
        elif "ratio" in kl:
            comp.ratio = val
        elif "attack" in kl:
            comp.attack = val
        elif "release" in kl:
            comp.release = val
        elif "knee" in kl:
            comp.knee = val
        elif "makeup" in kl or "make-up" in kl:
            comp.makeup_gain = val

    comp.raw_parameters = dict(params)
    plugin.compressor = comp


def _interpret_generic_eq(plugin: PluginInstance):
    """Try to interpret generic EQ parameters."""
    params = plugin.parameters
    eq_keywords = ["freq", "gain", "band"]

    has_eq_params = any(
        any(kw in key.lower() for kw in eq_keywords)
        for key in params
    )

    if not has_eq_params:
        return

    # Try to find numbered bands
    band_nums = set()
    for key in params:
        for pattern in [r"band\s*(\d+)", r"eq\s*(\d+)", r"band(\d+)"]:
            import re
            m = re.search(pattern, key, re.IGNORECASE)
            if m:
                band_nums.add(int(m.group(1)))

    for num in sorted(band_nums):
        band = EQBand()
        for key, val in params.items():
            kl = key.lower()
            if str(num) not in kl:
                continue
            if "freq" in kl:
                band.frequency = val
            elif "gain" in kl:
                band.gain = val
            elif "q" in kl or "width" in kl:
                band.q = val

        if band.frequency != 1000.0 or band.gain != 0.0:
            plugin.eq_bands.append(band)


# ── Main dispatcher ────────────────────────────────────────

# Map of plugin name patterns to their interpretation functions
PLUGIN_INTERPRETERS: dict[str, callable] = {}


def _name_matches(plugin_name: str, patterns: list[str]) -> bool:
    """Check if a plugin name matches any of the given patterns."""
    name_lower = plugin_name.lower()
    return any(p.lower() in name_lower for p in patterns)


def interpret_plugin_parameters(plugin: PluginInstance):
    """Interpret raw parameters based on plugin identity."""
    name = plugin.name

    if _name_matches(name, ["SSL", "Channel Strip", "E-Channel", "G-Channel"]):
        _interpret_ssl(plugin)
    elif _name_matches(name, ["CLA-76", "CLA76"]):
        _interpret_cla76(plugin)
    elif _name_matches(name, ["CLA-2A", "CLA2A"]):
        _interpret_cla2a(plugin)
    elif _name_matches(name, ["Pro-Q", "ProQ"]):
        _interpret_proq(plugin)
    else:
        # Generic interpretation for unknown plugins
        _interpret_generic_eq(plugin)
        _interpret_generic_compressor(plugin)
