"""Parsing and analysis behind the personal finance dashboard
(src/finance_dashboard.py), kept out of the marimo cells so it can be unit
tested - the same split as pnl_calculator.py and pnl_tracker.py.

Everything here reads the yearly budget spreadsheet's tabs as raw cell
matrices (see read_values_from_sheets), since most of them are laid out as
reports with title rows above the header rather than as plain tables."""

import calendar
import os
import re

import pandas as pd

from src.constants.gsheets import (
    BUDGET_SPREADSHEET_NAME_ENV_VAR,
    DEFAULT_BUDGET_SPREADSHEET_NAME,
    HOLDINGS_DUMP_SHEET_NAME,
)
from src.external_services.google_sheets import (
    read_from_sheets,
    read_values_from_sheets,
)

EXPENSE_LOG_TAB = "Expense Log"
# The household template's second log, for the partner's share of each
# expense; older single-person sheets don't have it
PARTNER_EXPENSE_LOG_TAB = "Partner Expense Log"
# The older single-person sheet's hand-kept tab (dividends, interest, stock
# gain/loss); the household template has none, so it's read only if present
SAVINGS_LOG_TAB = "Savings Log"
MONTHLY_EXPENSES_TAB = "Monthly Expenses"
BUDGET_TAB = "Budget"
NET_WORTH_TAB = "Net Worth"
BUDGET_TABS = [EXPENSE_LOG_TAB, MONTHLY_EXPENSES_TAB, BUDGET_TAB, NET_WORTH_TAB]

# Spending categories missing from the Monthly Expenses tab land here
OTHER_GROUP = "Other"

# Net Worth tab subtotal rows (column A), matched by keyword since the labels
# use typographic dashes ("Subtotal – Investments"), in display order
NET_WORTH_COMPONENTS = {
    "checking": "Cash & Savings",
    "investment": "Investments",
    "retirement": "Retirement",
    "real estate": "Real Estate",
    "liabilit": "Liabilities",
}
NET_WORTH = "Net Worth"
CONTRIBUTIONS = "Contributions"

_SHEETS_EPOCH = pd.Timestamp("1899-12-30")


def budget_spreadsheet_name() -> str:
    """The budget spreadsheet to read: BUDGET_SPREADSHEET_NAME, if set."""
    return os.environ.get(
        BUDGET_SPREADSHEET_NAME_ENV_VAR, DEFAULT_BUDGET_SPREADSHEET_NAME
    )


def budget_year(spreadsheet_name: str, today: pd.Timestamp) -> int:
    """The year in the spreadsheet's name ("Budget - 2026"), else today's."""
    match = re.search(r"(19|20)\d\d", spreadsheet_name)
    return int(match.group(0)) if match else today.year


def load_net_worth_tabs(spreadsheet_name: str) -> dict[str, list[list]]:
    """The tabs the Net Worth page reads: Net Worth, Budget (for the 401(k)
    in the market change) and, if the sheet has one, the Savings Log."""
    return read_values_from_sheets(
        [NET_WORTH_TAB, BUDGET_TAB], spreadsheet_name, (SAVINGS_LOG_TAB,)
    )


def load_budget_workbook(spreadsheet_name: str) -> dict[str, list[list]]:
    """Every tab the dashboard reads, as raw cell matrices."""
    return read_values_from_sheets(
        BUDGET_TABS, spreadsheet_name, (PARTNER_EXPENSE_LOG_TAB,)
    )


def _cell(row: list, index: int):
    return row[index] if index < len(row) else ""


def _to_number(value) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").replace("$", "").replace(",", "").strip()
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def _to_date(value) -> pd.Timestamp:
    """A cell holding a date: a serial day number (how the Sheets API returns
    a date cell unformatted), or text that looks like a date."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _SHEETS_EPOCH + pd.Timedelta(days=float(value))
    return pd.to_datetime(value or None, errors="coerce")


def _find_row(values: list[list], label: str) -> int:
    for index, row in enumerate(values):
        if any(str(cell).strip() == label for cell in row):
            return index
    raise ValueError(f"No row containing '{label}'")


def _column(header: list, label: str) -> int:
    for index, cell in enumerate(header):
        if str(cell).strip() == label:
            return index
    raise ValueError(f"No '{label}' column")


def months_of(year: int, today: pd.Timestamp) -> pd.PeriodIndex:
    """Jan through the current month of year (all 12 for a past year)."""
    last = 12 if year < today.year else today.month
    return pd.period_range(f"{year}-01", f"{year}-{last:02d}", freq="M")


def parse_expense_log(
    values: list[list], year: int, today: pd.Timestamp
) -> pd.DataFrame:
    """One row per Splitwise expense in year, up to today (Splitwise holds
    future-dated bills too, like a property tax due next month), with
    my_share = the "My Owed" column: your part of the bill whoever paid it."""
    header = values[0]
    columns = {
        "date": _column(header, "Date"),
        "description": _column(header, "Description"),
        "category": _column(header, "Category"),
        "my_share": _column(header, "My Owed"),
    }
    rows = [
        {
            "date": _to_date(_cell(row, columns["date"])),
            "description": str(_cell(row, columns["description"])).strip(),
            "category": str(_cell(row, columns["category"])).strip(),
            "my_share": _to_number(_cell(row, columns["my_share"])),
        }
        for row in values[1:]
    ]
    df = pd.DataFrame(rows, columns=list(columns))
    df = df.dropna(subset=["date"])
    df = df[(df["date"].dt.year == year) & (df["date"] <= today)]
    return df.sort_values("date").reset_index(drop=True)


def parse_expense_logs(
    workbook: dict[str, list[list]], year: int, today: pd.Timestamp
) -> pd.DataFrame:
    """Expense Log, plus the Partner Expense Log when the sheet has one with
    rows in it: each is its owner's share of every expense, so together
    they're the household's, a shared bill counted once."""
    logs = [
        parse_expense_log(workbook[tab], year, today)
        for tab in (EXPENSE_LOG_TAB, PARTNER_EXPENSE_LOG_TAB)
        if workbook.get(tab)
    ]
    expenses = pd.concat(logs) if len(logs) > 1 else logs[0]
    return expenses.sort_values("date", kind="stable").reset_index(drop=True)


def parse_category_budgets(values: list[list]) -> pd.DataFrame:
    """Monthly Expenses tab: each sub-category's group and monthly budget."""
    header_index = _find_row(values, "Sub-Category")
    header = values[header_index]
    group_col = _column(header, "Category")
    category_col = _column(header, "Sub-Category")
    budget_col = next(
        i for i, cell in enumerate(header) if str(cell).startswith("Monthly")
    )
    rows = []
    for row in values[header_index + 1 :]:
        group = str(_cell(row, group_col)).strip()
        if group.upper().startswith("TOTAL"):
            break
        category = str(_cell(row, category_col)).strip()
        if category:
            rows.append(
                {
                    "group": group or OTHER_GROUP,
                    "category": category,
                    "monthly_budget": _to_number(_cell(row, budget_col)),
                }
            )
    return pd.DataFrame(rows, columns=["group", "category", "monthly_budget"])


# Budget tab rows the Overview's income and savings tiles read, matched by
# their label (column A or B) in both the old sheet and the template
BUDGET_ITEMS = {
    "gross_income": "total gross income",
    "take_home": "take-home pay",
    "401k": "401k contribution",
    "401k_match": "401k company match",
    "total_savings": "total savings",
}


def parse_budget_items(values: list[list]) -> dict[str, tuple[float, float]]:
    """Budget tab: (Actual Yearly, Budget Yearly) for each BUDGET_ITEMS row
    found; a row the sheet doesn't have is left out."""
    header = values[_find_row(values, "Budget Yearly")]
    actual_col = _column(header, "Actual Yearly")
    budget_col = _column(header, "Budget Yearly")
    items = {}
    for row in values:
        labels = [str(_cell(row, i)).strip().lower() for i in (0, 1)]
        for key, label in BUDGET_ITEMS.items():
            if key not in items and any(label in text for text in labels):
                items[key] = (
                    _to_number(_cell(row, actual_col)),
                    _to_number(_cell(row, budget_col)),
                )
    return items


# Savings Log rows (label in column A, value in B) shown on the Overview
SAVINGS_LOG_ITEMS = {
    "dividends": "dividend",
    "interest": "interest",
    "stock_gain": "stock gain",
}


def parse_savings_log(values: list[list]) -> dict[str, float]:
    """Savings Log tab: each SAVINGS_LOG_ITEMS row's value, by the start of
    its label ("Dividends Received", "Interest", "Stock Gain/Loss")."""
    items = {}
    for row in values:
        label = str(_cell(row, 0)).strip().lower()
        for key, start in SAVINGS_LOG_ITEMS.items():
            if key not in items and label.startswith(start):
                items[key] = _to_number(_cell(row, 1))
    return items


def market_change(net_worth: pd.DataFrame, budget_items: dict) -> tuple[float, float]:
    """The year's net worth change less everything you put in: the logged
    contributions plus your 401(k) contributions and the company match,
    which the Net Worth tab's contribution rows don't include. Returned with
    its share of the net worth change, as the Dashboard tab's YTD Market
    Change and Market Change % show it."""
    change = net_worth[NET_WORTH].iloc[-1] - net_worth[NET_WORTH].iloc[0]
    put_in = net_worth[CONTRIBUTIONS].sum() + sum(
        budget_items.get(key, (0.0, 0.0))[0] for key in ("401k", "401k_match")
    )
    market = change - put_in
    return market, market / change if change else 0.0


def split_large(
    expenses: pd.DataFrame, threshold: float
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(everyday, one-offs): transactions whose share is at least threshold
    either way (a down payment, or a big purchase and its refund) would
    swamp every chart, so they're shown separately instead."""
    large = expenses["my_share"].abs() >= threshold
    return expenses[~large], expenses[large]


def with_groups(expenses: pd.DataFrame, budgets: pd.DataFrame) -> pd.DataFrame:
    """Adds each expense's category group and month."""
    groups = dict(zip(budgets["category"], budgets["group"]))
    return expenses.assign(
        group=expenses["category"].map(groups).fillna(OTHER_GROUP),
        month=expenses["date"].dt.to_period("M"),
    )


def monthly_by_group(
    expenses: pd.DataFrame, budgets: pd.DataFrame, months: pd.PeriodIndex
) -> pd.DataFrame:
    """Month x category group of your share, every month present (0 if
    nothing was spent), groups in the Monthly Expenses tab's order."""
    grouped = with_groups(expenses, budgets)
    table = grouped.pivot_table(
        index="month", columns="group", values="my_share", aggfunc="sum"
    )
    order = list(dict.fromkeys(budgets["group"])) + [OTHER_GROUP]
    columns = [g for g in order if g in table.columns]
    return table.reindex(index=months, columns=columns).fillna(0.0)


def monthly_by_category(
    expenses: pd.DataFrame,
    budgets: pd.DataFrame,
    months: pd.PeriodIndex,
    group: str,
    max_categories: int = 8,
) -> pd.DataFrame:
    """Month x sub-category of your share within one category group, every
    month present, sub-categories by the year's spending (largest first).
    Beyond max_categories the smallest are summed into Other, so the
    columns always add up to the group's monthly_by_group() column."""
    grouped = with_groups(expenses, budgets)
    grouped = grouped[grouped["group"] == group]
    table = (
        grouped.pivot_table(
            index="month", columns="category", values="my_share", aggfunc="sum"
        )
        .reindex(index=months)
        .fillna(0.0)
    )
    order = table.sum().sort_values(ascending=False).index
    table = table[order]
    if len(order) > max_categories:
        keep = order[: max_categories - 1]
        table = table[keep].assign(Other=table[order[max_categories - 1 :]].sum(axis=1))
    return table


def budget_vs_actual(
    expenses: pd.DataFrame, budgets: pd.DataFrame, today: pd.Timestamp, year: int
) -> pd.DataFrame:
    """Each sub-category's spending so far this year against its budget for
    the same stretch (the current month prorated by day), most over budget
    first. Only categories with a budget or some spending are listed."""
    if year < today.year:
        elapsed = 12.0
    else:
        days = calendar.monthrange(today.year, today.month)[1]
        elapsed = today.month - 1 + today.day / days
    actual = expenses.groupby("category")["my_share"].sum()
    table = budgets.set_index("category")[["group", "monthly_budget"]].copy()
    for category in actual.index.difference(table.index):
        table.loc[category] = [OTHER_GROUP, 0.0]
    table["actual"] = actual.reindex(table.index).fillna(0.0)
    table["budget"] = table["monthly_budget"] * elapsed
    table["annual"] = table["monthly_budget"] * 12
    table["over"] = table["actual"] - table["budget"]
    table = table[(table["budget"] != 0) | (table["actual"] != 0)]
    return (
        table.drop(columns="monthly_budget")
        .reset_index(names="category")
        .sort_values("over", ascending=False)
        .reset_index(drop=True)
    )


def top_merchants(expenses: pd.DataFrame, n: int = 10) -> pd.DataFrame:
    """Biggest descriptions by your share, case and spacing ignored."""
    key = expenses["description"].str.lower().str.split().str.join(" ")
    table = (
        expenses.assign(key=key)
        .groupby("key")
        .agg(
            description=("description", "first"),
            total=("my_share", "sum"),
            count=("my_share", "size"),
        )
        .sort_values("total", ascending=False)
    )
    return table.head(n).reset_index(drop=True)


def _net_worth_months(values: list[list], months: pd.PeriodIndex):
    """The Net Worth tab's month header row, and a function reading a row's
    value for each of the months given."""
    header_index = next(
        i
        for i, row in enumerate(values)
        if "Jan" in [str(c).strip() for c in row]
        and "Dec" in [str(c).strip() for c in row]
    )
    header = [str(c).strip() for c in values[header_index]]
    columns = {
        month: header.index(calendar.month_abbr[month.month]) for month in months
    }

    def series(row):
        return [_to_number(_cell(row, columns[month])) for month in months]

    return header_index, series


def parse_net_worth(values: list[list], months: pd.PeriodIndex) -> pd.DataFrame:
    """Net Worth tab: per month, each component's subtotal, the net worth
    total and the contributions logged at the bottom, for the months given
    (the current month is still live; later ones just repeat it)."""
    header_index, series = _net_worth_months(values, months)

    data, contributions = {}, [0.0] * len(months)
    in_contributions = False
    for row in values[header_index + 1 :]:
        label = str(_cell(row, 0)).strip().lower()
        if "contribution" in label:
            in_contributions = True
            continue
        if in_contributions:
            # Only the per-account rows (label in column B), not the
            # "Total Contributed" and "Market Gains" rows under them
            if not label and str(_cell(row, 1)).strip():
                contributions = [a + b for a, b in zip(contributions, series(row))]
        elif label.startswith("subtotal"):
            for keyword, component in NET_WORTH_COMPONENTS.items():
                if keyword in label:
                    data[component] = series(row)
        elif label.startswith("net worth"):
            data[NET_WORTH] = series(row)
    missing = [c for c in [*NET_WORTH_COMPONENTS.values(), NET_WORTH] if c not in data]
    if missing:
        raise ValueError(f"Net Worth tab has no row for {', '.join(missing)}")
    order = [*NET_WORTH_COMPONENTS.values(), NET_WORTH]
    df = pd.DataFrame({c: data[c] for c in order}, index=months)
    df[CONTRIBUTIONS] = contributions
    return df


def net_worth_changes(net_worth: pd.DataFrame) -> pd.DataFrame:
    """Each month's change in net worth (from the second month on, since the
    first is the opening balance), split into what you put in (the
    contributions logged that month) and everything else (markets, home
    value, paying down debt)."""
    change = net_worth[NET_WORTH].diff().iloc[1:]
    saved = net_worth[CONTRIBUTIONS].iloc[1:]
    return pd.DataFrame({"change": change, "saved": saved, "market": change - saved})


def contribution_buckets(
    values: list[list], months: pd.PeriodIndex, max_buckets: int = 8
) -> pd.DataFrame:
    """Where each month's savings went: one column per contribution row on the
    Net Worth tab (label in column B, named like an account row, e.g.
    "Brokerage · Stocks"), indexed by month. Rows that are $0 in every month
    are dropped; past max_buckets, the smallest (by total) are summed into
    "Other". A repeated label gets a " (2)" suffix."""
    header_index, series = _net_worth_months(values, months)
    buckets, in_contributions = {}, False
    for row in values[header_index + 1 :]:
        label = str(_cell(row, 0)).strip().lower()
        if "contribution" in label and not label.startswith("total"):
            in_contributions = True
            continue
        if not in_contributions:
            continue
        # Only the per-bucket rows (label in column B), not the "Total
        # Contributed" and "Market Gains" rows under them
        if not label and str(_cell(row, 1)).strip():
            base = _account_label(row)
            name, n = base, 2
            while name in buckets:
                name, n = f"{base} ({n})", n + 1
            buckets[name] = series(row)
    df = pd.DataFrame(buckets, index=months, dtype=float)
    df = df.loc[:, (df != 0).any()]
    if len(df.columns) > max_buckets:
        order = df.abs().sum().sort_values(ascending=False).index
        keep, rest = order[: max_buckets - 1], order[max_buckets - 1 :]
        df = df[keep].assign(Other=df[rest].sum(axis=1))
    return df


# Accounts that don't add up to their subtotal (e.g. a row the subtotal
# formula leaves out or subtracts) show up as this, so each category's
# breakdown always sums to the subtotal charted above it
UNLISTED = "Not itemized"


def _net_worth_sections(values: list[list], months: pd.PeriodIndex):
    """The Net Worth tab's sections as (component, {account: row},
    subtotal row), with the month header row and its series() reader.
    Account rows have their label in column B; a repeated label within a
    section gets a " (2)" suffix."""
    header_index, series = _net_worth_months(values, months)
    sections, pending = [], {}
    for row in values[header_index + 1 :]:
        label = str(_cell(row, 0)).strip().lower()
        account = str(_cell(row, 1)).strip()
        if "contribution" in label or label.startswith("net worth"):
            break
        if label.startswith("subtotal"):
            component = next(
                (c for k, c in NET_WORTH_COMPONENTS.items() if k in label), None
            )
            if component:
                sections.append((component, pending, row))
            pending = {}
        elif not label and account:
            base = _account_label(row)
            name, n = base, 2
            while name in pending:
                name, n = f"{base} ({n})", n + 1
            pending[name] = row
    return values[header_index], _signed(series), sections


# Account rows that are debts. Some sheets keep these positive and subtract
# them in the subtotal formula (Real Estate's "Mortgage Balance"), so they
# always count as negative here
_DEBT_WORDS = ("liabilit", "mortgage", "loan", "debt", "credit card")


def _account_label(row: list) -> str:
    """A Net Worth account row's name: its institution (column D), account
    (B) and type (C), skipping blanks and repeats - "Wells Fargo · Savings ·
    Joint" - since column B alone is often generic ("Savings")."""
    parts = []
    for index in (3, 1, 2):
        text = " ".join(str(_cell(row, index)).split())
        if text and text.lower() not in [p.lower() for p in parts]:
            parts.append(text)
    return " · ".join(parts)


def _signed(series):
    """series() with debt rows (by their account or type label) negative."""

    def read(row):
        values = series(row)
        text = f"{_cell(row, 1)} {_cell(row, 2)}".lower()
        if any(word in text for word in _DEBT_WORDS):
            return [-abs(v) for v in values]
        return values

    return read


def net_worth_breakdown(
    values: list[list], months: pd.PeriodIndex, max_accounts: int = 7
) -> dict[str, pd.DataFrame]:
    """Net Worth tab, per component: one column per account row (label in
    column B) above that component's subtotal, indexed by month. Accounts
    that are $0 every month are dropped; past max_accounts, the smallest
    (by latest balance) are summed into "Other". Any gap between the
    accounts and the subtotal is an extra "Not itemized" column."""
    _, series, sections = _net_worth_sections(values, months)
    breakdown = {
        component: _component_breakdown(
            {name: series(row) for name, row in rows.items()},
            series(subtotal),
            months,
            max_accounts,
        )
        for component, rows, subtotal in sections
    }
    return {
        c: breakdown.get(c, pd.DataFrame(index=months))
        for c in NET_WORTH_COMPONENTS.values()
    }


def _component_breakdown(
    accounts: dict, subtotal: list, months: pd.PeriodIndex, max_accounts: int
) -> pd.DataFrame:
    df = pd.DataFrame(accounts, index=months, dtype=float)
    df = df.loc[:, (df != 0).any()]
    if len(df.columns) > max_accounts:
        order = df.iloc[-1].abs().sort_values(ascending=False).index
        keep, rest = order[: max_accounts - 1], order[max_accounts - 1 :]
        df = df[keep].assign(Other=df[rest].sum(axis=1))
    gap = pd.Series(subtotal, index=months) - df.sum(axis=1)
    if (gap.abs() >= 0.5).any():
        df[UNLISTED] = gap
    return df


# ── Holdings drill-down ─────────────────────────────────────────────────────

# What's left of an account's balance after its holdings (uninvested cash,
# or anything SimpleFIN doesn't itemize)
CASH_AND_OTHER = "Cash & other"
# An account no holdings are reported for (a bank account, the house)
BALANCE_ONLY = "Balance (no holdings reported)"


def load_holdings() -> pd.DataFrame:
    """The SimpleFIN pipeline's holdings_dump tab (one row per security per
    account), from the RH_Sheets spreadsheet."""
    return read_from_sheets(HOLDINGS_DUMP_SHEET_NAME)


def net_worth_accounts(values: list[list], months: pd.PeriodIndex) -> pd.DataFrame:
    """Every account row on the Net Worth tab with a balance this year:
    Category, Account (named as in net_worth_breakdown), Institution
    (column D), Type (column C), Key, Share and its latest Balance. Key and
    Share come from the template's Balance Key and My Share % columns; a
    sheet without them has no key and a 100% share."""
    header, series, sections = _net_worth_sections(values, months)
    labels = [str(c).strip().lower() for c in header]

    def column(name):
        return labels.index(name) if name in labels else None

    key_col, share_col = column("balance key"), column("my share %")
    records = []
    for component, rows, _ in sections:
        for name, row in rows.items():
            balances = series(row)
            if not any(balances):
                continue
            share = _to_number(_cell(row, share_col)) if share_col is not None else 0
            records.append(
                {
                    "Category": component,
                    "Account": name,
                    "Institution": " ".join(str(_cell(row, 3)).split()),
                    "Type": " ".join(str(_cell(row, 2)).split()),
                    "Key": (
                        str(_cell(row, key_col)).strip() if key_col is not None else ""
                    ),
                    "Share": share or 1.0,
                    "Balance": balances[-1],
                }
            )
    return pd.DataFrame(
        records,
        columns=[
            "Category", "Account", "Institution", "Type", "Key", "Share", "Balance",
        ],
    )  # fmt: skip


# Without a Balance Key, only these categories' rows are matched to
# holdings, so a brokerage's uninvested-cash row under Cash & Savings
# doesn't pick up its securities
INVESTED = ("Investments", "Retirement")


def _norm(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _key_matches(institution: str, name: str, key: str) -> bool:
    """The template's Balance Key rule: the key is part of the SimpleFIN
    institution and account name, or a 4-digit account number in the key
    is, so "Joint (1111)" still finds "Joint 3.30% APY (1111)"."""
    text = f"{institution} {name}".lower()
    return key.lower() in text or any(d in text for d in re.findall(r"\d{4}", key))


def holdings_accounts(accounts: pd.DataFrame, holdings: pd.DataFrame) -> dict:
    """Which SimpleFIN holdings accounts, as (Institution, Account Name)
    pairs, make up each Net Worth account row (by index). A row with a
    Balance Key takes every account the key matches. A keyless Investments
    or Retirement row matches by institution: first the accounts whose name
    contains its type ("Roth IRA", "401k" for "401(k)", "Crypto"), then, if
    it's the only row left for that institution, whatever accounts are left
    (Wells Fargo "Stocks" -> WELLSTRADE)."""
    result = {i: [] for i in accounts.index}
    if holdings.empty:
        return result
    pairs = list(
        holdings[["Institution", "Account Name"]]
        .astype(str)
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    claimed = set()
    for i, account in accounts.iterrows():
        if account["Key"]:
            result[i] = [p for p in pairs if _key_matches(*p, account["Key"])]
            claimed.update(result[i])
    candidates = {
        i: [
            p
            for p in pairs
            if p not in claimed
            and _norm(account["Institution"])
            and (
                _norm(account["Institution"]) in _norm(p[0])
                or _norm(p[0]) in _norm(account["Institution"])
            )
        ]
        for i, account in accounts.iterrows()
        if not account["Key"] and account["Category"] in INVESTED
    }
    unresolved = []
    for i, pool in candidates.items():
        kind = _norm(accounts.at[i, "Type"])
        typed = [p for p in pool if kind and kind in _norm(p[1])]
        if typed:
            result[i] = typed
            claimed.update(typed)
        elif pool:
            unresolved.append(i)
    for i in unresolved:
        rest = [p for p in candidates[i] if p not in claimed]
        rivals = [j for j in unresolved if j != i and set(rest) & set(candidates[j])]
        if rest and not rivals:
            result[i] = rest
    return result


def account_holdings(
    holdings: pd.DataFrame, account: pd.Series, sources: list
) -> pd.DataFrame:
    """One Net Worth account's row-level assets: Symbol, Description,
    Shares and Value (your share of the market value) of the holdings in
    its source accounts (from holdings_accounts), largest first, plus a
    "Cash & other" row for whatever of the account's balance its holdings
    don't cover (none when they're worth more than it, which is just
    prices moving between the sheet and SimpleFIN).
    An account with no holdings (a bank account, the house) is a single row
    for its whole balance."""
    records = []
    if sources:
        names = list(
            zip(
                holdings["Institution"].astype(str),
                holdings["Account Name"].astype(str),
            )
        )
        matched = holdings[[n in sources for n in names]]
        # One row per security: a 401(k) lists a fund once per money source
        # (pre-tax, Roth, match)
        merged = (
            pd.DataFrame(
                {
                    "Symbol": matched["Symbol"].astype(str),
                    "Description": matched["Description"].astype(str),
                    "Shares": matched["Shares"].map(_to_number),
                    "Value": matched["Market Value"].map(_to_number),
                }
            )
            .groupby(["Symbol", "Description"], as_index=False, sort=False)
            .sum()
        )
        for h in merged.itertuples():
            value = h.Value * account["Share"]
            if abs(value) >= 0.5:
                records.append(
                    {
                        "Account": account["Account"],
                        "Symbol": h.Symbol,
                        "Description": h.Description,
                        "Shares": h.Shares * account["Share"],
                        "Value": value,
                    }
                )
    rest = account["Balance"] - sum(r["Value"] for r in records)
    # Holdings worth more than the row's balance is just prices moving
    # between the sheet and SimpleFIN, not a position, so there's no row for it
    if not records or rest >= 1:
        label = CASH_AND_OTHER if records else BALANCE_ONLY
        records.append(
            {
                "Account": account["Account"],
                "Symbol": "",
                "Description": label,
                "Shares": None,
                "Value": rest,
            }
        )
    df = pd.DataFrame(records)
    return df.sort_values("Value", key=abs, ascending=False).reset_index(drop=True)


def category_holdings(
    holdings: pd.DataFrame, accounts: pd.DataFrame, category: str
) -> pd.DataFrame:
    """account_holdings for every account in a Net Worth category, with
    each row's share of the category total (blank when the category mixes
    assets and debts, like a house and its mortgage, where shares of the
    net total mean nothing)."""
    sources = holdings_accounts(accounts, holdings)
    parts = [
        account_holdings(holdings, account, sources[i])
        for i, account in accounts[accounts["Category"] == category].iterrows()
    ]
    if not parts:
        return pd.DataFrame(
            columns=["Account", "Symbol", "Description", "Shares", "Value", "Weight"]
        )
    df = pd.concat(parts, ignore_index=True)
    total = df["Value"].sum()
    mixed = (df["Value"] > 0).any() and (df["Value"] < 0).any()
    df["Weight"] = df["Value"] / total if total and not mixed else float("nan")
    return df.sort_values("Value", key=abs, ascending=False).reset_index(drop=True)


# ── Allocation ──────────────────────────────────────────────────────────────

# The categories weighed against each other: everything you own, net of the
# mortgage inside Real Estate, but not the card and loan balances in
# Liabilities, which aren't a slice of what you hold
ASSET_COMPONENTS = [c for c in NET_WORTH_COMPONENTS.values() if c != "Liabilities"]


def _weights(values: pd.Series) -> pd.Series:
    """Each value's share of their total, or blank (NaN) when they mix
    assets and debts (a house and its mortgage), where shares of the net
    total mean nothing."""
    total = values.sum()
    if not total or ((values > 0).any() and (values < 0).any()):
        return pd.Series(float("nan"), index=values.index)
    return values / total


def account_types(accounts: pd.DataFrame) -> pd.Series:
    """Each net_worth_accounts() row's type for grouping: its Type column
    (Stocks, ETF, 401k...), or its account name when that's blank. Within a
    category, spellings that differ only in case or spacing share the first
    one's name, so "ETF" and " etf" are one type."""
    kind = accounts["Type"].where(
        accounts["Type"].str.strip() != "", accounts["Account"]
    )
    kind = kind.str.strip()
    key = accounts["Category"] + "\0" + kind.str.lower()
    return kind.groupby(key).transform("first")


def category_summary(net_worth: pd.DataFrame) -> pd.DataFrame:
    """One row per net worth category (Liabilities included): its latest
    value, its share of the asset categories' total (blank for Liabilities,
    or for everything if the assets mix signs) and its change since the first
    month."""
    latest, first = net_worth.iloc[-1], net_worth.iloc[0]
    categories = list(NET_WORTH_COMPONENTS.values())
    summary = pd.DataFrame(
        {
            "category": categories,
            "value": [latest[c] for c in categories],
            "change": [latest[c] - first[c] for c in categories],
        }
    )
    assets = summary["category"].isin(ASSET_COMPONENTS)
    summary["weight"] = float("nan")
    summary.loc[assets, "weight"] = _weights(summary.loc[assets, "value"])
    return summary


def allocation(
    accounts: pd.DataFrame, net_worth: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The latest month's allocation at two levels. By category: each asset
    category's subtotal (ASSET_COMPONENTS) and its share of their total. By
    type: within each category, its account rows grouped by their Type
    column (Stocks, ETF, Crypto, Foreign, 401k...; the account's name when
    the type is blank), with the type's share of its category and of all
    assets. Any gap between a category's rows and its subtotal is a "Not
    itemized" type, so the types add up to the category."""
    latest = net_worth.iloc[-1]
    by_category = pd.DataFrame(
        {"category": ASSET_COMPONENTS, "value": [latest[c] for c in ASSET_COMPONENTS]}
    )
    by_category = by_category[by_category["value"].abs() >= 0.5]
    by_category["weight"] = _weights(by_category["value"])
    total = by_category["value"].sum()

    kinds = account_types(accounts)
    parts = []
    for category in by_category["category"]:
        rows = accounts[accounts["Category"] == category]
        types = rows["Balance"].groupby(kinds[rows.index], sort=False).sum()
        gap = latest[category] - types.sum()
        if abs(gap) >= 0.5:
            types[UNLISTED] = gap
        types = types[types.abs() >= 0.5].sort_values(key=abs, ascending=False)
        parts.append(
            pd.DataFrame(
                {
                    "category": category,
                    "type": types.index,
                    "value": types.values,
                    "weight": _weights(types).values,
                    "of_assets": types.values / total if total else float("nan"),
                }
            )
        )
    by_type = (
        pd.concat(parts, ignore_index=True)
        if parts
        else pd.DataFrame(columns=["category", "type", "value", "weight", "of_assets"])
    )
    return by_category.reset_index(drop=True), by_type
