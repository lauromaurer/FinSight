#!/usr/bin/env bash
# Hand-run macOS build: the shared FinSight.spec, then a zip in release/.
# Releases are normally built by CI on a v* tag (.github/workflows/release.yml).
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -x ".venv/bin/python" ]; then
  echo "Missing .venv. Create it with: python3 -m venv .venv"
  exit 1
fi

".venv/bin/python" -m PyInstaller --noconfirm --clean FinSight.spec

mkdir -p release
rm -f "release/FinSight macOS.zip"
ditto -c -k --keepParent "dist/FinSight.app" "release/FinSight macOS.zip"

echo "Built dist/FinSight.app"
echo "Created release/FinSight macOS.zip"
