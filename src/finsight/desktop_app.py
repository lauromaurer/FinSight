from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

if __package__ in (None, ""):
    # Launched as a script (`python src/finsight/desktop_app.py`, PyInstaller
    # entry point): put `src/` on the path so the package import below works.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

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
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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

from finsight.finsight_core import (
    APP_NAME,
    BUNDLE_DIR,
    DEFAULT_CATEGORIES_PATH,
)
from finsight.check_columns import CheckColumnsDialog
from finsight.data_store import DataStore, open_user_store, user_data_folder
from finsight.money_flow_chart import money_flow_figure
from finsight.month_analysis import (
    OTHER,
    UNCATEGORIZED,
    ImportOverrides,
    MonthAnalysis,
    ReviewMerchant,
    UnreadableCsvError,
    analyze_month,
)


_preview_dir: Path | None = None


def preview_dir() -> Path:
    """A private temp folder for preview HTML, removed when the app exits."""
    global _preview_dir
    if _preview_dir is None:
        _preview_dir = Path(tempfile.mkdtemp(prefix="finsight-preview-"))
        atexit.register(shutil.rmtree, _preview_dir, ignore_errors=True)
    return _preview_dir

def resource_path(relative_path: str) -> Path:
    return BUNDLE_DIR / relative_path

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
QLabel#MonthHeader {
    font-size: 24px;
    font-weight: 700;
    color: #0f172a;
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


SETTINGS_PAGE = 4
REVIEW_COLUMNS = ["Merchant", "Transactions", "Total (CHF)", "Category", "", "Example"]
CHOOSE_CATEGORY = "Choose a Category…"
NEW_CATEGORY = "New Category…"


def _chf(amount: float) -> str:
    """CHF amount with a leading minus when negative, e.g. "-CHF 19.50"."""
    return f"{'-' if amount < 0 else ''}CHF {abs(amount):,.2f}"


class FinSightWindow(QMainWindow):
    def __init__(self, store: DataStore) -> None:
        super().__init__()
        self.store = store
        self.setWindowTitle(APP_NAME)
        if LOGO_PATH.exists():
            self.setWindowIcon(QIcon(load_logo_pixmap(256)))
        self.resize(1320, 850)

        self.rules = store.load_rules()
        self.categories = self._merged_categories()
        self.csv_bytes: bytes | None = None
        self.analysis: MonthAnalysis | None = None
        self.current_csv: Path | None = None
        self.source_csv: Path | None = None
        # Overrides this month was Imported with (remembered or confirmed in Check your columns).
        self.import_overrides = ImportOverrides()
        self.current_fig = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar())
        layout.addWidget(self._build_main(), stretch=1)
        self._set_ready_state(False)
        self._update_review_badge()

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
        for index, label in enumerate(["Dashboard", "Categorize", "Rules", "Data", "Settings"]):
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
        self.categorize_tab = QWidget()
        self.rules_tab = QWidget()
        self.data_tab = QWidget()
        self.settings_tab = QWidget()
        self.tabs.addTab(self.dashboard_tab, "Dashboard")
        self.tabs.addTab(self.categorize_tab, "Categorize")
        self.tabs.addTab(self.rules_tab, "Rules")
        self.tabs.addTab(self.data_tab, "Data")
        self.tabs.addTab(self.settings_tab, "Settings")
        layout.addWidget(self.tabs, stretch=1)
        self.tabs.currentChanged.connect(self.sync_sidebar_navigation)

        self._build_dashboard_tab()
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
        card.label_label = label_label  # type: ignore[attr-defined]
        return card

    def _build_dashboard_tab(self) -> None:
        layout = QVBoxLayout(self.dashboard_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        header = QHBoxLayout()
        self.month_header = QLabel("No month imported")
        self.month_header.setObjectName("MonthHeader")
        header.addWidget(self.month_header, stretch=1)
        self.export_money_flow_button = QPushButton("Export Money flow")
        self.export_money_flow_button.setObjectName("Secondary")
        self.export_money_flow_button.clicked.connect(self.export_money_flow)
        header.addWidget(self.export_money_flow_button)
        layout.addLayout(header)

        metrics = QHBoxLayout()
        self.total_inflow_metric = self._metric_card("Income", "CHF 0.00")
        self.total_outflow_metric = self._metric_card("Expenses", "CHF 0.00")
        self.total_saved_metric = self._metric_card("Saved", "CHF 0.00")
        metrics.addWidget(self.total_inflow_metric)
        metrics.addWidget(self.total_outflow_metric)
        metrics.addWidget(self.total_saved_metric)
        layout.addLayout(metrics)

        if QWebEngineView is None:
            fallback = QWidget()
            fallback_layout = QVBoxLayout(fallback)
            fallback_layout.setAlignment(Qt.AlignCenter)
            self.web_view = QLabel("The Money flow opens in your browser.")
            self.web_view.setAlignment(Qt.AlignCenter)
            self.external_preview_button = QPushButton("Open Money flow")
            self.external_preview_button.clicked.connect(self.open_preview_external)
            fallback_layout.addWidget(self.web_view)
            fallback_layout.addWidget(self.external_preview_button, alignment=Qt.AlignCenter)
            layout.addWidget(fallback, stretch=3)
        else:
            self.web_view = QWebEngineView()
            layout.addWidget(self.web_view, stretch=3)

        self.category_table = QTableWidget(0, 4)
        self.category_table.setHorizontalHeaderLabels(["Category", "Income", "Expenses", "Share of Expenses"])
        self.category_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.category_table.setAlternatingRowColors(True)
        self.category_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.category_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.category_table.setToolTip("Click a Category to see its transactions")
        self.category_table.cellClicked.connect(self.show_category_transactions)
        layout.addWidget(self.category_table, stretch=2)

    def _load_plotly_preview(self, view: QWidget, filename: str, fig: go.Figure) -> None:
        preview_path = preview_dir() / filename
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
        self.review_status = QLabel("Import a month to review its Uncategorized Merchants.")
        top.addWidget(self.review_status, stretch=1)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search Merchants or transaction text")
        self.search_box.textChanged.connect(self.refresh_uncategorized)
        top.addWidget(self.search_box, stretch=1)
        layout.addLayout(top)

        self.uncat_table = QTableWidget(0, len(REVIEW_COLUMNS))
        self.uncat_table.setHorizontalHeaderLabels(REVIEW_COLUMNS)
        self.uncat_table.horizontalHeader().setSectionResizeMode(REVIEW_COLUMNS.index("Example"), QHeaderView.Stretch)
        self.uncat_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.uncat_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.uncat_table.verticalHeader().setVisible(False)
        layout.addWidget(self.uncat_table, stretch=1)

        hint = QLabel(
            "Pick a Category for a Merchant to file it there from now on. "
            "Review is optional: anything left here shows as Uncategorized on the Dashboard."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _build_rules_tab(self) -> None:
        layout = QVBoxLayout(self.rules_tab)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)

        labels_panel = QFrame()
        labels_panel.setObjectName("Panel")
        labels_layout = QVBoxLayout(labels_panel)
        labels_layout.setContentsMargins(14, 12, 14, 12)
        labels_layout.addWidget(QLabel("Category labels"))
        self.categories_table = QTableWidget(0, 1)
        self.categories_table.setHorizontalHeaderLabels(["Label"])
        self.categories_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        labels_layout.addWidget(self.categories_table, stretch=1)
        label_buttons = QHBoxLayout()
        add_category = QPushButton("New label")
        add_category.setObjectName("Secondary")
        add_category.clicked.connect(lambda: self.categories_table.insertRow(self.categories_table.rowCount()))
        remove_category = QPushButton("Remove selected")
        remove_category.setObjectName("Secondary")
        remove_category.clicked.connect(self.remove_selected_categories)
        save_categories_button = QPushButton("Save labels")
        save_categories_button.clicked.connect(self.save_categories_from_table)
        label_buttons.addStretch(1)
        label_buttons.addWidget(add_category)
        label_buttons.addWidget(remove_category)
        label_buttons.addWidget(save_categories_button)
        labels_layout.addLayout(label_buttons)
        layout.addWidget(labels_panel, stretch=1)

        rules_panel = QFrame()
        rules_panel.setObjectName("Panel")
        rules_layout = QVBoxLayout(rules_panel)
        rules_layout.setContentsMargins(14, 12, 14, 12)
        rules_layout.addWidget(QLabel("Learned regex rules"))
        self.rules_table = QTableWidget(0, 3)
        self.rules_table.setHorizontalHeaderLabels(["Regex", "Label", "Merchant alias"])
        self.rules_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        rules_layout.addWidget(self.rules_table, stretch=1)

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
        rules_layout.addLayout(buttons)
        layout.addWidget(rules_panel, stretch=2)

        self.populate_categories_table()
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
        self.uploaded_file_label = QLabel(f"Imported CSVs are kept in: {self.store.imports_dir}")
        self.uploaded_file_label.setWordWrap(True)
        self.status_label = QLabel(f"Rules are saved in: {self.store.rules_path}")
        self.status_label.setWordWrap(True)
        self.data_folder_label = QLabel(str(self.store.root))
        self.data_folder_label.setWordWrap(True)
        self.data_folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        open_data_folder = QPushButton("Open data folder")
        open_data_folder.clicked.connect(self.open_data_folder)
        info_layout.addWidget(QLabel("Data folder"), 3, 0)
        info_layout.addWidget(self.data_folder_label, 3, 1)
        info_layout.addWidget(open_data_folder, 3, 2)
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

        settings_layout.addWidget(QLabel("Income column"), 4, 0)
        settings_layout.addWidget(QLabel("Expenses column"), 4, 1)
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
            self.export_money_flow_button,
            self.tabs,
        ):
            widget.setEnabled(ready)

    def _overrides(self, include_columns: bool) -> ImportOverrides:
        """Import overrides from the Settings page. Columns only once the user has seen them."""
        base = self.import_overrides
        sep = self.sep_box.currentText()
        sep = base.sep if sep == "Auto" else ("\t" if sep == "\\t" else sep)
        decimal = base.decimal if self.decimal_box.currentText() == "Auto" else self.decimal_box.currentText()
        header_row = base.header_row if self.skip_auto.isChecked() else self.skip_rows.value()
        if not include_columns:
            return replace(base, sep=sep, decimal=decimal, header_row=header_row)
        return ImportOverrides(
            sep=sep,
            decimal=decimal,
            header_row=header_row,
            income_column=self.inflow_box.currentText() or None,
            expenses_column=self.outflow_box.currentText() or None,
            text_columns=tuple(self.selected_text_columns()),
            date_column=self.analysis.settings.date_column if self.analysis else None,
        )

    def _analyze(self, include_columns: bool) -> bool:
        assert self.csv_bytes is not None
        try:
            self.analysis = analyze_month(
                self.csv_bytes,
                self.rules,
                self._overrides(include_columns),
                categories=self._category_names(),
                minimum_amount=float(self.min_amount.value()),
            )
        except UnreadableCsvError as exc:
            QMessageBox.critical(self, "CSV error", f"Could not read the CSV:\n{exc}")
            return False
        return True

    def _analyze_import(self, data: bytes) -> tuple[MonthAnalysis, ImportOverrides]:
        """Analyze an Imported CSV, applying the choices remembered for its bank format.

        Raises UnreadableCsvError when the file isn't a readable CSV.
        """
        options = {"categories": self._category_names(), "minimum_amount": float(self.min_amount.value())}
        analysis = analyze_month(data, self.rules, **options)
        remembered = self.store.remembered_import_overrides(analysis.columns)
        if remembered is None:
            return analysis, ImportOverrides()
        return analyze_month(data, self.rules, remembered, **options), remembered

    def open_csv(self) -> None:
        """Import: pick a CSV; only ask about columns when they can't be detected.

        The current month is replaced only once the new one is ready; an unreadable
        file or a cancelled Check your columns leaves it untouched.
        """
        file_name, _ = QFileDialog.getOpenFileName(self, "Import a month", "", "CSV Files (*.csv);;All Files (*)")
        if not file_name:
            return
        source = Path(file_name)
        try:
            data = source.read_bytes()
            analysis, overrides = self._analyze_import(data)
        except (OSError, UnreadableCsvError) as exc:
            QMessageBox.critical(
                self,
                "Can't read this file",
                f"FinSight couldn't read {source.name} as a bank CSV export.\n"
                f"Your current month is unchanged.\n\nDetails: {exc}",
            )
            return
        if analysis.columns_need_checking:
            dialog = CheckColumnsDialog(
                data,
                self.rules,
                analysis,
                categories=self._category_names(),
                minimum_amount=float(self.min_amount.value()),
                parent=self,
            )
            if dialog.exec() != QDialog.Accepted:
                return
            self.store.remember_import_overrides(analysis.columns, dialog.overrides)
            analysis, overrides = dialog.analysis, dialog.overrides
        try:
            copy = self.store.save_import(source)
            self.store.remember_last_import(copy)
        except OSError as exc:
            QMessageBox.critical(self, "CSV storage error", f"Could not save a local copy of the CSV:\n{exc}")
            return
        self._show_month(data, analysis, overrides, copy, source)
        self.show_page(0)

    def reopen_last_import(self) -> None:
        """On launch, reopen the last Imported month (silently skipped if it can't be)."""
        copy = self.store.last_import()
        if copy is None:
            return
        try:
            data = copy.read_bytes()
            analysis, overrides = self._analyze_import(data)
        except (OSError, UnreadableCsvError):
            return
        if not analysis.columns_need_checking:
            self._show_month(data, analysis, overrides, copy, None)

    def _show_month(
        self,
        data: bytes,
        analysis: MonthAnalysis,
        overrides: ImportOverrides,
        copy: Path,
        source: Path | None,
    ) -> None:
        """Make this the current month (replacing any previous one) and draw it."""
        self.csv_bytes = data
        self.analysis = analysis
        self.import_overrides = overrides
        self.current_csv = copy
        self.source_csv = source
        self.sep_box.setCurrentText("Auto")
        self.decimal_box.setCurrentText("Auto")
        self.skip_auto.setChecked(True)
        self.file_label.setText(str(source or copy))
        self.uploaded_file_label.setText(str(copy))
        self.populate_columns()
        self.populate_preview()
        self._set_ready_state(True)
        self.render_analysis()

    def open_data_folder(self) -> None:
        self.store.root.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.root)))

    def reload_csv(self) -> None:
        if self.current_csv is None:
            return
        try:
            self.csv_bytes = self.current_csv.read_bytes()
        except OSError as exc:
            QMessageBox.critical(self, "CSV error", f"Could not read the CSV:\n{exc}")
            return
        if not self._analyze(include_columns=False):
            return
        self.file_label.setText(str(self.source_csv or self.current_csv))
        self.uploaded_file_label.setText(str(self.current_csv))
        self.populate_columns()
        self.populate_preview()
        self._set_ready_state(True)
        self.render_analysis()

    def populate_columns(self) -> None:
        if self.analysis is None:
            return
        columns = list(self.analysis.columns)
        settings = self.analysis.settings
        self.inflow_box.clear()
        self.outflow_box.clear()
        self.inflow_box.addItems([""] + columns)
        self.outflow_box.addItems([""] + columns)
        self.inflow_box.setCurrentText(settings.income_column or "")
        self.outflow_box.setCurrentText(settings.expenses_column or "")

        self.text_table.setRowCount(len(columns))
        for row, column in enumerate(columns):
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            check.setCheckState(Qt.Checked if column in settings.text_columns else Qt.Unchecked)
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

    def refresh_plot(self) -> None:
        """Re-analyze with the current Rules and Settings, then redraw every page."""
        if self.csv_bytes is None:
            return
        if self._analyze(include_columns=True):
            self.render_analysis()

    def render_analysis(self) -> None:
        analysis = self.analysis
        if analysis is None:
            return
        if analysis.columns_need_checking:
            self.current_fig = None
            QMessageBox.warning(
                self,
                "Check your columns",
                "FinSight could not find the Income, Expenses and text columns in this file.\n"
                "Choose them in Settings, then press Apply settings.",
            )
            self.show_page(SETTINGS_PAGE)
            return

        self.current_fig = money_flow_figure(analysis)
        if QWebEngineView is None:
            self.web_view.setText("Money flow built. Open the interactive preview or save it to your data folder.")
        else:
            self._load_plotly_preview(self.web_view, "money_flow_preview.html", self.current_fig)
        self.refresh_uncategorized()
        self.refresh_dashboard()

    def open_preview_external(self) -> None:
        if self.current_fig is None:
            return
        preview_path = preview_dir() / "money_flow.html"
        self.current_fig.write_html(str(preview_path), include_plotlyjs=True, full_html=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(preview_path.resolve())))

    def _category_names(self) -> list[str]:
        return sorted({c for c in self.categories if c} | {OTHER})

    def refresh_dashboard(self) -> None:
        analysis = self.analysis
        if analysis is None:
            return
        self.month_header.setText(analysis.month_label)
        self.total_inflow_metric.value_label.setText(_chf(analysis.income))  # type: ignore[attr-defined]
        self.total_outflow_metric.value_label.setText(_chf(analysis.expenses))  # type: ignore[attr-defined]
        saved = analysis.saved
        self.total_saved_metric.value_label.setText(_chf(saved))  # type: ignore[attr-defined]
        self.total_saved_metric.value_label.setStyleSheet(  # type: ignore[attr-defined]
            "color: #dc2626;" if saved < 0 else ""
        )

        categories = analysis.categories
        self.category_table.setRowCount(len(categories))
        for row, total in enumerate(categories):
            self.category_table.setItem(row, 0, QTableWidgetItem(total.category))
            self.category_table.setItem(row, 1, QTableWidgetItem(_chf(total.income)))
            self.category_table.setItem(row, 2, QTableWidgetItem(_chf(total.expenses)))
            self.category_table.setItem(row, 3, QTableWidgetItem(f"{total.expense_share * 100:.1f}%"))
        self.category_table.resizeColumnsToContents()
        self.category_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

    def show_category_transactions(self, row: int, _column: int = 0) -> None:
        item = self.category_table.item(row, 0)
        if self.analysis is None or item is None:
            return
        category = item.text()
        transactions = self.analysis.transactions_in(category)

        dialog = QDialog(self)
        dialog.setWindowTitle(f"{category} - {self.analysis.month_label}")
        dialog.resize(820, 480)
        layout = QVBoxLayout(dialog)
        table = QTableWidget(len(transactions), 5)
        table.setHorizontalHeaderLabels(["Date", "Merchant", "Text", "Income", "Expenses"])
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for r, t in enumerate(transactions):
            table.setItem(r, 0, QTableWidgetItem(f"{t.date:%d.%m.%Y}" if t.date else ""))
            table.setItem(r, 1, QTableWidgetItem(t.merchant))
            table.setItem(r, 2, QTableWidgetItem(t.text))
            table.setItem(r, 3, QTableWidgetItem(_chf(t.income) if t.income else ""))
            table.setItem(r, 4, QTableWidgetItem(_chf(t.expenses) if t.expenses else ""))
        table.resizeColumnsToContents()
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(table)
        close = QPushButton("Close")
        close.clicked.connect(dialog.accept)
        layout.addWidget(close, alignment=Qt.AlignRight)
        dialog.exec()

    def populate_preview(self) -> None:
        if self.analysis is None:
            return
        preview = self.analysis.table.head(200)
        self.preview_table.setRowCount(len(preview))
        self.preview_table.setColumnCount(len(preview.columns))
        self.preview_table.setHorizontalHeaderLabels([str(c) for c in preview.columns])
        for r, (_, row) in enumerate(preview.iterrows()):
            for c, value in enumerate(row):
                self.preview_table.setItem(r, c, QTableWidgetItem("" if pd.isna(value) else str(value)))
        self.preview_table.resizeColumnsToContents()

    def refresh_uncategorized(self) -> None:
        """Fill Review: one row per Uncategorized Merchant, largest total first."""
        if self.analysis is None:
            self._update_review_badge()
            return
        search = self.search_box.text().strip().lower()
        merchants = [
            m
            for m in self.analysis.review_merchants
            if not search or search in f"{m.merchant} {m.example}".lower()
        ]
        self.uncat_table.setRowCount(len(merchants))
        for row, merchant in enumerate(merchants):
            self.uncat_table.setItem(row, 0, QTableWidgetItem(merchant.merchant))
            count_item = QTableWidgetItem(str(merchant.count))
            count_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.uncat_table.setItem(row, 1, count_item)
            total_item = QTableWidgetItem(f"{merchant.total:,.2f}")
            total_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.uncat_table.setItem(row, 2, total_item)
            combo = self._review_category_combo(merchant)
            self.uncat_table.setCellWidget(row, 3, combo)
            apply_button = QPushButton("Apply")
            apply_button.setObjectName("Secondary")
            apply_button.setToolTip("File this Merchant under the chosen Category")
            apply_button.clicked.connect(
                lambda checked=False, m=merchant.merchant, c=combo: self._apply_review_choice(m, c)
            )
            self.uncat_table.setCellWidget(row, 4, apply_button)
            self.uncat_table.setItem(row, 5, QTableWidgetItem(merchant.example))
        self.uncat_table.resizeColumnsToContents()
        self.uncat_table.horizontalHeader().setSectionResizeMode(REVIEW_COLUMNS.index("Example"), QHeaderView.Stretch)
        self._update_review_badge()

    def _review_category_combo(self, merchant: ReviewMerchant) -> QComboBox:
        combo = QComboBox()
        if not merchant.suggested_category:
            combo.addItem(CHOOSE_CATEGORY)
        combo.addItems(self._category_names())
        combo.addItem(NEW_CATEGORY)
        if merchant.suggested_category:
            index = combo.findText(merchant.suggested_category)
            combo.setCurrentIndex(max(index, 0))
        combo.activated.connect(lambda _index, m=merchant.merchant, c=combo: self._apply_review_choice(m, c))
        return combo

    def _apply_review_choice(self, merchant: str, combo: QComboBox) -> None:
        choice = combo.currentText()
        if choice == CHOOSE_CATEGORY:
            return
        if choice == NEW_CATEGORY:
            name, ok = QInputDialog.getText(self, "New Category", f"File “{merchant}” under a new Category:")
            choice = name.strip()
            if not ok or not choice or choice == UNCATEGORIZED:
                combo.setCurrentIndex(0)
                return
        self.categorize_merchant(merchant, choice)

    def categorize_merchant(self, merchant: str, category: str) -> None:
        """Save a literal Rule for the Merchant, then re-analyze so it leaves Review."""
        try:
            self.rules = self.store.categorize_merchant(merchant, category)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save Rule", f"Could not save the Rule:\n{exc}")
            return
        self.categories = self._merged_categories()
        self.populate_rules_table()
        self.populate_categories_table()
        self.refresh_plot()

    def _merged_categories(self) -> list[str]:
        rule_categories = [rule.get("category", "").strip() for rule in self.rules]
        return sorted(
            dict.fromkeys(c for c in [*self.store.load_categories(), *rule_categories] if c and c != OTHER)
        )

    def _update_review_badge(self) -> None:
        remaining = len(self.analysis.review_merchants) if self.analysis is not None else 0
        if hasattr(self, "nav_buttons"):
            review_button = self.nav_buttons[self.tabs.indexOf(self.categorize_tab)]
            review_button.setText(f"Review ({remaining})" if remaining else "Review")
        if hasattr(self, "review_status"):
            if self.analysis is None:
                self.review_status.setText("Import a month to review its Uncategorized Merchants.")
            elif remaining:
                noun = "Merchant" if remaining == 1 else "Merchants"
                self.review_status.setText(f"{remaining} Uncategorized {noun} left to review.")
            else:
                self.review_status.setText("All Merchants are categorized.")

    def populate_category_combo(self) -> None:
        """Categories changed: rebuild the Review dropdowns."""
        if hasattr(self, "uncat_table"):
            self.refresh_uncategorized()

    def populate_categories_table(self) -> None:
        if not hasattr(self, "categories_table"):
            return
        self.categories_table.setRowCount(len(self.categories))
        for row, category in enumerate(self.categories):
            self.categories_table.setItem(row, 0, QTableWidgetItem(category))

    def remove_selected_categories(self) -> None:
        rows = sorted({item.row() for item in self.categories_table.selectedItems()}, reverse=True)
        for row in rows:
            self.categories_table.removeRow(row)

    def save_categories_from_table(self) -> None:
        categories: list[str] = []
        for row in range(self.categories_table.rowCount()):
            item = self.categories_table.item(row, 0)
            label = item.text().strip() if item else ""
            if label and label != "Other":
                categories.append(label)
        if not categories:
            QMessageBox.warning(self, "Missing labels", "Create at least one category label.")
            return
        self.categories = sorted(dict.fromkeys(categories))
        self.store.save_categories(self.categories)
        self.populate_categories_table()
        self.populate_category_combo()
        self.refresh_plot()
        QMessageBox.information(self, "Labels saved", f"Category labels were saved to {self.store.categories_path}.")

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
                if category not in self.categories:
                    QMessageBox.warning(self, "Unknown label", f"Row {row + 1}: choose one of the saved category labels.")
                    return
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
        self.store.save_rules(self.rules)
        self.refresh_plot()
        QMessageBox.information(self, "Rules saved", f"Rules were saved to {self.store.rules_path}.")

    def export_money_flow(self) -> None:
        if self.current_fig is None:
            return
        source = (self.source_csv.stem if self.source_csv else self.current_csv.stem) if self.current_csv else "finsight"
        html = self.current_fig.to_html(include_plotlyjs="cdn", full_html=True)
        try:
            html_path = self.store.save_money_flow(html, source)
        except Exception as exc:
            QMessageBox.critical(self, "Export error", f"Could not save the Money flow:\n{exc}")
            return
        QMessageBox.information(self, "Money flow saved", f"Interactive HTML: {html_path}")


SELF_CHECK_FLAG = "--self-check"


def _report(message: str, stream) -> None:
    # A windowed frozen build on Windows has no console: stdout/stderr are None.
    if stream is not None:
        print(message, file=stream)


def self_check() -> int:
    """Start without a window: core modules loaded, bundled files present, Qt up,
    and the data store working (in a throwaway temp folder: the self-check never
    writes to the real data folder or the working directory).

    Returns the process exit code: 0 on success, 1 on failure.
    """
    try:
        missing = [str(path) for path in (LOGO_PATH, DEFAULT_CATEGORIES_PATH) if not path.exists()]
        if missing:
            raise FileNotFoundError(f"bundled files missing: {', '.join(missing)}")
        with tempfile.TemporaryDirectory(prefix="finsight-self-check-") as scratch:
            store = DataStore(Path(scratch) / "FinSight")
            store.save_rules(store.load_rules())
            store.save_categories(store.load_categories())
            if not store.has_rules() or not store.load_categories():
                raise RuntimeError("data store round-trip failed")
        data_folder = user_data_folder()
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        QApplication.instance() or QApplication([sys.argv[0]])
    except Exception as exc:
        _report(f"FinSight self-check FAILED: {exc!r}", sys.stderr)
        return 1
    _report(f"Data folder: {data_folder}", sys.stdout)
    _report("FinSight self-check OK", sys.stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    if SELF_CHECK_FLAG in argv[1:]:
        return self_check()
    app = QApplication(argv)
    if LOGO_PATH.exists():
        app.setWindowIcon(QIcon(load_logo_pixmap(256)))
    app.setStyleSheet(STYLE)
    window = FinSightWindow(open_user_store())
    window.reopen_last_import()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
