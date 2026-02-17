"""Project tree view widget for displaying track/plugin hierarchy."""

import customtkinter as ctk
from cubasetools.gui import theme
from cubasetools.core.models import CubaseProject


class ProjectTree(ctk.CTkScrollableFrame):
    """Scrollable tree showing tracks and their plugin chains."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, fg_color=theme.BG_PRIMARY, **kwargs)
        self._items: list[ctk.CTkFrame] = []

    def load_project(self, project: CubaseProject):
        """Display the project's track/plugin hierarchy."""
        self._clear()

        for track in project.tracks:
            # Track header
            track_frame = ctk.CTkFrame(self, fg_color=theme.BG_TERTIARY, corner_radius=6)
            track_frame.pack(fill="x", pady=(4, 0), padx=4)

            type_color = {
                "audio": theme.ACCENT,
                "instrument": theme.ACCENT_SUCCESS,
                "fx": theme.ACCENT_INFO,
                "group": theme.ACCENT_WARNING,
                "midi": "#ffb74d",
            }.get(track.track_type.value, theme.TEXT_MUTED)

            # Type indicator + name
            header = ctk.CTkFrame(track_frame, fg_color="transparent")
            header.pack(fill="x", padx=8, pady=6)

            ctk.CTkLabel(
                header,
                text=f"[{track.track_type.value.upper()}]",
                font=(theme.FONT_MONO, theme.FONT_SIZE_SMALL),
                text_color=type_color,
                width=80,
                anchor="w",
            ).pack(side="left")

            ctk.CTkLabel(
                header,
                text=track.name,
                font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY, "bold"),
                text_color=theme.TEXT_PRIMARY,
                anchor="w",
            ).pack(side="left", fill="x", expand=True)

            plugin_count = len(track.plugins)
            if plugin_count:
                ctk.CTkLabel(
                    header,
                    text=f"{plugin_count} Plugin{'s' if plugin_count != 1 else ''}",
                    font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
                    text_color=theme.TEXT_MUTED,
                ).pack(side="right")

            # Plugin list
            for plugin in track.plugins:
                plugin_frame = ctk.CTkFrame(track_frame, fg_color="transparent")
                plugin_frame.pack(fill="x", padx=(30, 8), pady=2)

                status_color = theme.TEXT_DISABLED if plugin.bypassed else theme.ACCENT_SUCCESS
                ctk.CTkLabel(
                    plugin_frame,
                    text="●",
                    font=(theme.FONT_FAMILY, 8),
                    text_color=status_color,
                    width=15,
                ).pack(side="left")

                ctk.CTkLabel(
                    plugin_frame,
                    text=plugin.name or "Unknown Plugin",
                    font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
                    text_color=theme.TEXT_SECONDARY,
                    anchor="w",
                ).pack(side="left", fill="x", expand=True)

                # EQ/Comp indicators
                indicators = []
                if plugin.eq_bands:
                    indicators.append(f"EQ({len(plugin.eq_bands)})")
                if plugin.compressor:
                    indicators.append("COMP")

                if indicators:
                    ctk.CTkLabel(
                        plugin_frame,
                        text=" | ".join(indicators),
                        font=(theme.FONT_MONO, theme.FONT_SIZE_SMALL - 1),
                        text_color=theme.ACCENT_INFO,
                    ).pack(side="right")

            self._items.append(track_frame)

    def _clear(self):
        for item in self._items:
            item.destroy()
        self._items.clear()
