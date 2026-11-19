# FinanceToSheets
Exports SimpleFIN-linked bank, credit card, brokerage and retirement accounts to Google Sheets, with brokerage tabs (Robinhood, Wells Fargo, Fidelity), a dividend ledger, a joint account ledger, and a marimo P&L dashboard.

## How it runs
A scheduled GitHub Action (see "SimpleFIN Bank & Savings Accounts" below) fetches every account linked in your SimpleFIN Bridge and refreshes the Robinhood, Wells Fargo and Fidelity tabs from it, three times a day, plus twice more on weekdays during market hours. Run the same export locally with:
```bash
python -m src.simplefin_to_sheets
```

### Running it on GitHub Actions
`.github/workflows/simplefin_export.yml` reads these repo secrets (Settings → Secrets and variables → Actions):

| Secret | What it is |
|---|---|
| `GSHEETS_AUTH_JSON` | The contents of the Google service account's JSON key (`data/gsheets_authentication.json` locally) |
| `SIMPLEFIN_ACCESS_URL` | Your SimpleFIN Bridge Access URL (see below) |
| `HOUSEHOLD_CONFIG` | Your household config JSON (see `config/household.example.json`) |
| `FIDELITY_DRIVE_FOLDER_ID` | Optional: the Drive folder with Fidelity's account-history CSV |

Secrets never reach workflow runs from forks, and the workflows log counts and tab names only, never balances, symbols or account names, since a public repo's Actions logs are public. GitHub pauses a public repo's scheduled workflows after 60 days without activity, so `keepalive.yml` re-enables them once a month. `python-tests.yml` runs the tests on pushes and pull requests.

## Fidelity YTD realized P&L
SimpleFIN's transactions can't give realized P&L (about 90 days of history, and trades carry no quantity or price), so that figure comes from Fidelity's account-history CSV:

1. In Fidelity, download your account history CSV (`Accounts_History_<year>.csv`) covering this year from January 1.
2. Drop it in a Google Drive folder shared with the service account's `client_email` (Viewer is enough), keeping "history" in the filename.
3. Set the `FIDELITY_DRIVE_FOLDER_ID` repo secret (and Render env var) to that folder's ID, the part after `/folders/` in its URL.

Each scheduled run picks up the newest file and writes YTD realized P&L to `fidelity_dump!M1`, and the Swing Trading page loads it without an upload. Re-upload only when you want the figure refreshed; old files don't need deleting.

## SimpleFIN Bank & Savings Accounts
Most institutions have no scriptable login, so this project uses [SimpleFIN Bridge](https://beta-bridge.simplefin.org/) ($1.50/mo or $15/yr) to pull balances for whatever accounts you link — no per-institution code needed, so linking a new account is a Bridge-side change only.

### Setup (one-time)
1. Create a SimpleFIN Bridge account and link the accounts you want automated. A linked brokerage account's balance appears both in `bank_accounts_dump` and in its brokerage tabs (Robinhood, Wells Fargo, Fidelity), so make sure your net worth formulas only count it once.
2. The Bridge gives you a **Setup Token** — a base64 string that decodes to a one-time claim URL. Claim it to get your permanent **Access URL**:
   ```bash
   curl -X POST "$(echo '<paste your Setup Token here>' | base64 -d)"
   ```
   The response body is your Access URL (Basic Auth credentials embedded in it). The Setup Token is single-use and stops working once claimed, so save the Access URL immediately (e.g. in a password manager) — it can't be re-derived.
3. Store the Access URL as the `SIMPLEFIN_ACCESS_URL` GitHub secret (and/or in your local `.env`/shell for manual runs).
4. Copy `config/household.example.json` to `config/household.json` (gitignored) and fill in your own values: the joint accounts' SimpleFIN ids (they start with `ACT-`) for the joint account ledger, the account-number digits and payee names it matches on, and any account whose `available-balance` should be used instead of `balance`. Store the same JSON as the `HOUSEHOLD_CONFIG` GitHub secret. It stays out of the repo because it identifies your accounts.
5. Manually create a `bank_accounts_dump` worksheet tab in `RH_Sheets` before the first run — like the other dump tabs, `write_to_sheets` writes into an existing tab but doesn't create one.
6. (Optional) Run the pipeline standalone to test it:
   ```bash
   python -m src.simplefin_to_sheets
   ```

This writes one row per linked account (Institution, Account Name, Balance, Balance As Of) to `bank_accounts_dump`. It also writes one row per security to a `holdings_dump` tab (created automatically on the first run) for any investment accounts whose institution reports holdings through SimpleFIN. The job logs show, per institution, how many holdings each account reported. Cost Basis and Purchase Price are written exactly as SimpleFIN returns them: the protocol says cost basis is per-share, but some brokerages send the position's total cost instead. The same run also rebuilds the Robinhood, Wells Fargo and Fidelity tabs from those holdings, so they stay up to date without logins or file uploads. To check a change before it replaces those tabs, run the workflow manually with **preview** ticked; it writes `<tab>_preview` copies instead, including `joint_account_ledger_preview`. Data lags about a day, since SimpleFIN Bridge syncs each institution roughly daily. Wells Fargo and Fidelity dividends are also collected into a `dividends_ledger` tab, with YTD totals in `WF_stock_dump!K1` and `fidelity_dump!M2`. The list grows run over run, since SimpleFIN only returns about 90 days of transactions at a time. To build a dividend portfolio out of your Wells Fargo holdings, tick the `Dividend Portfolio` column (I) on `WF_stock_dump` or `WF_etf_dump` (Insert → Checkbox on the column works). Every run keeps your ticks, matched by symbol, so another tab can pick them out with e.g. `=FILTER(WF_stock_dump!A2:A, WF_stock_dump!I2:I=TRUE)`. The tab opens with dividend totals by account, this year and all time, above the table, and each row has its ticker in a Symbol column (matched from your Wells Fargo holdings; type one in for a position you've since sold, and it's kept). To total dividends for a ticker elsewhere, e.g. on a Dividend tab with tickers in column B: `=SUMIFS(dividends_ledger!$G$7:$G, dividends_ledger!$H$7:$H, B6, dividends_ledger!$B$7:$B, ">="&DATE(YEAR(TODAY()),1,1))`. To include dividends from before the list started, add a row by hand with a unique Transaction ID, the Institution (`Wells Fargo` or `Fidelity`), a Posted date and the Amount; later runs keep it. Credit card balances come back from SimpleFIN as negative numbers (what's owed); flip the sign in whatever spreadsheet formula consumes this tab if your net worth sheet expects a positive debt figure.


## P&L Dashboard (Swing Trading)
`src/pnl_tracker.py` is a marimo app that computes year-to-date realized P&L from your Fidelity account history with FIFO cost basis: best and worst trades, a monthly view, a per-ticker drill-down and a weekly P&L chart against the S&P 500. Run it locally with:
```bash
marimo run src/pnl_tracker.py
```

The Yearly Overview and Net Worth dashboards over your budget sheet, and the budget template, moved to [FinanceDashboards](https://github.com/bsundar2/FinanceDashboards). They read the `bank_accounts_dump` and `holdings_dump` tabs this project writes.

### Hosting on Render (one-time)
On Render, `src/dashboard_server.py` serves the P&L tracker at `/` behind a password (`FINANCE_TOKEN`). A menu bar at the top links to the other dashboards when `FINANCE_DASHBOARD_URL`, `NET_WORTH_DASHBOARD_URL` and `SPENDING_DASHBOARD_URL` are set. When `FIDELITY_DRIVE_FOLDER_ID` is set, the page loads the newest `Accounts_History` CSV from that Drive folder by itself; uploading a CSV on the page still overrides it. Run the same thing locally with:
```bash
FINANCE_TOKEN=<any password> uvicorn --factory src.dashboard_server:create_app --port 2718
```

`render.yaml` defines the `pnl-tracker` service:
1. Share the Fidelity Drive folder with the service account's `client_email` (from `data/gsheets_authentication.json`); it's already shared for the GitHub Action.
2. In Render, sync the Blueprint, then on the service:
   - **Environment → Secret Files**: add `gsheets_authentication.json` with the contents of `data/gsheets_authentication.json`. `GSHEETS_AUTH_FILE` already points at `/etc/secrets/gsheets_authentication.json`.
   - **Environment**: set `FINANCE_TOKEN` to a long random password (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`) and keep it in your password manager. Set `FIDELITY_DRIVE_FOLDER_ID` to the same folder ID as the GitHub secret of that name, and the three dashboard URLs to the other apps' Render URLs.

This page loads your trades on the server, so the password is all that stands between the public URL and your data.
