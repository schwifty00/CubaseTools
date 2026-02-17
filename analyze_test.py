"""Quick test script to display full CPR analysis."""
import sys
sys.path.insert(0, ".")

from cubasetools.core.cpr_parser import parse_cpr
from pathlib import Path

cpr_path = sys.argv[1] if len(sys.argv) > 1 else r"C:\DeepArt\Projekt 25\Provisorisch\25-7\25-7.cpr"
p = parse_cpr(Path(cpr_path))

print(f"=== PROJEKT: {p.project_name} ===")
print(f"Sample Rate: {p.sample_rate} Hz | Tempo: {p.tempo} BPM")
print(f"Tracks: {p.track_count} | Plugins: {p.plugin_count} | Audio: {len(p.referenced_audio)}")
print()

for t in p.tracks:
    print(f"--- [{t.track_type.value.upper():12s}] {t.name} ---")
    if not t.plugins:
        print("    (keine Plugins)")
    for i, pl in enumerate(t.plugins):
        bypassed = " [BYPASS]" if pl.bypassed else ""
        print(f"    Slot {i+1}: {pl.name}{bypassed}")

        if pl.eq_bands:
            for band in pl.eq_bands:
                status = "ON" if band.enabled else "off"
                sign = "+" if band.gain >= 0 else ""
                print(f"      EQ: {band.band_type.value:12s} {band.frequency:8.1f} Hz  {sign}{band.gain:.1f} dB  Q={band.q:.2f}  [{status}]")

        if pl.compressor:
            c = pl.compressor
            parts = []
            if c.threshold:
                parts.append(f"Thresh={c.threshold:.1f}dB")
            if c.ratio and c.ratio != 1:
                parts.append(f"Ratio={c.ratio:.1f}:1")
            if c.attack and c.attack != 10:
                parts.append(f"Atk={c.attack:.1f}ms")
            if c.release and c.release != 100:
                parts.append(f"Rel={c.release:.1f}ms")
            if c.input_gain:
                parts.append(f"In={c.input_gain:.1f}dB")
            if c.output_gain:
                parts.append(f"Out={c.output_gain:.1f}dB")
            if parts:
                print(f"      COMP: {' | '.join(parts)}")

        if pl.parameters and not pl.eq_bands and not pl.compressor:
            relevant = {k: v for k, v in pl.parameters.items() if not k.startswith("Param_")}
            if relevant:
                print(f"      Params: {relevant}")
            else:
                raw = {k: round(v, 2) for k, v in list(pl.parameters.items())[:5]}
                if raw:
                    print(f"      Raw: {raw}")
    print()
