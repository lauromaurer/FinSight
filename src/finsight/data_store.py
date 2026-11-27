"""The data store: everything FinSight keeps on disk, under one root folder."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping

from finsight.finsight_core import DEFAULT_RULES, load_default_categories
from finsight.month_analysis import OTHER, ImportOverrides, rule_for_merchant


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
    try:
        store.migrate_from(old_data_folders())
    except (OSError, ValueError):
        pass  # A failed migration must never stop FinSight from starting.
    return store


def header_fingerprint(columns: Iterable[object]) -> str:
    """Identify a bank format by its CSV header row (column names, in order).

    Surrounding whitespace and letter case are ignored.
    """
    normalized = "\x1f".join(str(column).strip().casefold() for column in columns)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


class InvalidRuleError(ValueError):
    """A Rule whose match text isn't a valid regular expression. `row` is its 0-based index."""

    def __init__(self, row: int, pattern: str, reason: str) -> None:
        super().__init__(f"Rule {row + 1} ({pattern!r}): {reason}")
        self.row = row
        self.pattern = pattern
        self.reason = reason


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


def _valid_rules(rules: list[dict[str, str]]) -> list[dict[str, str]]:
    """Drop Rules whose match text isn't a valid regular expression (old versions skipped them)."""
    valid = []
    for rule in rules:
        try:
            re.compile(rule["pattern"], flags=re.IGNORECASE)
        except re.error:
            continue
        valid.append(rule)
    return valid


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
        """Saved Rules (possibly none), or the starter Rules when no Rules file exists yet
        (or it is unreadable)."""
        data = _read_json(self.rules_path)
        if not isinstance(data, list):
            return [dict(rule) for rule in DEFAULT_RULES]
        return _clean_rules(data)

    def save_rules(self, rules: list[dict[str, str]]) -> None:
        """Save Rules. Raises InvalidRuleError (saving nothing) if any pattern is invalid regex."""
        for row, rule in enumerate(rules):
            try:
                re.compile(rule["pattern"], flags=re.IGNORECASE)
            except re.error as exc:
                raise InvalidRuleError(row, rule["pattern"], str(exc)) from None
        self._write_json(self.rules_path, rules)

    def load_categories(self) -> list[str]:
        """Saved Categories (possibly none), sorted; the bundled default Categories when
        no Categories file exists yet (or it is unreadable)."""
        data = _read_json(self.categories_path)
        if not isinstance(data, list):
            data = load_default_categories()
        return sorted(dict.fromkeys(str(item).strip() for item in data if str(item).strip()))

    def save_categories(self, categories: list[str]) -> None:
        cleaned = sorted(dict.fromkeys(str(item).strip() for item in categories if str(item).strip()))
        self._write_json(self.categories_path, cleaned)

    def categorize_merchant(self, merchant: str, category: str) -> list[dict[str, str]]:
        """Review: file a Merchant under a Category by saving a literal Rule for it.

        Replaces any earlier Rule for that same Merchant, saves a new Category
        (Other is always available and never saved), and returns the saved Rules.
        """
        rule = rule_for_merchant(merchant.strip(), category.strip())
        rules = [r for r in self.load_rules() if r["pattern"] != rule["pattern"]]
        rules.append(rule)
        self.save_rules(rules)
        categories = self.load_categories()
        if rule["category"] != OTHER and rule["category"] not in categories:
            self.save_categories([*categories, rule["category"]])
        return rules

    def rename_category(self, old: str, new: str) -> list[dict[str, str]]:
        """Rename a Category, moving every Rule that files into it. Returns the saved Rules.

        Renaming onto an existing Category merges the two.
        """
        old, new = old.strip(), new.strip()
        rules = [{**rule, "category": new} if rule["category"] == old else rule for rule in self.load_rules()]
        self.save_rules(rules)
        categories = [new if category == old else category for category in self.load_categories()]
        self.save_categories([category for category in [*categories, new] if category != OTHER])
        return rules

    def remove_category(self, name: str) -> list[dict[str, str]]:
        """Remove a Category and the Rules that file into it, so their Merchants
        go back to Review. Returns the saved Rules."""
        name = name.strip()
        rules = [rule for rule in self.load_rules() if rule["category"] != name]
        self.save_rules(rules)
        self.save_categories([category for category in self.load_categories() if category != name])
        return rules

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
            if destination.exists():
                continue
            if destination == self.rules_path:
                rules = _valid_rules(_clean_rules(_read_json(path)))
                if rules:
                    self.save_rules(rules)
            else:
                _write_atomically(destination, path.read_bytes())
        return bool(files)

    def _copy_legacy_rules(self, folder: Path) -> bool:
        for candidate in [folder / "rules.json", *sorted(folder.glob("rules-*.json"))]:
            rules = _valid_rules(_clean_rules(_read_json(candidate))) if candidate.is_file() else []
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

    def remember_import_overrides(self, columns: Iterable[object], overrides: ImportOverrides) -> None:
        """Remember Check your columns choices for the bank format with this header row.

        `columns` is the header as FinSight detects it without overrides, so the
        next Import of the same format finds these choices again.
        """
        data = {key: value for key, value in asdict(overrides).items() if value is not None}
        if "text_columns" in data:
            data["text_columns"] = list(data["text_columns"])
        self.save_import_overrides(header_fingerprint(columns), data)

    def remembered_import_overrides(self, columns: Iterable[object]) -> ImportOverrides | None:
        """The choices remembered for the bank format with this header row, or None."""
        data = self.import_overrides(header_fingerprint(columns))
        if data is None:
            return None
        known = {f.name for f in fields(ImportOverrides)}
        values = {key: value for key, value in data.items() if key in known}
        if not values:
            return None
        try:
            if values.get("text_columns") is not None:
                values["text_columns"] = tuple(str(c) for c in values["text_columns"])
            if values.get("header_row") is not None:
                values["header_row"] = int(values["header_row"])
        except (TypeError, ValueError):
            return None
        return ImportOverrides(**values)

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
