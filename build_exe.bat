@echo off
cd /d "%~dp0"

rd /S /Q build
rd /S /Q dist

set MAIN_PY_SCRIPT=copier.py
set FOLDER_TO_INCLUDE=.\

pyinstaller --noconfirm --log-level=INFO ^
            --onefile ^
            --name "resumeable_file_copier" ^
            "%MAIN_PY_SCRIPT%"

echo.
echo PyInstaller has finished.