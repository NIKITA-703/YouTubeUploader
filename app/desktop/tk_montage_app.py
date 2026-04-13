from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox
import tkinter as tk

import customtkinter as ctk

from app.desktop.package_export import (
    DEFAULT_DESKTOP_EXPORTS_DIR,
    DEFAULT_SHORTS_SCHEDULE_TIMES,
    create_bundle_archive,
    prepare_bundle_paths,
    write_bundle_manifest,
)
from app.desktop.profile import (
    ensure_desktop_app_profile_template,
    load_desktop_app_profile,
    resolve_profile_identity,
)
from app.montage.models import MontageRequest
from app.montage.service import create_montage_video, create_shorts_batch


MAX_LINKS = 10
DEFAULT_QUALITY = "high"
DEFAULT_CREATE_ARCHIVE = True
BG = "#040607"
PANEL = "#0a0f11"
PANEL_ALT = "#0d1416"
FIELD = "#06090b"
ACCENT = "#00f0ff"
ACCENT_HOVER = "#0a2e35"
TEXT = "#ecf7f8"
MUTED = "#7d9297"
BRAND = "#ff5e61"
BRAND_ALT = "#f4c14b"
SUCCESS = "#1af2b3"
DIVIDER = "#12353b"
TITLE_FONT = ("Consolas", 12, "bold")
BODY_FONT = ("Segoe UI", 14)
SMALL_FONT = ("Segoe UI", 12)
MICRO_FONT = ("Consolas", 10, "bold")
CONTROL_SHORTCUT_KEYCODES = {
    65: "select_all",
    67: "copy",
    86: "paste",
    88: "cut",
    89: "redo",
    90: "undo",
}
CONTROL_SHORTCUT_ALIASES = {
    "c": "copy",
    "с": "copy",
    "v": "paste",
    "м": "paste",
    "x": "cut",
    "ч": "cut",
    "a": "select_all",
    "ф": "select_all",
    "z": "undo",
    "я": "undo",
    "y": "redo",
    "н": "redo",
}

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _is_valid_youtube_url(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return (
        normalized.startswith("https://www.youtube.com/")
        or normalized.startswith("https://youtube.com/")
        or normalized.startswith("https://youtu.be/")
    )


def _format_windows_path(value: str | Path) -> str:
    return str(value).replace("/", "\\")


class DesktopMontageApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("YouTubeUploader Desktop Builder")
        self.geometry("1250x790")
        self.minsize(1040, 700)
        self.configure(fg_color=BG)

        self.event_queue: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.link_vars: list[tk.StringVar] = []
        self.link_rows: list[ctk.CTkFrame] = []
        self.entry_history: dict[tk.Widget, dict[str, list[str]]] = {}
        self.last_progress_detail = ""
        self.profile_path = ensure_desktop_app_profile_template()
        self.profile = load_desktop_app_profile(self.profile_path)

        self.title_var = tk.StringVar()
        self.audio_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(
            value=_format_windows_path(self.profile.output_dir or DEFAULT_DESKTOP_EXPORTS_DIR)
        )
        self.profile_status_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Готово")
        self.status_detail_var = tk.StringVar(value="")

        self._build_ui()
        self._configure_shortcuts()
        self._apply_default_title_if_empty()
        self._refresh_profile_status()
        self._refresh_summary()
        self.after(150, self._poll_events)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        header = ctk.CTkFrame(self, fg_color=BG, corner_radius=0, height=68)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_propagate(False)

        brand_wrap = ctk.CTkFrame(header, fg_color="transparent")
        brand_wrap.grid(row=0, column=0, sticky="w", padx=24, pady=(14, 10))
        ctk.CTkLabel(
            brand_wrap,
            text="YOUTUBE",
            font=("Consolas", 28, "bold"),
            text_color=BRAND,
        ).pack(side="left")
        ctk.CTkLabel(
            brand_wrap,
            text="UPLOADER",
            font=("Consolas", 28, "bold"),
            text_color=BRAND_ALT,
        ).pack(side="left")
        ctk.CTkLabel(
            brand_wrap,
            text="SECURE_PANEL // DESKTOP",
            font=MICRO_FONT,
            text_color=MUTED,
        ).pack(side="left", padx=(16, 0), pady=(4, 0))

        ctk.CTkFrame(self, fg_color=ACCENT, height=1, corner_radius=0).grid(row=1, column=0, sticky="new")

        body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        body.grid(row=2, column=0, sticky="nsew", padx=18, pady=18)
        body.grid_columnconfigure(0, weight=3, uniform="main_panels")
        body.grid_columnconfigure(1, weight=2, uniform="main_panels")
        body.grid_rowconfigure(0, weight=1)

        self.left_panel = self._create_panel(body, "BUILD_PANEL")
        self.left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.left_panel.grid_columnconfigure(0, weight=1)

        self.right_panel = self._create_panel(body, "SYSTEM_PANEL")
        self.right_panel.grid(row=0, column=1, sticky="nsew")
        self.right_panel.grid_columnconfigure(0, weight=1)
        self.right_panel.grid_rowconfigure(6, weight=1)
        self.right_panel.bind("<Configure>", lambda _event: self._update_status_wraplength(), add="+")

        self._build_form(self.left_panel)
        self._build_status(self.right_panel)

    def _create_panel(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkFrame:
        panel = ctk.CTkFrame(
            parent,
            fg_color=PANEL,
            corner_radius=0,
            border_width=1,
            border_color=DIVIDER,
        )
        header = ctk.CTkFrame(panel, fg_color=PANEL_ALT, corner_radius=0, height=42)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(header, text=title, font=TITLE_FONT, text_color=ACCENT).pack(
            side="left", padx=16, pady=10
        )
        ctk.CTkLabel(header, text="● ● ●", font=MICRO_FONT, text_color="#3c4448").pack(
            side="right", padx=16
        )
        return panel

    def _build_form(self, parent: ctk.CTkFrame) -> None:
        content = ctk.CTkScrollableFrame(
            parent,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_fg_color=PANEL_ALT,
            scrollbar_button_color=ACCENT_HOVER,
            scrollbar_button_hover_color=ACCENT,
        )
        content.pack(fill="both", expand=True, padx=18, pady=18)
        content.grid_columnconfigure(0, weight=1)
        self._set_scrollable_content_gap(content, 8)

        self._field_label(content, 0, "НАЗВАНИЕ ВИДЕО")
        self.title_entry = self._entry(content, self.title_var)
        self.title_entry.grid(row=1, column=0, sticky="ew")

        self._field_label(content, 2, "БИТ")
        self._path_row(content, 3, self.audio_path_var, self._pick_audio_file)

        self._field_label(content, 4, "ПАПКА ВЫВОДА")
        self._path_row(content, 5, self.output_dir_var, self._pick_output_dir)

        profile_row = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        profile_row.grid(row=6, column=0, sticky="ew", pady=(16, 0))
        profile_row.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            profile_row,
            text="ОТКРЫТЬ ПРОФИЛЬ",
            width=162,
            height=38,
            corner_radius=0,
            fg_color=FIELD,
            hover_color=ACCENT_HOVER,
            border_width=1,
            border_color=DIVIDER,
            text_color=TEXT,
            font=TITLE_FONT,
            command=self._open_profile_json,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            profile_row,
            textvariable=self.profile_status_var,
            text_color=TEXT,
            font=BODY_FONT,
            anchor="w",
        ).grid(row=0, column=1, sticky="ew", padx=(12, 0))

        links_box = ctk.CTkFrame(content, fg_color=PANEL_ALT, corner_radius=0, border_width=1, border_color=DIVIDER)
        links_box.grid(row=7, column=0, sticky="ew", pady=(20, 0))
        links_box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(links_box, text="YOUTUBE ССЫЛКИ", font=TITLE_FONT, text_color=ACCENT).grid(
            row=0, column=0, sticky="w", padx=16, pady=(12, 4)
        )
        self.links_container = ctk.CTkFrame(links_box, fg_color="transparent", corner_radius=0)
        self.links_container.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 12))
        self.links_container.grid_columnconfigure(0, weight=1)
        for _ in range(2):
            self._add_link_row()

        actions = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        actions.grid(row=8, column=0, sticky="ew", pady=(16, 0))
        ctk.CTkButton(
            actions,
            text="ДОБАВИТЬ ССЫЛКУ",
            width=170,
            height=42,
            corner_radius=0,
            fg_color=FIELD,
            hover_color=ACCENT_HOVER,
            border_width=1,
            border_color=ACCENT,
            text_color=ACCENT,
            font=TITLE_FONT,
            command=self._add_link_row,
        ).pack(side="left")
        ctk.CTkLabel(actions, text=f"Максимум {MAX_LINKS} ссылок", text_color=MUTED, font=SMALL_FONT).pack(
            side="left", padx=(12, 0)
        )

        build_actions = ctk.CTkFrame(content, fg_color="transparent", corner_radius=0)
        build_actions.grid(row=9, column=0, sticky="ew", pady=(18, 0))
        self.start_button = ctk.CTkButton(
            build_actions,
            text="СОЗДАТЬ ВИДЕО",
            width=190,
            height=46,
            corner_radius=0,
            fg_color=FIELD,
            hover_color=ACCENT_HOVER,
            border_width=1,
            border_color=ACCENT,
            text_color=ACCENT,
            font=TITLE_FONT,
            command=self._start_build,
        )
        self.start_button.pack(side="left")
        ctk.CTkButton(
            build_actions,
            text="ОТКРЫТЬ ПАПКУ ВЫВОДА",
            width=220,
            height=46,
            corner_radius=0,
            fg_color=FIELD,
            hover_color=ACCENT_HOVER,
            border_width=1,
            border_color=DIVIDER,
            text_color=TEXT,
            font=TITLE_FONT,
            command=self._open_output_dir,
        ).pack(side="left", padx=(12, 0))

    def _build_status(self, parent: ctk.CTkFrame) -> None:
        content = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        content.pack(fill="both", expand=True, padx=18, pady=18)
        content.grid_columnconfigure(0, weight=1)
        content.grid_rowconfigure(6, weight=1)

        ctk.CTkLabel(content, text="SYSTEM_STATUS", font=TITLE_FONT, text_color=ACCENT).grid(
            row=0, column=0, sticky="w"
        )
        self.status_label = ctk.CTkLabel(
            content,
            textvariable=self.status_var,
            font=("Consolas", 22, "bold"),
            text_color=SUCCESS,
            anchor="w",
            justify="left",
        )
        self.status_label.grid(row=1, column=0, sticky="ew", pady=(8, 4))
        self.status_detail_label = ctk.CTkLabel(
            content,
            textvariable=self.status_detail_var,
            font=SMALL_FONT,
            text_color=MUTED,
            justify="left",
            anchor="w",
        )
        self.status_detail_label.grid(row=2, column=0, sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(
            content,
            height=10,
            corner_radius=0,
            fg_color=FIELD,
            progress_color=ACCENT,
        )
        self.progress_bar.grid(row=3, column=0, sticky="ew", pady=(14, 18))
        self.progress_bar.set(0)

        ctk.CTkLabel(content, text="PROFILE", font=TITLE_FONT, text_color=ACCENT).grid(
            row=4, column=0, sticky="w", pady=(0, 8)
        )
        self.profile_large_label = ctk.CTkLabel(
            content,
            text="НЕ ОПРЕДЕЛЁН",
            font=("Consolas", 26, "bold"),
            text_color=TEXT,
            anchor="w",
        )
        self.profile_large_label.grid(row=5, column=0, sticky="ew")

        self.log_widget = ctk.CTkTextbox(
            content,
            wrap="word",
            activate_scrollbars=True,
            corner_radius=0,
            fg_color=FIELD,
            border_width=1,
            border_color=DIVIDER,
            text_color=TEXT,
            font=("Consolas", 12),
        )
        self.log_widget.grid(row=6, column=0, sticky="nsew", pady=(16, 0))
        self.log_widget.configure(state="disabled")
        self.after(0, self._update_status_wraplength)

    def _field_label(self, parent: ctk.CTkFrame, row: int, text: str) -> None:
        ctk.CTkLabel(parent, text=text, font=TITLE_FONT, text_color=ACCENT, anchor="w").grid(
            row=row, column=0, sticky="w", pady=(0, 8)
        )

    def _update_status_wraplength(self) -> None:
        if not hasattr(self, "right_panel"):
            return
        try:
            available_width = max(self.right_panel.winfo_width() - 72, 180)
            if hasattr(self, "status_label"):
                self.status_label.configure(wraplength=available_width)
            if hasattr(self, "status_detail_label"):
                self.status_detail_label.configure(wraplength=available_width)
        except Exception:
            return

    def _entry(self, parent: ctk.CTkFrame, variable: tk.StringVar) -> ctk.CTkEntry:
        entry = ctk.CTkEntry(
            parent,
            textvariable=variable,
            height=42,
            corner_radius=0,
            fg_color=FIELD,
            border_width=1,
            border_color=ACCENT,
            text_color=TEXT,
            font=BODY_FONT,
        )
        self._register_editable_widget(entry)
        return entry

    def _path_row(self, parent: ctk.CTkFrame, row: int, variable: tk.StringVar, callback) -> None:
        wrap = ctk.CTkFrame(parent, fg_color="transparent", corner_radius=0)
        wrap.grid(row=row, column=0, sticky="ew", pady=(0, 16))
        wrap.grid_columnconfigure(0, weight=1)
        border_box = ctk.CTkFrame(wrap, fg_color=ACCENT, corner_radius=0, border_width=0, height=42)
        border_box.grid(row=0, column=0, sticky="ew")
        border_box.grid_columnconfigure(0, weight=1)
        border_box.grid_rowconfigure(0, weight=1)
        border_box.grid_propagate(False)

        inner_box = ctk.CTkFrame(border_box, fg_color=FIELD, corner_radius=0, border_width=0)
        inner_box.grid(row=0, column=0, sticky="nsew", padx=1, pady=1)
        inner_box.grid_columnconfigure(0, weight=1)
        inner_box.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(
            inner_box,
            textvariable=variable,
            text_color=TEXT,
            font=BODY_FONT,
            anchor="w",
        ).grid(row=0, column=0, sticky="nsew", padx=13, pady=0)

        ctk.CTkButton(
            wrap,
            text="ОБЗОР",
            width=96,
            height=42,
            corner_radius=0,
            fg_color=FIELD,
            hover_color=ACCENT_HOVER,
            border_width=1,
            border_color=ACCENT,
            text_color=ACCENT,
            font=TITLE_FONT,
            command=callback,
        ).grid(row=0, column=1, padx=(12, 0))

    def _set_scrollable_content_gap(self, frame: ctk.CTkScrollableFrame, gap: int) -> None:
        try:
            border_spacing = frame._apply_widget_scaling(
                frame._parent_frame.cget("corner_radius") + frame._parent_frame.cget("border_width")
            )
            frame._parent_canvas.grid_configure(
                padx=(border_spacing, frame._apply_widget_scaling(gap)),
                pady=border_spacing,
            )
        except Exception:
            pass

    def _register_editable_widget(self, widget) -> None:
        target = getattr(widget, "_entry", None) or getattr(widget, "_textbox", None) or widget
        try:
            initial_value = target.get()
        except Exception:
            initial_value = ""
        self.entry_history[target] = {"undo": [initial_value], "redo": []}
        target.bind("<Control-KeyPress>", self._control_shortcut_handler)
        target.bind("<KeyRelease>", lambda event: self.after_idle(self._remember_entry_state, event.widget), add="+")
        target.bind("<FocusOut>", lambda event: self._remember_entry_state(event.widget), add="+")

    def _configure_shortcuts(self) -> None:
        return None

    def _control_shortcut_handler(self, event):
        action = CONTROL_SHORTCUT_KEYCODES.get(getattr(event, "keycode", None))
        if not action:
            action = CONTROL_SHORTCUT_ALIASES.get((event.keysym or "").lower())
        if not action:
            return None
        widget = event.widget
        class_name = widget.winfo_class()
        if class_name not in {"Entry", "Text"}:
            return None
        if action in {"copy", "paste", "cut"}:
            virtual = {"copy": "<<Copy>>", "paste": "<<Paste>>", "cut": "<<Cut>>"}[action]
            try:
                widget.event_generate(virtual)
            except Exception:
                return None
            if action != "copy" and class_name == "Entry":
                self.after_idle(self._remember_entry_state, widget)
            return "break"
        if action == "select_all":
            try:
                if class_name == "Text":
                    widget.tag_add("sel", "1.0", "end-1c")
                else:
                    widget.selection_range(0, "end")
            except Exception:
                return None
            return "break"
        if class_name == "Entry":
            return self._entry_undo(widget) if action == "undo" else self._entry_redo(widget)
        try:
            widget.event_generate("<<Undo>>" if action == "undo" else "<<Redo>>")
        except Exception:
            return None
        return "break"

    def _remember_entry_state(self, widget) -> None:
        history = self.entry_history.get(widget)
        if history is None:
            return
        try:
            current = widget.get()
        except Exception:
            return
        if not history["undo"] or history["undo"][-1] != current:
            history["undo"].append(current)
            history["redo"].clear()
            if len(history["undo"]) > 100:
                del history["undo"][:-100]

    def _entry_undo(self, widget) -> str:
        history = self.entry_history.get(widget)
        if not history or len(history["undo"]) <= 1:
            return "break"
        current = history["undo"].pop()
        history["redo"].append(current)
        widget.delete(0, "end")
        widget.insert(0, history["undo"][-1])
        return "break"

    def _entry_redo(self, widget) -> str:
        history = self.entry_history.get(widget)
        if not history or not history["redo"]:
            return "break"
        value = history["redo"].pop()
        history["undo"].append(value)
        widget.delete(0, "end")
        widget.insert(0, value)
        return "break"

    def _pick_audio_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Выбери бит",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac"), ("All files", "*.*")],
        )
        if selected:
            self.audio_path_var.set(_format_windows_path(Path(selected)))
            self._refresh_summary()

    def _pick_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="Выбери папку вывода")
        if selected:
            self.output_dir_var.set(_format_windows_path(Path(selected)))
            self._refresh_summary()

    def _add_link_row(self, value: str = "") -> None:
        if len(self.link_vars) >= MAX_LINKS:
            messagebox.showwarning("Лимит", f"Максимум {MAX_LINKS} ссылок.")
            return
        row_index = len(self.link_vars)
        value_var = tk.StringVar(value=value)
        value_var.trace_add("write", lambda *_: self._refresh_summary())
        row = ctk.CTkFrame(self.links_container, fg_color="transparent", corner_radius=0)
        row.grid(row=row_index, column=0, sticky="ew", pady=6)
        row.grid_columnconfigure(0, weight=1)
        self._entry(row, value_var).grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(
            row,
            text="УДАЛИТЬ",
            width=108,
            height=42,
            corner_radius=0,
            fg_color=FIELD,
            hover_color="#281014",
            border_width=1,
            border_color=DIVIDER,
            text_color=TEXT,
            font=TITLE_FONT,
            command=lambda target=value_var: self._remove_link_row(target),
        ).grid(row=0, column=1, padx=(12, 0))
        self.link_vars.append(value_var)
        self.link_rows.append(row)
        self._refresh_summary()

    def _remove_link_row(self, target_var: tk.StringVar) -> None:
        if len(self.link_vars) <= 1:
            target_var.set("")
            return
        index = self.link_vars.index(target_var)
        self.link_vars.pop(index)
        row = self.link_rows.pop(index)
        row.destroy()
        for idx, existing in enumerate(self.link_rows):
            existing.grid_configure(row=idx)
        self._refresh_summary()

    def _append_log(self, text: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text.rstrip() + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _set_running(self, is_running: bool) -> None:
        self.start_button.configure(state="disabled" if is_running else "normal")

    def _collect_urls(self) -> list[str]:
        return [value for value in ((var.get() or "").strip() for var in self.link_vars) if value]

    def _validate_form(self) -> tuple[str, Path, Path, list[str]]:
        title = (self.title_var.get() or "").strip()
        if not title:
            raise ValueError("Укажи название видео.")
        audio_path = Path((self.audio_path_var.get() or "").strip()).expanduser()
        if not audio_path.exists() or not audio_path.is_file():
            raise ValueError("Файл бита не найден.")
        output_dir = Path((self.output_dir_var.get() or "").strip()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        urls = self._collect_urls()
        if not urls:
            raise ValueError("Добавь хотя бы одну YouTube-ссылку.")
        invalid = [url for url in urls if not _is_valid_youtube_url(url)]
        if invalid:
            raise ValueError(f"Некорректная YouTube-ссылка: {invalid[0]}")
        return title, audio_path.resolve(), output_dir.resolve(), urls

    def _refresh_profile_status(self) -> None:
        username, display_name = resolve_profile_identity(self.title_var.get(), self.profile)
        if username:
            text = f"Профиль: {username}" + (f"  //  Имя: {display_name}" if display_name and display_name != username else "")
        else:
            text = "Профиль не настроен. Fallback возьмёт (prod. ...) из названия."
        self.profile_status_var.set(text)
        self._refresh_summary()

    def _build_default_title(self) -> str:
        producer = (self.profile.username or self.profile.display_name or "").strip() or "kellmi"
        return f'[FREE] АРТИСТ x АРТИСТ TYPE BEAT - "НАЗВАНИЕ" (prod. {producer})'

    def _apply_default_title_if_empty(self) -> None:
        if not (self.title_var.get() or "").strip():
            self.title_var.set(self._build_default_title())

    def _refresh_summary(self) -> None:
        if not hasattr(self, "profile_large_label"):
            return
        username, display_name = resolve_profile_identity(self.title_var.get(), self.profile)
        profile_title = display_name or username or "НЕ ОПРЕДЕЛЁН"
        self.profile_large_label.configure(text=profile_title.upper())

    def _open_profile_json(self) -> None:
        ensure_desktop_app_profile_template(self.profile_path)
        os.startfile(str(self.profile_path))

    def _get_hidden_build_options(self, title: str) -> dict:
        username, display_name = resolve_profile_identity(title, self.profile)
        return {
            "username": username,
            "display_name": display_name,
            "quality": DEFAULT_QUALITY,
            "create_archive": DEFAULT_CREATE_ARCHIVE,
            "cookies_from_browser": (os.getenv("MONTAGE_COOKIES_FROM_BROWSER") or "").strip() or None,
            "cookies_file": (os.getenv("MONTAGE_COOKIES_FILE") or "").strip(),
            "js_runtime": (os.getenv("MONTAGE_JS_RUNTIME") or "").strip() or None,
            "schedule_times": list(DEFAULT_SHORTS_SCHEDULE_TIMES),
        }

    def _start_build(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showinfo("Занято", "Сборка уже запущена.")
            return
        try:
            title, audio_path, output_dir, urls = self._validate_form()
            self.profile = load_desktop_app_profile(self.profile_path)
            build_options = self._get_hidden_build_options(title)
            if not build_options["username"]:
                raise ValueError(
                    "Не удалось определить битмаря. Заполни data/json/desktop_app_profile.json "
                    "или укажи (prod. username) в названии."
                )
        except Exception as error:
            messagebox.showerror("Ошибка валидации", str(error))
            return

        self.progress_bar.set(0)
        self.status_var.set("ПОДГОТАВЛИВАЮ СБОРКУ")
        self.status_detail_var.set(
            f"Профиль={build_options['username']}  //  quality={build_options['quality']}  //  zip=on"
        )
        self.last_progress_detail = ""
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", "end")
        self.log_widget.configure(state="disabled")
        self._set_running(True)

        self.worker_thread = threading.Thread(
            target=self._run_build_worker,
            args=(title, audio_path, output_dir, urls, build_options),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_build_worker(self, title: str, audio_path: Path, output_dir: Path, urls: list[str], build_options: dict) -> None:
        try:
            username = build_options["username"]
            display_name = build_options["display_name"]
            quality = build_options["quality"]
            schedule_times = build_options["schedule_times"]

            bundle_paths = prepare_bundle_paths(output_dir, title)
            self.event_queue.put(("log", {"text": f"Project folder: {bundle_paths.project_dir}"}))
            self.event_queue.put(("log", {"text": f"Profile resolved: username={username!r}, display_name={display_name!r}, quality={quality}, zip={build_options['create_archive']}, shorts_slots={','.join(schedule_times)}"}))
            os.environ["MONTAGE_QUALITY"] = quality

            cookies_from_browser = build_options["cookies_from_browser"]
            cookies_file_raw = build_options["cookies_file"]
            cookies_file = Path(cookies_file_raw).expanduser().resolve() if cookies_file_raw else None
            js_runtime = build_options["js_runtime"]

            request = MontageRequest(
                title=title,
                audio_path=audio_path,
                youtube_urls=urls,
                output_path=bundle_paths.project_dir / "main_video.mp4",
                cookies_from_browser=cookies_from_browser,
                cookies_file=cookies_file,
                js_runtime=js_runtime,
            )

            def progress_callback(phase: str, progress: float, detail: str = "") -> None:
                self.event_queue.put(("progress", {"phase": phase, "progress": progress, "detail": detail}))

            self.event_queue.put(("log", {"text": "Собираю основное видео..."}))
            main_result = create_montage_video(request, username=username, display_name=display_name, progress_callback=progress_callback)
            self.event_queue.put(("log", {"text": f"основное видео готов: {main_result.output_path.name}"}))

            self.event_queue.put(("log", {"text": "Собираю shorts..."}))
            short_results = create_shorts_batch(request, username=username, display_name=display_name, output_dir=bundle_paths.shorts_dir, progress_callback=progress_callback)
            self.event_queue.put(("log", {"text": f"Shorts готовы: {len(short_results)} файл(ов)"}))

            manifest_path = write_bundle_manifest(
                bundle_paths,
                title=title,
                audio_path=audio_path,
                source_urls=urls,
                main_result=main_result,
                short_results=short_results,
                username=username,
                display_name=display_name,
                quality=quality,
                schedule_times=schedule_times,
            )

            archive_path = ""
            if build_options["create_archive"]:
                archive_path = str(create_bundle_archive(bundle_paths))
                self.event_queue.put(("log", {"text": f"Архив готов: {Path(archive_path).name}"}))

            self.event_queue.put(("success", {"manifest_path": str(manifest_path), "archive_path": archive_path}))
        except Exception as error:
            self.event_queue.put(("error", {"message": str(error), "traceback": traceback.format_exc()}))

    def _poll_events(self) -> None:
        while True:
            try:
                event, payload = self.event_queue.get_nowait()
            except queue.Empty:
                break
            if event == "progress":
                phase = payload.get("phase", "")
                detail = payload.get("detail", "")
                progress = float(payload.get("progress", 0.0))
                status_text = phase if not detail else f"{phase} | {detail}"
                self.status_var.set((phase or "СБОРКА").upper())
                self.status_detail_var.set(detail or status_text)
                self.progress_bar.set(max(0.0, min(1.0, progress / 100.0)))
                if detail and detail != self.last_progress_detail:
                    self._append_log(status_text)
                    self.last_progress_detail = detail
            elif event == "log":
                self._append_log(payload.get("text", ""))
            elif event == "success":
                self._set_running(False)
                self.progress_bar.set(1)
                self.status_var.set("СБОРКА ЗАВЕРШЕНА")
                self.status_detail_var.set("Основное видео, shorts и ZIP готовы.")
                self._append_log(f"Manifest: {payload.get('manifest_path')}")
                if payload.get("archive_path"):
                    self._append_log(f"Archive: {payload.get('archive_path')}")
                messagebox.showinfo("Сборка завершена", "Основное видео, shorts и ZIP готовы.")
            elif event == "error":
                self._set_running(False)
                self.status_var.set("СБОРКА УПАЛА")
                self.status_detail_var.set("Подробности есть в логах справа.")
                self._append_log(payload.get("traceback", payload.get("message", "Unknown error")))
                messagebox.showerror("Ошибка сборки", payload.get("message", "Unknown error"))
        self.after(150, self._poll_events)

    def _open_output_dir(self) -> None:
        output_dir = Path((self.output_dir_var.get() or "").strip()).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(output_dir))


def main() -> None:
    app = DesktopMontageApp()
    app.title_var.trace_add("write", lambda *_: app._refresh_profile_status())
    app.audio_path_var.trace_add("write", lambda *_: app._refresh_summary())
    app.output_dir_var.trace_add("write", lambda *_: app._refresh_summary())
    app.mainloop()


if __name__ == "__main__":
    main()
