from __future__ import annotations

import os
import queue
import threading
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

from app.desktop.package_export import (
    DEFAULT_DESKTOP_EXPORTS_DIR,
    DEFAULT_SHORTS_SCHEDULE_TIMES,
    create_bundle_archive,
    prepare_bundle_paths,
    write_bundle_manifest,
)
from app.desktop.profile import (
    DEFAULT_PROFILE_PATH,
    ensure_desktop_app_profile_template,
    load_desktop_app_profile,
    resolve_profile_identity,
)
from app.montage.models import MontageRequest
from app.montage.service import create_montage_video, create_shorts_batch


MAX_LINKS = 10
DEFAULT_QUALITY = "high"
DEFAULT_CREATE_ARCHIVE = True
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


def _is_valid_youtube_url(value: str) -> bool:
    normalized = (value or "").strip().lower()
    return (
        normalized.startswith("https://www.youtube.com/")
        or normalized.startswith("https://youtube.com/")
        or normalized.startswith("https://youtu.be/")
    )


def _format_windows_path(value: str | Path) -> str:
    return str(value).replace("/", "\\")


class DesktopMontageApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("YouTubeUploader Desktop Builder")
        self.geometry("750x525")
        self.minsize(580, 525)

        self.event_queue: queue.Queue[tuple[str, dict]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.link_vars: list[tk.StringVar] = []
        self.link_row_frames: list[tk.Frame] = []
        self.entry_history: dict[tk.Widget, dict[str, list[str]]] = {}
        self.last_progress_detail = ""
        self.profile_path = ensure_desktop_app_profile_template()
        self.profile = load_desktop_app_profile(self.profile_path)

        self.title_var = tk.StringVar()
        self.audio_path_var = tk.StringVar()
        default_output_dir = self.profile.output_dir or str(DEFAULT_DESKTOP_EXPORTS_DIR)
        self.output_dir_var = tk.StringVar(value=_format_windows_path(default_output_dir))
        self.cookies_from_browser_var = tk.StringVar(value=(os.getenv("MONTAGE_COOKIES_FROM_BROWSER") or "").strip())
        self.cookies_file_var = tk.StringVar(value=(os.getenv("MONTAGE_COOKIES_FILE") or "").strip())
        self.js_runtime_var = tk.StringVar(value=(os.getenv("MONTAGE_JS_RUNTIME") or "").strip())
        self.profile_status_var = tk.StringVar()

        self._build_ui()
        self._configure_shortcuts()
        self._apply_default_title_if_empty()
        self._refresh_profile_status()
        self.after(150, self._poll_events)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root_frame = ttk.Frame(self, padding=12)
        root_frame.grid(row=0, column=0, sticky="nsew")
        root_frame.columnconfigure(0, weight=1)
        root_frame.rowconfigure(4, weight=1)

        form_frame = ttk.LabelFrame(root_frame, text="Проект")
        form_frame.grid(row=0, column=0, sticky="ew")
        form_frame.columnconfigure(1, weight=1)

        self._add_labeled_entry(form_frame, 0, "Название видео", self.title_var)
        self._add_file_picker_row(form_frame, 1, "Бит", self.audio_path_var, self._pick_audio_file, readonly=True)
        self._add_file_picker_row(form_frame, 2, "Папка вывода", self.output_dir_var, self._pick_output_dir, readonly=True)
        profile_row = ttk.Frame(form_frame)
        profile_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        ttk.Button(profile_row, text="Открыть профиль", command=self._open_profile_json).pack(side="left")
        ttk.Label(profile_row, textvariable=self.profile_status_var).pack(side="left", padx=(12, 0))

        links_frame = ttk.LabelFrame(root_frame, text="YouTube ссылки")
        links_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        links_frame.columnconfigure(0, weight=1)
        self.links_container = ttk.Frame(links_frame)
        self.links_container.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.links_container.columnconfigure(0, weight=1)

        links_buttons = ttk.Frame(links_frame)
        links_buttons.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(links_buttons, text="Добавить ссылку", command=self._add_link_row).pack(side="left")
        ttk.Label(links_buttons, text=f"Максимум {MAX_LINKS} ссылок").pack(side="left", padx=(12, 0))

        for _ in range(2):
            self._add_link_row()

        actions_frame = ttk.Frame(root_frame)
        actions_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.start_button = ttk.Button(actions_frame, text="Собрать main + shorts", command=self._start_build)
        self.start_button.pack(side="left")
        ttk.Button(actions_frame, text="Открыть папку вывода", command=self._open_output_dir).pack(side="left", padx=(8, 0))

        status_frame = ttk.LabelFrame(root_frame, text="Статус")
        status_frame.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        status_frame.columnconfigure(0, weight=1)
        status_frame.rowconfigure(2, weight=1)

        self.status_var = tk.StringVar(value="Готово")
        ttk.Label(status_frame, textvariable=self.status_var).grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 4))
        self.progress = ttk.Progressbar(status_frame, mode="determinate", maximum=100)
        self.progress.grid(row=1, column=0, sticky="ew", padx=8)
        self.log_widget = ScrolledText(status_frame, wrap="word", height=5, state="disabled", undo=True)
        self.log_widget.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)

    def _add_labeled_entry(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(8, 8), pady=4)
        self._create_entry(parent, variable).grid(row=row, column=1, columnspan=2, sticky="ew", pady=4, padx=(0, 8))

    def _add_file_picker_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        variable: tk.StringVar,
        callback,
        readonly: bool = False,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(8, 8), pady=4)
        self._create_entry(parent, variable, readonly=readonly).grid(row=row, column=1, sticky="ew", pady=4)
        ttk.Button(parent, text="Обзор", command=callback).grid(row=row, column=2, sticky="e", padx=8, pady=4)

    def _create_entry(self, parent, variable: tk.StringVar, readonly: bool = False) -> ttk.Entry:
        entry = ttk.Entry(parent, textvariable=variable)
        self.entry_history[entry] = {"undo": [variable.get()], "redo": []}
        entry.bind("<KeyRelease>", lambda event: self.after_idle(self._remember_entry_state, event.widget), add="+")
        entry.bind("<FocusOut>", lambda event: self._remember_entry_state(event.widget), add="+")
        if readonly:
            entry.configure(state="readonly")
        return entry

    def _configure_shortcuts(self) -> None:
        self.bind_class("TEntry", "<Control-KeyPress>", self._control_shortcut_handler, add="+")
        self.bind_class("Text", "<Control-KeyPress>", self._control_shortcut_handler, add="+")

    def _make_virtual_event_handler(self, virtual_event: str):
        def _handler(event):
            try:
                event.widget.event_generate(virtual_event)
                if virtual_event in {"<<Paste>>", "<<Cut>>"} and event.widget.winfo_class() == "TEntry":
                    self.after_idle(self._remember_entry_state, event.widget)
            except Exception:
                return None
            return "break"
        return _handler

    def _control_shortcut_handler(self, event):
        keysym = (event.keysym or "").lower()
        action = CONTROL_SHORTCUT_ALIASES.get(keysym)
        if not action:
            return None

        widget_class = event.widget.winfo_class()
        if widget_class not in {"TEntry", "Text"}:
            return None

        if action == "copy":
            return self._make_virtual_event_handler("<<Copy>>")(event)
        if action == "paste":
            return self._make_virtual_event_handler("<<Paste>>")(event)
        if action == "cut":
            return self._make_virtual_event_handler("<<Cut>>")(event)
        if action == "select_all":
            return self._select_all_handler(event)
        if action == "undo":
            if widget_class == "TEntry":
                return self._entry_undo_handler(event)
            return self._make_virtual_event_handler("<<Undo>>")(event)
        if action == "redo":
            if widget_class == "TEntry":
                return self._entry_redo_handler(event)
            return self._make_virtual_event_handler("<<Redo>>")(event)
        return None

    def _remember_entry_state(self, widget) -> None:
        history = self.entry_history.get(widget)
        if history is None:
            return
        current = widget.get()
        undo_stack = history["undo"]
        if not undo_stack or undo_stack[-1] != current:
            undo_stack.append(current)
            if len(undo_stack) > 100:
                del undo_stack[:-100]
            history["redo"].clear()

    def _entry_undo_handler(self, event):
        history = self.entry_history.get(event.widget)
        if history is None:
            return None
        undo_stack = history["undo"]
        redo_stack = history["redo"]
        if len(undo_stack) <= 1:
            return "break"
        current = undo_stack.pop()
        redo_stack.append(current)
        previous = undo_stack[-1]
        event.widget.delete(0, "end")
        event.widget.insert(0, previous)
        return "break"

    def _entry_redo_handler(self, event):
        history = self.entry_history.get(event.widget)
        if history is None:
            return None
        redo_stack = history["redo"]
        if not redo_stack:
            return "break"
        value = redo_stack.pop()
        history["undo"].append(value)
        event.widget.delete(0, "end")
        event.widget.insert(0, value)
        return "break"

    def _select_all_handler(self, event):
        widget = event.widget
        try:
            if isinstance(widget, (tk.Text, ScrolledText)):
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "1.0")
            else:
                widget.selection_range(0, "end")
                widget.icursor("end")
        except Exception:
            return None
        return "break"

    def _pick_audio_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select beat audio",
            filetypes=[("Audio files", "*.mp3 *.wav *.flac"), ("All files", "*.*")],
        )
        if selected:
            self.audio_path_var.set(_format_windows_path(Path(selected)))

    def _pick_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="Select output folder")
        if selected:
            self.output_dir_var.set(_format_windows_path(Path(selected)))

    def _add_link_row(self, value: str = "") -> None:
        if len(self.link_vars) >= MAX_LINKS:
            messagebox.showwarning("Лимит", f"Максимум {MAX_LINKS} ссылок.")
            return

        var = tk.StringVar(value=value)
        row_index = len(self.link_vars)
        frame = ttk.Frame(self.links_container)
        frame.grid(row=row_index, column=0, sticky="ew", pady=2)
        frame.columnconfigure(0, weight=1)

        self._create_entry(frame, var).grid(row=0, column=0, sticky="ew")
        ttk.Button(frame, text="Удалить", command=lambda target_var=var: self._remove_link_row(target_var)).grid(
            row=0,
            column=1,
            padx=(8, 0),
        )

        self.link_vars.append(var)
        self.link_row_frames.append(frame)

    def _remove_link_row(self, target_var: tk.StringVar) -> None:
        if len(self.link_vars) <= 1:
            target_var.set("")
            return

        index = self.link_vars.index(target_var)
        self.link_vars.pop(index)
        frame = self.link_row_frames.pop(index)
        frame.destroy()

        for row_index, existing_frame in enumerate(self.link_row_frames):
            existing_frame.grid_configure(row=row_index)

    def _append_log(self, text: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.insert("end", text.rstrip() + "\n")
        self.log_widget.see("end")
        self.log_widget.configure(state="disabled")

    def _set_running(self, is_running: bool) -> None:
        self.start_button.configure(state="disabled" if is_running else "normal")

    def _collect_urls(self) -> list[str]:
        values = [(var.get() or "").strip() for var in self.link_vars]
        return [value for value in values if value]

    def _validate_form(self) -> tuple[str, Path, Path, list[str]]:
        title = (self.title_var.get() or "").strip()
        if not title:
            raise ValueError("Укажи название видео.")

        audio_path = Path((self.audio_path_var.get() or "").strip()).expanduser()
        if not audio_path.exists() or not audio_path.is_file():
            raise ValueError("Файл бита не найден.")

        output_dir = Path((self.output_dir_var.get() or "").strip()).expanduser()
        if not output_dir:
            raise ValueError("Укажи папку вывода.")
        output_dir.mkdir(parents=True, exist_ok=True)

        urls = self._collect_urls()
        if not urls:
            raise ValueError("Добавь хотя бы одну YouTube-ссылку.")
        if len(urls) > MAX_LINKS:
            raise ValueError(f"Максимум {MAX_LINKS} ссылок.")
        invalid = [url for url in urls if not _is_valid_youtube_url(url)]
        if invalid:
            raise ValueError(f"Некорректная YouTube-ссылка: {invalid[0]}")

        return title, audio_path.resolve(), output_dir.resolve(), urls

    def _refresh_profile_status(self) -> None:
        username, display_name = resolve_profile_identity(self.title_var.get(), self.profile)
        if username:
            self.profile_status_var.set(
                f"Профиль: {username}"
                + (f" | Имя: {display_name}" if display_name and display_name != username else "")
            )
        else:
            self.profile_status_var.set(
                "Профиль не настроен. Fallback возьмёт (prod. ...) из названия."
            )

    def _build_default_title(self) -> str:
        producer = (self.profile.username or self.profile.display_name or "").strip() or "kellmi"
        return f'[FREE] АРТИСТ x АРТИСТ TYPE BEAT - "НАЗВАНИЕ" (prod. {producer})'

    def _apply_default_title_if_empty(self) -> None:
        if not (self.title_var.get() or "").strip():
            self.title_var.set(self._build_default_title())

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
            "cookies_from_browser": (self.cookies_from_browser_var.get() or "").strip() or None,
            "cookies_file": (self.cookies_file_var.get() or "").strip(),
            "js_runtime": (self.js_runtime_var.get() or "").strip() or None,
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

        self.progress["value"] = 0
        self.status_var.set(
            f"Подготавливаю сборку... профиль={build_options['username']} quality={build_options['quality']} zip=on"
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

    def _run_build_worker(
        self,
        title: str,
        audio_path: Path,
        output_dir: Path,
        urls: list[str],
        build_options: dict,
    ) -> None:
        try:
            username = build_options["username"]
            display_name = build_options["display_name"]
            quality = build_options["quality"]
            schedule_times = build_options["schedule_times"]

            bundle_paths = prepare_bundle_paths(output_dir, title)
            self.event_queue.put(("log", {"text": f"Project folder: {bundle_paths.project_dir}"}))
            self.event_queue.put(
                (
                    "log",
                    {
                        "text": (
                            f"Profile resolved: username={username!r}, "
                            f"display_name={display_name!r}, quality={quality}, "
                            f"zip={build_options['create_archive']}, "
                            f"shorts_slots={','.join(schedule_times)}"
                        )
                    },
                )
            )

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
                self.event_queue.put(
                    (
                        "progress",
                        {
                            "phase": phase,
                            "progress": progress,
                            "detail": detail,
                        },
                    )
                )

            self.event_queue.put(("log", {"text": "Собираю main video..."}))
            main_result = create_montage_video(
                request,
                username=username,
                display_name=display_name,
                progress_callback=progress_callback,
            )
            self.event_queue.put(("log", {"text": f"Main video готов: {main_result.output_path.name}"}))

            self.event_queue.put(("log", {"text": "Собираю shorts..."}))
            short_results = create_shorts_batch(
                request,
                username=username,
                display_name=display_name,
                output_dir=bundle_paths.shorts_dir,
                progress_callback=progress_callback,
            )
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

            archive_path = None
            if build_options["create_archive"]:
                archive_path = create_bundle_archive(bundle_paths)
                self.event_queue.put(("log", {"text": f"Архив готов: {archive_path.name}"}))

            self.event_queue.put(
                (
                    "success",
                    {
                        "project_dir": str(bundle_paths.project_dir),
                        "manifest_path": str(manifest_path),
                        "archive_path": str(archive_path) if archive_path else "",
                    },
                )
            )
        except Exception as error:
            self.event_queue.put(
                (
                    "error",
                    {
                        "message": str(error),
                        "traceback": traceback.format_exc(),
                    },
                )
            )

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
                self.status_var.set(status_text)
                self.progress["value"] = progress
                if detail and detail != self.last_progress_detail:
                    self._append_log(status_text)
                    self.last_progress_detail = detail
            elif event == "log":
                self._append_log(payload.get("text", ""))
            elif event == "success":
                self._set_running(False)
                self.progress["value"] = 100
                self.status_var.set("Сборка завершена")
                self._append_log(f"Manifest: {payload.get('manifest_path')}")
                archive_path = payload.get("archive_path", "")
                if archive_path:
                    self._append_log(f"Archive: {archive_path}")
                messagebox.showinfo(
                    "Сборка завершена",
                    "Main video, shorts и export package готовы.",
                )
            elif event == "error":
                self._set_running(False)
                self.status_var.set("Сборка завершилась ошибкой")
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
    app.mainloop()


if __name__ == "__main__":
    main()
