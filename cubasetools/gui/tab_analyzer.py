"""Mix Analyzer tab - plugin chains, EQ curves, compressor overview."""

import threading
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog

from cubasetools.gui import theme
from cubasetools.core.cpr_parser import parse_cpr
from cubasetools.core.models import CubaseProject
from cubasetools.analyzer.plugin_chain import get_plugin_chains, get_plugin_usage_stats
from cubasetools.analyzer.eq_analyzer import get_all_eq_data
from cubasetools.analyzer.compressor_analyzer import get_all_compressor_data, compressor_summary
from cubasetools.export.json_export import export_project_json
from cubasetools.gui.widgets.project_tree import ProjectTree
from cubasetools.gui.widgets.eq_curve import EQCurveWidget
from cubasetools.gui.widgets.plugin_table import PluginTable
from cubasetools.gui.widgets.stat_card import StatCard
from cubasetools.utils.config import DEFAULT_SCAN_PATH


class AnalyzerTab:
    """Mix analyzer tab with plugin chain, EQ, and compressor views."""

    def __init__(self, parent: ctk.CTkFrame):
        self.parent = parent
        self.project: CubaseProject | None = None
        self._busy = False
        self._build_ui()

    def _build_ui(self):
        # Top bar: file selection
        top_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        top_frame.pack(fill="x", padx=15, pady=(15, 5))

        ctk.CTkLabel(
            top_frame,
            text=".cpr Datei:",
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY),
        ).pack(side="left", padx=(0, 10))

        self.path_var = ctk.StringVar()
        ctk.CTkEntry(
            top_frame,
            textvariable=self.path_var,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY),
            fg_color=theme.BG_TERTIARY,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            top_frame,
            text="Datei...",
            width=80,
            command=self._browse,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.BG_HOVER,
        ).pack(side="left", padx=(0, 5))

        self.parse_btn = ctk.CTkButton(
            top_frame,
            text="Analysieren",
            width=120,
            command=self._parse,
            fg_color=theme.ACCENT_DARK,
            hover_color=theme.ACCENT,
        )
        self.parse_btn.pack(side="left", padx=(0, 5))

        self.export_btn = ctk.CTkButton(
            top_frame,
            text="JSON Export",
            width=120,
            command=self._export_json,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.ACCENT_SUCCESS,
            state="disabled",
        )
        self.export_btn.pack(side="left")

        # Project info bar (stat cards)
        self.info_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        self.info_frame.pack(fill="x", padx=15, pady=(5, 5))

        self.card_tempo = StatCard(self.info_frame, title="Tempo", accent_color=theme.ACCENT)
        self.card_tempo.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.card_sig = StatCard(self.info_frame, title="Taktart", accent_color=theme.ACCENT_SUCCESS)
        self.card_sig.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.card_sr = StatCard(self.info_frame, title="Sample Rate", accent_color=theme.ACCENT_INFO)
        self.card_sr.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.card_bit = StatCard(self.info_frame, title="Bit Depth", accent_color=theme.ACCENT_WARNING)
        self.card_bit.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.card_tracks = StatCard(self.info_frame, title="Tracks", accent_color=theme.ACCENT)
        self.card_tracks.pack(side="left", fill="x", expand=True, padx=(0, 5))

        self.card_plugins = StatCard(self.info_frame, title="Plugins", accent_color=theme.ACCENT_SUCCESS)
        self.card_plugins.pack(side="left", fill="x", expand=True)

        # Status
        self.status_var = ctk.StringVar(value=".cpr Datei auswaehlen und 'Analysieren' klicken")
        ctk.CTkLabel(
            self.parent,
            textvariable=self.status_var,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
            text_color=theme.TEXT_MUTED,
        ).pack(fill="x", padx=15, pady=(2, 2))

        # Main content area with sub-tabs
        self.content_tabs = ctk.CTkTabview(
            self.parent,
            fg_color=theme.BG_PRIMARY,
            segmented_button_fg_color=theme.BG_TERTIARY,
            segmented_button_selected_color=theme.ACCENT_DARK,
            segmented_button_selected_hover_color=theme.ACCENT,
            segmented_button_unselected_color=theme.BG_TERTIARY,
            segmented_button_unselected_hover_color=theme.BG_HOVER,
        )
        self.content_tabs.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        tab_mixer = self.content_tabs.add("Mixer")
        tab_chain = self.content_tabs.add("Plugin-Chain")
        tab_eq = self.content_tabs.add("EQ-Kurven")
        tab_comp = self.content_tabs.add("Kompressor")
        tab_stats = self.content_tabs.add("Plugin-Statistik")
        tab_midi = self.content_tabs.add("MIDI")
        tab_auto = self.content_tabs.add("Automation")

        # Mixer overview table (expanded with new columns)
        self.mixer_table = PluginTable(
            tab_mixer,
            columns=[
                "Track", "Typ", "Folder", "Volume", "Pan",
                "M", "S", "Mon", "Output", "Sends", "Plugins",
            ],
        )
        self.mixer_table.pack(fill="both", expand=True)

        # Plugin chain tree
        self.project_tree = ProjectTree(tab_chain)
        self.project_tree.pack(fill="both", expand=True)

        # EQ curves
        self.eq_widget = EQCurveWidget(tab_eq)
        self.eq_widget.pack(fill="both", expand=True)

        # Compressor table
        self.comp_table = PluginTable(
            tab_comp,
            columns=["Track", "Plugin", "Preset", "Threshold", "Ratio", "Attack", "Release", "Makeup"],
        )
        self.comp_table.pack(fill="both", expand=True)

        # Plugin stats table
        self.stats_table = PluginTable(
            tab_stats,
            columns=["Plugin", "Anzahl", "Tracks"],
        )
        self.stats_table.pack(fill="both", expand=True)

        # MIDI table
        self.midi_table = PluginTable(
            tab_midi,
            columns=["Track", "Part", "Noten", "Tiefste", "Hoechste", "Vel Min", "Vel Max"],
        )
        self.midi_table.pack(fill="both", expand=True)

        # Automation table
        self.auto_table = PluginTable(
            tab_auto,
            columns=["Parameter", "Punkte", "Min", "Max"],
        )
        self.auto_table.pack(fill="both", expand=True)

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Cubase Projektdatei auswaehlen",
            filetypes=[("Cubase Project", "*.cpr")],
            initialdir=str(DEFAULT_SCAN_PATH),
        )
        if path:
            self.path_var.set(path)
            self._parse()

    def load_project(self, cpr_path):
        """Load a specific .cpr file (called from dashboard)."""
        self.path_var.set(str(cpr_path))
        self._parse()

    def _parse(self):
        if self._busy:
            return
        path = self.path_var.get().strip()
        if not path:
            return

        cpr_path = Path(path)
        if not cpr_path.exists() or cpr_path.suffix.lower() != ".cpr":
            self.status_var.set("Ungueltige .cpr Datei!")
            return

        self._busy = True
        self.parse_btn.configure(state="disabled")
        self.status_var.set("Analysiere...")

        threading.Thread(target=self._run_parse, args=(cpr_path,), daemon=True).start()

    def _run_parse(self, cpr_path: Path):
        try:
            project = parse_cpr(cpr_path)
            self.project = project

            def update_ui():
                self._busy = False
                self._display_results(project)
                self.parse_btn.configure(state="normal")
                self.export_btn.configure(state="normal")

                cycle = f"  Cycle [{project.cycle_left:.1f}-{project.cycle_right:.1f}]" if project.cycle_on else ""
                self.status_var.set(
                    f"{project.cubase_version}{cycle}"
                )

            self.parent.after(0, update_ui)

        except Exception as e:
            self.parent.after(
                0,
                lambda: (
                    setattr(self, '_busy', False),
                    self.status_var.set(f"Fehler: {e}"),
                    self.parse_btn.configure(state="normal"),
                ),
            )

    def _display_results(self, project: CubaseProject):
        # Stat cards
        self.card_tempo.update_value(f"{project.tempo} BPM")
        self.card_sig.update_value(project.time_signature)
        self.card_sr.update_value(f"{project.sample_rate / 1000:.0f} kHz")
        self.card_bit.update_value(f"{project.bit_depth} bit")
        self.card_tracks.update_value(str(project.track_count))
        self.card_plugins.update_value(str(project.plugin_count))

        # Mixer overview (expanded)
        mixer_rows = []
        for t in project.tracks:
            vol = f"{t.volume:+.1f}" if t.volume != 0 else "0.0"
            if t.pan is None:
                pan = "-"
            elif t.pan < -0.01:
                pan = f"L{abs(t.pan)*100:.0f}"
            elif t.pan > 0.01:
                pan = f"R{t.pan*100:.0f}"
            else:
                pan = "C"
            mute = "M" if t.muted else ""
            solo = "S" if t.solo else ""
            mon = "Mon" if t.monitor else ""
            out = t.output_bus or "-"
            sends = ", ".join(s.target_name for s in t.sends) if t.sends else "-"
            plugins = str(len(t.plugins)) if t.plugins else "-"
            folder = t.folder or "-"
            mixer_rows.append([
                t.name, t.track_type.value, folder, vol, pan,
                mute, solo, mon, out, sends, plugins,
            ])
        self.mixer_table.set_data(mixer_rows)

        # Plugin chain tree
        self.project_tree.load_project(project)

        # EQ curves
        eq_data = get_all_eq_data(project)
        if eq_data:
            curves = [(f"{track.name} ({pname})", bands) for track, pname, bands in eq_data]
            self.eq_widget.plot_curves(curves, project.sample_rate)
        else:
            self.eq_widget.clear()

        # Compressor table (with preset names)
        comp_data = get_all_compressor_data(project)
        comp_rows = []
        for track, comp in comp_data:
            summary = compressor_summary(comp)
            # Find preset name for this compressor plugin
            preset = ""
            for p in track.plugins:
                if p.compressor and p.compressor.plugin_name == comp.plugin_name:
                    preset = p.preset_name
                    break
            comp_rows.append([
                track.name,
                summary["Plugin"],
                preset,
                summary["Threshold"],
                summary["Ratio"],
                summary["Attack"],
                summary["Release"],
                summary["Makeup"],
            ])
        self.comp_table.set_data(comp_rows)

        # Plugin stats
        usage = get_plugin_usage_stats(project)
        stats_rows = []
        by_name = project.plugins_by_name()
        for name, count in usage.items():
            tracks = ", ".join(t.name for t, _ in by_name.get(name, []))
            stats_rows.append([name, str(count), tracks])
        self.stats_table.set_data(stats_rows)

        # MIDI table
        _NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        def _note_name(midi_num):
            return f"{_NOTE_NAMES[midi_num % 12]}{midi_num // 12 - 1}"

        midi_rows = []
        for t in project.tracks:
            for mp in t.midi_parts:
                if not mp.notes:
                    continue
                pitches = [n.pitch for n in mp.notes]
                vels = [n.velocity for n in mp.notes]
                midi_rows.append([
                    t.name,
                    mp.name or "-",
                    str(len(mp.notes)),
                    _note_name(min(pitches)),
                    _note_name(max(pitches)),
                    str(min(vels)),
                    str(max(vels)),
                ])
        self.midi_table.set_data(midi_rows)

        # Automation table
        auto_rows = []
        for lane in project.automation:
            if not lane.points:
                continue
            values = [p.value for p in lane.points]
            auto_rows.append([
                lane.parameter_name or "-",
                str(len(lane.points)),
                f"{min(values):.3f}",
                f"{max(values):.3f}",
            ])
        self.auto_table.set_data(auto_rows)

    def _export_json(self):
        if not self.project:
            return

        path = filedialog.asksaveasfilename(
            title="JSON Export speichern",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"{self.project.project_name}_mix.json",
        )
        if path:
            export_project_json(self.project, Path(path))
            self.status_var.set(f"Exportiert: {path}")
