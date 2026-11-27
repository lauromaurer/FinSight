# FinSight

A local desktop app that turns a monthly bank CSV export into a categorized
spending dashboard and cash-flow diagram — no server, no cloud upload, all
processing stays on your machine.

## Overview

FinSight reads transaction exports from your bank's CSV download, auto-detects
the delimiter/encoding/header row (bank exports often have a few descriptive
lines before the real header, which trips up a plain `pd.read_csv`), and
categorizes each transaction against a local rule set you build up over time.
It's built for a simple monthly habit: at the end of the month, import that
month's export and get an immediate read on where the money went — a KPI
summary, a category breakdown, top merchants, a daily flow chart, and a
Sankey-style diagram of income flowing through a cash-flow hub into expense
categories. Everything (rules, categories, uploaded CSVs, generated plots) is
kept in local folders next to the app, so nothing needs to be re-entered or
re-uploaded between sessions.

The project started as a Streamlit web prototype and was later rewritten as a
PySide6 desktop app — running fully locally turned out simpler and more
stable than routing personal financial data through a local web server, and
it packages into a standalone Windows/macOS app that doesn't need Python
installed to run.

## Tech stack

- **PySide6** — desktop GUI (chosen over the Streamlit prototype for a
  fully local, no-server experience).
- **pandas** — CSV parsing, delimiter/encoding detection, categorization,
  and aggregation.
- **Plotly** (+ **Kaleido** for static export) — the interactive cash-flow
  diagram, embedded in-app via Qt WebEngine when available, or opened as a
  local HTML file otherwise.
- **PyInstaller** — packages the app into a standalone `.exe` (Windows) or
  `.app` (macOS) bundle.

## How it works

1. **Import** — pick a CSV via the file picker; it's copied into
   `uploaded CSV files/` for local reuse and re-analysis without re-picking
   the file.
2. **Analyze a month** — `month_analysis.analyze_month` is the one pure
   entry point (CSV bytes + Rules + optional import overrides in, a
   `MonthAnalysis` out). It sniffs the encoding, delimiter, decimal mark and
   header row, guesses the Income, Expenses and text columns (overridable in
   Settings), and returns "columns need checking" when it can't find them.
3. **Categorize** — inside the same call, each transaction's text is matched
   against the Rules (`config/rules.json`). A match assigns a Category and,
   optionally, a Merchant name. Transactions no Rule matches are
   **Uncategorized** (Other is an ordinary Category you pick on purpose) and
   are grouped by Merchant for Review, where saving a Rule files them next time.
4. **Visualize** — the Dashboard (Income, Expenses, Saved, the Category
   table, top Merchants, daily flow) and the Money flow are all drawn from the
   same `MonthAnalysis`, so their numbers always agree. In the Money flow,
   Income Categories flow into the month, which flows out into Expense
   Categories and Saved.
5. **Export** — save the current chart to `generated Plots/` as HTML by
   default, or PNG when Kaleido is available.

## Getting started

```bash
python -m venv .venv
source .venv/bin/activate      # .\.venv\Scripts\Activate.ps1 on Windows
pip install -r requirements.txt
python src/finsight/desktop_app.py   # works from any folder
```

`python src/finsight/desktop_app.py --self-check` starts the app without a
window, checks that the core modules and bundled files load, and exits 0 on
success (non-zero on failure).

### Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

CI runs the tests on Windows and macOS on every push and pull request
(`.github/workflows/tests.yml`).

If your Python/Qt install has WebEngine available, the Plotly chart renders
inside the app. Otherwise, use the **Open interactive preview** button — it
opens the same chart as a local HTML file in your browser while the rest of
the app (CSV import, categorization, rules) keeps working normally.

### Building a standalone app

**macOS** (run on a Mac):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./build_mac.sh
```

Produces `dist/FinSight.app`, zipped to `release/FinSight macOS.zip`.

**Windows:**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
.\build_exe.bat
```

Produces `dist\FinSight\FinSight.exe`. Share the whole `dist\FinSight\`
folder (or `release\FinSight Windows.zip`) — the `.exe` depends on the
bundled `_internal` files next to it.

## Project structure

```
FinSight/
├── src/finsight/
│   ├── __main__.py        # `python -m finsight`
│   ├── desktop_app.py     # PySide6 GUI
│   └── finsight_core.py   # CSV parsing, categorization, flow generation
├── assets/                 # app logo/icon (svg, ico, icns)
├── default_categories.json # starter category labels bundled into releases
├── tests/                  # pytest suite
├── FinSight.spec            # PyInstaller build spec
├── build_mac.sh / build_exe.bat
└── config/, generated Plots/, uploaded CSV files/   # created on first run
```

`config/`, `generated Plots/`, and `uploaded CSV files/` hold local rules and
personal financial data — they're created automatically and excluded from
git (see `.gitignore`).

## Status / roadmap

Actively used month by month for personal budgeting — at the end of each
month I import that month's export and review the dashboard. It's a
finished, working tool rather than a polished product: the currency display
is hardcoded to CHF throughout the UI and chart code (a real limitation if
you use a different currency — there's no settings/config for it yet), and
the starter category rules are intentionally generic rather than tuned to
any particular bank or country.

## License

MIT — see [LICENSE](LICENSE).
