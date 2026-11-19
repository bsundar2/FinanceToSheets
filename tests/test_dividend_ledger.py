import datetime
import re
from datetime import date
from unittest.mock import patch

import openpyxl
import pandas as pd
import pytest

from src import dividend_ledger as dl
from src import simplefin_portfolios as sp
from tests.test_budget_template import _has_calc, _recalculate

_JUL_15 = 1784073600  # 2026-07-15 UTC
_AUG_31 = 1788134400  # 2026-08-31 UTC


def _txn(txn_id, posted, amount, description, **extra):
    return {
        "id": txn_id,
        "posted": posted,
        "amount": amount,
        "description": description,
        **extra,
    }


def _account(org, name, transactions, holdings=None):
    account = {"org": {"name": org}, "name": name, "transactions": transactions}
    if holdings is not None:
        account["holdings"] = holdings
    return account


class TestFidelityDividend:
    def test_symbol_from_last_parenthesized_group(self):
        assert (
            dl.fidelity_dividend(
                "DIVIDEND RECEIVED COCA-COLA CO COM (KO) (Cash)", 2.0
            )
            == "KO"
        )

    @pytest.mark.parametrize(
        "description",
        [
            "REINVESTMENT FIDELITY GOVERNMENT MONEY MARKET (SPAXX) (Cash)",
            "YOU BOUGHT 10X GENOMICS INC CL A COM (TXG) (Cash)",
        ],
    )
    def test_non_dividends(self, description):
        assert dl.fidelity_dividend(description, 12.0) is None


class TestWellsFargoDividend:
    @pytest.mark.parametrize(
        "description, security",
        [
            ("MICROSOFT CORP 100126         100", "MICROSOFT CORP"),
            (
                "PUBLIC STORAGE REIT INC 093026          50",
                "PUBLIC STORAGE REIT INC",
            ),
            ("TARGET CORP NEW COM 080726           10", "TARGET CORP NEW COM"),
            (  # pay date partly masked by SimpleFIN
                "BERKSHIRE HATHAWAY INC DEL CL B XXX426           5",
                "BERKSHIRE HATHAWAY INC DEL CL B",
            ),
        ],
    )
    def test_dividend_credit(self, description, security):
        assert dl.wells_fargo_dividend(description, 25.0) == security

    @pytest.mark.parametrize(
        "description, amount",
        [
            ("MICROSOFT CORP", -25.0),  # the matching reinvestment
            ("MICROSOFT CORP 100126         100", -25.0),
            ("ORACLE CORP", 1000.0),  # a sale
            ("BANK DEPOSIT SWEEP 093026           24", 0.05),  # sweep interest
            ("AUTOMATED CREDIT", 2000.0),
            ("SPDR S&P 500 ETF TR", 0.0),
        ],
    )
    def test_non_dividends(self, description, amount):
        assert dl.wells_fargo_dividend(description, amount) is None


class TestExtractDividends:
    def test_tags_institution_and_skips_pending(self):
        account = _account(
            "Wells Fargo",
            "WELLSTRADE ...8888",
            [
                _txn("T1", _AUG_31, "12.50", "MERCK & CO INC 081426          20"),
                _txn("T2", _AUG_31, "-12.50", "MERCK & CO INC"),
                _txn("T3", _AUG_31, "5.00", "FOO CORP 090126 1", pending=True),
            ],
        )

        df = dl.extract_dividends([account], "Wells Fargo", dl.wells_fargo_dividend)

        assert list(df.columns) == dl.LEDGER_COLUMNS
        assert df.to_dict("records") == [
            {
                "Transaction ID": "T1",
                "Posted": "2026-08-31",
                "Institution": "Wells Fargo",
                "Account Name": "WELLSTRADE ...8888",
                "Security": "MERCK & CO INC",
                "Description": "MERCK & CO INC 081426          20",
                "Amount": 12.5,
                "Symbol": "",
            }
        ]

    def test_fidelity_amount_is_absolute(self):
        account = _account(
            "Fidelity Investments",
            "ROTH IRA",
            [_txn("T1", _JUL_15, "-3.00", "DIVIDEND RECEIVED X (SPAXX) (Cash)")],
        )
        df = dl.extract_dividends([account], "Fidelity", dl.fidelity_dividend)
        assert df.iloc[0]["Amount"] == pytest.approx(3.0)


class TestMergeLedger:
    def _rows(self, *rows):
        return pd.DataFrame([[*r, ""] for r in rows], columns=dl.LEDGER_COLUMNS)

    def test_first_run_creates_ledger(self):
        new = self._rows(["T1", "2026-07-15", "Fidelity", "ROTH", "KO", "d", 2.0])
        assert list(dl.merge_ledger(pd.DataFrame(), new)["Transaction ID"]) == ["T1"]

    def test_appends_only_unseen_ids_and_keeps_manual_rows(self):
        # As read back from Sheets: formatted strings, plus a hand-added seed
        existing = pd.DataFrame(
            {
                "Transaction ID": ["T2", "SEED-WF"],
                "Posted": ["2026-08-31", "7/20/2026"],
                "Institution": ["Wells Fargo", "Wells Fargo"],
                "Account Name": ["WELLSTRADE", ""],
                "Security": ["MERCK & CO INC", ""],
                "Description": ["d", "YTD through 7/20 from WellsTrade"],
                "Amount": ["$12.50", "$1,500.00"],
            }
        )
        new = self._rows(
            ["T2", "2026-08-31", "Wells Fargo", "WELLSTRADE", "MERCK & CO INC", "d", 99.0],
            ["T1", "2026-09-30", "Wells Fargo", "WELLSTRADE", "MICROSOFT CORP", "d", 25.0],
        )

        merged = dl.merge_ledger(existing, new)

        assert list(merged["Transaction ID"]) == ["SEED-WF", "T2", "T1"]
        assert list(merged["Amount"]) == pytest.approx([1500.0, 12.5, 25.0])


_HOLDINGS = [
    {"symbol": "TGT", "description": "Target Corp"},
    {"symbol": "PFE", "description": "Pfizer Inc"},
    {"symbol": "MSFT", "description": "Microsoft Corp"},
    {"symbol": "MU", "description": "Micron Technology Inc"},
    {"symbol": "XOM", "description": "Exxon Mobil Corp"},
    {"symbol": "CVX", "description": "Chevron Corp"},
    {"symbol": "BMO", "description": "Bank of Montreal"},
    {"symbol": "BNS", "description": "Bank of Nova Scotia"},
]


class TestMatchSymbol:
    @pytest.mark.parametrize(
        "security, symbol",
        [
            ("TARGET CORP NEW COM", "TGT"),  # WellsTrade adds suffixes
            ("PFIZER INC", "PFE"),
            ("MICROSOFT CORP", "MSFT"),
            ("CHEVRON CORP NEW", "CVX"),
            ("BANK OF MONTREAL", "BMO"),  # narrowed by later words
            ("BANK OF NOVA SCOTIA", "BNS"),
        ],
    )
    def test_matches_by_leading_words(self, security, symbol):
        assert dl.match_symbol(security, _HOLDINGS) == symbol

    def test_no_holding_left_is_blank(self):
        # Sold, so no longer among the holdings
        assert dl.match_symbol("BERKSHIRE HATHAWAY INC DEL CL B", _HOLDINGS) == ""

    def test_still_ambiguous_is_blank(self):
        holdings = [
            {"symbol": "A", "description": "Acme Corp"},
            {"symbol": "B", "description": "Acme Corp"},
        ]
        assert dl.match_symbol("ACME CORP", holdings) == ""


class TestWithSymbols:
    def test_fills_blanks_and_keeps_what_is_there(self):
        ledger = pd.DataFrame(
            [
                ["T1", "2026-07-15", "Fidelity", "ROTH", "KO", "d", 2.0, "KO"],
                ["T2", "2026-08-07", "Wells Fargo", "WT", "TARGET CORP NEW", "d", 10.0, ""],
                ["T3", "2026-09-14", "Wells Fargo", "WT", "BERKSHIRE HATHAWAY", "d", 1.0, "BRK.B"],
                ["T4", "2026-09-14", "Wells Fargo", "WT", "UNKNOWN CO", "d", 2.0, ""],
            ],
            columns=dl.LEDGER_COLUMNS,
        )
        out = dl.with_symbols(ledger, _HOLDINGS)
        # T3's was typed by hand; T4 has no holding to match
        assert list(out["Symbol"]) == ["KO", "TGT", "BRK.B", ""]


class TestSummaryCells:
    def _ledger(self):
        return pd.DataFrame(
            [
                ["T1", "2025-12-31", "Wells Fargo", "WT (8888)", "X", "d", 50.0, "TGT"],
                ["T2", "2026-08-31", "Wells Fargo", "WT (8888)", "X", "d", 12.5, "MRK"],
                ["T3", "2026-09-30", "Fidelity", "ROTH IRA (9999)", "X", "d", 3.0, "SPAXX"],
            ],
            columns=dl.LEDGER_COLUMNS,
        )

    def test_a_column_per_account_then_total(self):
        cells = dl.summary_cells(self._ledger())
        assert [cells["A2"], cells["A3"], cells["A4"]] == ["Dividends", "YTD", "All time"]
        assert [cells["B2"], cells["C2"], cells["D2"]] == [
            "Fidelity · ROTH IRA (9999)",
            "Wells Fargo · WT (8888)",
            "Total",
        ]
        assert cells["C4"] == (
            '=SUMIFS($G$7:$G,$C$7:$C,"Wells Fargo",$D$7:$D,"WT (8888)")'
        )

    def test_wildcards_and_quotes_in_names_match_literally(self):
        assert dl._criterion('A*B?C~"D"') == '"A~*B~?C~~""D"""'

    @pytest.mark.skipif(not _has_calc(), reason="needs LibreOffice Calc")
    def test_totals_recalculate(self, tmp_path):
        ledger = self._ledger()
        wb = openpyxl.Workbook()
        ws = wb.active
        last = dl.FIRST_ROW + len(ledger) - 1
        for offset, row in enumerate(ledger.itertuples(index=False)):
            for col, value in enumerate(row, start=1):
                if col == 2:
                    value = datetime.date.fromisoformat(value)
                ws.cell(row=dl.FIRST_ROW + offset, column=col, value=value)
        for cell, value in dl.summary_cells(ledger).items():
            # Bounded ranges: LibreOffice reads "G7:G" as a whole-row range
            ws[cell] = re.sub(r"(\$7:\$[A-Z])(?!\$?\d)", rf"\g<1>{last}", value)
        # TODAY() is the real date, so the YTD row only counts this year
        this_year = datetime.date.today().year
        calc = _recalculate(wb, tmp_path).active

        assert [calc[f"{c}4"].value for c in "BCD"] == pytest.approx(
            [3.0, 62.5, 65.5]
        )
        assert calc["D3"].value == pytest.approx(
            sum(r.Amount for r in ledger.itertuples() if r.Posted.startswith(str(this_year)))
        )


class TestYtdDividends:
    def test_sums_this_year_for_one_institution(self):
        ledger = pd.DataFrame(
            [
                ["T0", "2025-12-31", "Wells Fargo", "", "", "", 50.0, ""],
                ["T1", "2026-08-31", "Wells Fargo", "", "", "", 12.5, ""],
                ["T2", "2026-09-30", "Wells Fargo", "", "", "", 25.0, ""],
                ["T3", "2026-09-30", "Fidelity", "", "", "", 3.0, ""],
            ],
            columns=dl.LEDGER_COLUMNS,
        )
        assert dl.ytd_dividends(
            ledger, "Wells Fargo", today=date(2026, 10, 6)
        ) == pytest.approx(37.5)
        assert dl.ytd_dividends(
            ledger, "Fidelity", today=date(2026, 10, 6)
        ) == pytest.approx(3.0)


class TestIsoDate:
    @pytest.mark.parametrize(
        "value",
        [_JUL_15, "2026-07-15", "7/15/2026", 46218],  # unix, ISO, US, Sheets serial
    )
    def test_normalizes_every_form(self, value):
        assert dl._iso_date(value) == "2026-07-15"

    def test_blank_is_empty(self):
        assert dl._iso_date("") == ""


def _all_accounts():
    return [
        _account(
            "Wells Fargo",
            "WELLSTRADE ...8888",
            [_txn("W1", _AUG_31, "12.50", "MERCK & CO INC 081426          20")],
            holdings=[{"symbol": "MRK", "description": "Merck & Co Inc"}],
        ),
        _account(  # checking: never scanned for dividends
            "Wells Fargo",
            "EVERYDAY CHECKING",
            [_txn("W2", _AUG_31, "10.00", "SOMETHING 081426 1")],
            holdings=[],
        ),
        _account(
            "Fidelity Investments",
            "ROTH IRA",
            [_txn("F1", _JUL_15, "2.00", "DIVIDEND RECEIVED K (KO) (Cash)")],
        ),
    ]


class TestExportDividends:
    def test_merges_live_ledger_and_writes_ytd_cells(self):
        writer = sp._Writer("_preview")
        with patch.object(
            sp, "read_from_sheets", return_value=pd.DataFrame()
        ) as mock_read, patch.object(sp, "write_to_sheets") as mock_write, patch.object(
            sp, "write_cell_to_sheets"
        ) as mock_cell, patch.object(
            sp, "write_cells_to_sheets"
        ) as mock_cells, patch.object(
            dl, "date"
        ) as mock_date:
            mock_date.today.return_value = date(2026, 10, 6)
            sp._export_dividends(_all_accounts(), writer)

        # The live ledger, its header found under the summary
        mock_read.assert_called_once_with(
            "dividends_ledger", header_label="Transaction ID"
        )
        ledger, tab = mock_write.call_args.args
        assert tab == "dividends_ledger_preview"
        assert mock_write.call_args.kwargs == {
            "create_if_missing": True,
            "start": (6, 1),
        }
        assert list(ledger["Transaction ID"]) == ["F1", "W1"]
        assert list(ledger["Symbol"]) == ["KO", "MRK"]
        summary, summary_tab = mock_cells.call_args.args
        assert summary_tab == "dividends_ledger_preview"
        assert summary["B2"] == "Fidelity · ROTH IRA"
        assert summary["C2"] == "Wells Fargo · WELLSTRADE ...8888"
        assert summary["D2"] == "Total"
        assert [c.args for c in mock_cell.call_args_list] == [
            ("YTD Dividends", "J1", "WF_stock_dump_preview"),
            (pytest.approx(12.5), "K1", "WF_stock_dump_preview"),
            ("YTD Dividends", "L2", "fidelity_dump_preview"),
            (pytest.approx(2.0), "M2", "fidelity_dump_preview"),
        ]

    def test_failed_ledger_read_raises_without_writing(self):
        with patch.object(
            sp, "read_from_sheets", side_effect=Exception("503")
        ), patch.object(sp, "write_to_sheets") as mock_write:
            with pytest.raises(Exception, match="503"):
                sp._export_dividends(_all_accounts(), sp._Writer(""))
        mock_write.assert_not_called()

    def test_runs_after_the_brokerage_tabs(self):
        calls = []
        with patch.object(
            sp, "_export_robinhood", side_effect=lambda *a: calls.append("rh")
        ), patch.object(
            sp, "_export_wells_fargo", side_effect=lambda *a: calls.append("wf")
        ), patch.object(
            sp, "_export_fidelity", side_effect=lambda *a: calls.append("fid")
        ), patch.object(
            sp, "_export_dividends", side_effect=lambda *a: calls.append("div")
        ):
            sp.export_portfolios_to_sheets([])
        assert calls == ["rh", "wf", "fid", "div"]
