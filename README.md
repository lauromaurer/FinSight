# FinSight

A local desktop app that turns a monthly bank CSV export into a categorized
Dashboard and Money flow diagram — no server, no cloud, all processing stays
on your machine.

## Overview

FinSight reads transaction exports from your bank's CSV download, auto-detects
the delimiter/encoding/header row (bank exports often have a few descriptive
lines before the real header, which trips up a plain `pd.read_csv`), and
categorizes each transaction against a local rule set you build up over time.
It's built for a simple monthly habit, **Import → Review → Dashboard**: at the
end of the month, Import that month's export, file any new Merchants under a
Category in Review, and get an immediate read on where the money went — Income,
Expenses and Saved, a Category table, and the Money flow from Income into
Expense Categories. Rules, Categories and import overrides live under Advanced. Everything (rules, categories, imported CSVs, exported Money flow
files) is kept in your per-user data folder, so nothing needs to be re-entered
or re-uploaded between sessions (see [Your data](#your-data)).

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
- **Plotly** — the interactive Money flow diagram, embedded in-app via Qt
  WebEngine when available, or opened as a local HTML file otherwise; it is
  exported as HTML.
- **PyInstaller** — packages the app into a standalone `.exe` (Windows) or
  `.app` (macOS) bundle.

## How it works

1. **Import** — pick a CSV via the file picker; it's copied into
   `imports/` in your data folder for local reuse and re-analysis without
   re-picking the file.
2. **Analyze a month** — `month_analysis.analyze_month` is the one pure
   entry point (CSV bytes + Rules + optional import overrides in, a
   `MonthAnalysis` out). It sniffs the encoding, delimiter, decimal mark and
   header row, guesses the Income, Expenses and text columns (overridable in
   Advanced), and returns "columns need checking" when it can't find them.
3. **Categorize** — inside the same call, each transaction's text is matched
   against the Rules (`rules.json` in your data folder). A match assigns a
   Category and, optionally, a Merchant name. Transactions no Rule matches are
   **Uncategorized** (Other is an ordinary Category you pick on purpose) and
   are grouped by Merchant for Review, where saving a Rule files them next time.
4. **Dashboard** — the totals (Income, Expenses, Saved), the Category
   table and the Money flow are all drawn from the
   same `MonthAnalysis`, so their numbers always agree. In the Money flow,
   Income Categories flow into the month, which flows out into Expense
   Categories and Saved.
5. **Export** — save the current Money flow as HTML to `money-flow/` in your
   data folder.

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

If your Python/Qt install has WebEngine available, the Money flow renders
inside the app. Otherwise, use the **Open Money flow** button — it
opens the same diagram as a local HTML file in your browser while the rest of
the app (CSV import, categorization, rules) keeps working normally.

### Releases

Releases are built by CI. Pushing a version tag builds both platforms:

```bash
git tag v1.1
git push origin v1.1
```

`.github/workflows/release.yml` then, on `windows-latest` and `macos-latest`:

1. builds the app from the one shared build definition, `FinSight.spec`;
2. runs the built app's `--self-check` (`tests/test_frozen_app.py`);
3. zips each build (`FinSight-v1.1-Windows.zip`, `FinSight-v1.1-macOS.zip`);
4. creates a GitHub Release for the tag with both zips attached.

If either built app fails its self-check, the workflow fails and no Release
is published. Running the workflow by hand (Actions → Release → Run workflow)
or pushing a branch that changes `FinSight.spec`, `requirements.txt` or the
workflow is a dry run: same build and self-check, with the zips kept as
workflow artifacts and no Release. Build output (`build/`, `dist/`,
`release/`) is git-ignored and never committed. The Windows zip holds the
`FinSight` folder: keep `FinSight.exe` next to its `_internal` folder. The
builds are not code-signed, so macOS Gatekeeper and Windows SmartScreen warn
on first launch.

### Building a standalone app by hand

Both scripts just run `FinSight.spec` from a local `.venv` and zip the result
into `release/`:

```bash
./build_mac.sh        # macOS   -> dist/FinSight.app, release/FinSight macOS.zip
```

```powershell
.\build_exe.bat      # Windows -> dist\FinSight\FinSight.exe, release\FinSight Windows.zip
```

To self-check a local build:
`FINSIGHT_FROZEN_APP=dist/FinSight.app/Contents/MacOS/FinSight python -m pytest tests/test_frozen_app.py`.

## Project structure

```
FinSight/
├── src/finsight/
│   ├── __main__.py        # `python -m finsight`
│   ├── desktop_app.py     # PySide6 GUI
│   ├── data_store.py      # everything FinSight keeps on disk (per-user data folder)
│   ├── month_analysis.py  # analyze a month: CSV detection, Rules, totals, Money flow data
│   ├── money_flow_chart.py # draws the Money flow (Plotly)
│   ├── check_columns.py   # the Check your columns dialog
│   └── finsight_core.py   # bundled defaults (starter Rules, Categories)
├── assets/                 # app logo/icon (svg, ico, icns)
├── default_categories.json # starter Categories bundled into releases
├── tests/                  # pytest suite
├── FinSight.spec            # the one PyInstaller build spec (Windows + macOS)
└── build_mac.sh / build_exe.bat
```

## Your data

FinSight keeps your rules, categories, imported CSVs and exported Money flow
files in the standard per-user data folder (see
[ADR-0001](docs/adr/0001-user-data-in-per-user-app-data-folder.md)), never next
to the app or in the folder it was launched from:

- macOS: `~/Library/Application Support/FinSight`
- Windows: `%APPDATA%\FinSight`

Advanced > Data folder shows the exact location and can open it. On first launch,
data from an older version (a `config/` folder next to the app or in the
working directory, or a legacy `rules.json`) is copied in once; existing data
is never overwritten. Interactive previews are written to a temp folder.

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
