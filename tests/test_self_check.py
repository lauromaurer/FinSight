"""The app's self-check mode, driven as a real process.

Each run starts from an unrelated working directory, which is how the app is
launched from Finder/Explorer, a shortcut or a terminal.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
APP_SCRIPT = SRC_DIR / "finsight" / "desktop_app.py"


def run_app(args: list[str], cwd: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", **(extra_env or {})}
    return subprocess.run(
        [sys.executable, *args, "--self-check"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_self_check_passes_when_launched_as_a_script_from_another_folder(tmp_path):
    result = run_app([str(APP_SCRIPT)], cwd=tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "self-check ok" in result.stdout.lower()


def test_self_check_passes_when_launched_as_a_module_from_another_folder(tmp_path):
    result = run_app(["-m", "finsight"], cwd=tmp_path, extra_env={"PYTHONPATH": str(SRC_DIR)})

    assert result.returncode == 0, result.stdout + result.stderr
    assert "self-check ok" in result.stdout.lower()


def test_self_check_leaves_the_launch_folder_untouched(tmp_path):
    run_app([str(APP_SCRIPT)], cwd=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_self_check_names_the_data_folder_without_writing_to_it(tmp_path):
    home = tmp_path / "home"
    appdata = tmp_path / "appdata"
    launch = tmp_path / "launch"
    launch.mkdir()
    fake_user = {"HOME": str(home), "USERPROFILE": str(home), "APPDATA": str(appdata), "XDG_DATA_HOME": str(home)}

    result = run_app([str(APP_SCRIPT)], cwd=launch, extra_env=fake_user)

    assert result.returncode == 0, result.stdout + result.stderr
    data_folders = [appdata / "FinSight", home / "Library" / "Application Support" / "FinSight", home / "FinSight"]
    assert any(f"Data folder: {folder}" in result.stdout for folder in data_folders), result.stdout
    assert not any(folder.exists() for folder in data_folders)
    assert list(launch.iterdir()) == []
