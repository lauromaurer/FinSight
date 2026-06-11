@echo off
setlocal

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -c "import pandas, plotly, PySide6" >nul 2>nul
    if not errorlevel 1 (
        ".venv\Scripts\python.exe" desktop_app.py
        exit /b %errorlevel%
    )
    echo Local .venv is missing dependencies. Falling back to system Python.
)

python -c "import pandas, plotly, PySide6" >nul 2>nul
if errorlevel 1 (
    echo Missing dependencies. Run: pip install -r requirements.txt
    exit /b 1
) else (
    python desktop_app.py
)
