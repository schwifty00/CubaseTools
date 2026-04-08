"""Sortable plugin table widget using grid layout for aligned columns."""

import customtkinter as ctk
from cubasetools.gui import theme


class PluginTable(ctk.CTkFrame):
    """A scrollable table with aligned columns and sortable headers."""

    def __init__(self, parent, columns: list[str], **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)

        self.columns = columns
        self.rows: list[list[str]] = []
        self.sort_column = 0
        self.sort_reverse = False
        self._col_widths = self._compute_widths(columns)

        # Header row
        header_frame = ctk.CTkFrame(self, fg_color=theme.BG_TERTIARY, height=32)
        header_frame.pack(fill="x")
        header_frame.pack_propagate(False)

        self._header_labels = []
        for i, col in enumerate(columns):
            btn = ctk.CTkButton(
                header_frame,
                text=col,
                width=self._col_widths[i],
                fg_color="transparent",
                hover_color=theme.BG_HOVER,
                text_color=theme.TEXT_MUTED,
                font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL, "bold"),
                anchor="w",
                command=lambda idx=i: self._sort_by(idx),
            )
            btn.pack(side="left", padx=0)
            self._header_labels.append(btn)

        # Scrollable body
        self.body = ctk.CTkScrollableFrame(
            self, fg_color=theme.BG_PRIMARY, label_text=""
        )
        self.body.pack(fill="both", expand=True)

        self._row_frames: list[ctk.CTkFrame] = []

    @staticmethod
    def _compute_widths(columns: list[str]) -> list[int]:
        """Assign fixed pixel widths based on column name."""
        widths = []
        for col in columns:
            low = col.lower()
            if low in ("m", "s", "mon"):
                widths.append(35)
            elif low in ("volume", "pan", "plugins", "anzahl", "noten",
                         "vel min", "vel max", "tiefste", "hoechste",
                         "punkte", "min", "max"):
                widths.append(60)
            elif low in ("typ", "threshold", "ratio", "attack", "release",
                         "makeup", "folder", "preset"):
                widths.append(80)
            elif low in ("output", "plugin", "part", "parameter"):
                widths.append(120)
            elif low in ("track", "sends", "tracks"):
                widths.append(150)
            else:
                widths.append(100)
        return widths

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
        for frame in self._row_frames:
            frame.destroy()
        self._row_frames.clear()

        for i, row in enumerate(self.rows):
            bg = theme.BG_SECONDARY if i % 2 == 0 else theme.BG_PRIMARY
            row_frame = ctk.CTkFrame(self.body, fg_color=bg, height=26)
            row_frame.pack(fill="x", pady=0)
            row_frame.pack_propagate(False)

            for j, cell in enumerate(row):
                w = self._col_widths[j] if j < len(self._col_widths) else 80

                # Color flags
                low_col = self.columns[j].lower() if j < len(self.columns) else ""
                if low_col == "m" and str(cell).strip():
                    text_color = theme.ACCENT_WARNING
                elif low_col == "s" and str(cell).strip():
                    text_color = theme.ACCENT_INFO
                elif low_col == "mon" and str(cell).strip():
                    text_color = theme.ACCENT_SUCCESS
                else:
                    text_color = theme.TEXT_SECONDARY

                ctk.CTkLabel(
                    row_frame,
                    text=str(cell),
                    width=w,
                    font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
                    text_color=text_color,
                    anchor="w",
                ).pack(side="left", padx=0)

            self._row_frames.append(row_frame)
