"""Draws the Money flow. A thin layer: every number comes from MonthAnalysis."""

from __future__ import annotations

import plotly.graph_objects as go

from finsight.month_analysis import MonthAnalysis


def _chf(value: float) -> str:
    return f"CHF {value:,.2f}"


def money_flow_figure(analysis: MonthAnalysis, title: str | None = None) -> go.Figure:
    flow = analysis.money_flow
    index = {node.id: i for i, node in enumerate(flow.nodes)}

    def node_label(node) -> str:
        if node.side == "month":
            return f"{node.label} (Saved {'-' if analysis.saved < 0 else ''}{_chf(abs(analysis.saved))})"
        # Income streams and Saved are shares of Income; Expense Categories of Expenses.
        total = analysis.expenses if node.side == "expenses" and node.id != "saved" else analysis.income
        share = f" - {node.amount / total * 100:.1f}%" if total else ""
        return f"{node.label} ({_chf(node.amount)}{share})"

    figure = go.Figure(
        go.Sankey(
            arrangement="snap",
            node=dict(
                label=[node_label(node) for node in flow.nodes],
                pad=22,
                thickness=18,
                line=dict(color="rgba(17,24,39,0.18)", width=0.5),
            ),
            link=dict(
                source=[index[link.source] for link in flow.links],
                target=[index[link.target] for link in flow.links],
                value=[link.amount for link in flow.links],
                hovertemplate="%{source.label} → %{target.label}<br>%{value:,.2f} CHF<extra></extra>",
            ),
        )
    )
    heading = title or analysis.month_label
    saved = f"{'-' if analysis.saved < 0 else ''}{_chf(abs(analysis.saved))}"
    figure.update_layout(
        title=f"{heading} - Income {_chf(analysis.income)} - Expenses {_chf(analysis.expenses)} - Saved {saved}",
        font=dict(size=13, family="Inter, Segoe UI, Arial"),
        paper_bgcolor="#f8fafc",
        plot_bgcolor="#f8fafc",
        height=720,
        margin=dict(l=24, r=24, t=72, b=24),
    )
    return figure
