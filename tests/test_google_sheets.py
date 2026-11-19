import pandas as pd
import pygsheets
import pytest
from unittest.mock import MagicMock, patch

from src.external_services.google_sheets import (
    read_from_sheets,
    read_values_from_sheets,
    write_cells_to_sheets,
    write_to_sheets,
)


def _sheet_without(worksheet_name):
    sheet = MagicMock()
    sheet.worksheet_by_title.side_effect = pygsheets.WorksheetNotFound(worksheet_name)
    return sheet


class TestWriteToSheets:
    def test_missing_worksheet_raises_by_default(self):
        sheet = _sheet_without("new_tab")

        with patch("src.external_services.google_sheets.pygsheets.authorize") as auth:
            auth.return_value.open.return_value = sheet
            with pytest.raises(pygsheets.WorksheetNotFound):
                write_to_sheets(pd.DataFrame({"a": [1]}), "new_tab")

        sheet.add_worksheet.assert_not_called()

    def test_missing_worksheet_created_when_opted_in(self):
        sheet = _sheet_without("new_tab")
        df = pd.DataFrame({"a": [1]})

        with patch("src.external_services.google_sheets.pygsheets.authorize") as auth:
            auth.return_value.open.return_value = sheet
            write_to_sheets(df, "new_tab", create_if_missing=True)

        sheet.add_worksheet.assert_called_once_with("new_tab")
        created = sheet.add_worksheet.return_value
        created.clear.assert_called_once()
        created.set_dataframe.assert_called_once_with(
            df, (1, 1), copy_index=False, copy_head=True
        )

    def test_writes_beside_existing_table_without_clearing(self):
        worksheet = MagicMock()
        df = pd.DataFrame({"a": [1]})

        with patch("src.external_services.google_sheets.pygsheets.authorize") as auth:
            auth.return_value.open.return_value.worksheet_by_title.return_value = (
                worksheet
            )
            write_to_sheets(df, "tab", start=(1, 15), clear=False)

        worksheet.clear.assert_not_called()
        worksheet.set_dataframe.assert_called_once_with(
            df, (1, 15), copy_index=False, copy_head=True
        )


class TestReadValuesFromSheets:
    def test_reads_each_tab_unformatted_from_one_open(self):
        with patch("src.external_services.google_sheets.pygsheets.authorize") as auth:
            sheet = auth.return_value.open.return_value
            sheet.worksheet_by_title.return_value.get_all_values.return_value = [[1]]
            result = read_values_from_sheets(["A", "B"], "Budget")

        auth.return_value.open.assert_called_once_with("Budget")
        assert result == {"A": [[1]], "B": [[1]]}
        kwargs = sheet.worksheet_by_title.return_value.get_all_values.call_args.kwargs
        assert kwargs["value_render"] == pygsheets.ValueRenderOption.UNFORMATTED_VALUE
        assert (
            kwargs["date_time_render_option"]
            == pygsheets.DateTimeRenderOption.SERIAL_NUMBER
        )

    def test_missing_optional_tab_is_left_out(self):
        def worksheet(name):
            if name == "Partner":
                raise pygsheets.WorksheetNotFound(name)
            found = MagicMock()
            found.get_all_values.return_value = [[1]]
            return found

        with patch("src.external_services.google_sheets.pygsheets.authorize") as auth:
            auth.return_value.open.return_value.worksheet_by_title.side_effect = (
                worksheet
            )
            result = read_values_from_sheets(["A"], "Budget", ("Partner",))

        assert result == {"A": [[1]]}

    def test_missing_required_tab_still_raises(self):
        with patch("src.external_services.google_sheets.pygsheets.authorize") as auth:
            auth.return_value.open.return_value = _sheet_without("A")
            with pytest.raises(pygsheets.WorksheetNotFound):
                read_values_from_sheets(["A"], "Budget", ("Partner",))


class TestReadFromSheets:
    def _read(self, values, **kwargs):
        with patch("src.external_services.google_sheets.pygsheets.authorize") as auth:
            worksheet = auth.return_value.open.return_value.worksheet_by_title.return_value
            worksheet.get_as_df.return_value = pd.DataFrame(values)
            return read_from_sheets("ledger", "Sheets", **kwargs), worksheet

    def test_header_found_below_a_summary(self):
        df, worksheet = self._read(
            [
                ["", "", ""],
                ["Joint Balance Total", "Mine", ""],
                [430, 550, ""],
                ["", "", ""],
                ["Transaction ID", "Date", "Amount"],
                ["TRN-1", "2026-09-11", 2000],
                ["", "", None],  # blank rows aren't transactions
            ],
            header_label="Transaction ID",
        )
        worksheet.get_as_df.assert_called_once_with(has_header=False)
        assert df.columns.tolist() == ["Transaction ID", "Date", "Amount"]
        assert df.to_dict("records") == [
            {"Transaction ID": "TRN-1", "Date": "2026-09-11", "Amount": 2000}
        ]

    def test_header_in_the_first_row_still_works(self):
        df, _ = self._read(
            [["Transaction ID", "Amount", "My Contributions Total"], ["TRN-1", 5, 42]],
            header_label="Transaction ID",
        )
        assert df["Transaction ID"].tolist() == ["TRN-1"]

    def test_content_without_the_header_raises(self):
        with pytest.raises(ValueError, match="Transaction ID"):
            self._read([["something else"], ["x"]], header_label="Transaction ID")

    def test_empty_tab_reads_as_empty(self):
        df, _ = self._read([], header_label="Transaction ID")
        assert df.empty

    def test_without_a_header_label_row_one_is_the_header(self):
        df, worksheet = self._read([{"a": 1}])
        worksheet.get_as_df.assert_called_once_with()


class TestWriteCellsToSheets:
    def test_writes_each_cell_from_one_open(self):
        with patch("src.external_services.google_sheets.pygsheets.authorize") as auth:
            write_cells_to_sheets({"A2": "Total", "A3": "=SUM(G7:G)"}, "ledger", "Sheets")

        auth.return_value.open.assert_called_once_with("Sheets")
        worksheet = auth.return_value.open.return_value.worksheet_by_title.return_value
        assert [c.args for c in worksheet.update_value.call_args_list] == [
            ("A2", "Total"),
            ("A3", "=SUM(G7:G)"),
        ]
