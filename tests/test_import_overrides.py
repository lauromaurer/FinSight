"""Check your columns: choices are remembered by the data store per bank format (header fingerprint).

Driven through the two seams: analyze a month, and the data store on a temp folder.
"""

from pathlib import Path

from finsight.data_store import DataStore
from finsight.month_analysis import ImportOverrides, analyze_month

FIXTURES = Path(__file__).resolve().parent / "fixtures"
UNRECOGNISED = (FIXTURES / "undetectable_columns.csv").read_bytes()
RULES = [{"pattern": "foo", "category": "Groceries"}]

# What the user picks on the Check your columns screen for undetectable_columns.csv.
CHOSEN = ImportOverrides(expenses_column="Col3", text_columns=("Col2", "Col4"))


def test_columns_chosen_for_an_unrecognised_format_are_applied_on_the_next_import(tmp_path):
    first = analyze_month(UNRECOGNISED, RULES)
    assert first.columns_need_checking
    DataStore(tmp_path).remember_import_overrides(first.columns, CHOSEN)

    detected = analyze_month(UNRECOGNISED, RULES)
    remembered = DataStore(tmp_path).remembered_import_overrides(detected.columns)
    again = analyze_month(UNRECOGNISED, RULES, remembered)

    assert remembered == CHOSEN
    assert not again.columns_need_checking
    assert again.expenses == 19.5
    assert {(c.category, c.expenses) for c in again.categories} >= {("Groceries", 12.0)}


def test_a_format_without_remembered_choices_gets_none(tmp_path):
    store = DataStore(tmp_path)
    store.remember_import_overrides(("Col1", "Col2", "Col3", "Col4"), CHOSEN)

    assert store.remembered_import_overrides(("Date", "Text", "Amount")) is None


def test_every_import_choice_survives_the_round_trip(tmp_path):
    columns = ("Datum", "Text", "Soll", "Haben")
    everything = ImportOverrides(
        sep=";",
        decimal=",",
        header_row=3,
        income_column="Haben",
        expenses_column="Soll",
        text_columns=("Text",),
        date_column="Datum",
    )
    DataStore(tmp_path).remember_import_overrides(columns, everything)

    assert DataStore(tmp_path).remembered_import_overrides(columns) == everything


def test_choices_for_the_same_format_are_replaced_not_merged(tmp_path):
    columns = ("Col1", "Col2", "Col3", "Col4")
    store = DataStore(tmp_path)
    store.remember_import_overrides(columns, ImportOverrides(sep=";", expenses_column="Col3"))
    store.remember_import_overrides(columns, ImportOverrides(income_column="Col3"))

    assert store.remembered_import_overrides(columns) == ImportOverrides(income_column="Col3")


def test_an_import_applies_the_choices_remembered_for_its_bank_format(tmp_path):
    store = DataStore(tmp_path)
    store.remember_import_overrides(analyze_month(UNRECOGNISED, RULES).columns, CHOSEN)

    analysis, overrides = store.analyze_import(UNRECOGNISED, RULES)

    assert overrides == CHOSEN
    assert not analysis.columns_need_checking
    assert analysis.expenses == 19.5


ENGLISH = (FIXTURES / "comma_english.csv").read_bytes()


def test_remembered_choices_that_make_the_file_unreadable_fall_back_to_detection(tmp_path):
    store = DataStore(tmp_path)
    store.remember_import_overrides(analyze_month(ENGLISH, []).columns, ImportOverrides(header_row=50))

    analysis, overrides = store.analyze_import(ENGLISH, [])

    assert overrides == ImportOverrides()
    assert analysis.expenses == analyze_month(ENGLISH, []).expenses > 0


def test_remembered_choices_whose_columns_need_checking_fall_back_to_detection(tmp_path):
    store = DataStore(tmp_path)
    gone = ImportOverrides(expenses_column="Gone", text_columns=("Gone too",))
    store.remember_import_overrides(analyze_month(ENGLISH, []).columns, gone)

    analysis, overrides = store.analyze_import(ENGLISH, [])

    assert overrides == ImportOverrides()
    assert not analysis.columns_need_checking


def test_an_unrecognised_format_without_remembered_choices_still_needs_checking(tmp_path):
    analysis, overrides = DataStore(tmp_path).analyze_import(UNRECOGNISED, RULES)

    assert overrides == ImportOverrides()
    assert analysis.columns_need_checking
