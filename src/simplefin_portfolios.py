"""
Rebuilds the Robinhood, Wells Fargo and Fidelity worksheets from SimpleFIN
holdings, in the same column layout the per-brokerage pipelines write, so
those tabs refresh on the SimpleFIN schedule without logins or file uploads.

SimpleFIN only gives symbol/description/shares/market value/purchase price
per holding, so the rest comes from yfinance: whether a symbol is an ETF,
sector/industry/description, and dividend rates. The Robinhood tabs'
received-dividend columns (Last Quarterly Dividend, Last Year's DVD, YTD
DVD) are estimates - per-share dividends by ex-date times the *current*
share count - since neither source has the account's actual payouts, and
Total DVD Paid (all-time) is left blank for the same reason.
"""

import logging
import os
from functools import cache

import pandas as pd

from src.constants.gsheets import (
    DIVIDENDS_LEDGER_SHEET_NAME,
    FIDELITY_DUMP_SHEET_NAME,
    PORTFOLIO_TAB_SUFFIX_ENV_VAR,
    RH_CASH_DUMP_SHEET_NAME,
    RH_CRYPTO_DUMP_SHEET_NAME,
    RH_ETF_DUMP_SHEET_NAME,
    RH_STOCK_DUMP_SHEET_NAME,
    WF_CASH_DUMP_SHEET_NAME,
    WF_ETF_DUMP_SHEET_NAME,
    WF_STOCK_DUMP_SHEET_NAME,
)
from src.constants import portfolio_columns as col
from src.dividend_ledger import (
    HEADER_ROW as DIVIDENDS_HEADER_ROW,
    LEDGER_COLUMNS as DIVIDENDS_LEDGER_COLUMNS,
    extract_dividends,
    fidelity_dividend,
    merge_ledger,
    summary_cells as dividends_summary_cells,
    wells_fargo_dividend,
    with_symbols,
    ytd_dividends,
)
from src.external_services.google_sheets import (
    read_from_sheets,
    write_cell_to_sheets,
    write_cells_to_sheets,
    write_to_sheets,
)
from src.external_services.market_data import get_dividend_history, get_security_info
from src.external_services.simplefin import (
    PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS,
    account_balance,
    to_float,
)
from src.fidelity_parser import (
    YTD_DIVIDENDS_LABEL_CELL,
    YTD_DIVIDENDS_VALUE_CELL,
    sync_fidelity_account_history_from_drive,
    write_fidelity_positions_to_sheets,
    write_ytd_realized_pnl_to_sheets,
)

logger = logging.getLogger(__name__)

# Accounts are routed by case-insensitive substring of SimpleFIN's org name
# and account name, rather than hard-coded account ids, so re-linking an
# account in the Bridge doesn't silently stop a tab from updating.
ROBINHOOD_INSTITUTION = "robinhood"
ROBINHOOD_CRYPTO_ACCOUNT = "crypto"
WELLS_FARGO_INSTITUTION = "wells fargo"
FIDELITY_INSTITUTION = "fidelity"
FIDELITY_ACCOUNT = "roth"

_ETF_QUOTE_TYPE = "ETF"
_QUARTERS_PER_YEAR = 4
_DAYS_IN_QUARTER = 90

_FIDELITY_COLUMNS = [
    "Current Stop Price",
    "Original Stop Price",
    "R Value",
    "Current R Multiple",
    "Stop R Multiple",
    "Average Cost Basis",
    "Symbol",
    "Description",
    "Quantity",
    "Current Value",
]


def _matches(value, needle: str) -> bool:
    return needle in (value or "").lower()


def _institution_accounts(accounts: list[dict], institution: str) -> list[dict]:
    return [a for a in accounts if _matches(a.get("org", {}).get("name"), institution)]


def _is_dead(holding: dict) -> bool:
    """A holding with no market value and either no shares (a closed
    position SimpleFIN still reports) or no cost (e.g. an escrow
    placeholder like "ACME CORP ESC": shares, but $0 value and $0 cost). A real position with a missing quote still has a cost, so it's
    kept; so is Robinhood crypto, which has a value but no cost."""
    return not _num(holding, "market_value") and not (
        _num(holding, "shares") and _num(holding, "purchase_price")
    )


def _holdings(accounts: list[dict]) -> list[dict]:
    """All holdings across the accounts, minus dead ones (see _is_dead)."""
    return [h for a in accounts for h in (a.get("holdings") or []) if not _is_dead(h)]


def _num(holding: dict, field: str) -> float:
    return to_float(holding.get(field)) or 0.0


@cache
def _security_info(symbol: str) -> dict:
    return get_security_info(symbol)


@cache
def _dividends(symbol: str) -> pd.Series:
    dividends = get_dividend_history(symbol)
    if not isinstance(dividends.index, pd.DatetimeIndex):
        # An empty history has no dates to compare against
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    return dividends


def _is_etf(symbol: str) -> bool:
    return _security_info(symbol).get("quoteType") == _ETF_QUOTE_TYPE


def _annual_dividend_rate(symbol: str) -> float:
    """yfinance's forward dividendRate, falling back to the trailing 12
    months of per-share dividends - ETFs don't report a dividendRate."""
    rate = to_float(_security_info(symbol).get("dividendRate"))
    if rate:
        return rate
    dividends = _dividends(symbol)
    year_ago = pd.Timestamp.today().normalize() - pd.DateOffset(years=1)
    return float(dividends[dividends.index > year_ago].sum())


def _known_costs(tabs: list[str], symbol_col: str, cost_col: str) -> dict[str, float]:
    """Symbol -> cost per share from the live tabs as they stand, so a
    holding SimpleFIN reports without a cost (purchase_price 0 - e.g. all of
    Robinhood crypto) keeps the last known one instead of dropping to 0.
    Always reads the live tabs, even on a preview run."""
    costs = {}
    for tab in tabs:
        try:
            df = read_from_sheets(tab)
        except Exception:
            logger.warning(f"Could not read '{tab}' for known costs - skipping")
            continue
        if symbol_col not in df.columns or cost_col not in df.columns:
            continue
        for symbol, cost in zip(df[symbol_col], df[cost_col]):
            cost = to_float(str(cost).replace("$", "").replace(",", ""))
            if symbol and cost:
                costs[str(symbol)] = cost
    return costs


# A column you tick (TRUE) on WF_stock_dump / WF_etf_dump to put a holding
# in your dividend portfolio. The tabs are rewritten every run, so the
# ticked symbols are read back first and ticked again.
DIVIDEND_PORTFOLIO_COLUMN = "Dividend Portfolio"
_TICKED = {"TRUE", "YES", "Y", "X", "1"}


def _ticked_symbols(tabs: list[str]) -> set[str]:
    """Symbols ticked in the Dividend Portfolio column of the live tabs
    (TRUE from a checkbox, or yes/x/1 typed in), even on a preview run.
    Unlike _known_costs(), a failed read raises: writing the tabs without
    the ticks would wipe them."""
    ticked = set()
    for tab in tabs:
        df = read_from_sheets(tab)
        if "Symbol" not in df.columns or DIVIDEND_PORTFOLIO_COLUMN not in df.columns:
            continue
        for symbol, flag in zip(df["Symbol"], df[DIVIDEND_PORTFOLIO_COLUMN]):
            if symbol and str(flag).strip().upper() in _TICKED:
                ticked.add(str(symbol))
    return ticked


def _with_known_costs(holdings: list[dict], costs: dict[str, float]) -> list[dict]:
    result, filled = [], 0
    for holding in holdings:
        symbol = holding.get("symbol") or ""
        if not _num(holding, "purchase_price") and costs.get(symbol):
            holding = {**holding, "purchase_price": costs[symbol]}
            filled += 1
        result.append(holding)
    if filled:
        logger.info(f"Kept the last known cost for {filled} holding(s) with none")
    return result


def _split_stocks_etfs(holdings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Splits holdings by yfinance's quoteType. If no symbol could be looked
    up at all (Yahoo unreachable), raises instead of guessing, since filing
    every ETF under stocks would wipe the ETF tab; a single unknown symbol
    is treated as a stock."""
    symbols = [h.get("symbol") or "" for h in holdings]
    if symbols and not any(_security_info(s) for s in symbols):
        raise RuntimeError(
            "Could not look up any symbol on yfinance to tell stocks from ETFs"
        )

    stocks, etfs = [], []
    for holding, symbol in zip(holdings, symbols):
        if not _security_info(symbol):
            # Symbol left out: Actions logs are public
            logger.warning("A holding has no yfinance data - treating it as a stock")
        (etfs if _is_etf(symbol) else stocks).append(holding)
    return stocks, etfs


def build_rh_stock_df(
    holdings: list[dict], today: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Robinhood stock/ETF tab, same columns and order as
    the original Robinhood pipeline wrote, sorted by Total (cost) descending."""
    if not holdings:
        return pd.DataFrame(columns=col.RH_STOCK_COLUMNS)

    today = (today or pd.Timestamp.today()).normalize()
    rows = []
    for holding in holdings:
        symbol = holding.get("symbol") or ""
        info = _security_info(symbol)
        shares = _num(holding, "shares")
        dividends = _dividends(symbol)
        rows.append(
            {
                col.TICKER: symbol,
                col.NAME: holding.get("description") or "",
                col.AVG_PRICE: _num(holding, "purchase_price"),
                col.QUANTITY: shares,
                col.DESCRIPTION: info.get("longBusinessSummary", ""),
                col.SECTOR: info.get("sector", ""),
                col.INDUSTRY: info.get("industry", ""),
                # Robinhood's rate is per payment, normalized to a quarter
                col.DVD_RATE: _annual_dividend_rate(symbol) / _QUARTERS_PER_YEAR,
                col.LAST_DIVIDEND: shares
                * dividends[
                    dividends.index > today - pd.Timedelta(days=_DAYS_IN_QUARTER)
                ].sum(),
                # Not derivable here; "" since pygsheets writes NaN as text
                col.TOTAL_DVD_PAID: "",
                col.LAST_YEAR_DVD: shares
                * dividends[dividends.index.year == today.year - 1].sum(),
                col.YTD_DVD: shares
                * dividends[
                    (dividends.index.year == today.year) & (dividends.index <= today)
                ].sum(),
            }
        )

    df = pd.DataFrame(rows)
    total = col.TOTAL
    df[total] = df[col.AVG_PRICE] * df[col.QUANTITY]
    df[col.DIVERSITY] = df[total] / df[total].sum() if df[total].sum() else 0.0
    df[col.PROJECTED_DVD] = df[col.DVD_RATE] * df[col.QUANTITY]
    df = df.sort_values(by=total, ascending=False).reset_index(drop=True)
    return df[col.RH_STOCK_COLUMNS]


def build_rh_crypto_df(holdings: list[dict]) -> pd.DataFrame:
    rows = [
        {
            col.TICKER: h.get("symbol") or "",
            col.NAME: h.get("description") or "",
            col.AVG_PRICE: _num(h, "purchase_price"),
            col.QUANTITY: _num(h, "shares"),
            col.TOTAL: _num(h, "purchase_price") * _num(h, "shares"),
        }
        for h in holdings
    ]
    if not rows:
        return pd.DataFrame(columns=col.RH_CRYPTO_COLUMNS)
    df = pd.DataFrame(rows, columns=col.RH_CRYPTO_COLUMNS)
    return df.sort_values(by=col.TOTAL, ascending=False).reset_index(drop=True)


def uninvested_cash(accounts: list[dict]) -> float:
    """Account balance minus the market value of its holdings, summed."""
    cash = 0.0
    for account in accounts:
        holdings_value = sum(
            _num(h, "market_value") for h in account.get("holdings") or []
        )
        cash += (account_balance(account) or 0.0) - holdings_value
    return round(cash, 2)


def build_wf_df(
    holdings: list[dict], ticked: set[str] | frozenset = frozenset()
) -> pd.DataFrame:
    """Wells Fargo stock/ETF tab, the WellsTrade export's columns plus
    Dividend Portfolio (TRUE for the symbols in `ticked`, else blank),
    sorted by Symbol. DVD Rate is the annual per-share dividend and Est.
    Annual Yield a fraction (0.0266 for 2.66%), as in the WellsTrade export."""
    columns = [*col.WF_COLUMNS, DIVIDEND_PORTFOLIO_COLUMN]
    rows = []
    for holding in holdings:
        symbol = holding.get("symbol") or ""
        description = holding.get("description") or ""
        shares = _num(holding, "shares")
        market_value = _num(holding, "market_value")
        rate = _annual_dividend_rate(symbol)
        price = market_value / shares if shares else 0.0
        rows.append(
            {
                # As in the WellsTrade export, a holding without
                # a ticker (e.g. a fund with no live quote)
                "Symbol": symbol or description,
                "Description": description,
                "Quantity": shares,
                "Average Cost Basis": _num(holding, "purchase_price"),
                "Current Value": market_value,
                "DVD Rate": rate,
                "Est. Annual Yield": rate / price if price else 0.0,
                "Projected DVD": rate * shares,
                # Blank rather than FALSE, so an unticked checkbox stays
                # unticked and a plain cell stays empty
                DIVIDEND_PORTFOLIO_COLUMN: True if symbol in ticked else "",
            }
        )
    if not rows:
        return pd.DataFrame(columns=columns)
    df = pd.DataFrame(rows, columns=columns)
    return df.sort_values(by="Symbol").reset_index(drop=True)


def build_fidelity_df(holdings: list[dict]) -> pd.DataFrame:
    """fidelity_dump positions, in the column layout of Fidelity's positions export
    (stop-price and formula columns as blank placeholders)."""
    rows = [
        {
            "Average Cost Basis": _num(h, "purchase_price"),
            "Symbol": h.get("symbol") or "",
            "Description": h.get("description") or "",
            "Quantity": _num(h, "shares"),
            "Current Value": _num(h, "market_value"),
        }
        for h in holdings
    ]
    df = pd.DataFrame(rows, columns=_FIDELITY_COLUMNS)
    for column in _FIDELITY_COLUMNS[:5]:
        df[column] = ""
    return df.sort_values(by="Symbol").reset_index(drop=True)


class _Writer:
    """Writes to `<tab><suffix>`. With a suffix set (a preview run), tabs
    are created on first write, since they won't exist yet."""

    def __init__(self, suffix: str):
        self.suffix = suffix

    def tab(self, name: str) -> str:
        return name + self.suffix

    def write(self, df: pd.DataFrame, name: str) -> None:
        logger.info(f"Writing to Google Sheets tab: '{self.tab(name)}'")
        if self.suffix:
            write_to_sheets(df, self.tab(name), create_if_missing=True)
        else:
            write_to_sheets(df, self.tab(name))


def _export_robinhood(accounts: list[dict], writer: _Writer) -> None:
    rh_accounts = _institution_accounts(accounts, ROBINHOOD_INSTITUTION)
    crypto = [
        a for a in rh_accounts if _matches(a.get("name"), ROBINHOOD_CRYPTO_ACCOUNT)
    ]
    brokerage = [a for a in rh_accounts if a not in crypto]

    # Crypto and cash first: they don't depend on yfinance lookups
    if crypto:
        costs = _known_costs(
            [RH_CRYPTO_DUMP_SHEET_NAME],
            col.TICKER,
            col.AVG_PRICE,
        )
        writer.write(
            build_rh_crypto_df(_with_known_costs(_holdings(crypto), costs)),
            RH_CRYPTO_DUMP_SHEET_NAME,
        )
    else:
        logger.warning("No Robinhood crypto account in SimpleFIN - skipping its tab")

    if brokerage:
        writer.write(
            pd.DataFrame({"Available Cash": [uninvested_cash(brokerage)]}),
            RH_CASH_DUMP_SHEET_NAME,
        )
        costs = _known_costs(
            [RH_STOCK_DUMP_SHEET_NAME, RH_ETF_DUMP_SHEET_NAME],
            col.TICKER,
            col.AVG_PRICE,
        )
        stocks, etfs = _split_stocks_etfs(
            _with_known_costs(_holdings(brokerage), costs)
        )
        writer.write(build_rh_stock_df(stocks), RH_STOCK_DUMP_SHEET_NAME)
        writer.write(build_rh_stock_df(etfs), RH_ETF_DUMP_SHEET_NAME)
    else:
        logger.warning(
            "No Robinhood brokerage account in SimpleFIN - skipping its tabs"
        )


def _export_wells_fargo(accounts: list[dict], writer: _Writer) -> None:
    wf_accounts = _institution_accounts(accounts, WELLS_FARGO_INSTITUTION)
    # The brokerage is the one account reporting holdings; requiring holdings
    # also means a refresh glitch that drops them leaves the tabs untouched
    # rather than wiping them.
    brokerage = [a for a in wf_accounts if a.get("holdings")]
    cash_accounts = [
        a for a in wf_accounts if a.get("id") in PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS
    ]

    if cash_accounts:
        cash = sum(account_balance(a) or 0.0 for a in cash_accounts)
        writer.write(pd.DataFrame({"Available Cash": [cash]}), WF_CASH_DUMP_SHEET_NAME)
    else:
        logger.warning(
            "No Wells Fargo brokerage cash account in SimpleFIN - skipping its tab"
        )

    if brokerage:
        costs = _known_costs(
            [WF_STOCK_DUMP_SHEET_NAME, WF_ETF_DUMP_SHEET_NAME],
            "Symbol",
            "Average Cost Basis",
        )
        ticked = _ticked_symbols([WF_STOCK_DUMP_SHEET_NAME, WF_ETF_DUMP_SHEET_NAME])
        stocks, etfs = _split_stocks_etfs(
            _with_known_costs(_holdings(brokerage), costs)
        )
        writer.write(build_wf_df(stocks, ticked), WF_STOCK_DUMP_SHEET_NAME)
        writer.write(build_wf_df(etfs, ticked), WF_ETF_DUMP_SHEET_NAME)
    else:
        logger.warning(
            "No Wells Fargo account with holdings in SimpleFIN - skipping its tabs"
        )


def _export_fidelity(accounts: list[dict], writer: _Writer) -> None:
    roth = [
        a
        for a in _institution_accounts(accounts, FIDELITY_INSTITUTION)
        if _matches(a.get("name"), FIDELITY_ACCOUNT)
    ]
    if not roth:
        logger.warning("No Fidelity Roth IRA account in SimpleFIN - skipping its tab")
        return

    tab = writer.tab(FIDELITY_DUMP_SHEET_NAME)
    write_fidelity_positions_to_sheets(
        build_fidelity_df(
            _with_known_costs(
                _holdings(roth),
                _known_costs(
                    [FIDELITY_DUMP_SHEET_NAME], "Symbol", "Average Cost Basis"
                ),
            )
        ),
        tab,
        create_if_missing=bool(writer.suffix),
    )
    sync_fidelity_account_history_from_drive()
    write_ytd_realized_pnl_to_sheets(tab)


# Outside WF_stock_dump's A-I table, so the cells stay put however many
# positions there are (same idea as fidelity_dump's L/M cells).
WF_YTD_DIVIDENDS_LABEL_CELL = "J1"
WF_YTD_DIVIDENDS_VALUE_CELL = "K1"


def _write_ytd_dividends(
    ledger: pd.DataFrame, institution: str, tab: str, label_cell: str, value_cell: str
) -> None:
    total = ytd_dividends(ledger, institution)
    logger.info(f"Writing {institution} YTD dividends to '{tab}'")
    write_cell_to_sheets("YTD Dividends", label_cell, tab)
    write_cell_to_sheets(total, value_cell, tab)


def _export_dividends(accounts: list[dict], writer: _Writer) -> None:
    """Merges the Wells Fargo brokerage and Fidelity dividends in this
    response into the dividends_ledger tab (with each row's ticker, and a
    summary of totals by account above the table), then writes each institution's
    YTD total next to its positions (WF_stock_dump J1/K1, fidelity_dump
    L2/M2). Runs after the brokerage tabs, since writing those clears the
    cells. Reads the live ledger even on a preview run. A failed read raises
    rather than reading as empty, so a transient error can't rewrite the
    ledger with only ~90 days of rows."""
    wf_brokerage = [
        a
        for a in _institution_accounts(accounts, WELLS_FARGO_INSTITUTION)
        if a.get("holdings")
    ]
    fidelity_accounts = _institution_accounts(accounts, FIDELITY_INSTITUTION)
    new = pd.concat(
        [
            extract_dividends(wf_brokerage, "Wells Fargo", wells_fargo_dividend),
            extract_dividends(fidelity_accounts, "Fidelity", fidelity_dividend),
        ],
        ignore_index=True,
    )
    # The header row is found by its first label, since the summary sits
    # above it (and older tabs had the table from row 1)
    existing = read_from_sheets(
        DIVIDENDS_LEDGER_SHEET_NAME, header_label=DIVIDENDS_LEDGER_COLUMNS[0]
    )
    holdings = [h for account in wf_brokerage for h in account.get("holdings") or []]
    ledger = with_symbols(merge_ledger(existing, new), holdings)
    ledger_tab = writer.tab(DIVIDENDS_LEDGER_SHEET_NAME)
    logger.info(f"Writing to Google Sheets tab: '{ledger_tab}'")
    write_to_sheets(
        ledger, ledger_tab, create_if_missing=True, start=(DIVIDENDS_HEADER_ROW, 1)
    )
    write_cells_to_sheets(dividends_summary_cells(ledger), ledger_tab)

    if wf_brokerage:
        _write_ytd_dividends(
            ledger,
            "Wells Fargo",
            writer.tab(WF_STOCK_DUMP_SHEET_NAME),
            WF_YTD_DIVIDENDS_LABEL_CELL,
            WF_YTD_DIVIDENDS_VALUE_CELL,
        )
    if fidelity_accounts:
        _write_ytd_dividends(
            ledger,
            "Fidelity",
            writer.tab(FIDELITY_DUMP_SHEET_NAME),
            YTD_DIVIDENDS_LABEL_CELL,
            YTD_DIVIDENDS_VALUE_CELL,
        )


def export_portfolios_to_sheets(accounts: list[dict]) -> None:
    """Writes every brokerage tab from one SimpleFIN response. Each
    institution is independent: one failing is logged and the rest still
    run, then the export raises so the workflow run shows as failed. If the
    PORTFOLIO_TAB_SUFFIX env var is set (e.g. "_preview"), tabs are written
    with that suffix instead, so a run can be compared against the live
    tabs before replacing them."""
    writer = _Writer(os.getenv(PORTFOLIO_TAB_SUFFIX_ENV_VAR, ""))

    failed = []
    for name, export in [
        ("Robinhood", _export_robinhood),
        ("Wells Fargo", _export_wells_fargo),
        ("Fidelity", _export_fidelity),
        # Last: writes YTD cells into the WF/Fidelity tabs written above
        ("Dividends", _export_dividends),
    ]:
        try:
            export(accounts, writer)
        except Exception:
            logger.exception(f"{name} export from SimpleFIN failed")
            failed.append(name)

    if failed:
        raise RuntimeError(
            f"SimpleFIN portfolio export failed for: {', '.join(failed)}"
        )
