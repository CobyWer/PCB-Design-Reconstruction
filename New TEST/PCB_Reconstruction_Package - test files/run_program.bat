@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0launch.py"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        py -3 "%~dp0launch.py"
    ) else (
        python "%~dp0launch.py"
    )
)
if errorlevel 1 (
    echo.
    echo The program did not finish. Read the error above.
)
echo.
pause
