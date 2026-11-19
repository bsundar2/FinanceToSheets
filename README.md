# FinanceToSheets
Exports SimpleFIN-linked bank, credit card, brokerage and retirement accounts to Google Sheets, with brokerage tabs (Robinhood, Wells Fargo, Fidelity), a dividend ledger, a joint account ledger, and marimo dashboards over a yearly budget spreadsheet.

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


## Personal Finance Dashboard
`src/finance_dashboard.py` is a marimo app, styled like the P&L dashboard, that reads the yearly budget spreadsheet (`Budget - 2026`) live and shows:
Under the headline numbers, a row of tiles mirrors the sheet's Dashboard tab: gross income, take-home pay, 401(k) contributions (plus the company match) and total savings from the Budget tab. The Dashboard tab's investment figures (dividends, interest and realized gain/loss (its `Stock Gain/Loss` row) from the Savings Log, and the year's market change: the net worth change less what you put in, including the 401(k)) follow in a second row of tiles.
1. **Spending**: your share of each Splitwise expense by month and category group (click a group in the bar above the chart to see its sub-categories by month, with each one's spending against its budget), over/under budget so far, top merchants, and the one-off expenses kept out of the charts (anything at or above an adjustable threshold, $5,000 by default, like a down payment).
2. **Savings by month**: what you logged as saved each month (the Net Worth tab's Monthly Savings Contributions), in dollars, split by the bucket each part went to (one per contribution row: savings, brokerage, retirement...), with a running total for the year.
3. **Net worth**: the Net Worth tab's monthly subtotals, and each month's change split into what you logged as contributions and everything else.

That page is the site's **Yearly Overview**: everything year to date, including the investment income tiles. Its **Net Worth** page (`src/net_worth_dashboard.py`) opens on your allocation: each category's share of your assets as one bar, with a table of each category's value and share. Click a category in the bar (or its chip; Liabilities has a chip too) to drill into it below: its types (stocks, ETF, crypto, foreign, 401k...) as a second bar, its accounts by month, and the securities each account holds, from the SimpleFIN `holdings_dump` tab in RH_Sheets. Clicking a type filters those holdings to it.

Run it locally with:
```bash
marimo run src/finance_dashboard.py
```

### One site: overview, net worth, swing trading and spending
On Render, `src/dashboard_server.py` serves the finance dashboard (Yearly Overview) at `/`, its Net Worth page at `/net-worth` and the P&L tracker (Swing Trading) at `/pnl` from one service, behind one password (`FINANCE_TOKEN`; you log in once for all of them). A menu bar at the top of each page links them, plus SplitwiseToSheets's spending dashboard when `SPENDING_DASHBOARD_URL` is set. When `FIDELITY_DRIVE_FOLDER_ID` is set, the P&L page loads the newest `Accounts_History` CSV from that Drive folder by itself; uploading a CSV on the page still overrides it. Run the same thing locally with:
```bash
FINANCE_TOKEN=<any password> uvicorn --factory src.dashboard_server:create_app --port 2718
```

### Hosting on Render (one-time)
`render.yaml` defines the `finance-dashboard` service:
1. Share `Budget - 2026` with the service account's `client_email` (from `data/gsheets_authentication.json`) as a Viewer. The Fidelity Drive folder is already shared with it for the GitHub Action.
2. In Render, sync the Blueprint, then on the `finance-dashboard` service:
   - **Environment → Secret Files**: add `gsheets_authentication.json` with the contents of `data/gsheets_authentication.json`. `GSHEETS_AUTH_FILE` already points at `/etc/secrets/gsheets_authentication.json`.
   - **Environment**: set `FINANCE_TOKEN` to a long random password (e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`) and keep it in your password manager. Set `FIDELITY_DRIVE_FOLDER_ID` to the same folder ID as the GitHub secret of that name, and `SPENDING_DASHBOARD_URL` to the spending dashboard's Render URL.
3. Delete the old `pnl-tracker` service; the P&L tracker now lives at `/pnl`.
4. Next year, change `BUDGET_SPREADSHEET_NAME` in `render.yaml` (or the service's environment) to the new spreadsheet's name, and share that one too.

These pages load your finances on the server, so the password is all that stands between the public URL and your data.

## Budget Template
`src/budget_template.py` builds the yearly budget spreadsheet as an `.xlsx` to import into Google Sheets: a generic household template, one sheet that both partners share (or just you, leaving the partner's parts empty). It has the same tabs and formulas as `Budget - 2026`, plus:
- **Settings**: both names, the year and how often each of you is paid. Every formula reads these instead of hard-coding them.
- **Income**: each person's pay, taxes and 401k side by side. The Budget tab's income rows add the two up, so take-home pay is the household's.
- **Expense Log** and **Partner Expense Log**: one per person, each filled by that person's SplitwiseToSheets. `My Owed` is that person's share of each expense, so a bill you split appears in both logs with each share, and the two add up to its full cost without counting it twice. Budget and Monthly Expenses total both.
- **Accounts**: balances entered by hand, plus an optional IMPORTRANGE of each person's SimpleFIN `bank_accounts_dump` (yours at G5, your partner's at L5).
- **Net Worth**: every account once, at its full balance, with each person's %: 100% / 0% for yours, 0% / 100% for your partner's, 50% / 50% (or 60% / 40%) for a joint account or the house. A balance is looked up by account name (or a fragment like `(1234)`), not a fixed cell, so new SimpleFIN accounts don't shift anything. The subtotals and NET WORTH are the household's, and two rows under NET WORTH give each person's own net worth.

```bash
# Blank template
python -m src.budget_template --out "Budget Template.xlsx" --year 2027

# An existing sheet in the original layout (File → Download → .xlsx), moved onto the template
python -m src.budget_migration "Budget - 2026.xlsx" --out "Budget - 2026 (v2).xlsx" --name Alex --partner Sam --year 2026
```

The migration puts the old sheet in your columns and tabs: your pay in Income, your Expense Log, and your Net Worth rows at full balance with your % (a `0.6 *` factor becomes 60% yours, 40% your partner's). Your partner's Income columns, Partner Expense Log and accounts start empty. A joint account the old sheet tracked as your part only (e.g. from the joint account ledger) stays that way, 100% yours, until you switch it to the full balance and each person's %.

To use either file, upload it to Google Drive and open it with Google Sheets (or File → Import → Create new spreadsheet). Then click **Allow access** on the first IMPORTRANGE cell (Accounts G5) so it can read RH_Sheets. To keep the Expense Logs updating, point each person's SplitwiseToSheets `SPREADSHEET_KEY` at the new sheet, with your partner's `EXPENSES_WORKSHEET_NAME` (or `--worksheet`) set to `Partner Expense Log`. Point the finance dashboard's `BUDGET_SPREADSHEET_NAME` at it; it reads both logs.
