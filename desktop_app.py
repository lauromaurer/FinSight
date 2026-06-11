from __future__ import annotations

from datetime import datetime
import re
import shutil
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
    QButtonGroup,
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
    UPLOADS_DIR,
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

def resource_path(relative_path: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return base / relative_path

LOGO_PATH = resource_path("assets/logo.svg")


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
QPushButton#NavButton {
    background: transparent;
    color: #cbd5e1;
    text-align: left;
    padding: 10px 12px;
    border-radius: 6px;
    font-weight: 600;
}
QPushButton#NavButton:hover {
    background: #1e293b;
    color: #f8fafc;
}
QPushButton#NavButton:checked {
    background: #2563eb;
    color: #ffffff;
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
        self.source_csv: Path | None = None
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
        side.setFixedWidth(180)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(18, 24, 18, 24)
        layout.setSpacing(16)

        logo = QLabel()
        logo.setObjectName("Logo")
        logo.setFixedSize(56, 56)
        if LOGO_PATH.exists():
            logo.setPixmap(load_logo_pixmap(56))
        layout.addWidget(logo, alignment=Qt.AlignHCenter)

        self.open_button = QPushButton("Load CSV")
        self.open_button.clicked.connect(self.open_csv)
        layout.addWidget(self.open_button)

        self.nav_group = QButtonGroup(side)
        self.nav_group.setExclusive(True)
        self.nav_buttons = []
        for index, label in enumerate(["Dashboard", "Plot", "Categorize", "Rules", "Data", "Settings"]):
            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, i=index: self.show_page(i))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)
        self.nav_buttons[0].setChecked(True)
        layout.addStretch(1)
        return side

    def _build_main(self) -> QWidget:
        main = QWidget()
        layout = QVBoxLayout(main)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.dashboard_tab = QWidget()
        self.chart_tab = QWidget()
        self.categorize_tab = QWidget()
        self.rules_tab = QWidget()
        self.data_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.chart_tab, "Plot")
        self.tabs.addTab(self.categorize_tab, "Categorize")
        self.tabs.addTab(self.rules_tab, "Rules")
        self.tabs.addTab(self.data_tab, "Data")
        self.tabs.addTab(self.settings_tab, "Settings")
        layout.addWidget(self.tabs, stretch=1)
        self.tabs.currentChanged.connect(self.sync_sidebar_navigation)

        self._build_dashboard_tab()
        self._build_chart_tab()
        self._build_categorize_tab()
        self._build_rules_tab()
        self._build_data_tab()
        self._build_settings_tab()
        return main

    def show_page(self, index: int) -> None:
        if hasattr(self, "tabs"):
            self.tabs.setCurrentIndex(index)

    def sync_sidebar_navigation(self, index: int) -> None:
        if hasattr(self, "nav_buttons") and 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)

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
        self.total_outflow_metric = self._metric_card("Total Outflow", "CHF 0.00")
        self.total_inflow_metric = self._metric_card("Total Inflow", "CHF 0.00")
        self.total_saved_metric = self._metric_card("Total Saved", "CHF 0.00")
        metrics.addWidget(self.total_outflow_metric)
        metrics.addWidget(self.total_inflow_metric)
        metrics.addWidget(self.total_saved_metric)
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
        layout.setSpacing(10)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.save_plot_button = QPushButton("Save plot")
        self.save_plot_button.clicked.connect(self.save_plot)
        actions.addWidget(self.save_plot_button)
        layout.addLayout(actions)

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
            layout.addWidget(fallback, stretch=1)
        else:
            self.web_view = QWebEngineView()
            layout.addWidget(self.web_view, stretch=1)

    def _load_plotly_preview(self, view: QWidget, filename: str, fig: go.Figure) -> None:
        PREVIEW_DIR.mkdir(exist_ok=True)
        preview_path = PREVIEW_DIR / filename
        fig.write_html(str(preview_path), include_plotlyjs=True, full_html=True)
        if QWebEngineView is None:
            return
        view.load(QUrl.fromLocalFile(str(preview_path.resolve())))

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

        self.uncat_table = QTableWidget(0, 5)
        self.uncat_table.setHorizontalHeaderLabels(["Rows", "Merchant", "Suggested Category", "Example Text", "Total Amount"])
        self.uncat_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
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
        self.new_merchant = QLineEdit()
        self.new_merchant.setPlaceholderText("Merchant alias")
        pick_button = QPushButton("Use selected text")
        pick_button.setObjectName("Secondary")
        pick_button.clicked.connect(self.use_selected_uncategorized)
        add_button = QPushButton("Add rule")
        add_button.clicked.connect(self.add_rule_from_fields)
        add_layout.addWidget(QLabel("Pattern"), 0, 0)
        add_layout.addWidget(QLabel("Category"), 0, 1)
        add_layout.addWidget(QLabel("Merchant"), 0, 2)
        add_layout.addWidget(self.new_pattern, 1, 0)
        add_layout.addWidget(self.new_category, 1, 1)
        add_layout.addWidget(self.new_merchant, 1, 2)
        add_layout.addWidget(pick_button, 1, 3)
        add_layout.addWidget(add_button, 1, 4)
        layout.addWidget(add)

    def _build_rules_tab(self) -> None:
        layout = QVBoxLayout(self.rules_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        self.rules_table = QTableWidget(0, 3)
        self.rules_table.setHorizontalHeaderLabels(["Pattern", "Category", "Merchant"])
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

    def _build_settings_tab(self) -> None:
        layout = QVBoxLayout(self.settings_tab)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        info = QFrame()
        info.setObjectName("Panel")
        info_layout = QGridLayout(info)
        info_layout.setContentsMargins(16, 14, 16, 14)
        info_layout.setHorizontalSpacing(12)
        info_layout.setVerticalSpacing(10)

        self.file_label = QLabel("No CSV loaded")
        self.file_label.setWordWrap(True)
        self.uploaded_file_label = QLabel(f"Uploaded CSVs are saved in: {UPLOADS_DIR}")
        self.uploaded_file_label.setWordWrap(True)
        self.status_label = QLabel("Rules are saved locally in config/rules.json.")
        self.status_label.setWordWrap(True)
        info_layout.addWidget(QLabel("Current CSV"), 0, 0)
        info_layout.addWidget(self.file_label, 0, 1)
        info_layout.addWidget(QLabel("Saved copy"), 1, 0)
        info_layout.addWidget(self.uploaded_file_label, 1, 1)
        info_layout.addWidget(QLabel("Rules"), 2, 0)
        info_layout.addWidget(self.status_label, 2, 1)
        layout.addWidget(info)

        settings = QFrame()
        settings.setObjectName("Panel")
        settings_layout = QGridLayout(settings)
        settings_layout.setContentsMargins(16, 14, 16, 14)
        settings_layout.setHorizontalSpacing(12)
        settings_layout.setVerticalSpacing(10)

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

        self.inflow_box = QComboBox()
        self.outflow_box = QComboBox()
        self.min_amount = QSpinBox()
        self.min_amount.setRange(0, 100_000)
        self.min_amount.setSingleStep(10)

        self.text_table = QTableWidget(0, 2)
        self.text_table.setHorizontalHeaderLabels(["Use", "Text column"])
        self.text_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.text_table.verticalHeader().setVisible(False)
        self.text_table.setFixedHeight(260)

        self.refresh_button = QPushButton("Apply settings")
        self.refresh_button.clicked.connect(self.refresh_plot)
        self.reload_button = QPushButton("Reload CSV")
        self.reload_button.setObjectName("Secondary")
        self.reload_button.clicked.connect(self.reload_csv)

        settings_layout.addWidget(QLabel("Delimiter"), 0, 0)
        settings_layout.addWidget(QLabel("Decimal"), 0, 1)
        settings_layout.addWidget(QLabel("Header row"), 0, 2)
        settings_layout.addWidget(self.sep_box, 1, 0)
        settings_layout.addWidget(self.decimal_box, 1, 1)
        settings_layout.addWidget(self.skip_auto, 1, 2)
        settings_layout.addWidget(QLabel("Manual rows to skip"), 2, 2)
        settings_layout.addWidget(self.skip_rows, 3, 2)

        settings_layout.addWidget(QLabel("Inflow column"), 4, 0)
        settings_layout.addWidget(QLabel("Outflow column"), 4, 1)
        settings_layout.addWidget(QLabel("Minimum amount"), 4, 2)
        settings_layout.addWidget(self.inflow_box, 5, 0)
        settings_layout.addWidget(self.outflow_box, 5, 1)
        settings_layout.addWidget(self.min_amount, 5, 2)
        settings_layout.addWidget(QLabel("Category text columns"), 6, 0, 1, 3)
        settings_layout.addWidget(self.text_table, 7, 0, 1, 3)
        settings_layout.addWidget(self.reload_button, 8, 1)
        settings_layout.addWidget(self.refresh_button, 8, 2)
        layout.addWidget(settings)
        layout.addStretch(1)

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
        source = Path(file_name)
        try:
            self.source_csv = source
            self.current_csv = self._store_uploaded_csv(source)
        except Exception as exc:
            QMessageBox.critical(self, "CSV storage error", f"Could not save a local copy of the CSV:\n{exc}")
            return
        self.reload_csv()

    def _store_uploaded_csv(self, source: Path) -> Path:
        ensure_app_dirs()
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = UPLOADS_DIR / f"{source.stem}_{stamp}{source.suffix or '.csv'}"
        shutil.copy2(source, destination)
        return destination
    def reload_csv(self) -> None:
        if self.current_csv is None:
            return
        try:
            self.df = read_csv_file(self.current_csv, self._read_options())
        except Exception as exc:
            QMessageBox.critical(self, "CSV error", f"Could not read the CSV:\n{exc}")
            return
        self.file_label.setText(str(self.source_csv or self.current_csv))
        self.uploaded_file_label.setText(str(self.current_csv))
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
                title=(self.source_csv.stem if self.source_csv else self.current_csv.stem) if self.current_csv else "Cash Flow",
                decimal_override=self.decimal_box.currentText(),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Plot error", f"Could not build the Sankey plot:\n{exc}")
            return

        self.current_fig = fig
        self.current_summary = summary
        if QWebEngineView is None:
            self.web_view.setText("Plot built. Open the interactive preview or save it to generated Plots.")
        else:
            self._load_plotly_preview(self.web_view, "sankey_preview.html", fig)
        self.refresh_uncategorized()
        self.refresh_dashboard(df)

    def open_preview_external(self) -> None:
        if self.current_fig is None:
            return
        PREVIEW_DIR.mkdir(exist_ok=True)
        preview_path = PREVIEW_DIR / "cashflow_preview.html"
        self.current_fig.write_html(str(preview_path), include_plotlyjs=True, full_html=True)
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

    def _match_rule(self, text: str) -> tuple[str, str]:
        text = str(text or "")
        for rule in self.rules:
            pattern = (rule.get("pattern") or "").strip()
            if not pattern:
                continue
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    category = (rule.get("category") or "").strip() or "Other"
                    merchant = (rule.get("merchant") or "").strip()
                    return category, merchant
            except re.error:
                continue
        return "Other", ""

    def _category_names(self) -> list[str]:
        categories = {str(rule.get("category", "")).strip() for rule in self.rules}
        categories.update({"Groceries", "Food & Drink", "Transport", "Shopping", "Subscriptions", "Telecom", "Health", "P2P"})
        return sorted(c for c in categories if c and c != "Other")

    def _suggest_category(self, merchant: str, text: str) -> str:
        sample = f"{merchant} {text}".lower()
        hints = [
            ("Groceries", ["migros", "coop", "aldi", "lidl", "denner", "supermarkt", "market"]),
            ("Food & Drink", ["restaurant", "cafe", "bar", "pizza", "kebab", "mcdonald", "burger", "bakery", "baeckerei"]),
            ("Transport", ["sbb", "cff", "ffs", "bahn", "rail", "bus", "train", "ticket", "uber", "taxi"]),
            ("Shopping", ["shop", "store", "amazon", "aliexpress", "zalando", "ikea", "galaxus"]),
            ("Subscriptions", ["apple.com/bill", "spotify", "netflix", "subscription", "abo"]),
            ("Telecom", ["yallo", "sunrise", "salt", "swisscom", "telecom"]),
            ("Health", ["apotheke", "pharmacy", "arzt", "doctor", "hirslanden"]),
            ("P2P", ["twint", "paypal"]),
        ]
        existing = set(self._category_names())
        for category, keywords in hints:
            if category in existing and any(keyword in sample for keyword in keywords):
                return category

        merchant_tokens = set(re.findall(r"[a-z0-9]{4,}", merchant.lower()))
        best_category = ""
        best_score = 0
        for category in existing:
            category_tokens = set(re.findall(r"[a-z0-9]{4,}", category.lower()))
            score = len(merchant_tokens & category_tokens)
            if score > best_score:
                best_category = category
                best_score = score
        if best_category:
            return best_category

        clean = re.sub(r"[^\w\s&+-]", " ", merchant, flags=re.UNICODE).strip()
        clean = re.sub(r"\s+", " ", clean)
        return clean[:40].title() if clean else "Other"

    def _categorized_text_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        text_cols = self.selected_text_columns()
        combined = combine_text_columns(df, text_cols)
        categories: list[str] = []
        merchants: list[str] = []
        suggestions: list[str] = []
        for text in combined.astype(str):
            category, merchant_alias = self._match_rule(text)
            merchant = merchant_alias or self._merchant_from_text(text)
            suggestion = category if category != "Other" else self._suggest_category(merchant, text)
            categories.append(category)
            merchants.append(merchant)
            suggestions.append(suggestion)
        return pd.DataFrame(
            {"Text": combined, "Category": categories, "Merchant": merchants, "Suggested Category": suggestions},
            index=df.index,
        )

    def dashboard_frame(self, df: pd.DataFrame) -> pd.DataFrame:
        matched = self._categorized_text_frame(df)
        inflow = parse_amount_series(df[self.inflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0)
        outflow = parse_amount_series(df[self.outflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0).abs()

        date_col = self._date_column()
        if date_col and date_col in df.columns:
            dates = pd.to_datetime(df[date_col], errors="coerce", dayfirst=False)
        else:
            dates = pd.Series(pd.NaT, index=df.index)

        matched = matched.copy()
        matched["Income"] = inflow
        matched["Expenses"] = outflow
        matched["Net"] = inflow - outflow
        matched["Date"] = dates
        return matched

    @staticmethod
    def _merchant_from_text(text: str) -> str:
        text = str(text or "").strip()
        if not text:
            return "Unknown"
        first = re.split(r"[;|]", text, maxsplit=1)[0].strip()
        first = re.sub(r"\s+", " ", first)
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
        self.total_outflow_metric.value_label.setText(f"CHF {expenses:,.2f}")  # type: ignore[attr-defined]
        self.total_inflow_metric.value_label.setText(f"CHF {income:,.2f}")  # type: ignore[attr-defined]
        self.total_saved_metric.value_label.setText(f"CHF {net:,.2f}")  # type: ignore[attr-defined]

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
            self._load_plotly_preview(self.category_view, "category_breakdown.html", fig)

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
            self._load_plotly_preview(self.timeline_view, "daily_cashflow.html", fig)

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
        categorized = self._categorized_text_frame(self.df)
        amount = pd.Series(0.0, index=self.df.index)
        if self.inflow_box.currentText() and self.outflow_box.currentText():
            inc = parse_amount_series(self.df[self.inflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0)
            out = parse_amount_series(self.df[self.outflow_box.currentText()], self.decimal_box.currentText()).fillna(0.0).abs()
            amount = out.where(out > 0, inc)
        categorized = categorized.copy()
        categorized["Amount"] = amount
        return categorized

    def refresh_uncategorized(self) -> None:
        if self.df is None:
            return
        categorized = self.categorized_frame()
        other = categorized[categorized["Category"] == "Other"].copy()
        search = self.search_box.text().strip()
        if search:
            haystack = (
                other["Text"].astype(str) + " " +
                other["Merchant"].astype(str) + " " +
                other["Suggested Category"].astype(str)
            )
            other = other[haystack.str.contains(search, case=False, na=False, regex=False)]

        grouped = (
            other.groupby(["Merchant", "Suggested Category"], dropna=False)
            .agg(Rows=("Text", "count"), Example=("Text", "first"), Total=("Amount", "sum"))
            .sort_values(["Total", "Rows"], ascending=[False, False])
        )

        self.uncat_table.setRowCount(len(grouped))
        for row, ((merchant, suggestion), values) in enumerate(grouped.iterrows()):
            payload = {
                "merchant": str(merchant),
                "suggestion": str(suggestion),
                "example": str(values["Example"]),
            }
            rows_item = QTableWidgetItem(str(int(values["Rows"])))
            rows_item.setData(Qt.UserRole, payload)
            self.uncat_table.setItem(row, 0, rows_item)
            self.uncat_table.setItem(row, 1, QTableWidgetItem(str(merchant)))
            self.uncat_table.setItem(row, 2, QTableWidgetItem(str(suggestion)))
            self.uncat_table.setItem(row, 3, QTableWidgetItem(str(values["Example"])))
            self.uncat_table.setItem(row, 4, QTableWidgetItem(f"{float(values['Total']):,.2f}"))
        self.uncat_table.resizeColumnsToContents()
        self.uncat_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

    def use_selected_uncategorized(self) -> None:
        selected = self.uncat_table.selectedItems()
        if not selected:
            return
        row = selected[0].row()
        rows_item = self.uncat_table.item(row, 0)
        payload = rows_item.data(Qt.UserRole) if rows_item else None
        if not isinstance(payload, dict):
            return
        merchant = str(payload.get("merchant", "")).strip()
        suggestion = str(payload.get("suggestion", "")).strip()
        example = str(payload.get("example", "")).strip()
        if merchant and merchant != "Unknown":
            self.new_pattern.setText(re.escape(merchant))
            self.new_merchant.setText(merchant)
        else:
            words = re.findall(r"[\w./-]{4,}", example, flags=re.UNICODE)
            self.new_pattern.setText(re.escape(words[0]) if words else re.escape(example[:80]))
            self.new_merchant.clear()
        if suggestion and suggestion != "Other":
            self.new_category.setText(suggestion)

    def add_rule_from_fields(self) -> None:
        pattern = self.new_pattern.text().strip()
        category = self.new_category.text().strip()
        merchant = self.new_merchant.text().strip()
        if not pattern or not category:
            QMessageBox.warning(self, "Missing rule", "Enter both a pattern and a category.")
            return
        try:
            re.compile(pattern, flags=re.IGNORECASE)
        except re.error as exc:
            QMessageBox.warning(self, "Invalid regex", str(exc))
            return
        rule = {"pattern": pattern, "category": category}
        if merchant:
            rule["merchant"] = merchant
        self.rules.append(rule)
        save_rules(self.rules)
        self.populate_rules_table()
        self.new_pattern.clear()
        self.new_category.clear()
        self.new_merchant.clear()
        self.refresh_plot()

    def populate_rules_table(self) -> None:
        self.rules_table.setRowCount(len(self.rules))
        for row, rule in enumerate(self.rules):
            self.rules_table.setItem(row, 0, QTableWidgetItem(rule.get("pattern", "")))
            self.rules_table.setItem(row, 1, QTableWidgetItem(rule.get("category", "")))
            self.rules_table.setItem(row, 2, QTableWidgetItem(rule.get("merchant", "")))

    def remove_selected_rules(self) -> None:
        rows = sorted({item.row() for item in self.rules_table.selectedItems()}, reverse=True)
        for row in rows:
            self.rules_table.removeRow(row)

    def save_rules_from_table(self) -> None:
        rules: list[dict[str, str]] = []
        for row in range(self.rules_table.rowCount()):
            pattern_item = self.rules_table.item(row, 0)
            category_item = self.rules_table.item(row, 1)
            merchant_item = self.rules_table.item(row, 2)
            pattern = pattern_item.text().strip() if pattern_item else ""
            category = category_item.text().strip() if category_item else ""
            merchant = merchant_item.text().strip() if merchant_item else ""
            if pattern and category:
                try:
                    re.compile(pattern, flags=re.IGNORECASE)
                except re.error as exc:
                    QMessageBox.warning(self, "Invalid regex", f"Row {row + 1}: {exc}")
                    return
                rule = {"pattern": pattern, "category": category}
                if merchant:
                    rule["merchant"] = merchant
                rules.append(rule)
        self.rules = rules
        save_rules(self.rules)
        self.refresh_plot()
        QMessageBox.information(self, "Rules saved", "Rules were saved to config/rules.json.")

    def save_plot(self) -> None:
        if self.current_fig is None:
            return
        ensure_app_dirs()
        source = (self.source_csv.stem if self.source_csv else self.current_csv.stem) if self.current_csv else "cashflow"
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
