"""Styling and hand-rolled SVG/HTML helpers shared by the Overview
(finance_dashboard.py) and Net Worth (net_worth_dashboard.py) notebooks,
in the dark look of the P&L and spending dashboards."""

STYLE = """
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
      .t-subtitle, .t-note, .t-kpi-sub, .t-kpi-label, .t-section, .t-legend {
        font-family: 'IBM Plex Mono', monospace;
        color: #E8890C;
      }
      .t-subtitle { font-size: 0.9rem; letter-spacing: 0.12em; margin-top: 0.3rem; }

      .t-kpis {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1px;
        background: #1e2330;
        border-bottom: 1px solid #1e2330;
      }
      .t-kpis.t-kpis-3 { grid-template-columns: repeat(3, 1fr); }
      .t-kpi { background: #111318; padding: 1.4rem 1.8rem; position: relative; }
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
        font-size: 0.82rem;
        letter-spacing: 0.15em;
        text-transform: uppercase;
        margin-bottom: 0.6rem;
      }
      .t-kpi-value {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 2rem;
        font-weight: 600;
        line-height: 1;
        color: #e8edf5;
      }
      .t-kpi-value.pos { color: #00d17a; }
      .t-kpi-value.neg { color: #ff4d6a; }
      .t-kpi-sub { font-size: 0.85rem; margin-top: 0.45rem; }

      .t-section {
        font-size: 0.82rem;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        padding: 1.4rem 1.8rem 0.7rem;
        border-top: 1px solid #1e2330;
        background: #13161d;
        border-bottom: 1px solid #1e2330;
      }
      .t-note { font-size: 0.8rem; letter-spacing: 0.04em; padding: 0.8rem 1.8rem; color: #8a93a6; }
      .t-legend {
        display: flex;
        flex-wrap: wrap;
        gap: 0.4rem 1.5rem;
        padding: 1rem 1.8rem 0;
        font-size: 0.78rem;
        letter-spacing: 0.1em;
      }
      .t-chart { padding: 0.5rem 1.8rem 1.2rem; }

      .t-table-wrap { overflow-x: auto; }
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
      .t-table td { padding: 0.75rem 1.8rem; border-bottom: 1px solid #1a1e28; color: #c8d0e0; }
      .t-table tr:last-child td { border-bottom: none; }
      .t-table td.tk  { font-weight: 600; color: #e8edf5; }
      .t-table td.pos { color: #00d17a; }
      .t-table td.neg { color: #ff4d6a; }

      .t-two-col {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1px;
        background: #1e2330;
        border-top: 1px solid #1e2330;
      }
      .t-two-col > div { background: #0a0c0f; }

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

      .t-controls {
        display: flex;
        flex-wrap: wrap;
        align-items: flex-end;
        gap: 1rem 2rem;
        padding: 1rem 1.8rem;
        border-bottom: 1px solid #1e2330;
        background: #0e1014;
      }
      /* Our own labels: marimo's widget labels use its theme's text color,
         which is dark-on-dark against this bar */
      .t-control-label {
        display: block;
        font-family: 'IBM Plex Mono', monospace;
        font-size: 0.78rem;
        letter-spacing: 0.1em;
        text-transform: uppercase;
        color: #E8890C;
        margin-bottom: 0.4rem;
      }

      @media (max-width: 640px) {
        .t-header { flex-wrap: wrap; gap: 0.6rem; padding: 1.4rem 1.2rem 1rem; }
        .t-kpis, .t-kpis.t-kpis-3 { grid-template-columns: repeat(2, 1fr); }
        .t-kpi { padding: 1rem 1.1rem; }
        .t-kpi-value { font-size: 1.5rem; }
        .t-section { padding: 1.1rem 1.2rem 0.6rem; }
        .t-table th, .t-table td { padding: 0.6rem 1rem; }
        .t-table { font-size: 0.85rem; }
        .t-two-col { grid-template-columns: 1fr; }
        .t-chart, .t-legend, .t-note, .t-controls { padding-left: 1.2rem; padding-right: 1.2rem; }
        .t-collapsible summary { padding: 0.8rem 1.2rem; }
      }
    </style>
"""

PALETTE = [
    "#E8890C",
    "#00d17a",
    "#4da3ff",
    "#c77dff",
    "#ff4d6a",
    "#f5d90a",
    "#5ce1e6",
    "#8a93a6",
]


def money(value, signed=False):
    sign = "-" if value < 0 else ("+" if signed and value > 0 else "")
    return f"{sign}${abs(value):,.0f}"


def legend(names, colors):
    return (
        '<div class="t-legend">'
        + "".join(
            f'<span style="color:{c}">■ {n}</span>' for n, c in zip(names, colors)
        )
        + "</div>"
    )


def stacked_bars_svg(labels, series, colors, line=None, line_color="#e8edf5"):
    """Bars stacked per label: positive values upward from zero, negative
    ones downward. series is {name: [value per label]}; line is an
    optional [value per label] drawn over the bars on the same scale."""
    W, H = 1200, 340
    ML, MR, MT, MB = 80, 20, 20, 40
    PW, PH = W - ML - MR, H - MT - MB
    n = max(len(labels), 1)
    slot = PW / n
    bar_w = slot * 0.6

    tops = [sum(max(s[i], 0) for s in series.values()) for i in range(len(labels))]
    bottoms = [sum(min(s[i], 0) for s in series.values()) for i in range(len(labels))]
    hi = max(tops + (line or []) + [0])
    lo = min(bottoms + (line or []) + [0])
    if hi == lo:
        hi = lo + 1

    def y(v):
        return MT + (hi - v) / (hi - lo) * PH

    parts = [
        f'<line x1="{ML}" y1="{y(0):.1f}" x2="{W - MR}" y2="{y(0):.1f}" stroke="#3a4152" stroke-width="1"/>',
        f'<text x="{ML - 8}" y="{y(hi) + 4:.1f}" fill="#8a93a6" font-size="11" text-anchor="end" font-family="IBM Plex Mono, monospace">{money(hi)}</text>',
    ]
    if lo < 0:
        parts.append(
            f'<text x="{ML - 8}" y="{y(lo) + 4:.1f}" fill="#8a93a6" font-size="11" text-anchor="end" font-family="IBM Plex Mono, monospace">{money(lo)}</text>'
        )
    for i, label in enumerate(labels):
        x = ML + i * slot + (slot - bar_w) / 2
        up, down = 0.0, 0.0
        for (name, values), color in zip(series.items(), colors):
            v = values[i]
            if v >= 0:
                y0, y1 = y(up + v), y(up)
                up += v
            else:
                y0, y1 = y(down), y(down + v)
                down += v
            if y1 - y0 > 0.2:
                parts.append(
                    f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bar_w:.1f}" height="{y1 - y0:.1f}" '
                    f'fill="{color}" opacity="0.85"><title>{label} · {name}: {money(v)}</title></rect>'
                )
        parts.append(
            f'<text x="{ML + i * slot + slot / 2:.1f}" y="{H - MB + 20}" fill="#E8890C" font-size="11" '
            f'text-anchor="middle" font-family="IBM Plex Mono, monospace">{label}</text>'
        )
    if line:
        pts = [(ML + i * slot + slot / 2, y(v)) for i, v in enumerate(line)]
        parts.append(
            '<polyline points="'
            + " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
            + f'" fill="none" stroke="{line_color}" stroke-width="2"/>'
        )
        parts += [
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{line_color}"><title>{labels[i]}: {money(line[i])}</title></circle>'
            for i, (px, py) in enumerate(pts)
        ]
    return f'<svg viewBox="0 0 {W} {H}" width="100%" style="height:auto;display:block;">{"".join(parts)}</svg>'


def table(headers, rows):
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join(
        "<tr>"
        + "".join(f'<td class="{cls}">{text}</td>' for text, cls in row)
        + "</tr>"
        for row in rows
    )
    return f'<div class="t-table-wrap"><table class="t-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def fold(hint, headline, body, cls=""):
    """A table folded under a one-line summary, like the spending
    dashboard's: closed until clicked."""
    return (
        f'<details class="t-collapsible"><summary><span class="t-collapsible-hint">{hint}</span>'
        f'<span class="{cls}">{headline}</span></summary>{body}</details>'
    )


def kpi_tile(label, value, sub, cls=None):
    """One headline tile: a dollar value, green or red by its sign unless a
    class ("amb", "pos", "neg") is given."""
    cls = cls or ("pos" if value >= 0 else "neg")
    return (
        f'<div class="t-kpi {cls}"><div class="t-kpi-label">{label}</div>'
        f'<div class="t-kpi-value {cls}">{money(value)}</div>'
        f'<div class="t-kpi-sub">{sub}</div></div>'
    )


def kpi_row(title, tiles):
    """A titled row of tiles, leaving out empty ones (a figure the sheet
    doesn't have); nothing at all if every tile is empty."""
    tiles = [t for t in tiles if t]
    if not tiles:
        return ""
    cls = "t-kpis t-kpis-3" if len(tiles) == 3 else "t-kpis"
    return (
        f'<div class="t-section">{title}</div><div class="{cls}">{"".join(tiles)}</div>'
    )
