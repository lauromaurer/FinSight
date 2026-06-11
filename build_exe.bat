@echo off
setlocal

if not exist ".venv\Scripts\python.exe" (
    echo Missing .venv. Create it with: python -m venv .venv
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name "FinSight" --icon "assets\logo.ico" --add-data "assets;assets" --add-data "default_categories.json;." desktop_app.py