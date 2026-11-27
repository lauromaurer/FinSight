"""The Money flow figure is drawn straight from MonthAnalysis's Money flow data."""

from pathlib import Path

import pytest

from finsight.money_flow_chart import money_flow_figure
from finsight.month_analysis import analyze_month

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "semicolon_german_preamble.csv"


def test_money_flow_figure_draws_every_money_flow_link_with_glossary_labels():
    analysis = analyze_month(FIXTURE.read_bytes(), [{"pattern": "migros", "category": "Groceries"}])

    figure = money_flow_figure(analysis)
    sankey = figure.data[0]

    assert sorted(sankey.link.value) == pytest.approx(sorted(link.amount for link in analysis.money_flow.links))
    labels = " ".join(sankey.node.label)
    assert "Groceries" in labels and "Uncategorized" in labels and "Saved" in labels
    assert "October 2026" in labels
    assert "hub" not in (labels + figure.layout.title.text).lower()
    assert "Income CHF 5,240.00" in figure.layout.title.text
