"""Sortable plugin table widget using CTkScrollableFrame."""

import customtkinter as ctk
from cubasetools.gui import theme


class PluginTable(ctk.CTkFrame):
    """A scrollable table showing plugin data with sortable columns."""

    def __init__(self, parent, columns: list[str], **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.columns = columns
        self.rows: list[list[str]] = []
        self.sort_column = 0
        self.sort_reverse = False

        # Header
        header_frame = ctk.CTkFrame(self, fg_color=theme.BG_TERTIARY, height=35)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        self._header_labels = []
        for i, col in enumerate(columns):
            btn = ctk.CTkButton(
                header_frame,
                text=col,
                fg_color="transparent",
                hover_color=theme.BG_HOVER,
                text_color=theme.TEXT_MUTED,
                font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL, "bold"),
                anchor="w",
                command=lambda idx=i: self._sort_by(idx),
            )
            btn.pack(side="left", fill="both", expand=True)
            self._header_labels.append(btn)

        # Body
        self.body = ctk.CTkScrollableFrame(
            self, fg_color=theme.BG_PRIMARY, label_text=""
        )
        self.body.pack(fill="both", expand=True)

        self._row_frames: list[ctk.CTkFrame] = []

    def set_data(self, rows: list[list[str]]):
        """Set table data and refresh display."""
        self.rows = rows
        self._render()

    def _sort_by(self, col_index: int):
        if self.sort_column == col_index:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = col_index
            self.sort_reverse = False

        # Try numeric sort, fallback to string
        try:
            self.rows.sort(
                key=lambda r: float(r[col_index]) if col_index < len(r) else 0,
                reverse=self.sort_reverse,
            )
        except (ValueError, IndexError):
            self.rows.sort(
                key=lambda r: r[col_index] if col_index < len(r) else "",
                reverse=self.sort_reverse,
            )

        self._render()

    def _render(self):
        # Clear existing rows
        for frame in self._row_frames:
            frame.destroy()
        self._row_frames.clear()

        for i, row in enumerate(self.rows):
            bg = theme.BG_SECONDARY if i % 2 == 0 else theme.BG_PRIMARY
            row_frame = ctk.CTkFrame(self.body, fg_color=bg, height=30)
            row_frame.pack(fill="x", pady=1)
            row_frame.pack_propagate(False)

            for j, cell in enumerate(row):
                ctk.CTkLabel(
                    row_frame,
                    text=str(cell),
                    font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
                    text_color=theme.TEXT_SECONDARY,
                    anchor="w",
                ).pack(side="left", fill="both", expand=True, padx=8)

            self._row_frames.append(row_frame)
