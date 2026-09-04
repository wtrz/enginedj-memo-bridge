@echo off
setlocal
cd /d "%~dp0"
py -m pip install -e ".[dev]"
pyinstaller --noconfirm --clean --windowed --name Engine-DNS3700-Sync --paths src src\engine_dns3700_sync\__main__.py
endlocal
