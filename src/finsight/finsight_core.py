from __future__ import annotations

from pathlib import Path
import json
import sys


APP_NAME = "FinSight"
# Read-only files shipped with the app (assets/, default_categories.json):
# the PyInstaller bundle when frozen, else the repository root. Never the cwd.
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
DEFAULT_CATEGORIES_PATH = BUNDLE_DIR / "default_categories.json"

DEFAULT_CATEGORIES = ["P2P", "Transport", "Groceries", "Food & Drink"]

DEFAULT_RULES = [
    {"pattern": r"restaurant|cafe|bar|pizza|kebab|bakery", "category": "Food & Drink"},
    {"pattern": r"bus|train|rail|taxi|uber", "category": "Transport"},
    {"pattern": r"paypal", "category": "P2P", "merchant": "PayPal"},
]


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
