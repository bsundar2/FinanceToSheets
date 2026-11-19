import io
from collections import deque
from pathlib import Path

import pandas as pd


def clean_currency(value):
    if pd.isna(value) or value == "":
        return 0.0
    # Remove $, commas, and handle parentheses for negative numbers if they exist
    cleaned = str(value).replace("$", "").replace(",", "")
    if "(" in cleaned and ")" in cleaned:
        cleaned = "-" + cleaned.replace("(", "").replace(")", "")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_history(path_or_bytes) -> pd.DataFrame:
    """Parses a Fidelity Accounts_History CSV into a clean DataFrame ready for
    calculate_ytd_pnl. Accepts a file path or raw bytes (e.g. from a marimo
    file-upload widget). Locates the real header row dynamically since
    Fidelity prepends a variable number of preamble lines before the
    "Run Date" header."""
    if isinstance(path_or_bytes, bytes):
        raw = path_or_bytes.decode("utf-8-sig")
    else:
        raw = Path(path_or_bytes).read_bytes().decode("utf-8-sig")

    lines = raw.splitlines()
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("Run Date"))
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])), index_col=False, on_bad_lines="skip")

    # Drop rows that don't have a valid Date (e.g. footer)
    df = df[df["Run Date"].notna()].copy()
    df["Run Date"] = pd.to_datetime(df["Run Date"], errors="coerce")
    df = df[df["Run Date"].notna()]

    # Clean numeric columns
    df["Price ($)"] = df["Price ($)"].apply(clean_currency)
    df["Quantity"] = df["Quantity"].apply(clean_currency)
    df["Amount ($)"] = df["Amount ($)"].apply(clean_currency)
    if "Fees ($)" in df.columns:
        df["Fees ($)"] = df["Fees ($)"].apply(clean_currency)
    if "Commission ($)" in df.columns:
        df["Commission ($)"] = df["Commission ($)"].apply(clean_currency)

    # Sort chronologically; on same-day ties, process buys before sells so a
    # same-day buy+sell of the same symbol matches instead of landing in
    # missing_cost_basis.
    df["_is_sell"] = df["Action"].str.upper().str.contains("SOLD")
    df = df.sort_values(by=["Run Date", "_is_sell"], ascending=True).drop(columns="_is_sell")
    return df.reset_index(drop=True)


def calculate_ytd_pnl(df: pd.DataFrame):
    """FIFO-matches "YOU BOUGHT"/"YOU SOLD" rows per symbol.

    Returns (realized_pnl, missing_cost_basis). realized_pnl is a list of
    per-lot-match dicts (one entry per matched buy lot, so a sale spanning
    multiple lots produces multiple entries): symbol, buy_date, sell_date,
    qty, buy_price, sell_price (both per-share), proceeds, cost, gain_loss,
    pct_gain. missing_cost_basis covers sold quantity with no matching buy
    in the given history (e.g. bought before the history window).
    """
    inventory = {}  # symbol -> deque of {qty, unit_cost, date}
    realized_pnl = []
    missing_cost_basis = []

    for _, row in df.iterrows():
        action = str(row["Action"]).upper()
        symbol = row["Symbol"]
        qty = round(abs(row["Quantity"]), 6)
        amount = row["Amount ($)"]
        date = row["Run Date"]

        if qty == 0:
            continue

        if "YOU BOUGHT" in action:
            unit_cost = abs(amount) / qty
            inventory.setdefault(symbol, deque()).append(
                {"qty": qty, "unit_cost": unit_cost, "date": date}
            )

        elif "YOU SOLD" in action:
            unit_proceeds = amount / qty
            sold_qty = qty
            lots = inventory.get(symbol)

            if not lots:
                missing_cost_basis.append({
                    "symbol": symbol, "qty": sold_qty, "proceeds": amount, "date": date
                })
                continue

            while sold_qty > 0.000001 and lots:
                lot = lots[0]
                matched_qty = min(sold_qty, lot["qty"])
                if matched_qty > 0.000001:
                    cost = matched_qty * lot["unit_cost"]
                    proceeds = matched_qty * unit_proceeds
                    realized_pnl.append({
                        "symbol": symbol,
                        "buy_date": lot["date"],
                        "sell_date": date,
                        "qty": matched_qty,
                        "buy_price": lot["unit_cost"],
                        "sell_price": unit_proceeds,
                        "proceeds": proceeds,
                        "cost": cost,
                        "gain_loss": proceeds - cost,
                        "pct_gain": (unit_proceeds / lot["unit_cost"] - 1) * 100 if lot["unit_cost"] else 0.0,
                    })
                lot["qty"] -= matched_qty
                sold_qty -= matched_qty
                if lot["qty"] <= 0.000001:
                    lots.popleft()

            if sold_qty > 0.000001:
                missing_cost_basis.append({
                    "symbol": symbol,
                    "qty": sold_qty,
                    "proceeds": sold_qty * unit_proceeds,
                    "date": date,
                })

    return realized_pnl, missing_cost_basis
