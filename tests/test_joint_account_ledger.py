import pandas as pd
import pytest
from unittest.mock import patch

import re

import openpyxl

from src.joint_account_ledger import (
    classify_transaction,
    get_new_transactions_as_df,
    build_ledger_df,
    build_balance_columns_df,
    export_joint_account_ledger_to_sheets,
    JOINT_ACCOUNT_IDS,
    _OUTPUT_COLUMNS,
    FIRST_ROW,
    summary_cells,
)
from tests.test_budget_template import _has_calc, _recalculate


class TestClassifyTransaction:
    def test_interest_keyword_wins_over_everything(self):
        assert classify_transaction("August interest") == "Interest"
        assert classify_transaction("INTEREST PAYMENT") == "Interest"

    def test_matches_joint_account_transfer(self):
        assert (
            classify_transaction("Big Bank (Account ****2222)") == "Joint Internal"
        )
        assert (
            classify_transaction("Instant Pmt from ONLINE BANK LLC")
            == "Joint Internal"
        )

    def test_matches_personal_account_transfer(self):
        assert (
            classify_transaction(
                "ONLINE TRANSFER FROM CREDIT UNION CHK XXXXXX3333 A. EXAMPLE"
            )
            == "Mine"
        )
        assert (
            classify_transaction("TRANSFER TO EXAMPLE A PREMIER CHECKING XXXXXX4444")
            == "Mine"
        )

    def test_matches_my_payroll_deposit(self):
        assert (
            classify_transaction(
                "Acme Corp        PAYROLL    190101       XXXXX0001 Example,Alex"
            )
            == "Mine"
        )

    def test_matches_spouse_payroll_deposit(self):
        assert (
            classify_transaction(
                "GLOBEX INC       PAYROLL    XXXXXX XXXXXXXX0002NFT SAMPLE,SAM"
            )
            == "Spouse"
        )

    def test_matches_spouse_account_transfer(self):
        assert classify_transaction("Credit Union (Account ****7777)") == "Spouse"

    def test_matches_shared_bill(self):
        assert (
            classify_transaction(
                "PHONECO          PAYMENT    XXXXXX XXXXX0003EPAYZ  alex example"
            )
            == "Shared"
        )
        assert classify_transaction("XPHONECO ELECTRIC PAYMENT") == "Unclassified"

    def test_hoa_dues_and_fee_are_shared(self):
        assert (
            classify_transaction(
                "PL*HOAInteres    WEB PMTS   100626 AB1C23          Alex Example"
            )
            == "Shared"
        )
        assert (
            classify_transaction(
                "PL*FEEPAY        WEB PMTS   100626 DE4F56          Alex Example"
            )
            == "Shared"
        )
        # The full payee name contains "interest", but it's a bill, not interest earned.
        assert classify_transaction("PL*HOAINTEREST WEB PMTS") == "Shared"

    def test_mortgage_payment_is_mortgage(self):
        assert (
            classify_transaction("ONLINE TRANSFER TO MORTGAGE XXXXXX6666")
            == "Mortgage"
        )
        assert (
            classify_transaction("WF HOME MTG PRINCIPAL AND INTEREST 6666")
            == "Mortgage"
        )

    def test_mortgage_autopay_is_regular_payment(self):
        assert (
            classify_transaction(
                "WF HOME MTG      AUTO PAY   100926 XXXXXX6666      ALEX EXAMPLE"
            )
            == "Mortgage Payment"
        )

    def test_unrecognized_description_is_unclassified(self):
        assert (
            classify_transaction(
                "WT FED#00000 US BANK BNF=Example Title Co"
            )
            == "Unclassified"
        )

    def test_empty_description_is_unclassified(self):
        assert classify_transaction("") == "Unclassified"
        assert classify_transaction(None) == "Unclassified"


def _txn(txn_id, posted, amount, description, account_id):
    return {
        "id": txn_id,
        "posted": posted,
        "amount": amount,
        "description": description,
        "account_id": account_id,
        "account_name": JOINT_ACCOUNT_IDS[account_id],
    }


class TestGetNewTransactionsAsDf:
    @patch("src.joint_account_ledger.get_transactions")
    def test_maps_and_classifies_fetched_transactions(self, mock_get_transactions):
        mock_get_transactions.return_value = [
            _txn(
                "TRN-1",
                1735689600,
                "3.56",
                "August interest",
                list(JOINT_ACCOUNT_IDS)[0],
            )
        ]
        df = get_new_transactions_as_df("https://user:pass@bridge.simplefin.org")
        assert list(df.columns) == _OUTPUT_COLUMNS[:6]
        assert df.iloc[0]["Transaction ID"] == "TRN-1"
        assert df.iloc[0]["Amount"] == pytest.approx(3.56)
        assert df.iloc[0]["Suggested Classification"] == "Interest"

    @patch("src.joint_account_ledger.get_transactions")
    def test_empty_when_no_transactions(self, mock_get_transactions):
        mock_get_transactions.return_value = []
        df = get_new_transactions_as_df("https://user:pass@bridge.simplefin.org")
        assert df.empty


class TestBuildLedgerDf:
    def test_first_run_with_no_existing_sheet(self):
        fetched_df = pd.DataFrame(
            [
                {
                    "Transaction ID": "TRN-1",
                    "Date": pd.Timestamp("2026-08-28").date(),
                    "Account": "Online Bank Joint (1111)",
                    "Description": "Credit Union (Account ****3333)",
                    "Amount": 10000.00,
                    "Suggested Classification": "Mine",
                }
            ]
        )
        ledger_df = build_ledger_df(fetched_df, pd.DataFrame())
        assert len(ledger_df) == 1
        assert ledger_df.iloc[0]["Override Classification"] == ""
        # The first transaction is in row 6, under the summary and header
        assert ledger_df.iloc[0]["Effective Classification"] == '=IF(G6<>"",G6,F6)'
        assert ledger_df.iloc[0]["My Contribution"] == (
            '=IF(ISNUMBER(H6),E6*H6/100,IF(OR(H6="Mine",H6="Mortgage"),E6,IF(H6="Shared",E6*0.5,'
            'IF(H6="Mortgage Payment",E6*60/100,0))))'
        )

    def test_drops_rows_dated_before_ledger_start_date(self):
        existing_df = pd.DataFrame(
            [
                {
                    "Transaction ID": "TRN-OLD",
                    "Date": "2026-08-03",
                    "Account": "Big Bank Joint Savings (2222)",
                    "Description": "WT FED#00000 US BANK BNF=Example Title Co",
                    "Amount": -10000.00,
                    "Suggested Classification": "Unclassified",
                    "Override Classification": "60",
                    "Effective Classification": "60",
                    "My Contribution": -6000.00,
                    "Interest (Total)": 0,
                    "My Interest Share": 0,
                }
            ]
        )
        fetched_df = pd.DataFrame(columns=_OUTPUT_COLUMNS[:6])
        ledger_df = build_ledger_df(fetched_df, existing_df)
        assert ledger_df.empty
        assert list(ledger_df.columns) == _OUTPUT_COLUMNS

    def test_seed_row_with_percentage_override_is_preserved(self):
        existing_df = pd.DataFrame(
            [
                {
                    "Transaction ID": "SEED-ONLINEBANK-2026-09-06",
                    "Date": "2026-09-06",
                    "Account": "Online Bank Joint (1111)",
                    "Description": "Manual seed: balance as of ledger start date",
                    "Amount": 10003.59,
                    "Suggested Classification": "Unclassified",
                    "Override Classification": "Mine",
                    "Effective Classification": "Mine",
                    "My Contribution": 10003.59,
                    "Interest (Total)": 0,
                    "My Interest Share": 0,
                }
            ]
        )
        fetched_df = pd.DataFrame(columns=_OUTPUT_COLUMNS[:6])
        ledger_df = build_ledger_df(fetched_df, existing_df)
        assert len(ledger_df) == 1
        assert ledger_df.iloc[0]["Override Classification"] == "Mine"

    def test_dedupes_against_existing_transaction_ids(self):
        existing_df = pd.DataFrame(
            [
                {
                    "Transaction ID": "TRN-1",
                    "Date": "2026-09-10",
                    "Account": "Online Bank Joint (1111)",
                    "Description": "Credit Union (Account ****3333)",
                    "Amount": 10000.00,
                    "Suggested Classification": "Mine",
                    "Override Classification": "",
                    "Effective Classification": "Mine",
                    "My Contribution": 10000.00,
                    "Interest (Total)": 0,
                    "My Interest Share": 0,
                }
            ]
        )
        fetched_df = pd.DataFrame(
            [
                {
                    "Transaction ID": "TRN-1",
                    "Date": pd.Timestamp("2026-09-10").date(),
                    "Account": "Online Bank Joint (1111)",
                    "Description": "Credit Union (Account ****3333)",
                    "Amount": 10000.00,
                    "Suggested Classification": "Mine",
                },
                {
                    "Transaction ID": "TRN-2",
                    "Date": pd.Timestamp("2026-09-01").date(),
                    "Account": "Online Bank Joint (1111)",
                    "Description": "August interest",
                    "Amount": 3.56,
                    "Suggested Classification": "Interest",
                },
            ]
        )
        ledger_df = build_ledger_df(fetched_df, existing_df)
        assert len(ledger_df) == 2
        assert set(ledger_df["Transaction ID"]) == {"TRN-1", "TRN-2"}

    def test_preserves_manual_override_across_reruns(self):
        existing_df = pd.DataFrame(
            [
                {
                    "Transaction ID": "TRN-1",
                    "Date": "2026-09-08",
                    "Account": "Big Bank Joint Savings (2222)",
                    "Description": "WT FED#00000 US BANK BNF=Example Title Co",
                    "Amount": -10000.00,
                    "Suggested Classification": "Unclassified",
                    "Override Classification": "Mine",
                    "Effective Classification": "Mine",
                    "My Contribution": -10000.00,
                    "Interest (Total)": 0,
                    "My Interest Share": 0,
                }
            ]
        )
        fetched_df = pd.DataFrame(columns=_OUTPUT_COLUMNS[:6])
        ledger_df = build_ledger_df(fetched_df, existing_df)
        assert ledger_df.iloc[0]["Override Classification"] == "Mine"

    def test_recomputes_suggested_classification_from_stored_description(self):
        # Simulates the matcher list having been edited after this row was
        # first written - the old row's Suggested Classification should be
        # recomputed from its stored Description, not carried forward stale.
        existing_df = pd.DataFrame(
            [
                {
                    "Transaction ID": "TRN-1",
                    "Date": "2026-09-10",
                    "Account": "Online Bank Joint (1111)",
                    "Description": "August interest",
                    "Amount": 3.56,
                    "Suggested Classification": "Unclassified",
                    "Override Classification": "",
                    "Effective Classification": "Unclassified",
                    "My Contribution": 0,
                    "Interest (Total)": 0,
                    "My Interest Share": 0,
                }
            ]
        )
        fetched_df = pd.DataFrame(columns=_OUTPUT_COLUMNS[:6])
        ledger_df = build_ledger_df(fetched_df, existing_df)
        assert ledger_df.iloc[0]["Suggested Classification"] == "Interest"


class TestExportJointAccountLedgerToSheets:
    @patch.dict("os.environ", {}, clear=True)
    def test_skips_when_access_url_missing(self, caplog):
        export_joint_account_ledger_to_sheets()
        assert "not set" in caplog.text

    @patch("src.joint_account_ledger.write_cell_to_sheets")
    @patch("src.joint_account_ledger.write_to_sheets")
    @patch("src.joint_account_ledger.get_new_transactions_as_df")
    @patch("src.joint_account_ledger.read_from_sheets")
    @patch.dict(
        "os.environ",
        {
            "SIMPLEFIN_ACCESS_URL": "https://user:pass@bridge.simplefin.org",
            "PORTFOLIO_TAB_SUFFIX": "_preview",
        },
    )
    def test_preview_reads_live_tab_and_writes_preview_tab(
        self, mock_read, mock_get_new, mock_write, mock_write_cell
    ):
        mock_read.return_value = pd.DataFrame()
        mock_get_new.return_value = pd.DataFrame(
            [
                {
                    "Transaction ID": "TRN-1",
                    "Date": pd.Timestamp("2026-08-28").date(),
                    "Account": "Joint Savings (1111)",
                    "Description": "Interest Payment",
                    "Amount": 5.00,
                    "Suggested Classification": "Interest",
                }
            ]
        )
        export_joint_account_ledger_to_sheets()

        assert mock_read.call_args.args == ("joint_account_ledger",)
        ledger_call, balances_call = mock_write.call_args_list
        assert ledger_call.args[1] == "joint_account_ledger_preview"
        assert ledger_call.kwargs["create_if_missing"] is True
        assert balances_call.args[1] == "joint_account_ledger_preview"
        assert {c.args[2] for c in mock_write_cell.call_args_list} == {
            "joint_account_ledger_preview"
        }

    @patch("src.joint_account_ledger.write_cell_to_sheets")
    @patch("src.joint_account_ledger.write_to_sheets")
    @patch("src.joint_account_ledger.get_new_transactions_as_df")
    @patch("src.joint_account_ledger.read_from_sheets")
    @patch.dict(
        "os.environ", {"SIMPLEFIN_ACCESS_URL": "https://user:pass@bridge.simplefin.org"}
    )
    def test_writes_ledger_and_summary_cells(
        self, mock_read, mock_get_new, mock_write, mock_write_cell
    ):
        mock_read.return_value = pd.DataFrame()
        mock_get_new.return_value = pd.DataFrame(
            [
                {
                    "Transaction ID": "TRN-1",
                    "Date": pd.Timestamp("2026-08-28").date(),
                    "Account": "Online Bank Joint (1111)",
                    "Description": "Credit Union (Account ****3333)",
                    "Amount": 10000.00,
                    "Suggested Classification": "Mine",
                }
            ]
        )
        export_joint_account_ledger_to_sheets()
        assert mock_read.call_args.kwargs == {"header_label": "Transaction ID"}
        assert mock_write.call_count == 2
        ledger_call, balances_call = mock_write.call_args_list
        assert len(ledger_call.args[0]) == 1
        assert ledger_call.kwargs == {"start": (5, 1)}
        assert balances_call.args[0].columns.tolist() == [
            "Spouse Share",
            "My Running Balance",
            "Spouse Running Balance",
            "Spouse Share Covered",
            "Owed by Spouse (Splitwise)",
        ]
        assert balances_call.kwargs == {"start": (5, 12), "clear": False}
        assert mock_write_cell.call_count == 16
        written = {c.args[1]: c.args[0] for c in mock_write_cell.call_args_list}
        assert written["A2"] == "Joint Balance Total"
        assert written["A3"] == "=SUM(E6:E)"
        assert all(cell[1] in "23" for cell in written)  # above the table


class TestSummaryCells:
    def test_each_label_sits_above_its_formula(self):
        cells = summary_cells()
        assert cells["C2"] == "Spouse Current Balance"
        assert cells["C3"] == "=SUM(L6:L)+SUM(P6:P)"
        assert cells["D2"] == "Owed by Spouse (record in Splitwise)"
        assert cells["D3"] == "=SUM(P6:P)"
        assert len(cells) == 16


class TestBuildBalanceColumnsDf:
    def test_formulas_reference_their_own_row(self):
        balances_df = build_balance_columns_df(2)
        assert balances_df.iloc[1].tolist() == [
            '=IF(H7="Unclassified",0,E7-I7-K7)',
            "=SUM(I$6:I7)+SUM(K$6:K7)-SUM(P$6:P7)",
            "=MAX(0,N6+L7)",
            "=IF(L7<0,-L7-P7,0)",
            "=MAX(0,-(N6+L7))",
        ]

    def test_first_row_starts_from_zero(self):
        first = build_balance_columns_df(1).iloc[0]
        assert first["Spouse Running Balance"] == "=MAX(0,0+L6)"
        assert first["Owed by Spouse (Splitwise)"] == "=MAX(0,-(0+L6))"

    @pytest.mark.skipif(not _has_calc(), reason="needs LibreOffice Calc")
    def test_her_balance_covers_bills_until_it_runs_out(self, tmp_path):
        # (amount, effective classification, my contribution): your seed, their
        # pay, a 50/50 HOA bill, more of their pay, a property tax at 60/40
        # (override 60), then their pay again
        rows = [
            (1000, "Mine", 1000),
            (100, "Spouse", 0),
            (-300, "Shared", -150),
            (80, "Spouse", 0),
            (-500, 60, -300),
            (50, "Spouse", 0),
        ]
        first, last = FIRST_ROW, FIRST_ROW + len(rows) - 1
        wb = openpyxl.Workbook()
        ws = wb.active
        for offset, (amount, effective, mine) in enumerate(rows):
            ws.cell(row=first + offset, column=5, value=amount)
            ws.cell(row=first + offset, column=8, value=effective)
            ws.cell(row=first + offset, column=9, value=mine)
            ws.cell(row=first + offset, column=11, value=0)
        balances = build_balance_columns_df(len(rows))
        for offset, values in enumerate(balances.itertuples(index=False)):
            for col, formula in enumerate(values, start=12):
                ws.cell(row=first + offset, column=col, value=formula)
        for cell, value in summary_cells().items():
            # Bounded ranges: LibreOffice reads "L6:L" as a whole-row range
            ws[cell] = re.sub(rf"({first}:[A-Z])(?!\d)", rf"\g<1>{last}", value)
        calc = _recalculate(wb, tmp_path).active

        def column(letter):
            return [calc[f"{letter}{r}"].value for r in range(first, last + 1)]

        assert column("N") == [0, 100, 0, 80, 0, 50]  # their balance
        assert column("O") == [0, 0, 100, 0, 80, 0]  # covered by it
        assert column("P") == [0, 0, 50, 0, 120, 0]  # owed, for Splitwise
        assert column("M")[-1] == 1000 - 150 - 300 - 170
        assert calc[f"M{last}"].value + calc[f"N{last}"].value == sum(
            r[0] for r in rows
        )
        # The summary row: joint balance, mine, theirs, owed by them
        assert [calc[f"{c}3"].value for c in "ABCD"] == [430, 550, 50, 170]

    def test_empty_ledger_has_no_rows(self):
        assert build_balance_columns_df(0).empty
