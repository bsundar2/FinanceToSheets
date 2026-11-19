"""Moves an existing budget spreadsheet (the original Budget - 2026 layout,
exported from Google Sheets as .xlsx) onto the household layout
src/budget_template.py builds, as a new .xlsx to import side by side with
the original. The old sheet was one person's, so everything lands in that
person's columns and tabs; the partner's start empty.

What carries over:
- Budget: the income, tax and deduction cells as they were (values and
  formulas), into your Income columns; every category's yearly budget, and
  which categories the Total Expenses formula left out.
- Expense Log: every row, by column name.
- Savings Log -> Accounts: the hand-entered balances, a currency conversion
  applied to the balances it multiplied, and the IMPORTRANGE of SimpleFIN
  balances (now open-ended, so new accounts don't fall off the end).
- Net Worth: past months' values, and each live formula. The old rows held
  your share of a balance; the new ones hold the full balance and your %.
  A formula that read a fixed Savings Log cell becomes a Balance Key (the
  imported account's "(1234)" suffix, or the hand-entered label), so the
  row keeps working when SimpleFIN adds or reorders accounts. A "0.6 * ..."
  factor (in that formula, or around a constant like "=1555000*0.6")
  becomes your % instead, the partner getting the rest, and past values
  are divided by it to get the full balance back. On an "Extra" Real
  Estate row the factor is a credit from the partner's share, so the
  partner's % is minus yours. Other formulas (an IMPORTRANGE of the joint
  ledger, "=M23") are kept at 100% yours, with their cell references (and
  COLUMN() offsets) moved to the new columns and rows. Rows the old Real
  Estate subtotal subtracted (the mortgage balance) are stored negative
  instead, since every subtotal now adds rows up.

Google Sheets' .xlsx export wraps functions Excel doesn't know (IMPORTRANGE,
GOOGLEFINANCE, QUERY) as =IFERROR(__xludf.DUMMYFUNCTION("..."), cached);
unwrap() recovers the original formula."""

import argparse
import datetime
import logging
import re

import openpyxl

from src import budget_template as bt

logger = logging.getLogger(__name__)

_DUMMY_PREFIX = "=IFERROR(__xludf.DUMMYFUNCTION("
_SAVINGS_LOG = "'Savings Log'!"
_KEY_SUFFIX = re.compile(r"\([\w-]+\)\s*$")
_CELL_REF = re.compile(r"(?<![A-Za-z_!'\]])(\$?)([A-Z]{1,3})(\$?)(\d+)(?![\w(])")
_FIXED_BALANCE = re.compile(
    r"^=(?:(-?\d*\.?\d+)\*)?'Savings Log'!\$([BF])\$(\d+)$"
)  # ='Savings Log'!$F$6, =-0.6*'Savings Log'!$F$21, ='Savings Log'!$B$7
_CONVERTED_BALANCE = re.compile(
    r"^='Savings Log'!\$B\$(\d+)\*'Savings Log'!\$B\$(\d+)$"
)  # ='Savings Log'!$B$2*'Savings Log'!$B$1
_SCALED_CONSTANT = re.compile(r"^=(-?\d*\.?\d+)\s*\*\s*(\d*\.\d+)$")  # =1555000*0.6
_SCALED_FORMULA = re.compile(r"^=(\d*\.\d+)\s*\*\s*(.+)$", re.S)  # =0.4 * LET(...)
_COLUMN_OFFSET = re.compile(r"COLUMN\(\)\s*-\s*(\d+)")  # month from COLUMN()-4


def unwrap(value):
    """The formula Google Sheets exported inside DUMMYFUNCTION, else value
    unchanged. Cells that only hold part of another formula's spilled
    output ("COMPUTED_VALUE") come back as None."""
    if not isinstance(value, str) or not value.startswith(_DUMMY_PREFIX):
        return value
    text, pos, parts = value, len(_DUMMY_PREFIX), []
    # The argument is one or more "..." literals joined by &, with "" for
    # a quote inside a literal
    while text[pos] == '"':
        pos += 1
        literal = []
        while True:
            if text[pos] == '"' and text[pos + 1 : pos + 2] == '"':
                literal.append('"')
                pos += 2
            elif text[pos] == '"':
                pos += 1
                break
            else:
                literal.append(text[pos])
                pos += 1
        parts.append("".join(literal))
        if text[pos] != "&":
            break
        pos += 1
    formula = "".join(parts)
    if formula == '"COMPUTED_VALUE"':
        return None
    return "=" + formula


def translate(formula, column_shift: int, row_map: dict, first_shifted_col: int):
    """Moves a formula's same-sheet cell references to the new layout:
    columns from first_shifted_col on move right by column_shift, and rows
    are renumbered through row_map. Text in quotes and references to other
    tabs are left alone. A month worked out as COLUMN()-n gets n moved by
    the same column shift."""
    if not isinstance(formula, str) or not formula.startswith("="):
        return formula
    formula = _COLUMN_OFFSET.sub(
        lambda m: f"COLUMN()-{int(m.group(1)) + column_shift}", formula
    )

    def move(match):
        dollar_col, col, dollar_row, row = match.groups()
        index = openpyxl.utils.column_index_from_string(col)
        if index >= first_shifted_col:
            index += column_shift
        new_row = row_map.get(int(row), int(row))
        return f"{dollar_col}{bt.column_letter(index)}{dollar_row}{new_row}"

    pieces = re.split(r'("(?:[^"]|"")*")', formula)
    return "".join(
        piece if piece.startswith('"') else _CELL_REF.sub(move, piece)
        for piece in pieces
    )


def _balance_key(account_name: str) -> str:
    """ "Joint 3.55% APY (1111)" -> "(1111)": the masked account number at
    the end stays put when an institution renames the account."""
    match = _KEY_SUFFIX.search(account_name or "")
    return match.group(0).strip() if match else (account_name or "").strip()


class _Source:
    """The original workbook, with formulas and Google's cached values."""

    def __init__(self, path: str):
        self.formulas = openpyxl.load_workbook(path)
        self.values = openpyxl.load_workbook(path, data_only=True)

    def formula(self, tab: str, coordinate: str):
        return unwrap(self.formulas[tab][coordinate].value)

    def value(self, tab: str, coordinate: str):
        return self.values[tab][coordinate].value


def _budget_cells(src: _Source) -> tuple[bt.BudgetCells, list]:
    ws = src.formulas["Budget"]
    overrides = {}
    for row in range(5, 20):
        for col in "CDEF":
            value = unwrap(ws[f"{col}{row}"].value)
            if value is not None:
                overrides[f"{col}{row}"] = value
    cells = bt.BudgetCells(overrides, ws["B15"].value or "Pre-tax deductions")

    categories, row = [], 21
    while ws[f"B{row}"].value and ws[f"A{row}"].value != "Expenses":
        categories.append(
            bt.Category(
                ws[f"A{row}"].value, ws[f"B{row}"].value, unwrap(ws[f"D{row}"].value)
            )
        )
        row += 1
    # The old Total Expenses was =SUM(C21:C63)-C42: the subtracted rows
    # become In Totals = No
    for excluded in re.findall(r"-C(\d+)", str(ws[f"C{row}"].value or "")):
        categories[int(excluded) - 21].in_totals = False
    return cells, categories


def _expense_rows(src: _Source) -> list[list]:
    ws = src.values["Expense Log"]
    rows = ws.iter_rows(values_only=True)
    header = [str(h or "").strip() for h in next(rows)]
    index = {
        name: header.index(name) for name in bt.EXPENSE_LOG_COLUMNS if name in header
    }
    return [
        [row[index[name]] if name in index else None for name in bt.EXPENSE_LOG_COLUMNS]
        for row in rows
        if any(v is not None for v in row)
    ]


def _accounts(src: _Source, nw_formulas: list[str]):
    """Hand-entered Savings Log balances (columns A:B), with the conversion
    rate a Net Worth formula multiplied them by, and the IMPORTRANGE that
    filled its imported block."""
    fx_for = {}
    for formula in nw_formulas:
        match = _CONVERTED_BALANCE.match(formula)
        if match:
            fx_for[int(match.group(1))] = int(match.group(2))
    fx_rows = set(fx_for.values())
    ws = src.formulas["Savings Log"]
    balances = []
    for row in range(1, ws.max_row + 1):
        label = ws[f"A{row}"].value
        amount = unwrap(ws[f"B{row}"].value)
        if not label or amount is None or row in fx_rows:
            continue
        fx = unwrap(ws[f"B{fx_for[row]}"].value) if row in fx_for else None
        balances.append(bt.ManualBalance(str(label).strip(), amount, fx))

    imported = ""
    for cell in ws[1]:
        formula = unwrap(cell.value)
        if isinstance(formula, str) and "IMPORTRANGE" in formula.upper():
            # Open-ended and below the new header row, so accounts SimpleFIN
            # adds later are included
            imported = re.sub(r"!A1:D\d*", "!A2:D", formula)
    return balances, imported


def _section_of(label: str) -> int | None:
    label = label.lower()
    for section, keyword in enumerate(
        ["checking", "investment", "retirement", "real estate", "liabilit"]
    ):
        if keyword in label:
            return section
    return None


def _net_worth(src: _Source, year_columns: range):
    """Net Worth rows grouped by section, the contribution rows, and each
    old row's new spot (filled in once the new layout is known)."""
    ws = src.formulas["Net Worth"]
    values = src.values["Net Worth"]
    savings = src.values["Savings Log"]
    sections = [[] for _ in bt.SECTIONS]
    contributions = []
    origins = {}  # id(new row object) -> old row number
    pending, negate = [], set()
    in_contributions = False

    for row in range(5, ws.max_row + 1):
        label = str(ws[f"A{row}"].value or "").strip()
        account = ws[f"B{row}"].value
        if "contribution" in label.lower():
            in_contributions = True
            continue
        if label.lower().startswith("subtotal"):
            section = _section_of(label)
            if section is not None:
                sections[section] = pending
                # =E33-E34: rows the old subtotal subtracted
                negate |= {
                    int(r) for r in re.findall(r"-E(\d+)", str(ws[f"E{row}"].value))
                }
            pending = []
            continue
        if not account or label:
            continue
        months = {}
        for month, col in enumerate(year_columns, start=1):
            cell = ws.cell(row=row, column=col)
            months[month] = (unwrap(cell.value), values.cell(row=row, column=col).value)
        if in_contributions:
            item = bt.ContributionRow(account, ws[f"C{row}"].value or "", months)
            contributions.append(item)
        else:
            item = bt.NetWorthRow(
                account, ws[f"C{row}"].value or "", ws[f"D{row}"].value or "",
                months=months,
            )  # fmt: skip
            pending.append(item)
        origins[id(item)] = row

    for rows in sections:
        for item in rows:
            _resolve_balance(item, savings, origins[id(item)] in negate)
    return sections, contributions, origins, negate


def _share_factor(text: str) -> float | None:
    """The share an old Net Worth formula multiplied a balance by
    (=-0.6*'Savings Log'!$F$21, =1555000*0.6, =0.4 * LET(...)), if any."""
    fixed = _FIXED_BALANCE.match(text)
    if fixed:
        return abs(float(fixed.group(1))) if fixed.group(1) else None
    constant = _SCALED_CONSTANT.match(text)
    if constant:
        return float(constant.group(2))
    scaled = _SCALED_FORMULA.match(text)
    return float(scaled.group(1)) if scaled else None


def _resolve_balance(item: bt.NetWorthRow, savings, negate: bool):
    """Turns the old row (your share of a balance) into the new one (the
    full balance and your %): months whose formula read a fixed Savings
    Log cell become the row's Balance Key, a share factor becomes your %,
    and a row the old subtotal subtracted is stored negated."""
    share = 1.0
    for formula, _ in item.months.values():
        share = _share_factor(formula if isinstance(formula, str) else "") or share
    item.share = share
    if share != 1 and "extra" in item.type.lower():
        item.partner_share = -share

    kept = {}
    for month, (formula, cached) in item.months.items():
        text = formula if isinstance(formula, str) else ""
        fixed, converted = _FIXED_BALANCE.match(text), _CONVERTED_BALANCE.match(text)
        constant, scaled = _SCALED_CONSTANT.match(text), _SCALED_FORMULA.match(text)
        if fixed:
            _, column, source = fixed.groups()
            name_col = "E" if column == "F" else "A"
            name = savings[f"{name_col}{source}"].value
            item.key = _balance_key(name) if column == "F" else str(name).strip()
        elif converted:
            item.key = str(savings[f"A{converted.group(1)}"].value).strip()
        elif constant:
            value = float(constant.group(1))
            kept[month] = -value if negate else value
        elif scaled:
            body = scaled.group(2).strip()
            kept[month] = f"=-({body})" if negate else f"={body}"
        elif text:
            kept[month] = f"=-({text[1:]})" if negate else text
        elif cached is not None:
            value = -cached if negate else cached
            kept[month] = value / share if share else value
    item.months = kept


def migrate(path: str, name: str, partner: str, year: int) -> openpyxl.Workbook:
    src = _Source(path)
    budget, categories = _budget_cells(src)
    old_columns = range(5, 17)  # E-P: Jan-Dec in the original Net Worth tab
    sections, contributions, origins, _ = _net_worth(src, old_columns)
    nw_formulas = [
        unwrap(cell.value)
        for row in src.formulas["Net Worth"].iter_rows()
        for cell in row
        if isinstance(unwrap(cell.value), str)
    ]
    balances, imported = _accounts(src, nw_formulas)
    for item in contributions:
        item.months = {
            month: formula if formula is not None else cached
            for month, (formula, cached) in item.months.items()
            if formula is not None or cached is not None
        }

    spec = bt.BudgetSpec(
        name=name, partner=partner, year=year, budget=budget,
        categories=categories, expense_rows=_expense_rows(src),
        manual_balances=balances, imported_balances_formula=imported,
        net_worth=sections, contributions=contributions,
    )  # fmt: skip

    layout = bt.plan_layout(spec)
    row_map = {}
    for section, rows in enumerate(sections):
        first, _ = layout.nw_rows[section]
        for offset, item in enumerate(rows):
            row_map[origins[id(item)]] = first + offset
    for offset, item in enumerate(contributions):
        row_map[origins[id(item)]] = layout.contrib_first + offset
    shift = bt.NW_FIRST_MONTH_COL - old_columns[0]
    for item in [i for rows in sections for i in rows] + contributions:
        item.months = {
            month: translate(value, shift, row_map, old_columns[0])
            for month, value in item.months.items()
        }
        for value in item.months.values():
            if isinstance(value, str) and _SAVINGS_LOG in value:
                logger.warning(
                    "Net Worth '%s' still reads the old Savings Log: %s",
                    item.account,
                    value,
                )
    return bt.build_workbook(spec)


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(
        description="Move a budget spreadsheet export onto the template layout"
    )
    parser.add_argument("source", help="The old spreadsheet, exported as .xlsx")
    parser.add_argument("--out", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--partner", default="")
    parser.add_argument("--year", type=int, default=datetime.date.today().year)
    args = parser.parse_args()
    migrate(args.source, args.name, args.partner, args.year).save(args.out)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
