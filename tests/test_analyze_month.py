"""Analyze a month: CSV bytes + Rules in, MonthAnalysis out.

Fixtures in tests/fixtures/ are hand-written and anonymised, never real exports.
Expected numbers are worked out by hand from those files.
"""

from pathlib import Path

import pytest

from finsight.month_analysis import analyze_month, rule_for_merchant

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


def test_the_month_date_range_comes_from_the_transaction_dates():
    analysis = german_month()

    assert (str(analysis.start_date), str(analysis.end_date)) == ("2026-10-01", "2026-10-28")
