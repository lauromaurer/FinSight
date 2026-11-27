"""Analyze a month: CSV bytes + Rules in, MonthAnalysis out.

Fixtures in tests/fixtures/ are hand-written and anonymised, never real exports.
Expected numbers are worked out by hand from those files.
"""

from pathlib import Path

import pytest

from finsight.month_analysis import ImportOverrides, analyze_month, rule_for_merchant

FIXTURES = Path(__file__).resolve().parent / "fixtures"

RULES = [
    {"pattern": "migros", "category": "Groceries"},
    {"pattern": "sbb", "category": "Transport"},
    {"pattern": "paypal", "category": "P2P", "merchant": "PayPal"},
    {"pattern": "pizzeria", "category": "Food & Drink"},
    {"pattern": "flea market", "category": "Other"},
    {"pattern": "example employer", "category": "Salary"},
]


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def german_month(rules=RULES, **kwargs):
    return analyze_month(fixture("semicolon_german_preamble.csv"), rules, **kwargs)


def test_semicolon_german_export_with_preamble_gives_income_expenses_and_saved():
    analysis = german_month()

    assert analysis.income == pytest.approx(5240.00)
    assert analysis.expenses == pytest.approx(1696.25)
    assert analysis.saved == pytest.approx(3543.75)


def category_totals(analysis) -> dict[str, tuple[float, float]]:
    return {c.category: (round(c.income, 2), round(c.expenses, 2)) for c in analysis.categories}


def test_each_category_gets_its_income_and_expenses_with_uncategorized_as_its_own_bucket():
    analysis = german_month()

    assert category_totals(analysis) == {
        "Salary": (5200.00, 0.00),
        "Groceries": (0.00, 126.45),
        "Transport": (0.00, 3.80),
        "P2P": (40.00, 25.00),
        "Food & Drink": (0.00, 18.50),
        "Other": (0.00, 60.00),
        "Uncategorized": (0.00, 1462.50),
    }


def test_transactions_no_rule_matched_are_uncategorized_and_other_is_only_a_chosen_category():
    analysis = german_month()

    by_merchant = {t.merchant: t.category for t in analysis.transactions}
    assert by_merchant["Example Immobilien AG"] == "Uncategorized"
    assert by_merchant["Flea Market Stand"] == "Other"

    no_rules = german_month(rules=[])
    assert {t.category for t in no_rules.transactions} == {"Uncategorized"}


def test_review_groups_uncategorized_transactions_by_merchant_largest_total_first():
    rules_without_groceries = [r for r in RULES if r["category"] != "Groceries"]
    analysis = german_month(rules=rules_without_groceries)

    review = [(m.merchant, m.count, round(m.total, 2)) for m in analysis.review_merchants]
    assert review == [
        ("Example Immobilien AG", 1, 1450.00),
        ("Migros Supermarkt", 2, 126.45),
        ("Café Central *Bern", 1, 12.00),
        ("Bank Fee", 1, 0.50),
    ]


def test_review_suggests_a_known_category_for_a_merchant():
    rules_without_groceries = [r for r in RULES if r["category"] != "Groceries"]
    analysis = german_month(rules=rules_without_groceries, categories=["Groceries", "Transport"])

    suggestions = {m.merchant: m.suggested_category for m in analysis.review_merchants}
    assert suggestions["Migros Supermarkt"] == "Groceries"
    assert suggestions["Example Immobilien AG"] == ""


def test_a_rule_created_for_a_merchant_moves_it_out_of_uncategorized_on_re_analysis():
    before = german_month()
    assert "Café Central *Bern" in {m.merchant for m in before.review_merchants}

    rules = RULES + [rule_for_merchant("Café Central *Bern", "Food & Drink")]
    after = german_month(rules=rules)

    assert "Café Central *Bern" not in {m.merchant for m in after.review_merchants}
    assert category_totals(after)["Food & Drink"] == (0.00, 30.50)
    assert category_totals(after)["Uncategorized"] == (0.00, 1450.50)


def test_minimum_amount_drops_small_transactions_from_totals_categories_and_review_alike():
    analysis = german_month(minimum_amount=1.0)

    assert analysis.expenses == pytest.approx(1695.75)
    assert category_totals(analysis)["Uncategorized"] == (0.00, 1462.00)
    assert "Bank Fee" not in {m.merchant for m in analysis.review_merchants}
    assert "Bank Fee" not in {t.merchant for t in analysis.transactions}


def test_comma_delimited_english_export_with_dot_decimals_and_comma_thousands():
    analysis = analyze_month(fixture("comma_english.csv"), [{"pattern": "grocery", "category": "Groceries"}])

    assert analysis.income == pytest.approx(3500.00)
    assert analysis.expenses == pytest.approx(1313.70)
    assert category_totals(analysis)["Groceries"] == (0.00, 56.20)
    assert (str(analysis.start_date), str(analysis.end_date)) == ("2026-09-01", "2026-09-28")
    assert analysis.settings.sep == ","
    assert analysis.settings.decimal == "."


def test_cp1252_export_with_comma_decimals_and_dot_thousands():
    analysis = analyze_month(fixture("comma_decimal_cp1252.csv"), [])

    assert analysis.income == pytest.approx(4250.00)
    assert analysis.expenses == pytest.approx(1304.70)
    assert {t.merchant for t in analysis.transactions} == {
        "Bäckerei Müller Zürich",
        "Lohn Firma Beispiel",
        "Möbelhaus Grün",
    }
    assert analysis.settings.decimal == ","


def test_amounts_with_chf_and_apostrophe_thousands_separators():
    analysis = analyze_month(fixture("apostrophe_thousands_chf.csv"), [])

    assert analysis.income == pytest.approx(6100.00)
    assert analysis.expenses == pytest.approx(1257.85)


def test_undetectable_columns_return_columns_need_checking_with_candidates_and_preview_rows():
    analysis = analyze_month(fixture("undetectable_columns.csv"), RULES)

    assert analysis.columns_need_checking
    assert analysis.column_check.columns == ("Col1", "Col2", "Col3", "Col4")
    assert analysis.column_check.preview_rows[0] == {
        "Col1": "01.10.2026",
        "Col2": "foo",
        "Col3": "12.00",
        "Col4": "bar",
    }
    assert analysis.transactions == ()
    assert analysis.income == 0 and analysis.expenses == 0


def test_import_overrides_choose_the_columns_when_detection_fails():
    overrides = ImportOverrides(expenses_column="Col3", text_columns=("Col2",), date_column="Col1")
    analysis = analyze_month(fixture("undetectable_columns.csv"), [], overrides=overrides)

    assert not analysis.columns_need_checking
    assert analysis.expenses == pytest.approx(19.50)
    assert [(m.merchant, m.total) for m in analysis.review_merchants] == [("foo", 12.00), ("baz", 7.50)]
    assert str(analysis.end_date) == "2026-10-02"


def test_import_overrides_replace_detected_delimiter_decimal_and_header_row():
    detected = german_month().settings
    overrides = ImportOverrides(sep=detected.sep, decimal=",", header_row=detected.header_row)

    analysis = german_month(overrides=overrides)

    assert analysis.settings.decimal == ","
    # "-3.80" read with a decimal comma treats the dot as a thousands mark: 380.
    assert {t.merchant: t.expenses for t in analysis.transactions}["SBB CFF FFS"] == pytest.approx(380)


def flow_amounts(analysis) -> dict[tuple[str, str], float]:
    labels = {node.id: node.label for node in analysis.money_flow.nodes}
    return {(labels[link.source], labels[link.target]): round(link.amount, 2) for link in analysis.money_flow.links}


def test_money_flow_carries_each_category_into_and_out_of_the_month_with_saved():
    analysis = german_month()

    assert flow_amounts(analysis) == {
        ("Salary", "October 2026"): 5200.00,
        ("P2P", "October 2026"): 40.00,
        ("October 2026", "Uncategorized"): 1462.50,
        ("October 2026", "Groceries"): 126.45,
        ("October 2026", "Other"): 60.00,
        ("October 2026", "P2P"): 25.00,
        ("October 2026", "Food & Drink"): 18.50,
        ("October 2026", "Transport"): 3.80,
        ("October 2026", "Saved"): 3543.75,
    }


def test_money_flow_and_category_table_agree_for_every_category():
    analysis = german_month(minimum_amount=1.0)
    links = analysis.money_flow.links
    nodes = {node.id: node for node in analysis.money_flow.nodes}

    for total in analysis.categories:
        flowed_in = sum(l.amount for l in links if nodes[l.source].label == total.category and nodes[l.source].side == "income")
        flowed_out = sum(l.amount for l in links if nodes[l.target].label == total.category and nodes[l.target].side == "expenses")
        assert flowed_in == pytest.approx(total.income)
        assert flowed_out == pytest.approx(total.expenses)


def test_money_flow_shows_overspent_when_expenses_exceed_income():
    overrides = ImportOverrides(expenses_column="Col3", text_columns=("Col2",), date_column="Col1")
    analysis = analyze_month(fixture("undetectable_columns.csv"), [], overrides=overrides)

    assert analysis.saved == pytest.approx(-19.50)
    assert flow_amounts(analysis)[("Overspent", "October 2026")] == 19.50


def test_the_month_date_range_comes_from_the_transaction_dates():
    analysis = german_month()

    assert (str(analysis.start_date), str(analysis.end_date)) == ("2026-10-01", "2026-10-28")
