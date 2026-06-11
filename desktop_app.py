from __future__ import annotations

from datetime import datetime
import re
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:  # pragma: no cover - import depends on installed Qt modules
    QWebEngineView = None

from cashflow_core import (
    APP_NAME,
    CsvReadOptions,
    PLOTS_DIR,
    apply_categories,
    build_cashflow_sankey,
    combine_text_columns,
    ensure_app_dirs,
    guess_inflow_column,
    guess_outflow_column,
    guess_text_columns,
    load_rules,
    parse_amount_series,
    read_csv_file,
    save_rules,
)


PREVIEW_DIR = Path(".preview")
LOGO_PATH = Path("assets/logo.svg")


def load_logo_pixmap(size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    if not LOGO_PATH.exists():
        return pixmap

    renderer = QSvgRenderer(str(LOGO_PATH))
    if not renderer.isValid():
        return pixmap

    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap


STYLE = """
QMainWindow, QWidget {
    background: #f8fafc;
    color: #111827;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}
QFrame#Sidebar {
    background: #0f172a;
    color: #e5e7eb;
}
QFrame#Panel {
    background: #ffffff;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
}
QLabel#Title {
    color: #f8fafc;
    font-size: 22px;
    font-weight: 700;
}
QLabel#Subtitle {
    color: #94a3b8;
}
QLabel#Logo {
    background: transparent;
}
QLabel#MetricValue {
    font-size: 22px;
    font-weight: 700;
    color: #0f172a;
}
QLabel#MetricLabel {
    color: #64748b;
    font-size: 12px;
}
QPushButton {
    background: #2563eb;
    border: none;
    border-radius: 6px;
    color: white;
    padding: 9px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #1d4ed8;
}
QPushButton:disabled {
    background: #94a3b8;
}
QPushButton#Secondary {
    background: #e2e8f0;
    color: #0f172a;
}
QPushButton#Secondary:hover {
    background: #cbd5e1;
}
QLineEdit, QComboBox, QSpinBox {
    background: white;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 7px;
}
QTabWidget::pane {
    border: 1px solid #e5e7eb;
    background: white;
    border-radius: 8px;
}
QTabBar::tab {
    background: #e2e8f0;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 9px 14px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: white;
    color: #1d4ed8;
}
QTableWidget {
    background: white;
    gridline-color: #e5e7eb;
    alternate-background-color: #f8fafc;
    selection-background-color: #dbeafe;
}
QHeaderView::section {
    background: #f1f5f9;
    color: #334155;
    border: none;
    border-right: 1px solid #e5e7eb;
    padding: 7px;
    font-weight: 600;
}
"""


class CashflowWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        ensure_app_dirs()
        self.setWindowTitle(APP_NAME)
        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(load_logo_pixmap(256)))
        self.resize(1320, 850)

        self.rules = load_rules()
        self.df: pd.DataFrame | None = None
        self.current_csv: Path | None = None
        self.current_fig = None
        self.current_summary = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_main(), stretch=1)
        self._set_ready_state(False)

    def _build_sidebar(self) -> QWidget:
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(280)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(22, 24, 22, 24)
        layout.setSpacing(14)

        logo = QLabel()
        logo.setObjectName("Logo")
        logo.setFixedSize(56, 56)
        if LOGO_PATH.exists():
            pixmap = load_logo_pixmap(56)
            logo.setPixmap(pixmap)
        layout.addWidget(logo)

        title = QLabel("Cashflow Sankey")
        title.setObjectName("Title")
        subtitle = QLabel("Desktop transaction explorer")
        subtitle.setObjectName("Subtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(10)

        self.open_button = QPushButton("Open CSV")
        self.open_button.clicked.connect(self.open_csv)
        layout.addWidget(self.open_button)

        self.file_label = QLabel("No CSV loaded")
        self.file_label.setObjectName("Subtitle")
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        layout.addSpacing(10)
        layout.addWidget(QLabel("CSV parsing"))
        self.sep_box = QComboBox()
        self.sep_box.addItems(["Auto", ";", ",", "\\t", "|"])
        self.decimal_box = QComboBox()
        self.decimal_box.addItems(["Auto", ".", ","])
        self.skip_auto = QCheckBox("Auto-detect header row")
        self.skip_auto.setChecked(True)
        self.skip_rows = QSpinBox()
        self.skip_rows.setRange(0, 80)
        self.skip_rows.setValue(0)
        self.skip_rows.setEnabled(False)
        self.skip_auto.toggled.connect(self.skip_rows.setDisabled)
        for widget in (self.sep_box, self.decimal_box, self.skip_auto, self.skip_rows):
            layout.addWidget(widget)

        reload_button = QPushButton("Reload CSV")
        reload_button.setObjectName("Secondary")
        reload_button.clicked.connect(self.reload_csv)
        layout.addWidget(reload_button)

        layout.addStretch(1)
        self.status_label = QLabel("Rules are saved locally in config/rules.json.")
        self.status_label.setObjectName("Subtitle")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        return side

    def _build_main(self) -> QWidget:
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        controls = QFrame()
        controls.setObjectName("Panel")
        controls_layout = QGridLayout(controls)
        controls_layout.setContentsMargins(16, 14, 16, 14)
        controls_layout.setHorizontalSpacing(12)
        controls_layout.setVerticalSpacing(8)

        self.inflow_box = QComboBox()
        self.outflow_box = QComboBox()
        self.text_table = QTableWidget(0, 2)
        self.text_table.setHorizontalHeaderLabels(["Use", "Text column"])
        self.text_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.text_table.verticalHeader().setVisible(False)
        self.text_table.setFixedHeight(118)

        self.min_amount = QSpinBox()
        self.min_amount.setRange(0, 100_000)
        self.min_amount.setSingleStep(10)

        self.refresh_button = QPushButton("Build plot")
        self.refresh_button.clicked.connect(self.refresh_plot)
        self.save_plot_button = QPushButton("Save plot")
        self.save_plot_button.clicked.connect(self.save_plot)

        controls_layout.addWidget(QLabel("Inflow column"), 0, 0)
        controls_layout.addWidget(QLabel("Outflow column"), 0, 1)
        controls_layout.addWidget(QLabel("Minimum amount"), 0, 2)
        controls_layout.addWidget(self.inflow_box, 1, 0)
        controls_layout.addWidget(self.outflow_box, 1, 1)
        controls_layout.addWidget(self.min_amount, 1, 2)
        controls_layout.addWidget(QLabel("Category text columns"), 2, 0, 1, 3)
        controls_layout.addWidget(self.text_table, 3, 0, 1, 3)
        controls_layout.addWidget(self.refresh_button, 4, 1)
        controls_layout.addWidget(self.save_plot_button, 4, 2)
        layout.addWidget(controls)

        metrics = QHBoxLayout()
        self.income_metric = self._metric_card("Income", "CHF 0.00")
        self.expense_metric = self._metric_card("Expenses", "CHF 0.00")
        self.net_metric = self._metric_card("Net", "CHF 0.00")
        metrics.addWidget(self.income_metric)
        metrics.addWidget(self.expense_metric)
        metrics.addWidget(self.net_metric)
        layout.addLayout(metrics)

        self.tabs = QTabWidget()
        self.dashboard_tab = QWidget()
        self.chart_tab = QWidget()
        self.data_tab = QWidget()
        self.categorize_tab = QWidget()
        self.rules_tab = QWidget()
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.chart_tab, "Plot")
        self.tabs.addTab(self.categorize_tab, "Categorize")
        self.tabs.addTab(self.rules_tab, "Rules")
        self.tabs.addTab(self.data_tab, "Data")
        layout.addWidget(self.tabs, stretch=1)

        self._build_dashboard_tab()
        self._build_chart_tab()
        self._build_categorize_tab()
        self._build_rules_tab()
        self._build_data_tab()
        return main

    def _metric_card(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("Panel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        value_label = QLabel(value)
        value_label.setObjectName("MetricValue")
        label_label = QLabel(label)
        label_label.setObjectName("MetricLabel")
        layout.addWidget(value_label)
        layout.addWidget(label_label)
        card.value_label = value_label  # type: ignore[attr-defined]
        return card

    def _build_dashboard_tab(self) -> None:
        layout = QVBoxLayout(self.dashboard_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        metrics = QHBoxLayout()
        self.savings_rate_metric = self._metric_card("Savings Rate", "0.0%")
        self.transaction_metric = self._metric_card("Transactions", "0")
        self.uncategorized_metric = self._metric_card("Uncategorized", "0")
        metrics.addWidget(self.savings_rate_metric)
        metrics.addWidget(self.transaction_metric)
        metrics.addWidget(self.uncategorized_metric)
        layout.addLayout(metrics)

        charts = QHBoxLayout()
        if QWebEngineView is None:
            self.category_view = QLabel("Category chart requires Qt WebEngine.")
            self.timeline_view = QLabel("Timeline chart requires Qt WebEngine.")
            self.category_view.setAlignment(Qt.AlignCenter)
            self.timeline_view.setAlignment(Qt.AlignCenter)
        else:
            self.category_view = QWebEngineView()
            self.timeline_view = QWebEngineView()
        charts.addWidget(self.category_view, stretch=1)
        charts.addWidget(self.timeline_view, stretch=1)
        layout.addLayout(charts, stretch=2)

        tables = QHBoxLayout()
        self.top_merchants_table = QTableWidget(0, 3)
        self.top_merchants_table.setHorizontalHeaderLabels(["Merchant", "Spent", "Transactions"])
        self.top_merchants_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.top_merchants_table.setAlternatingRowColors(True)
        self.top_merchants_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        self.category_table = QTableWidget(0, 4)
        self.category_table.setHorizontalHeaderLabels(["Category", "Income", "Expenses", "Net"])
        self.category_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.category_table.setAlternatingRowColors(True)
        self.category_table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        tables.addWidget(self.top_merchants_table, stretch=1)
        tables.addWidget(self.category_table, stretch=1)
        layout.addLayout(tables, stretch=1)
    def _build_chart_tab(self) -> None:
        layout = QVBoxLayout(self.chart_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        if QWebEngineView is None:
            fallback = QWidget()
            fallback_layout = QVBoxLayout(fallback)
            fallback_layout.setAlignment(Qt.AlignCenter)
            self.web_view = QLabel("Interactive preview is opened as a local HTML file.")
            self.web_view.setAlignment(Qt.AlignCenter)
            self.external_preview_button = QPushButton("Open interactive preview")
            self.external_preview_button.clicked.connect(self.open_preview_external)
            fallback_layout.addWidget(self.web_view)
            fallback_layout.addWidget(self.external_preview_button, alignment=Qt.AlignCenter)
            layout.addWidget(fallback)
        else:
            self.web_view = QWebEngineView()
            layout.addWidget(self.web_view)

    def _build_data_tab(self) -> None:
        layout = QVBoxLayout(self.data_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        self.preview_table = QTableWidget(0, 0)
        self.preview_table.setAlternatingRowColors(True)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.preview_table)

    def _build_categorize_tab(self) -> None:
        layout = QVBoxLayout(self.categorize_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        top = QHBoxLayout()
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search uncategorized transactions")
        self.search_box.textChanged.connect(self.refresh_uncategorized)
        top.addWidget(self.search_box, stretch=1)
        layout.addLayout(top)

        self.uncat_table = QTableWidget(0, 3)
        self.uncat_table.setHorizontalHeaderLabels(["Index", "Text", "Amount"])
        self.uncat_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.uncat_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.uncat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self.uncat_table, stretch=1)

        add = QFrame()
        add.setObjectName("Panel")
        add_layout = QGridLayout(add)
        add_layout.setContentsMargins(14, 12, 14, 12)
        self.new_pattern = QLineEdit()
        self.new_pattern.setPlaceholderText("Regex or merchant keyword")
        self.new_category = QLineEdit()
        self.new_category.setPlaceholderText("Category")
        pick_button = QPushButton("Use selected text")
        pick_button.setObjectName("Secondary")
        pick_button.clicked.connect(self.use_selected_uncategorized)
        add_button = QPushButton("Add rule")
        add_button.clicked.connect(self.add_rule_from_fields)
        add_layout.addWidget(QLabel("Pattern"), 0, 0)
        add_layout.addWidget(QLabel("Category"), 0, 1)
        add_layout.addWidget(self.new_pattern, 1, 0)
        add_layout.addWidget(self.new_category, 1, 1)
        add_layout.addWidget(pick_button, 1, 2)
        add_layout.addWidget(add_button, 1, 3)
        layout.addWidget(add)

    def _build_rules_tab(self) -> None:
        layout = QVBoxLayout(self.rules_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        self.rules_table = QTableWidget(0, 2)
        self.rules_table.setHorizontalHeaderLabels(["Pattern", "Category"])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.rules_table, stretch=1)

        buttons = QHBoxLayout()
        add_rule = QPushButton("New row")
        add_rule.setObjectName("Secondary")
        add_rule.clicked.connect(lambda: self.rules_table.insertRow(self.rules_table.rowCount()))
        remove_rule = QPushButton("Remove selected")
        remove_rule.setObjectName("Secondary")
        remove_rule.clicked.connect(self.remove_selected_rules)
        save_rule_button = QPushButton("Save rules")
        save_rule_button.clicked.connect(self.save_rules_from_table)
        buttons.addStretch(1)
        buttons.addWidget(add_rule)
        buttons.addWidget(remove_rule)
        buttons.addWidget(save_rule_button)
        layout.addLayout(buttons)
        self.populate_rules_table()

    def _set_ready_state(self, ready: bool) -> None:
        for widget in (
            self.inflow_box,
            self.outflow_box,
            self.text_table,
            self.min_amount,
            self.refresh_button,
            self.save_plot_button,
            self.tabs,
        ):
            widget.setEnabled(ready)

    def _read_options(self) -> CsvReadOptions:
        sep = self.sep_box.currentText()
        if sep == "\\t":
            sep = "\t"
        skip = None if self.skip_auto.isChecked() else self.skip_rows.value()
        return CsvReadOptions(sep=sep, decimal=self.decimal_box.currentText(), skip_rows=skip)

    def open_csv(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(self, "Open transactions CSV", "", "CSV Files (*.csv);;All Files (*)")
        if not file_name:
            return
        self.current_csv = Path(file_name)
        self.reload_csv()

    def reload_csv(self) -> None:
        if self.current_csv is None:
            return
        try:
            self.df = read_csv_file(self.current_csv, self._read_options())
        except Exception as exc:
            QMessageBox.critical(self, "CSV error", f"Could not read the CSV:\n{exc}")
            return
        self.file_label.setText(str(self.current_csv))
        self.populate_columns()
        self.populate_preview()
        self._set_ready_state(True)
        self.refresh_plot()

    def populate_columns(self) -> None:
        if self.df is None:
            return
        columns = [str(c) for c in self.df.columns]
        self.inflow_box.clear()
        self.outflow_box.clear()
        self.inflow_box.addItems(columns)
        self.outflow_box.addItems(columns)

        inflow = guess_inflow_column(self.df) or (columns[0] if columns else "")
        outflow = guess_outflow_column(self.df) or (columns[0] if columns else "")
        if inflow in columns:
            self.inflow_box.setCurrentText(inflow)
        if outflow in columns:
            self.outflow_box.setCurrentText(outflow)

        guessed_text = set(guess_text_columns(self.df))
        self.text_table.setRowCount(len(columns))
        for row, column in enumerate(columns):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if column in guessed_text else Qt.Unchecked)
            self.text_table.setItem(row, 0, check)
            self.text_table.setItem(row, 1, QTableWidgetItem(column))
        self.text_table.resizeColumnsToContents()

    def selected_text_columns(self) -> list[str]:
        columns: list[str] = []
        for row in range(self.text_table.rowCount()):
            check = self.text_table.item(row, 0)
            name = self.text_table.item(row, 1)
            if check and name and check.checkState() == Qt.Checked:
                columns.append(name.text())
        return columns

    def filtered_df(self) -> pd.DataFrame:
        assert self.df is not None
        df = self.df.copy()
        if self.min_amount.value() <= 0:
            return df
        inflow = parse_amount_series(df[self.inflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0)
        outflow = parse_amount_series(df[self.outflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0).abs()
        return df[(inflow + outflow) >= self.min_amount.value()]

    def refresh_plot(self) -> None:
        if self.df is None:
            return
        try:
            df = self.filtered_df()
            text_cols = self.selected_text_columns()
            text_series = combine_text_columns(df, text_cols) if text_cols else None
            fig, summary = build_cashflow_sankey(
                df,
                self.inflow_box.currentText(),
                self.outflow_box.currentText(),
                text_series,
                self.rules,
                title=self.current_csv.stem if self.current_csv else "Cash Flow",
                decimal_override=self.decimal_box.currentText(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Plot error", f"Could not build the Sankey plot:\n{exc}")
            return

        self.current_fig = fig
        self.current_summary = summary
        self.income_metric.value_label.setText(f"CHF {summary.total_in:,.2f}")  # type: ignore[attr-defined]
        self.expense_metric.value_label.setText(f"CHF {summary.total_out:,.2f}")  # type: ignore[attr-defined]
        self.net_metric.value_label.setText(f"CHF {summary.net:,.2f}")  # type: ignore[attr-defined]
        html = fig.to_html(include_plotlyjs=True, full_html=True)
        if QWebEngineView is None:
            self.web_view.setText("Plot built. Open the interactive preview or save it to generated Plots.")
        else:
            self.web_view.setHtml(html)
        self.refresh_uncategorized()
        self.refresh_dashboard(df)

    def open_preview_external(self) -> None:
        if self.current_fig is None:
            return
        PREVIEW_DIR.mkdir(exist_ok=True)
        preview_path = PREVIEW_DIR / "cashflow_preview.html"
        self.current_fig.write_html(str(preview_path), include_plotlyjs="cdn", full_html=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(preview_path.resolve())))

    def _date_column(self) -> str | None:
        if self.df is None:
            return None
        keys = ["buchungsdatum", "abschlussdatum", "valutadatum", "date", "datum"]
        for column in self.df.columns:
            lc = str(column).lower()
            if any(key in lc for key in keys):
                return str(column)
        return None

    def dashboard_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        text_cols = self.selected_text_columns()
        combined = combine_text_columns(df, text_cols)
        categories = apply_categories(combined, self.rules)
        inflow = parse_amount_series(df[self.inflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0)
        outflow = parse_amount_series(df[self.outflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0).abs()
        merchant = combined.map(self._merchant_from_text)

        date_col = self._date_column()
        if date_col and date_col in df.columns:
            dates = pd.to_datetime(df[date_col], errors="coerce", dayfirst=False)
        else:
            dates = pd.Series(pd.NaT, index=df.index)

        return pd.DataFrame(
            {
                "Text": combined,
                "Merchant": merchant,
                "Category": categories,
                "Income": inflow,
                "Expenses": outflow,
                "Net": inflow - outflow,
                "Date": dates,
            },
            index=df.index,
        )

    @staticmethod
    def _merchant_from_text(text: str) -> str:
        text = str(text or "").strip()
        if not text:
            return "Unknown"
        first = re.split(r"[;|]", text, maxsplit=1)[0].strip()
        return first[:80] if first else text[:80]

    def refresh_dashboard(self, df: pd.DataFrame | None = None) -> None:
        if self.df is None:
            return
        if df is None:
            df = self.filtered_df()

        dashboard = self.dashboard_frame(df)
        income = float(dashboard["Income"].sum())
        expenses = float(dashboard["Expenses"].sum())
        net = income - expenses
        savings_rate = (net / income * 100) if income else 0.0
        uncategorized = int((dashboard["Category"] == "Other").sum())

        self.savings_rate_metric.value_label.setText(f"{savings_rate:.1f}%")  # type: ignore[attr-defined]
        self.transaction_metric.value_label.setText(f"{len(dashboard):,}")  # type: ignore[attr-defined]
        self.uncategorized_metric.value_label.setText(f"{uncategorized:,}")  # type: ignore[attr-defined]

        self._refresh_category_breakdown(dashboard)
        self._refresh_top_merchants(dashboard)
        self._refresh_timeline(dashboard)

    def _refresh_category_breakdown(self, dashboard: pd.DataFrame) -> None:
        category_totals = (
            dashboard.groupby("Category", dropna=False)[["Income", "Expenses", "Net"]]
            .sum()
            .sort_values("Expenses", ascending=False)
        )
        display = category_totals.head(12).copy()
        self.category_table.setRowCount(len(display))
        for row, (category, values) in enumerate(display.iterrows()):
            self.category_table.setItem(row, 0, QTableWidgetItem(str(category)))
            self.category_table.setItem(row, 1, QTableWidgetItem(f"CHF {float(values['Income']):,.2f}"))
            self.category_table.setItem(row, 2, QTableWidgetItem(f"CHF {float(values['Expenses']):,.2f}"))
            self.category_table.setItem(row, 3, QTableWidgetItem(f"CHF {float(values['Net']):,.2f}"))
        self.category_table.resizeColumnsToContents()
        self.category_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        spend = display[display["Expenses"] > 0].sort_values("Expenses", ascending=True)
        fig = go.Figure(
            go.Bar(
                x=spend["Expenses"],
                y=spend.index.astype(str),
                orientation="h",
                marker_color="#2563eb",
                hovertemplate="%{y}<br>CHF %{x:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            title="Spending by Category",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            font=dict(family="Inter, Segoe UI, Arial", size=12),
            margin=dict(l=130, r=20, t=48, b=34),
            xaxis_title="CHF",
            yaxis_title="",
            height=360,
        )
        if QWebEngineView is None:
            self.category_view.setText("Category chart requires Qt WebEngine.")
        else:
            self.category_view.setHtml(fig.to_html(include_plotlyjs=True, full_html=True))

    def _refresh_top_merchants(self, dashboard: pd.DataFrame) -> None:
        merchants = (
            dashboard[dashboard["Expenses"] > 0]
            .groupby("Merchant", dropna=False)
            .agg(Spent=("Expenses", "sum"), Transactions=("Expenses", "count"))
            .sort_values("Spent", ascending=False)
            .head(12)
        )
        self.top_merchants_table.setRowCount(len(merchants))
        for row, (merchant, values) in enumerate(merchants.iterrows()):
            self.top_merchants_table.setItem(row, 0, QTableWidgetItem(str(merchant)))
            self.top_merchants_table.setItem(row, 1, QTableWidgetItem(f"CHF {float(values['Spent']):,.2f}"))
            self.top_merchants_table.setItem(row, 2, QTableWidgetItem(str(int(values["Transactions"]))))
        self.top_merchants_table.resizeColumnsToContents()
        self.top_merchants_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def _refresh_timeline(self, dashboard: pd.DataFrame) -> None:
        dated = dashboard.dropna(subset=["Date"]).copy()
        if dated.empty:
            ordered = dashboard.reset_index(drop=True).copy()
            ordered["Step"] = ordered.index + 1
            ordered["Cumulative Net"] = ordered["Net"].cumsum()
            fig = go.Figure(
                go.Scatter(
                    x=ordered["Step"],
                    y=ordered["Cumulative Net"],
                    mode="lines+markers",
                    line=dict(color="#0f172a", width=3),
                    hovertemplate="Transaction %{x}<br>CHF %{y:,.2f}<extra></extra>",
                )
            )
            fig.update_layout(xaxis_title="Transaction", title="Cumulative Net Cashflow")
        else:
            daily = dated.groupby(dated["Date"].dt.date)[["Income", "Expenses", "Net"]].sum().sort_index()
            daily["Cumulative Net"] = daily["Net"].cumsum()
            fig = go.Figure()
            fig.add_bar(
                x=daily.index,
                y=daily["Income"],
                name="Income",
                marker_color="#16a34a",
                hovertemplate="Income<br>%{x}<br>CHF %{y:,.2f}<extra></extra>",
            )
            fig.add_bar(
                x=daily.index,
                y=-daily["Expenses"],
                name="Expenses",
                marker_color="#dc2626",
                hovertemplate="Expenses<br>%{x}<br>CHF %{customdata:,.2f}<extra></extra>",
                customdata=daily["Expenses"],
            )
            fig.add_scatter(
                x=daily.index,
                y=daily["Cumulative Net"],
                name="Cumulative net",
                mode="lines+markers",
                line=dict(color="#0f172a", width=3),
                hovertemplate="Cumulative net<br>%{x}<br>CHF %{y:,.2f}<extra></extra>",
            )
            fig.update_layout(xaxis_title="Date", title="Daily Cashflow")

        fig.update_layout(
            barmode="relative",
            paper_bgcolor="#ffffff",
            plot_bgcolor="#ffffff",
            font=dict(family="Inter, Segoe UI, Arial", size=12),
            margin=dict(l=54, r=24, t=48, b=42),
            yaxis_title="CHF",
            height=360,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        if QWebEngineView is None:
            self.timeline_view.setText("Timeline chart requires Qt WebEngine.")
        else:
            self.timeline_view.setHtml(fig.to_html(include_plotlyjs=True, full_html=True))
    def populate_preview(self) -> None:
        if self.df is None:
            return
        preview = self.df.head(200)
        self.preview_table.setRowCount(len(preview))
        self.preview_table.setColumnCount(len(preview.columns))
        self.preview_table.setHorizontalHeaderLabels([str(c) for c in preview.columns])
        for r, (_, row) in enumerate(preview.iterrows()):
            for c, value in enumerate(row):
                self.preview_table.setItem(r, c, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.preview_table.resizeColumnsToContents()

    def categorized_frame(self) -> pd.DataFrame:
        assert self.df is not None
        text_cols = self.selected_text_columns()
        combined = combine_text_columns(self.df, text_cols)
        cats = apply_categories(combined, self.rules)
        amount = pd.Series(0.0, index=self.df.index)
        if self.inflow_box.currentText() and self.outflow_box.currentText():
            inc = parse_amount_series(self.df[self.inflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0)
            out = parse_amount_series(self.df[self.outflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0)
            amount = inc + out
        return pd.DataFrame({"Text": combined, "Category": cats, "Amount": amount}, index=self.df.index)

    def refresh_uncategorized(self) -> None:
        if self.df is None:
            return
        categorized = self.categorized_frame()
        other = categorized[categorized["Category"] == "Other"].copy()
        search = self.search_box.text().strip()
        if search:
            other = other[other["Text"].str.contains(search, case=False, na=False)]

        self.uncat_table.setRowCount(len(other))
        for row, (idx, data) in enumerate(other.iterrows()):
            self.uncat_table.setItem(row, 0, QTableWidgetItem(str(idx)))
            self.uncat_table.setItem(row, 1, QTableWidgetItem(str(data["Text"])))
            self.uncat_table.setItem(row, 2, QTableWidgetItem(f"{float(data['Amount']):,.2f}"))
        self.uncat_table.resizeColumnsToContents()
        self.uncat_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

    def use_selected_uncategorized(self) -> None:
        selected = self.uncat_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        text_item = self.uncat_table.item(row, 1)
        if not text_item:
            return
        words = re.findall(r"[\w./-]{4,}", text_item.text(), flags=re.UNICODE)
        self.new_pattern.setText(re.escape(words[0]) if words else re.escape(text_item.text()[:80]))

    def add_rule_from_fields(self) -> None:
        pattern = self.new_pattern.text().strip()
        category = self.new_category.text().strip()
        if not pattern or not category:
            QMessageBox.warning(self, "Missing rule", "Enter both a pattern and a category.")
            return
        try:
            re.compile(pattern, flags=re.IGNORECASE)
        except re.error as exc:
            QMessageBox.warning(self, "Invalid regex", str(exc))
            return
        self.rules.append({"pattern": pattern, "category": category})
        save_rules(self.rules)
        self.populate_rules_table()
        self.new_pattern.clear()
        self.new_category.clear()
        self.refresh_plot()

    def populate_rules_table(self) -> None:
        self.rules_table.setRowCount(len(self.rules))
        for row, rule in enumerate(self.rules):
            self.rules_table.setItem(row, 0, QTableWidgetItem(rule.get("pattern", "")))
            self.rules_table.setItem(row, 1, QTableWidgetItem(rule.get("category", "")))

    def remove_selected_rules(self) -> None:
        rows = sorted({item.row() for item in self.rules_table.selectedItems()}, reverse=True)
        for row in rows:
            self.rules_table.removeRow(row)

    def save_rules_from_table(self) -> None:
        rules: list[dict[str, str]] = []
        for row in range(self.rules_table.rowCount()):
            pattern_item = self.rules_table.item(row, 0)
            category_item = self.rules_table.item(row, 1)
            pattern = pattern_item.text().strip() if pattern_item else ""
            category = category_item.text().strip() if category_item else ""
            if pattern and category:
                try:
                    re.compile(pattern, flags=re.IGNORECASE)
                except re.error as exc:
                    QMessageBox.warning(self, "Invalid regex", f"Row {row + 1}: {exc}")
                    return
                rules.append({"pattern": pattern, "category": category})
        self.rules = rules
        save_rules(self.rules)
        self.refresh_plot()
        QMessageBox.information(self, "Rules saved", "Rules were saved to config/rules.json.")

    def save_plot(self) -> None:
        if self.current_fig is None:
            return
        ensure_app_dirs()
        source = self.current_csv.stem if self.current_csv else "cashflow"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        html_path = PLOTS_DIR / f"{source}_sankey_{stamp}.html"
        self.current_fig.write_html(str(html_path), include_plotlyjs="cdn", full_html=True)

        png_note = ""
        try:
            png_path = PLOTS_DIR / f"{source}_sankey_{stamp}.png"
            self.current_fig.write_image(str(png_path), scale=2)
            png_note = f"\nPNG: {png_path}"
        except Exception:
            png_note = "\nPNG export skipped. Install/repair kaleido if you also want static PNG output."

        QMessageBox.information(self, "Plot saved", f"Interactive HTML: {html_path}{png_note}")


def main() -> int:
    app = QApplication(sys.argv)
    if LOGO_PATH.exists():
        app.setWindowIcon(QIcon(load_logo_pixmap(256)))
    app.setStyleSheet(STYLE)
    window = CashflowWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
