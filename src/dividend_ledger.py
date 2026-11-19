"""
Dividend tracking from SimpleFIN transactions, for Wells Fargo (WellsTrade)
and Fidelity.

SimpleFIN only returns roughly the last 90 days of transactions, so each run
merges the dividends it sees into a persistent ledger tab, keyed by
transaction id, and the history grows from there. Rows already in the
ledger are never rewritten, so a manually added row - e.g. a one-off
"seed" for dividends received before the ledger started - stays put and
counts toward YTD like any other.

Each institution describes dividends differently:
- Fidelity: "DIVIDEND RECEIVED <name> (<SYMBOL>) (Cash)". Amount signs are
  unreliable (they flip partway through the history), so the absolute
  value is used.
- Wells Fargo: never says "dividend". A dividend is a positive amount whose
  description is "<SECURITY NAME> <MMDDYY pay date> <shares>", e.g.
  "MICROSOFT CORP 100126 100" (the date is sometimes partly masked, e.g.
  "XXX426"), usually followed by an equal negative entry
  when it's reinvested. Cash sweep interest has the same shape
  ("BANK DEPOSIT SWEEP 093026 24") and is excluded.

Each row also gets the security's ticker (Symbol), so other tabs can total
dividends by ticker. Fidelity's description carries it; for Wells Fargo
it's matched from the account's holdings by name (with_symbols()). A row
keeps the Symbol it has, so one filled in by hand (e.g. for a position
since sold, which no longer has a holding to match) stays.

The tab opens with a summary of totals by account, YTD and all time
(summary_cells()), above the table.
"""

import logging
import re
from datetime import date
from typing import Callable

import pandas as pd

from src.external_services.simplefin import to_float

logger = logging.getLogger(__name__)

LEDGER_COLUMNS = [
    "Transaction ID",
    "Posted",
    "Institution",
    "Account Name",
    "Security",
    "Description",
    "Amount",
    "Symbol",
]

# Layout: the summary in rows 2-4, the table's header in HEADER_ROW
HEADER_ROW = 6
FIRST_ROW = HEADER_ROW + 1

_FIDELITY_DIVIDEND_PREFIX = "DIVIDEND RECEIVED"
# Fidelity descriptions end like "... (HPE) (Cash)": the symbol is the last
# parenthesized group that isn't the cash/margin marker.
_PAREN_GROUP = re.compile(r"\(([^()]*)\)")
_NOT_SYMBOLS = {"CASH", "MARGIN"}

# The pay date is sometimes partly masked by SimpleFIN ("XXX426" for
# 091426), so X counts as a digit there.
_WELLS_FARGO_DIVIDEND = re.compile(r"^(?P<security>.*\S)\s+[\dX]{6}\s+\d+$")
_WELLS_FARGO_NOT_DIVIDENDS = {"BANK DEPOSIT SWEEP"}


def fidelity_dividend(description: str, amount: float) -> str | None:
    """The symbol if this Fidelity transaction is a dividend, else None."""
    if not description.upper().startswith(_FIDELITY_DIVIDEND_PREFIX):
        return None
    groups = [
        g for g in _PAREN_GROUP.findall(description) if g.upper() not in _NOT_SYMBOLS
    ]
    return groups[-1] if groups else ""


def wells_fargo_dividend(description: str, amount: float) -> str | None:
    """The security name if this WellsTrade transaction is a dividend, else
    None."""
    match = _WELLS_FARGO_DIVIDEND.match(description.strip())
    if amount <= 0 or not match:
        return None
    security = match["security"]
    return None if security.upper() in _WELLS_FARGO_NOT_DIVIDENDS else security


_WORD = re.compile(r"[A-Z0-9]+")


def _words(text: str) -> list[str]:
    return _WORD.findall(str(text).upper())


def match_symbol(security: str, holdings: list[dict]) -> str:
    """The ticker of the one holding whose name starts with the same words
    as a WellsTrade dividend's security name, else "". WellsTrade
    abbreviates (e.g. "ACME WHSL CORP NEW COM" for "Acme Wholesale Corp"),
    so this compares word by word only until a single holding is left."""
    words = _words(security)
    candidates = [
        (holding["symbol"], _words(holding.get("description") or ""))
        for holding in holdings
        if holding.get("symbol")
    ]
    for position, word in enumerate(words):
        candidates = [
            (symbol, name)
            for symbol, name in candidates
            if len(name) > position and name[position] == word
        ]
        if len(candidates) <= 1:
            break
    return candidates[0][0] if len(candidates) == 1 else ""


def with_symbols(ledger: pd.DataFrame, holdings: list[dict]) -> pd.DataFrame:
    """Fills in Symbol where it's blank: a Fidelity row's Security is
    already its ticker, and a Wells Fargo row is matched to `holdings` (the
    brokerage's current positions) by name. A Symbol already there, matched
    on an earlier run or typed by hand, is kept."""
    ledger = ledger.copy()
    for index, row in ledger.iterrows():
        if str(row.get("Symbol") or "").strip():
            continue
        if row["Institution"] == "Fidelity":
            ledger.at[index, "Symbol"] = row["Security"]
        elif row["Institution"] == "Wells Fargo":
            ledger.at[index, "Symbol"] = match_symbol(row["Security"], holdings)
    return ledger


def _criterion(text: str) -> str:
    """text as a SUMIFS criterion string literal, matching exactly: Sheets
    treats * ? ~ as wildcards and doubles quotes inside a literal."""
    escaped = re.sub(r"([*?~])", r"~\1", str(text)).replace('"', '""')
    return f'"{escaped}"'


def summary_cells(ledger: pd.DataFrame) -> dict[str, str]:
    """The summary above the table: a column per account (labels in row 2),
    with its dividends this year (row 3) and all time (row 4), then a
    Total column. Formulas over the table, so they stay current as the
    year turns over and when rows are added by hand."""
    col = {name: chr(ord("A") + i) for i, name in enumerate(LEDGER_COLUMNS)}

    def rng(name: str) -> str:
        return f"${col[name]}${FIRST_ROW}:${col[name]}"

    year_start = '">="&DATE(YEAR(TODAY()),1,1)'
    cells = {"A2": "Dividends", "A3": "YTD", "A4": "All time"}
    accounts = (
        ledger[["Institution", "Account Name"]]
        .astype(str)
        .drop_duplicates()
        .sort_values(["Institution", "Account Name"])
    )
    letter = "A"
    for institution, account in accounts.itertuples(index=False):
        letter = chr(ord(letter) + 1)
        cells[f"{letter}2"] = f"{institution} · {account}" if account else institution
        match = (
            f'{rng("Amount")},{rng("Institution")},{_criterion(institution)},'
            f'{rng("Account Name")},{_criterion(account)}'
        )
        cells[f"{letter}3"] = f'=SUMIFS({match},{rng("Posted")},{year_start})'
        cells[f"{letter}4"] = f"=SUMIFS({match})"
    letter = chr(ord(letter) + 1)
    cells[f"{letter}2"] = "Total"
    cells[f"{letter}3"] = f'=SUMIFS({rng("Amount")},{rng("Posted")},{year_start})'
    cells[f"{letter}4"] = f'=SUM({rng("Amount")})'
    return cells


_SHEETS_EPOCH = pd.Timestamp("1899-12-30")
_MAX_SHEETS_SERIAL = 100_000  # ~2173; anything larger is a unix timestamp


def _iso_date(value) -> str:
    """ISO date from a SimpleFIN unix timestamp, or from a ledger cell read
    back from Sheets (a date string, or a day-count serial)."""
    if isinstance(value, (int, float)) and not pd.isna(value):
        if value < _MAX_SHEETS_SERIAL:
            parsed = _SHEETS_EPOCH + pd.Timedelta(days=value)
        else:
            parsed = pd.to_datetime(value, unit="s")
    else:
        parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def _money(value) -> float:
    return to_float(str(value).replace("$", "").replace(",", "")) or 0.0


def extract_dividends(
    accounts: list[dict],
    institution: str,
    is_dividend: Callable[[str, float], str | None],
) -> pd.DataFrame:
    """Settled dividend transactions from the given accounts, as ledger rows
    tagged with `institution`. `is_dividend` returns the security for a
    dividend and None for anything else."""
    rows = []
    for account in accounts:
        for txn in account.get("transactions") or []:
            description = txn.get("description") or ""
            amount = to_float(txn.get("amount")) or 0.0
            security = is_dividend(description, amount)
            if security is None or not txn.get("id") or txn.get("pending"):
                continue
            rows.append(
                {
                    "Transaction ID": str(txn["id"]),
                    "Posted": _iso_date(txn.get("posted")),
                    "Institution": institution,
                    "Account Name": account.get("name", ""),
                    "Security": security,
                    "Description": description,
                    "Amount": abs(amount),
                    "Symbol": "",
                }
            )
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)


def merge_ledger(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Existing ledger rows plus any new transaction ids, oldest first.
    Existing rows win on a repeated id, so a row is never rewritten."""
    if existing.empty:
        existing = pd.DataFrame(columns=LEDGER_COLUMNS)
    existing = existing.reindex(columns=LEDGER_COLUMNS).fillna("")
    existing["Transaction ID"] = existing["Transaction ID"].astype(str)
    existing["Posted"] = existing["Posted"].map(_iso_date)
    existing["Amount"] = existing["Amount"].map(_money)

    fresh = new[~new["Transaction ID"].isin(existing["Transaction ID"])]
    parts = [df for df in (existing, fresh) if len(df)]
    merged = pd.concat(parts, ignore_index=True) if parts else existing
    logger.info(f"Dividend ledger: {len(fresh)} new, {len(merged)} total")
    return merged.sort_values(
        by=["Posted", "Transaction ID"], kind="stable"
    ).reset_index(drop=True)


def ytd_dividends(
    ledger: pd.DataFrame, institution: str, today: date | None = None
) -> float:
    """This year's ledger total for one institution."""
    today = today or date.today()
    rows = ledger[
        (ledger["Institution"] == institution)
        & ledger["Posted"].str.startswith(str(today.year))
    ]
    return float(rows["Amount"].sum())
