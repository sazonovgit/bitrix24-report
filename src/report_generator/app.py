"""Десктоп-окно отчёта Модули / План-Факт."""

from __future__ import annotations

import os
import sys
import threading
import traceback
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from report_generator.bitrix import BitrixClient, BitrixClientError, parse_webhook_url
from report_generator.config import (
    COLUMN_KEYS,
    AppConfig,
    config_path,
    default_output_path,
    load_config,
    mapping_path,
    save_config,
)
from report_generator.excel import write_report
from report_generator.mapping import discover_schema
from report_generator.models import COLUMN_LABELS
from report_generator.report import build_report


APP_TITLE = "Отчёт Битрикс24: Модули / План-Факт"
LABEL_FONT = ("Segoe UI", 13)
BODY_FONT = ("Segoe UI", 13)
TITLE_FONT = ("Segoe UI", 22, "bold")


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("820x680")
        self.minsize(760, 620)
        ctk.set_appearance_mode("system")
        ctk.set_default_color_theme("blue")

        self.config_data = load_config()
        self._busy = False

        current_year = date.today().year
        year = self.config_data.year or current_year
        self.webhook_var = ctk.StringVar(value=self.config_data.webhook_url)
        self.year_var = ctk.StringVar(value=str(year))
        self.output_var = ctk.StringVar(value=self.config_data.output_path)
        self.status_var = ctk.StringVar(value="Укажите год, колонки и путь — затем сформируйте отчёт.")
        self.column_vars = {
            key: ctk.BooleanVar(value=key in self.config_data.columns)
            for key in COLUMN_KEYS
        }

        self._build_ui()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        tabs = ctk.CTkTabview(self)
        tabs.grid(row=0, column=0, sticky="nsew", padx=16, pady=16)
        tabs.add("Отчёт")
        tabs.add("Настройки")
        self.tabs = tabs

        self._build_main_tab(tabs.tab("Отчёт"))
        self._build_settings_tab(tabs.tab("Настройки"))

    def _build_main_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(2, weight=1)

        header = ctk.CTkLabel(parent, text=APP_TITLE, font=TITLE_FONT)
        header.grid(row=0, column=0, sticky="w", pady=(8, 4))

        hint = ctk.CTkLabel(
            parent,
            text="Данные берутся из смарт-процесса «Модули» и вкладок планируемых / фактических продаж.",
            font=("Segoe UI", 13),
            text_color=("gray30", "gray70"),
            wraplength=740,
            justify="left",
        )
        hint.grid(row=1, column=0, sticky="w", pady=(0, 12))

        form = ctk.CTkFrame(parent)
        form.grid(row=2, column=0, sticky="nsew")
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Год", font=LABEL_FONT).grid(
            row=0, column=0, sticky="w", padx=16, pady=(16, 8)
        )
        years = [str(value) for value in range(date.today().year - 5, date.today().year + 4)]
        self.year_menu = ctk.CTkComboBox(
            form,
            values=years,
            variable=self.year_var,
            width=140,
            font=BODY_FONT,
            command=self._on_year_changed,
        )
        self.year_menu.grid(row=0, column=1, sticky="w", padx=(0, 16), pady=(16, 8))

        ctk.CTkLabel(form, text="Поля отчёта", font=LABEL_FONT).grid(
            row=1, column=0, sticky="nw", padx=16, pady=8
        )
        checks = ctk.CTkFrame(form, fg_color="transparent")
        checks.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=8)
        for index, key in enumerate(COLUMN_KEYS):
            box = ctk.CTkCheckBox(
                checks,
                text=COLUMN_LABELS[key],
                variable=self.column_vars[key],
                font=BODY_FONT,
            )
            box.grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 24), pady=4)

        ctk.CTkLabel(form, text="Файл отчёта", font=LABEL_FONT).grid(
            row=2, column=0, sticky="w", padx=16, pady=8
        )
        path_row = ctk.CTkFrame(form, fg_color="transparent")
        path_row.grid(row=2, column=1, sticky="ew", padx=(0, 16), pady=8)
        path_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(path_row, textvariable=self.output_var, font=BODY_FONT).grid(
            row=0, column=0, sticky="ew"
        )
        ctk.CTkButton(path_row, text="Обзор…", width=110, command=self.on_pick_output).grid(
            row=0, column=1, padx=(8, 0)
        )

        self.generate_button = ctk.CTkButton(
            form,
            text="Сформировать отчет",
            width=220,
            height=36,
            command=self.on_generate,
        )
        self.generate_button.grid(row=3, column=1, sticky="w", padx=(0, 16), pady=(8, 16))

        footer = ctk.CTkFrame(parent, fg_color="transparent")
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        footer.grid_columnconfigure(0, weight=1)
        self.status_label = ctk.CTkLabel(
            footer, textvariable=self.status_var, font=BODY_FONT, anchor="w", wraplength=700
        )
        self.status_label.grid(row=0, column=0, sticky="w")

    def _build_settings_tab(self, parent: ctk.CTkFrame) -> None:
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        form = ctk.CTkScrollableFrame(parent)
        form.grid(row=0, column=0, sticky="nsew")
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Подключение к Битрикс24", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(8, 8)
        )
        ctk.CTkLabel(form, text="URL вебхука", font=LABEL_FONT, width=170, anchor="w").grid(
            row=1, column=0, sticky="w", pady=4
        )
        ctk.CTkEntry(form, textvariable=self.webhook_var, font=BODY_FONT, show="").grid(
            row=1, column=1, sticky="ew", pady=4
        )
        hint = ctk.CTkLabel(
            form,
            text="Разработчикам → Другое → Входящий вебхук. Нужно право CRM (чтение).",
            font=("Segoe UI", 12),
            text_color=("gray30", "gray70"),
        )
        hint.grid(row=2, column=1, sticky="w", pady=(0, 10))

        path_row = ctk.CTkFrame(parent, fg_color="transparent")
        path_row.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        path_row.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(path_row, text="Файл настроек", font=LABEL_FONT, width=170, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        self.config_path_label = ctk.CTkLabel(
            path_row,
            text=str(config_path()),
            font=("Segoe UI", 12),
            anchor="w",
            justify="left",
            wraplength=480,
        )
        self.config_path_label.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkButton(path_row, text="Открыть папку", width=140, command=self.on_open_config_folder).grid(
            row=0, column=2
        )

        buttons = ctk.CTkFrame(parent, fg_color="transparent")
        buttons.grid(row=2, column=0, sticky="e", pady=(10, 0))
        ctk.CTkButton(
            buttons, text="Обновить схему полей", width=180, command=self.on_refresh_schema
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(buttons, text="Сохранить настройки", command=self.on_save_settings).pack(
            side="right"
        )

    def _selected_year(self) -> int:
        try:
            year = int(str(self.year_var.get()).strip())
        except ValueError as exc:
            raise BitrixClientError("Укажите год числом, например 2026.") from exc
        if year < 2000 or year > 2100:
            raise BitrixClientError("Год должен быть в диапазоне 2000–2100.")
        return year

    def _selected_columns(self) -> list[str]:
        return [key for key in COLUMN_KEYS if self.column_vars[key].get()]

    def _collect_config(self) -> AppConfig:
        try:
            year = self._selected_year()
        except BitrixClientError:
            year = date.today().year
        return AppConfig(
            webhook_url=self.webhook_var.get().strip(),
            output_path=self.output_var.get().strip(),
            year=year,
            columns=self._selected_columns() or list(COLUMN_KEYS),
        )

    def _on_year_changed(self, _value: str | None = None) -> None:
        try:
            year = self._selected_year()
        except BitrixClientError:
            return
        current = Path(self.output_var.get().strip() or ".")
        suggested = default_output_path(year)
        if not current.name or current.name.startswith("Прайс_ПланФакт_"):
            folder = current.parent if current.suffix else (current if current.exists() else suggested.parent)
            self.output_var.set(str(folder / suggested.name))

    def on_save_settings(self) -> None:
        cfg = self._collect_config()
        if cfg.webhook_url:
            try:
                parse_webhook_url(cfg.webhook_url)
            except BitrixClientError as exc:
                messagebox.showerror("Настройки", str(exc))
                return
        save_config(cfg)
        self.config_data = cfg
        saved = config_path()
        self.status_var.set(f"Настройки сохранены: {saved}")
        messagebox.showinfo("Настройки", f"Сохранено в файл:\n{saved}")

    def on_open_config_folder(self) -> None:
        folder = config_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(folder)  # noqa: S606

    def on_pick_output(self) -> None:
        try:
            year = self._selected_year()
        except BitrixClientError:
            year = date.today().year
        initial = Path(self.output_var.get().strip() or default_output_path(year))
        path = filedialog.asksaveasfilename(
            title="Куда сохранить отчёт",
            defaultextension=".xlsx",
            filetypes=[("Книга Excel", "*.xlsx"), ("Все файлы", "*.*")],
            initialdir=str(initial.parent if initial.parent.exists() else Path.home()),
            initialfile=initial.name or default_output_path(year).name,
        )
        if path:
            self.output_var.set(path)

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.generate_button.configure(state=state)
        if status is not None:
            self.status_var.set(status)

    def _validate_generate(self) -> AppConfig | None:
        try:
            year = self._selected_year()
        except BitrixClientError as exc:
            messagebox.showerror("Год", str(exc))
            return None
        columns = self._selected_columns()
        if not columns:
            messagebox.showerror("Поля отчёта", "Выберите хотя бы одну колонку.")
            return None
        output = self.output_var.get().strip()
        if not output:
            messagebox.showerror("Файл", "Укажите путь для сохранения отчёта.")
            return None
        cfg = self._collect_config()
        cfg.year = year
        cfg.columns = columns
        cfg.output_path = output
        try:
            parse_webhook_url(cfg.webhook_url)
        except BitrixClientError as exc:
            messagebox.showerror("Вебхук", str(exc))
            self.tabs.set("Настройки")
            return None
        return cfg

    def on_refresh_schema(self) -> None:
        if self._busy:
            return
        cfg = self._collect_config()
        try:
            year = self._selected_year()
            parse_webhook_url(cfg.webhook_url)
        except BitrixClientError as exc:
            messagebox.showerror("Схема полей", str(exc))
            self.tabs.set("Настройки")
            return

        self._set_busy(True, "Обновление схемы полей Битрикс24…")

        def worker() -> None:
            try:
                client = BitrixClient(cfg.webhook_url)
                schema = discover_schema(client, year, force=True)
            except BitrixClientError as exc:
                message = str(exc)
                self.after(0, lambda msg=message: self._on_schema_error(msg))
            except Exception:
                traceback.print_exc()
                self.after(
                    0,
                    lambda: self._on_schema_error(
                        "Не удалось обновить схему полей. Подробности в консоли."
                    ),
                )
            else:
                self.after(0, lambda s=schema: self._on_schema_ok(s))

        threading.Thread(target=worker, daemon=True).start()

    def _on_schema_ok(self, schema) -> None:
        save_config(self._collect_config())
        self._set_busy(
            False,
            f"Схема обновлена: {schema.modules.title}, "
            f"{schema.planned.title or 'нет плана'}, {schema.actual.title or 'нет факта'}. "
            f"Кэш: {mapping_path()}",
        )
        messagebox.showinfo("Схема полей", "Схема смарт-процессов и полей года сохранена.")

    def _on_schema_error(self, message: str) -> None:
        self._set_busy(False, message)
        messagebox.showerror("Схема полей", message)

    def on_generate(self) -> None:
        if self._busy:
            return
        cfg = self._validate_generate()
        if cfg is None:
            return

        save_config(cfg)
        self.config_data = cfg
        self._set_busy(True, "Подключение к Битрикс24…")

        def worker() -> None:
            try:
                client = BitrixClient(cfg.webhook_url)

                def progress(message: str) -> None:
                    self.after(0, lambda msg=message: self.status_var.set(msg))

                progress("Поиск смарт-процессов и полей года…")
                schema = discover_schema(client, cfg.year, force=False)
                rows = build_report(client, schema, cfg.year, progress=progress)
                if not rows:
                    raise BitrixClientError(
                        "Нет строк для отчёта: у продаж не заполнена компания "
                        "или не найдены связанные модули."
                    )
                progress(f"Запись Excel ({len(rows)} строк)…")
                path = write_report(
                    Path(cfg.output_path),
                    rows,
                    year=cfg.year,
                    columns=cfg.columns,
                )
            except BitrixClientError as exc:
                message = str(exc)
                self.after(0, lambda msg=message: self._on_generate_error(msg))
            except Exception as exc:
                traceback.print_exc()
                message = str(exc)
                self.after(0, lambda msg=message: self._on_generate_error(msg))
            else:
                self.after(0, lambda p=path, n=len(rows): self._on_generate_ok(p, n))

        threading.Thread(target=worker, daemon=True).start()

    def _on_generate_ok(self, path: Path, count: int) -> None:
        self._set_busy(False, f"Готово: {count} строк → {path}")
        messagebox.showinfo("Готово", f"Отчёт сохранён:\n{path}\n\nСтрок: {count}")

    def _on_generate_error(self, message: str) -> None:
        self._set_busy(False, "Не удалось сформировать отчёт.")
        messagebox.showerror("Ошибка", message)


def main() -> None:
    if sys.platform == "win32":
        try:
            from ctypes import windll

            windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    app = App()
    app.mainloop()
