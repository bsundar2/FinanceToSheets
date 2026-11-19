import logging
from datetime import date, datetime, timezone
from urllib.parse import urlsplit, urlunsplit

import requests

from src import household_config

logger = logging.getLogger(__name__)

# Accounts where SimpleFIN's `balance` field misreports as 0 while the real,
# spendable figure lives in `available-balance` instead - confirmed for Wells
# Fargo's brokerage cash sweep account. This is NOT safe to apply generally:
# for a credit card, `balance` (amount owed) and `available-balance`
# (remaining credit limit) mean different things entirely, so a paid-off
# card's `balance: 0` would get overwritten with its credit limit if this
# were a blanket fallback instead of an explicit, per-account allowlist.
# The ids come from the household config's
# prefer_available_balance_account_ids (see src/household_config.py); add
# one there if you spot the same 0-balance pattern elsewhere (e.g. another
# brokerage's cash sweep account).
PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS = frozenset(
    household_config.load().get("prefer_available_balance_account_ids", [])
)


def to_float(value) -> float | None:
    """SimpleFIN sends numeric fields as strings; blanks and junk become
    None rather than failing the whole export."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def account_balance(account: dict) -> float | None:
    """An account's balance as a float, honoring
    PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS. None when SimpleFIN returned no
    usable balance."""
    balance = account.get("balance")
    if account.get("id") in PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS:
        balance = account.get("available-balance", balance)
    return to_float(balance)


def _accounts_url(access_url: str) -> str:
    return access_url.rstrip("/") + "/accounts"


def _split_auth(access_url: str) -> tuple[str, tuple[str, str] | None]:
    """SimpleFIN Access URLs embed Basic Auth credentials directly in the
    URL (https://user:pass@bridge.simplefin.org/...). requests won't send
    credentials that are simply left in the URL, so they're pulled out here
    and passed as an explicit auth tuple instead."""
    parts = urlsplit(access_url)
    if parts.username is None:
        return access_url, None

    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    stripped = urlunsplit(
        (parts.scheme, netloc, parts.path, parts.query, parts.fragment)
    )
    return stripped, (parts.username, parts.password or "")


def get_bank_accounts(access_url: str, start_date: date | None = None) -> list[dict]:
    """Fetches the current account list (with balances) from a SimpleFIN
    Bridge Access URL. Per the SimpleFIN protocol, a successful response may
    still carry an "errlist" of per-account refresh failures alongside
    otherwise-valid accounts - those are logged as warnings, not raised,
    since the rest of the account set is still usable. start_date asks for
    transactions posted on or after that date (the protocol's start-date);
    without it the Bridge returns its default recent window."""
    base_url, auth = _split_auth(_accounts_url(access_url))
    kwargs = {}
    if start_date is not None:
        start = datetime(
            start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc
        )
        kwargs["params"] = {"start-date": int(start.timestamp())}
    response = requests.get(base_url, auth=auth, **kwargs)
    response.raise_for_status()

    payload = response.json()
    for error in payload.get("errlist", []) or []:
        logger.warning(f"SimpleFIN account refresh error: {error}")

    return payload.get("accounts", [])


def get_transactions(
    access_url: str, account_ids: list[str], start_date: int
) -> list[dict]:
    """Fetches transactions for a specific set of accounts (the same
    `/accounts` endpoint as `get_bank_accounts`, but scoped with `account`
    and `start-date` query params, which is how the SimpleFIN protocol
    filters transaction history). Each returned account dict carries its
    transactions in a "transactions" list; pending transactions are dropped
    since they can still change or disappear before they post. Returns a
    flat list of transaction dicts, each tagged with `account_id` and
    `account_name` so callers don't need to re-associate them."""
    base_url, auth = _split_auth(_accounts_url(access_url))
    params = [("start-date", start_date)] + [
        ("account", account_id) for account_id in account_ids
    ]
    response = requests.get(base_url, auth=auth, params=params)
    response.raise_for_status()

    payload = response.json()
    for error in payload.get("errlist", []) or []:
        logger.warning(f"SimpleFIN account refresh error: {error}")

    transactions = []
    for account in payload.get("accounts", []):
        for txn in account.get("transactions", []) or []:
            if txn.get("pending"):
                continue
            transactions.append(
                {
                    **txn,
                    "account_id": account.get("id"),
                    "account_name": account.get("name"),
                }
            )
    return transactions
