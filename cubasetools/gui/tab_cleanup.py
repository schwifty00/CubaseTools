"""Audio Cleanup tab - migrated from standalone cubase_cleanup.py."""

import threading
import customtkinter as ctk
from pathlib import Path
from tkinter import filedialog, messagebox

from cubasetools.gui import theme
from cubasetools.cleanup.audio_cleanup import (
    analyze_project,
    delete_files,
    find_all_projects,
    is_single_project,
    move_files_to_unused,
)
from cubasetools.utils.config import DEFAULT_SCAN_PATH
from cubasetools.utils.file_utils import format_size


class CleanupTab:
    """Audio cleanup tab with project analysis and unused file management."""

    def __init__(self, parent: ctk.CTkFrame):
        self.parent = parent
        self.unused_entries: list[tuple[Path, Path]] = []
        self._build_ui()

    def _build_ui(self):
        # Folder selection
        folder_frame = ctk.CTkFrame(self.parent, fg_color="transparent")
        folder_frame.pack(fill="x", padx=15, pady=(15, 5))

        ctk.CTkLabel(
            folder_frame,
            text="Projekt-Ordner:",
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY),
        ).pack(side="left", padx=(0, 10))

        self.path_var = ctk.StringVar(value=str(DEFAULT_SCAN_PATH))
        self.path_entry = ctk.CTkEntry(
            folder_frame,
            textvariable=self.path_var,
            font=(theme.FONT_FAMILY, theme.FONT_SIZE_BODY),
            fg_color=theme.BG_TERTIARY,
        )
        self.path_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

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

        self.analyze_btn = ctk.CTkButton(
            btn_frame,
            text="Analysieren",
            command=self._analyze,
            fg_color=theme.ACCENT_DARK,
            hover_color=theme.ACCENT,
            width=140,
        )
        self.analyze_btn.pack(side="left", padx=(0, 10))

        self.move_btn = ctk.CTkButton(
            btn_frame,
            text="Verschieben nach _unused",
            command=self._move,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.ACCENT_SUCCESS,
            width=200,
            state="disabled",
        )
        self.move_btn.pack(side="left", padx=(0, 10))

        self.delete_btn = ctk.CTkButton(
            btn_frame,
            text="Endgueltig loeschen",
            command=self._delete,
            fg_color=theme.BG_TERTIARY,
            hover_color=theme.ACCENT_WARNING,
            width=180,
            state="disabled",
        )
        self.delete_btn.pack(side="left")

        # Status
        self.status_var = ctk.StringVar(
            value="Projekt- oder uebergeordneten Ordner auswaehlen und 'Analysieren' klicken"
        )
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

    def _set_action_buttons(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.move_btn.configure(state=state)
        self.delete_btn.configure(state=state)

    def _browse(self):
        folder = filedialog.askdirectory(
            title="Cubase Projekt-Ordner auswaehlen",
            initialdir=str(DEFAULT_SCAN_PATH),
        )
        if folder:
            self.path_var.set(folder)
            self._analyze()

    def _analyze(self):
        path = self.path_var.get().strip()
        if not path:
            messagebox.showwarning("Fehler", "Bitte einen Ordner auswaehlen!")
            return

        target = Path(path)
        if not target.exists():
            messagebox.showerror("Fehler", f"Ordner existiert nicht:\n{path}")
            return

        self._clear_log()
        self._set_action_buttons(False)
        self.unused_entries = []

        # Run analysis in background thread
        self.analyze_btn.configure(state="disabled")
        threading.Thread(
            target=self._run_analysis, args=(target,), daemon=True
        ).start()

    def _run_analysis(self, target: Path):
        try:
            if is_single_project(target):
                self._analyze_single(target)
            else:
                self._analyze_batch(target)
        finally:
            self.parent.after(0, lambda: self.analyze_btn.configure(state="normal"))

    def _analyze_single(self, project_dir: Path):
        try:
            self.parent.after(0, lambda: self.status_var.set("Analysiere Projekt..."))
            self.parent.after(0, lambda: self._log(f"Projekt: {project_dir.name}"))

            used, unused, cpr_name, audio_dir = analyze_project(project_dir)

            for f in unused:
                self.unused_entries.append((f, audio_dir))

            def update_ui():
                self._log(f"Projektdatei: {cpr_name}")
                self._log(f"Audio-Ordner: {audio_dir.name}")
                self._log("")

                total_used = sum(f.stat().st_size for f in used)
                total_unused = sum(f.stat().st_size for f in unused)

                self._log(f"Benutzt:   {len(used):>4} Dateien  ({format_size(total_used)})")
                self._log(f"Unbenutzt: {len(unused):>4} Dateien  ({format_size(total_unused)})")
                self._log("")

                if unused:
                    self._log("Unbenutzte Dateien:")
                    for f in unused:
                        self._log(f"  - {f.name}  ({format_size(f.stat().st_size)})")
                    self._set_action_buttons(True)
                    self.status_var.set(
                        f"{len(unused)} unbenutzte Dateien ({format_size(total_unused)}) "
                        f"- Verschieben oder Loeschen?"
                    )
                else:
                    self._log("Alles sauber! Keine unbenutzten Dateien.")
                    self.status_var.set("Keine unbenutzten Dateien gefunden.")

            self.parent.after(0, update_ui)

        except Exception as e:
            self.parent.after(0, lambda: self._log(f"FEHLER: {e}"))
            self.parent.after(0, lambda: self.status_var.set(f"Fehler: {e}"))

    def _analyze_batch(self, base_dir: Path):
        self.parent.after(0, lambda: self.status_var.set("Suche Cubase-Projekte..."))
        self.parent.after(0, lambda: self._log(f"Suche Cubase-Projekte in: {base_dir}"))
        self.parent.after(0, lambda: self._log(""))

        projects = find_all_projects(base_dir)

        if not projects:
            self.parent.after(0, lambda: self._log("Keine Cubase-Projekte gefunden!"))
            self.parent.after(
                0,
                lambda: self.status_var.set(
                    "Keine Projekte gefunden. Richtigen Ordner ausgewaehlt?"
                ),
            )
            return

        self.parent.after(0, lambda: self._log(f"{len(projects)} Projekt(e) gefunden:"))
        self.parent.after(0, lambda: self._log("-" * 50))

        total_unused_count = 0
        total_unused_size = 0
        projects_with_unused = 0

        for project_dir in projects:
            self.parent.after(
                0, lambda d=project_dir: self.status_var.set(f"Analysiere: {d.name}...")
            )
            try:
                used, unused, cpr_name, audio_dir = analyze_project(project_dir)
                unused_size = sum(f.stat().st_size for f in unused)

                total_unused_count += len(unused)
                total_unused_size += unused_size

                for f in unused:
                    self.unused_entries.append((f, audio_dir))

                if unused:
                    projects_with_unused += 1
                    msg = (
                        f"  {project_dir.name}:  "
                        f"{len(unused)} unbenutzt ({format_size(unused_size)})"
                    )
                else:
                    msg = f"  {project_dir.name}:  sauber"
                self.parent.after(0, lambda m=msg: self._log(m))

            except Exception as e:
                msg = f"  {project_dir.name}:  FEHLER - {e}"
                self.parent.after(0, lambda m=msg: self._log(m))

        # Summary
        tuc = total_unused_count
        tus = total_unused_size
        pwu = projects_with_unused
        np = len(projects)

        def show_summary():
            self._log("")
            self._log("=" * 50)
            self._log(f"Gesamt: {np} Projekte analysiert")
            self._log(f"  Unbenutzte Dateien: {tuc}  ({format_size(tus)})")
            self._log(f"  Projekte mit Muell: {pwu}")

            if self.unused_entries:
                self._set_action_buttons(True)
                self.status_var.set(
                    f"{tuc} unbenutzte Dateien in {pwu} Projekten "
                    f"({format_size(tus)}) - Verschieben oder Loeschen?"
                )
            else:
                self.status_var.set("Alle Projekte sind sauber!")

        self.parent.after(0, show_summary)

    def _move(self):
        if not self.unused_entries:
            return

        count = len(self.unused_entries)
        total_size = format_size(sum(f.stat().st_size for f, _ in self.unused_entries))

        if not messagebox.askyesno(
            "Verschieben bestaetigen",
            f"{count} Dateien ({total_size}) nach _unused/ verschieben?\n\n"
            f"Die Dateien werden NICHT geloescht.",
        ):
            return

        try:
            moved = move_files_to_unused(self.unused_entries)
            self._log(f"\nFertig! {moved} Dateien nach _unused/ verschoben.")
            self._set_action_buttons(False)
            self.unused_entries = []
            self.status_var.set(f"Fertig! {moved} Dateien verschoben ({total_size} freigegeben)")
        except Exception as e:
            self._log(f"FEHLER beim Verschieben: {e}")

    def _delete(self):
        if not self.unused_entries:
            return

        count = len(self.unused_entries)
        total_size = format_size(sum(f.stat().st_size for f, _ in self.unused_entries))

        if not messagebox.askyesno(
            "ACHTUNG - Endgueltig loeschen",
            f"{count} Dateien ({total_size}) ENDGUELTIG loeschen?\n\n"
            f"WARNUNG: Dies kann NICHT rueckgaengig gemacht werden!",
            icon="warning",
        ):
            return

        if not messagebox.askyesno(
            "Letzte Warnung",
            f"WIRKLICH {count} Dateien loeschen?",
            icon="warning",
        ):
            return

        try:
            deleted = delete_files(self.unused_entries)
            self._log(f"\nFertig! {deleted} Dateien geloescht.")
            self._set_action_buttons(False)
            self.unused_entries = []
            self.status_var.set(f"Fertig! {deleted} Dateien geloescht ({total_size} freigegeben)")
        except Exception as e:
            self._log(f"FEHLER beim Loeschen: {e}")
