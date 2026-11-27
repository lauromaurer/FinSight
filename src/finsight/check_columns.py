"""The "Check your columns" screen: shown only when an Import's columns can't be detected.

Thin UI over analyze a month: every change re-analyzes the CSV bytes with the
current choices and shows a live preview. The caller remembers the confirmed
choices in the data store.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from finsight.month_analysis import ImportOverrides, MonthAnalysis, UnreadableCsvError, analyze_month

PREVIEW_ROWS = 5
SEPARATORS = {"Auto": None, ";": ";", ",": ",", "Tab": "\t", "|": "|"}
DECIMALS = {"Auto": None, ".": ".", ",": ","}


class CheckColumnsDialog(QDialog):
    """Pick delimiter, decimal mark, header row and columns; Continue once they work."""

    def __init__(
        self,
        data: bytes,
        rules: list[dict[str, str]],
        analysis: MonthAnalysis,
        *,
        categories: list[str] | None = None,
        minimum_amount: float = 0.0,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Check your columns")
        self.resize(900, 560)
        self._data = data
        self._rules = rules
        self._categories = categories
        self._minimum_amount = minimum_amount
        self._updating = False
        self.analysis: MonthAnalysis = analysis
        self.overrides = ImportOverrides()
        # Column picks survive a delimiter / header row change that hides them for a moment.
        self._picked: tuple[str | None, str | None, tuple[str, ...]] | None = None

        layout = QVBoxLayout(self)
        intro = QLabel(
            "FinSight couldn't recognise this file's columns. Pick the Income and/or Expenses "
            "column and the text columns that describe each transaction. FinSight remembers "
            "your choices for files with the same columns."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        grid = QGridLayout()
        self.sep_box = QComboBox()
        self.sep_box.addItems(list(SEPARATORS))
        self.decimal_box = QComboBox()
        self.decimal_box.addItems(list(DECIMALS))
        self.header_auto = QCheckBox("Detect header row")
        self.header_auto.setChecked(True)
        self.header_row = QSpinBox()
        self.header_row.setRange(0, 80)
        self.header_row.setValue(analysis.settings.header_row)
        self.header_row.setEnabled(False)
        self.income_box = QComboBox()
        self.expenses_box = QComboBox()
        self.text_list = QListWidget()
        self.text_list.setMaximumHeight(140)

        grid.addWidget(QLabel("Delimiter"), 0, 0)
        grid.addWidget(QLabel("Decimal mark"), 0, 1)
        grid.addWidget(QLabel("Header row"), 0, 2)
        grid.addWidget(self.sep_box, 1, 0)
        grid.addWidget(self.decimal_box, 1, 1)
        grid.addWidget(self.header_auto, 1, 2)
        grid.addWidget(self.header_row, 1, 3)
        grid.addWidget(QLabel("Income column"), 2, 0)
        grid.addWidget(QLabel("Expenses column"), 2, 1)
        grid.addWidget(QLabel("Text columns"), 2, 2, 1, 2)
        grid.addWidget(self.income_box, 3, 0, Qt.AlignTop)
        grid.addWidget(self.expenses_box, 3, 1, Qt.AlignTop)
        grid.addWidget(self.text_list, 3, 2, 1, 2)
        layout.addLayout(grid)

        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.preview = QTableWidget()
        self.preview.setEditTriggers(QTableWidget.NoEditTriggers)
        self.preview.verticalHeader().setVisible(False)
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(self.preview, stretch=1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Continue")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self._show(analysis)

        self.sep_box.currentTextChanged.connect(self._reanalyze)
        self.decimal_box.currentTextChanged.connect(self._reanalyze)
        self.header_auto.toggled.connect(self.header_row.setDisabled)
        self.header_auto.toggled.connect(self._reanalyze)
        self.header_row.valueChanged.connect(self._reanalyze)
        self.income_box.currentTextChanged.connect(self._columns_picked)
        self.expenses_box.currentTextChanged.connect(self._columns_picked)
        self.text_list.itemChanged.connect(self._columns_picked)

    def _columns_picked(self, *_args) -> None:
        if self._updating:
            return
        texts = tuple(
            self.text_list.item(row).text()
            for row in range(self.text_list.count())
            if self.text_list.item(row).checkState() == Qt.Checked
        )
        self._picked = (self.income_box.currentText() or None, self.expenses_box.currentText() or None, texts)
        self._reanalyze()

    def _choices(self) -> ImportOverrides:
        file_format = ImportOverrides(
            sep=SEPARATORS[self.sep_box.currentText()],
            decimal=DECIMALS[self.decimal_box.currentText()],
            header_row=None if self.header_auto.isChecked() else self.header_row.value(),
        )
        if self._picked is None:  # nothing picked yet: let FinSight detect the columns
            return file_format
        income, expenses, texts = self._picked
        return replace(file_format, income_column=income, expenses_column=expenses, text_columns=texts)

    def _reanalyze(self, *_args) -> None:
        if self._updating:
            return
        choices = self._choices()
        try:
            analysis = analyze_month(
                self._data,
                self._rules,
                choices,
                categories=self._categories,
                minimum_amount=self._minimum_amount,
            )
        except UnreadableCsvError as exc:
            self.status.setText(f"FinSight can't read the file with these settings: {exc}")
            self.buttons.button(QDialogButtonBox.Ok).setEnabled(False)
            return
        self._show(analysis)

    def _show(self, analysis: MonthAnalysis) -> None:
        """Show the analysis: pickers keep the user's choices where the columns still exist."""
        self._updating = True
        try:
            columns_changed = tuple(analysis.columns) != tuple(self.analysis.columns) or not self.income_box.count()
            self.analysis = analysis
            settings = analysis.settings
            if columns_changed:
                for box in (self.income_box, self.expenses_box):
                    box.clear()
                    box.addItems(["", *analysis.columns])
                self.text_list.clear()
                for column in analysis.columns:
                    item = QListWidgetItem(column)
                    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    item.setCheckState(Qt.Checked if column in settings.text_columns else Qt.Unchecked)
                    self.text_list.addItem(item)
            self.income_box.setCurrentText(settings.income_column or "")
            self.expenses_box.setCurrentText(settings.expenses_column or "")
            if self.header_auto.isChecked():
                self.header_row.setValue(settings.header_row)
            self._fill_preview(analysis)
        finally:
            self._updating = False

        self.overrides = self._confirmed_choices()
        ok = not analysis.columns_need_checking
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)
        if ok:
            self.status.setText(
                f"Looks good: {len(analysis.transactions)} transactions, "
                f"Income {analysis.income:,.2f}, Expenses {analysis.expenses:,.2f}."
            )
        else:
            self.status.setText("Pick an Income or Expenses column and at least one text column.")

    def _confirmed_choices(self) -> ImportOverrides:
        """What to remember: the file format choices plus the columns as now resolved."""
        settings = self.analysis.settings
        return replace(
            self._choices(),
            income_column=settings.income_column,
            expenses_column=settings.expenses_column,
            text_columns=settings.text_columns,
        )

    def _fill_preview(self, analysis: MonthAnalysis) -> None:
        settings = analysis.settings
        roles = {settings.income_column: "Income", settings.expenses_column: "Expenses"}
        roles.update({column: "Text" for column in settings.text_columns})
        columns = list(analysis.columns)
        rows = [
            {column: "" if value is None else str(value) for column, value in row.items()}
            for row in analysis.table.head(PREVIEW_ROWS).to_dict("records")
        ] if analysis.table is not None else []
        self.preview.clear()
        self.preview.setColumnCount(len(columns))
        self.preview.setRowCount(len(rows))
        self.preview.setHorizontalHeaderLabels(
            [f"{column}\n({roles[column]})" if column in roles else column for column in columns]
        )
        for r, row in enumerate(rows):
            for c, column in enumerate(columns):
                value = row.get(column, "")
                self.preview.setItem(r, c, QTableWidgetItem("" if value == "nan" else value))
