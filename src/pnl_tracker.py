import marimo

__generated_with = "0.6.0"
app = marimo.App(width="full")


@app.cell
def __():
    import marimo as mo
    import pandas as pd

    try:
        # Normal local/CI usage: repo root is on sys.path, so these are
        # real absolute imports of the src package.
        from src.pnl_calculator import parse_history, calculate_ytd_pnl
        from src.external_services.market_data import get_sp500_weekly_returns
        from src.dashboard_nav import PNL, nav_html
    except ModuleNotFoundError:
        # marimo's html-wasm export bundles each notebook-local import as
        # its own top-level wheel rooted at src/'s *contents*, not at a
        # "src" package itself (see marimo's local_modules.py) - so under
        # Pyodide, these same modules are importable without the "src."
        # prefix instead.
        from pnl_calculator import parse_history, calculate_ytd_pnl
        from external_services.market_data import get_sp500_weekly_returns
        from dashboard_nav import PNL, nav_html

    try:
        # Loads the newest account-history CSV from the Fidelity Drive
        # folder, so there's nothing to upload. Needs the Google client
        # libraries and credentials, so it's left out in the browser-only
        # (html-wasm) build, where uploading is the only option.
        from src.fidelity_parser import latest_account_history_from_drive
    except Exception:
        latest_account_history_from_drive = None

    return (
        PNL, calculate_ytd_pnl, get_sp500_weekly_returns,
        latest_account_history_from_drive, mo, nav_html, parse_history, pd,
    )


@app.cell
def __(PNL, mo, nav_html):
    mo.Html(nav_html(PNL))
    return


@app.cell
def __(mo):
    # ── Styles scoped to .terminal wrapper — avoids fighting Marimo's shell ──
    mo.Html("""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&family=IBM+Plex+Sans:wght@300;400;500&display=swap');

      /* The page behind the cells is dark too (marimo's own theme is set
         in .marimo.toml), so the gaps between sections don't show white */
      body { background: #0a0c0f; }

      /* marimo's "running" indicator: a ring in the middle of the screen
         instead of its hourglass in the top-left corner. Like the hourglass
         it only appears once cells have run for a second, so a quick
         dropdown change doesn't flash it. */
      [data-testid="loading-indicator"] {
        position: fixed;
        top: 50%;
        left: 50%;
        width: 44px;
        height: 44px;
        margin: -22px 0 0 -22px;
        border-radius: 50%;
        border: 3px solid #1e2330;
        border-top-color: #00d17a;
        box-shadow: 0 0 0 10px rgba(10, 12, 15, 0.85);
        background: rgba(10, 12, 15, 0.85);
        animation: t-spin 0.8s linear infinite, t-appear 0.2s ease-out 1s both;
      }
      [data-testid="loading-indicator"] .running-app-icon { display: none; }
      @keyframes t-spin { to { transform: rotate(360deg); } }
      @keyframes t-appear { from { opacity: 0; } to { opacity: 1; } }

      .terminal {
        background: #0a0c0f;
        color: #c8d0e0;
        font-family: 'IBM Plex Sans', sans-serif;
        width: 100%;
        box-sizing: border-box;
      }

      .terminal * { box-sizing: border-box; }

      /* ── Header ── */
      .t-header {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        padding: 2rem 2.5rem 1.5rem;
        border-bottom: 1px solid #1e2330;
      }
      .t-title {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.3rem;
        font-weight: 500;
        color: #e8edf5;
        letter-spacing: 0.08em;
        text-transform: uppercase;
      }
      .t-subtitle {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.9rem;
        color: #E8890C;
        letter-spacing: 0.12em;
        margin-top: 0.3rem;
      }
      .t-badge {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.82rem;
        letter-spacing: 0.1em;
        color: #00d17a;
        border: 1px solid #00412a;
        background: rgba(0,209,122,0.05);
        padding: 0.25rem 0.6rem;
        border-radius: 2px;
      }

      /* ── KPI strip ── */
      .t-kpis {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1px;
        background: #1e2330;
        border-bottom: 1px solid #1e2330;
      }
      .t-kpi {
        background: #111318;
        padding: 1.4rem 1.8rem;
        position: relative;
      }
      .t-kpi::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 2px;
      }
      .t-kpi.pos::before { background: #00d17a; }
      .t-kpi.neg::before { background: #ff4d6a; }
      .t-kpi.amb::before { background: #f5a623; }

      .t-kpi-label {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.82rem;
        letter-spacing: 0.15em;
        color: #E8890C;
        text-transform: uppercase;
        margin-bottom: 0.6rem;
      }
      .t-kpi-value {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 2rem;
        font-weight: 600;
        line-height: 1;
      }
      .t-kpi-value.pos { color: #00d17a; }
      .t-kpi-value.neg { color: #ff4d6a; }
      .t-kpi-value.amb { color: #f5a623; }
      .t-kpi-value.hi  { color: #e8edf5; }
      .t-kpi-sub {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.85rem;
        color: #E8890C;
        margin-top: 0.45rem;
      }

      /* ── Section label ── */
      .t-section {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.82rem;
        letter-spacing: 0.16em;
        color: #E8890C;
        text-transform: uppercase;
        padding: 1.4rem 1.8rem 0.7rem;
        border-top: 1px solid #1e2330;
        background: #13161d;
        border-bottom: 1px solid #1e2330;
      }

      /* ── Tables ── */
      .t-table {
        width: 100%;
        border-collapse: collapse;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.95rem;
      }
      .t-table th {
        text-align: left;
        font-size: 0.78rem;
        font-weight: 500;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: #E8890C;
        padding: 0.6rem 1.8rem;
        border-bottom: 1px solid #1e2330;
        background: #0a0c0f;
      }
      .t-table td {
        padding: 0.75rem 1.8rem;
        border-bottom: 1px solid #1a1e28;
        color: #c8d0e0;
      }
      .t-table tr:last-child td { border-bottom: none; }
      .t-table tr:hover td { background: rgba(255,255,255,0.018); }

      .t-table td.tk   { font-weight: 600; color: #e8edf5; letter-spacing: 0.06em; }
      .t-table td.pos  { color: #00d17a; }
      .t-table td.neg  { color: #ff4d6a; }
      .t-table td.dim  { color: #c8d0e0; }

      /* ── Win/Loss pill bar ── */
      .pill {
        height: 3px;
        border-radius: 2px;
        overflow: hidden;
        width: 72px;
        background: #3d0f18;
        margin-top: 5px;
      }
      .pill-fill { height: 100%; background: #00d17a; border-radius: 2px; }

      /* ── Drill header ── */
      .t-drill-header {
        display: flex;
        align-items: center;
        gap: 0.9rem;
        padding: 1.2rem 1.8rem 0.6rem;
        border-top: 1px solid #1e2330;
      }
      .t-drill-ticker {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.3rem;
        font-weight: 600;
        color: #e8edf5;
        letter-spacing: 0.08em;
      }
      .t-drill-meta {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.85rem;
        color: #E8890C;
        letter-spacing: 0.1em;
        text-transform: uppercase;
      }

      /* ── Upload prompt ── */
      .t-upload-prompt {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        min-height: 40vh;
        gap: 0.8rem;
        border-top: 1px solid #1e2330;
      }
      .t-upload-title {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 1.1rem;
        letter-spacing: 0.14em;
        color: #e8edf5;
        text-transform: uppercase;
      }
      .t-upload-hint {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.85rem;
        color: #E8890C;
        letter-spacing: 0.1em;
      }

      /* ── Upload widget override — make it blend in ── */
      .t-upload-source {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.8rem;
        color: #8a93a6;
        margin-top: 0.6rem;
      }
      .t-upload-row {
        padding: 1rem 1.8rem;
        border-bottom: 1px solid #1e2330;
        background: #0e1014;
      }

      /* ── Collapsible tables (same as the spending dashboard) ── A
         <details>/<summary> pair needs no JS: the summary line stays visible
         with an at-a-glance figure, and the table opens on click. */
      .t-collapsible summary {
        cursor: pointer;
        list-style: none;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        padding: 0.9rem 1.8rem;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.85rem;
        color: #c8d0e0;
      }
      .t-collapsible summary::-webkit-details-marker { display: none; }
      .t-collapsible summary::marker { content: ""; }
      .t-collapsible summary:hover { background: rgba(255,255,255,0.02); }
      .t-collapsible summary::after {
        content: '▸';
        color: #E8890C;
        font-size: 0.8rem;
        flex-shrink: 0;
        transition: transform 0.15s ease;
      }
      .t-collapsible[open] summary::after { transform: rotate(90deg); }
      .t-collapsible-hint { color: #7a8296; }
      .t-collapsible summary .pos { color: #00d17a; }
      .t-collapsible summary .neg { color: #ff4d6a; }

      /* ── Side-by-side comparison sections (best/worst, longest/shortest) ── */
      .t-two-col {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1px;
        background: #1e2330;
        border-top: 1px solid #1e2330;
      }

      /* ── Tables scroll within their own box on narrow screens instead of
         blowing out the page width ── */
      .t-table-wrap { overflow-x: auto; }

      /* ── Mobile ── */
      @media (max-width: 640px) {
        .t-header { flex-wrap: wrap; gap: 0.6rem; padding: 1.4rem 1.2rem 1rem; }
        .t-kpis { grid-template-columns: repeat(2, 1fr); }
        .t-kpi { padding: 1rem 1.1rem; }
        .t-kpi-value { font-size: 1.5rem; }
        .t-section { padding: 1.1rem 1.2rem 0.6rem; }
        .t-table th, .t-table td { padding: 0.6rem 1rem; }
        .t-table { font-size: 0.85rem; }
        .t-two-col { grid-template-columns: 1fr; }
        .t-drill-header { padding: 1rem 1.2rem 0.6rem; flex-wrap: wrap; }
        .t-upload-row { padding: 0.8rem 1.2rem; }
        .t-collapsible summary { padding: 0.8rem 1.2rem; }
      }
    </style>
    """)
    return


@app.cell
def __(mo):
    # ── File upload ────────────────────────────────────────────────────────
    upload = mo.ui.file(label="Upload Fidelity CSV", filetypes=[".csv"])
    return (upload,)


@app.cell
def __(latest_account_history_from_drive):
    # ── Newest account-history CSV from Google Drive, when configured ──────
    drive_file, drive_error = None, None
    if latest_account_history_from_drive is not None:
        try:
            drive_file = latest_account_history_from_drive()
        except Exception as e:  # shown next to the upload widget instead
            drive_error = f"{type(e).__name__}: {e}"
    return drive_error, drive_file


@app.cell
def __(drive_error, drive_file, mo, upload):
    # ── Always render the upload widget at the top of the page ─────────────
    import html as _html

    if upload.value:
        _source = f"Using your upload: {_html.escape(upload.value[0].name)}"
    elif drive_file:
        _modified = drive_file["modified"][:10]
        _source = (
            f"Using {_html.escape(drive_file['name'])} from Google Drive"
            f" (updated {_modified}) · upload a CSV to use a different file"
        )
    elif drive_error:
        _source = f"Couldn't load from Google Drive ({_html.escape(drive_error)}) · upload a CSV instead"
    else:
        _source = ""
    mo.vstack([
        mo.Html('<div class="t-upload-row">'),
        upload,
        mo.Html(f'<div class="t-upload-source">{_source}</div></div>' if _source else "</div>"),
    ])
    return


@app.cell
def __(drive_file, mo, pd, upload, parse_history):
    # ── Parse CSV ──────────────────────────────────────────────────────────
    EXCLUDE = {
        "FZROX", "SPAXX", "VTI", "VTV", "VBR",
        "VOE", "SLV", "FZILX", "FSKAX",
    }

    # An upload takes priority over the file from Drive
    if upload.value:
        _contents = upload.value[0].contents
    else:
        _contents = drive_file["contents"] if drive_file else None
    parsed_ok = _contents is not None

    if parsed_ok:
        df = parse_history(_contents)
        df = df.dropna(subset=["Symbol", "Price ($)", "Quantity"])
        df = df[~df["Symbol"].isin(EXCLUDE)]
        df = df[df["Symbol"].str.match(r"^[A-Z]{1,5}$")]
    else:
        df = pd.DataFrame()

    mo.md("")
    return df, EXCLUDE, parsed_ok


@app.cell
def __(pd, df, parsed_ok, calculate_ytd_pnl):
    # ── FIFO engine ────────────────────────────────────────────────────────
    if parsed_ok:
        realized_pnl, _missing = calculate_ytd_pnl(df)
        trades_df = pd.DataFrame(realized_pnl).rename(
            columns={"symbol": "ticker", "gain_loss": "pnl"}
        )
    else:
        trades_df = pd.DataFrame()

    return (trades_df,)


@app.cell
def __(mo, trades_df, parsed_ok):
    # ── Full dashboard rendered as one dark container ──────────────────────

    if not parsed_ok or trades_df.empty:
        content = mo.Html(f"""
        <div class="terminal">
          <div class="t-header">
            <div>
              <div class="t-title">⬡ Trade P&amp;L Terminal</div>
              <div class="t-subtitle">Fidelity Roth IRA · FIFO Realized Gains · 2026</div>
            </div>
            <div class="t-badge">INDIVIDUAL STOCKS ONLY</div>
          </div>
          <div class="t-upload-prompt">
            <div class="t-upload-title">Upload Fidelity Activity CSV</div>
            <div class="t-upload-hint">Accounts_History_YYYY.csv · Individual stocks · FIFO matched</div>
          </div>
        </div>
        """)
        mo.stop(True, content)

    # -- Compute KPIs --
    total_pnl  = trades_df["pnl"].sum()
    wins       = int((trades_df["pnl"] > 0).sum())
    losses     = int((trades_df["pnl"] < 0).sum())
    lots       = len(trades_df)
    wr         = wins / lots * 100 if lots else 0
    best       = trades_df.loc[trades_df["pnl"].idxmax()]
    worst      = trades_df.loc[trades_df["pnl"].idxmin()]

    pnl_cls    = "pos" if total_pnl >= 0 else "neg"
    pnl_sign   = "+" if total_pnl >= 0 else ""
    wr_cls     = "pos" if wr >= 50 else "amb"

    # -- Ticker summary (avg_pct weighted by cost basis = buy_price × qty) --
    cb_series = trades_df["buy_price"] * trades_df["qty"]
    wp_series = trades_df["pct_gain"] * cb_series

    summary = (
        trades_df.assign(cost_basis=cb_series, weighted_pct=wp_series)
        .groupby("ticker")
        .agg(
            total_pnl = ("pnl",          "sum"),
            num_lots  = ("pnl",          "count"),
            wins      = ("pnl",          lambda x: (x > 0).sum()),
            losses    = ("pnl",          lambda x: (x < 0).sum()),
            sum_w_pct = ("weighted_pct", "sum"),
            sum_cb    = ("cost_basis",   "sum"),
            best_lot  = ("pnl",          "max"),
        )
        .reset_index()
    )
    summary["avg_pct"] = summary.apply(lambda r: r.sum_w_pct / r.sum_cb if r.sum_cb > 0 else 0.0, axis=1)
    summary = summary.drop(columns=["sum_w_pct", "sum_cb"]).sort_values("total_pnl", ascending=False)

    def summary_row(r):
        pc  = "pos" if r.total_pnl >= 0 else "neg"
        sg  = "+" if r.total_pnl > 0 else ("" if r.total_pnl == 0 else "")
        ac  = "pos" if r.avg_pct >= 0 else "neg"
        bar = int(r.wins / r.num_lots * 100) if r.num_lots else 0
        # best_lot sign and color
        if r.best_lot > 0:
            blc, blsg = "pos", "+"
        elif r.best_lot < 0:
            blc, blsg = "neg", "-"
        else:
            blc, blsg = "pos", ""
        bl_abs = abs(r.best_lot)
        # total_pnl sign (reuse abs to avoid -0.00)
        total_abs = abs(r.total_pnl)
        sg = "+" if r.total_pnl > 0 else ("-" if r.total_pnl < 0 else "")
        return f"""
        <tr>
          <td class="tk">{r.ticker}</td>
          <td class="{pc}">{sg}${total_abs:,.2f}</td>
          <td class="{ac}">{r.avg_pct:+.2f}%</td>
          <td class="dim">{int(r.num_lots)}</td>
          <td>
            <span style="color:#00d17a">{int(r.wins)}W</span>
            <span style="color:#E8890C"> / </span>
            <span style="color:#ff4d6a">{int(r.losses)}L</span>
            <div class="pill"><div class="pill-fill" style="width:{bar}%"></div></div>
          </td>
          <td class="{blc}">{blsg}${bl_abs:,.2f}</td>
        </tr>"""

    summary_rows = "".join(summary_row(r) for _, r in summary.iterrows())

    # -- Top 5 / Bottom 5 lots by % gain --
    sorted_lots  = trades_df.sort_values("pct_gain", ascending=False).reset_index(drop=True)
    top5         = sorted_lots.head(5)
    bottom5      = sorted_lots.tail(5).sort_values("pct_gain")

    def extremes_row(r, cls):
        pnl_abs = abs(r.pnl)
        if r.pnl > 0:   sg = "+"
        elif r.pnl < 0: sg = "-"
        else:            sg = ""
        xc = "neg" if r.pct_gain < 0 else "pos"
        xsg = "-" if r.pct_gain < 0 else ("+" if r.pct_gain > 0 else "")
        return f"""
        <tr>
          <td class="tk">{r.ticker}</td>
          <td class="dim">{r.sell_date.strftime('%Y-%m-%d')}</td>
          <td class="{cls}">{sg}${pnl_abs:,.2f}</td>
          <td class="{xc}">{xsg}{abs(r.pct_gain):.2f}%</td>
        </tr>"""

    top5_rows    = "".join(extremes_row(r, "pos") for _, r in top5.iterrows())
    bottom5_rows = "".join(extremes_row(r, "neg") for _, r in bottom5.iterrows())

    # -- Top 5 Longest / Shortest trades by hold duration --
    trades_df["hold_days"] = (trades_df["sell_date"] - trades_df["buy_date"]).dt.days
    sorted_by_duration = trades_df.sort_values("hold_days", ascending=False).reset_index(drop=True)
    longest5  = sorted_by_duration.head(5)
    shortest5 = sorted_by_duration.tail(5).sort_values("hold_days")

    def duration_row(r):
        days = int(r.hold_days)
        xc  = "pos" if r.pct_gain >= 0 else "neg"
        xsg = "+" if r.pct_gain > 0 else ("-" if r.pct_gain < 0 else "")
        return f"""
        <tr>
          <td class="tk">{r.ticker}</td>
          <td class="dim">{r.buy_date.strftime('%Y-%m-%d')}</td>
          <td class="dim">{r.sell_date.strftime('%Y-%m-%d')}</td>
          <td class="amb">{days}d</td>
          <td class="{xc}">{xsg}{abs(r.pct_gain):.2f}%</td>
        </tr>"""

    longest5_rows  = "".join(duration_row(r) for _, r in longest5.iterrows())
    shortest5_rows = "".join(duration_row(r) for _, r in shortest5.iterrows())

    # -- Monthly realized P&L --
    monthly = (
        trades_df.assign(month=trades_df["sell_date"].dt.to_period("M"))
        .groupby("month")
        .agg(
            pnl   =("pnl", "sum"),
            lots  =("pnl", "count"),
            wins  =("pnl", lambda x: (x > 0).sum()),
            losses=("pnl", lambda x: (x < 0).sum()),
        )
        .reset_index()
        .sort_values("month")
    )
    monthly["pnl"] = monthly["pnl"].round(2)
    monthly["cum_pnl"] = monthly["pnl"].cumsum().round(2)

    def monthly_row(r):
        pc  = "pos" if r.pnl >= 0 else "neg"
        sg  = "+" if r.pnl > 0 else ("-" if r.pnl < 0 else "")
        cc  = "pos" if r.cum_pnl >= 0 else "neg"
        csg = "+" if r.cum_pnl > 0 else ("-" if r.cum_pnl < 0 else "")
        return f"""
        <tr>
          <td class="tk">{r.month.strftime('%b %Y')}</td>
          <td class="{pc}">{sg}${abs(r.pnl):,.2f}</td>
          <td class="dim">{int(r.lots)}</td>
          <td>
            <span style="color:#00d17a">{int(r.wins)}W</span>
            <span style="color:#E8890C"> / </span>
            <span style="color:#ff4d6a">{int(r.losses)}L</span>
          </td>
          <td class="{cc}">{csg}${abs(r.cum_pnl):,.2f}</td>
        </tr>"""

    monthly_rows = "".join(monthly_row(r) for _, r in monthly.iterrows())

    # For the Monthly Realized P&L fold's summary line
    _best_month = monthly.loc[monthly["pnl"].idxmax()]
    _best_month_cls = "pos" if _best_month.pnl >= 0 else "neg"
    _best_month_sign = "+" if _best_month.pnl >= 0 else "-"

    dashboard = mo.Html(f"""
    <div class="terminal">
      <div class="t-header">
        <div>
          <div class="t-title">⬡ Trade P&amp;L Terminal</div>
          <div class="t-subtitle">Fidelity Roth IRA · FIFO Realized Gains · 2026</div>
        </div>
        <div class="t-badge">INDIVIDUAL STOCKS ONLY</div>
      </div>

      <div class="t-kpis">
        <div class="t-kpi {pnl_cls}">
          <div class="t-kpi-label">Realized P&amp;L</div>
          <div class="t-kpi-value {pnl_cls}">{pnl_sign}${total_pnl:,.2f}</div>
          <div class="t-kpi-sub">{lots} closed lots matched</div>
        </div>
        <div class="t-kpi {wr_cls}">
          <div class="t-kpi-label">Win Rate</div>
          <div class="t-kpi-value {wr_cls}">{wr:.1f}%</div>
          <div class="t-kpi-sub">{wins}W &nbsp;·&nbsp; {losses}L</div>
        </div>
        <div class="t-kpi pos">
          <div class="t-kpi-label">Best Trade</div>
          <div class="t-kpi-value pos">+${best['pnl']:,.2f}</div>
          <div class="t-kpi-sub">{best['ticker']} &nbsp;·&nbsp; {best['pct_gain']:+.1f}%</div>
        </div>
        <div class="t-kpi neg">
          <div class="t-kpi-label">Worst Trade</div>
          <div class="t-kpi-value neg">${worst['pnl']:,.2f}</div>
          <div class="t-kpi-sub">{worst['ticker']} &nbsp;·&nbsp; {worst['pct_gain']:+.1f}%</div>
        </div>
      </div>

      <div class="t-section">Performance by Ticker</div>
      <details class="t-collapsible">
        <summary><span class="t-collapsible-hint">{len(summary)} tickers</span><span class="{pnl_cls}">{pnl_sign}${total_pnl:,.2f} realized</span></summary>
        <div class="t-table-wrap">
        <table class="t-table">
          <thead>
            <tr>
              <th>Ticker</th>
              <th>Realized P&amp;L</th>
              <th>Avg % Gain</th>
              <th>Lots</th>
              <th>Win / Loss</th>
              <th>Best Lot</th>
            </tr>
          </thead>
          <tbody>{summary_rows}</tbody>
        </table>
      </div>
      </details>

      <div class="t-two-col">
        <div style="background:#0a0c0f;">
          <div class="t-section" style="border-top:none;">🏆 Top 5 Best Lots</div>
          <details class="t-collapsible">
            <summary><span class="t-collapsible-hint">{len(top5)} lots</span><span>best {top5.iloc[0]['pct_gain']:+.1f}% · {top5.iloc[0]['ticker']}</span></summary>
            <div class="t-table-wrap">
            <table class="t-table">
              <thead><tr>
                <th>Ticker</th><th>Sold</th><th>P&amp;L</th><th>% Gain</th>
              </tr></thead>
              <tbody>{top5_rows}</tbody>
            </table>
          </div>
          </details>
        </div>
        <div style="background:#0a0c0f;">
          <div class="t-section" style="border-top:none;">💀 Top 5 Worst Lots</div>
          <details class="t-collapsible">
            <summary><span class="t-collapsible-hint">{len(bottom5)} lots</span><span>worst {bottom5.iloc[0]['pct_gain']:+.1f}% · {bottom5.iloc[0]['ticker']}</span></summary>
            <div class="t-table-wrap">
            <table class="t-table">
              <thead><tr>
                <th>Ticker</th><th>Sold</th><th>P&amp;L</th><th>% Gain</th>
              </tr></thead>
              <tbody>{bottom5_rows}</tbody>
            </table>
          </div>
          </details>
        </div>
      </div>

      <div class="t-two-col">
        <div style="background:#0a0c0f;">
          <div class="t-section" style="border-top:none;">⏳ Top 5 Longest Trades</div>
          <details class="t-collapsible">
            <summary><span class="t-collapsible-hint">{len(longest5)} lots</span><span>longest {int(longest5.iloc[0]['hold_days'])}d · {longest5.iloc[0]['ticker']}</span></summary>
            <div class="t-table-wrap">
            <table class="t-table">
              <thead><tr>
                <th>Ticker</th><th>Bought</th><th>Sold</th><th>Hold</th><th>% Gain</th>
              </tr></thead>
              <tbody>{longest5_rows}</tbody>
            </table>
          </div>
          </details>
        </div>
        <div style="background:#0a0c0f;">
          <div class="t-section" style="border-top:none;">⚡ Top 5 Shortest Trades</div>
          <details class="t-collapsible">
            <summary><span class="t-collapsible-hint">{len(shortest5)} lots</span><span>shortest {int(shortest5.iloc[0]['hold_days'])}d · {shortest5.iloc[0]['ticker']}</span></summary>
            <div class="t-table-wrap">
            <table class="t-table">
              <thead><tr>
                <th>Ticker</th><th>Bought</th><th>Sold</th><th>Hold</th><th>% Gain</th>
              </tr></thead>
              <tbody>{shortest5_rows}</tbody>
            </table>
          </div>
          </details>
        </div>
      </div>

      <div class="t-section">📅 Monthly Realized P&amp;L</div>
      <details class="t-collapsible">
        <summary><span class="t-collapsible-hint">{len(monthly)} months</span><span class="{_best_month_cls}">best month {_best_month.month.strftime('%b')} · {_best_month_sign}${abs(_best_month.pnl):,.2f}</span></summary>
        <div class="t-table-wrap">
        <table class="t-table">
          <thead><tr>
            <th>Month</th><th>Realized P&amp;L</th><th>Lots</th><th>W / L</th><th>Cumulative</th>
          </tr></thead>
          <tbody>{monthly_rows}</tbody>
        </table>
      </div>
      </details>

    </div>
    """)

    dashboard
    return (
        dashboard, summary, summary_rows, total_pnl, wins, losses,
        lots, wr, best, worst, pnl_cls, pnl_sign, wr_cls,
        top5, bottom5, top5_rows, bottom5_rows,
        longest5, shortest5, longest5_rows, shortest5_rows,
        monthly, monthly_rows,
    )


@app.cell
def __(mo, trades_df, parsed_ok):
    # ── Drill-down selector ────────────────────────────────────────────────
    if not parsed_ok or trades_df.empty or "ticker" not in trades_df.columns:
        ticker_list = []
    else:
        ticker_list = sorted(trades_df["ticker"].unique().tolist())
    ticker_select = mo.ui.dropdown(
        options = ["— select ticker —"] + ticker_list,
        value   = "— select ticker —",
        label   = "Drill into ticker",
    )
    mo.vstack([
        mo.Html('<div class="t-upload-row" style="display:flex;align-items:center;gap:2rem;">'),
        ticker_select,
        mo.Html("""
          <span style="font-family:'IBM Plex Mono',monospace;font-size:0.78rem;
                       color:#E8890C;letter-spacing:0.12em;">
            &#9654;&nbsp; SELECT A TICKER TO SEE INDIVIDUAL LOTS
          </span>
        """),
        mo.Html("</div>"),
    ])
    return ticker_list, ticker_select


@app.cell
def __(mo, trades_df, ticker_select):
    # ── Drill-down detail ──────────────────────────────────────────────────
    if not ticker_select.value or ticker_select.value.startswith("—"):
        mo.stop(True)

    sel    = ticker_select.value
    detail = trades_df[trades_df["ticker"] == sel].copy()
    tk_pnl = detail["pnl"].sum()
    tk_sgn = "+" if tk_pnl >= 0 else ""
    tk_col = "#00d17a" if tk_pnl >= 0 else "#ff4d6a"

    def detail_row(r):
        pnl_abs = abs(r.pnl)
        pct_abs = abs(r.pct_gain)
        if r.pnl > 0:
            pc, sg = "pos", "+"
        elif r.pnl < 0:
            pc, sg = "neg", "-"
        else:
            pc, sg = "pos", ""
        xc = "neg" if r.pct_gain < 0 else "pos"
        xsg = "-" if r.pct_gain < 0 else ("+" if r.pct_gain > 0 else "")
        return f"""
        <tr>
          <td class="dim">{r.buy_date.strftime('%Y-%m-%d')}</td>
          <td class="dim">{r.sell_date.strftime('%Y-%m-%d')}</td>
          <td>{r.qty:.3f}</td>
          <td>${r.buy_price:,.2f}</td>
          <td>${r.sell_price:,.2f}</td>
          <td class="{pc}">{sg}${pnl_abs:,.2f}</td>
          <td class="{xc}">{xsg}{pct_abs:.2f}%</td>
        </tr>"""

    detail_rows = "".join(detail_row(r) for _, r in detail.iterrows())

    mo.Html(f"""
    <div class="terminal" style="min-height:auto">
      <div class="t-drill-header">
        <span class="t-drill-ticker">{sel}</span>
        <span class="t-drill-meta">· {len(detail)} lots ·</span>
        <span class="t-drill-meta" style="color:{tk_col}">{tk_sgn}${tk_pnl:,.2f} total</span>
      </div>
      <div class="t-table-wrap">
        <table class="t-table">
          <thead>
            <tr>
              <th>Buy Date</th><th>Sell Date</th><th>Qty</th>
              <th>Buy Price</th><th>Sell Price</th><th>P&amp;L</th><th>% Gain</th>
            </tr>
          </thead>
          <tbody>{detail_rows}</tbody>
        </table>
      </div>
    </div>
    """)
    return sel, detail, tk_pnl, tk_sgn, tk_col, detail_rows


@app.cell
def __(mo, pd, trades_df, parsed_ok):
    # ── Weekly realized P&L, reindexed across every week of the year ────────
    if not parsed_ok or trades_df.empty:
        mo.stop(True)

    _year = trades_df["sell_date"].dt.year.min()
    week_index = pd.period_range(
        start=pd.Timestamp(year=_year, month=1, day=1),
        end=min(pd.Timestamp(year=_year, month=12, day=31), pd.Timestamp.today()),
        freq="W-FRI",
    )

    weekly_pnl = (
        trades_df.assign(week=trades_df["sell_date"].dt.to_period("W-FRI"))
        .groupby("week")["pnl"]
        .sum()
        .reindex(week_index, fill_value=0.0)
    )
    weekly_pnl.index.name = "week"
    weekly_pnl = weekly_pnl.reset_index()
    weekly_pnl["week_end"] = weekly_pnl["week"].apply(lambda p: p.end_time.normalize())
    return week_index, weekly_pnl


@app.cell
def __(weekly_pnl, get_sp500_weekly_returns):
    # ── S&P 500 weekly benchmark (Stooq, free, no API key) ──────────────────
    spy = get_sp500_weekly_returns()
    spy_available = not spy.empty

    weekly = weekly_pnl.merge(spy, on="week", how="left") if spy_available else weekly_pnl.assign(pct_return=float("nan"))
    return spy, spy_available, weekly


@app.cell
def __(mo, pd, weekly, spy_available):
    # ── Weekly Realized P&L vs. S&P 500 chart ───────────────────────────────
    W, H = 1200, 340
    ML, MR, MT, MB = 70, 70, 20, 50
    PW, PH = W - ML - MR, H - MT - MB
    n = len(weekly)
    slot = PW / n
    bar_w = slot * 0.6
    zero_y = MT + PH / 2

    max_abs_pnl = max(weekly["pnl"].abs().max(), 1.0)
    pnl_scale = (PH / 2) / max_abs_pnl

    bars = []
    for i, row in enumerate(weekly.itertuples()):
        x = ML + i * slot + (slot - bar_w) / 2
        bh = abs(row.pnl) * pnl_scale
        y = zero_y - bh if row.pnl >= 0 else zero_y
        color = "#00d17a" if row.pnl >= 0 else "#ff4d6a"
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" '
            f'height="{max(bh, 0.5):.1f}" fill="{color}" opacity="0.85"/>'
        )

    line_svg = ""
    if spy_available and weekly["pct_return"].notna().any():
        max_abs_pct = max(weekly["pct_return"].abs().max(skipna=True), 0.1)
        pct_scale = (PH / 2) / max_abs_pct

        segments, current = [], []
        for i, val in enumerate(weekly["pct_return"]):
            if pd.isna(val):
                if len(current) > 1:
                    segments.append(current)
                current = []
                continue
            cx = ML + i * slot + slot / 2
            cy = zero_y - val * pct_scale
            current.append((cx, cy))
        if len(current) > 1:
            segments.append(current)

        for seg in segments:
            pts = " ".join(f"{px:.1f},{py:.1f}" for px, py in seg)
            line_svg += f'<polyline points="{pts}" fill="none" stroke="#E8890C" stroke-width="2"/>'
        for i, val in enumerate(weekly["pct_return"]):
            if pd.isna(val):
                continue
            cx = ML + i * slot + slot / 2
            cy = zero_y - val * pct_scale
            line_svg += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.5" fill="#E8890C"/>'

    month_labels = []
    seen_months = set()
    for i, we in enumerate(weekly["week_end"]):
        key = (we.year, we.month)
        if key not in seen_months:
            seen_months.add(key)
            cx = ML + i * slot + slot / 2
            month_labels.append(
                f'<text x="{cx:.1f}" y="{H - MB + 18:.1f}" fill="#E8890C" font-size="11" '
                f'text-anchor="middle" font-family="IBM Plex Mono, monospace">{we.strftime("%b")}</text>'
            )

    note = "" if spy_available else """
      <div class="t-kpi-sub" style="padding:0 1.8rem 1rem;color:#ff4d6a;">
        S&amp;P 500 comparison unavailable — could not fetch the weekly benchmark (check network access).
      </div>"""

    chart_svg = f"""
    <svg viewBox="0 0 {W} {H}" width="100%" style="height:auto; display:block;">
      <line x1="{ML}" y1="{zero_y:.1f}" x2="{W - MR}" y2="{zero_y:.1f}" stroke="#1e2330" stroke-width="1"/>
      {"".join(bars)}
      {line_svg}
      {"".join(month_labels)}
    </svg>"""

    mo.Html(f"""
    <div class="terminal" style="min-height:auto">
      <div class="t-section">📈 Weekly Realized P&amp;L vs. S&amp;P 500 ({len(weekly)} weeks)</div>
      <div style="display:flex;gap:1.5rem;padding:1rem 1.8rem 0;font-family:'IBM Plex Mono',monospace;font-size:0.78rem;letter-spacing:0.1em;">
        <span style="color:#00d17a">■ Realized Gain (weekly, $)</span>
        <span style="color:#ff4d6a">■ Realized Loss (weekly, $)</span>
        <span style="color:#E8890C">— S&amp;P 500 weekly return (%)</span>
      </div>
      <div style="padding:0.5rem 1.8rem 1.5rem;">{chart_svg}</div>
      {note}
    </div>
    """)
    return (chart_svg,)


if __name__ == "__main__":
    app.run()