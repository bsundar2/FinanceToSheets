import pandas as pd
from unittest.mock import patch

from src.external_services.market_data import (
    get_dividend_history,
    get_security_info,
    get_sp500_weekly_returns,
)


def _fake_yf_download(closes, start="2026-01-26"):
    # Mirrors yfinance's yf.download(interval="1wk") shape: rows indexed by
    # each week's Monday, MultiIndex (Price, Ticker) columns even for a
    # single ticker (confirmed against a real GitHub Actions run).
    idx = pd.date_range(start, periods=len(closes), freq="W-MON")
    idx.name = "Date"
    columns = pd.MultiIndex.from_product([["Close", "High", "Low", "Open", "Volume"], ["SPY"]], names=["Price", "Ticker"])
    data = [[c, c + 1, c - 1, c, 1000] for c in closes]
    return pd.DataFrame(data, index=idx, columns=columns)


class TestGetSp500WeeklyReturns:
    def test_returns_pct_return_and_week_columns(self):
        with patch("src.external_services.market_data.yf.download", return_value=_fake_yf_download([100, 101, 99, 102])):
            result = get_sp500_weekly_returns()
        assert list(result.columns) == ["week", "pct_return"]

    def test_computes_week_over_week_pct_change(self):
        with patch("src.external_services.market_data.yf.download", return_value=_fake_yf_download([100, 101, 99, 102])):
            result = get_sp500_weekly_returns()
        # 100 -> 101 is a 1% gain; 101 -> 99 is a ~1.98% drop
        assert round(result["pct_return"].iloc[0], 2) == 1.0
        assert round(result["pct_return"].iloc[1], 2) == -1.98

    def test_drops_first_row_with_no_prior_week(self):
        with patch("src.external_services.market_data.yf.download", return_value=_fake_yf_download([100, 101, 99, 102])):
            result = get_sp500_weekly_returns()
        # 4 input rows -> 3 pct_change rows (first has no prior close)
        assert len(result) == 3

    def test_returns_empty_df_on_fetch_failure(self):
        with patch("src.external_services.market_data.yf.download", side_effect=Exception("network down")):
            result = get_sp500_weekly_returns()
        assert result.empty
        assert list(result.columns) == ["week", "pct_return"]

    def test_returns_empty_df_when_download_returns_empty(self):
        with patch("src.external_services.market_data.yf.download", return_value=pd.DataFrame()):
            result = get_sp500_weekly_returns()
        assert result.empty
        assert list(result.columns) == ["week", "pct_return"]

    def test_week_column_is_period_dtype(self):
        with patch("src.external_services.market_data.yf.download", return_value=_fake_yf_download([100, 101, 99, 102])):
            result = get_sp500_weekly_returns()
        assert isinstance(result["week"].dtype, pd.PeriodDtype)

    def test_monday_indexed_bar_buckets_into_its_own_trading_week(self):
        # yfinance indexes weekly bars by that week's Monday; the W-FRI
        # period it lands in should be the same week (Mon-Fri), not a
        # neighboring one.
        with patch("src.external_services.market_data.yf.download", return_value=_fake_yf_download([100, 101], start="2026-02-02")):
            result = get_sp500_weekly_returns()
        assert str(result["week"].iloc[0]) == "2026-02-07/2026-02-13"

    def test_returns_empty_df_when_yfinance_unavailable(self):
        # e.g. running under Pyodide (marimo html-wasm export), where
        # yfinance's compiled curl_cffi dependency can't load at all.
        with patch("src.external_services.market_data.yf", None):
            result = get_sp500_weekly_returns()
        assert result.empty
        assert list(result.columns) == ["week", "pct_return"]


class TestGetSecurityInfo:
    def test_returns_ticker_info(self):
        with patch("src.external_services.market_data.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.info = {"quoteType": "ETF"}
            assert get_security_info("SPYD") == {"quoteType": "ETF"}

    def test_returns_empty_dict_on_failure(self):
        with patch("src.external_services.market_data.yf.Ticker", side_effect=Exception("network down")):
            assert get_security_info("SPYD") == {}

    def test_returns_empty_dict_when_yfinance_unavailable(self):
        with patch("src.external_services.market_data.yf", None):
            assert get_security_info("SPYD") == {}


class TestGetDividendHistory:
    def test_strips_timezone(self):
        index = pd.DatetimeIndex(["2026-01-02", "2026-04-01"]).tz_localize("America/New_York")
        with patch("src.external_services.market_data.yf.Ticker") as mock_ticker:
            mock_ticker.return_value.dividends = pd.Series([0.5, 0.6], index=index)
            dividends = get_dividend_history("DELL")
        assert dividends.index.tz is None
        assert list(dividends) == [0.5, 0.6]

    def test_failure_returns_empty_series_with_datetime_index(self):
        with patch("src.external_services.market_data.yf.Ticker", side_effect=Exception("network down")):
            dividends = get_dividend_history("DELL")
        assert dividends.empty
        assert isinstance(dividends.index, pd.DatetimeIndex)
