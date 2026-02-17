"""EQ curve visualization widget using matplotlib embedded in tkinter."""

from __future__ import annotations

import customtkinter as ctk

from cubasetools.gui import theme
from cubasetools.core.models import EQBand
from cubasetools.analyzer.eq_analyzer import compute_eq_curve

try:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


class EQCurveWidget(ctk.CTkFrame):
    """Widget that displays EQ curves using matplotlib."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=theme.BG_PRIMARY, **kwargs)

        if not HAS_MATPLOTLIB:
            ctk.CTkLabel(
                self,
                text="matplotlib nicht installiert - pip install matplotlib",
                text_color=theme.ACCENT_WARNING,
            ).pack(expand=True)
            return

        self.fig = Figure(figsize=(6, 3), dpi=100, facecolor=theme.BG_PRIMARY)
        self.ax = self.fig.add_subplot(111)
        self._style_axes()

        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)

    def _style_axes(self):
        """Apply dark theme to matplotlib axes."""
        self.ax.set_facecolor(theme.BG_SECONDARY)
        self.ax.tick_params(colors=theme.TEXT_MUTED, labelsize=8)
        self.ax.spines["bottom"].set_color(theme.BG_TERTIARY)
        self.ax.spines["top"].set_color(theme.BG_TERTIARY)
        self.ax.spines["left"].set_color(theme.BG_TERTIARY)
        self.ax.spines["right"].set_color(theme.BG_TERTIARY)
        self.ax.set_xlabel("Frequency (Hz)", color=theme.TEXT_MUTED, fontsize=8)
        self.ax.set_ylabel("Gain (dB)", color=theme.TEXT_MUTED, fontsize=8)
        self.ax.set_xscale("log")
        self.ax.set_xlim(20, 20000)
        self.ax.set_ylim(-18, 18)
        self.ax.axhline(y=0, color=theme.BG_TERTIARY, linewidth=0.5)
        self.ax.grid(True, alpha=0.15, color=theme.TEXT_MUTED)

    def plot_curves(
        self,
        curves: list[tuple[str, list[EQBand]]],
        sample_rate: int = 48000,
    ):
        """Plot multiple EQ curves overlaid.

        curves: list of (label, bands) tuples.
        """
        if not HAS_MATPLOTLIB:
            return

        self.ax.clear()
        self._style_axes()

        colors = theme.CHART_COLORS
        for i, (label, bands) in enumerate(curves):
            freqs, gains = compute_eq_curve(bands, sample_rate)
            color = colors[i % len(colors)]
            self.ax.plot(freqs, gains, color=color, linewidth=1.5, label=label, alpha=0.85)

        if curves:
            self.ax.legend(
                fontsize=7,
                facecolor=theme.BG_TERTIARY,
                edgecolor=theme.BG_HOVER,
                labelcolor=theme.TEXT_SECONDARY,
                loc="upper right",
            )

        self.fig.tight_layout(pad=1.0)
        self.canvas.draw()

    def clear(self):
        """Clear the plot."""
        if not HAS_MATPLOTLIB:
            return
        self.ax.clear()
        self._style_axes()
        self.canvas.draw()
