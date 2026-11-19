import pandas as pd
import pytest

from src.pnl_calculator import clean_currency, calculate_ytd_pnl, parse_history


class TestCleanCurrency:
    def test_removes_dollar_sign(self):
        assert clean_currency("$150.00") == 150.0

    def test_removes_commas(self):
        assert clean_currency("1,500.00") == 1500.0

    def test_removes_dollar_sign_and_commas(self):
        assert clean_currency("$1,500.00") == 1500.0

    def test_handles_negative_in_parentheses(self):
        assert clean_currency("($100.00)") == -100.0

    def test_handles_nan(self):
        assert clean_currency(float("nan")) == 0.0

    def test_handles_empty_string(self):
        assert clean_currency("") == 0.0

    def test_plain_number_string(self):
        assert clean_currency("42.5") == 42.5

    def test_zero_value(self):
        assert clean_currency("$0.00") == 0.0


def _row(action, symbol, qty, amount, date="2026-01-01"):
    return {
        "Run Date": pd.Timestamp(date),
        "Action": action,
        "Symbol": symbol,
        "Quantity": qty,
        "Price ($)": abs(amount) / qty if qty else 0,
        "Amount ($)": amount,
        "Fees ($)": 0.0,
        "Commission ($)": 0.0,
    }


class TestCalculateYtdPnl:
    def test_simple_buy_then_sell_profit(self):
        rows = [
            _row("YOU BOUGHT", "AAPL", 10, -1000.0, "2026-01-01"),
            _row("YOU SOLD", "AAPL", 10, 1500.0, "2026-06-01"),
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        assert len(realized) == 1
        assert len(missing) == 0
        assert realized[0]["gain_loss"] == pytest.approx(500.0)

    def test_simple_buy_then_sell_loss(self):
        rows = [
            _row("YOU BOUGHT", "MSFT", 5, -1000.0, "2026-01-01"),
            _row("YOU SOLD", "MSFT", 5, 900.0, "2026-06-01"),
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        assert len(realized) == 1
        assert realized[0]["gain_loss"] == pytest.approx(-100.0)

    def test_fifo_uses_oldest_lot_first(self):
        rows = [
            _row("YOU BOUGHT", "GOOG", 5, -500.0, "2026-01-01"),   # cost basis $100/share
            _row("YOU BOUGHT", "GOOG", 5, -1000.0, "2026-02-01"),  # cost basis $200/share
            _row("YOU SOLD", "GOOG", 5, 1250.0, "2026-06-01"),     # sells first lot (cost=$500)
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        assert len(realized) == 1
        assert realized[0]["gain_loss"] == pytest.approx(750.0)   # 1250 - 500

    def test_sell_spanning_two_lots(self):
        rows = [
            _row("YOU BOUGHT", "AMZN", 3, -300.0, "2026-01-01"),  # cost $100/share
            _row("YOU BOUGHT", "AMZN", 3, -600.0, "2026-02-01"),  # cost $200/share
            _row("YOU SOLD", "AMZN", 4, 800.0, "2026-06-01"),     # uses all of lot1 + 1 of lot2
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        # One match record per lot consumed: 3 shares @ $100 cost, then 1 share @ $200 cost
        assert len(realized) == 2
        assert realized[0]["qty"] == pytest.approx(3.0)
        assert realized[0]["gain_loss"] == pytest.approx(300.0)  # 3*200 - 3*100
        assert realized[1]["qty"] == pytest.approx(1.0)
        assert realized[1]["gain_loss"] == pytest.approx(0.0)  # 1*200 - 1*200
        assert sum(r["gain_loss"] for r in realized) == pytest.approx(300.0)

    def test_sell_without_prior_buy_goes_to_missing(self):
        rows = [
            _row("YOU SOLD", "TSLA", 3, 900.0, "2026-03-01"),
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        assert len(realized) == 0
        assert len(missing) == 1
        assert missing[0]["symbol"] == "TSLA"

    def test_partial_lot_sell_leaves_remainder(self):
        rows = [
            _row("YOU BOUGHT", "NVDA", 10, -1000.0, "2026-01-01"),
            _row("YOU SOLD", "NVDA", 4, 600.0, "2026-06-01"),
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        # cost for 4 shares = 4*100 = 400; proceeds = 600; gain = 200
        assert realized[0]["gain_loss"] == pytest.approx(200.0)

    def test_unrelated_actions_are_ignored(self):
        rows = [
            _row("DIVIDEND RECEIVED", "AAPL", 0.001, 5.0, "2026-01-15"),
            _row("YOU BOUGHT", "AAPL", 2, -200.0, "2026-01-01"),
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        assert realized == []
        assert missing == []

    def test_empty_dataframe_returns_empty_lists(self):
        df = pd.DataFrame(
            columns=["Run Date", "Action", "Symbol", "Quantity", "Price ($)", "Amount ($)", "Fees ($)", "Commission ($)"]
        )
        realized, missing = calculate_ytd_pnl(df)
        assert realized == []
        assert missing == []

    def test_multiple_symbols_tracked_independently(self):
        rows = [
            _row("YOU BOUGHT", "AAPL", 10, -1000.0, "2026-01-01"),
            _row("YOU BOUGHT", "MSFT", 5, -1000.0, "2026-01-01"),
            _row("YOU SOLD", "AAPL", 10, 1200.0, "2026-06-01"),
            _row("YOU SOLD", "MSFT", 5, 800.0, "2026-06-01"),
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        assert len(realized) == 2
        symbols = {r["symbol"] for r in realized}
        assert symbols == {"AAPL", "MSFT"}
        aapl = next(r for r in realized if r["symbol"] == "AAPL")
        msft = next(r for r in realized if r["symbol"] == "MSFT")
        assert aapl["gain_loss"] == pytest.approx(200.0)
        assert msft["gain_loss"] == pytest.approx(-200.0)

    def test_case_insensitive_action_matching(self):
        rows = [
            _row("you bought", "F", 100, -1000.0, "2026-01-01"),
            _row("you sold", "F", 100, 1100.0, "2026-06-01"),
        ]
        realized, missing = calculate_ytd_pnl(pd.DataFrame(rows))
        assert len(realized) == 1
        assert realized[0]["gain_loss"] == pytest.approx(100.0)

    def test_records_buy_and_sell_dates_and_per_share_prices(self):
        rows = [
            _row("YOU BOUGHT", "AAPL", 10, -1000.0, "2026-01-01"),
            _row("YOU SOLD", "AAPL", 10, 1500.0, "2026-06-01"),
        ]
        realized, _ = calculate_ytd_pnl(pd.DataFrame(rows))
        assert realized[0]["buy_date"] == pd.Timestamp("2026-01-01")
        assert realized[0]["sell_date"] == pd.Timestamp("2026-06-01")
        assert realized[0]["buy_price"] == pytest.approx(100.0)
        assert realized[0]["sell_price"] == pytest.approx(150.0)

    def test_pct_gain_reflects_per_share_return(self):
        rows = [
            _row("YOU BOUGHT", "AAPL", 10, -1000.0, "2026-01-01"),
            _row("YOU SOLD", "AAPL", 10, 1500.0, "2026-06-01"),
        ]
        realized, _ = calculate_ytd_pnl(pd.DataFrame(rows))
        assert realized[0]["pct_gain"] == pytest.approx(50.0)


class TestParseHistory:
    SAMPLE = (
        "Brokerage Statement\n"
        "Exported Jul-05-2026\n"
        'Run Date,Action,Symbol,Price ($),Quantity,Amount ($),Fees ($),Commission ($)\n'
        '01/01/2026,YOU BOUGHT AAPL,AAPL,"$100.00",10,"($1,000.00)",0,0\n'
        '06/01/2026,YOU SOLD AAPL,AAPL,"$150.00",-10,"$1,500.00",0,0\n'
        "\n"
        '"Disclaimer text that should be ignored"\n'
    )

    def test_locates_header_row_dynamically(self, tmp_path):
        csv_file = tmp_path / "history.csv"
        csv_file.write_text(self.SAMPLE)
        df = parse_history(csv_file)
        assert list(df.columns) == [
            "Run Date", "Action", "Symbol", "Price ($)", "Quantity", "Amount ($)", "Fees ($)", "Commission ($)"
        ]
        assert len(df) == 2

    def test_accepts_raw_bytes(self):
        df = parse_history(self.SAMPLE.encode("utf-8"))
        assert len(df) == 2

    def test_cleans_currency_columns(self, tmp_path):
        csv_file = tmp_path / "history.csv"
        csv_file.write_text(self.SAMPLE)
        df = parse_history(csv_file)
        assert df["Amount ($)"].tolist() == pytest.approx([-1000.0, 1500.0])

    def test_sorts_chronologically(self):
        df = parse_history(self.SAMPLE.encode("utf-8"))
        assert df["Run Date"].is_monotonic_increasing

    def test_same_day_buy_sorts_before_sell(self):
        sample = (
            "Preamble\n"
            'Run Date,Action,Symbol,Price ($),Quantity,Amount ($),Fees ($),Commission ($)\n'
            '01/01/2026,YOU SOLD AAPL,AAPL,"$150.00",-10,"$1,500.00",0,0\n'
            '01/01/2026,YOU BOUGHT AAPL,AAPL,"$100.00",10,"($1,000.00)",0,0\n'
        )
        df = parse_history(sample.encode("utf-8"))
        assert df["Action"].tolist() == ["YOU BOUGHT AAPL", "YOU SOLD AAPL"]
