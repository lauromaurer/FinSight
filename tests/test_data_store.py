"""The data store seam: everything FinSight keeps on disk, driven against a temp folder."""

import json

import pytest

from finsight.data_store import DataStore, header_fingerprint, user_data_folder
from finsight.month_analysis import analyze_month


def test_rules_round_trip_through_the_store(tmp_path):
    rules = [
        {"pattern": r"migros|coop", "category": "Groceries"},
        {"pattern": r"Café Zürich", "category": "Food & Drink", "merchant": "Café Zürich"},
    ]

    DataStore(tmp_path).save_rules(rules)

    assert DataStore(tmp_path).load_rules() == rules


def test_a_new_store_starts_with_starter_rules(tmp_path):
    rules = DataStore(tmp_path / "FinSight").load_rules()

    assert rules
    assert all(rule["pattern"] and rule["category"] for rule in rules)


def test_categories_round_trip_through_the_store(tmp_path):
    DataStore(tmp_path).save_categories(["Rent", "Groceries", "Salary"])

    assert DataStore(tmp_path).load_categories() == ["Groceries", "Rent", "Salary"]


def test_a_save_that_fails_halfway_leaves_the_previous_rules_intact(tmp_path):
    store = DataStore(tmp_path)
    saved = [{"pattern": "migros", "category": "Groceries"}]
    store.save_rules(saved)

    # A lone surrogate can't be encoded as UTF-8: the write fails part-way through.
    broken = [{"pattern": "sbb", "category": "Transport"}, {"pattern": "\ud800", "category": "Oops"}]
    with pytest.raises(UnicodeEncodeError):
        store.save_rules(broken)

    assert DataStore(tmp_path).load_rules() == saved
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rules.json"]


def test_an_imported_csv_is_kept_as_a_copy_in_the_store(tmp_path):
    download = tmp_path / "downloads" / "account-2026-10.csv"
    download.parent.mkdir()
    download.write_bytes(b"Date;Text;Debit\n01.10.2026;Migros;12.50\n")
    store = DataStore(tmp_path / "FinSight")

    first = store.save_import(download)
    second = store.save_import(download)
    download.unlink()

    assert first != second
    for copy in (first, second):
        assert copy.is_relative_to(store.root)
        assert copy.suffix == ".csv"
        assert copy.read_bytes() == b"Date;Text;Debit\n01.10.2026;Migros;12.50\n"


def test_the_store_remembers_the_last_imported_month(tmp_path):
    download = tmp_path / "account-2026-10.csv"
    download.write_bytes(b"Date;Text;Debit\n")
    store = DataStore(tmp_path / "FinSight")
    assert store.last_import() is None

    copy = store.save_import(download)
    store.remember_last_import(copy)

    assert DataStore(tmp_path / "FinSight").last_import() == copy


def test_the_last_imported_month_is_forgotten_when_its_copy_is_gone(tmp_path):
    download = tmp_path / "account-2026-10.csv"
    download.write_bytes(b"Date;Text;Debit\n")
    store = DataStore(tmp_path / "FinSight")
    copy = store.save_import(download)
    store.remember_last_import(copy)

    copy.unlink()

    assert store.last_import() is None


def test_an_exported_money_flow_is_saved_as_html_in_the_store(tmp_path):
    store = DataStore(tmp_path / "FinSight")
    html = "<html><body>Money flow – Oktober</body></html>"

    first = store.save_money_flow(html, "account-2026-10")
    second = store.save_money_flow(html, "account-2026-10")

    assert first != second
    for exported in (first, second):
        assert exported.is_relative_to(store.root)
        assert exported.suffix == ".html"
        assert exported.read_text(encoding="utf-8") == html


def test_import_overrides_are_remembered_per_bank_format(tmp_path):
    bank_a = header_fingerprint(["Buchungsdatum", "Buchungstext", "Belastung", "Gutschrift"])
    bank_b = header_fingerprint(["Date", "Description", "Amount"])
    overrides = {"sep": ";", "decimal": ",", "skip_rows": 9, "income": "Gutschrift", "expenses": "Belastung"}

    DataStore(tmp_path).save_import_overrides(bank_a, overrides)

    store = DataStore(tmp_path)
    assert store.import_overrides(bank_a) == overrides
    assert store.import_overrides(bank_b) is None


OLD_RULES = [{"pattern": "migros", "category": "Groceries"}, {"pattern": "sbb", "category": "Transport"}]
OLD_CATEGORIES = ["Groceries", "Rent", "Transport"]


def make_old_install(folder, rules=OLD_RULES, categories=OLD_CATEGORIES):
    """An old FinSight folder: config/ next to the executable or in the working directory."""
    config = folder / "config"
    config.mkdir(parents=True)
    if rules is not None:
        (config / "rules.json").write_text(json.dumps(rules), encoding="utf-8")
    if categories is not None:
        (config / "categories.json").write_text(json.dumps(categories), encoding="utf-8")
    return folder


def test_migration_copies_rules_and_categories_from_an_old_config_folder(tmp_path):
    old = make_old_install(tmp_path / "old")
    store = DataStore(tmp_path / "FinSight")

    assert store.migrate_from([tmp_path / "nowhere", old]) is True

    assert store.load_rules() == OLD_RULES
    assert store.load_categories() == OLD_CATEGORIES
    assert (old / "config" / "rules.json").exists()  # copied, not moved


def test_migration_copies_a_legacy_rules_json_from_an_old_folder(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    (old / "rules.json").write_text(json.dumps(OLD_RULES), encoding="utf-8")
    store = DataStore(tmp_path / "FinSight")

    store.migrate_from([old])

    assert store.load_rules() == OLD_RULES


def test_migration_never_overwrites_rules_already_in_the_store(tmp_path):
    old = make_old_install(tmp_path / "old")
    store = DataStore(tmp_path / "FinSight")
    current = [{"pattern": "coop", "category": "Groceries"}]
    store.save_rules(current)

    assert store.migrate_from([old]) is False

    assert store.load_rules() == current
    assert not store.categories_path.exists()


def test_migration_never_overwrites_any_file_already_in_the_store(tmp_path):
    old = make_old_install(tmp_path / "old")
    store = DataStore(tmp_path / "FinSight")
    store.save_categories(["Holidays"])

    store.migrate_from([old])

    assert store.load_rules() == OLD_RULES
    assert store.load_categories() == ["Holidays"]


def test_migration_runs_only_once(tmp_path):
    old = make_old_install(tmp_path / "old", rules=None)
    store = DataStore(tmp_path / "FinSight")
    store.migrate_from([old])

    (old / "config" / "rules.json").write_text(json.dumps(OLD_RULES), encoding="utf-8")

    assert DataStore(tmp_path / "FinSight").migrate_from([old]) is False
    assert not store.has_rules()


def test_the_data_folder_on_windows_is_finsight_in_appdata(tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"

    folder = user_data_folder(platform="win32", environ={"APPDATA": str(appdata)}, home=tmp_path)

    assert folder == appdata / "FinSight"


def test_the_data_folder_on_macos_is_finsight_in_application_support(tmp_path):
    folder = user_data_folder(platform="darwin", environ={}, home=tmp_path)

    assert folder == tmp_path / "Library" / "Application Support" / "FinSight"


def test_the_same_header_row_gives_the_same_fingerprint(tmp_path):
    exported_in_october = header_fingerprint(["Buchungsdatum", "Buchungstext", "Belastung"])
    exported_in_november = header_fingerprint([" Buchungsdatum", "Buchungstext ", "Belastung"])
    other_bank = header_fingerprint(["Buchungsdatum", "Buchungstext", "Gutschrift"])

    assert exported_in_october == exported_in_november
    assert exported_in_october != other_bank


REVIEW_CSV = b"""Date,Description,Debit,Credit
2026-10-01,Shop+Co (Zurich) A.G.,40.00,
2026-10-03,Corner Kiosk,12.00,
"""


def test_categorizing_a_merchant_in_review_saves_a_rule_the_next_import_applies(tmp_path):
    DataStore(tmp_path).save_rules([{"pattern": "migros", "category": "Groceries"}])

    DataStore(tmp_path).categorize_merchant("Shop+Co (Zurich) A.G.", "Shopping")

    next_month = analyze_month(REVIEW_CSV, DataStore(tmp_path).load_rules())
    assert {t.merchant: t.category for t in next_month.transactions} == {
        "Shop+Co (Zurich) A.G.": "Shopping",
        "Corner Kiosk": "Uncategorized",
    }
    assert [m.merchant for m in next_month.review_merchants] == ["Corner Kiosk"]
    assert DataStore(tmp_path).load_rules()[0] == {"pattern": "migros", "category": "Groceries"}


def test_categorizing_a_merchant_returns_the_saved_rules_with_the_merchant_name(tmp_path):
    rules = DataStore(tmp_path).categorize_merchant("Corner Kiosk", "Food & Drink")

    assert rules == DataStore(tmp_path).load_rules()
    assert rules[-1]["merchant"] == "Corner Kiosk"
    assert rules[-1]["category"] == "Food & Drink"


def test_categorizing_a_merchant_again_replaces_its_earlier_rule(tmp_path):
    store = DataStore(tmp_path)
    store.categorize_merchant("Corner Kiosk", "Food & Drink")

    rules = store.categorize_merchant("Corner Kiosk", "Groceries")

    assert [r["category"] for r in rules if r.get("merchant") == "Corner Kiosk"] == ["Groceries"]


def test_a_new_category_picked_in_review_is_saved_but_other_is_not_added(tmp_path):
    store = DataStore(tmp_path)
    store.save_categories(["Groceries"])

    store.categorize_merchant("Corner Kiosk", "Snacks")
    store.categorize_merchant("Shop+Co (Zurich) A.G.", "Other")

    assert DataStore(tmp_path).load_categories() == ["Groceries", "Snacks"]
