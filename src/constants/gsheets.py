import os

# Env var pointing at the service account credentials file somewhere other
# than the default local path - e.g. a hosted dashboard whose secret file is
# mounted elsewhere (Render puts them under /etc/secrets/).
SHEETS_AUTHENTICATION_FILE_ENV_VAR = "GSHEETS_AUTH_FILE"
SHEETS_AUTHENTICATION_FILE = os.environ.get(
    SHEETS_AUTHENTICATION_FILE_ENV_VAR, "data/gsheets_authentication.json"
)
DEFAULT_SPREADSHEET_NAME = "RH_Sheets"

# Env var holding the ID of a Google Drive folder shared with the service
# account (SHEETS_AUTHENTICATION_FILE) that holds manually-dropped Fidelity
# account-history CSVs (the segment after /folders/ in the folder's URL). If
# unset, Drive fetching is skipped and a local file is used as-is.
FIDELITY_DRIVE_FOLDER_ID_ENV_VAR = "FIDELITY_DRIVE_FOLDER_ID"

# Env var holding a SimpleFIN Bridge Access URL (Basic Auth credentials
# embedded in the URL itself - see https://www.simplefin.org/protocol.html).
# Claimed once from a Bridge Setup Token; there's no refresh flow, so this is
# a long-lived secret rather than something rotated per run.
SIMPLEFIN_ACCESS_URL_ENV_VAR = "SIMPLEFIN_ACCESS_URL"

# Optional suffix (e.g. "_preview") the SimpleFIN pipeline appends to the
# brokerage tab names it writes, so a run can be compared side by side with
# the live tabs before replacing them. Unset writes the live tabs.
PORTFOLIO_TAB_SUFFIX_ENV_VAR = "PORTFOLIO_TAB_SUFFIX"

RH_STOCK_DUMP_SHEET_NAME = "RH_stock_dump"
RH_ETF_DUMP_SHEET_NAME = "RH_etf_dump"
RH_CRYPTO_DUMP_SHEET_NAME = "RH_crypto_dump"
RH_CASH_DUMP_SHEET_NAME = "RH_cash_dump"
FIDELITY_DUMP_SHEET_NAME = "fidelity_dump"
WF_STOCK_DUMP_SHEET_NAME = "WF_stock_dump"
WF_ETF_DUMP_SHEET_NAME = "WF_etf_dump"
WF_CASH_DUMP_SHEET_NAME = "WF_cash_dump"
BANK_ACCOUNTS_DUMP_SHEET_NAME = "bank_accounts_dump"
HOLDINGS_DUMP_SHEET_NAME = "holdings_dump"
DIVIDENDS_LEDGER_SHEET_NAME = "dividends_ledger"
JOINT_ACCOUNT_LEDGER_SHEET_NAME = "joint_account_ledger"
