$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Error "Не найден $Python. Сначала создайте venv и установите пакет: python -m venv .venv; .\.venv\Scripts\Activate.ps1; pip install -e ."
}
& $Python (Join-Path $PSScriptRoot "create_desktop_shortcut.py")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
