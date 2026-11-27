"""Analyze a month: the one place that turns a bank CSV and the Rules into numbers.

`analyze_month` is pure: it takes CSV bytes, the Rules and optional import
overrides and returns a `MonthAnalysis`. No Qt, no filesystem, no global paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO
import re

import pandas as pd

from finsight.finsight_core import _decode_bytes, detect_sep_from_text, detect_skip_rows

UNCATEGORIZED = "Uncategorized"
OTHER = "Other"


@dataclass(frozen=True)
class Transaction:
    date: date | None
    text: str
    merchant: str
    category: str
    income: float
    expenses: float


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    income: float
    expenses: float


@dataclass(frozen=True)
class ReviewMerchant:
    """An Uncategorized Merchant waiting for Review."""

    merchant: str
    count: int
    total: float
    suggested_category: str
    example: str


@dataclass(frozen=True)
class MonthAnalysis:
    income: float
    expenses: float
    categories: tuple[CategoryTotal, ...]
    transactions: tuple[Transaction, ...]
    review_merchants: tuple[ReviewMerchant, ...]
    start_date: date | None
    end_date: date | None

    @property
    def saved(self) -> float:
        return self.income - self.expenses


def _read_table(data: bytes) -> pd.DataFrame:
    text, encoding = _decode_bytes(data)
    sep = detect_sep_from_text(text[:10_000])
    header_row = detect_skip_rows(text, sep)
    table = pd.read_csv(
        BytesIO(data), encoding=encoding, sep=sep, engine="python", skiprows=header_row, dtype=str
    )
    return table.dropna(axis=1, how="all")


def _parse_amounts(series: pd.Series) -> pd.Series:
    cleaned = series.fillna("").astype(str).str.replace("CHF", "", regex=False)
    cleaned = cleaned.str.replace(r"[\s'’]", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


def _first_column(columns, keys) -> str | None:
    for column in columns:
        if any(key in str(column).lower() for key in keys):
            return str(column)
    return None


def _text_columns(columns) -> list[str]:
    exact = [str(c) for c in columns if str(c).lower() in {"beschreibung1", "beschreibung2", "beschreibung3"}]
    if exact:
        return exact
    keys = ["beschreibung", "text", "verwendungszweck", "merchant", "description", "name"]
    return [str(c) for c in columns if any(key in str(c).lower() for key in keys)][:3]


def _parse_dates(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    if values.str.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}").any():
        return pd.to_datetime(values, errors="coerce", dayfirst=True, format="mixed")
    return pd.to_datetime(values, errors="coerce", format="mixed")


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


class _Categorizer:
    """Applies the Rules in order; the first matching Rule wins."""

    def __init__(self, rules: list[dict[str, str]]) -> None:
        self._rules: list[tuple[re.Pattern[str], str, str]] = []
        for rule in rules:
            pattern = (rule.get("pattern") or "").strip()
            category = (rule.get("category") or "").strip()
            if not pattern or not category:
                continue
            try:
                compiled = re.compile(pattern, flags=re.IGNORECASE)
            except re.error:
                continue
            self._rules.append((compiled, category, (rule.get("merchant") or "").strip()))

    def categorize(self, text: str) -> tuple[str, str]:
        """Return (Category, Merchant from the Rule or "")."""
        for pattern, category, merchant in self._rules:
            if pattern.search(text):
                return category, merchant
        return UNCATEGORIZED, ""


_SUGGESTION_HINTS = [
    ("Groceries", ["supermarket", "supermarkt", "grocery", "migros", "coop", "denner", "lidl", "aldi"]),
    ("Food & Drink", ["restaurant", "cafe", "café", "bar ", "pizza", "kebab", "mcdonald", "burger", "bakery", "bäckerei"]),
    ("Transport", ["sbb", "rail", "bus", "train", "ticket", "uber", "taxi"]),
    ("Shopping", ["shop", "store", "amazon", "aliexpress", "ikea"]),
    ("Subscriptions", ["apple.com/bill", "spotify", "netflix", "subscription"]),
    ("Telecom", ["telecom", "mobile", "wireless", "swisscom", "salt", "sunrise"]),
    ("Health", ["pharmacy", "apotheke", "doctor", "hospital", "clinic"]),
    ("P2P", ["paypal", "twint"]),
]


def _suggest_category(merchant: str, text: str, categories: set[str]) -> str:
    sample = f"{merchant} {text}".lower()
    for category, keywords in _SUGGESTION_HINTS:
        if category in categories and any(keyword in sample for keyword in keywords):
            return category
    merchant_tokens = set(re.findall(r"[a-z0-9]{4,}", merchant.lower()))
    best, best_score = "", 0
    for category in sorted(categories):
        score = len(merchant_tokens & set(re.findall(r"[a-z0-9]{4,}", category.lower())))
        if score > best_score:
            best, best_score = category, score
    return best


def _review_merchants(transactions: list[Transaction], categories: set[str]) -> tuple[ReviewMerchant, ...]:
    groups: dict[str, list[Transaction]] = {}
    for t in transactions:
        if t.category == UNCATEGORIZED:
            groups.setdefault(t.merchant, []).append(t)
    merchants = [
        ReviewMerchant(
            merchant=merchant,
            count=len(items),
            total=sum(t.income + t.expenses for t in items),
            suggested_category=_suggest_category(merchant, items[0].text, categories),
            example=items[0].text,
        )
        for merchant, items in groups.items()
    ]
    return tuple(sorted(merchants, key=lambda m: (-m.total, -m.count, m.merchant)))


def rule_for_merchant(merchant: str, category: str) -> dict[str, str]:
    """The Rule Review creates when a Category is picked for a Merchant.

    The pattern matches the Merchant literally, so special characters are safe.
    """
    return {"pattern": re.escape(merchant), "category": category, "merchant": merchant}


def _category_totals(transactions: list[Transaction]) -> tuple[CategoryTotal, ...]:
    totals: dict[str, list[float]] = {}
    for t in transactions:
        income_expenses = totals.setdefault(t.category, [0.0, 0.0])
        income_expenses[0] += t.income
        income_expenses[1] += t.expenses
    ordered = sorted(totals.items(), key=lambda item: (-(item[1][0] + item[1][1]), item[0]))
    return tuple(CategoryTotal(name, income, expenses) for name, (income, expenses) in ordered)


def analyze_month(
    data: bytes,
    rules: list[dict[str, str]],
    categories: list[str] | None = None,
    minimum_amount: float = 0.0,
) -> MonthAnalysis:
    table = _read_table(data)
    income_column = _first_column(table.columns, ["gutschrift", "credit"])
    expenses_column = _first_column(table.columns, ["belastung", "debit"])
    text_columns = _text_columns(table.columns)
    incomes = _parse_amounts(table[income_column])
    expenses = _parse_amounts(table[expenses_column]).abs()
    date_column = _first_column(table.columns, ["buchungsdatum", "abschlussdatum", "valutadatum", "date", "datum"])
    dates = _parse_dates(table[date_column]) if date_column else pd.Series(pd.NaT, index=table.index)

    categorizer = _Categorizer(rules)
    transactions: list[Transaction] = []
    for position, (_, row) in enumerate(table.iterrows()):
        income, expense = float(incomes.iloc[position]), float(expenses.iloc[position])
        if income == 0 and expense == 0:
            continue
        if income + expense < minimum_amount:
            continue
        when = dates.iloc[position]
        when = None if pd.isna(when) else when.date()
        parts = [_clean(row[c]) for c in text_columns]
        text = " ".join(p for p in parts if p)
        category, rule_merchant = categorizer.categorize(text)
        merchant = rule_merchant or next((p for p in parts if p), "") or "Unknown"
        transactions.append(Transaction(when, text, merchant[:80], category, income, expense))

    known_dates = [t.date for t in transactions if t.date is not None]
    return MonthAnalysis(
        income=sum(t.income for t in transactions),
        expenses=sum(t.expenses for t in transactions),
        categories=_category_totals(transactions),
        transactions=tuple(transactions),
        review_merchants=_review_merchants(transactions, set(categories or [])),
        start_date=min(known_dates, default=None),
        end_date=max(known_dates, default=None),
    )
