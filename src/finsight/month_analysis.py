"""Analyze a month: the one place that turns a bank CSV and the Rules into numbers.

`analyze_month` is pure: it takes CSV bytes, the Rules and optional import
overrides and returns a `MonthAnalysis`. No Qt, no filesystem, no global paths.
Nothing else in FinSight applies Rules to transactions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from io import BytesIO
import re

import pandas as pd

from finsight.finsight_core import detect_sep_from_text, detect_skip_rows

UNCATEGORIZED = "Uncategorized"
OTHER = "Other"
PREVIEW_ROW_COUNT = 5


class UnreadableCsvError(ValueError):
    """The file could not be read as a CSV at all."""


@dataclass(frozen=True)
class ImportOverrides:
    """Choices that replace detection. None means "detect it"."""

    sep: str | None = None
    decimal: str | None = None
    header_row: int | None = None
    income_column: str | None = None
    expenses_column: str | None = None
    text_columns: tuple[str, ...] | None = None
    date_column: str | None = None


@dataclass(frozen=True)
class ImportSettings:
    """How the CSV was read: detected, or taken from import overrides."""

    encoding: str
    sep: str
    header_row: int
    decimal: str
    income_column: str | None
    expenses_column: str | None
    text_columns: tuple[str, ...]
    date_column: str | None


@dataclass(frozen=True)
class ColumnCheck:
    """Detection failed: the columns to choose from and a few rows to preview."""

    columns: tuple[str, ...]
    preview_rows: tuple[dict[str, str], ...]


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
class FlowNode:
    """A Money flow node. `side` is "income", "month" or "expenses"."""

    id: str
    label: str
    side: str
    amount: float


@dataclass(frozen=True)
class FlowLink:
    source: str
    target: str
    amount: float


@dataclass(frozen=True)
class MoneyFlow:
    """Income Categories flow into the month, which flows out into Expense Categories and Saved."""

    nodes: tuple[FlowNode, ...]
    links: tuple[FlowLink, ...]


@dataclass(frozen=True)
class MonthAnalysis:
    settings: ImportSettings
    column_check: ColumnCheck | None
    income: float
    expenses: float
    categories: tuple[CategoryTotal, ...]
    transactions: tuple[Transaction, ...]
    review_merchants: tuple[ReviewMerchant, ...]
    start_date: date | None
    end_date: date | None
    month_label: str
    money_flow: MoneyFlow
    columns: tuple[str, ...]
    # The raw imported table, for the Advanced view. Not part of equality.
    table: pd.DataFrame = field(compare=False, repr=False)

    @property
    def saved(self) -> float:
        return self.income - self.expenses

    @property
    def columns_need_checking(self) -> bool:
        return self.column_check is not None


# --- Reading the CSV -------------------------------------------------------


def _decode(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1"), "latin-1"


def _read_table(data: bytes, overrides: ImportOverrides) -> tuple[pd.DataFrame, str, str, int]:
    text, encoding = _decode(data)
    sep = overrides.sep or detect_sep_from_text(text[:10_000])
    header_row = overrides.header_row if overrides.header_row is not None else detect_skip_rows(text, sep)
    try:
        table = pd.read_csv(
            BytesIO(data), encoding=encoding, sep=sep, engine="python", skiprows=header_row, dtype=str
        )
    except Exception as exc:  # pandas raises several unrelated error types
        raise UnreadableCsvError(str(exc)) from exc
    table = table.dropna(axis=1, how="all")
    table = table.drop(columns=[c for c in table.columns if str(c).lower().startswith("unnamed")])
    table.columns = [str(c).strip() for c in table.columns]
    return table, encoding, sep, header_row


def _clean_amount_text(series: pd.Series) -> pd.Series:
    cleaned = series.fillna("").astype(str).str.replace("CHF", "", regex=False)
    return cleaned.str.replace(r"[\s'’]", "", regex=True)


def _detect_decimal(columns: list[pd.Series]) -> str:
    """"," when amounts end in a comma and one or two digits more often than in a dot."""
    if not columns:
        return "."
    values = pd.concat([_clean_amount_text(c) for c in columns])
    comma = int(values.str.contains(r",\d{1,2}$").sum())
    dot = int(values.str.contains(r"\.\d{1,2}$").sum())
    return "," if comma > dot else "."


def _parse_amounts(series: pd.Series, decimal: str) -> pd.Series:
    cleaned = _clean_amount_text(series)
    if decimal == ",":
        cleaned = cleaned.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
    else:
        cleaned = cleaned.str.replace(",", "", regex=False)
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


def _parse_dates(series: pd.Series) -> pd.Series:
    values = series.fillna("").astype(str).str.strip()
    dayfirst = bool(values.str.match(r"^\d{1,2}\.\d{1,2}\.\d{2,4}").any())
    return pd.to_datetime(values, errors="coerce", dayfirst=dayfirst, format="mixed")


def _first_column(columns, keys) -> str | None:
    for column in columns:
        if any(key in str(column).lower() for key in keys):
            return str(column)
    return None


def _guess_text_columns(columns) -> tuple[str, ...]:
    exact = [str(c) for c in columns if str(c).lower() in {"beschreibung1", "beschreibung2", "beschreibung3"}]
    if exact:
        return tuple(exact)
    keys = ["beschreibung", "text", "verwendungszweck", "merchant", "description", "name"]
    return tuple([str(c) for c in columns if any(key in str(c).lower() for key in keys)][:3])


def _chosen(override: str | None, columns, keys) -> str | None:
    if override is not None:
        return override if override in columns else None
    return _first_column(columns, keys)


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


# --- Categorizing ----------------------------------------------------------


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


def rule_for_merchant(merchant: str, category: str) -> dict[str, str]:
    """The Rule Review creates when a Category is picked for a Merchant.

    The pattern matches the Merchant literally, so special characters are safe.
    """
    return {"pattern": re.escape(merchant), "category": category, "merchant": merchant}


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


def _category_totals(transactions: list[Transaction]) -> tuple[CategoryTotal, ...]:
    totals: dict[str, list[float]] = {}
    for t in transactions:
        income_expenses = totals.setdefault(t.category, [0.0, 0.0])
        income_expenses[0] += t.income
        income_expenses[1] += t.expenses
    ordered = sorted(totals.items(), key=lambda item: (-(item[1][0] + item[1][1]), item[0]))
    return tuple(CategoryTotal(name, income, expenses) for name, (income, expenses) in ordered)


_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def _month_label(start: date | None, end: date | None) -> str:
    if start is None or end is None:
        return "This month"
    if (start.year, start.month) == (end.year, end.month):
        return f"{_MONTH_NAMES[start.month - 1]} {start.year}"
    return f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"


def _money_flow(categories: tuple[CategoryTotal, ...], month_label: str) -> MoneyFlow:
    income = sum(c.income for c in categories)
    expenses = sum(c.expenses for c in categories)
    saved = income - expenses
    month = FlowNode("month", month_label, "month", max(income, expenses))
    nodes: list[FlowNode] = [month]
    links: list[FlowLink] = []

    for c in sorted((c for c in categories if c.income > 0), key=lambda c: -c.income):
        node = FlowNode(f"income:{c.category}", c.category, "income", c.income)
        nodes.append(node)
        links.append(FlowLink(node.id, month.id, c.income))
    if saved < 0:
        node = FlowNode("overspent", "Overspent", "income", -saved)
        nodes.append(node)
        links.append(FlowLink(node.id, month.id, -saved))
    for c in sorted((c for c in categories if c.expenses > 0), key=lambda c: -c.expenses):
        node = FlowNode(f"expenses:{c.category}", c.category, "expenses", c.expenses)
        nodes.append(node)
        links.append(FlowLink(month.id, node.id, c.expenses))
    if saved > 0:
        node = FlowNode("saved", "Saved", "expenses", saved)
        nodes.append(node)
        links.append(FlowLink(month.id, node.id, saved))
    return MoneyFlow(tuple(nodes), tuple(links))


# --- The entry point -------------------------------------------------------


def analyze_month(
    data: bytes,
    rules: list[dict[str, str]],
    overrides: ImportOverrides | None = None,
    *,
    categories: list[str] | None = None,
    minimum_amount: float = 0.0,
) -> MonthAnalysis:
    """Read one month's bank CSV and categorize it with the Rules.

    `categories` are the known Categories Review may suggest; `minimum_amount`
    drops transactions smaller than it from every figure alike.
    Raises UnreadableCsvError when the bytes are not a CSV at all.
    """
    overrides = overrides or ImportOverrides()
    table, encoding, sep, header_row = _read_table(data, overrides)
    columns = tuple(table.columns)

    income_column = _chosen(overrides.income_column, columns, ["gutschrift", "credit", "einzahlung", "income"])
    expenses_column = _chosen(overrides.expenses_column, columns, ["belastung", "debit", "auszahlung", "expense"])
    date_column = _chosen(
        overrides.date_column, columns, ["buchungsdatum", "abschlussdatum", "valutadatum", "date", "datum"]
    )
    if overrides.text_columns is not None:
        text_columns = tuple(c for c in overrides.text_columns if c in columns)
    else:
        text_columns = _guess_text_columns(columns)

    amount_columns = [table[c] for c in (income_column, expenses_column) if c]
    decimal = overrides.decimal or _detect_decimal(amount_columns)
    settings = ImportSettings(
        encoding, sep, header_row, decimal, income_column, expenses_column, text_columns, date_column
    )

    if (income_column is None and expenses_column is None) or not text_columns:
        preview = table.head(PREVIEW_ROW_COUNT).fillna("").astype(str)
        check = ColumnCheck(columns, tuple(preview.to_dict(orient="records")))
        label = _month_label(None, None)
        return MonthAnalysis(
            settings, check, 0.0, 0.0, (), (), (), None, None, label, _money_flow((), label), columns, table
        )

    zero = pd.Series(0.0, index=table.index)
    incomes = _parse_amounts(table[income_column], decimal) if income_column else zero
    expenses = _parse_amounts(table[expenses_column], decimal).abs() if expenses_column else zero
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
        parts = [_clean(row[c]) for c in text_columns]
        text = " ".join(p for p in parts if p)
        category, rule_merchant = categorizer.categorize(text)
        merchant = rule_merchant or next((p for p in parts if p), "") or "Unknown"
        transactions.append(
            Transaction(None if pd.isna(when) else when.date(), text, merchant[:80], category, income, expense)
        )

    known_dates = [t.date for t in transactions if t.date is not None]
    start_date, end_date = min(known_dates, default=None), max(known_dates, default=None)
    category_totals = _category_totals(transactions)
    label = _month_label(start_date, end_date)
    return MonthAnalysis(
        settings=settings,
        column_check=None,
        income=sum(t.income for t in transactions),
        expenses=sum(t.expenses for t in transactions),
        categories=category_totals,
        transactions=tuple(transactions),
        review_merchants=_review_merchants(transactions, set(categories or [])),
        start_date=start_date,
        end_date=end_date,
        month_label=label,
        money_flow=_money_flow(category_totals, label),
        columns=columns,
        table=table,
    )
