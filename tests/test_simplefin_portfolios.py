import pandas as pd
import pytest
from unittest.mock import patch

from src import simplefin_portfolios as sp
from src.external_services.simplefin import PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS
from src.constants.portfolio_columns import RH_STOCK_COLUMNS, WF_COLUMNS

_INFO = {
    "SPYD": {"quoteType": "ETF", "dividendRate": 2.0},
    "DELL": {
        "quoteType": "EQUITY",
        "dividendRate": 1.6,
        "sector": "Technology",
        "industry": "Computer Hardware",
        "longBusinessSummary": "Dell makes computers.",
    },
    "VTI": {"quoteType": "ETF", "dividendRate": 3.0},
    "MSFT": {"quoteType": "EQUITY", "dividendRate": 3.0},
}

_DIVIDENDS = {
    "DELL": pd.Series(
        [0.4, 0.4, 0.5, 0.5],
        index=pd.to_datetime(["2025-04-01", "2025-10-01", "2026-04-01", "2026-09-01"]),
    ),
}

_TODAY = pd.Timestamp("2026-10-06")


@pytest.fixture(autouse=True)
def no_dividends(request):
    # The dividend step has its own tests in test_dividend_ledger.py
    with patch.object(sp, "_export_dividends") as mock_dividends:
        if request.instance is not None:
            request.instance.no_dividends = mock_dividends
        yield mock_dividends


@pytest.fixture(autouse=True)
def no_live_tabs():
    with patch.object(sp, "read_from_sheets", return_value=pd.DataFrame()):
        yield


@pytest.fixture(autouse=True)
def fake_market_data():
    sp._security_info.cache_clear()
    sp._dividends.cache_clear()
    with patch.object(
        sp, "get_security_info", side_effect=lambda s: _INFO.get(s, {})
    ), patch.object(
        sp,
        "get_dividend_history",
        side_effect=lambda s: _DIVIDENDS.get(s, pd.Series(dtype=float)),
    ):
        yield
    sp._security_info.cache_clear()
    sp._dividends.cache_clear()


def _holding(symbol, shares="10", market_value="1000.00", purchase_price="80.00"):
    return {
        "symbol": symbol,
        "description": f"{symbol} Inc",
        "shares": shares,
        "market_value": market_value,
        "cost_basis": "0",
        "purchase_price": purchase_price,
    }


def _account(org, name, holdings=None, balance="0.00", account_id=None):
    account = {"org": {"name": org}, "name": name, "balance": balance}
    if holdings is not None:
        account["holdings"] = holdings
    if account_id:
        account["id"] = account_id
    return account


def _all_accounts():
    return [
        _account(
            "Robinhood", "Crypto (8002)", [_holding("BTC", "0.5", "30000", "40000")]
        ),
        _account(
            "Robinhood",
            "Robinhood individual (8001)",
            [_holding("SPYD"), _holding("DELL")],
            balance="2100.00",
        ),
        _account("Wells Fargo", "Checking", []),
        _account("Wells Fargo", "Brokerage", [_holding("MSFT"), _holding("VTI")]),
        _account(
            "Wells Fargo",
            "BROKERAGE CASH",
            [],
            account_id=next(iter(PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS)),
        )
        | {"available-balance": "209.34"},
        _account("Fidelity Investments", "ROTH IRA", [_holding("NVDA")]),
        _account("Fidelity Investments", "Traditional IRA", [_holding("FZROX")]),
        _account("Bank of America", "Checking", []),
    ]


def _written(mock_write):
    return {c.args[1]: c.args[0] for c in mock_write.call_args_list}


class TestBuildRhStockDf:
    def test_columns_match_robinhood_pipeline(self):
        df = sp.build_rh_stock_df([_holding("DELL")], today=_TODAY)
        assert list(df.columns) == RH_STOCK_COLUMNS

    def test_maps_holding_and_enrichment(self):
        row = sp.build_rh_stock_df([_holding("DELL")], today=_TODAY).iloc[0]
        assert row["Ticker"] == "DELL"
        assert row["Name"] == "DELL Inc"
        assert row["Avg Price"] == pytest.approx(80.0)
        assert row["Quantity"] == pytest.approx(10.0)
        assert row["Total"] == pytest.approx(800.0)
        assert row["Diversity"] == pytest.approx(1.0)
        assert row["Sector"] == "Technology"
        assert row["Industry"] == "Computer Hardware"
        assert row["Description"] == "Dell makes computers."
        assert row["DVD Rate"] == pytest.approx(0.4)  # 1.6 annual / 4
        assert row["Projected DVD"] == pytest.approx(4.0)

    def test_dividend_estimates_use_current_shares(self):
        row = sp.build_rh_stock_df([_holding("DELL")], today=_TODAY).iloc[0]
        assert row["Last Quarterly Dividend"] == pytest.approx(5.0)  # 0.5 x 10
        assert row["Last Year's DVD"] == pytest.approx(8.0)  # (0.4 + 0.4) x 10
        assert row["YTD DVD"] == pytest.approx(10.0)  # (0.5 + 0.5) x 10
        assert row["Total DVD Paid"] == ""

    def test_sorted_by_total_descending_with_diversity(self):
        df = sp.build_rh_stock_df(
            [_holding("DELL", shares="1"), _holding("SPYD", shares="3")], today=_TODAY
        )
        assert list(df["Ticker"]) == ["SPYD", "DELL"]
        assert list(df["Diversity"]) == pytest.approx([0.75, 0.25])

    def test_empty_returns_headers_only(self):
        df = sp.build_rh_stock_df([])
        assert df.empty
        assert list(df.columns) == RH_STOCK_COLUMNS


class TestBuildRhCryptoDf:
    def test_maps_and_sorts_by_total(self):
        df = sp.build_rh_crypto_df(
            [
                _holding("ETH", "1", "3000", "2000"),
                _holding("BTC", "0.5", "30000", "40000"),
            ]
        )
        assert list(df.columns) == ["Ticker", "Name", "Avg Price", "Quantity", "Total"]
        assert list(df["Ticker"]) == ["BTC", "ETH"]
        assert df.iloc[0]["Total"] == pytest.approx(20000.0)


class TestBuildWfDf:
    def test_columns_and_dividend_math(self):
        df = sp.build_wf_df([_holding("MSFT", shares="10", market_value="4000")])
        assert list(df.columns) == [*WF_COLUMNS, "Dividend Portfolio"]
        row = df.iloc[0]
        assert row["Average Cost Basis"] == pytest.approx(80.0)
        assert row["Current Value"] == pytest.approx(4000.0)
        assert row["DVD Rate"] == pytest.approx(3.0)
        assert row["Est. Annual Yield"] == pytest.approx(0.0075)  # 3 / 400
        assert row["Projected DVD"] == pytest.approx(30.0)

    def test_unknown_symbol_has_zero_dividends(self):
        row = sp.build_wf_df([_holding("ZZZZ")]).iloc[0]
        assert row["DVD Rate"] == 0
        assert row["Projected DVD"] == 0


class TestDividendPortfolio:
    def test_ticked_symbols_are_ticked_and_the_rest_blank(self):
        df = sp.build_wf_df([_holding("MSFT"), _holding("AAPL")], {"MSFT"})
        assert dict(zip(df["Symbol"], df["Dividend Portfolio"])) == {
            "AAPL": "",
            "MSFT": True,
        }

    def test_reads_ticks_from_both_live_tabs(self):
        tabs = {
            # As read back: a checkbox comes as "TRUE", typed values vary
            "WF_stock_dump": pd.DataFrame(
                {
                    "Symbol": ["MSFT", "AAPL", "KO", "PEP"],
                    "Dividend Portfolio": ["TRUE", "FALSE", "x", ""],
                }
            ),
            "WF_etf_dump": pd.DataFrame(
                {"Symbol": ["SCHD"], "Dividend Portfolio": ["yes"]}
            ),
        }
        with patch.object(sp, "read_from_sheets", side_effect=tabs.get):
            ticked = sp._ticked_symbols(["WF_stock_dump", "WF_etf_dump"])
        assert ticked == {"MSFT", "KO", "SCHD"}

    def test_tab_without_the_column_has_none(self):
        with patch.object(
            sp, "read_from_sheets", return_value=pd.DataFrame({"Symbol": ["MSFT"]})
        ):
            assert sp._ticked_symbols(["WF_stock_dump"]) == set()

    def test_failed_read_leaves_the_tabs_untouched(self):
        # Writing without the ticks would wipe them, so the export stops
        accounts = [_account("Wells Fargo", "Brokerage", [_holding("MSFT")])]
        with patch.object(
            sp, "read_from_sheets", side_effect=Exception("503")
        ), patch.object(sp, "write_to_sheets") as mock_write:
            with pytest.raises(Exception, match="503"):
                sp._export_wells_fargo(accounts, sp._Writer(""))
        mock_write.assert_not_called()

    def test_ticks_survive_a_run(self, monkeypatch):
        monkeypatch.delenv("PORTFOLIO_TAB_SUFFIX", raising=False)
        live = pd.DataFrame({"Symbol": ["MSFT"], "Dividend Portfolio": ["TRUE"]})
        accounts = [
            _account("Wells Fargo", "Brokerage", [_holding("MSFT"), _holding("VTI")])
        ]
        with patch.object(sp, "read_from_sheets", return_value=live), patch.object(
            sp, "write_to_sheets"
        ) as mock_write:
            sp.export_portfolios_to_sheets(accounts)
        written = _written(mock_write)
        assert bool(written["WF_stock_dump"].iloc[0]["Dividend Portfolio"]) is True
        assert written["WF_etf_dump"].iloc[0]["Dividend Portfolio"] == ""


class TestBuildWfDfSymbolFallback:
    def test_missing_symbol_falls_back_to_description(self):
        holding = {**_holding("X"), "symbol": "", "description": "Restricted Fund"}
        row = sp.build_wf_df([holding]).iloc[0]
        assert row["Symbol"] == "Restricted Fund"
        assert row["Description"] == "Restricted Fund"


class TestBuildFidelityDf:
    def test_shape_matches_csv_pipeline(self):
        df = sp.build_fidelity_df([_holding("VTI"), _holding("AAPL")])
        assert list(df.columns) == sp._FIDELITY_COLUMNS
        assert list(df["Symbol"]) == ["AAPL", "VTI"]
        assert df.iloc[0]["Average Cost Basis"] == pytest.approx(80.0)
        assert df.iloc[0]["Current Stop Price"] == ""


class TestUninvestedCash:
    def test_balance_minus_holdings_value(self):
        account = _account(
            "Robinhood", "Individual", [_holding("A", market_value="900")], "1000.50"
        )
        assert sp.uninvested_cash([account]) == pytest.approx(100.50)


class TestExportPortfoliosToSheets:
    def _run(self, accounts, suffix=None, monkeypatch=None):
        with patch.object(sp, "write_to_sheets") as mock_write, patch.object(
            sp, "write_fidelity_positions_to_sheets"
        ) as mock_fidelity, patch.object(
            sp, "sync_fidelity_account_history_from_drive"
        ), patch.object(
            sp, "write_ytd_realized_pnl_to_sheets"
        ) as mock_ytd:
            sp.export_portfolios_to_sheets(accounts)
        return mock_write, mock_fidelity, mock_ytd

    def test_routes_each_account_to_its_tabs(self, monkeypatch):
        monkeypatch.delenv("PORTFOLIO_TAB_SUFFIX", raising=False)
        mock_write, mock_fidelity, mock_ytd = self._run(_all_accounts())
        written = _written(mock_write)

        assert set(written) == {
            "RH_stock_dump",
            "RH_etf_dump",
            "RH_cash_dump",
            "RH_crypto_dump",
            "WF_stock_dump",
            "WF_etf_dump",
            "WF_cash_dump",
        }
        assert list(written["RH_stock_dump"]["Ticker"]) == ["DELL"]
        assert list(written["RH_etf_dump"]["Ticker"]) == ["SPYD"]
        assert list(written["RH_crypto_dump"]["Ticker"]) == ["BTC"]
        assert written["RH_cash_dump"].iloc[0]["Available Cash"] == pytest.approx(100.0)
        assert list(written["WF_stock_dump"]["Symbol"]) == ["MSFT"]
        assert list(written["WF_etf_dump"]["Symbol"]) == ["VTI"]
        assert written["WF_cash_dump"].iloc[0]["Available Cash"] == pytest.approx(
            209.34
        )
        assert all(c.kwargs == {} for c in mock_write.call_args_list)

        fidelity_df, fidelity_tab = mock_fidelity.call_args.args
        assert list(fidelity_df["Symbol"]) == ["NVDA"]  # Roth only
        assert fidelity_tab == "fidelity_dump"
        mock_ytd.assert_called_once_with("fidelity_dump")
        self.no_dividends.assert_called_once()
        assert self.no_dividends.call_args.args[0] == _all_accounts()

    def test_preview_suffix_writes_new_tabs(self, monkeypatch):
        monkeypatch.setenv("PORTFOLIO_TAB_SUFFIX", "_preview")
        mock_write, mock_fidelity, mock_ytd = self._run(_all_accounts())

        assert all(name.endswith("_preview") for name in _written(mock_write))
        assert all(
            c.kwargs == {"create_if_missing": True} for c in mock_write.call_args_list
        )
        assert mock_fidelity.call_args.args[1] == "fidelity_dump_preview"
        assert mock_fidelity.call_args.kwargs == {"create_if_missing": True}
        mock_ytd.assert_called_once_with("fidelity_dump_preview")

    def test_missing_accounts_leave_tabs_untouched(self, monkeypatch):
        monkeypatch.delenv("PORTFOLIO_TAB_SUFFIX", raising=False)
        accounts = [
            _account(
                "Wells Fargo", "Brokerage", []
            ),  # holdings dropped by a refresh glitch
            _account("Bank of America", "Checking", []),
        ]
        mock_write, mock_fidelity, _ = self._run(accounts)

        mock_write.assert_not_called()
        mock_fidelity.assert_not_called()

    def test_one_institution_failing_still_runs_the_rest(self, monkeypatch):
        monkeypatch.delenv("PORTFOLIO_TAB_SUFFIX", raising=False)
        with patch.object(
            sp, "_export_robinhood", side_effect=ValueError("boom")
        ), patch.object(sp, "_export_wells_fargo") as mock_wf, patch.object(
            sp, "_export_fidelity"
        ) as mock_fid:
            with pytest.raises(RuntimeError, match="Robinhood"):
                sp.export_portfolios_to_sheets(_all_accounts())

        mock_wf.assert_called_once()
        mock_fid.assert_called_once()


class TestSplitStocksEtfs:
    def test_unknown_symbol_treated_as_stock(self):
        stocks, etfs = sp._split_stocks_etfs([_holding("SPYD"), _holding("ZZZZ")])
        assert [h["symbol"] for h in stocks] == ["ZZZZ"]
        assert [h["symbol"] for h in etfs] == ["SPYD"]

    def test_yfinance_outage_raises_instead_of_guessing(self):
        with pytest.raises(RuntimeError, match="yfinance"):
            sp._split_stocks_etfs([_holding("ZZZZ"), _holding("YYYY")])

    def test_outage_leaves_stock_and_etf_tabs_untouched(self, monkeypatch):
        monkeypatch.delenv("PORTFOLIO_TAB_SUFFIX", raising=False)
        accounts = [
            _account("Robinhood", "Crypto", [_holding("BTC")]),
            _account("Robinhood", "Individual", [_holding("QQQQ")], balance="1000"),
        ]
        with patch.object(sp, "write_to_sheets") as mock_write:
            with pytest.raises(RuntimeError):
                sp.export_portfolios_to_sheets(accounts)

        assert set(_written(mock_write)) == {"RH_crypto_dump", "RH_cash_dump"}


class TestHoldingsFilter:
    def test_drops_dead_positions_but_keeps_unpriced_ones(self):
        account = _account(
            "Wells Fargo",
            "WELLSTRADE",
            [
                # closed: 0 shares, $0 value (cost still reported)
                _holding("WDC", shares="0", market_value="0", purchase_price="100.00"),
                # escrow placeholder: shares but $0 value and $0 cost
                _holding("", shares="50", market_value="0", purchase_price="0"),
                # real position missing a quote: has a cost, so kept
                _holding("UNPRICED", shares="10", market_value="0"),
                # Robinhood crypto: value but no cost, so kept
                _holding("BTC", shares="0.1", market_value="9000", purchase_price="0"),
                _holding("AMD"),
            ],
        )
        assert [h["symbol"] for h in sp._holdings([account])] == [
            "UNPRICED",
            "BTC",
            "AMD",
        ]


class TestAnnualDividendRate:
    def test_falls_back_to_trailing_year_of_dividends(self):
        recent = pd.Timestamp.today().normalize()
        _INFO["ETFX"] = {"quoteType": "ETF"}
        _DIVIDENDS["ETFX"] = pd.Series(
            [0.5, 0.5, 9.0],
            index=[
                recent - pd.Timedelta(days=30),
                recent - pd.Timedelta(days=120),
                recent - pd.Timedelta(days=500),
            ],
        )
        try:
            assert sp._annual_dividend_rate("ETFX") == pytest.approx(1.0)
        finally:
            del _INFO["ETFX"], _DIVIDENDS["ETFX"]


class TestKnownCosts:
    def test_reads_formatted_costs_from_live_tabs(self):
        live = pd.DataFrame(
            {"Ticker": ["BTC", "DOGE"], "Avg Price": ["$50,000.00", "$0.00"]}
        )
        with patch.object(sp, "read_from_sheets", return_value=live):
            costs = sp._known_costs(["RH_crypto_dump"], "Ticker", "Avg Price")
        assert costs == {"BTC": pytest.approx(50000.0)}

    def test_unreadable_tab_is_skipped(self):
        with patch.object(sp, "read_from_sheets", side_effect=Exception("boom")):
            assert sp._known_costs(["RH_crypto_dump"], "Ticker", "Avg Price") == {}

    def test_fills_only_holdings_without_a_cost(self):
        holdings = [
            _holding("BTC", purchase_price="0"),
            _holding("ETH", purchase_price="2000"),
        ]
        filled = sp._with_known_costs(holdings, {"BTC": 50000.0, "ETH": 1.0})
        assert [_h["purchase_price"] for _h in filled] == [50000.0, "2000"]
        assert holdings[0]["purchase_price"] == "0"  # input not mutated

    def test_crypto_tab_keeps_last_known_cost(self, monkeypatch):
        monkeypatch.setenv("PORTFOLIO_TAB_SUFFIX", "_preview")
        live = pd.DataFrame({"Ticker": ["BTC"], "Avg Price": ["$50,000.00"]})
        accounts = [
            _account("Robinhood", "Crypto", [_holding("BTC", "0.1", "9000", "0")])
        ]
        with patch.object(
            sp, "read_from_sheets", return_value=live
        ) as mock_read, patch.object(sp, "write_to_sheets") as mock_write:
            sp.export_portfolios_to_sheets(accounts)

        mock_read.assert_called_once_with("RH_crypto_dump")  # live tab, not preview
        row = _written(mock_write)["RH_crypto_dump_preview"].iloc[0]
        assert row["Avg Price"] == pytest.approx(50000.0)
        assert row["Total"] == pytest.approx(5000.0)
