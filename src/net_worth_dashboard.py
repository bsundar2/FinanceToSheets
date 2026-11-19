import marimo

__generated_with = "0.6.0"
app = marimo.App(width="full")


@app.cell
def __():
    import html

    import marimo as mo
    import pandas as pd

    from src import personal_finance as pf
    from src.dashboard_nav import NET_WORTH, nav_html
    from src.finance_ui import (
        PALETTE,
        STYLE,
        fold,
        legend,
        money,
        stacked_bars_svg,
        table,
    )
    from src.finance_widgets import ShareBar

    return (
        NET_WORTH,
        PALETTE,
        STYLE,
        ShareBar,
        fold,
        html,
        legend,
        mo,
        money,
        nav_html,
        pd,
        pf,
        stacked_bars_svg,
        table,
    )


@app.cell
def __(NET_WORTH, mo, nav_html):
    mo.Html(nav_html(NET_WORTH))
    return


@app.cell
def __(STYLE, mo):
    # ── Same dark look as the Overview ──────────────────────────────────────
    mo.Html(STYLE)
    return


@app.cell
def __(mo):
    reload = mo.ui.button(
        label="↻ Reload from Sheets", value=0, on_click=lambda n: n + 1
    )
    return (reload,)


@app.cell
def __(mo, pd, pf, reload):
    # ── Load the Net Worth tab and holdings (re-runs on Reload) ────────────
    reload.value
    spreadsheet_name = pf.budget_spreadsheet_name()
    today = pd.Timestamp.today().normalize()
    try:
        tabs = pf.load_net_worth_tabs(spreadsheet_name)
        load_error = None
    except Exception as e:  # shown on the page instead of a stack trace
        tabs, load_error = None, f"{type(e).__name__}: {e}"
    # Row-level holdings are optional: without them each account is just
    # its balance
    try:
        holdings, holdings_error = pf.load_holdings(), None
    except Exception as e:
        holdings, holdings_error = pd.DataFrame(), f"{type(e).__name__}: {e}"
    return holdings, holdings_error, load_error, spreadsheet_name, tabs, today


@app.cell
def __(html, load_error, mo, pf, spreadsheet_name, tabs, today):
    # ── Parse the tabs once ─────────────────────────────────────────────────
    if load_error:
        mo.stop(
            True,
            mo.Html(
                f"""
        <div class="terminal"><div class="t-section">Could not load '{html.escape(spreadsheet_name)}'</div>
        <div class="t-note">{html.escape(load_error)}<br><br>Check that the spreadsheet is shared with the
        service account and that GSHEETS_AUTH_FILE points at its credentials.</div></div>"""
            ),
        )

    values = tabs[pf.NET_WORTH_TAB]
    year = pf.budget_year(spreadsheet_name, today)
    months = pf.months_of(year, today)
    net_worth = pf.parse_net_worth(values, months)
    breakdown = pf.net_worth_breakdown(values, months)
    nw_accounts = pf.net_worth_accounts(values, months)
    month_labels = [m.strftime("%b") for m in months]
    return (
        breakdown,
        month_labels,
        months,
        net_worth,
        nw_accounts,
        year,
    )


@app.cell
def __(html, mo, money, net_worth, pf, reload, spreadsheet_name):
    # ── Header: each category's latest total ────────────────────────────────
    def _kpi(label, value):
        cls = "pos" if value >= 0 else "neg"
        return f"""<div class="t-kpi {cls}"><div class="t-kpi-label">{label}</div>
        <div class="t-kpi-value {cls}">{money(value)}</div>
        <div class="t-kpi-sub">as of {net_worth.index[-1].strftime('%b')}</div></div>"""

    mo.Html(f"""
    <div class="terminal">
      <div class="t-header">
        <div>
          <div class="t-title">⬡ Net Worth</div>
          <div class="t-subtitle">{html.escape(pf.without_year(spreadsheet_name))} · Current balances</div>
        </div>
        <div>{reload}</div>
      </div>
      <div class="t-kpis t-kpis-3">
        {"".join(_kpi(c, net_worth[c].iloc[-1]) for c in [*pf.NET_WORTH_COMPONENTS.values(), pf.NET_WORTH])}
      </div>
    </div>""")
    return


@app.cell
def __(PALETTE, ShareBar, html, mo, money, net_worth, nw_accounts, pf, table):
    # ── Allocation: the overview. Click a category to drill into it below ──
    by_category, by_type = pf.allocation(nw_accounts, net_worth)
    _summary = pf.category_summary(net_worth)
    _liabilities = pf.NET_WORTH_COMPONENTS["liabilit"]
    _names = list(by_category["category"])
    _default = (
        by_category.loc[by_category["value"].idxmax(), "category"]
        if _names
        else _liabilities
    )
    category_bar = mo.ui.anywidget(
        ShareBar(
            names=_names,
            values=[float(v) for v in by_category["value"]],
            colors=[PALETTE[i % len(PALETTE)] for i in range(len(_names))],
            chips=[
                [
                    _liabilities,
                    f"{_liabilities} {money(net_worth[_liabilities].iloc[-1])}",
                ]
            ],
            selected=_default,
        )
    )

    def _pct(w):
        return f"{w:.1%}" if w == w else "–"

    _rows = [
        [
            (html.escape(r.category), "tk"),
            (money(r.value), "pos" if r.value >= 0 else "neg"),
            (_pct(r.weight), ""),
        ]
        for r in _summary.itertuples()
    ]
    mo.Html(f"""
    <div class="terminal">
      <div class="t-section">Allocation · {net_worth.index[-1].strftime('%b')} · {money(by_category["value"].sum())} in assets</div>
      <div class="t-chart">{category_bar}</div>
      <div class="t-note">Click a category, in the bar or its chip, to see its types, accounts and holdings below.
      Real Estate is net of the mortgage; Liabilities aren't part of the split.</div>
      {table(["Category", "Value", "Share of assets"], _rows)}
    </div>""")
    return by_category, by_type, category_bar


@app.cell
def __(
    PALETTE,
    ShareBar,
    by_category,
    by_type,
    category_bar,
    fold,
    html,
    mo,
    money,
    net_worth,
    pf,
    table,
):
    # ── The selected category: its types (click one to filter holdings) ────
    nw_category = category_bar.value["selected"] or by_category["category"].iloc[0]
    _value = net_worth[nw_category].iloc[-1]
    _share = by_category.set_index("category")["weight"].get(nw_category)
    _types = by_type[by_type["category"] == nw_category]
    # A category mixing assets and debts (house and mortgage) has no shares
    # to draw, so it has no type filter either
    _drawable = (
        not _types.empty
        and _types["weight"].notna().all()
        and (_types["value"] > 0).all()
    )
    type_bar = (
        mo.ui.anywidget(
            ShareBar(
                names=list(_types["type"]),
                values=[float(v) for v in _types["value"]],
                colors=[PALETTE[i % len(PALETTE)] for i in range(len(_types))],
                allow_none=True,
                height=26,
            )
        )
        if _drawable
        else None
    )

    def _pct(w):
        return f"{w:.1%}" if w == w else "–"

    _rows = [
        [
            (html.escape(t.type), "tk"),
            (money(t.value), "pos" if t.value >= 0 else "neg"),
            (_pct(t.weight), ""),
            (_pct(t.of_assets), ""),
        ]
        for t in _types.itertuples()
    ]
    _headline = f"{money(_value)}" + (
        f" · {_pct(_share)} of assets" if _share is not None else ""
    )
    if type_bar is not None:
        _body = f"""<div class="t-chart">{type_bar}</div>
        <div class="t-note">Grouped by the Net Worth tab's Type column (C). Click a type to filter the holdings
        below; click it again to clear.</div>"""
    elif nw_category in pf.ASSET_COMPONENTS:
        _body = '<div class="t-note">Its rows mix assets and debts, so it has no shares to draw; its total is the net.</div>'
    else:
        _body = ""
    mo.Html(f"""
    <div class="terminal">
      <div class="t-section">{html.escape(nw_category)} · {_headline}</div>
      {_body}
      {fold(f"{len(_rows)} types", money(_value), table(["Type", "Value", f"Share of {html.escape(nw_category)}", "Share of assets"], _rows)) if _rows else ""}
    </div>""")
    return nw_category, type_bar


@app.cell
def __(
    PALETTE,
    breakdown,
    fold,
    html,
    legend,
    mo,
    money,
    month_labels,
    net_worth,
    nw_category,
    pf,
    stacked_bars_svg,
    table,
):
    # ── Its accounts over the year ──────────────────────────────────────────
    _df = breakdown[nw_category]
    mo.stop(
        _df.empty,
        mo.Html(
            f'<div class="terminal"><div class="t-note">No {html.escape(nw_category)} accounts with a balance.</div></div>'
        ),
    )
    _accounts = list(_df.columns)
    _colors = [PALETTE[i % len(PALETTE)] for i in range(len(_accounts))]
    _chart = stacked_bars_svg(
        month_labels,
        {html.escape(a): list(_df[a]) for a in _accounts},
        _colors,
        line=list(net_worth[nw_category]),
    )
    _total = net_worth[nw_category].iloc[-1]
    _rows = []
    for _a in sorted(_accounts, key=lambda a: -abs(_df[a].iloc[-1])):
        _latest = _df[_a].iloc[-1]
        _rows.append(
            [
                (html.escape(_a), "tk"),
                (money(_latest), "pos" if _latest >= 0 else "neg"),
                (f"{_latest / _total:.0%}" if _total else "–", ""),
            ]
        )
    _headers = ["Account", month_labels[-1], "Share"]
    mo.Html(f"""
    <div class="terminal">
      {legend([html.escape(a) for a in _accounts] + [nw_category + " total"], _colors + ["#e8edf5"])}
      <div class="t-chart">{_chart}</div>
      <div class="t-note">The account rows above the subtotal on the Net Worth tab. Beyond seven accounts the
      smallest are summed into Other, and "{pf.UNLISTED}" is whatever the subtotal holds that its account rows
      don't add up to.</div>
      {fold(f"{len(_accounts)} accounts", f"{money(_total)} in {month_labels[-1]}", table(_headers, _rows), "pos" if _total >= 0 else "neg")}
    </div>""")
    return


@app.cell
def __(html, mo, nw_accounts, nw_category, pf, type_bar):
    # ── Drill into one account, or every account in the category/type ─────
    ALL_ACCOUNTS = "All accounts"
    nw_type = type_bar.value["selected"] if type_bar is not None else ""
    _in_category = nw_accounts[nw_accounts["Category"] == nw_category]
    if nw_type:
        _in_category = _in_category[
            pf.account_types(nw_accounts)[_in_category.index] == nw_type
        ]
    nw_account = mo.ui.dropdown(
        options=[ALL_ACCOUNTS] + list(_in_category["Account"]), value=ALL_ACCOUNTS
    )
    _filter = (
        f' · <span class="tk">{html.escape(nw_type)}</span> only' if nw_type else ""
    )
    mo.hstack(
        [
            mo.Html(f'<div class="t-note">Holdings in</div>'),
            nw_account,
            mo.Html(f'<div class="t-note">{_filter}</div>'),
        ],
        justify="start",
        align="center",
    )
    return ALL_ACCOUNTS, nw_account, nw_type


@app.cell
def __(
    ALL_ACCOUNTS,
    holdings,
    holdings_error,
    html,
    mo,
    money,
    nw_account,
    nw_accounts,
    nw_category,
    nw_type,
    pf,
    table,
):
    _rows_df = pf.category_holdings(holdings, nw_accounts, nw_category)
    if nw_type:
        _types = pf.account_types(nw_accounts)
        _of_type = set(nw_accounts.loc[_types == nw_type, "Account"])
        _rows_df = _rows_df[_rows_df["Account"].isin(_of_type)]
    _all = nw_account.value == ALL_ACCOUNTS
    if not _all:
        _rows_df = _rows_df[_rows_df["Account"] == nw_account.value]
    _total = _rows_df["Value"].sum()
    _max = _rows_df["Value"].abs().max() if not _rows_df.empty else 0

    if (nw_type or not _all) and not _rows_df.empty:
        # Weights within the type or the one account, unless it mixes signs
        _mixed = (_rows_df["Value"] > 0).any() and (_rows_df["Value"] < 0).any()
        _rows_df = _rows_df.assign(
            Weight=float("nan") if _mixed or not _total else _rows_df["Value"] / _total
        )

    def _shares(n):
        if n is None or n != n:
            return ""
        return f"{n:,.0f}" if abs(n) >= 1000 else f"{n:,.4g}"

    def _bar(value):
        width = abs(value) / _max * 100 if _max else 0
        color = "#00d17a" if value >= 0 else "#ff4d6a"
        return (
            f'<div style="width:160px;background:#1a1e28;height:8px">'
            f'<div style="background:{color};opacity:.8;height:8px;width:{width:.1f}%;min-width:1px"></div></div>'
        )

    _rows = [
        ([(html.escape(r.Account), "")] if _all else [])
        + [
            (html.escape(r.Symbol) or "–", "tk"),
            (html.escape(r.Description), ""),
            (_shares(r.Shares), ""),
            (money(r.Value), "pos" if r.Value >= 0 else "neg"),
            (f"{r.Weight:.1%}" if r.Weight == r.Weight else "–", ""),
            (_bar(r.Value), ""),
        ]
        for r in _rows_df.itertuples()
    ]
    _headers = (["Account"] if _all else []) + [
        "Symbol",
        "Description",
        "Shares",
        "Value",
        "Weight",
        "",
    ]
    _note = (
        f"Couldn't read holdings_dump ({html.escape(holdings_error)}), so each account is shown as its balance."
        if holdings_error
        else f"Securities come from the SimpleFIN holdings_dump tab, priced at its last refresh. Each Net Worth row "
        f"takes the holdings accounts its Balance Key matches, or, without a key, an Investments or Retirement row takes "
        f"its institution's accounts whose name contains its type (or the ones left over), scaled by My Share %. "
        f'"{pf.CASH_AND_OTHER}" is the rest of the row\'s balance. When the holdings are worth more than the row '
        f"(usually just prices moving since the sheet's value), there's no row for the difference."
    )
    _scope = " · ".join(
        html.escape(x) for x in [nw_category, nw_type, nw_account.value] if x
    )
    mo.Html(f"""
    <div class="terminal">
      <div class="t-section">{_scope} · {len(_rows)} rows · {money(_total)}</div>
      {table(_headers, _rows) if _rows else '<div class="t-note">Nothing to show.</div>'}
      <div class="t-note">{_note}</div>
    </div>""")
    return


if __name__ == "__main__":
    app.run()
