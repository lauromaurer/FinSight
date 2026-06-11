@echo off
setlocal

if not exist ".venv\Scripts\python.exe" (
    echo Missing .venv. Create it with: python -m venv .venv
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name "Cashflow Sankey" --icon "assets\logo.ico" --add-data "assets;assets" desktop_app.py