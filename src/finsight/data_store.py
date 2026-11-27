"""The data store: everything FinSight keeps on disk, under one root folder."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from finsight.finsight_core import DEFAULT_RULES, load_default_categories


APP_FOLDER_NAME = "FinSight"


def user_data_folder(
    platform: str | None = None,
    environ: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    """The per-user data folder (ADR-0001). Arguments default to the real machine.

    macOS: ~/Library/Application Support/FinSight; Windows: %APPDATA%\\FinSight;
    elsewhere: $XDG_DATA_HOME/FinSight (default ~/.local/share/FinSight).
    """
    platform = sys.platform if platform is None else platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform == "win32":
        appdata = environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
    elif platform == "darwin":
        base = home / "Library" / "Application Support"
    else:
        xdg = environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else home / ".local" / "share"
    return base / APP_FOLDER_NAME


def old_data_folders() -> list[Path]:
    """Where FinSight kept data before ADR-0001: next to the executable, and the cwd."""
    folders = [Path(sys.executable).resolve().parent] if getattr(sys, "frozen", False) else []
    folders.append(Path.cwd())
    return list(dict.fromkeys(folders))


def open_user_store() -> DataStore:
    """The app's store: the per-user data folder, with old data migrated in once."""
    store = DataStore(user_data_folder())
    store.migrate_from(old_data_folders())
    return store


def header_fingerprint(columns: Iterable[object]) -> str:
    """Identify a bank format by its CSV header row (column names, in order).

    Surrounding whitespace and letter case are ignored.
    """
    normalized = "\x1f".join(str(column).strip().casefold() for column in columns)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _clean_rules(data: Any) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []
    rules: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        pattern = str(item.get("pattern", "")).strip()
        category = str(item.get("category", "")).strip()
        if pattern and category:
            rule = {"pattern": pattern, "category": category}
            merchant = str(item.get("merchant", "")).strip()
            if merchant:
                rule["merchant"] = merchant
            rules.append(rule)
    return rules


def _write_atomically(path: Path, data: bytes) -> None:
    """Write to a temp file in the same folder, then rename over the target.

    A crash or error mid-write leaves the previous file untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class DataStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def rules_path(self) -> Path:
        return self.root / "rules.json"

    @property
    def categories_path(self) -> Path:
        return self.root / "categories.json"

    def has_rules(self) -> bool:
        return self.rules_path.exists()

    def load_rules(self) -> list[dict[str, str]]:
        """Saved Rules, or the starter Rules when none are saved (or the file is unreadable)."""
        return _clean_rules(_read_json(self.rules_path)) or [dict(rule) for rule in DEFAULT_RULES]

    def save_rules(self, rules: list[dict[str, str]]) -> None:
        self._write_json(self.rules_path, rules)

    def load_categories(self) -> list[str]:
        """Saved Categories, sorted; the bundled default Categories when none are saved."""
        data = _read_json(self.categories_path)
        if not isinstance(data, list):
            data = load_default_categories()
        return sorted(dict.fromkeys(str(item).strip() for item in data if str(item).strip()))

    def save_categories(self, categories: list[str]) -> None:
        cleaned = sorted(dict.fromkeys(str(item).strip() for item in categories if str(item).strip()))
        self._write_json(self.categories_path, cleaned)

    @property
    def imports_dir(self) -> Path:
        return self.root / "imports"

    def save_import(self, source: str | Path) -> Path:
        """Keep a copy of an Imported CSV in the store; returns the copy's path."""
        source = Path(source)
        destination = self._unique_path(self.imports_dir, source.stem, source.suffix or ".csv")
        _write_atomically(destination, source.read_bytes())
        return destination

    def remember_last_import(self, imported_copy: str | Path) -> None:
        """Point at the Imported CSV copy to reopen on the next launch."""
        relative = Path(imported_copy).resolve().relative_to(self.root.resolve())
        self._write_json(self.root / "last_import.json", {"file": relative.as_posix()})

    def last_import(self) -> Path | None:
        """The last Imported CSV copy, or None if there is none (or it was deleted)."""
        data = _read_json(self.root / "last_import.json")
        if not isinstance(data, dict) or not isinstance(data.get("file"), str):
            return None
        path = self.root / data["file"]
        return path if path.is_file() else None

    def migrate_from(self, old_folders: Iterable[str | Path]) -> bool:
        """Copy data from an old FinSight install into this store, once (ADR-0001).

        `old_folders` are where older versions kept data: the folder next to the
        executable and the working directory. The first one holding a `config/`
        folder (or a legacy `rules.json` / `rules-*.json`) is copied from.
        Nothing happens if the store already has Rules or a migration already ran.
        Existing files are never overwritten. Returns True if anything was copied.
        """
        marker = self.root / "migration.json"
        if marker.exists() or self.has_rules():
            return False
        source = None
        for folder in map(Path, old_folders):
            if self._copy_old_config(folder / "config") or self._copy_legacy_rules(folder):
                source = folder
                break
        self._write_json(marker, {"migrated_from": str(source) if source else None})
        return source is not None

    def _copy_old_config(self, config: Path) -> bool:
        files = [path for path in config.glob("*") if path.is_file()] if config.is_dir() else []
        for path in files:
            destination = self.root / path.name
            if not destination.exists():
                _write_atomically(destination, path.read_bytes())
        return bool(files)

    def _copy_legacy_rules(self, folder: Path) -> bool:
        for candidate in [folder / "rules.json", *sorted(folder.glob("rules-*.json"))]:
            rules = _clean_rules(_read_json(candidate)) if candidate.is_file() else []
            if rules:
                self.save_rules(rules)
                return True
        return False

    @property
    def money_flow_dir(self) -> Path:
        return self.root / "money-flow"

    def save_money_flow(self, html: str, name: str) -> Path:
        """Save an exported Money flow HTML page; returns its path."""
        destination = self._unique_path(self.money_flow_dir, f"{name}_money-flow", ".html")
        _write_atomically(destination, html.encode("utf-8"))
        return destination

    @property
    def _overrides_path(self) -> Path:
        return self.root / "import_overrides.json"

    def import_overrides(self, fingerprint: str) -> dict[str, Any] | None:
        """The import overrides remembered for a bank format, or None."""
        data = _read_json(self._overrides_path)
        found = data.get(fingerprint) if isinstance(data, dict) else None
        return found if isinstance(found, dict) else None

    def save_import_overrides(self, fingerprint: str, overrides: dict[str, Any]) -> None:
        """Remember import overrides for a bank format (see `header_fingerprint`)."""
        data = _read_json(self._overrides_path)
        if not isinstance(data, dict):
            data = {}
        data[fingerprint] = overrides
        self._write_json(self._overrides_path, data)

    @staticmethod
    def _unique_path(folder: Path, stem: str, suffix: str) -> Path:
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        candidate = folder / f"{stem}_{stamp}{suffix}"
        counter = 2
        while candidate.exists():
            candidate = folder / f"{stem}_{stamp}_{counter}{suffix}"
            counter += 1
        return candidate

    def _write_json(self, path: Path, data: Any) -> None:
        _write_atomically(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
