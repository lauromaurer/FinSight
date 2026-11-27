@echo off
rem Hand-run Windows build: the shared FinSight.spec, then a zip in release\.
rem Releases are normally built by CI on a v* tag (.github/workflows/release.yml).
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Missing .venv. Create it with: python -m venv .venv
    exit /b 1
)

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean FinSight.spec || exit /b 1

if not exist release mkdir release
powershell -NoProfile -Command "Compress-Archive -Path 'dist\FinSight' -DestinationPath 'release\FinSight Windows.zip' -Force" || exit /b 1

echo Built dist\FinSight\FinSight.exe
echo Created release\FinSight Windows.zip
