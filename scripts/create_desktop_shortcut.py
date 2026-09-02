"""Создаёт ярлык на рабочем столе: pythonw -m report_generator."""

from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path

from report_generator.icon import write_app_icon


SHORTCUT_NAME = "Отчёт Битрикс24.lnk"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def desktop_dir() -> Path:
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    desktop = home / "Desktop"
    if desktop.exists():
        return desktop
    return Path.home() / "Desktop"


def create_shortcut() -> Path:
    root = project_root()
    pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.exists():
        raise SystemExit(
            f"Не найден {pythonw}. Сначала: python -m venv .venv; "
            ".\\.venv\\Scripts\\Activate.ps1; pip install -e ."
        )

    icon = write_app_icon(root / "assets" / "app.ico")
    link = desktop_dir() / SHORTCUT_NAME
    icon_line = (
        f'$Shortcut.IconLocation = {str(icon.resolve())!r}'
        if icon.exists()
        else ""
    )
    script = f"""
$Wsh = New-Object -ComObject WScript.Shell
$Shortcut = $Wsh.CreateShortcut({str(link)!r})
$Shortcut.TargetPath = {str(pythonw.resolve())!r}
$Shortcut.Arguments = '-m report_generator'
$Shortcut.WorkingDirectory = {str(root)!r}
$Shortcut.WindowStyle = 1
$Shortcut.Description = 'Отчёт Модули / План-Факт из Битрикс24'
{icon_line}
$Shortcut.Save()
Write-Output {str(link)!r}
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-EncodedCommand",
            encoded,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    print(result.stdout.strip() or f"Ярлык создан: {link}")
    if result.stderr.strip():
        print(result.stderr, file=sys.stderr)
    return link


if __name__ == "__main__":
    create_shortcut()
