import datetime

import openpyxl
import pytest

from src import budget_migration as bm
from src import budget_template as bt

SHEET_ID = "1abcDEF"


def _dummy(formula: str, cached) -> str:
    """How Google Sheets' .xlsx export wraps a function Excel lacks."""
    inner = formula[1:].replace('"', '""')
    return f'=IFERROR(__xludf.DUMMYFUNCTION("{inner}"),{cached!r})'


class TestUnwrap:
    def test_recovers_the_formula_and_its_quotes(self):
        formula = f'=IMPORTRANGE("{SHEET_ID}", "bank_accounts_dump!A1:D25")'
        assert bm.unwrap(_dummy(formula, "Institution")) == formula

    def test_joins_literals_split_with_ampersands(self):
        wrapped = '=IFERROR(__xludf.DUMMYFUNCTION("SUM(\'Monthly"&" Expenses\'!P5)"),3)'
        assert bm.unwrap(wrapped) == "=SUM('Monthly Expenses'!P5)"

    def test_spilled_output_cells_are_empty(self):
        assert bm.unwrap(_dummy('="COMPUTED_VALUE"', 5.0)) is None

    def test_other_values_pass_through(self):
        assert bm.unwrap("=A1+1") == "=A1+1"
        assert bm.unwrap(12.5) == 12.5


class TestTranslate:
    def test_moves_month_columns_and_renumbers_rows(self):
        assert bm.translate("=M23", 2, {23: 30}, 5) == "=O30"
        assert bm.translate("=N23+5000", 2, {23: 30}, 5) == "=P30+5000"
        assert bm.translate("=P6+P7", 2, {6: 8, 7: 9}, 5) == "=R8+R9"

    def test_keeps_absolute_markers_and_unshifted_columns(self):
        assert bm.translate("=$B$4*E$4", 2, {}, 5) == "=$B$4*G$4"

    def test_leaves_quoted_text_and_function_names_alone(self):
        formula = (
            f'=0.4 * IMPORTRANGE("{SHEET_ID}", "joint_account_ledger!M5")+LOG10(E5)'
        )
        assert bm.translate(formula, 2, {5: 9}, 5) == (
            f'=0.4 * IMPORTRANGE("{SHEET_ID}", "joint_account_ledger!M5")+LOG10(G9)'
        )

    def test_leaves_other_tabs_references_alone(self):
        assert bm.translate("=Budget!C17+E5", 2, {}, 5) == "=Budget!C17+G5"

    def test_month_from_column_number_moves_with_the_columns(self):
        assert bm.translate("=DATE(2026, COLUMN()-4, 1)", 3, {}, 5) == (
            "=DATE(2026, COLUMN()-7, 1)"
        )


class TestBalanceKey:
    @pytest.mark.parametrize(
        "name, key",
        [
            ("Joint 3.55% APY (1111)", "(1111)"),
            ("Acme Corp 401(k) Plan (2-01)", "(2-01)"),
            ("Individual (8I5T)", "(8I5T)"),
            ("No number here", "No number here"),
        ],
    )
    def test_masked_account_number_suffix(self, name, key):
        assert bm._balance_key(name) == key


def _old_sheet(path):
    """A small spreadsheet in the original Budget - 2026 layout."""
    wb = openpyxl.Workbook()
    budget = wb.active
    budget.title = "Budget"
    budget["B15"] = "Commuter card"
    budget["F5"] = 5000
    budget["E5"] = "=F5*2"
    budget["D9"] = "=(E9*12)+(0.4*D6*0.6)"
    for row, (group, name, yearly) in enumerate(
        [("Food and drink", "Groceries", 1200), ("Home", "Mortgage", 50000),
         ("Home", "Rent", 6000)], start=21,
    ):  # fmt: skip
        budget[f"A{row}"], budget[f"B{row}"], budget[f"D{row}"] = group, name, yearly
    budget["A24"], budget["B24"] = "Expenses", "Total Expenses"
    budget["C24"] = "=SUM(C21:C23)-C22"

    log = wb.create_sheet("Expense Log")
    log.append(["Date", "Amount", "Category", "Description", "Details",
                "Split Type", "Participant Names", "My Paid", "My Owed",
                "My Net", "Splitwise ID", "Transaction Fingerprint"])  # fmt: skip
    log.append([datetime.datetime(2026, 1, 3), 10, "Groceries", "Store", None,
                "self", "Alex", 10, 10, 0, 7, "f"])  # fmt: skip

    savings = wb.create_sheet("Savings Log")
    savings["A1"] = "Conversion Rate"
    savings["B1"] = _dummy('=GOOGLEFINANCE("CURRENCY:INRUSD")', 0.0105)
    savings["A2"], savings["B2"] = "Foreign bank balance", 100000
    savings["A3"], savings["B3"] = "RH Available Cash", 250
    savings["D1"] = _dummy(
        f'=IMPORTRANGE("{SHEET_ID}", "bank_accounts_dump!A1:D25")', "Institution"
    )
    savings["E5"] = "Joint 3.55% APY (1111)"
    savings["E6"] = "MORTGAGE ...6666 (6666)"

    nw = wb.create_sheet("Net Worth")
    nw["B4"] = "Account"
    for month in range(12):
        nw.cell(
            row=4,
            column=5 + month,
            value=datetime.date(2026, month + 1, 1).strftime("%b"),
        )
    rows = {
        5: ("Cash Accounts", None, None),
        6: (None, "Savings", "Joint "),
        7: (None, "Savings", "Foreign"),
        8: (None, "Brokerage", "Uninvested"),
        9: ("Subtotal – Checking & Savings", None, None),
        11: ("INVESTMENTS", None, None),
        12: (None, "Bonds", "I-Bonds"),
        13: ("Subtotal – Investments", None, None),
        15: ("RETIREMENT", None, None),
        16: ("Subtotal – Retirement", None, None),
        18: ("REAL ESTATE", None, None),
        19: (None, "Real Estate", "Home Value"),
        20: (None, "Liability", "Mortgage Balance"),
        21: (None, "Real Estate", "Extra Payments"),
        22: ("Subtotal – Real Estate", None, None),
        23: ("LIABILITIES", None, None),
        24: ("Subtotal – Liabilities", None, None),
        26: ("NET WORTH (Assets − Liabilities)", None, None),
        28: (
            "Monthly Savings Contributions  (enter cash deposited each month)",
            None,
            None,
        ),
        29: (None, "Savings", "Individual"),
        30: ("Total Contributed (YTD)", None, None),
    }
    for row, (a, b, c) in rows.items():
        nw[f"A{row}"], nw[f"B{row}"], nw[f"C{row}"] = a, b, c
    # Jan-Sep hard-coded, Oct-Dec live
    for col in range(5, 14):
        nw.cell(row=6, column=col, value=1000)
        nw.cell(row=12, column=col, value=500)
        nw.cell(row=20, column=col, value=300000)
    for col in range(14, 17):
        nw.cell(row=6, column=col, value="='Savings Log'!$F$5")
        nw.cell(row=7, column=col, value="='Savings Log'!$B$2*'Savings Log'!$B$1")
        nw.cell(row=8, column=col, value="='Savings Log'!$B$3")
        nw.cell(row=19, column=col, value="=1555000*0.6")
        nw.cell(row=20, column=col, value="=-0.6*'Savings Log'!$F$6")
        nw.cell(row=21, column=col, value=f'=0.4 * IMPORTRANGE("{SHEET_ID}", "x!M5")')
    nw["N12"], nw["O12"] = "=M12", "=N12+5000"
    nw["E22"] = "=E19-E20+E21"
    nw["H29"], nw["P29"] = 700, "=P6+P8"
    wb.save(path)


@pytest.fixture
def migrated(tmp_path):
    path = tmp_path / "old.xlsx"
    _old_sheet(path)
    return bm.migrate(str(path), "Alex", "Sam", 2026)


class TestMigrate:
    def test_pay_goes_to_your_income_columns(self, migrated):
        ws = migrated[bt.INCOME]
        assert ws["B15"].value == "Commuter card"
        assert ws["F5"].value == 5000 and ws["E5"].value == "=F5*2"
        assert ws["D9"].value == "=(E9*12)+(0.4*D6*0.6)"
        assert ws["K5"].value is None  # the partner's, still to fill in
        assert migrated[bt.BUDGET]["B15"].value == "=Income!B15"

    def test_categories_carry_over(self, migrated):
        ws = migrated[bt.BUDGET]
        assert [ws[f"B{r}"].value for r in (21, 22, 23)] == [
            "Groceries",
            "Mortgage",
            "Rent",
        ]
        assert [ws[f"D{r}"].value for r in (21, 22, 23)] == [1200, 50000, 6000]
        assert [ws[f"I{r}"].value for r in (21, 22, 23)] == ["Yes", "No", "Yes"]

    def test_expense_log_rows_by_column_name(self, migrated):
        row = [c.value for c in migrated[bt.EXPENSE_LOG][2]]
        assert row[bt.EXPENSE_LOG_COLUMNS.index("My Owed")] == 10
        assert row[bt.EXPENSE_LOG_COLUMNS.index("Friends Split")] is None
        assert row[bt.EXPENSE_LOG_COLUMNS.index("Splitwise ID")] == 7
        assert migrated[bt.PARTNER_EXPENSE_LOG].max_row == 1  # header only

    def test_accounts_get_balances_conversion_and_open_ended_import(self, migrated):
        ws = migrated[bt.ACCOUNTS]
        assert [ws["A5"].value, ws["B5"].value] == ["Foreign bank balance", 100000]
        assert ws["C5"].value == '=GOOGLEFINANCE("CURRENCY:INRUSD")'
        assert ws["A6"].value == "RH Available Cash" and ws["C6"].value is None
        assert ws["A7"].value is None  # the conversion rate isn't a balance
        assert ws["G5"].value == (
            f'=IMPORTRANGE("{SHEET_ID}", "bank_accounts_dump!A2:D")'
        )
        assert ws["L5"].value is None

    def test_fixed_savings_log_cells_become_keys(self, migrated):
        ws = migrated[bt.NET_WORTH]
        assert [ws[f"E{r}"].value for r in (6, 7, 8)] == [
            "(1111)", "Foreign bank balance", "RH Available Cash",
        ]  # fmt: skip
        assert [ws[f"F{r}"].value for r in (6, 7, 8)] == [1, 1, 1]
        assert ws["H6"].value == 1000  # Jan, as it was
        assert ws["Q6"].value == bt.lookup_formula(6)  # Oct, live

    def test_share_factor_becomes_your_percent_and_values_full(self, migrated):
        ws = migrated[bt.NET_WORTH]
        mortgage = 20
        assert ws[f"E{mortgage}"].value == "(6666)"
        assert ws[f"F{mortgage}"].value == 0.6
        assert ws[f"G{mortgage}"].value == f"=1-F{mortgage}"
        # Stored negative (the old subtotal subtracted it), and divided by
        # the 60% it was, back to the full balance
        assert ws[f"H{mortgage}"].value == pytest.approx(-500000)
        home = 19
        assert ws[f"Q{home}"].value == 1555000 and ws[f"F{home}"].value == 0.6

    def test_extra_principal_factor_moves_the_partners_share(self, migrated):
        ws = migrated[bt.NET_WORTH]
        extra = 21
        assert ws[f"F{extra}"].value == 0.4 and ws[f"G{extra}"].value == -0.4
        assert ws[f"Q{extra}"].value == f'=IMPORTRANGE("{SHEET_ID}", "x!M5")'

    def test_other_formulas_move_with_their_rows_and_columns(self, migrated):
        ws = migrated[bt.NET_WORTH]
        assert ws["Q12"].value == "=P12" and ws["R12"].value == "=Q12+5000"

    def test_contributions_keep_values_and_remapped_formulas(self, migrated):
        ws = migrated[bt.NET_WORTH]
        row = next(
            r for r in range(1, ws.max_row + 1)
            if ws[f"B{r}"].value == "Savings" and ws[f"C{r}"].value == "Individual"
        )  # fmt: skip
        assert ws[f"K{row}"].value == 700  # April
        assert ws[f"S{row}"].value == "=S6+S8"  # December, rows renumbered
