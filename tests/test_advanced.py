"""Advanced: editing Rules and Categories, and import overrides applied there.

Driven through the two seams: the data store on a temp folder, and analyze a month.
"""

from pathlib import Path

import pytest

from finsight.data_store import DataStore, InvalidRuleError
from finsight.month_analysis import ImportOverrides, analyze_month

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_a_rule_with_invalid_regex_is_rejected_and_nothing_is_saved(tmp_path):
    store = DataStore(tmp_path)
    saved = [{"pattern": "migros", "category": "Groceries"}]
    store.save_rules(saved)

    with pytest.raises(InvalidRuleError) as error:
        store.save_rules([{"pattern": "sbb", "category": "Transport"}, {"pattern": "coop(", "category": "Groceries"}])

    assert error.value.row == 1
    assert DataStore(tmp_path).load_rules() == saved


def test_renaming_a_category_updates_the_rules_that_use_it(tmp_path):
    store = DataStore(tmp_path)
    store.save_categories(["Food", "Transport"])
    store.save_rules([
        {"pattern": "migros", "category": "Food"},
        {"pattern": "sbb", "category": "Transport"},
        {"pattern": r"Corner\ Kiosk", "category": "Food", "merchant": "Corner Kiosk"},
    ])

    store.rename_category("Food", "Groceries")

    assert DataStore(tmp_path).load_categories() == ["Groceries", "Transport"]
    assert DataStore(tmp_path).load_rules() == [
        {"pattern": "migros", "category": "Groceries"},
        {"pattern": "sbb", "category": "Transport"},
        {"pattern": r"Corner\ Kiosk", "category": "Groceries", "merchant": "Corner Kiosk"},
    ]


def test_removing_a_category_sends_its_merchants_back_to_review(tmp_path):
    store = DataStore(tmp_path)
    store.save_categories(["Furniture", "Transport"])
    store.save_rules([
        {"pattern": "furniture", "category": "Furniture"},
        {"pattern": "uber", "category": "Transport"},
    ])

    store.remove_category("Furniture")

    rules = DataStore(tmp_path).load_rules()
    month = analyze_month((FIXTURES / "comma_english.csv").read_bytes(), rules)
    assert DataStore(tmp_path).load_categories() == ["Transport"]
    assert rules == [{"pattern": "uber", "category": "Transport"}]
    assert "Furniture Warehouse" in {m.merchant for m in month.review_merchants}
    assert "Furniture" not in {c.category for c in month.categories}


def test_overrides_applied_in_advanced_are_used_on_the_next_import_of_that_format(tmp_path):
    data = (FIXTURES / "comma_english.csv").read_bytes()
    rules = [{"pattern": "REF003", "category": "Furniture"}]
    detected = analyze_month(data, rules)
    assert detected.settings.text_columns == ("Description",)

    # Advanced: also match Rules against the Reference column, and Apply.
    applied = ImportOverrides(text_columns=("Description", "Reference"))
    DataStore(tmp_path).remember_import_overrides(detected.columns, applied)

    # Next month, same bank format: Import looks up remembered overrides by the detected header.
    next_import = analyze_month(data, rules)
    remembered = DataStore(tmp_path).remembered_import_overrides(next_import.columns)
    month = analyze_month(data, rules, remembered)

    assert month.settings.text_columns == ("Description", "Reference")
    assert [t.merchant for t in month.transactions_in("Furniture")] == ["Furniture Warehouse"]
