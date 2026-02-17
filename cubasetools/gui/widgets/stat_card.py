"""Stat card widget for dashboard overview."""

import customtkinter as ctk
from cubasetools.gui import theme


class StatCard(ctk.CTkFrame):
    """A compact statistics card showing a label and value."""

    def __init__(
        self,
        parent,
        title: str = "",
        value: str = "0",
        accent_color: str = theme.ACCENT,
        **kwargs,
    ):
        super().__init__(parent, fg_color=theme.BG_TERTIARY, corner_radius=10, **kwargs)

        # Color accent bar
        accent_bar = ctk.CTkFrame(
            self, fg_color=accent_color, width=4, corner_radius=2
        )
        accent_bar.pack(side="left", fill="y", padx=(8, 0), pady=10)

        text_frame = ctk.CTkFrame(self, fg_color="transparent")
        text_frame.pack(side="left", fill="both", expand=True, padx=12, pady=10)

        self.value_label = ctk.CTkLabel(
            text_frame,
            text=value,
            font=(theme.FONT_FAMILY, 24, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        )
        self.value_label.pack(fill="x")

        self.title_label = ctk.CTkLabel(
            text_frame,
            text=title,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
            text_color=theme.TEXT_MUTED,
            anchor="w",
        )
        self.title_label.pack(fill="x")

    def update_value(self, value: str):
        self.value_label.configure(text=value)

    def update_title(self, title: str):
        self.title_label.configure(text=title)
