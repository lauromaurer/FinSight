# FinSight

A personal desktop tool that turns one month of bank transactions into a categorized view of where the money went.

## Workflow

**Import**:
Loading one bank CSV export into FinSight; the first step of the monthly routine.
_Avoid_: Upload, load CSV

**Review**:
The step where transactions no rule matched are given a category, teaching FinSight new rules as you go.
_Avoid_: Categorize tab

**Dashboard**:
The final view of an imported month: totals and where the money flowed.
_Avoid_: Plot, Chart tab

**Advanced**:
The tucked-away area for editing rules, categories and import settings; not part of the monthly routine.
_Avoid_: Settings

## Categorizing

**Category**:
A bucket a transaction is filed under, such as Groceries or Salary.
_Avoid_: Label, sector

**Rule**:
A learned match from a merchant to a category, applied automatically on every Import.
_Avoid_: Pattern, regex, assignment

**Merchant**:
The counterparty of a transaction, as shown to the user.
_Avoid_: Payee, merchant alias

**Uncategorized**:
The state of a transaction that no rule has matched yet; it is waiting for Review.
_Avoid_: Other (when meaning "not yet matched")

**Other**:
A normal category the user deliberately picks for transactions that fit nowhere else.
_Avoid_: Uncategorized, Unknown

## Money

**Income**:
Money coming into the account in the imported month.
_Avoid_: Inflow

**Expenses**:
Money leaving the account in the imported month.
_Avoid_: Outflow, spending

**Saved**:
Income minus Expenses for the imported month; negative when more went out than came in.
_Avoid_: Net, total saved

**Overspent**:
The amount by which Expenses exceeded Income in the imported month, shown as the balancing source in the Money flow.
_Avoid_: deficit, negative saved

**Money flow**:
The diagram showing Income streams flowing into the month and out into Expense categories.
_Avoid_: Plot, chart, Sankey, FinSight flow, cash flow hub
