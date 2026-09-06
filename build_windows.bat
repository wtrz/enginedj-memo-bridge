@echo off
setlocal
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m PyInstaller --noconfirm --clean --windowed --name EngineDJ-Memo-Bridge --icon logo-enginedj-memo-bridge.ico --add-data "logo-enginedj-memo-bridge.png;." --paths src src\enginedj_memo_bridge\__main__.py
endlocal
