import logging

import pygsheets
import pandas as pd

from src.constants.gsheets import DEFAULT_SPREADSHEET_NAME, SHEETS_AUTHENTICATION_FILE

logger = logging.getLogger(__name__)


def write_to_sheets(
    write_data: pd.DataFrame,
    worksheet_name: str,
    spreadsheet_name: str = DEFAULT_SPREADSHEET_NAME,
    create_if_missing: bool = False,
    start: tuple[int, int] = (1, 1),
    clear: bool = True,
):
    """Clears worksheet_name and writes write_data into it. By default the
    tab must already exist, so a typo'd name fails loudly instead of
    silently creating a stray tab - pass create_if_missing=True to opt out
    of that for a newly-introduced tab. start is the (row, column) of the
    header's top-left cell; pass clear=False to add columns beside a table
    already written."""
    # Login/Authenticate
    logger.info("Authenticating to Google Sheets")
    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)

    logger.info("Open sheet to edit")
    sheet = gc.open(spreadsheet_name)
    try:
        worksheet = sheet.worksheet_by_title(worksheet_name)
    except pygsheets.WorksheetNotFound:
        if not create_if_missing:
            raise
        logger.info(f"Worksheet '{worksheet_name}' not found - creating it")
        worksheet = sheet.add_worksheet(worksheet_name)
    if clear:
        worksheet.clear()

    logger.info("Writing to sheet")
    worksheet.set_dataframe(write_data, start, copy_index=False, copy_head=True)
    logger.info("Updated Google sheet successfully")


def write_cell_to_sheets(
    value,
    cell: str,
    worksheet_name: str,
    spreadsheet_name: str = DEFAULT_SPREADSHEET_NAME,
):
    """Writes a single value to a fixed cell (e.g. "M1"), independent of the
    row range write_to_sheets uses. Does not clear the worksheet, so it's
    safe to call after write_to_sheets has already written the main table."""
    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)

    sheet = gc.open(spreadsheet_name)
    worksheet = sheet.worksheet_by_title(worksheet_name)
    worksheet.update_value(cell, value)


def write_cells_to_sheets(
    cells: dict[str, object],
    worksheet_name: str,
    spreadsheet_name: str = DEFAULT_SPREADSHEET_NAME,
):
    """Writes each value to its fixed cell (e.g. {"A2": "Total", "A3":
    "=SUM(G7:G)"}), opening the sheet once. Like write_cell_to_sheets, it
    doesn't clear anything."""
    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)

    sheet = gc.open(spreadsheet_name)
    worksheet = sheet.worksheet_by_title(worksheet_name)
    for cell, value in cells.items():
        worksheet.update_value(cell, value)


def read_from_sheets(
    worksheet_name: str,
    spreadsheet_name: str = DEFAULT_SPREADSHEET_NAME,
    header_label: str | None = None,
) -> pd.DataFrame:
    """The tab as a DataFrame, headed by its first row - or, with
    header_label, by the first row that has a cell equal to it, for a table
    with something above it (a summary). A tab that has content but no such
    row raises rather than reading as empty, so a caller that rebuilds the
    tab from what it read can't wipe it. A missing tab reads as empty."""
    # Login/Authenticate
    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)

    sheet = gc.open(spreadsheet_name)
    try:
        worksheet = sheet.worksheet_by_title(worksheet_name)
    except pygsheets.WorksheetNotFound:
        return pd.DataFrame()
    if header_label is None:
        # get_as_df returns a DataFrame with headers from the first row
        return worksheet.get_as_df()

    values = worksheet.get_as_df(has_header=False)
    for index in range(len(values)):
        row = values.iloc[index]
        if (row.astype(str) == header_label).any():
            table = values.iloc[index + 1 :]
            blank = table.isna() | (table.astype(str).apply(lambda c: c.str.strip()) == "")
            table = table[~blank.all(axis=1)].reset_index(drop=True)
            table.columns = [str(label) for label in row]
            return table
    if (values.astype(str) != "").any().any():
        raise ValueError(f"No '{header_label}' header row in '{worksheet_name}'")
    return pd.DataFrame()


def read_values_from_sheets(
    worksheet_names: list[str],
    spreadsheet_name: str = DEFAULT_SPREADSHEET_NAME,
    optional_worksheet_names: tuple[str, ...] = (),
) -> dict[str, list[list]]:
    """Every cell of each named tab as a matrix of raw values (numbers as
    numbers, dates as serial day numbers), for tabs laid out as a report
    rather than a table with its header in row 1. Opens the spreadsheet once
    for all the tabs. An optional tab the spreadsheet doesn't have is left
    out of the result; any other missing tab raises."""
    gc = pygsheets.authorize(service_account_file=SHEETS_AUTHENTICATION_FILE)

    sheet = gc.open(spreadsheet_name)
    values = {}
    for name in [*worksheet_names, *optional_worksheet_names]:
        try:
            worksheet = sheet.worksheet_by_title(name)
        except pygsheets.WorksheetNotFound:
            if name in optional_worksheet_names:
                continue
            raise
        values[name] = worksheet.get_all_values(
            include_tailing_empty=False,
            include_tailing_empty_rows=False,
            value_render=pygsheets.ValueRenderOption.UNFORMATTED_VALUE,
            date_time_render_option=pygsheets.DateTimeRenderOption.SERIAL_NUMBER,
        )
    return values
