@echo off
setlocal
cd /d "%~dp0"
py -m pip install -e ".[dev]"
pyinstaller --noconfirm --clean --windowed --name EngineDJ-Memo-Bridge --paths src src\enginedj_memo_bridge\__main__.py
endlocal
