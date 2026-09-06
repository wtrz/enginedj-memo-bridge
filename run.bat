@echo off
setlocal
cd /d "%~dp0"
py -m pip install -e .
py -m enginedj_memo_bridge
endlocal
