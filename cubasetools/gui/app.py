"""Main application window with tabbed interface."""

import ctypes
import customtkinter as ctk

from cubasetools.gui import theme
from cubasetools.gui.tab_cleanup import CleanupTab
from cubasetools.gui.tab_backup import BackupTab
from cubasetools.gui.tab_analyzer import AnalyzerTab
from cubasetools.gui.tab_dashboard import DashboardTab
from cubasetools.utils.config import (
    APP_NAME,
    APP_VERSION,
    WINDOW_HEIGHT,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
    WINDOW_WIDTH,
)


class CubaseToolsApp:
    """Main application class."""

    def __init__(self):
        self._set_dpi_awareness()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.root = ctk.CTk()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self.root.configure(fg_color=theme.BG_PRIMARY)

        self._build_ui()

    def _set_dpi_awareness(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass

    def _build_ui(self):
        # Title bar
        title_frame = ctk.CTkFrame(self.root, fg_color=theme.BG_PRIMARY)
        title_frame.pack(fill="x", padx=20, pady=(15, 5))

        ctk.CTkLabel(
            title_frame,
            text=APP_NAME,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_TITLE, "bold"),
            text_color=theme.ACCENT,
        ).pack(side="left")

        ctk.CTkLabel(
            title_frame,
            text=f"v{APP_VERSION}",
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
            text_color=theme.TEXT_MUTED,
        ).pack(side="left", padx=(10, 0), pady=(8, 0))

        # Tab view
        self.tabview = ctk.CTkTabview(
            self.root,
            fg_color=theme.BG_SECONDARY,
            segmented_button_fg_color=theme.BG_TERTIARY,
            segmented_button_selected_color=theme.ACCENT_DARK,
            segmented_button_selected_hover_color=theme.ACCENT,
            segmented_button_unselected_color=theme.BG_TERTIARY,
            segmented_button_unselected_hover_color=theme.BG_HOVER,
        )
        self.tabview.pack(fill="both", expand=True, padx=15, pady=(5, 15))

        # Create tabs
        tab_dashboard = self.tabview.add("Dashboard")
        tab_analyzer = self.tabview.add("Mix Analyzer")
        tab_cleanup = self.tabview.add("Audio Cleanup")
        tab_backup = self.tabview.add("Backup Cleanup")

        # Initialize tab content
        self.dashboard_tab = DashboardTab(tab_dashboard, self)
        self.analyzer_tab = AnalyzerTab(tab_analyzer)
        self.cleanup_tab = CleanupTab(tab_cleanup)
        self.backup_tab = BackupTab(tab_backup)

    def open_analyzer_for_project(self, cpr_path):
        """Switch to analyzer tab and load a specific project."""
        self.tabview.set("Mix Analyzer")
        self.analyzer_tab.load_project(cpr_path)

    def run(self):
        self.root.mainloop()
