import marimo

__generated_with = "0.6.0"
app = marimo.App(width="full")


@app.cell
def __():
    import html

    import marimo as mo
    import pandas as pd

    from src import personal_finance as pf
    from src.dashboard_nav import OVERVIEW, nav_html
    from src.finance_ui import (
        PALETTE,
        STYLE,
        fold,
        kpi_row,
        kpi_tile,
        legend,
        money,
        stacked_bars_svg,
        table,
    )
    from src.finance_widgets import ShareBar

    return OVERVIEW, PALETTE, STYLE, ShareBar, fold, html, kpi_row, kpi_tile, legend, mo, money, nav_html, pd, pf, stacked_bars_svg, table


@app.cell
def __(OVERVIEW, mo, nav_html):
    mo.Html(nav_html(OVERVIEW))
    return


@app.cell
def __(STYLE, mo):
    # ── Same dark look as the P&L and spending dashboards ──────────────────
    mo.Html(STYLE)
    return


@app.cell
def __(mo):
    reload = mo.ui.button(label="↻ Reload from Sheets", value=0, on_click=lambda n: n + 1)
    large_threshold = mo.ui.number(
        start=500, stop=1_000_000, step=500, value=5000,
    )
    return large_threshold, reload


@app.cell
def __(mo, pd, pf, reload):
    # ── Load the budget spreadsheet (re-runs on Reload) ─────────────────────
    reload.value
    spreadsheet_name = pf.budget_spreadsheet_name()
    today = pd.Timestamp.today().normalize()
    try:
        workbook = pf.load_budget_workbook(spreadsheet_name)
        load_error = None
    except Exception as e:  # shown on the page instead of a stack trace
        workbook, load_error = None, f"{type(e).__name__}: {e}"
    return load_error, spreadsheet_name, today, workbook


@app.cell
def __(html, load_error, mo, pd, pf, spreadsheet_name, today, workbook):
    # ── Parse every tab once ────────────────────────────────────────────────
    if load_error:
        mo.stop(True, mo.Html(f"""
        <div class="terminal"><div class="t-section">Could not load '{html.escape(spreadsheet_name)}'</div>
        <div class="t-note">{html.escape(load_error)}<br><br>Check that the spreadsheet is shared with the
        service account and that GSHEETS_AUTH_FILE points at its credentials.</div></div>"""))

    year = pf.budget_year(spreadsheet_name, today)
    months = pf.months_of(year, today)
    expenses = pf.parse_expense_logs(workbook, year, today)
    budgets = pf.parse_category_budgets(workbook[pf.MONTHLY_EXPENSES_TAB])
    net_worth = pf.parse_net_worth(workbook[pf.NET_WORTH_TAB], months)
    budget_items = pf.parse_budget_items(workbook[pf.BUDGET_TAB])
    savings_log = (
        pf.parse_savings_log(workbook[pf.SAVINGS_LOG_TAB])
        if pf.SAVINGS_LOG_TAB in workbook
        else {}
    )
    buckets = pf.contribution_buckets(workbook[pf.NET_WORTH_TAB], months)
    month_labels = [m.strftime("%b") for m in months]
    return budget_items, budgets, buckets, expenses, month_labels, months, net_worth, savings_log, year


@app.cell
def __(large_threshold, mo, reload):
    mo.Html(f"""
    <div class="t-controls">
      <div>{reload}</div>
      <div><span class="t-control-label">Show one-off expenses of at least ($) separately</span>{large_threshold}</div>
    </div>""")
    return


@app.cell
def __(budgets, expenses, large_threshold, months, net_worth, pf):
    # ── Everything the sections below draw ──────────────────────────────────
    everyday, one_offs = pf.split_large(expenses, large_threshold.value)
    by_group = pf.monthly_by_group(everyday, budgets, months)
    monthly_spend = by_group.sum(axis=1)
    # What you logged as saved each month: the Net Worth tab's contributions
    savings = net_worth[pf.CONTRIBUTIONS]
    changes = pf.net_worth_changes(net_worth)
    return by_group, changes, everyday, monthly_spend, one_offs, savings


@app.cell
def __(mo, money, monthly_spend, net_worth, pf, savings, spreadsheet_name, html, year):
    # ── Header and KPIs ─────────────────────────────────────────────────────
    _spent = monthly_spend.sum()
    _saved = savings.sum()
    _nw = net_worth[pf.NET_WORTH]
    _nw_change = _nw.iloc[-1] - _nw.iloc[0]

    def _kpi(label, value, sub, cls):
        return f"""<div class="t-kpi {cls}"><div class="t-kpi-label">{label}</div>
        <div class="t-kpi-value {cls}">{value}</div><div class="t-kpi-sub">{sub}</div></div>"""

    mo.Html(f"""
    <div class="terminal">
      <div class="t-header">
        <div>
          <div class="t-title">⬡ Yearly Overview</div>
          <div class="t-subtitle">{html.escape(spreadsheet_name)} · Year to Date</div>
        </div>
      </div>
      <div class="t-kpis">
        {_kpi("Spent (your share)", money(_spent), f"{money(_spent / len(monthly_spend))} / month · excl. one-offs", "amb")}
        {_kpi("Saved", money(_saved), f"{money(_saved / len(savings))} / month · logged contributions", "pos" if _saved >= 0 else "neg")}
        {_kpi("Net worth", money(_nw.iloc[-1]), f"as of {_nw.index[-1].strftime('%b')} (live)", "pos")}
        {_kpi("Net worth change", money(_nw_change, signed=True), f"since {_nw.index[0].strftime('%b')} opening", "pos" if _nw_change >= 0 else "neg")}
      </div>
    </div>""")
    return


@app.cell
def __(budget_items, kpi_row, kpi_tile, mo, money, net_worth, pf, savings_log):
    # ── Income, savings and investment income, as on the sheet's Dashboard tab ─
    # A tile only appears when its row is found. Dividends, interest and
    # realized gain/loss come from the older sheet's Savings Log, so a sheet
    # without one shows only the market change.
    def _budget_tile(key, label, sub=None):
        if key not in budget_items:
            return ""
        actual, budget = budget_items[key]
        return kpi_tile(label, actual, sub or f"{money(budget)} budgeted", "amb")

    _market, _share = pf.market_change(net_worth, budget_items)

    def _logged(key, label):
        return kpi_tile(label, savings_log[key], "Savings Log") if key in savings_log else ""

    _match = budget_items.get("401k_match", (0.0, 0.0))[0]
    mo.Html(f"""
    <div class="terminal">
      {kpi_row("Income &amp; savings · this year", [
          _budget_tile("gross_income", "Gross income"),
          _budget_tile("take_home", "Take-home pay"),
          _budget_tile("401k", "401(k) contributions", f"+ {money(_match)} company match" if _match else None),
          _budget_tile("total_savings", "Total savings"),
      ])}
      {kpi_row("Investment income · this year", [
          _logged("dividends", "Dividends"),
          _logged("interest", "Interest"),
          _logged("stock_gain", "Realized gain/loss"),
          kpi_tile("Market change", _market, f"{_share:.1%} of the net worth change · after contributions and 401(k)"),
      ])}
    </div>""")
    return


@app.cell
def __(PALETTE, ShareBar, by_group, mo, money, month_labels, stacked_bars_svg):
    # ── 1. Spending: by group, click one for its sub-categories ────────────
    _colors = PALETTE[: len(by_group.columns)]
    _chart = stacked_bars_svg(
        month_labels, {g: list(by_group[g]) for g in by_group.columns}, _colors
    )
    # The group bar doubles as the chart's legend. A group whose refunds
    # outweigh its spending has no share to draw, so it's a chip only.
    _totals = by_group.sum()
    _shown = [g for g in by_group.columns if _totals[g] > 0]
    group_bar = mo.ui.anywidget(
        ShareBar(
            names=_shown,
            values=[float(_totals[g]) for g in _shown],
            colors=[_colors[list(by_group.columns).index(g)] for g in _shown],
            chips=[[g, f"{g} {money(_totals[g])}"] for g in by_group.columns if g not in _shown],
            allow_none=True,
            height=22,
        )
    )
    mo.Html(f"""
    <div class="terminal">
      <div class="t-section">1 · Spending by month (your share of each Splitwise expense)</div>
      <div class="t-chart">{group_bar}</div>
      <div class="t-chart">{_chart}</div>
      <div class="t-note">Click a group, in the bar or its chip, to see its sub-categories; click it again to close them.</div>
    </div>""")
    return (group_bar,)


@app.cell
def __(PALETTE, budgets, by_group, everyday, expenses, fold, group_bar, html, legend, mo, money, month_labels, months, pf, stacked_bars_svg, table, today, year):
    # ── The selected group's sub-categories, on demand ─────────────────────
    _group = group_bar.value["selected"]
    mo.stop(not _group)
    _df = pf.monthly_by_category(everyday, budgets, months, _group)
    _colors = [PALETTE[i % len(PALETTE)] for i in range(len(_df.columns))]
    _chart = stacked_bars_svg(
        month_labels,
        {html.escape(c): list(_df[c]) for c in _df.columns},
        _colors,
        line=list(by_group[_group]),
    )
    # Budget to date counts one-offs too, as in the tables below
    _vs = pf.budget_vs_actual(expenses, budgets, today, year)
    _vs = _vs[_vs["group"] == _group].set_index("category")
    _spent = _df.sum()
    _rows = []
    for _c in _df.columns:
        _r = _vs.loc[_c] if _c in _vs.index else None
        _rows.append([
            (html.escape(_c), "tk"),
            (money(_spent[_c]), ""),
            (money(_spent[_c] / len(_df)), ""),
            (money(_r["actual"]) if _r is not None else "–", ""),
            (money(_r["budget"]) if _r is not None else "–", ""),
            ((money(_r["over"], signed=True), "neg" if _r["over"] > 0 else "pos") if _r is not None else ("–", "")),
        ])
    _total = by_group[_group].sum()
    mo.Html(f"""
    <div class="terminal">
      <div class="t-section">{html.escape(_group)} · {money(_total)} this year · {money(_total / len(by_group))} / month</div>
      {legend([html.escape(c) for c in _df.columns] + [f"{html.escape(_group)} total"], _colors + ["#e8edf5"])}
      <div class="t-chart">{_chart}</div>
      {fold(f"{len(_rows)} sub-categories", f"{money(_total)} excl. one-offs", table(["Sub-category", "Spent (excl. one-offs)", "Per month", "Spent (all)", "Budget to date", "Over / under"], _rows))}
      <div class="t-note">Sub-categories are the Expense Log's categories, grouped as on the Monthly Expenses tab;
      beyond eight the smallest are summed into Other. The chart leaves out one-offs, like the one above; the
      last three columns count them, as the budget tables below do.</div>
    </div>""")
    return


@app.cell
def __(budgets, everyday, expenses, fold, html, mo, money, one_offs, pf, table, today, year):
    # ── Budget, merchants and one-offs ──────────────────────────────────────

    # Every expense counts against its budget, one-offs included: they're
    # only left out of the charts, where they'd dwarf everything else
    _vs = pf.budget_vs_actual(expenses, budgets, today, year)
    _over = _vs[_vs["over"] > 0].head(8)
    _under = _vs[_vs["over"] < 0].sort_values("over").head(8)

    def _vs_rows(df):
        return [
            [
                (html.escape(r.category), "tk"),
                (money(r.actual), ""),
                (money(r.budget), ""),
                (money(r.over, signed=True), "neg" if r.over > 0 else "pos"),
                (money(r.annual), ""),
            ]
            for r in df.itertuples()
        ]

    _merchants = pf.top_merchants(everyday)
    _merchant_rows = [
        [(html.escape(r.description), "tk"), (money(r.total), ""), (str(r.count), "")]
        for r in _merchants.itertuples()
    ]
    _one_off_rows = [
        [
            (r.date.strftime("%Y-%m-%d"), ""),
            (html.escape(r.description), "tk"),
            (html.escape(r.category), ""),
            (money(r.my_share), "neg" if r.my_share > 0 else "pos"),
        ]
        for r in one_offs.sort_values("date").itertuples()
    ]

    mo.Html(f"""
    <div class="terminal">
      <div class="t-two-col">
        <div>
          <div class="t-section">Over budget so far</div>
          {fold(f"{len(_over)} categories", f"{money(_over['over'].sum(), signed=True)} over", table(["Category", "Spent", "Budget to date", "Over", "Year budget"], _vs_rows(_over)), "neg")}
        </div>
        <div>
          <div class="t-section">Under budget so far</div>
          {fold(f"{len(_under)} categories", f"{money(-_under['over'].sum())} under", table(["Category", "Spent", "Budget to date", "Under", "Year budget"], _vs_rows(_under)), "pos")}
        </div>
      </div>
      <div class="t-two-col">
        <div>
          <div class="t-section">Top merchants</div>
          {fold(f"{len(_merchants)} merchants", f"{money(_merchants['total'].sum())} total", table(["Description", "Your share", "Count"], _merchant_rows))}
        </div>
        <div>
          <div class="t-section">One-offs left out of the charts ({len(one_offs)})</div>
          {fold(f"{len(one_offs)} expenses", f"{money(one_offs['my_share'].sum())} net", table(["Date", "Description", "Category", "Your share"], _one_off_rows))}
        </div>
      </div>
      <div class="t-note">Spent includes one-offs. Budget to date is each category's monthly budget from the Monthly
      Expenses tab times the months elapsed, with the current month prorated by day; the sheet's Variance column
      compares against the whole year's budget instead. Splitwise bills dated after today aren't counted yet.</div>
    </div>""")
    return


@app.cell
def __(fold, mo, money, month_labels, savings, stacked_bars_svg, table):
    # ── 2. Savings by month ─────────────────────────────────────────────────
    _chart = stacked_bars_svg(
        month_labels,
        {"Saved": [max(v, 0) for v in savings],
         "Withdrawn": [min(v, 0) for v in savings]},
        ["#00d17a", "#ff4d6a"],
    )
    _rows = [
        [
            (m.strftime("%b"), "tk"),
            (money(v), "pos" if v >= 0 else "neg"),
            (money(t), "pos" if t >= 0 else "neg"),
        ]
        for m, v, t in zip(savings.index, savings, savings.cumsum())
    ]
    mo.Html(f"""
    <div class="terminal">
      <div class="t-section">2 · Savings by month</div>
      <div class="t-legend"><span style="color:#00d17a">■ Saved</span><span style="color:#ff4d6a">■ Taken out</span></div>
      <div class="t-chart">{_chart}</div>
      {fold(f"{len(savings)} months", f"{money(savings.sum())} saved", table(["Month", "Saved", "Year to date"], _rows), "pos" if savings.sum() >= 0 else "neg")}
      <div class="t-note">Saved is the Monthly Savings Contributions rows at the bottom of the Net Worth tab, the same
      figure as the Budget tab's Take-Home Savings. It's what you logged as put away, not take-home minus spending,
      so a big purchase paid from savings, like a down payment, doesn't lower it.</div>
    </div>""")
    return


@app.cell
def __(PALETTE, buckets, fold, html, legend, mo, money, month_labels, stacked_bars_svg, table):
    # ── Savings by bucket ───────────────────────────────────────────────────
    mo.stop(
        buckets.empty,
        mo.Html('<div class="terminal"><div class="t-note">No savings contributions logged this year.</div></div>'),
    )
    _names = list(buckets.columns)
    _colors = [PALETTE[i % len(PALETTE)] for i in range(len(_names))]
    _chart = stacked_bars_svg(
        month_labels,
        {html.escape(b): list(buckets[b]) for b in _names},
        _colors,
        line=list(buckets.sum(axis=1)),
    )
    _total = buckets.to_numpy().sum()
    _rows = []
    for _b in sorted(_names, key=lambda b: -buckets[b].sum()):
        _sum = buckets[_b].sum()
        _rows.append(
            [(html.escape(_b), "tk")]
            + [(money(v), "pos" if v > 0 else "neg" if v < 0 else "") for v in buckets[_b]]
            + [(money(_sum), "pos" if _sum >= 0 else "neg"), (f"{_sum / _total:.0%}" if _total else "–", "")]
        )
    _rows.append(
        [("Total", "tk")]
        + [(money(v), "pos" if v >= 0 else "neg") for v in buckets.sum(axis=1)]
        + [(money(_total), "pos" if _total >= 0 else "neg"), ("100%" if _total else "–", "")]
    )
    mo.Html(f"""
    <div class="terminal">
      <div class="t-section">Savings by bucket · {money(_total)} this year</div>
      {legend([html.escape(b) for b in _names] + ["Total saved"], _colors + ["#e8edf5"])}
      <div class="t-chart">{_chart}</div>
      <div class="t-note">The same Monthly Savings Contributions rows, one bucket per row. Beyond eight buckets the
      smallest are summed into Other. A negative bar is money taken out.</div>
      {fold(f"{len(_names)} buckets", money(_total), table(["Bucket", *month_labels, "Total", "Share"], _rows), "pos" if _total >= 0 else "neg")}
    </div>""")
    return


@app.cell
def __(PALETTE, changes, fold, legend, mo, money, month_labels, net_worth, pf, stacked_bars_svg, table):
    # ── 3. Net worth ────────────────────────────────────────────────────────
    _components = list(pf.NET_WORTH_COMPONENTS.values())
    _colors = ["#4da3ff", "#00d17a", "#c77dff", "#E8890C", "#ff4d6a"]
    _chart = stacked_bars_svg(
        month_labels,
        {c: list(net_worth[c]) for c in _components},
        _colors,
        line=list(net_worth[pf.NET_WORTH]),
    )
    _change_chart = stacked_bars_svg(
        [m.strftime("%b") for m in changes.index],
        {"You put in": list(changes["saved"]), "Everything else": list(changes["market"])},
        [PALETTE[1], PALETTE[2]],
        line=list(changes["change"]),
    )
    _rows = [
        [
            (m.strftime("%b"), "tk"),
            (money(r.change, signed=True), "pos" if r.change >= 0 else "neg"),
            (money(r.saved, signed=True), "pos" if r.saved >= 0 else "neg"),
            (money(r.market, signed=True), "pos" if r.market >= 0 else "neg"),
        ]
        for m, r in zip(changes.index, changes.itertuples())
    ]
    mo.Html(f"""
    <div class="terminal">
      <div class="t-section">3 · Net worth by month (Net Worth tab subtotals)</div>
      {legend(_components + ["Net worth"], _colors + ["#e8edf5"])}
      <div class="t-chart">{_chart}</div>
      <div class="t-section">Where each month's change came from</div>
      {legend(["You put in", "Everything else", "Total change"], [PALETTE[1], PALETTE[2], "#e8edf5"])}
      <div class="t-chart">{_change_chart}</div>
      {fold(f"{len(changes)} months", f"{money(changes['change'].sum(), signed=True)} change", table(["Month", "Change", "You put in", "Everything else"], _rows), "pos" if changes["change"].sum() >= 0 else "neg")}
      <div class="t-note">"You put in" is the Monthly Savings Contributions rows at the bottom of the Net Worth tab.
      "Everything else" is the rest of the change: markets, home value, paying down debt, and any saving not logged
      there. The current month is still live until you paste its values at month end.</div>
    </div>""")
    return

if __name__ == "__main__":
    app.run()
