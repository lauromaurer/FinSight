# Cashflow Sankey

A desktop app for turning card transaction CSV exports into an interactive cashflow Sankey plot.

The app keeps category rules locally, so you do not need to upload a `rules.json` file every time. It also reads bank CSV exports with descriptive metadata lines before the real header, so the CSV can be loaded without manual cleanup.

## Features

- Desktop GUI built with PySide6.
- CSV import through a file picker.
- Automatic delimiter, encoding, and header-row detection.
- Local category rules in `config/rules.json`.
- Rule editor for uncategorized transactions.
- Interactive Plotly Sankey preview.
- Dashboard tab with KPI cards, category spending, daily cashflow, top merchants, and uncategorized count.
- One-click export to `generated Plots`.
- HTML export by default, with PNG export when Kaleido is available.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Run

```powershell
python desktop_app.py
```

The older Streamlit prototype is still available:

```powershell
streamlit run main.py
```

If your Python installation has Qt WebEngine available, the Plotly chart appears inside the app. Otherwise, use the **Open interactive preview** button; it opens a local HTML preview in your browser while keeping the CSV/rules workflow in the desktop app.

## Project Files

- `desktop_app.py` - desktop GUI.
- `assets/logo.svg` - app logo and window icon.
- `cashflow_core.py` - CSV parsing, categorization, Sankey generation, rule persistence.
- `main.py` - original Streamlit app.
- `config/rules.json` - created automatically on first run.
- `generated Plots/` - created automatically for saved plots.

## Suggested Git Usage

Transaction CSVs are personal financial data, so they are ignored by default. Keep anonymized sample files only if you intentionally want them in the repository.
