"""Локальные настройки приложения (вебхук и путь отчёта)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path


APP_DIR_NAME = "bitrix24-report"
COLUMN_KEYS = (
    "title",
    "year",
    "deal_id",
    "company",
    "price_po",
    "price_impl",
    "amount",
    "plan_fact",
)


@dataclass
class AppConfig:
    webhook_url: str = ""
    output_path: str = ""
    year: int = 0
    columns: list[str] = field(default_factory=lambda: list(COLUMN_KEYS))


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / ".config")
    path = Path(base) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def mapping_path() -> Path:
    return config_dir() / "mapping.json"


def default_output_dir() -> Path:
    documents = Path.home() / "Documents"
    return documents if documents.exists() else Path.home()


def default_output_path(year: int | None = None) -> Path:
    year = year or date.today().year
    stamp = date.today().strftime("%d_%m_%Y")
    return default_output_dir() / f"Прайс_ПланФакт_{year}_{stamp}.xlsx"


def load_config() -> AppConfig:
    path = config_path()
    created = not path.exists()
    data: dict = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}

    known = {item.name for item in fields(AppConfig)}
    filtered = {key: value for key, value in data.items() if key in known}
    cfg = AppConfig(**filtered)

    env_url = os.environ.get("BITRIX_WEBHOOK_URL", "").strip()
    if env_url and not cfg.webhook_url:
        cfg.webhook_url = env_url

    if not cfg.year:
        cfg.year = date.today().year

    columns = [key for key in cfg.columns if key in COLUMN_KEYS]
    cfg.columns = columns or list(COLUMN_KEYS)

    if not cfg.output_path:
        cfg.output_path = str(default_output_path(cfg.year))

    if created:
        save_config(cfg)
    return cfg


def save_config(cfg: AppConfig) -> None:
    path = config_path()
    path.write_text(
        json.dumps(asdict(cfg), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
