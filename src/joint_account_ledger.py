"""
Tracks each spouse's share of two joint SimpleFIN-linked accounts at the
transaction level, so the combined balance isn't just attributed entirely to
whoever happened to fund the account first.

Every transaction is auto-classified from its SimpleFIN description:
  - "Mine": a transfer to/from an account you solely own (see
    _PERSONAL_ACCOUNT_DESCRIPTION_MATCHERS below).
  - "Joint Internal": a transfer between the two tracked joint accounts
    themselves - not new money, so it must not be double-counted as a
    contribution on the receiving leg.
  - "Mortgage": an extra principal payment to the mortgage, always made
    with your money (see _MORTGAGE_DESCRIPTION_MATCHERS below) - counts like
    "Mine", and is also totalled separately so the Net Worth tab can credit
    you for the full payment rather than your ownership share of it.
  - "Mortgage Payment": the regular monthly mortgage autopay, split like the
    house - MORTGAGE_PAYMENT_MY_SHARE_PERCENT of it comes out of your totals,
    and it isn't extra principal.
  - "Interest": bank-paid interest, split 50/50.
  - "Spouse": your spouse's payroll deposits and transfers from their accounts
    (see _SPOUSE_DESCRIPTION_MATCHERS below) - counted as $0 toward your
    totals.
  - "Shared": a recurring bill you split 50/50, paid from a joint account
    (see _SHARED_BILL_DESCRIPTION_PREFIXES below) - half of it comes out of
    your totals.
  - "Unclassified": anything else (e.g. your spouse's future contributions,
    from an account not yet in the matcher list, or a one-off wire this
    rule set was never meant to guess about) - excluded from your totals by
    default, but left visible in the sheet so you can type an override.

The "Override Classification" column is the only thing preserved across
runs; everything else is recomputed fresh each time so the matcher lists
above can be edited without needing to backfill old rows by hand. It also
accepts a plain number (e.g. "60") instead of a classification label, for a
one-off transaction that should count as a partial share rather than
entirely yours or entirely excluded (e.g. a jointly-owed expense split
60/40) - the sheet's My Contribution formula treats a numeric override as
"you own this % of the transaction amount".

A row of summary figures sits at the top of the tab, above the
transactions table. For each bill, columns L-P show what part of their share their balance in the
accounts covered and what's left for them to owe you (record that in
Splitwise); see build_balance_columns_df().

The accounts, matchers, start date and mortgage split come from the
household config (src/household_config.py), since they identify you.

Only transactions on or after LEDGER_START_DATE are tracked (see that
constant below for why) - both accounts' balances as of that date are
captured with a one-time manual SEED row rather than reconstructed from
transaction history.
"""

import logging
import os
import re
from datetime import date, datetime, timezone

import pandas as pd

from src.constants.gsheets import (
    JOINT_ACCOUNT_LEDGER_SHEET_NAME,
    PORTFOLIO_TAB_SUFFIX_ENV_VAR,
    SIMPLEFIN_ACCESS_URL_ENV_VAR,
)
from src.external_services.google_sheets import (
    read_from_sheets,
    write_cell_to_sheets,
    write_to_sheets,
)
from src.external_services.simplefin import get_transactions
from src import household_config

logger = logging.getLogger(__name__)

# Everything identifying - account ids and digits, payee names, the start
# date and the mortgage split - comes from the household config (see
# src/household_config.py and config/household.example.json for the keys).
_CONFIG = household_config.load().get("joint_ledger", {})


def _matchers(key: str) -> tuple[str, ...]:
    return tuple(str(m).upper() for m in _CONFIG.get(key, []))


# The joint accounts this ledger tracks: SimpleFIN account id -> the name
# written in the Account column.
JOINT_ACCOUNT_IDS: dict[str, str] = dict(_CONFIG.get("accounts", {}))

# Transfers between the tracked joint accounts - not external money, so not
# a contribution on either leg. Matchers are bare account-number digits
# rather than a masked form ("XXXXXX1234" or "****1234"), since institutions
# mask differently in their transaction descriptions, or an institution name.
_JOINT_ACCOUNT_DESCRIPTION_MATCHERS = _matchers("joint_account_matchers")

# Accounts solely owned by you that feed the joint accounts ("Mine").
_PERSONAL_ACCOUNT_DESCRIPTION_MATCHERS = _matchers("personal_account_matchers")

# Payroll direct deposits split straight into a joint account, matched on
# the employer name. Yours count as "Mine". Your spouse's, and transfers from
# their accounts, are "Spouse": $0 toward your totals like "Unclassified",
# but not in the needs-review total.
_MY_PAYROLL_DESCRIPTION_MATCHERS = _matchers("my_payroll_matchers")
_SPOUSE_DESCRIPTION_MATCHERS = _matchers("spouse_matchers")

# Extra principal payments to the mortgage made from a joint account are paid
# with your money, so they come out of your share ("Mortgage", which the
# sheet counts like "Mine", on a negative amount). Matched on the loan's
# digits or wording like "MORTGAGE". Checked before interest, so a
# description like "PRINCIPAL AND INTEREST" isn't split 50/50.
_MORTGAGE_DESCRIPTION_MATCHERS = _matchers("mortgage_matchers")
# The regular monthly payment is an autopay, split like the house ("Mortgage
# Payment", your share being MORTGAGE_PAYMENT_MY_SHARE_PERCENT), so only the
# other mortgage payments are extra principal. Matched on the autopay
# wording rather than the amount, which changes whenever escrow does.
_MORTGAGE_AUTOPAY_DESCRIPTION_MATCHERS = _matchers("mortgage_autopay_matchers")
MORTGAGE_PAYMENT_MY_SHARE_PERCENT = _CONFIG.get("mortgage_payment_my_share_percent", 50)

# Recurring bills split 50/50, matched on the start of the description since
# a short payee name would otherwise match inside other words. Checked
# before interest, so a payee with "interest" in its name isn't mistaken for
# interest earned.
_SHARED_BILL_DESCRIPTION_PREFIXES = _matchers("shared_bill_prefixes")

_INTEREST_DESCRIPTION_PATTERN = re.compile(r"interest", re.IGNORECASE)

# Everything before this date is deliberately out of scope: both accounts
# had been funded solely by you up to this point, so rather than rely on
# SimpleFIN's limited transaction retention (roughly the last couple months)
# to reconstruct that history, each account's balance as of this date is
# captured once with a manual SEED-* row (Transaction ID not starting with
# "TRN-", Override Classification "Mine") added directly to the sheet.
# Existing rows dated earlier are dropped on every run, and transactions are
# only fetched from this date forward, so moving it later means re-seeding.
LEDGER_START_DATE = date.fromisoformat(_CONFIG.get("start_date", "2000-01-01"))

_OUTPUT_COLUMNS = [
    "Transaction ID",
    "Date",
    "Account",
    "Description",
    "Amount",
    "Suggested Classification",
    "Override Classification",
    "Effective Classification",
    "My Contribution",
    "Interest (Total)",
    "My Interest Share",
]

# Layout, like the Stocks tab: a row of summary figures at the top (labels
# in row 2, values in row 3), then the transactions table, its header in
# HEADER_ROW. The Budget sheet's Net Worth tab reads the table from
# FIRST_ROW down (joint_account_ledger!C6:K and B6:H), so moving it means
# updating those formulas too.
HEADER_ROW = 5
FIRST_ROW = HEADER_ROW + 1
_SUMMARY_LABEL_ROW = 2

# (label, formula) per summary figure, left to right from column A
_SUMMARY = [
    ("Joint Balance Total", f"=SUM(E{FIRST_ROW}:E)"),
    (
        "My Current Balance (Contributions + Interest)",
        f"=SUM(I{FIRST_ROW}:I)+SUM(K{FIRST_ROW}:K)",
    ),
    # What's theirs in the joint accounts now: their money in, less the part of
    # each bill their balance covered. Never negative, since a bill their
    # balance can't cover goes to Splitwise instead.
    ("Spouse Current Balance", f"=SUM(L{FIRST_ROW}:L)+SUM(P{FIRST_ROW}:P)"),
    # The part of their share of bills their balance didn't cover, which your
    # money paid: what to record in Splitwise as owed by them (column P has
    # it per bill). Your balance in the accounts is My Current Balance
    # minus this.
    ("Owed by Spouse (record in Splitwise)", f"=SUM(P{FIRST_ROW}:P)"),
    ("My Contributions Total", f"=SUM(I{FIRST_ROW}:I)"),
    ("My Interest Share Total", f"=SUM(K{FIRST_ROW}:K)"),
    # Payments are negative amounts, so negate to report principal paid as a
    # positive figure.
    (
        "My Extra Mortgage Principal Paid",
        f'=-SUMIF(H{FIRST_ROW}:H,"Mortgage",E{FIRST_ROW}:E)',
    ),
    (
        "Unclassified $ Needing Review",
        f'=SUMIF(H{FIRST_ROW}:H,"Unclassified",E{FIRST_ROW}:E)',
    ),
]


def summary_cells() -> dict[str, str]:
    """The summary row's cells: each label above its formula."""
    cells = {}
    for col, (label, formula) in enumerate(_SUMMARY):
        letter = chr(ord("A") + col)
        cells[f"{letter}{_SUMMARY_LABEL_ROW}"] = label
        cells[f"{letter}{_SUMMARY_LABEL_ROW + 1}"] = formula
    return cells


# Per-row balance columns, written at column L right after the A-K table
_BALANCE_COLUMNS_START = (HEADER_ROW, 12)
_BALANCE_COLUMNS = [
    "Spouse Share",
    "My Running Balance",
    "Spouse Running Balance",
    "Spouse Share Covered",
    "Owed by Spouse (Splitwise)",
]


def classify_transaction(description: str) -> str:
    """Suggests a classification for a transaction from its SimpleFIN
    description. Mortgage, shared bills and interest are checked first since
    they're unambiguous matches; everything else defaults to "Unclassified"
    rather than guessing, so an account or wire this rule set doesn't
    recognize surfaces for manual review instead of silently going the wrong
    way."""
    description = description or ""
    upper_description = description.upper()
    if any(m in upper_description for m in _MORTGAGE_DESCRIPTION_MATCHERS):
        if any(m in upper_description for m in _MORTGAGE_AUTOPAY_DESCRIPTION_MATCHERS):
            return "Mortgage Payment"
        return "Mortgage"
    if upper_description.startswith(_SHARED_BILL_DESCRIPTION_PREFIXES):
        return "Shared"
    if _INTEREST_DESCRIPTION_PATTERN.search(description):
        return "Interest"

    if any(m in upper_description for m in _JOINT_ACCOUNT_DESCRIPTION_MATCHERS):
        return "Joint Internal"
    if any(
        m in upper_description
        for m in _PERSONAL_ACCOUNT_DESCRIPTION_MATCHERS + _MY_PAYROLL_DESCRIPTION_MATCHERS
    ):
        return "Mine"
    if any(m in upper_description for m in _SPOUSE_DESCRIPTION_MATCHERS):
        return "Spouse"
    return "Unclassified"


def _transaction_fetch_start_timestamp() -> int:
    """The SEED-* rows for LEDGER_START_DATE capture each account's balance
    as of the end of that day, so transactions are only fetched starting
    the day after - fetching LEDGER_START_DATE itself risks double-counting
    a same-day transaction that's already baked into the seeded balance."""
    day_after_start = date.fromordinal(LEDGER_START_DATE.toordinal() + 1)
    return int(
        datetime.combine(day_after_start, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    )


def get_new_transactions_as_df(access_url: str) -> pd.DataFrame:
    """Fetches every transaction after LEDGER_START_DATE for the tracked
    joint accounts and returns them as a DataFrame with a freshly computed
    Suggested Classification. "New" refers to the fetch window, not dedup
    against the sheet - dedup against already-recorded transactions happens
    in build_ledger_df, keyed by Transaction ID."""
    transactions = get_transactions(
        access_url,
        account_ids=list(JOINT_ACCOUNT_IDS),
        start_date=_transaction_fetch_start_timestamp(),
    )

    rows = [
        {
            "Transaction ID": txn["id"],
            "Date": pd.to_datetime(int(txn["posted"]), unit="s", utc=True).date(),
            "Account": txn.get("account_name", ""),
            "Description": txn.get("description", ""),
            "Amount": float(txn["amount"]),
            "Suggested Classification": classify_transaction(txn.get("description", "")),
        }
        for txn in transactions
    ]
    return pd.DataFrame(
        rows,
        columns=_OUTPUT_COLUMNS[:6],
    )


def build_ledger_df(fetched_df: pd.DataFrame, existing_df: pd.DataFrame) -> pd.DataFrame:
    """Merges freshly fetched transactions with whatever's already in the
    sheet. Override Classification is the only column preserved verbatim
    from existing rows - everything else (including Suggested
    Classification) is recomputed from the stored Description so edits to
    the matcher lists apply retroactively without a manual backfill.
    Formula columns (Effective Classification, My Contribution, Interest
    (Total), My Interest Share) are (re)injected for every row so they stay
    live in Sheets rather than freezing at whatever value was last read."""
    if not existing_df.empty and "Transaction ID" in existing_df.columns:
        in_scope_df = existing_df[
            pd.to_datetime(existing_df["Date"]).dt.date >= LEDGER_START_DATE
        ]
    else:
        in_scope_df = pd.DataFrame()

    overrides = {}
    if not in_scope_df.empty:
        overrides = dict(
            zip(
                in_scope_df["Transaction ID"],
                in_scope_df.get("Override Classification", ""),
            )
        )

    known_ids = set(overrides)
    base_rows = [
        {
            "Transaction ID": row["Transaction ID"],
            "Date": row["Date"],
            "Account": row["Account"],
            "Description": row["Description"],
            "Amount": float(row["Amount"]),
            "Suggested Classification": classify_transaction(row["Description"]),
        }
        for _, row in in_scope_df.iterrows()
    ]

    new_rows_df = fetched_df[~fetched_df["Transaction ID"].isin(known_ids)]
    frames = [df for df in (pd.DataFrame(base_rows, columns=_OUTPUT_COLUMNS[:6]), new_rows_df) if not df.empty]
    merged = pd.concat(frames) if frames else pd.DataFrame(columns=_OUTPUT_COLUMNS[:6])
    merged["Date"] = pd.to_datetime(merged["Date"])
    merged = merged.sort_values(by="Date").reset_index(drop=True)
    merged["Date"] = merged["Date"].dt.date

    if merged.empty:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    merged["Override Classification"] = merged["Transaction ID"].map(overrides).fillna("")

    for i in range(len(merged)):
        row_idx = i + FIRST_ROW
        merged.at[i, "Effective Classification"] = f'=IF(G{row_idx}<>"",G{row_idx},F{row_idx})'
        # A numeric Effective Classification (e.g. 60) is a partial-share
        # override - "you own this % of the amount" - for a one-off
        # transaction like a jointly-owed expense split, rather than the
        # all-or-nothing "Mine"/excluded default.
        merged.at[i, "My Contribution"] = (
            f'=IF(ISNUMBER(H{row_idx}),E{row_idx}*H{row_idx}/100,'
            f'IF(OR(H{row_idx}="Mine",H{row_idx}="Mortgage"),E{row_idx},'
            f'IF(H{row_idx}="Shared",E{row_idx}*0.5,'
            f'IF(H{row_idx}="Mortgage Payment",'
            f'E{row_idx}*{MORTGAGE_PAYMENT_MY_SHARE_PERCENT}/100,0))))'
        )
        merged.at[i, "Interest (Total)"] = f'=IF(H{row_idx}="Interest",E{row_idx},0)'
        merged.at[i, "My Interest Share"] = f"=J{row_idx}*0.5"

    return merged[_OUTPUT_COLUMNS]


def build_balance_columns_df(row_count: int) -> pd.DataFrame:
    """Formulas for each ledger row's Spouse Share, both spouses' running
    balances, and how a bill's share of theirs was paid (columns L-P).

    Spouse Share is whatever part of the amount isn't yours (My Contribution)
    or your half of interest. Unclassified rows count for neither of you
    until they're overridden; they're totalled under Unclassified $ Needing
    Review instead.

    Their running balance never goes below zero: when their share of a bill is
    more than they have in the accounts, their balance covers what it can
    (Spouse Share Covered) and the rest, which your money paid, is Owed by
    Spouse - the amount to record in Splitwise. Once it's there, it's a
    debt in Splitwise rather than a negative balance here, so their next
    deposits stay theirs instead of quietly paying it back a second time.
    Your running balance is your contributions and interest less what they
    owe, so the two balances add up to the joint balance."""
    rows = []
    first = FIRST_ROW
    for row_idx in range(first, first + row_count):
        before = "0" if row_idx == first else f"N{row_idx - 1}"
        rows.append(
            {
                "Spouse Share": (
                    f'=IF(H{row_idx}="Unclassified",0,'
                    f"E{row_idx}-I{row_idx}-K{row_idx})"
                ),
                "My Running Balance": (
                    f"=SUM(I${first}:I{row_idx})+SUM(K${first}:K{row_idx})"
                    f"-SUM(P${first}:P{row_idx})"
                ),
                "Spouse Running Balance": f"=MAX(0,{before}+L{row_idx})",
                "Spouse Share Covered": (f"=IF(L{row_idx}<0,-L{row_idx}-P{row_idx},0)"),
                "Owed by Spouse (Splitwise)": f"=MAX(0,-({before}+L{row_idx}))",
            }
        )
    return pd.DataFrame(rows, columns=_BALANCE_COLUMNS)


def export_joint_account_ledger_to_sheets() -> None:
    access_url = os.getenv(SIMPLEFIN_ACCESS_URL_ENV_VAR)
    if not access_url:
        logger.error(
            f"{SIMPLEFIN_ACCESS_URL_ENV_VAR} is not set - skipping joint account ledger export."
        )
        return
    if not JOINT_ACCOUNT_IDS:
        raise RuntimeError(
            "No joint accounts configured - set joint_ledger.accounts in the "
            "household config (HOUSEHOLD_CONFIG or config/household.json)"
        )

    # A preview run (PORTFOLIO_TAB_SUFFIX set, e.g. "_preview") writes
    # <tab><suffix> instead, created if missing, so the live tab the Budget
    # sheet imports is left alone. It still reads the live tab, which holds
    # the seed rows and overrides.
    suffix = os.getenv(PORTFOLIO_TAB_SUFFIX_ENV_VAR, "")
    tab = JOINT_ACCOUNT_LEDGER_SHEET_NAME + suffix

    logger.info(f"Reading existing ledger from '{JOINT_ACCOUNT_LEDGER_SHEET_NAME}'")
    # The header row is found by its first label rather than assumed, so a
    # tab still in an older layout (table from row 1) is read just the same
    existing_df = read_from_sheets(
        JOINT_ACCOUNT_LEDGER_SHEET_NAME, header_label=_OUTPUT_COLUMNS[0]
    )

    logger.info("Fetching joint account transactions from SimpleFIN")
    fetched_df = get_new_transactions_as_df(access_url)

    ledger_df = build_ledger_df(fetched_df, existing_df)

    logger.info(f"Writing {len(ledger_df)} rows to '{tab}'")
    if suffix:
        write_to_sheets(
            ledger_df, tab, start=(HEADER_ROW, 1), create_if_missing=True
        )
    else:
        write_to_sheets(ledger_df, tab, start=(HEADER_ROW, 1))

    for cell, value in summary_cells().items():
        write_cell_to_sheets(value, cell, tab)

    write_to_sheets(
        build_balance_columns_df(len(ledger_df)),
        tab,
        start=_BALANCE_COLUMNS_START,
        clear=False,
    )

    logger.info("Done!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    export_joint_account_ledger_to_sheets()
