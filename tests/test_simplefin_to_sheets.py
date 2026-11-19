import pandas as pd
import pytest
from datetime import date
from unittest.mock import patch

from src.external_services.simplefin import _split_auth, get_bank_accounts, get_transactions
from src.simplefin_to_sheets import (
    get_bank_accounts_as_df,
    get_holdings_as_df,
    export_bank_accounts_to_sheets,
    _OUTPUT_COLUMNS,
    _HOLDINGS_OUTPUT_COLUMNS,
    _PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS,
)


def _account(name, org_name, balance, balance_date=1735689600):
    return {
        "name": name,
        "balance": balance,
        "balance-date": balance_date,
        "org": {"name": org_name},
    }


class TestSplitAuth:
    def test_extracts_credentials_embedded_in_url(self):
        base_url, auth = _split_auth(
            "https://user:pass@bridge.simplefin.org/access/accounts"
        )
        assert base_url == "https://bridge.simplefin.org/access/accounts"
        assert auth == ("user", "pass")

    def test_no_credentials_returns_none_auth(self):
        base_url, auth = _split_auth("https://bridge.simplefin.org/access/accounts")
        assert base_url == "https://bridge.simplefin.org/access/accounts"
        assert auth is None


class TestGetBankAccounts:
    def test_returns_accounts_from_response(self):
        response_json = {
            "accounts": [_account("Checking", "Bank", 100.0)],
            "errlist": [],
        }

        with patch("src.external_services.simplefin.requests.get") as mock_get:
            mock_get.return_value.json.return_value = response_json
            mock_get.return_value.raise_for_status.return_value = None

            accounts = get_bank_accounts(
                "https://user:pass@bridge.simplefin.org/access"
            )

        assert accounts == response_json["accounts"]

    def test_logs_warning_for_errlist_entries_without_raising(self, caplog):
        response_json = {"accounts": [], "errlist": ["some-account: refresh failed"]}

        with patch("src.external_services.simplefin.requests.get") as mock_get:
            mock_get.return_value.json.return_value = response_json
            mock_get.return_value.raise_for_status.return_value = None

            with caplog.at_level("WARNING"):
                get_bank_accounts("https://user:pass@bridge.simplefin.org/access")

        assert "refresh failed" in caplog.text

    def test_requests_accounts_endpoint_with_parsed_auth(self):
        with patch("src.external_services.simplefin.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"accounts": []}
            mock_get.return_value.raise_for_status.return_value = None

            get_bank_accounts("https://user:pass@bridge.simplefin.org/access")

            mock_get.assert_called_once_with(
                "https://bridge.simplefin.org/access/accounts", auth=("user", "pass")
            )


class TestGetTransactions:
    def test_flattens_transactions_with_account_context(self):
        response_json = {
            "accounts": [
                {
                    "id": "ACT-1",
                    "name": "Joint Savings",
                    "transactions": [
                        {"id": "TRN-1", "posted": 123, "amount": "10.00", "description": "Deposit"}
                    ],
                }
            ]
        }

        with patch("src.external_services.simplefin.requests.get") as mock_get:
            mock_get.return_value.json.return_value = response_json
            mock_get.return_value.raise_for_status.return_value = None

            txns = get_transactions(
                "https://user:pass@bridge.simplefin.org/access", ["ACT-1"], 100
            )

        assert txns == [
            {
                "id": "TRN-1",
                "posted": 123,
                "amount": "10.00",
                "description": "Deposit",
                "account_id": "ACT-1",
                "account_name": "Joint Savings",
            }
        ]

    def test_skips_pending_transactions(self):
        response_json = {
            "accounts": [
                {
                    "id": "ACT-1",
                    "name": "Joint Savings",
                    "transactions": [
                        {"id": "TRN-1", "posted": 123, "amount": "10.00", "description": "Deposit", "pending": True},
                        {"id": "TRN-2", "posted": 124, "amount": "5.00", "description": "Posted"},
                    ],
                }
            ]
        }

        with patch("src.external_services.simplefin.requests.get") as mock_get:
            mock_get.return_value.json.return_value = response_json
            mock_get.return_value.raise_for_status.return_value = None

            txns = get_transactions(
                "https://user:pass@bridge.simplefin.org/access", ["ACT-1"], 100
            )

        assert [t["id"] for t in txns] == ["TRN-2"]

    def test_requests_with_start_date_and_account_params(self):
        with patch("src.external_services.simplefin.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"accounts": []}
            mock_get.return_value.raise_for_status.return_value = None

            get_transactions(
                "https://user:pass@bridge.simplefin.org/access",
                ["ACT-1", "ACT-2"],
                100,
            )

            mock_get.assert_called_once_with(
                "https://bridge.simplefin.org/access/accounts",
                auth=("user", "pass"),
                params=[("start-date", 100), ("account", "ACT-1"), ("account", "ACT-2")],
            )


class TestGetBankAccountsAsDf:
    def test_maps_accounts_to_expected_columns(self):
        accounts = [_account("Checking", "Bank of America", 110.65)]

        df = get_bank_accounts_as_df(accounts)

        assert list(df.columns) == _OUTPUT_COLUMNS
        row = df.iloc[0]
        assert row["Institution"] == "Bank of America"
        assert row["Account Name"] == "Checking"
        assert row["Balance"] == pytest.approx(110.65)
        assert row["Balance As Of"] == date(2025, 1, 1)

    def test_sorted_by_institution_then_account_name(self):
        accounts = [
            _account("Savings", "Zeta Bank", 1.0),
            _account("Checking", "Acme Bank", 2.0),
            _account("Savings", "Acme Bank", 3.0),
        ]

        df = get_bank_accounts_as_df(accounts)

        assert list(zip(df["Institution"], df["Account Name"])) == [
            ("Acme Bank", "Checking"),
            ("Acme Bank", "Savings"),
            ("Zeta Bank", "Savings"),
        ]

    def test_skips_accounts_with_no_balance(self):
        accounts = [
            _account("Checking", "Bank", 100.0),
            {**_account("Broken", "Bank", None), "balance": None},
        ]

        df = get_bank_accounts_as_df(accounts)

        assert list(df["Account Name"]) == ["Checking"]

    def test_no_accounts_returns_empty_df_with_columns(self):
        df = get_bank_accounts_as_df([])

        assert df.empty
        assert list(df.columns) == _OUTPUT_COLUMNS

    def test_uses_available_balance_for_allowlisted_account(self):
        allowlisted_id = next(iter(_PREFER_AVAILABLE_BALANCE_ACCOUNT_IDS))
        account = _account("Brokerage Cash", "Wells Fargo", "0.00")
        account["id"] = allowlisted_id
        account["available-balance"] = "209.34"

        df = get_bank_accounts_as_df([account])

        assert df.iloc[0]["Balance"] == pytest.approx(209.34)

    def test_non_allowlisted_zero_balance_account_is_not_overridden(self):
        account = _account("Paid Off Card", "Some Bank", "0.00")
        account["id"] = "ACT-not-on-the-allowlist"
        account["available-balance"] = "10000.00"

        df = get_bank_accounts_as_df([account])

        assert df.iloc[0]["Balance"] == pytest.approx(0.0)


def _holding(symbol, shares="10", market_value="1000.00", cost_basis="800.00"):
    return {
        "id": f"HOL-{symbol}",
        "symbol": symbol,
        "description": f"{symbol} Inc",
        "shares": shares,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "purchase_price": "80.00",
        "currency": "USD",
    }


class TestGetHoldingsAsDf:
    def test_maps_holdings_to_expected_columns(self):
        account = _account("Roth IRA", "Fidelity", "5000.00")
        account["holdings"] = [_holding("VTI")]

        df = get_holdings_as_df([account])

        assert list(df.columns) == _HOLDINGS_OUTPUT_COLUMNS
        row = df.iloc[0]
        assert row["Institution"] == "Fidelity"
        assert row["Account Name"] == "Roth IRA"
        assert row["Symbol"] == "VTI"
        assert row["Description"] == "VTI Inc"
        assert row["Shares"] == pytest.approx(10.0)
        assert row["Market Value"] == pytest.approx(1000.0)
        assert row["Cost Basis (raw)"] == pytest.approx(800.0)
        assert row["Purchase Price (raw)"] == pytest.approx(80.0)
        assert row["Currency"] == "USD"
        assert row["As Of"] == date(2025, 1, 1)

    def test_one_row_per_holding_sorted_across_accounts(self):
        wf = _account("Brokerage", "Wells Fargo", "1.00")
        wf["holdings"] = [_holding("MSFT"), _holding("AAPL")]
        rh = _account("Individual", "Robinhood", "1.00")
        rh["holdings"] = [_holding("BTC")]

        df = get_holdings_as_df([wf, rh])

        assert list(zip(df["Institution"], df["Symbol"])) == [
            ("Robinhood", "BTC"),
            ("Wells Fargo", "AAPL"),
            ("Wells Fargo", "MSFT"),
        ]

    def test_accounts_without_holdings_contribute_no_rows(self):
        checking = _account("Checking", "Bank", "100.00")
        empty = _account("Brokerage", "Broker", "0.00")
        empty["holdings"] = []

        df = get_holdings_as_df([checking, empty])

        assert df.empty
        assert list(df.columns) == _HOLDINGS_OUTPUT_COLUMNS

    def test_blank_or_malformed_numbers_become_none(self):
        account = _account("Brokerage", "Broker", "1.00")
        account["holdings"] = [
            {**_holding("XYZ"), "cost_basis": "", "market_value": "n/a"}
        ]
        del account["holdings"][0]["purchase_price"]

        row = get_holdings_as_df([account]).iloc[0]

        assert pd.isna(row["Cost Basis (raw)"])
        assert pd.isna(row["Market Value"])
        assert pd.isna(row["Purchase Price (raw)"])
        assert row["Shares"] == pytest.approx(10.0)

    def test_logs_counts_without_account_names_or_symbols(self, caplog):
        with_holdings = _account("Secret Account ...1234", "Fidelity", "1.00")
        with_holdings["holdings"] = [_holding("VTI"), _holding("VXUS")]
        without = _account("Checking ...5678", "Bank", "1.00")

        with caplog.at_level("INFO"):
            get_holdings_as_df([with_holdings, without])

        assert "Fidelity: account has 2 holdings" in caplog.text
        assert "Bank: account has no holdings field" in caplog.text
        assert "1234" not in caplog.text
        assert "5678" not in caplog.text
        assert "VTI" not in caplog.text


class TestExportBankAccountsToSheets:
    def test_skips_export_when_access_url_unset(self, monkeypatch):
        monkeypatch.delenv("SIMPLEFIN_ACCESS_URL", raising=False)

        with patch("src.simplefin_to_sheets.get_bank_accounts") as mock_get, patch(
            "src.simplefin_to_sheets.write_to_sheets"
        ) as mock_write:
            export_bank_accounts_to_sheets()

        mock_get.assert_not_called()
        mock_write.assert_not_called()

    def test_fetches_once_and_writes_balances_holdings_then_portfolios(
        self, monkeypatch
    ):
        monkeypatch.setenv(
            "SIMPLEFIN_ACCESS_URL", "https://user:pass@bridge.simplefin.org/access"
        )
        account = _account("Roth IRA", "Fidelity", "1000.00")
        account["holdings"] = [_holding("VTI")]

        with patch(
            "src.simplefin_to_sheets.get_bank_accounts", return_value=[account]
        ) as mock_get, patch(
            "src.simplefin_to_sheets.write_to_sheets"
        ) as mock_write, patch(
            "src.simplefin_to_sheets.export_portfolios_to_sheets"
        ) as mock_portfolios:
            export_bank_accounts_to_sheets()

        mock_portfolios.assert_called_once_with([account])

        mock_get.assert_called_once()
        assert mock_get.call_args.args == (
            "https://user:pass@bridge.simplefin.org/access",
        )
        start = mock_get.call_args.kwargs["start_date"]
        assert (date.today() - start).days == 90
        balances_call, holdings_call = mock_write.call_args_list

        pd.testing.assert_frame_equal(
            balances_call.args[0], get_bank_accounts_as_df([account])
        )
        assert balances_call.args[1] == "bank_accounts_dump"
        assert balances_call.kwargs == {}

        pd.testing.assert_frame_equal(
            holdings_call.args[0], get_holdings_as_df([account])
        )
        assert holdings_call.args[1] == "holdings_dump"
        assert holdings_call.kwargs == {"create_if_missing": True}


class TestGetBankAccountsStartDate:
    def test_passes_start_date_as_unix_timestamp(self):
        with patch("src.external_services.simplefin.requests.get") as mock_get:
            mock_get.return_value.json.return_value = {"accounts": []}
            mock_get.return_value.raise_for_status.return_value = None

            get_bank_accounts(
                "https://user:pass@bridge.simplefin.org/access",
                start_date=date(2026, 1, 1),
            )

            mock_get.assert_called_once_with(
                "https://bridge.simplefin.org/access/accounts",
                auth=("user", "pass"),
                params={"start-date": 1767225600},
            )
