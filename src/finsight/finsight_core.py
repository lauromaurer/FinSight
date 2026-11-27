from __future__ import annotations

from pathlib import Path
import json
import sys


APP_NAME = "FinSight"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
CONFIG_DIR = APP_DIR / "config"
RULES_PATH = CONFIG_DIR / "rules.json"
CATEGORIES_PATH = CONFIG_DIR / "categories.json"
# Read-only files shipped with the app (assets/, default_categories.json):
# the PyInstaller bundle when frozen, else the repository root. Never the cwd.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
DEFAULT_CATEGORIES_PATH = BUNDLE_DIR / "default_categories.json"
PLOTS_DIR = APP_DIR / "generated Plots"
UPLOADS_DIR = APP_DIR / "uploaded CSV files"

DEFAULT_CATEGORIES = ["P2P", "Transport", "Groceries", "Food & Drink"]

DEFAULT_RULES = [
    {"pattern": r"restaurant|cafe|bar|pizza|kebab|bakery", "category": "Food & Drink"},
    {"pattern": r"bus|train|rail|taxi|uber", "category": "Transport"},
    {"pattern": r"paypal", "category": "P2P", "merchant": "PayPal"},
]


def ensure_app_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)


def load_rules(path: Path = RULES_PATH) -> list[dict[str, str]]:
    ensure_app_dirs()
    if not path.exists():
        migrated = load_legacy_rules()
        rules = migrated or DEFAULT_RULES.copy()
        save_rules(rules, path)
        return rules

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_RULES.copy()

    if not isinstance(data, list):
        return DEFAULT_RULES.copy()

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
    return rules or DEFAULT_RULES.copy()


def load_legacy_rules() -> list[dict[str, str]]:
    candidates = [Path("rules.json"), *sorted(Path(".").glob("rules-*.json"))]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
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
        if rules:
            return rules
    return []


def load_default_categories(path: Path = DEFAULT_CATEGORIES_PATH) -> list[str]:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = []
        if isinstance(data, list):
            categories = [str(item).strip() for item in data if str(item).strip()]
            if categories:
                return categories
    return DEFAULT_CATEGORIES.copy()


def load_categories(path: Path = CATEGORIES_PATH) -> list[str]:
    ensure_app_dirs()
    categories: list[str] = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = []
        if isinstance(data, list):
            categories.extend(str(item).strip() for item in data if str(item).strip())
    else:
        categories.extend(load_default_categories())

    for rule in load_rules():
        category = str(rule.get("category", "")).strip()
        if category:
            categories.append(category)
    return sorted(dict.fromkeys(category for category in categories if category and category != "Other"))


def save_categories(categories: list[str], path: Path = CATEGORIES_PATH) -> None:
    ensure_app_dirs()
    cleaned = sorted(dict.fromkeys(str(category).strip() for category in categories if str(category).strip()))
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def save_rules(rules: list[dict[str, str]], path: Path = RULES_PATH) -> None:
    ensure_app_dirs()
    path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")

