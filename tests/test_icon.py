from pathlib import Path

from report_generator.icon import write_app_icon


def test_write_app_icon(tmp_path: Path):
    path = write_app_icon(tmp_path / "app.ico")
    data = path.read_bytes()
    assert data[:4] == b"\x00\x00\x01\x00"
    assert path.stat().st_size > 40
