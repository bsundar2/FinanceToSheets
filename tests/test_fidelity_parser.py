import pandas as pd
import pytest
from unittest.mock import patch

from src.fidelity_parser import (
    write_fidelity_positions_to_sheets,
    write_ytd_realized_pnl_to_sheets,
    sync_fidelity_account_history_from_drive,
    latest_account_history_from_drive,
)


SAMPLE_HISTORY_CSV = """\
Brokerage Statement
Exported Jul-05-2026
Run Date,Action,Symbol,Price ($),Quantity,Amount ($),Fees ($),Commission ($)
01/01/2026,YOU BOUGHT AAPL,AAPL,"$100.00",10,"($1,000.00)",0,0
06/01/2026,YOU SOLD AAPL,AAPL,"$150.00",-10,"$1,500.00",0,0
"""


def _make_portfolio_df():
    return pd.DataFrame({
        "Current Stop Price": ["", ""],
        "Original Stop Price": ["", ""],
        "R Value": ["", ""],
        "Current R Multiple": ["", ""],
        "Stop R Multiple": ["", ""],
        "Average Cost Basis": [200.0, 130.0],
        "Symbol": ["MSFT", "AAPL"],
        "Description": ["Microsoft Corp", "Apple Inc."],
        "Quantity": [5.0, 10.0],
        "Current Value": [1500.0, 1500.0],
    })


class TestWriteFidelityPositionsToSheets:
    def test_preserves_existing_stop_prices_by_symbol(self):
        new_df = _make_portfolio_df()
        old_df = pd.DataFrame({
            "Symbol": ["AAPL", "MSFT"],
            "Current Stop Price": ["140", ""],
            "Original Stop Price": ["125", "190"],
        })

        with patch("src.fidelity_parser.read_from_sheets", return_value=old_df), \
             patch("src.fidelity_parser.write_to_sheets") as mock_write:
            write_fidelity_positions_to_sheets(new_df)
            written = mock_write.call_args[0][0]

            aapl = written[written["Symbol"] == "AAPL"]
            msft = written[written["Symbol"] == "MSFT"]
            assert aapl["Current Stop Price"].iloc[0] == "140"
            assert aapl["Original Stop Price"].iloc[0] == "125"
            assert msft["Current Stop Price"].iloc[0] == ""
            assert msft["Original Stop Price"].iloc[0] == "190"

    def test_injects_r_value_formula(self):
        new_df = _make_portfolio_df().iloc[:1].reset_index(drop=True)  # one row

        with patch("src.fidelity_parser.read_from_sheets", return_value=pd.DataFrame()), \
             patch("src.fidelity_parser.write_to_sheets") as mock_write:
            write_fidelity_positions_to_sheets(new_df)
            written = mock_write.call_args[0][0]
            # First data row is row 2 in Sheets (1-indexed with header)
            assert written["R Value"].iloc[0] == "=F2-B2"

    def test_injects_current_r_multiple_formula(self):
        new_df = _make_portfolio_df().iloc[:1].reset_index(drop=True)

        with patch("src.fidelity_parser.read_from_sheets", return_value=pd.DataFrame()), \
             patch("src.fidelity_parser.write_to_sheets") as mock_write:
            write_fidelity_positions_to_sheets(new_df)
            written = mock_write.call_args[0][0]
            assert written["Current R Multiple"].iloc[0] == "=IFERROR(((J2/I2)-F2)/C2, 0)"

    def test_injects_stop_r_multiple_formula(self):
        new_df = _make_portfolio_df().iloc[:1].reset_index(drop=True)

        with patch("src.fidelity_parser.read_from_sheets", return_value=pd.DataFrame()), \
             patch("src.fidelity_parser.write_to_sheets") as mock_write:
            write_fidelity_positions_to_sheets(new_df)
            written = mock_write.call_args[0][0]
            assert written["Stop R Multiple"].iloc[0] == "=IFERROR((A2-F2)/C2, 0)"

    def test_formula_row_indices_increment_per_row(self):
        new_df = _make_portfolio_df()  # two rows

        with patch("src.fidelity_parser.read_from_sheets", return_value=pd.DataFrame()), \
             patch("src.fidelity_parser.write_to_sheets") as mock_write:
            write_fidelity_positions_to_sheets(new_df)
            written = mock_write.call_args[0][0]
            assert written["R Value"].iloc[0] == "=F2-B2"
            assert written["R Value"].iloc[1] == "=F3-B3"

    def test_calls_write_to_sheets_with_correct_worksheet(self):
        new_df = _make_portfolio_df()

        with patch("src.fidelity_parser.read_from_sheets", return_value=pd.DataFrame()), \
             patch("src.fidelity_parser.write_to_sheets") as mock_write:
            write_fidelity_positions_to_sheets(new_df)
            _, worksheet_name = mock_write.call_args[0]
            assert worksheet_name == "fidelity_dump"


class TestWriteYtdRealizedPnlToSheets:
    def test_skips_when_account_history_file_missing(self, tmp_path):
        missing_path = tmp_path / "account_history.csv"

        with patch("src.fidelity_parser.FIDELITY_ACCOUNT_HISTORY_CSV", missing_path), \
             patch("src.fidelity_parser.write_cell_to_sheets") as mock_write_cell:
            write_ytd_realized_pnl_to_sheets()
            mock_write_cell.assert_not_called()

    def test_writes_label_and_value_when_file_present(self, tmp_path):
        history_file = tmp_path / "account_history.csv"
        history_file.write_text(SAMPLE_HISTORY_CSV)

        with patch("src.fidelity_parser.FIDELITY_ACCOUNT_HISTORY_CSV", history_file), \
             patch("src.fidelity_parser.write_cell_to_sheets") as mock_write_cell:
            write_ytd_realized_pnl_to_sheets()

            assert mock_write_cell.call_count == 2
            label_call, value_call = mock_write_cell.call_args_list
            assert label_call.args == ("YTD Realized P&L", "L1", "fidelity_dump")
            assert value_call.args[1:] == ("M1", "fidelity_dump")
            assert value_call.args[0] == pytest.approx(500.0)

    def test_skips_without_raising_on_malformed_history_file(self, tmp_path):
        history_file = tmp_path / "account_history.csv"
        history_file.write_text("not,a,valid,fidelity,history,csv\n1,2,3,4,5,6\n")

        with patch("src.fidelity_parser.FIDELITY_ACCOUNT_HISTORY_CSV", history_file), \
             patch("src.fidelity_parser.write_cell_to_sheets") as mock_write_cell:
            # Should not raise
            write_ytd_realized_pnl_to_sheets()
            mock_write_cell.assert_not_called()


class TestSyncFidelityAccountHistoryFromDrive:
    def test_noop_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("FIDELITY_DRIVE_FOLDER_ID", raising=False)

        with patch("src.fidelity_parser.download_latest_matching_file") as mock_download:
            sync_fidelity_account_history_from_drive()
            mock_download.assert_not_called()

    def test_downloads_and_writes_history_when_configured(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FIDELITY_DRIVE_FOLDER_ID", "some-folder-id")
        history_path = tmp_path / "account_history.csv"

        def fake_download(folder_id, name_contains):
            assert (folder_id, name_contains) == ("some-folder-id", "history")
            return b"history content"

        with patch("src.fidelity_parser.FIDELITY_STATEMENTS_DIR", tmp_path), \
             patch("src.fidelity_parser.FIDELITY_ACCOUNT_HISTORY_CSV", history_path), \
             patch("src.fidelity_parser.download_latest_matching_file", side_effect=fake_download):
            sync_fidelity_account_history_from_drive()

        assert history_path.read_bytes() == b"history content"

    def test_leaves_file_untouched_when_no_drive_match(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FIDELITY_DRIVE_FOLDER_ID", "some-folder-id")
        history_path = tmp_path / "account_history.csv"

        with patch("src.fidelity_parser.FIDELITY_STATEMENTS_DIR", tmp_path), \
             patch("src.fidelity_parser.FIDELITY_ACCOUNT_HISTORY_CSV", history_path), \
             patch("src.fidelity_parser.download_latest_matching_file", return_value=None):
            sync_fidelity_account_history_from_drive()

        assert not history_path.exists()

    def test_download_failure_is_logged_not_raised(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FIDELITY_DRIVE_FOLDER_ID", "some-folder-id")
        history_path = tmp_path / "account_history.csv"

        with patch("src.fidelity_parser.FIDELITY_STATEMENTS_DIR", tmp_path), \
             patch("src.fidelity_parser.FIDELITY_ACCOUNT_HISTORY_CSV", history_path), \
             patch("src.fidelity_parser.download_latest_matching_file", side_effect=RuntimeError("Drive API error")):
            sync_fidelity_account_history_from_drive()

        assert not history_path.exists()


class TestLatestAccountHistoryFromDrive:
    def test_none_when_env_var_unset(self, monkeypatch):
        monkeypatch.delenv("FIDELITY_DRIVE_FOLDER_ID", raising=False)

        with patch("src.fidelity_parser.find_latest_matching_file") as find:
            assert latest_account_history_from_drive() is None
            find.assert_not_called()

    def test_none_when_the_folder_has_no_history_file(self, monkeypatch):
        monkeypatch.setenv("FIDELITY_DRIVE_FOLDER_ID", "some-folder-id")

        with patch("src.fidelity_parser.find_latest_matching_file", return_value=None):
            assert latest_account_history_from_drive() is None

    def test_newest_history_file_with_its_name_and_date(self, monkeypatch):
        monkeypatch.setenv("FIDELITY_DRIVE_FOLDER_ID", "some-folder-id")
        match = {"id": "7", "name": "Accounts_History.csv", "modifiedTime": "2026-10-20T08:00:00Z"}

        with patch("src.fidelity_parser.find_latest_matching_file", return_value=match) as find, \
             patch("src.fidelity_parser.download_file", return_value=b"csv bytes") as download:
            result = latest_account_history_from_drive()

        find.assert_called_once_with("some-folder-id", "history")
        download.assert_called_once_with("7")
        assert result == {
            "name": "Accounts_History.csv",
            "modified": "2026-10-20T08:00:00Z",
            "contents": b"csv bytes",
        }

    def test_drive_errors_propagate_for_the_dashboard_to_show(self, monkeypatch):
        monkeypatch.setenv("FIDELITY_DRIVE_FOLDER_ID", "some-folder-id")

        with patch("src.fidelity_parser.find_latest_matching_file", side_effect=OSError("denied")):
            with pytest.raises(OSError):
                latest_account_history_from_drive()
