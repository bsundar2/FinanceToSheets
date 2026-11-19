"""
File containing the logic of exporting SimpleFIN-linked bank, credit card,
and retirement account balances - plus any per-security holdings those
accounts report - to Google Sheets. Also refreshes the Robinhood, Wells
Fargo and Fidelity tabs from those holdings (see simplefin_portfolios.py).
"""

import logging
import os
from datetime import date, datetime, timedelta, timezone

import pandas as pd

from src.constants.gsheets import (
    BANK_ACCOUNTS_DUMP_SHEET_NAME,
    HOLDINGS_DUMP_SHEET_NAME,
    SIMPLEFIN_ACCESS_URL_ENV_VAR,
)
from src.external_services.google_sheets import write_to_sheets
from src.simplefin_portfolios import export_portfolios_to_sheets
from src.external_services.simplefin import (
    get_bank_accounts,
    account_balance,
    to_float as _to_float,
    PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS as _PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS,
)

logger = logging.getLogger(__name__)

_OUTPUT_COLUMNS = ["Institution", "Account Name", "Balance", "Balance As Of"]

# Cost Basis and Purchase Price are written exactly as SimpleFIN returns them:
# the protocol says cost_basis is per-share, but some brokerages (reportedly
# Fidelity, Vanguard, Schwab, E*Trade) send the position's total cost
# instead. Which convention each linked institution actually uses hasn't
# been confirmed yet, so no normalization is applied here.
_HOLDINGS_OUTPUT_COLUMNS = [
    "Institution",
    "Account Name",
    "Symbol",
    "Description",
    "Shares",
    "Market Value",
    "Cost Basis (raw)",
    "Purchase Price (raw)",
    "Currency",
    "As Of",
]


def _balance_as_of(balance_date) -> date | None:
    if not balance_date:
        return None
    return datetime.fromtimestamp(int(balance_date), tz=timezone.utc).date()


def get_bank_accounts_as_df(accounts: list[dict]) -> pd.DataFrame:
    """Maps SimpleFIN accounts to a DataFrame, sorted by institution then
    account name. Accounts with no balance (a refresh failure not severe
    enough to land in errlist) are skipped, since there's nothing meaningful
    to write for them."""
    rows = []
    for account in accounts:
        balance = account_balance(account)
        if balance is None:
            logger.warning(
                f"Skipping a {account.get('org', {}).get('name', '')} account - no balance returned"
            )
            continue

        rows.append(
            {
                "Institution": account.get("org", {}).get("name", ""),
                "Account Name": account.get("name", ""),
                "Balance": balance,
                "Balance As Of": _balance_as_of(account.get("balance-date")),
            }
        )

    if not rows:
        return pd.DataFrame(columns=_OUTPUT_COLUMNS)

    df = pd.DataFrame(rows, columns=_OUTPUT_COLUMNS)
    return df.sort_values(by=["Institution", "Account Name"]).reset_index(drop=True)


def get_holdings_as_df(accounts: list[dict]) -> pd.DataFrame:
    """Flattens each account's optional "holdings" list into one row per
    holding, sorted by institution, account name, then symbol. Logs a
    per-institution holdings count - deliberately without account names,
    symbols, or amounts, since Actions logs are a less private place than
    the sheet - so a run's logs alone show which institutions report
    holdings at all (no "holdings" field) vs. report an empty list."""
    rows = []
    for account in accounts:
        institution = account.get("org", {}).get("name", "")
        holdings = account.get("holdings")
        if holdings is None:
            logger.info(f"{institution}: account has no holdings field")
            continue
        logger.info(f"{institution}: account has {len(holdings)} holdings")

        as_of = _balance_as_of(account.get("balance-date"))
        for holding in holdings:
            rows.append(
                {
                    "Institution": institution,
                    "Account Name": account.get("name", ""),
                    "Symbol": holding.get("symbol") or "",
                    "Description": holding.get("description") or "",
                    "Shares": _to_float(holding.get("shares")),
                    "Market Value": _to_float(holding.get("market_value")),
                    "Cost Basis (raw)": _to_float(holding.get("cost_basis")),
                    "Purchase Price (raw)": _to_float(holding.get("purchase_price")),
                    "Currency": holding.get("currency") or "",
                    "As Of": as_of,
                }
            )

    if not rows:
        return pd.DataFrame(columns=_HOLDINGS_OUTPUT_COLUMNS)

    df = pd.DataFrame(rows, columns=_HOLDINGS_OUTPUT_COLUMNS)
    return df.sort_values(by=["Institution", "Account Name", "Symbol"]).reset_index(
        drop=True
    )


_TRANSACTION_HISTORY_DAYS = 90


def export_bank_accounts_to_sheets() -> None:
    access_url = os.getenv(SIMPLEFIN_ACCESS_URL_ENV_VAR)
    if not access_url:
        logger.error(
            f"{SIMPLEFIN_ACCESS_URL_ENV_VAR} is not set - skipping SimpleFIN export."
        )
        return

    # The Bridge only returns ~90 days of transactions however far back
    # start-date goes; asking for that much keeps the dividend ledger's
    # overlap between runs as wide as possible.
    logger.info("Fetching linked accounts from SimpleFIN")
    accounts = get_bank_accounts(
        access_url, start_date=date.today() - timedelta(days=_TRANSACTION_HISTORY_DAYS)
    )

    # Balances go first so a holdings problem can't block the existing tab.
    logger.info(f"Writing to Google Sheets tab: '{BANK_ACCOUNTS_DUMP_SHEET_NAME}'")
    write_to_sheets(get_bank_accounts_as_df(accounts), BANK_ACCOUNTS_DUMP_SHEET_NAME)

    logger.info(f"Writing to Google Sheets tab: '{HOLDINGS_DUMP_SHEET_NAME}'")
    write_to_sheets(
        get_holdings_as_df(accounts), HOLDINGS_DUMP_SHEET_NAME, create_if_missing=True
    )

    export_portfolios_to_sheets(accounts)

    logger.info("Done!")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    export_bank_accounts_to_sheets()
