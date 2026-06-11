from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import json
import re
import sys
from typing import Iterable

import pandas as pd
import plotly.graph_objects as go


APP_NAME = "Cashflow Sankey"
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
CONFIG_DIR = APP_DIR / "config"
RULES_PATH = CONFIG_DIR / "rules.json"
CATEGORIES_PATH = CONFIG_DIR / "categories.json"
PLOTS_DIR = APP_DIR / "generated Plots"
UPLOADS_DIR = APP_DIR / "uploaded CSV files"

DEFAULT_CATEGORIES = ["P2P", "Transport", "Groceries", "Food & Drink"]

DEFAULT_RULES = [
    {"pattern": r"twint", "category": "P2P", "merchant": "TWINT"},
    {"pattern": r"sbb|bahn|rail", "category": "Transport", "merchant": "SBB"},
    {"pattern": r"coop|migros|aldi|lidl", "category": "Groceries"},
    {"pattern": r"restaurant|cafe|bar|pizza|kebab", "category": "Food & Drink"},
]


@dataclass(frozen=True)
class CsvReadOptions:
    sep: str = "Auto"
    decimal: str = "Auto"
    skip_rows: int | None = None


@dataclass(frozen=True)
class CashflowSummary:
    total_in: float
    total_out: float
    net: float
    income_by_category: pd.Series
    expense_by_category: pd.Series


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

    for rule in load_rules():
        category = str(rule.get("category", "")).strip()
        if category:
            categories.append(category)

    if not categories:
        categories.extend(DEFAULT_CATEGORIES)
    return sorted(dict.fromkeys(category for category in categories if category and category != "Other"))


def save_categories(categories: list[str], path: Path = CATEGORIES_PATH) -> None:
    ensure_app_dirs()
    cleaned = sorted(dict.fromkeys(str(category).strip() for category in categories if str(category).strip()))
    path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def save_rules(rules: list[dict[str, str]], path: Path = RULES_PATH) -> None:
    ensure_app_dirs()
    path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")


def _decode_bytes(data: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding), encoding
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace"), "latin-1"


def detect_sep_from_text(sample_text: str) -> str:
    lines = [ln for ln in sample_text.splitlines() if ln.strip()]
    head = lines[0] if lines else sample_text
    candidates = [";", ",", "\t", "|"]
    counts = {c: head.count(c) for c in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def detect_skip_rows(sample_text: str, sep: str) -> int:
    header_keywords = {
        "buchungsdatum",
        "abschlussdatum",
        "valutadatum",
        "belastung",
        "gutschrift",
        "description",
        "merchant",
        "amount",
        "debit",
        "credit",
    }

    for i, line in enumerate(sample_text.splitlines()[:80]):
        cells = [c.strip().lower() for c in line.split(sep)]
        hits = sum(any(keyword in cell for keyword in header_keywords) for cell in cells)
        if hits >= 2 and len(cells) >= 4:
            return i
    return 0


def read_csv_bytes(data: bytes, options: CsvReadOptions | None = None) -> pd.DataFrame:
    options = options or CsvReadOptions()
    decoded_text, used_encoding = _decode_bytes(data)
    sep = options.sep if options.sep != "Auto" else detect_sep_from_text(decoded_text[:10_000])
    skip_rows = detect_skip_rows(decoded_text, sep) if options.skip_rows is None else options.skip_rows

    df0 = pd.read_csv(
        BytesIO(data),
        encoding=used_encoding,
        sep=sep,
        engine="python",
        quotechar='"',
        skiprows=int(skip_rows),
    )

    if df0.shape[1] == 1:
        col0 = df0.columns[0]
        if isinstance(col0, str) and ";" in col0 and sep != ";":
            retry_skip = detect_skip_rows(decoded_text, ";") if options.skip_rows is None else options.skip_rows
            df0 = pd.read_csv(
                BytesIO(data),
                encoding=used_encoding,
                sep=";",
                engine="python",
                quotechar='"',
                skiprows=int(retry_skip),
            )

    df0 = df0.dropna(axis=1, how="all")
    unnamed_cols = [c for c in df0.columns if str(c).lower().startswith("unnamed")]
    return df0.drop(columns=unnamed_cols, errors="ignore")


def read_csv_file(path: str | Path, options: CsvReadOptions | None = None) -> pd.DataFrame:
    return read_csv_bytes(Path(path).read_bytes(), options)


def parse_amount_series(series: pd.Series, decimal_override: str = "Auto") -> pd.Series:
    s = series.astype(str).str.strip()
    s = (
        s.str.replace("\u00a0", " ", regex=False)
        .str.replace("CHF", "", regex=False)
        .str.replace("EUR", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("'", "", regex=False)
    )

    if decimal_override == "Auto":
        sample = s.dropna().head(50)
        comma_like = sample.str.contains(",").any()
        dot_like = sample.str.contains("\\.").any()
        decimal = "," if comma_like and not dot_like else "."
    else:
        decimal = decimal_override

    if decimal == ",":
        s = s.str.replace(".", "", regex=False)
        s = s.str.replace(",", ".", regex=False)

    return pd.to_numeric(s, errors="coerce")


def combine_text_columns(df_in: pd.DataFrame, cols: Iterable[str]) -> pd.Series:
    cols = [c for c in cols if c in df_in.columns]
    if not cols:
        return pd.Series([""] * len(df_in), index=df_in.index)
    safe = df_in[cols].copy()
    for c in cols:
        safe[c] = safe[c].astype(str).fillna("")
    return safe.agg(" ".join, axis=1).str.replace(r"\s+", " ", regex=True).str.strip()


def apply_categories(text_series: pd.Series, rules: list[dict[str, str]]) -> pd.Series:
    compiled: list[tuple[re.Pattern[str], str]] = []
    for rule in rules:
        pattern = (rule.get("pattern") or "").strip()
        category = (rule.get("category") or "").strip() or "Other"
        if not pattern:
            continue
        try:
            compiled.append((re.compile(pattern, flags=re.IGNORECASE), category))
        except re.error:
            continue

    def one(text: str) -> str:
        text = (text or "").strip()
        for pattern, category in compiled:
            if pattern.search(text):
                return category
        return "Other"

    return text_series.astype(str).fillna("").map(one)


def first_matching_column(columns: Iterable[str], keys: Iterable[str]) -> str | None:
    for column in columns:
        lc = str(column).lower()
        if any(key in lc for key in keys):
            return str(column)
    return None


def guess_inflow_column(df: pd.DataFrame) -> str | None:
    return first_matching_column(df.columns, ["gutschrift", "credit", "einzahlung", "inflow", "income"])


def guess_outflow_column(df: pd.DataFrame) -> str | None:
    return first_matching_column(df.columns, ["belastung", "debit", "auszahlung", "outflow", "expense"])


def guess_text_columns(df: pd.DataFrame) -> list[str]:
    exact = [c for c in df.columns if str(c).lower() in {"beschreibung1", "beschreibung2", "beschreibung3"}]
    if exact:
        return [str(c) for c in exact]

    keys = ["beschreibung", "text", "verwendungszweck", "merchant", "description", "name"]
    guessed = [str(c) for c in df.columns if any(key in str(c).lower() for key in keys)]
    return guessed[:3]


def summarize_cashflow(
    df_in: pd.DataFrame,
    inflow_col: str,
    outflow_col: str,
    text_series: pd.Series | None,
    rules: list[dict[str, str]],
    decimal_override: str = "Auto",
) -> CashflowSummary:
    inflow = parse_amount_series(df_in[inflow_col], decimal_override).fillna(0.0)
    outflow = parse_amount_series(df_in[outflow_col], decimal_override).fillna(0.0).abs()

    if text_series is not None:
        txt = text_series.reindex(df_in.index).astype(str).fillna("")
        base_cats = apply_categories(txt, rules)
    else:
        base_cats = pd.Series(["All"] * len(df_in), index=df_in.index)

    def split_category(category: str, direction: str) -> str:
        if category == "P2P":
            return f"P2P {direction}"
        if category == "Other":
            return f"Other {direction}"
        return category

    cats_in = base_cats.astype(str).map(lambda c: split_category(c, "Incoming"))
    cats_out = base_cats.astype(str).map(lambda c: split_category(c, "Outgoing"))

    inc_sum = (
        pd.DataFrame({"cat": cats_in, "amt": inflow})
        .query("amt > 0")
        .groupby("cat", dropna=False)["amt"]
        .sum()
        .sort_values(ascending=False)
    )
    exp_sum = (
        pd.DataFrame({"cat": cats_out, "amt": outflow})
        .query("amt > 0")
        .groupby("cat", dropna=False)["amt"]
        .sum()
        .sort_values(ascending=False)
    )

    total_in = float(inc_sum.sum())
    total_out = float(exp_sum.sum())
    return CashflowSummary(total_in, total_out, total_in - total_out, inc_sum, exp_sum)


def build_cashflow_sankey(
    df_in: pd.DataFrame,
    inflow_col: str,
    outflow_col: str,
    text_series: pd.Series | None,
    rules: list[dict[str, str]],
    title: str = "Cash Flow",
    decimal_override: str = "Auto",
) -> tuple[go.Figure, CashflowSummary]:
    summary = summarize_cashflow(df_in, inflow_col, outflow_col, text_series, rules, decimal_override)
    inc_sum = summary.income_by_category
    exp_sum = summary.expense_by_category

    hub = "Cash flow hub"
    income_nodes = inc_sum.index.tolist()
    expense_nodes = exp_sum.index.tolist()

    def fmt(value: float) -> str:
        return f"{value:,.2f}"

    inc_pct = {k: (float(v) / summary.total_in * 100) if summary.total_in else 0.0 for k, v in inc_sum.items()}
    exp_pct = {k: (float(v) / summary.total_out * 100) if summary.total_out else 0.0 for k, v in exp_sum.items()}

    labels_plain = income_nodes + [hub] + expense_nodes
    display_labels = (
        [f"{k} (CHF {fmt(float(inc_sum[k]))} - {inc_pct[k]:.1f}%)" for k in income_nodes]
        + [f"{hub} (Net: CHF {fmt(summary.net)})"]
        + [f"{k} (CHF {fmt(float(exp_sum[k]))} - {exp_pct[k]:.1f}%)" for k in expense_nodes]
    )

    idx: dict[str, int] = {k: i for i, k in enumerate(labels_plain)}
    hub_idx = idx[hub]
    sources: list[int] = []
    targets: list[int] = []
    values: list[float] = []
    link_labels: list[str] = []

    for category, value in inc_sum.items():
        amount = float(value)
        if amount <= 0:
            continue
        sources.append(idx[category])
        targets.append(hub_idx)
        values.append(amount)
        link_labels.append(f"{category} -> {hub}")

    for category, value in exp_sum.items():
        amount = float(value)
        if amount <= 0:
            continue
        sources.append(hub_idx)
        targets.append(idx[category])
        values.append(amount)
        link_labels.append(f"{hub} -> {category}")

    if abs(summary.net) > 1e-9:
        if summary.net >= 0:
            net_name = "Net Savings"
            labels_plain.append(net_name)
            display_labels.append(f"{net_name} (CHF {fmt(summary.net)})")
            net_idx = len(labels_plain) - 1
            sources.append(hub_idx)
            targets.append(net_idx)
            values.append(float(summary.net))
            link_labels.append(f"{hub} -> {net_name}")
        else:
            net_name = "Overdrawn Balance"
            labels_plain.append(net_name)
            display_labels.append(f"{net_name} (CHF {fmt(-summary.net)})")
            net_idx = len(labels_plain) - 1
            sources.append(net_idx)
            targets.append(hub_idx)
            values.append(float(-summary.net))
            link_labels.append(f"{net_name} -> {hub}")

    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node=dict(
                    label=display_labels,
                    pad=22,
                    thickness=18,
                    line=dict(color="rgba(17,24,39,0.18)", width=0.5),
                ),
                link=dict(
                    source=sources,
                    target=targets,
                    value=values,
                    label=link_labels,
                    hovertemplate="%{label}<br>%{value:,.2f} CHF<extra></extra>",
                ),
            )
        ]
    )

    net_label = "Net Savings" if summary.net >= 0 else "Overdrawn"
    fig.update_layout(
        title=f"{title} - Income CHF {fmt(summary.total_in)} - Expenses CHF {fmt(summary.total_out)} - {net_label} CHF {fmt(abs(summary.net))}",
        font=dict(size=13, family="Inter, Segoe UI, Arial"),
        paper_bgcolor="#f8fafc",
        plot_bgcolor="#f8fafc",
        height=720,
        margin=dict(l=24, r=24, t=72, b=24),
    )
    return fig, summary
