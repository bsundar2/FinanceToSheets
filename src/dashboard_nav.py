"""The menu bar at the top of each dashboard, linking the Overview (finance
dashboard), Net Worth and Swing Trading (P&L tracker) pages, all served by
src/dashboard_server.py, and the spending dashboard SplitwiseToSheets hosts
separately.

Kept free of third-party imports, since pnl_tracker.py also runs in the
browser under Pyodide (marimo's html-wasm export)."""

import html
import os

OVERVIEW = "overview"
NET_WORTH = "net_worth"
PNL = "pnl"
SPENDING = "spending"

# Defaults are the paths dashboard_server.py mounts each app at. The
# spending dashboard runs elsewhere, so it has no link unless its URL is set.
# The last field marks a separate app (its own data, outside the budget
# sheet the Overview and Net Worth pages share), drawn with an arrow icon.
_LINKS = [
    (OVERVIEW, "Overview", "FINANCE_DASHBOARD_URL", "/", False),
    (NET_WORTH, "Net Worth", "NET_WORTH_DASHBOARD_URL", "/net-worth", False),
    (PNL, "Swing Trading", "PNL_DASHBOARD_URL", "/pnl", True),
    (SPENDING, "Spending", "SPENDING_DASHBOARD_URL", "", True),
]

# An arrow out of a box (the usual "external" mark), in the link's color.
_EXTERNAL_ICON = (
    '<svg class="t-nav-ext" viewBox="0 0 24 24" width="11" height="11" '
    'fill="none" stroke="currentColor" stroke-width="2.4" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/>'
    '<path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>'
    "</svg>"
)

_STYLE = """
<style>
  .t-nav {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem 1.6rem;
    padding: 0.8rem 1.8rem;
    background: #0a0c0f;
    border-bottom: 1px solid #1e2330;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.82rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  .t-nav a { color: #8a93a6; text-decoration: none; padding-bottom: 0.2rem; white-space: nowrap; }
  .t-nav a:hover { color: #e8edf5; }
  .t-nav a.active { color: #E8890C; border-bottom: 2px solid #E8890C; }
  .t-nav-ext { display: inline-block; margin-left: 0.4em; vertical-align: 0.05em; opacity: 0.7; }
</style>
"""


_ACTIVE = ' class="active"'


def nav_links(current: str) -> list[tuple[str, str, bool, bool]]:
    """(label, url, is the current page, is a separate app) for each
    dashboard with a URL."""
    links = []
    for key, label, env_var, default, separate in _LINKS:
        url = os.environ.get(env_var, default)
        if url:
            links.append((label, url, key == current, separate))
    return links


def nav_html(current: str) -> str:
    items = []
    for label, url, active, separate in nav_links(current):
        attrs = _ACTIVE if active else ""
        icon = ""
        if separate:
            attrs += ' title="Separate app"'
            icon = _EXTERNAL_ICON
        items.append(
            f'<a href="{html.escape(url)}" target="_top"{attrs}>'
            f"{html.escape(label)}{icon}</a>"
        )
    return f'{_STYLE}<nav class="t-nav">{"".join(items)}</nav>'
