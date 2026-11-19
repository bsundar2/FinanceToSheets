import pandas as pd

# Same source (and yf.download parameters) SwingTradeScreener already relies
# on in production for its SPY benchmark - see screener/screener.py there.
# yfinance handles Yahoo Finance's session/cookie dance internally, unlike
# Stooq's CSV endpoint (gated behind a JS proof-of-work bot check a plain
# HTTP client can't solve) or hand-rolled scraping.
BENCHMARK_TICKER = "SPY"
PRICE_HISTORY_PERIOD = "2y"

try:
    # yfinance depends on curl_cffi, which has compiled native code and
    # can't load under Pyodide (e.g. pnl_tracker.py exported via marimo's
    # html-wasm and run in-browser) - guard the import itself, not just the
    # network call, so the rest of this module still loads there.
    import yfinance as yf
except Exception:
    yf = None


def get_sp500_weekly_returns(
    ticker=BENCHMARK_TICKER, period=PRICE_HISTORY_PERIOD
) -> pd.DataFrame:
    """Fetches SPY weekly closes via yfinance (native weekly bars, indexed by
    each week's Monday) and returns week-over-week % returns, keyed by the
    same Friday-anchored weekly period used for the realized P&L aggregation
    so the two can be merged directly. Returns an empty DataFrame (rather
    than raising) on any fetch/parse failure, or if yfinance itself couldn't
    be imported, so the dashboard can degrade gracefully."""
    if yf is None:
        return pd.DataFrame(columns=["week", "pct_return"])

    try:
        raw = yf.download(
            ticker, period=period, interval="1wk", auto_adjust=True, progress=False
        )
    except Exception:
        return pd.DataFrame(columns=["week", "pct_return"])

    if raw.empty:
        return pd.DataFrame(columns=["week", "pct_return"])

    close = (
        raw[("Close", ticker)]
        if isinstance(raw.columns, pd.MultiIndex)
        else raw["Close"]
    )
    close = close.dropna()

    weekly = (close.pct_change() * 100).rename("pct_return").reset_index()
    date_column = weekly.columns[0]
    weekly["week"] = pd.to_datetime(weekly[date_column]).dt.to_period("W-FRI")
    return weekly[["week", "pct_return"]].dropna().reset_index(drop=True)


def get_security_info(symbol: str) -> dict:
    """Fetches yfinance's quote summary for one symbol (quoteType, sector,
    industry, longBusinessSummary, dividendRate, ...). Used to fill in the
    columns SimpleFIN holdings don't carry, including whether a symbol is an
    ETF. Returns {} on any failure so a lookup problem degrades to blank
    columns rather than failing the export."""
    if yf is None:
        return {}
    try:
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


def get_dividend_history(symbol: str) -> pd.Series:
    """Per-share dividends keyed by ex-dividend date (timezone-naive), via
    yfinance. Empty on any failure, same rationale as get_security_info."""
    empty = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    if yf is None:
        return empty
    try:
        dividends = yf.Ticker(symbol).dividends
    except Exception:
        return empty
    if dividends is None or dividends.empty:
        return empty
    if getattr(dividends.index, "tz", None) is not None:
        dividends = dividends.tz_localize(None)
    return dividends.astype(float)
