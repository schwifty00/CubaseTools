"""Backup Cleanup tab - finds and removes .bak and .peak files."""

import threading
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox

from cubasetools.gui import theme
from cubasetools.cleanup.backup_cleanup import (
    categorize_backup_files,
    delete_backup_files,
    find_backup_files,
)
from cubasetools.utils.config import DEFAULT_SCAN_PATH
from cubasetools.utils.file_utils import format_size


class BackupTab:
    """Tab for cleaning up .bak and .peak backup files."""

    def __init__(self, parent: ctk.CTkFrame):
        self.parent = parent
        self.found_files: list[Path] = []
        self._build_ui()

    def _build_ui(self):
        # Folder selection
        folder_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        folder_frame.pack(fill="x", padx=15, pady=(15, 5))

        ctk.CTkLabel(
            folder_frame,
            text="Scan-Ordner:",
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY),
        ).pack(side="left", padx=(0, 10))

        self.path_var = ctk.StringVar(value=str(DEFAULT_SCAN_PATH))
        ctk.CTkEntry(
            folder_frame,
            textvariable=self.path_var,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY),
            fg_color=theme.BG_TERTIARY,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))

        ctk.CTkButton(
            folder_frame,
            text="Ordner...",
            width=100,
            command=self._browse,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.BG_HOVER,
        ).pack(side="left")

        # Action buttons
        btn_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        btn_frame.pack(fill="x", padx=15, pady=(10, 5))

        self.scan_btn = ctk.CTkButton(
            btn_frame,
            text="Scannen",
            command=self._scan,
            fg_color=theme.ACCENT_DARK,
            hover_color=theme.ACCENT,
            width=140,
        )
        self.scan_btn.pack(side="left", padx=(0, 10))

        self.delete_btn = ctk.CTkButton(
            btn_frame,
            text="Alle loeschen",
            command=self._delete,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.ACCENT_WARNING,
            width=140,
            state="disabled",
        )
        self.delete_btn.pack(side="left")

        # Status
        self.status_var = ctk.StringVar(value="Ordner auswaehlen und 'Scannen' klicken")
        ctk.CTkLabel(
            self.parent,
            textvariable=self.status_var,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_SMALL),
            text_color=theme.TEXT_MUTED,
        ).pack(fill="x", padx=15, pady=(5, 5))

        # Log area
        self.log_text = ctk.CTkTextbox(
            self.parent,
            font=(theme.FONT_MONO, theme.FONT_SIZE_MONO),
            fg_color=theme.BG_PRIMARY,
            text_color=theme.TEXT_SECONDARY,
        )
        self.log_text.pack(fill="both", expand=True, padx=15, pady=(5, 15))

    def _log(self, text: str):
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.parent.update_idletasks()

    def _clear_log(self):
        self.log_text.delete("1.0", "end")

    def _browse(self):
        folder = filedialog.askdirectory(
            title="Ordner zum Scannen auswaehlen",
            initialdir=str(DEFAULT_SCAN_PATH),
        )
        if folder:
            self.path_var.set(folder)
            self._scan()

    def _scan(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Fehler", "Bitte einen Ordner auswaehlen!")
            return

        target = Path(path)
        if not target.exists():
            messagebox.showerror("Fehler", f"Ordner existiert nicht:\n{path}")
            return

        self._clear_log()
        self.found_files = []
        self.delete_btn.configure(state="disabled")
        self.scan_btn.configure(state="disabled")

        threading.Thread(target=self._run_scan, args=(target,), daemon=True).start()

    def _run_scan(self, target: Path):
        try:
            self.parent.after(0, lambda: self.status_var.set("Suche Backup-Dateien..."))
            self.parent.after(0, lambda: self._log(f"Scanne: {target}"))
            self.parent.after(0, lambda: self._log(""))

            files = find_backup_files(target)
            self.found_files = files

            if not files:
                self.parent.after(0, lambda: self._log("Keine .bak oder .peak Dateien gefunden."))
                self.parent.after(0, lambda: self.status_var.set("Keine Backup-Dateien gefunden."))
                return

            categories = categorize_backup_files(files)
            total_size = sum(f.stat().st_size for f in files)

            def update_ui():
                for ext, ext_files in sorted(categories.items()):
                    ext_size = sum(f.stat().st_size for f in ext_files)
                    self._log(f"{ext} Dateien: {len(ext_files)}  ({format_size(ext_size)})")
                    for f in ext_files[:20]:  # Show first 20 per category
                        self._log(f"  {f}")
                    if len(ext_files) > 20:
                        self._log(f"  ... und {len(ext_files) - 20} weitere")
                    self._log("")

                self._log(f"Gesamt: {len(files)} Dateien  ({format_size(total_size)})")
                self.delete_btn.configure(state="normal")
                self.status_var.set(
                    f"{len(files)} Backup-Dateien gefunden ({format_size(total_size)})"
                )

            self.parent.after(0, update_ui)

        except Exception as e:
            self.parent.after(0, lambda: self._log(f"FEHLER: {e}"))
            self.parent.after(0, lambda: self.status_var.set(f"Fehler: {e}"))
        finally:
            self.parent.after(0, lambda: self.scan_btn.configure(state="normal"))

    def _delete(self):
        if not self.found_files:
            return

        total_size = format_size(sum(f.stat().st_size for f in self.found_files))
        count = len(self.found_files)

        if not messagebox.askyesno(
            "Backup-Dateien loeschen",
            f"{count} Dateien ({total_size}) loeschen?\n\n"
            f"Dies betrifft nur .bak und .peak Dateien.",
        ):
            return

        deleted, freed = delete_backup_files(self.found_files)
        self._log(f"\n{deleted} Dateien geloescht ({format_size(freed)} freigegeben)")
        self.found_files = []
        self.delete_btn.configure(state="disabled")
        self.status_var.set(f"Fertig! {deleted} Dateien geloescht ({format_size(freed)})")
