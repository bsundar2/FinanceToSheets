"""Builds the yearly budget spreadsheet as an .xlsx, to import into Google
Sheets: the generic template a household (one person or a couple) copies
once and shares, and, through src/budget_migration.py, an existing sheet
moved onto this layout.

Layout and formulas follow the original Budget - 2026 sheet, with what a
reusable household template needs on top:
- Settings: both names, the year and each person's pay frequency, which
  every formula reads instead of hard-coding them.
- Income: each person's pay, taxes and deductions side by side; the Budget
  tab's income rows add the two up.
- Expense Log / Partner Expense Log: one tab per person, in the columns
  SplitwiseToSheets writes (or a pasted Splitwise export). "My Owed" is
  that person's share of each expense, so the two logs add up to what the
  household spent without counting a shared bill twice. Budget and Monthly
  Expenses total both.
- Accounts: balances entered by hand, plus optional blocks of balances
  imported from each person's SimpleFIN (bank_accounts_dump) with
  IMPORTRANGE.
- Net Worth: every account once, at its full balance, looked up by a
  "Balance Key" (an account name, or a fragment like "(1111)") rather than
  a fixed cell, with each person's % of it. The household totals count
  each row at both percentages added together; each person's net worth
  counts it at theirs.

The labels the dashboard's parser looks for (src/personal_finance.py) are
kept exactly as they were, so it reads both layouts."""

import argparse
import calendar
import datetime
from dataclasses import dataclass, field

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter

SETTINGS = "Settings"
INSTRUCTIONS = "Instructions"
INCOME = "Income"
BUDGET = "Budget"
MONTHLY_EXPENSES = "Monthly Expenses"
EXPENSE_LOG = "Expense Log"
PARTNER_EXPENSE_LOG = "Partner Expense Log"
EXPENSE_LOGS = [EXPENSE_LOG, PARTNER_EXPENSE_LOG]
ACCOUNTS = "Accounts"
NET_WORTH = "Net Worth"
DASHBOARD = "Dashboard"

YEAR_CELL = f"{SETTINGS}!$B$5"
PAYCHECKS_CELL = f"{SETTINGS}!$B$6"
PARTNER_PAYCHECKS_CELL = f"{SETTINGS}!$B$7"
# Each person's name, or "You" / "Partner" while Settings is blank
NAME = f'IF({SETTINGS}!$B$3="","You",{SETTINGS}!$B$3)'
PARTNER_NAME = f'IF({SETTINGS}!$B$4="","Partner",{SETTINGS}!$B$4)'

# Same order SplitwiseToSheets exports (its ExportColumns); "My Owed" (I)
# is your share of each expense, whoever paid it
EXPENSE_LOG_COLUMNS = [
    "Date",
    "Amount",
    "Category",
    "Description",
    "Details",
    "Split Type",
    "Participant Names",
    "My Paid",
    "My Owed",
    "My Net",
    "Friends Split",
    "Splitwise ID",
    "Transaction Fingerprint",
]

# Splitwise's categories (each group's "Other" named "<Group> - Other", as
# the export writes it), the Budget and Monthly Expenses rows by default
DEFAULT_CATEGORIES = [
    ("Utilities", ["Cleaning", "Electricity", "Heat/gas", "Utilities - Other",
                   "Trash", "TV/Phone/Internet", "Water"]),
    ("Uncategorized", ["General"]),
    ("Entertainment", ["Games", "Movies", "Music", "Entertainment - Other",
                       "Sports"]),
    ("Food and drink", ["Dining out", "Groceries", "Liquor",
                        "Food and drink - Other"]),
    ("Home", ["Electronics", "Furniture", "Household supplies", "Maintenance",
              "Mortgage", "Home - Other", "Pets", "Rent", "Services"]),
    ("Transportation", ["Bicycle", "Bus/train", "Car", "Gas/fuel", "Hotel",
                        "Transportation - Other", "Parking", "Plane", "Taxi"]),
    ("Life", ["Childcare", "Clothing", "Education", "Gifts", "Insurance",
              "Medical expenses", "Life - Other", "Taxes"]),
]  # fmt: skip

# Net Worth sections: (title, subtotal label). The subtotal labels are what
# the dashboard parser matches.
CASH, INVESTMENTS, RETIREMENT, REAL_ESTATE, LIABILITIES = range(5)
SECTIONS = [
    ("Cash Accounts", "Subtotal – Checking & Savings"),
    ("INVESTMENTS", "Subtotal – Investments"),
    ("RETIREMENT", "Subtotal – Retirement"),
    ("REAL ESTATE", "Subtotal – Real Estate"),
    ("LIABILITIES", "Subtotal – Liabilities"),
]
NET_WORTH_LABEL = "NET WORTH (Assets − Liabilities)"
CONTRIBUTIONS_LABEL = "Monthly Savings Contributions  (enter cash deposited each month)"
TOTAL_CONTRIBUTED_LABEL = "Total Contributed (YTD)"

# Net Worth columns: B-G describe the row (F and G are each person's %),
# H-S are Jan-Dec, then T and U
NW_SHARE_COL = 6
NW_PARTNER_SHARE_COL = 7
NW_FIRST_MONTH_COL = 8
NW_CURRENT_COL = NW_FIRST_MONTH_COL + 12
NW_CHANGE_COL = NW_CURRENT_COL + 1

ACCOUNTS_MANUAL_ROWS = 20
ACCOUNTS_FIRST_ROW = 5
# Imported balances: Institution, Account Name, Balance, Balance As Of from
# each person's bank_accounts_dump, at G5 and L5
IMPORTED_BLOCKS = ["G", "L"]

# Income columns: Actual Yearly, Budget Yearly, Monthly, Per Paycheck for
# each person
INCOME_COLUMNS = ["CDEF", "HIJK"]

INPUT_FILL = PatternFill("solid", fgColor="FFF2CC")
INPUT_FONT = Font(color="1F4E9E")
HEADER_FILL = PatternFill("solid", fgColor="1F2937")
HEADER_FONT = Font(bold=True, color="FFFFFF")
SECTION_FILL = PatternFill("solid", fgColor="E5E7EB")
TOTAL_FONT = Font(bold=True)
TITLE_FONT = Font(bold=True, size=14)
MONEY = '"$"#,##0.00;[Red]-"$"#,##0.00'
PERCENT = "0.0%"


@dataclass
class Category:
    group: str
    name: str
    yearly_budget: object = 0
    # False keeps a category out of Total Expenses (e.g. a mortgage whose
    # Splitwise entries include the down payment, which is savings)
    in_totals: bool = True


@dataclass
class ManualBalance:
    """An Accounts-tab row: a balance with no automated feed."""

    label: str
    amount: object = None
    fx_rate: object = None
    note: str = ""


@dataclass
class NetWorthRow:
    account: str
    type: str = ""
    institution: str = ""
    # Matched against Accounts: exactly against a manual row's label, or
    # as a fragment of an imported account's name. Blank = enter by hand.
    key: str = ""
    # Each person's part of the balance. The partner's defaults to the rest
    # (1 - share); setting it apart from that is for a row that moves value
    # between the two, like Extra Principal Credit (40% and -40%)
    share: object = 1
    partner_share: object = None
    # month number -> value or formula, the full balance; overrides the
    # default for that month
    months: dict = field(default_factory=dict)


@dataclass
class ContributionRow:
    type: str
    detail: str = ""
    months: dict = field(default_factory=dict)


@dataclass
class BudgetCells:
    """Your columns of the Income tab (C-F, rows 5-19: income, taxes,
    deductions, take-home), as coordinate -> value or formula, layered over
    the template's defaults."""

    overrides: dict = field(default_factory=dict)
    pre_tax_label: str = "Pre-tax deductions"


def default_net_worth() -> list[list[NetWorthRow]]:
    return [
        [
            NetWorthRow("Checking", "Yours"),
            NetWorthRow("Savings", "Yours"),
            NetWorthRow("Checking", "Partner's", share=0),
            NetWorthRow("Savings", "Partner's", share=0),
            NetWorthRow("Joint Savings", "Joint", share=0.5),
        ],
        [
            NetWorthRow("Brokerage", "Stocks"),
            NetWorthRow("Brokerage", "ETF"),
            NetWorthRow("Crypto", "Crypto"),
            NetWorthRow("Bonds", "I-Bonds"),
        ],
        [
            NetWorthRow("Retirement", "401k"),
            NetWorthRow("Retirement", "Roth IRA"),
            NetWorthRow("Retirement", "Traditional IRA"),
            NetWorthRow("Retirement", "Partner's 401k", share=0),
        ],
        [
            NetWorthRow("Real Estate", "Home Value", share=0.5),
            NetWorthRow("Liability", "Mortgage Balance (negative)", share=0.5),
            NetWorthRow(
                "Real Estate", "Extra Principal Credit", share=0, partner_share=0
            ),
        ],
        [
            NetWorthRow("Liability", "Credit Card"),
            NetWorthRow("Liability", "Car Loan"),
            NetWorthRow("Liability", "Other Debt"),
        ],
    ]


def default_contributions() -> list[ContributionRow]:
    return [
        ContributionRow("Savings", "Individual"),
        ContributionRow("Savings", "Joint"),
        ContributionRow("Brokerage", "Stocks"),
        ContributionRow("Brokerage", "ETF"),
        ContributionRow("Crypto", "Crypto"),
        ContributionRow("Bonds", "I-Bonds"),
        ContributionRow("Real Estate", "Extra Payments"),
        ContributionRow("Retirement", "Roth IRA"),
        ContributionRow("Retirement", "Traditional IRA"),
    ]


@dataclass
class BudgetSpec:
    name: str = ""
    partner: str = ""
    year: int = datetime.date.today().year
    paychecks_per_year: int = 24
    partner_paychecks_per_year: int = 24
    budget: BudgetCells = field(default_factory=BudgetCells)
    categories: list = field(
        default_factory=lambda: [
            Category(group, name)
            for group, names in DEFAULT_CATEGORIES
            for name in names
        ]
    )
    expense_rows: list = field(default_factory=list)
    partner_expense_rows: list = field(default_factory=list)
    manual_balances: list = field(default_factory=list)
    # e.g. =IMPORTRANGE("<RH_Sheets id>", "bank_accounts_dump!A2:D"), spilling
    # Institution / Account Name / Balance / Balance As Of into Accounts!G5
    # (yours) and L5 (your partner's)
    imported_balances_formula: str = ""
    partner_imported_balances_formula: str = ""
    net_worth: list = field(default_factory=default_net_worth)
    contributions: list = field(default_factory=default_contributions)


def column_letter(index: int) -> str:
    return get_column_letter(index)


def _input(cell, value=None, fmt=MONEY):
    if value is not None:
        cell.value = value
    cell.fill = INPUT_FILL
    cell.font = INPUT_FONT
    if fmt:
        cell.number_format = fmt


def _header(ws, row: int, labels: list, start_col: int = 1):
    for offset, label in enumerate(labels):
        cell = ws.cell(row=row, column=start_col + offset, value=label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def _section(ws, row: int, label: str, width: int):
    ws.cell(row=row, column=1, value=label).font = TOTAL_FONT
    for col in range(1, width + 1):
        ws.cell(row=row, column=col).fill = SECTION_FILL


def _title(ws, title: str, subtitle: str):
    ws["A1"] = title
    ws["A1"].font = TITLE_FONT
    ws["A2"] = subtitle
    ws["A2"].font = Font(italic=True, color="6B7280")


def _widths(ws, widths: dict):
    for column, width in widths.items():
        ws.column_dimensions[column].width = width


@dataclass
class _Layout:
    """Row numbers that depend on how many categories and accounts there
    are, shared by the tabs that reference each other."""

    first_category: int = 21
    last_category: int = 0
    total_expenses: int = 0
    take_home_savings: int = 0
    total_savings: int = 0
    me_first: int = 5
    me_last: int = 0
    me_total: int = 0
    nw_rows: dict = field(default_factory=dict)  # section -> (first, last)
    nw_subtotals: dict = field(default_factory=dict)  # section -> row
    nw_total: int = 0
    nw_people: tuple = ()  # your and your partner's net worth rows
    contrib_first: int = 0
    contrib_last: int = 0
    contrib_total: int = 0
    market_gains: int = 0


def plan_layout(spec: BudgetSpec) -> _Layout:
    layout = _Layout()
    count = len(spec.categories)
    layout.last_category = layout.first_category + count - 1
    layout.total_expenses = layout.last_category + 1
    layout.take_home_savings = layout.total_expenses + 1
    layout.total_savings = layout.take_home_savings + 1
    layout.me_last = layout.me_first + count - 1
    layout.me_total = layout.me_last + 1

    row = 5
    for section, rows in enumerate(spec.net_worth):
        first = row + 1  # the section title sits on `row`
        layout.nw_rows[section] = (first, first + len(rows) - 1)
        layout.nw_subtotals[section] = first + len(rows)
        row = first + len(rows) + 2  # subtotal, blank line
    layout.nw_total = row
    layout.nw_people = (row + 1, row + 2)
    layout.contrib_first = row + 6  # blank lines, then the section title
    layout.contrib_last = layout.contrib_first + len(spec.contributions) - 1
    layout.contrib_total = layout.contrib_last + 1
    layout.market_gains = layout.contrib_total + 1
    return layout


def _build_settings(ws, spec: BudgetSpec):
    _title(ws, "Settings", "Every other tab reads these - fill them in first")
    rows = [
        ("Your name", spec.name, None, "Heads your columns and rows"),
        ("Partner's name", spec.partner, None,
         "Leave blank if you're tracking just yourself"),
        ("Year", spec.year, "0", "The year this sheet tracks"),
        ("Paychecks per year", spec.paychecks_per_year, "0",
         "Yours: 24 = twice a month, 26 = every other week, 12 = monthly"),
        ("Partner's paychecks / yr", spec.partner_paychecks_per_year, "0",
         "Your partner's, the same way"),
    ]  # fmt: skip
    for offset, (label, value, fmt, note) in enumerate(rows):
        row = 3 + offset
        ws.cell(row=row, column=1, value=label).font = TOTAL_FONT
        _input(ws.cell(row=row, column=2), value, fmt)
        ws.cell(row=row, column=3, value=note).font = Font(color="6B7280")
    _widths(ws, {"A": 22, "B": 24, "C": 60})


# Income rows that hold a figure (the others are section titles), and the
# ones a person fills in from a pay stub
_INCOME_ROWS = [5, 6, 7, 9, 10, 11, 12, 13, 15, 17, 18, 19]
_ENTERED_ROWS = [9, 10, 11, 12, 15, 17, 18]

_INCOME_LABELS = {
    "B5": "Gross Salary",
    "B6": "Bonus",
    "A7": "Income",
    "B7": "Total Gross Income",
    "B9": "Federal Tax",
    "B10": "State Tax",
    "B11": "FICA / Social Security",
    "B12": "Medicare",
    "A13": "Taxes",
    "B13": "Total Taxes",
    "B17": "401k Contribution",
    "B18": "401k Company Match",
    "A19": "💵 Take-Home Pay",
}


def income_cells(columns: str, paychecks: str) -> dict:
    """One person's Income formulas, in their four columns (Actual Yearly,
    Budget Yearly, Monthly, Per Paycheck): per-paycheck figures from a pay
    stub scaled up by their pay frequency."""
    actual, yearly, monthly, paycheck = columns
    cells = {
        f"{yearly}5": f"={monthly}5*12",
        f"{monthly}5": f"={paycheck}5*{paychecks}/12",
        f"{actual}7": f"={actual}5+{actual}6",
        f"{yearly}7": f"={yearly}5+{yearly}6",
        f"{monthly}7": f"={monthly}5",
        f"{paycheck}7": f"={paycheck}5",
    }
    for col in columns:
        cells[f"{col}13"] = f"=SUM({col}9:{col}12)"
        cells[f"{col}19"] = f"={col}7-{col}13-SUM({col}15:{col}17)"
    for row in _ENTERED_ROWS:
        cells[f"{yearly}{row}"] = f"={monthly}{row}*12"
        cells[f"{monthly}{row}"] = f"={paycheck}{row}*{paychecks}/12"
    return cells


def income_inputs(columns: str) -> list[str]:
    """The cells a person fills in (amber), unless a migration put a formula
    there."""
    actual, yearly, _, paycheck = columns
    return [f"{actual}5", f"{paycheck}5", f"{actual}6", f"{yearly}6"] + [
        f"{col}{row}" for row in _ENTERED_ROWS for col in (actual, paycheck)
    ]


def _log_sum(category_cell: str, start: str, end: str) -> str:
    """Both people's share of a category between two dates: each log's
    "My Owed" (I) is its owner's part, so together they're the household's."""
    sums = [
        f"SUMIFS('{log}'!$I:$I,'{log}'!$C:$C,{category_cell},"
        f"'{log}'!$A:$A,\">=\"&{start},'{log}'!$A:$A,\"<=\"&{end})"
        for log in EXPENSE_LOGS
    ]
    return "=" + "+".join(sums)


def _build_income(ws, spec: BudgetSpec):
    _title(
        ws, "Income & Taxes",
        "Each person's pay from a pay stub — enter amber cells only; the Budget tab adds the two up",
    )  # fmt: skip
    ws["C2"], ws["H2"] = f"={NAME}", f"={PARTNER_NAME}"
    ws["C2"].font = ws["H2"].font = TOTAL_FONT
    labels = ["Actual Yearly", "Budget Yearly", "Monthly", "Per Paycheck"]
    _header(ws, 3, ["Category", "Item", *labels])
    _header(ws, 3, labels, 8)
    for row, label in [(4, "INCOME"), (8, "TAXES"), (14, "PRE-TAX"),
                       (16, "RETIREMENT")]:  # fmt: skip
        _section(ws, row, label, 11)

    cells = dict(_INCOME_LABELS)
    cells["B15"] = spec.budget.pre_tax_label
    cells.update(income_cells(INCOME_COLUMNS[0], PAYCHECKS_CELL))
    cells.update(income_cells(INCOME_COLUMNS[1], PARTNER_PAYCHECKS_CELL))
    cells.update(spec.budget.overrides)
    for columns in INCOME_COLUMNS:
        for coordinate in income_inputs(columns):
            _input(ws[coordinate])
    for coordinate, value in cells.items():
        ws[coordinate] = value
        if coordinate[0] not in "AB":
            ws[coordinate].number_format = MONEY
    for row in (7, 13, 19):
        for col in "AB" + "".join(INCOME_COLUMNS):
            ws[f"{col}{row}"].font = TOTAL_FONT
    ws.freeze_panes = "C4"
    _widths(ws, {"A": 16, "B": 26, "G": 3,
                 **{c: 14 for c in "".join(INCOME_COLUMNS)}})  # fmt: skip


def _build_budget(ws, spec: BudgetSpec, layout: _Layout):
    _title(
        ws, "Household Budget",
        "Pay comes from the Income tab, spending from both Expense Logs — enter a yearly budget per category (amber)",
    )  # fmt: skip
    _header(
        ws, 3,
        ["Category", "Item", "Actual Yearly", "Budget Yearly", "Monthly",
         "Per Paycheck", "% of Gross", "% of Take-Home", "In Totals"],
    )  # fmt: skip
    for row, label in [(4, "INCOME"), (8, "TAXES"), (14, "PRE-TAX"),
                       (16, "RETIREMENT"), (20, "EXPENSES")]:  # fmt: skip
        _section(ws, row, label, 9)

    # Income rows: the two people's Income columns added up. Per Paycheck
    # stays on the Income tab, since the two can be paid on different
    # schedules.
    for coordinate, label in _INCOME_LABELS.items():
        ws[coordinate] = label
    ws["B15"] = f"={INCOME}!B15"
    yours, partners = INCOME_COLUMNS
    for row in _INCOME_ROWS:
        for target, mine, theirs in zip("CDE", yours, partners):
            ws[f"{target}{row}"] = f"={INCOME}!{mine}{row}+{INCOME}!{theirs}{row}"
            ws[f"{target}{row}"].number_format = MONEY
        if row not in (5, 6, 7):
            ws[f"G{row}"] = f'=IFERROR(D{row}/$D$7,"-")'
            ws[f"G{row}"].number_format = PERCENT
    for coordinate in ("A7", "B7", "A13", "B13", "A19", "B19"):
        ws[coordinate].font = TOTAL_FONT

    first, last = layout.first_category, layout.last_category
    year_start = f"DATE({YEAR_CELL},1,1)"
    year_end = f"DATE({YEAR_CELL},12,31)"
    for offset, category in enumerate(spec.categories):
        row = first + offset
        ws.cell(row=row, column=1, value=category.group)
        ws.cell(row=row, column=2, value=category.name)
        ws.cell(
            row=row, column=3, value=_log_sum(f"$B{row}", year_start, year_end)
        ).number_format = MONEY
        _input(ws.cell(row=row, column=4), category.yearly_budget)
        ws.cell(row=row, column=5, value=f"=D{row}/12").number_format = MONEY
        ws.cell(row=row, column=6, value=f"=D{row}/{PAYCHECKS_CELL}").number_format = (
            MONEY
        )
        ws.cell(row=row, column=7, value=f'=IFERROR(D{row}/$D$7,"-")').number_format = (
            PERCENT
        )
        ws.cell(
            row=row, column=8, value=f'=IFERROR(D{row}/$D$19,"-")'
        ).number_format = PERCENT
        _input(ws.cell(row=row, column=9), "Yes" if category.in_totals else "No", None)

    total = layout.total_expenses
    rng = f"{first}:{{c}}{last}"
    ws[f"A{total}"], ws[f"B{total}"] = "Expenses", "Total Expenses"
    for col in "CD":
        ws[f"{col}{total}"] = (
            f'=SUMIF($I{first}:$I{last},"Yes",{col}{rng.format(c=col)})'
        )
    ws[f"E{total}"] = f"=D{total}/12"
    ws[f"F{total}"] = f"=D{total}/{PAYCHECKS_CELL}"
    ws[f"G{total}"] = f'=IFERROR(D{total}/$D$7,"-")'
    ws[f"H{total}"] = f'=IFERROR(D{total}/$D$19,"-")'

    saving = layout.take_home_savings
    ws[f"A{saving}"], ws[f"B{saving}"] = "Savings", "Take-Home Savings"
    ws[f"C{saving}"] = (
        f"='{NET_WORTH}'!{column_letter(NW_CURRENT_COL)}{layout.contrib_total}"
    )
    for col in "DEF":
        ws[f"{col}{saving}"] = f"={col}19-{col}{total}"
    ws[f"G{saving}"] = f'=IFERROR(D{saving}/$D$7,"-")'
    ws[f"H{saving}"] = f'=IFERROR(D{saving}/$D$19,"-")'

    all_savings = layout.total_savings
    ws[f"A{all_savings}"], ws[f"B{all_savings}"] = "Savings", "Total Savings"
    ws[f"C{all_savings}"] = f"=C{saving}+C17"
    ws[f"D{all_savings}"] = f"=D{saving}+D17"
    ws[f"G{all_savings}"] = f'=IFERROR(D{all_savings}/$D$7,"-")'

    for row in (total, saving, all_savings):
        ws[f"A{row}"].font = ws[f"B{row}"].font = TOTAL_FONT
        for col in "CDEF":
            ws[f"{col}{row}"].number_format = MONEY
        for col in "GH":
            ws[f"{col}{row}"].number_format = PERCENT
    ws.freeze_panes = "C4"
    _widths(ws, {"A": 16, "B": 26, "C": 15, "D": 15, "E": 13, "F": 13,
                 "G": 11, "H": 13, "I": 10})  # fmt: skip


def _build_monthly_expenses(ws, spec: BudgetSpec, layout: _Layout):
    _title(
        ws, "Monthly Expense Tracker",
        "Both Expense Logs by month (each person's share of every expense) — budgets come from the Budget tab",
    )  # fmt: skip
    months = [calendar.month_abbr[m] for m in range(1, 13)]
    _header(
        ws, 4,
        ["Category", "Sub-Category", "Monthly\nBudget", *months, "YTD\nActual",
         "Annual\nBudget", "Variance\n(Budget−Actual)", "Over Budget"],
    )  # fmt: skip
    for offset in range(len(spec.categories)):
        row = layout.me_first + offset
        source = layout.first_category + offset
        ws[f"A{row}"] = f"={BUDGET}!A{source}"
        ws[f"B{row}"] = f"={BUDGET}!B{source}"
        ws[f"C{row}"] = f"={BUDGET}!D{source}/12"
        for month in range(1, 13):
            start = f"DATE({YEAR_CELL},{month},1)"
            ws.cell(
                row=row, column=3 + month,
                value=_log_sum(f"$B{row}", start, f"EOMONTH({start},0)"),
            )  # fmt: skip
        ws[f"P{row}"] = f"=SUM(D{row}:O{row})"
        ws[f"Q{row}"] = f"={BUDGET}!D{source}"
        ws[f"R{row}"] = f"=Q{row}-P{row}"
        ws[f"S{row}"] = f"=MAX(0,P{row}-Q{row})"
    total = layout.me_total
    ws[f"A{total}"] = "TOTAL EXPENSES"
    ws[f"A{total}"].font = TOTAL_FONT
    for col in range(3, 20):
        letter = column_letter(col)
        ws[f"{letter}{total}"] = (
            f"=Q{total}-P{total}"
            if letter == "R"
            else f"=SUM({letter}{layout.me_first}:{letter}{layout.me_last})"
        )
        ws[f"{letter}{total}"].font = TOTAL_FONT
    for row in ws.iter_rows(min_row=layout.me_first, max_row=total, min_col=3):
        for cell in row:
            cell.number_format = MONEY
    ws.freeze_panes = "C5"
    _widths(ws, {"A": 16, "B": 24, **{column_letter(c): 12 for c in range(3, 20)}})


def _build_expense_log(ws, rows: list):
    _header(ws, 1, EXPENSE_LOG_COLUMNS)
    for values in rows:
        ws.append(list(values))
    for row in ws.iter_rows(min_row=2, max_col=1):
        row[0].number_format = "yyyy-mm-dd"
    ws.freeze_panes = "A2"
    _widths(ws, {"A": 12, "B": 11, "C": 20, "D": 32, "G": 26})


def _build_accounts(ws, spec: BudgetSpec):
    _title(
        ws, "Accounts",
        "Balances the Net Worth tab looks up by its Balance Key column",
    )  # fmt: skip
    ws["A3"] = "Entered by hand"
    ws["G3"] = '="Imported for "&' + NAME + '&" (optional)"'
    ws["L3"] = '="Imported for "&' + PARTNER_NAME + '&" (optional)"'
    ws["G2"] = (
        'Each: =IMPORTRANGE("<that person\'s sheet id>", "bank_accounts_dump!A2:D") in row 5'
    )
    ws["A3"].font = ws["G3"].font = ws["L3"].font = TOTAL_FONT
    _header(ws, 4, ["Account", "Amount", "FX Rate", "Value", "Notes"])
    for col in IMPORTED_BLOCKS:
        _header(
            ws, 4, ["Institution", "Account Name", "Balance", "Balance As Of"],
            column_index_from_string(col),
        )  # fmt: skip
    for offset in range(ACCOUNTS_MANUAL_ROWS):
        row = ACCOUNTS_FIRST_ROW + offset
        balance = (
            spec.manual_balances[offset]
            if offset < len(spec.manual_balances)
            else ManualBalance("")
        )
        _input(ws[f"A{row}"], balance.label or None, None)
        _input(ws[f"B{row}"], balance.amount)
        _input(ws[f"C{row}"], balance.fx_rate, "0.000000")
        ws[f"D{row}"] = f'=IF(B{row}="","",B{row}*IF(C{row}="",1,C{row}))'
        ws[f"D{row}"].number_format = MONEY
        ws[f"E{row}"] = balance.note or None
    for col, formula in zip(
        IMPORTED_BLOCKS,
        [spec.imported_balances_formula, spec.partner_imported_balances_formula],
    ):
        if formula:
            ws[f"{col}5"] = formula
    ws.freeze_panes = "A5"
    _widths(ws, {"A": 24, "B": 14, "C": 11, "D": 14, "E": 30, "F": 3,
                 "G": 22, "H": 36, "I": 14, "J": 14, "K": 3,
                 "L": 22, "M": 36, "N": 14, "O": 14})  # fmt: skip


def lookup_formula(row: int) -> str:
    """A Net Worth row's live balance, in full: the Accounts value whose
    label equals the key, plus any imported balance (either person's) whose
    account name contains it."""
    sums = [f"SUMIF({ACCOUNTS}!$A:$A,$E{row},{ACCOUNTS}!$D:$D)"]
    for col in IMPORTED_BLOCKS:
        name = get_column_letter(column_index_from_string(col) + 1)
        balance = get_column_letter(column_index_from_string(col) + 2)
        sums.append(
            f'SUMIF({ACCOUNTS}!${name}:${name},"*"&$E{row}&"*",'
            f"{ACCOUNTS}!${balance}:${balance})"
        )
    return "=" + "+".join(sums)


def _weighted(col: str, first: int, last: int, *share_cols: str) -> str:
    """A month column's rows each weighted by the share columns added up."""
    shares = "+".join(f"${c}${first}:${c}${last}" for c in share_cols)
    return f"=SUMPRODUCT({col}{first}:{col}{last},{shares})"


def _build_net_worth(ws, spec: BudgetSpec, layout: _Layout):
    _title(
        ws, "Net Worth Tracker",
        "Every account once, at its full balance, with each person's % · rows with a Balance Key "
        "fill in from Accounts · paste values over a month at month end to freeze it",
    )  # fmt: skip
    months = [calendar.month_abbr[m] for m in range(1, 13)]
    _header(
        ws, 4,
        ["", "Account", "Type", "Institution", "Balance Key", f'={NAME}&" %"',
         f'={PARTNER_NAME}&" %"', *months, "Dec Close /\nCurrent", "YTD Change"],
    )  # fmt: skip
    current, change = column_letter(NW_CURRENT_COL), column_letter(NW_CHANGE_COL)
    first_month, last_month = column_letter(NW_FIRST_MONTH_COL), column_letter(
        NW_CURRENT_COL - 1
    )
    share, partner_share = column_letter(NW_SHARE_COL), column_letter(
        NW_PARTNER_SHARE_COL
    )

    for section, rows in enumerate(spec.net_worth):
        first, last = layout.nw_rows[section]
        _section(ws, first - 1, SECTIONS[section][0], NW_CHANGE_COL)
        for offset, item in enumerate(rows):
            row = first + offset
            ws[f"B{row}"], ws[f"C{row}"], ws[f"D{row}"] = (
                item.account, item.type, item.institution,
            )  # fmt: skip
            _input(ws[f"E{row}"], item.key or None, None)
            _input(ws[f"{share}{row}"], item.share, "0%")
            _input(
                ws[f"{partner_share}{row}"],
                f"=1-{share}{row}" if item.partner_share is None else item.partner_share,
                "0%",
            )  # fmt: skip
            for month in range(1, 13):
                cell = ws.cell(row=row, column=NW_FIRST_MONTH_COL + month - 1)
                if month in item.months:
                    cell.value = item.months[month]
                    cell.number_format = MONEY
                elif item.key:
                    cell.value = lookup_formula(row)
                    cell.number_format = MONEY
                else:
                    _input(cell)
            ws[f"{current}{row}"] = f"={last_month}{row}"
            ws[f"{change}{row}"] = f"={current}{row}-{first_month}{row}"
        subtotal = layout.nw_subtotals[section]
        ws[f"A{subtotal}"] = SECTIONS[section][1]
        ws[f"A{subtotal}"].font = TOTAL_FONT
        for col in range(NW_FIRST_MONTH_COL, NW_CURRENT_COL + 1):
            letter = column_letter(col)
            # Each row at both people's % added up: 100% for an account, 0%
            # for a row that only moves value between the two. An empty
            # section's range would wrap around to the subtotal itself.
            ws[f"{letter}{subtotal}"] = (
                _weighted(letter, first, last, share, partner_share) if rows else 0
            )
            ws[f"{letter}{subtotal}"].font = TOTAL_FONT
        ws[f"{change}{subtotal}"] = f"={current}{subtotal}-{first_month}{subtotal}"

    total = layout.nw_total
    ws[f"A{total}"] = NET_WORTH_LABEL
    ws[f"A{total}"].font = TOTAL_FONT
    subtotals = list(layout.nw_subtotals.values())
    for col in range(NW_FIRST_MONTH_COL, NW_CURRENT_COL + 1):
        letter = column_letter(col)
        ws[f"{letter}{total}"] = "=" + "+".join(f"{letter}{r}" for r in subtotals)
        ws[f"{letter}{total}"].font = TOTAL_FONT
    ws[f"{change}{total}"] = f"={current}{total}-{first_month}{total}"

    # Each person's net worth: every row above at their % (section titles
    # and subtotals have no %, so they count as 0)
    for row, name, col in zip(
        layout.nw_people, [NAME, PARTNER_NAME], [share, partner_share]
    ):
        ws[f"A{row}"] = f'="   "&{name}&"\'s share"'
        for month_col in range(NW_FIRST_MONTH_COL, NW_CURRENT_COL + 1):
            letter = column_letter(month_col)
            ws[f"{letter}{row}"] = _weighted(letter, 5, total - 1, col)
        ws[f"{change}{row}"] = f"={current}{row}-{first_month}{row}"

    ws.cell(row=layout.contrib_first - 1, column=1, value=CONTRIBUTIONS_LABEL).font = (
        TOTAL_FONT
    )
    for offset, item in enumerate(spec.contributions):
        row = layout.contrib_first + offset
        ws[f"B{row}"], ws[f"C{row}"] = item.type, item.detail
        for month in range(1, 13):
            _input(
                ws.cell(row=row, column=NW_FIRST_MONTH_COL + month - 1),
                item.months.get(month),
            )
        ws[f"{current}{row}"] = f"=SUM({first_month}{row}:{last_month}{row})"
    contrib_total = layout.contrib_total
    ws[f"A{contrib_total}"] = TOTAL_CONTRIBUTED_LABEL
    ws[f"A{contrib_total}"].font = TOTAL_FONT
    for col in range(NW_FIRST_MONTH_COL, NW_CURRENT_COL):
        letter = column_letter(col)
        ws[f"{letter}{contrib_total}"] = (
            f"=SUM({letter}{layout.contrib_first}:{letter}{layout.contrib_last})"
        )
    ws[f"{current}{contrib_total}"] = (
        f"=SUM({first_month}{contrib_total}:{last_month}{contrib_total})"
    )
    gains = layout.market_gains
    ws[f"A{gains}"] = "Market Gains / (Losses)  =  Net Worth Change − Contributions"
    ws[f"{current}{gains}"] = (
        f"={current}{total}-{first_month}{total}-{current}{contrib_total}"
        f"-{BUDGET}!C17-{BUDGET}!C18"
    )
    ws[f"{change}{gains}"] = f"=IFERROR({current}{gains}/{change}{total},0)"
    ws[f"{change}{gains}"].number_format = PERCENT

    for row in ws.iter_rows(min_row=5, max_row=gains, min_col=NW_FIRST_MONTH_COL):
        for cell in row:
            if cell.number_format == "General":
                cell.number_format = MONEY
    ws.freeze_panes = ws.cell(row=5, column=NW_FIRST_MONTH_COL)
    _widths(ws, {"A": 6, "B": 22, "C": 24, "D": 18, "E": 14, "F": 10, "G": 10,
                 **{column_letter(c): 13 for c in range(NW_FIRST_MONTH_COL, NW_CHANGE_COL + 1)}})  # fmt: skip


def _kpi(ws, row: int, col: int, label: str, formula: str, fmt=MONEY):
    ws.cell(row=row, column=col, value=label).font = Font(bold=True, color="6B7280")
    value = ws.cell(row=row + 1, column=col, value=formula)
    value.font = Font(bold=True, size=13)
    value.number_format = fmt


def _build_dashboard(ws, spec: BudgetSpec, layout: _Layout):
    ws["A1"] = (
        f'="Household Finance Dashboard · "&{SETTINGS}!B3'
        f'&IF({SETTINGS}!B4="",""," & "&{SETTINGS}!B4)&" · "&{YEAR_CELL}'
    )
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "Everything here fills in from the other tabs"
    total, saving = layout.total_expenses, layout.take_home_savings
    nw_current = f"'{NET_WORTH}'!{column_letter(NW_CURRENT_COL)}"
    nw_change = f"'{NET_WORTH}'!{column_letter(NW_CHANGE_COL)}"
    yours, partners = layout.nw_people
    spent = [
        f"=SUMIFS('{log}'!$I:$I,'{log}'!$A:$A,\">=\"&DATE({YEAR_CELL},1,1),"
        f"'{log}'!$A:$A,\"<=\"&DATE({YEAR_CELL},12,31))"
        for log in EXPENSE_LOGS
    ]
    kpis = [
        (4, [("BUDGETED GROSS INCOME", f"={BUDGET}!D7"),
             ("BUDGETED TAKE-HOME PAY", f"={BUDGET}!D19"),
             ("BUDGETED EXPENSES", f"={BUDGET}!D{total}"),
             ("BUDGETED TAKE-HOME SAVINGS", f"={BUDGET}!D{saving}")]),
        (7, [("ACTUAL GROSS INCOME", f"={BUDGET}!C7"),
             ("ACTUAL TAKE-HOME PAY", f"={BUDGET}!C19"),
             ("ACTUAL EXPENSES", f"={BUDGET}!C{total}"),
             ("ACTUAL TAKE-HOME SAVINGS", f"={BUDGET}!C{saving}")]),
        (10, [("YTD 401k CONTRIBUTIONS", f"={BUDGET}!C17"),
              ("YTD TOTAL SAVINGS", f"={BUDGET}!C{layout.total_savings}"),
              ("RETIREMENT SAVINGS", f"={nw_current}{layout.nw_subtotals[RETIREMENT]}"),
              ("TAKE-HOME SAVINGS RATE", f"=IFERROR({BUDGET}!C{saving}/{BUDGET}!C19,0)")]),
        (13, [("CURRENT NET WORTH", f"={nw_current}{layout.nw_total}"),
              ("YTD NET WORTH CHANGE", f"={nw_change}{layout.nw_total}"),
              ("YTD MARKET CHANGE", f"={nw_current}{layout.market_gains}"),
              ("YTD MARKET CHANGE %", f"={nw_change}{layout.market_gains}")]),
        (16, [(f'=UPPER({NAME})&" · NET WORTH"', f"={nw_current}{yours}"),
              (f'=UPPER({PARTNER_NAME})&" · NET WORTH"', f"={nw_current}{partners}"),
              (f'=UPPER({NAME})&" · YTD SPENDING"', spent[0]),
              (f'=UPPER({PARTNER_NAME})&" · YTD SPENDING"', spent[1])]),
    ]  # fmt: skip
    for row, items in kpis:
        for index, (label, formula) in enumerate(items):
            fmt = PERCENT if label.endswith(("RATE", "%")) else MONEY
            _kpi(ws, row, 1 + index * 2, label, formula, fmt)

    row = 19
    ws[f"A{row}"] = "BUDGET VS. ACTUAL  ·  YTD EXPENSE SUMMARY"
    ws[f"A{row}"].font = TOTAL_FONT
    _header(
        ws, row + 1,
        ["CATEGORY", "LINE ITEM", "MONTHLY BUDGET", "YTD ACTUAL", "ANNUAL BUDGET",
         "VARIANCE", "STATUS"],
    )  # fmt: skip
    me = f"'{MONTHLY_EXPENSES}'"
    first = row + 2
    for offset in range(len(spec.categories)):
        r, source = first + offset, layout.me_first + offset
        ws[f"A{r}"], ws[f"B{r}"] = f"={me}!A{source}", f"={me}!B{source}"
        ws[f"C{r}"], ws[f"D{r}"] = f"={me}!C{source}", f"={me}!P{source}"
        ws[f"E{r}"], ws[f"F{r}"] = f"={me}!Q{source}", f"=E{r}-D{r}"
        ws[f"G{r}"] = f'=IF(F{r}>=0,"✓ on track","✗ over")'
    last = first + len(spec.categories) - 1
    r = last + 1
    ws[f"A{r}"], ws[f"B{r}"] = "TOTAL", "All expenses"
    for col in "CDE":
        ws[f"{col}{r}"] = f"=SUM({col}{first}:{col}{last})"
    ws[f"F{r}"] = f"=E{r}-D{r}"
    ws[f"G{r}"] = f'=IF(F{r}>=0,"✅ On Budget","🔴 Over Budget")'
    ws[f"A{r}"].font = TOTAL_FONT
    for cells in ws.iter_rows(min_row=first, max_row=r, min_col=3, max_col=6):
        for cell in cells:
            cell.number_format = MONEY

    # Top 5 lists with LARGE/INDEX/MATCH, which Google Sheets, Excel and
    # LibreOffice all evaluate the same way
    budget_first, budget_last = layout.first_category, layout.last_category
    spend = f"{BUDGET}!$C${budget_first}:$C${budget_last}"
    r += 3
    ws[f"A{r}"] = "TOP 5 BY SPEND  ·  YTD"
    ws[f"A{r}"].font = TOTAL_FONT
    _header(
        ws, r + 1, ["CATEGORY", "LINE ITEM", "YTD SPEND", "BUDGET", "% TOTAL SPEND"]
    )
    for k in range(1, 6):
        row = r + 1 + k
        match = f"MATCH(C{row},{spend},0)"
        ws[f"C{row}"] = f"=LARGE({spend},{k})"
        ws[f"A{row}"] = f"=INDEX({BUDGET}!$A${budget_first}:$A${budget_last},{match})"
        ws[f"B{row}"] = f"=INDEX({BUDGET}!$B${budget_first}:$B${budget_last},{match})"
        ws[f"D{row}"] = f"=INDEX({BUDGET}!$D${budget_first}:$D${budget_last},{match})"
        ws[f"E{row}"] = f"=IFERROR(C{row}/{BUDGET}!$C${total},0)"
        ws[f"C{row}"].number_format = ws[f"D{row}"].number_format = MONEY
        ws[f"E{row}"].number_format = PERCENT

    over = f"{me}!$S${layout.me_first}:$S${layout.me_last}"
    r += 9
    ws[f"A{r}"] = "TOP 5 OVERSPEND  ·  YTD"
    ws[f"A{r}"].font = TOTAL_FONT
    _header(ws, r + 1, ["CATEGORY", "LINE ITEM", "YTD SPEND", "BUDGET", "OVER BY"])
    for k in range(1, 6):
        row = r + 1 + k
        match = f"MATCH(E{row},{over},0)"
        ws[f"E{row}"] = f'=IF(LARGE({over},{k})>0,LARGE({over},{k}),"")'
        for col, source in (("A", "A"), ("B", "B"), ("C", "P"), ("D", "Q")):
            ws[f"{col}{row}"] = (
                f'=IF(E{row}="","",INDEX({me}!${source}${layout.me_first}:'
                f"${source}${layout.me_last},{match}))"
            )
        for col in "CDE":
            ws[f"{col}{row}"].number_format = MONEY

    r += 9
    ws[f"A{r}"] = "SPENDING BY PERSON  ·  YTD"
    ws[f"A{r}"].font = TOTAL_FONT
    _header(ws, r + 1, ["PERSON", "THEIR SHARE", "TRANSACTIONS", "% OF HOUSEHOLD"])
    for k, (name, log, total_spent) in enumerate(
        zip([NAME, PARTNER_NAME], EXPENSE_LOGS, spent)
    ):
        row = r + 2 + k
        ws[f"A{row}"] = f"={name}"
        ws[f"B{row}"] = total_spent
        ws[f"C{row}"] = (
            f"=COUNTIFS('{log}'!$A:$A,\">=\"&DATE({YEAR_CELL},1,1),"
            f"'{log}'!$A:$A,\"<=\"&DATE({YEAR_CELL},12,31))"
        )
        ws[f"D{row}"] = f"=IFERROR(B{row}/SUM($B${r + 2}:$B${r + 3}),0)"
        ws[f"B{row}"].number_format = MONEY
        ws[f"D{row}"].number_format = PERCENT
    _widths(ws, {c: 18 for c in "ABCDEFGH"})


_INSTRUCTIONS = [
    ("Household Finance Template", None),
    ("One sheet for the household, shared by both of you (or just you). Fill in the amber cells — everything else calculates automatically.", None),
    ("", None),
    ("SET UP  ·  < 30 MIN", None),
    ("Step 1  ·  ⚙️ Settings", "Both names, the year and how often each of you is paid. Leave your partner's name blank if it's just you."),
    ("Step 2  ·  💵 Income", "Each person's per-paycheck gross pay, withholding and 401k from a pay stub, in their own columns"),
    ("Step 3  ·  📋 Budget", "A yearly household budget per category. Pay and taxes add up from Income."),
    ("Step 4  ·  🧾 Expense Logs", "Expense Log is yours and Partner Expense Log is your partner's: each filled by that person's SplitwiseToSheets (--worksheet / EXPENSES_WORKSHEET_NAME), or a pasted Splitwise CSV export (Date, Amount, Category, ... My Owed in column I)"),
    ("Step 5  ·  🏦 Accounts", "Enter balances by hand, and/or import each person's SimpleFIN balances with IMPORTRANGE (yours into G5, your partner's into L5)"),
    ("Step 6  ·  📈 Net Worth", "List every account once with a Balance Key (an Accounts label, or part of an imported account name like \"(1111)\") and each person's %"),
    ("Step 7  ·  📊 Dashboard", "Fills in from everything above"),
    ("", None),
    ("HOW THE HOUSEHOLD ADDS UP", None),
    ("  Spending", "Each Expense Log's My Owed is that person's share of every expense, whoever paid. A bill you split shows up in both logs, each with its own share, so the two logs add up to the full cost without counting it twice."),
    ("  Accounts", "Net Worth lists each account once, at its full balance. Its two % columns say whose it is: 100% / 0% for yours, 0% / 100% for your partner's, e.g. 50% / 50% or 60% / 40% for a joint account or the house."),
    ("  Totals", "The section subtotals and NET WORTH are the household's. The two rows under NET WORTH are each person's own net worth, each row counted at their %."),
    ("  The house", "Home value and mortgage at full value, with each owner's %. Enter the mortgage balance as a negative number."),
    ("  Extra principal", "If one of you pays extra principal alone, enter the total paid on Extra Principal Credit with the other person's ownership % as the payer's % and minus that as the other's (e.g. 40% / -40%): it moves that part of the equity to the payer without changing the household total."),
    ("  Just you", "Leave the partner columns, Partner Expense Log and the partner's import empty, and put 100% on your rows."),
    ("", None),
    ("MONTH END", None),
    ("  Freeze the month", "Net Worth months fill in live from Accounts. At month end, copy that month's column and paste values only, so it stops changing."),
    ("  Contributions", "Enter what either of you put into each kind of account that month at the bottom of Net Worth; the rest of the change is markets and debt paydown."),
]  # fmt: skip


def _build_instructions(ws):
    for offset, (label, text) in enumerate(_INSTRUCTIONS):
        row = 1 + offset
        ws[f"B{row}"] = label or None
        ws[f"C{row}"] = text
        if text is None and label:
            ws[f"B{row}"].font = TITLE_FONT if row == 1 else TOTAL_FONT
    _widths(ws, {"A": 3, "B": 30, "C": 110})


def build_workbook(spec: BudgetSpec) -> Workbook:
    """The whole spreadsheet, tabs in the order a person fills them in."""
    layout = plan_layout(spec)
    wb = Workbook()
    wb.active.title = INSTRUCTIONS
    _build_instructions(wb.active)
    for title, build in [
        (SETTINGS, lambda ws: _build_settings(ws, spec)),
        (INCOME, lambda ws: _build_income(ws, spec)),
        (BUDGET, lambda ws: _build_budget(ws, spec, layout)),
        (MONTHLY_EXPENSES, lambda ws: _build_monthly_expenses(ws, spec, layout)),
        (EXPENSE_LOG, lambda ws: _build_expense_log(ws, spec.expense_rows)),
        (
            PARTNER_EXPENSE_LOG,
            lambda ws: _build_expense_log(ws, spec.partner_expense_rows),
        ),
        (ACCOUNTS, lambda ws: _build_accounts(ws, spec)),
        (NET_WORTH, lambda ws: _build_net_worth(ws, spec, layout)),
        (DASHBOARD, lambda ws: _build_dashboard(ws, spec, layout)),
    ]:
        build(wb.create_sheet(title))
    return wb


def main():
    parser = argparse.ArgumentParser(description="Write the blank budget template")
    parser.add_argument("--out", default="Budget Template.xlsx")
    parser.add_argument("--year", type=int, default=datetime.date.today().year)
    args = parser.parse_args()
    build_workbook(BudgetSpec(year=args.year)).save(args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
