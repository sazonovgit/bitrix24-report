from report_generator.config import COLUMN_KEYS, AppConfig, load_config, save_config


def test_load_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    cfg = load_config()
    assert cfg.columns == list(COLUMN_KEYS)
    assert cfg.year >= 2000
    cfg.webhook_url = "https://portal.bitrix24.ru/rest/1/abc/"
    cfg.columns = ["title", "company"]
    save_config(cfg)
    loaded = load_config()
    assert loaded.webhook_url.endswith("/abc/")
    assert loaded.columns == ["title", "company"]


def test_unknown_columns_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    save_config(AppConfig(columns=["title", "nope", "company"]))
    loaded = load_config()
    assert loaded.columns == ["title", "company"]
