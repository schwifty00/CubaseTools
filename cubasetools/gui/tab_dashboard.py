"""Dashboard tab - project overview with stats and quick access."""

import threading
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog

from cubasetools.gui import theme
from cubasetools.gui.widgets.stat_card import StatCard
from cubasetools.gui.widgets.plugin_table import PluginTable
from cubasetools.core.models import CubaseProject
from cubasetools.dashboard.scanner import scan_projects
from cubasetools.dashboard.cross_project import compute_cross_project_stats
from cubasetools.export.json_export import export_project_json
from cubasetools.utils.config import DEFAULT_SCAN_PATH
from cubasetools.utils.file_utils import format_size


class DashboardTab:
    """Dashboard tab with project overview cards and tables."""

    def __init__(self, parent: ctk.CTkFrame, app=None):
        self.parent = parent
        self.app = app
        self.projects: list[CubaseProject] = []
        self._build_ui()

    def _build_ui(self):
        # Top bar
        top_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        top_frame.pack(fill="x", padx=15, pady=(15, 5))

        ctk.CTkLabel(
            top_frame,
            text="Scan-Ordner:",
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY),
        ).pack(side="left", padx=(0, 10))

        self.path_var = ctk.StringVar(value=str(DEFAULT_SCAN_PATH))
        ctk.CTkEntry(
            top_frame,
            textvariable=self.path_var,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY),
            fg_color=theme.BG_TERTIARY,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            top_frame,
            text="Ordner...",
            width=80,
            command=self._browse,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.BG_HOVER,
        ).pack(side="left", padx=(0, 5))

        self.scan_btn = ctk.CTkButton(
            top_frame,
            text="Scannen",
            width=120,
            command=self._scan,
            fg_color=theme.ACCENT_DARK,
            hover_color=theme.ACCENT,
        )
        self.scan_btn.pack(side="left")

        # Status / progress
        self.status_var = ctk.StringVar(value="Klicke 'Scannen' um alle Projekte zu analysieren")
        ctk.CTkLabel(
            self.parent,
            textvariable=self.status_var,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
            text_color=theme.TEXT_MUTED,
        ).pack(fill="x", padx=15, pady=(5, 5))

        self.progress = ctk.CTkProgressBar(
            self.parent,
            fg_color=theme.BG_TERTIARY,
            progress_color=theme.ACCENT,
        )
        self.progress.pack(fill="x", padx=15, pady=(0, 10))
        self.progress.set(0)

        # Stats cards row
        cards_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        cards_frame.pack(fill="x", padx=15, pady=(0, 10))
        cards_frame.columnconfigure((0, 1, 2, 3), weight=1)

        self.card_projects = StatCard(
            cards_frame, title="Projekte", value="0",
            accent_color=theme.CARD_COLORS[0],
        )
        self.card_projects.grid(row=0, column=0, padx=(0, 5), sticky="ew")

        self.card_tracks = StatCard(
            cards_frame, title="Tracks", value="0",
            accent_color=theme.CARD_COLORS[1],
        )
        self.card_tracks.grid(row=0, column=1, padx=5, sticky="ew")

        self.card_plugins = StatCard(
            cards_frame, title="Plugins", value="0",
            accent_color=theme.CARD_COLORS[2],
        )
        self.card_plugins.grid(row=0, column=2, padx=5, sticky="ew")

        self.card_size = StatCard(
            cards_frame, title="Projektdaten", value="0 B",
            accent_color=theme.CARD_COLORS[3],
        )
        self.card_size.grid(row=0, column=3, padx=(5, 0), sticky="ew")

        # Bottom area: project table + plugin stats
        bottom_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        bottom_frame.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        bottom_frame.columnconfigure(0, weight=2)
        bottom_frame.columnconfigure(1, weight=1)
        bottom_frame.rowconfigure(0, weight=1)

        # Project table
        project_panel = ctk.CTkFrame(bottom_frame, fg_color=theme.BG_PRIMARY, corner_radius=8)
        project_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        ctk.CTkLabel(
            project_panel,
            text="Projekte",
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_HEADING, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(fill="x", padx=10, pady=(8, 4))

        self.project_table = PluginTable(
            project_panel,
            columns=["Projekt", "Tracks", "Plugins", "Tempo", "Groesse"],
        )
        self.project_table.pack(fill="both", expand=True, padx=5, pady=(0, 8))

        # Plugin stats panel
        plugin_panel = ctk.CTkFrame(bottom_frame, fg_color=theme.BG_PRIMARY, corner_radius=8)
        plugin_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0))

        ctk.CTkLabel(
            plugin_panel,
            text="Top Plugins",
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_HEADING, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(fill="x", padx=10, pady=(8, 4))

        self.plugin_stats_table = PluginTable(
            plugin_panel,
            columns=["Plugin", "Anzahl"],
        )
        self.plugin_stats_table.pack(fill="both", expand=True, padx=5, pady=(0, 8))

        # Double-click to open analyzer
        # (PluginTable doesn't natively support row-click, but data is accessible)

    def _browse(self):
        folder = filedialog.askdirectory(
            title="Projekt-Ordner auswaehlen",
            initialdir=str(DEFAULT_SCAN_PATH),
        )
        if folder:
            self.path_var.set(folder)
            self._scan()

    def _scan(self):
        path = self.path_var.get().strip()
        if not path:
            return

        target = Path(path)
        if not target.exists():
            self.status_var.set("Ordner existiert nicht!")
            return

        self.scan_btn.configure(state="disabled")
        self.progress.set(0)
        self.status_var.set("Scanne...")

        threading.Thread(target=self._run_scan, args=(target,), daemon=True).start()

    def _run_scan(self, target: Path):
        def on_progress(current, total, name):
            self.parent.after(0, lambda: self.progress.set(current / total))
            self.parent.after(
                0, lambda: self.status_var.set(f"[{current}/{total}] {name}")
            )

        try:
            projects = scan_projects(target, progress_callback=on_progress)
            self.projects = projects

            cross_stats = compute_cross_project_stats(projects)

            def update_ui():
                # Update stat cards
                self.card_projects.update_value(str(cross_stats.total_projects))
                self.card_tracks.update_value(str(cross_stats.total_tracks))
                self.card_plugins.update_value(str(cross_stats.total_plugins))
                self.card_size.update_value(format_size(cross_stats.total_file_size))

                # Project table
                rows = []
                for p in projects:
                    rows.append([
                        p.project_name,
                        str(p.track_count),
                        str(p.plugin_count),
                        f"{p.tempo:.0f}",
                        format_size(p.file_size),
                    ])
                self.project_table.set_data(rows)

                # Plugin stats
                plugin_rows = []
                for name, count in list(cross_stats.most_used_plugins.items())[:20]:
                    plugin_rows.append([name, str(count)])
                self.plugin_stats_table.set_data(plugin_rows)

                self.progress.set(1)
                self.status_var.set(
                    f"Fertig! {cross_stats.total_projects} Projekte, "
                    f"{cross_stats.total_tracks} Tracks, "
                    f"{cross_stats.total_plugins} Plugins"
                )
                self.scan_btn.configure(state="normal")

            self.parent.after(0, update_ui)

        except Exception as e:
            self.parent.after(
                0,
                lambda: (
                    self.status_var.set(f"Fehler: {e}"),
                    self.scan_btn.configure(state="normal"),
                ),
            )
