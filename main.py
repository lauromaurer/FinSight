from __future__ import annotations

from io import BytesIO
import json
import re

import pandas as pd
import streamlit as st
import plotly.graph_objects as go

st.set_page_config(page_title="Cashflow", layout="wide")
st.title("Cashflow")

# -----------------
# Navigation
# -----------------
with st.sidebar:
    st.header("Navigation")
    page = st.radio("Go to", ["Upload", "Dashboard", "Categorize"], index=0)


# -----------------
# Session helpers
# -----------------
DEFAULT_RULES = [
    {"pattern": r"twint", "category": "P2P"},
    {"pattern": r"sbb|bahn|rail", "category": "Transport"},
    {"pattern": r"coop|migros|aldi|lidl", "category": "Groceries"},
    {"pattern": r"restaurant|cafe|bar|pizza|kebab", "category": "Food & Drink"},
]


def _ensure_state() -> None:
    st.session_state.setdefault("csv_bytes", None)
    st.session_state.setdefault("csv_name", None)
    st.session_state.setdefault("rules", DEFAULT_RULES.copy())


def _get_rules() -> list[dict[str, str]]:
    _ensure_state()
    return st.session_state.rules


def _set_rules(rules: list[dict[str, str]]) -> None:
    st.session_state.rules = rules


# -----------------
# CSV parsing controls (global)
# -----------------
with st.sidebar:
    st.header("CSV settings")
    sep_override = st.selectbox(
        "Delimiter",
        options=["Auto", ";", ",", "\t", "|"],
        index=0,
        help="If the preview looks wrong (everything in one column), set this to ';'.",
    )
    decimal_override = st.selectbox(
        "Decimal",
        options=["Auto", ".", ","],
        index=0,
        help="Used when parsing money columns.",
    )
    skip_rows = st.number_input(
        "Skip header rows",
        min_value=0,
        max_value=50,
        value=0,
        step=1,
        help="If your CSV has descriptive lines before the actual header, increase this until columns align.",
    )


def _detect_sep_from_text(sample_text: str) -> str:
    lines = [ln for ln in sample_text.splitlines() if ln.strip()]
    head = lines[0] if lines else sample_text
    candidates = [";", ",", "\t", "|"]
    counts = {c: head.count(c) for c in candidates}
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def read_csv_bytes(data: bytes) -> pd.DataFrame:
    decoded_text = None
    used_encoding = None
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            decoded_text = data.decode(encoding)
            used_encoding = encoding
            break
        except Exception:
            pass
    if decoded_text is None:
        decoded_text = data.decode("latin-1", errors="replace")
        used_encoding = "latin-1"

    if sep_override != "Auto":
        sep = sep_override
    else:
        sep = _detect_sep_from_text(decoded_text[:10_000])

    df0 = pd.read_csv(
        BytesIO(data),
        encoding=used_encoding,
        sep=sep,
        engine="python",
        quotechar='"',
        skiprows=int(skip_rows),
    )

    # If it still looks wrong (single column with separators inside), retry with ';'
    if df0.shape[1] == 1:
        col0 = df0.columns[0]
        if isinstance(col0, str) and (";" in col0) and sep != ";":
            df0 = pd.read_csv(
                BytesIO(data),
                encoding=used_encoding,
                sep=";",
                engine="python",
                quotechar='"',
                skiprows=int(skip_rows),
            )

    return df0


def _parse_amount_series(series: pd.Series) -> pd.Series:
    """Parse numbers from typical bank-export formats (CHF/EUR, apostrophes, comma-decimal)."""
    s = series.astype(str).str.strip()

    s = (
        s.str.replace("\u00a0", " ", regex=False)
        .str.replace("CHF", "", regex=False)
        .str.replace("EUR", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("'", "", regex=False)
    )

    # Choose decimal based on sidebar setting
    if decimal_override == "Auto":
        sample = s.dropna().head(50)
        comma_like = sample.str.contains(",").any()
        dot_like = sample.str.contains("\\.").any()
        decimal = "," if (comma_like and not dot_like) else "."
    else:
        decimal = decimal_override

    # If comma-decimal, normalize to dot-decimal
    if decimal == ",":
        s = s.str.replace(".", "", regex=False)  # thousands sep like 1.234,56
        s = s.str.replace(",", ".", regex=False)

    return pd.to_numeric(s, errors="coerce")


def combine_text_columns(df_in: pd.DataFrame, cols: list[str]) -> pd.Series:
    """Combine multiple text columns into one searchable series."""
    if not cols:
        return pd.Series([""] * len(df_in), index=df_in.index)
    safe = df_in[cols].copy()
    for c in cols:
        safe[c] = safe[c].astype(str).fillna("")
    return (
        safe.astype(str)
        .agg(" ".join, axis=1)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def apply_categories(text_series: pd.Series, rules: list[dict[str, str]]) -> pd.Series:
    """Assign first-matching category by regex pattern; otherwise 'Other'."""
    compiled: list[tuple[re.Pattern, str]] = []
    for r in rules:
        pat = (r.get("pattern") or "").strip()
        cat = (r.get("category") or "").strip() or "Other"
        if not pat:
            continue
        try:
            compiled.append((re.compile(pat, flags=re.IGNORECASE), cat))
        except re.error:
            continue

    def _one(txt: str) -> str:
        t = (txt or "").strip()
        for p, c in compiled:
            if p.search(t):
                return c
        return "Other"

    return text_series.astype(str).fillna("").map(_one)


def build_cashflow_sankey(
    df_in: pd.DataFrame,
    inflow_col: str,
    outflow_col: str,
    text_series: pd.Series | None,
    rules: list[dict[str, str]] | None,
    title: str = "Cash Flow",
):
    inflow = _parse_amount_series(df_in[inflow_col]).fillna(0.0)
    outflow = _parse_amount_series(df_in[outflow_col]).fillna(0.0).abs()

    if text_series is not None:
        txt = text_series.reindex(df_in.index).astype(str).fillna("")
        base_cats = apply_categories(txt, rules or [])
    else:
        base_cats = pd.Series(["All"] * len(df_in), index=df_in.index)

    # Split only P2P and Other into Incoming/Outgoing variants
    def _split(cat: str, direction: str) -> str:
        if cat == "P2P":
            return f"P2P {direction}"
        if cat == "Other":
            return f"Other {direction}"
        return cat

    cats_in = base_cats.astype(str).map(lambda c: _split(c, "Incoming"))
    cats_out = base_cats.astype(str).map(lambda c: _split(c, "Outgoing"))

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
    net = total_in - total_out

    hub = "Cash flow hub"
    income_nodes = inc_sum.index.tolist()
    expense_nodes = exp_sum.index.tolist()

    def _fmt(x: float) -> str:
        return f"{x:,.2f}"

    inc_pct = {k: (float(v) / total_in * 100) if total_in else 0.0 for k, v in inc_sum.items()}
    exp_pct = {k: (float(v) / total_out * 100) if total_out else 0.0 for k, v in exp_sum.items()}

    labels_plain = income_nodes + [hub] + expense_nodes
    display_labels = (
        [f"{k} (CHF {_fmt(float(inc_sum[k]))} • {inc_pct[k]:.1f}%)" for k in income_nodes]
        + [f"{hub} (Net: CHF {_fmt(net)})"]
        + [f"{k} (CHF {_fmt(float(exp_sum[k]))} • {exp_pct[k]:.1f}%)" for k in expense_nodes]
    )

    idx: dict[str, int] = {k: i for i, k in enumerate(labels_plain)}
    hub_idx = idx[hub]

    sources: list[int] = []
    targets: list[int] = []
    values: list[float] = []
    link_labels: list[str] = []

    for k, v in inc_sum.items():
        vv = float(v)
        if vv <= 0:
            continue
        sources.append(idx[k])
        targets.append(hub_idx)
        values.append(vv)
        link_labels.append(f"{k} → {hub}")

    for k, v in exp_sum.items():
        vv = float(v)
        if vv <= 0:
            continue
        sources.append(hub_idx)
        targets.append(idx[k])
        values.append(vv)
        link_labels.append(f"{hub} → {k}")

    if abs(net) > 1e-9:
        if net >= 0:
            net_name = "Net Savings"
            labels_plain.append(net_name)
            display_labels.append(f"{net_name} (CHF {_fmt(net)})")
            net_idx = len(labels_plain) - 1
            sources.append(hub_idx)
            targets.append(net_idx)
            values.append(float(net))
            link_labels.append(f"{hub} → {net_name}")
        else:
            net_name = "Overdrawn Balance"
            labels_plain.append(net_name)
            display_labels.append(f"{net_name} (CHF {_fmt(-net)})")
            net_idx = len(labels_plain) - 1
            sources.append(net_idx)
            targets.append(hub_idx)
            values.append(float(-net))
            link_labels.append(f"{net_name} → {hub}")

    fig = go.Figure(
        data=[
            go.Sankey(
                arrangement="snap",
                node=dict(label=display_labels, pad=18, thickness=18),
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

    net_label = "Net Savings" if net >= 0 else "Overdrawn"
    fig.update_layout(
        title=f"{title} — Income CHF {_fmt(total_in)} • Expenses CHF {_fmt(total_out)} • {net_label} CHF {_fmt(abs(net))}",
        font_size=12,
        height=650,
    )

    return fig


def _require_data() -> pd.DataFrame:
    _ensure_state()
    if st.session_state.csv_bytes is None:
        st.warning("Go to **Upload** first and upload a CSV.")
        st.stop()
    try:
        return read_csv_bytes(st.session_state.csv_bytes)
    except Exception as e:
        st.error("Could not read the uploaded CSV with the current settings.")
        st.exception(e)
        st.stop()


# -----------------
# Upload page
# -----------------
if page == "Upload":
    st.header("Upload")
    st.caption("Upload your CSV and (optionally) a rules.json to reuse your categories.")

    csv_up = st.file_uploader("CSV file", type=["csv"], key="csv_uploader")
    rules_up = st.file_uploader("rules.json (optional)", type=["json"], key="rules_uploader")

    if csv_up is not None:
        st.session_state.csv_bytes = csv_up.getvalue()
        st.session_state.csv_name = csv_up.name
        st.success(f"CSV loaded: {csv_up.name}")

        # Show a quick preview
        try:
            df_preview = read_csv_bytes(st.session_state.csv_bytes)
            st.dataframe(df_preview.head(30), use_container_width=True)
        except Exception as e:
            st.error("CSV loaded but could not be parsed with current settings.")
            st.exception(e)

    if rules_up is not None:
        try:
            new_rules = json.loads(rules_up.getvalue().decode("utf-8"))
            if isinstance(new_rules, list):
                _set_rules(new_rules)
                st.success("Rules loaded into this session.")
            else:
                st.error("rules.json must be a JSON list of objects with keys: pattern, category")
        except Exception as e:
            st.error("Could not read rules.json")
            st.exception(e)

    st.subheader("Current rules")
    st.write("These live in-memory while the app runs. To persist them, download rules.json from the Categorize page.")
    st.json(_get_rules())


# -----------------
# Dashboard page
# -----------------
if page == "Dashboard":
    df = _require_data()

    st.header("Dashboard")
    st.subheader("Sankey chart")

    all_cols = df.columns.tolist()

    def _first_match(keys: list[str]) -> str | None:
        for cc in all_cols:
            lc = str(cc).lower()
            if any(k in lc for k in keys):
                return cc
        return None

    suggest_in = _first_match(["gutschrift", "credit", "einzahlung", "inflow"]) or (all_cols[0] if all_cols else None)
    suggest_out = _first_match(["belastung", "debit", "auszahlung", "outflow"]) or (all_cols[0] if all_cols else None)

    default_text_cols = [c for c in all_cols if str(c).lower() in {"beschreibung1", "beschreibung2", "beschreibung3"}]
    if not default_text_cols:
        first_txt = _first_match(["beschreibung", "text", "verwendungszweck", "merchant"])
        default_text_cols = [first_txt] if first_txt else []

    col1, col2, col3 = st.columns(3)

    inflow_col = col1.selectbox(
        "Inflow column (Gutschrift)",
        options=all_cols,
        index=all_cols.index(suggest_in) if suggest_in in all_cols else 0,
    )

    outflow_col = col2.selectbox(
        "Outflow column (Belastung)",
        options=all_cols,
        index=all_cols.index(suggest_out) if suggest_out in all_cols else 0,
    )

    text_cols = col3.multiselect(
        "Text columns for categories",
        options=all_cols,
        default=default_text_cols,
    )

    min_abs = st.number_input(
        "Hide transactions smaller than (CHF, based on inflow+outflow)",
        min_value=0.0,
        value=0.0,
        step=10.0,
    )

    rules = _get_rules()

    tmp = df.copy()
    inc = _parse_amount_series(tmp[inflow_col]).fillna(0.0)
    out = _parse_amount_series(tmp[outflow_col]).fillna(0.0).abs()

    if min_abs > 0:
        tmp = tmp[(inc + out) >= min_abs]

    text_series = combine_text_columns(tmp, text_cols) if text_cols else None

    try:
        fig = build_cashflow_sankey(
            tmp,
            inflow_col=inflow_col,
            outflow_col=outflow_col,
            text_series=text_series,
            rules=rules,
            title="Cash Flow",
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error("Could not build the Sankey chart with the selected columns.")
        st.exception(e)


# -----------------
# Categorize page
# -----------------
if page == "Categorize":
    df = _require_data()

    st.header("Categorize")
    st.caption("This page auto-focuses on transactions that are currently categorized as **Other**.")

    all_cols = df.columns.tolist()

    default_text_cols = [c for c in all_cols if str(c).lower() in {"beschreibung1", "beschreibung2", "beschreibung3"}]
    if not default_text_cols:
        # fallback
        fallback = None
        for c in all_cols:
            lc = str(c).lower()
            if any(k in lc for k in ["beschreibung", "text", "verwendungszweck", "merchant"]):
                fallback = c
                break
        default_text_cols = [fallback] if fallback else []

    text_cols = st.multiselect(
        "Description columns used for categorization",
        options=all_cols,
        default=default_text_cols,
    )

    if not text_cols:
        st.warning("Select at least one description column.")
        st.stop()

    combined_text = combine_text_columns(df, text_cols)

    rules = _get_rules()
    cats = apply_categories(combined_text, rules)

    df_view = df.copy()
    df_view["Category"] = cats
    df_view["_combined_text"] = combined_text

    # Auto-focus on 'Other'
    other_df = df_view[df_view["Category"] == "Other"].copy()

    st.subheader("Uncategorized (Other)")
    if other_df.empty:
        st.success("No rows are categorized as Other 🎉")
    else:
        st.write(f"Rows in Other: {len(other_df)}")

        # Quick search within Other
        q = st.text_input("Search in Other", "")
        if q.strip():
            other_df = other_df[other_df["_combined_text"].astype(str).str.contains(q, case=False, na=False)]

        st.dataframe(other_df.drop(columns=["_combined_text"], errors="ignore"), use_container_width=True)

        st.subheader("Add a new rule")
        st.caption("Pick a row from Other and add a rule that moves similar transactions into a category.")

        # Select a row index to build a rule from
        row_ids = other_df.index.tolist()
        chosen_idx = st.selectbox("Pick a row (index)", options=row_ids)
        example_text = str(df_view.loc[chosen_idx, "_combined_text"]) if chosen_idx is not None else ""

        st.write("Example text")
        st.code(example_text[:300] + ("..." if len(example_text) > 300 else ""))

        # Suggest a safe literal pattern by escaping the example
        default_pattern = re.escape(example_text.strip())[:200]

        new_category = st.text_input("New category name", "")
        new_pattern = st.text_input(
            "Rule pattern (regex)",
            value=default_pattern,
            help="Regex. Tip: keep it short (e.g. `twint` or `migros`).",
        )

        colA, colB = st.columns([1, 2])
        with colA:
            add_btn = st.button("Add rule")
        with colB:
            st.caption("When you add, the rule list updates immediately. Download rules.json below to save it.")

        if add_btn:
            cat = (new_category or "").strip()
            pat = (new_pattern or "").strip()
            if not cat:
                st.error("Please enter a category name.")
            elif not pat:
                st.error("Please enter a pattern.")
            else:
                # Validate regex
                try:
                    re.compile(pat, flags=re.IGNORECASE)
                except re.error as e:
                    st.error(f"Invalid regex: {e}")
                else:
                    updated = rules + [{"pattern": pat, "category": cat}]
                    _set_rules(updated)
                    st.success("Rule added.")
                    st.rerun()

    st.subheader("Rules")
    st.caption("Rules are stored in this browser session while the app runs. Download to persist.")

    # Save / load rules
    c1, c2 = st.columns(2)
    with c1:
        st.download_button(
            "Download rules.json",
            data=json.dumps(_get_rules(), ensure_ascii=False, indent=2).encode("utf-8"),
            file_name="rules.json",
            mime="application/json",
        )

    with c2:
        uploaded_rules = st.file_uploader("Upload rules.json", type=["json"], key="rules_upload")
        if uploaded_rules is not None:
            try:
                new_rules = json.loads(uploaded_rules.getvalue().decode("utf-8"))
                if isinstance(new_rules, list):
                    _set_rules(new_rules)
                    st.success("Loaded rules into this session.")
                    st.rerun()
                else:
                    st.error("rules.json must be a JSON list of objects with keys: pattern, category")
            except Exception as e:
                st.error("Could not read rules.json")
                st.exception(e)

    edited = st.data_editor(
        _get_rules(),
        num_rows="dynamic",
        use_container_width=True,
        key="rules_editor",
        column_config={
            "pattern": st.column_config.TextColumn("pattern (regex)", width="large"),
            "category": st.column_config.TextColumn("category", width="medium"),
        },
    )
    _set_rules(edited)

    # Optional: show totals by category
    with st.expander("Totals by category"):
        def _first_match(keys: list[str]) -> str | None:
            for c in df.columns:
                lc = str(c).lower()
                if any(k in lc for k in keys):
                    return c
            return None

        inflow_guess = _first_match(["gutschrift", "credit", "einzahlung", "inflow"]) or (df.columns[0] if len(df.columns) else None)
        outflow_guess = _first_match(["belastung", "debit", "auszahlung", "outflow"]) or (df.columns[0] if len(df.columns) else None)

        cc1, cc2 = st.columns(2)
        inflow_col = cc1.selectbox(
            "Inflow column",
            options=all_cols,
            index=all_cols.index(inflow_guess) if inflow_guess in all_cols else 0,
            key="tot_in",
        )
        outflow_col = cc2.selectbox(
            "Outflow column",
            options=all_cols,
            index=all_cols.index(outflow_guess) if outflow_guess in all_cols else 0,
            key="tot_out",
        )

        inc = _parse_amount_series(df[inflow_col]).fillna(0.0)
        out = _parse_amount_series(df[outflow_col]).fillna(0.0).abs()

        totals = pd.DataFrame({"income": inc, "expenses": out, "Category": cats}).groupby("Category").sum()
        totals["net"] = totals["income"] - totals["expenses"]
        totals = totals.sort_values("expenses", ascending=False)
        st.dataframe(totals, use_container_width=True)