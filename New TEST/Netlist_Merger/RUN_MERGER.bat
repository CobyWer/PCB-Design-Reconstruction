@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if not errorlevel 1 (
    py -3 netlistmerge.py
) else (
    python netlistmerge.py
)
if errorlevel 1 (
    echo Merger failed. Read the error above.
) else (
    echo Finished. Open COMPLETE_LOGICAL_NETLIST.txt in this folder.
)
pause
