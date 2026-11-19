import logging
import os
import pandas as pd
from src.external_services.google_sheets import write_to_sheets, read_from_sheets, write_cell_to_sheets
from src.external_services.google_drive import (
    download_file,
    download_latest_matching_file,
    find_latest_matching_file,
)
from src.constants.gsheets import FIDELITY_DUMP_SHEET_NAME, FIDELITY_DRIVE_FOLDER_ID_ENV_VAR
from src.constants.paths import FIDELITY_STATEMENTS_DIR, FIDELITY_ACCOUNT_HISTORY_CSV
from src.pnl_calculator import parse_history, calculate_ytd_pnl

logger = logging.getLogger(__name__)

# Fixed cells (outside the A-J position table columns) so they stay put
# regardless of how many position rows are written.
YTD_PNL_LABEL_CELL = "L1"
YTD_PNL_VALUE_CELL = "M1"
YTD_DIVIDENDS_LABEL_CELL = "L2"
YTD_DIVIDENDS_VALUE_CELL = "M2"


def sync_fidelity_account_history_from_drive() -> None:
    """If FIDELITY_DRIVE_FOLDER_ID is set, downloads the newest account-history
    CSV in that Drive folder (filename containing "history") to the local
    path write_ytd_realized_pnl_to_sheets() reads. Positions come from
    SimpleFIN, but YTD realized P&L still needs this CSV. Optional, so any
    failure is logged and skipped; a no-op if the env var is unset."""
    folder_id = os.getenv(FIDELITY_DRIVE_FOLDER_ID_ENV_VAR)
    if not folder_id:
        return

    FIDELITY_STATEMENTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        history_bytes = download_latest_matching_file(folder_id, "history")
        if history_bytes is not None:
            FIDELITY_ACCOUNT_HISTORY_CSV.write_bytes(history_bytes)
    except Exception as e:
        logger.warning(f"Could not fetch account history CSV from Drive: {e}")

def latest_account_history_from_drive() -> dict | None:
    """The newest account-history CSV in the Fidelity Drive folder, as
    {"name", "modified", "contents"} for the P&L dashboard to load without
    an upload. None if FIDELITY_DRIVE_FOLDER_ID is unset or no file in the
    folder matches; Drive errors propagate so the dashboard can show them."""
    folder_id = os.getenv(FIDELITY_DRIVE_FOLDER_ID_ENV_VAR)
    if not folder_id:
        return None
    match = find_latest_matching_file(folder_id, "history")
    if match is None:
        return None
    return {
        "name": match["name"],
        "modified": match.get("modifiedTime", ""),
        "contents": download_file(match["id"]),
    }


def write_ytd_realized_pnl_to_sheets(worksheet_name: str = FIDELITY_DUMP_SHEET_NAME) -> None:
    """If an account-history CSV is present (fetched from Drive by
    sync_fidelity_account_history_from_drive()), computes YTD
    realized P&L and writes it to a fixed cell in the fidelity_dump sheet.
    This is optional context on top of the position table: silently skipped
    if the file isn't there, and any parsing error is logged rather than
    raised so it never blocks the main position export."""
    if not FIDELITY_ACCOUNT_HISTORY_CSV.exists():
        return

    try:
        history_df = parse_history(FIDELITY_ACCOUNT_HISTORY_CSV)
        realized_pnl, _ = calculate_ytd_pnl(history_df)
        ytd_pnl = sum(r["gain_loss"] for r in realized_pnl)
    except Exception as e:
        logger.warning(f"Could not compute YTD realized P&L from {FIDELITY_ACCOUNT_HISTORY_CSV}: {e}")
        return

    # The amount stays out of the log, since Actions logs are public
    logger.info(f"Writing YTD realized P&L to '{worksheet_name}'")
    write_cell_to_sheets("YTD Realized P&L", YTD_PNL_LABEL_CELL, worksheet_name)
    write_cell_to_sheets(ytd_pnl, YTD_PNL_VALUE_CELL, worksheet_name)

def write_fidelity_positions_to_sheets(
    new_df: pd.DataFrame,
    worksheet_name: str = FIDELITY_DUMP_SHEET_NAME,
    create_if_missing: bool = False,
) -> None:
    """Writes the fidelity_dump positions table (built by
    simplefin_portfolios), re-applying manually entered stop prices and
    injecting the R-multiple formulas.
    Stop prices are always read from the live fidelity_dump tab, even when
    writing elsewhere (e.g. a preview tab), since that's where they're kept."""
    new_df = new_df.reset_index(drop=True)

    # Try to read existing data to preserve manually entered Stop Prices
    logger.info(f"Reading existing data from Google Sheets tab: '{FIDELITY_DUMP_SHEET_NAME}'")
    old_df = read_from_sheets(FIDELITY_DUMP_SHEET_NAME)

    # Standardize column names for preservation (case-sensitive)
    cols_to_preserve = ["Current Stop Price", "Original Stop Price"]

    if not old_df.empty and "Symbol" in old_df.columns:
        logger.info("Preserving existing manual entry values...")
        for col in cols_to_preserve:
            if col in old_df.columns:
                # Create a mapping of Symbol -> Value
                mapping = old_df.replace("", pd.NA).dropna(subset=[col])
                mapping = dict(zip(mapping["Symbol"], mapping[col]))

                # Apply mapping to new_df
                new_df[col] = new_df["Symbol"].map(mapping).fillna("")

    # Generate Formulas for each row
    # Column C (R Value) = F - B
    # Column D (Current R Multiple) = ((J/I) - F) / C
    # Column E (Stop R Multiple) = (A - F) / C
    logger.info("Generating formulas...")
    for i in range(len(new_df)):
        row_idx = i + 2  # +2 because Google Sheets is 1-indexed and has a header row
        new_df.at[i, "R Value"] = f"=F{row_idx}-B{row_idx}"
        new_df.at[i, "Current R Multiple"] = f"=IFERROR(((J{row_idx}/I{row_idx})-F{row_idx})/C{row_idx}, 0)"
        new_df.at[i, "Stop R Multiple"] = f"=IFERROR((A{row_idx}-F{row_idx})/C{row_idx}, 0)"

    logger.info(f"Writing to Google Sheets tab: '{worksheet_name}'")
    if create_if_missing:
        write_to_sheets(new_df, worksheet_name, create_if_missing=True)
    else:
        write_to_sheets(new_df, worksheet_name)
