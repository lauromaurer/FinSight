#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv. Create it with: python3 -m venv .venv"
  exit 1
fi

".venv/bin/python" -m PyInstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name "FinSight" \
  --icon "assets/logo.icns" \
  --add-data "assets:assets" \
  --add-data "default_categories.json:." \
  desktop_app.py

mkdir -p release
rm -f "release/FinSight macOS.zip"

(
  cd dist
  zip -qry "../release/FinSight macOS.zip" "FinSight.app"
)

echo "Built dist/FinSight.app"
echo "Created release/FinSight macOS.zip"
