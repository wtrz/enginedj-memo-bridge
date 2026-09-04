@echo off
setlocal
cd /d "%~dp0"
py -m pip install -e .
py -m engine_dns3700_sync
endlocal
