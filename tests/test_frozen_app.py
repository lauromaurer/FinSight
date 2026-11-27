"""The frozen (PyInstaller) build's self-check, driven as a real process.

Skipped unless FINSIGHT_FROZEN_APP points at a built executable: the release
workflow builds the app and then runs this test against it on each OS, so a
broken build fails the workflow before anything is published. Locally:

    FINSIGHT_FROZEN_APP=dist/FinSight.app/Contents/MacOS/FinSight python -m pytest tests/test_frozen_app.py
"""

import os
import subprocess
from pathlib import Path

import pytest

FROZEN_APP = os.environ.get("FINSIGHT_FROZEN_APP")

pytestmark = pytest.mark.skipif(not FROZEN_APP, reason="set FINSIGHT_FROZEN_APP to a built FinSight executable")


def test_frozen_app_passes_its_self_check_from_another_folder(tmp_path):
    app = Path(FROZEN_APP).resolve()
    assert app.is_file(), f"no built app at {app}"

    # A windowed Windows build has no console, so the exit code is the verdict;
    # subprocess.run still waits for a GUI-subsystem process to finish.
    result = subprocess.run(
        [str(app), "--self-check"],
        cwd=tmp_path,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert list(tmp_path.iterdir()) == []
