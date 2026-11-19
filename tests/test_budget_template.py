import datetime
import shutil
import subprocess

import openpyxl
import pandas as pd
import pytest

from src import budget_template as bt
from src import personal_finance as pf


def _spec(**kwargs):
    defaults = dict(
        name="Alex",
        partner="Sam",
        year=2026,
        budget=bt.BudgetCells({"F5": 5000, "K5": 4000}),
        categories=[
            bt.Category("Food and drink", "Groceries", 1200),
            bt.Category("Home", "Mortgage", 24000, in_totals=False),
            bt.Category("Home", "Rent", 6000),
        ],
        expense_rows=[
            [datetime.datetime(2026, 1, 5), 100, "Groceries", "Costco", None,
             "partner", "Alex, Sam", 100, 50, 50, None, 1, "a"],
            [datetime.datetime(2026, 2, 7), 80, "Groceries", "Safeway", None,
             "self", "Alex", 80, 80, 0, None, 2, "b"],
            [datetime.datetime(2026, 2, 1), 3000, "Mortgage", "Mortgage", None,
             "partner", "Alex, Sam", 3000, 1800, 1200, None, 3, "c"],
            [datetime.datetime(2025, 12, 30), 999, "Groceries", "Last year", None,
             "self", "Alex", 999, 999, 0, None, 4, "d"],
        ],
        # The same two shared bills from Sam's side, with Sam's share
        partner_expense_rows=[
            [datetime.datetime(2026, 1, 5), 100, "Groceries", "Costco", None,
             "partner", "Alex, Sam", 0, 50, -50, None, 1, "a"],
            [datetime.datetime(2026, 2, 1), 3000, "Mortgage", "Mortgage", None,
             "partner", "Alex, Sam", 0, 1200, -1200, None, 3, "c"],
        ],
        manual_balances=[bt.ManualBalance("Savings", 1000), bt.ManualBalance("Euro", 100, 1.1)],
        net_worth=[
            [bt.NetWorthRow("Savings", "Individual", key="Savings"),
             bt.NetWorthRow("Euro", "Foreign", key="Euro"),
             bt.NetWorthRow("Joint", "Joint", key="(1111)", share=0.4)],
            [bt.NetWorthRow("Brokerage", "Stocks", months={1: 500, 2: 600})],
            [bt.NetWorthRow("Retirement", "401k", months={1: 2000})],
            [bt.NetWorthRow("Real Estate", "Home Value", share=0.6, months={1: 500000}),
             bt.NetWorthRow("Liability", "Mortgage", key="(6666)", share=0.6),
             bt.NetWorthRow("Real Estate", "Extra Principal Credit", share=0.4,
                            partner_share=-0.4, months={1: 1000})],
            [bt.NetWorthRow("Liability", "Credit Card", months={1: -100})],
        ],
        contributions=[bt.ContributionRow("Savings", "Individual", {1: 100, 2: 50})],
    )  # fmt: skip
    defaults.update(kwargs)
    return bt.BudgetSpec(**defaults)


def _with_imported_balances(wb):
    # What IMPORTRANGE of each person's bank_accounts_dump would spill into
    # Accounts!G5 (Alex's) and L5 (Sam's)
    accounts = wb[bt.ACCOUNTS]
    for first_col, row in [
        (7, ["Online Bank", "Joint 3.55% APY (1111)", 10000, None]),
        (12, ["Wells Fargo", "MORTGAGE ...6666 (6666)", -500000, None]),
    ]:
        for col, value in enumerate(row):
            accounts.cell(row=5, column=first_col + col, value=value)
    return wb


def _row_labelled(ws, label):
    return next(r for r in range(1, 60) if ws[f"A{r}"].value == label)


class TestBuildWorkbook:
    def test_tabs_in_fill_in_order(self):
        wb = bt.build_workbook(bt.BudgetSpec())
        assert wb.sheetnames == [
            bt.INSTRUCTIONS, bt.SETTINGS, bt.INCOME, bt.BUDGET,
            bt.MONTHLY_EXPENSES, bt.EXPENSE_LOG, bt.PARTNER_EXPENSE_LOG,
            bt.ACCOUNTS, bt.NET_WORTH, bt.DASHBOARD,
        ]  # fmt: skip

    def test_default_categories_are_splitwises(self):
        wb = bt.build_workbook(bt.BudgetSpec())
        names = [wb[bt.BUDGET].cell(row=r, column=2).value for r in range(21, 21 + 43)]
        assert names[0] == "Cleaning" and names[-1] == "Taxes"
        assert wb[bt.BUDGET]["B64"].value == "Total Expenses"

    def test_settings_hold_names_year_and_pay_frequencies(self):
        ws = bt.build_workbook(_spec(partner_paychecks_per_year=26))[bt.SETTINGS]
        assert [ws[f"B{r}"].value for r in range(3, 8)] == [
            "Alex", "Sam", 2026, 24, 26,
        ]  # fmt: skip

    def test_each_person_has_income_columns_on_their_own_pay_schedule(self):
        ws = bt.build_workbook(_spec())[bt.INCOME]
        assert ws["E5"].value == f"=F5*{bt.PAYCHECKS_CELL}/12"
        assert ws["J5"].value == f"=K5*{bt.PARTNER_PAYCHECKS_CELL}/12"
        assert ws["F5"].value == 5000 and ws["K5"].value == 4000

    def test_budget_income_rows_add_both_people_up(self):
        ws = bt.build_workbook(_spec())[bt.BUDGET]
        assert ws["D19"].value == "=Income!D19+Income!I19"
        assert ws["F19"].value is None  # pay schedules can differ

    def test_spending_sums_both_logs(self):
        ws = bt.build_workbook(_spec())[bt.BUDGET]
        assert "'Expense Log'!$I:$I" in ws["C21"].value
        assert "'Partner Expense Log'!$I:$I" in ws["C21"].value

    def test_categories_out_of_totals_are_marked(self):
        ws = bt.build_workbook(_spec())[bt.BUDGET]
        assert [ws[f"I{r}"].value for r in (21, 22, 23)] == ["Yes", "No", "Yes"]
        assert ws["C24"].value == '=SUMIF($I21:$I23,"Yes",C21:C23)'

    def test_keyed_rows_look_up_accounts_and_others_keep_overrides(self):
        ws = bt.build_workbook(_spec())[bt.NET_WORTH]
        assert ws["E6"].value == "Savings"
        assert ws["H6"].value == bt.lookup_formula(6)
        assert ws["H12"].value == 500 and ws["I12"].value == 600
        assert ws["J12"].value is None

    def test_partner_share_defaults_to_the_rest(self):
        ws = bt.build_workbook(_spec())[bt.NET_WORTH]
        assert ws["F8"].value == 0.4 and ws["G8"].value == "=1-F8"
        extra = 22
        assert ws[f"F{extra}"].value == 0.4 and ws[f"G{extra}"].value == -0.4

    def test_empty_section_subtotals_to_zero(self):
        spec = _spec()
        spec.net_worth[2] = []
        ws = bt.build_workbook(spec)[bt.NET_WORTH]
        assert ws[f"H{_row_labelled(ws, 'Subtotal – Retirement')}"].value == 0

    def test_lookup_formula_matches_label_or_either_imported_name(self):
        formula = bt.lookup_formula(9)
        assert "SUMIF(Accounts!$A:$A,$E9,Accounts!$D:$D)" in formula
        assert 'SUMIF(Accounts!$H:$H,"*"&$E9&"*",Accounts!$I:$I)' in formula
        assert 'SUMIF(Accounts!$M:$M,"*"&$E9&"*",Accounts!$N:$N)' in formula
        assert "$F9" not in formula  # the full balance, not a share

    def test_layout_keeps_the_labels_the_dashboard_parses(self):
        wb = bt.build_workbook(_spec())
        nw = [wb[bt.NET_WORTH].cell(row=r, column=1).value for r in range(1, 50)]
        for _, subtotal in bt.SECTIONS:
            assert subtotal in nw
        assert bt.NET_WORTH_LABEL in nw and bt.TOTAL_CONTRIBUTED_LABEL in nw
        assert wb[bt.BUDGET]["D3"].value == "Budget Yearly"
        assert wb[bt.BUDGET]["E3"].value == "Monthly"
        assert wb[bt.MONTHLY_EXPENSES]["B4"].value == "Sub-Category"


def _recalculate(wb, tmp_path):
    """Saves wb and has LibreOffice compute every formula, as Google Sheets
    would on import."""
    source = tmp_path / "in.xlsx"
    wb.save(source)
    subprocess.run(
        ["soffice", "--headless", "--norestore",
         f"-env:UserInstallation=file://{tmp_path}/profile",
         "--convert-to", "xlsx", "--outdir", str(tmp_path / "out"), str(source)],
        check=True, capture_output=True, timeout=300,
    )  # fmt: skip
    return openpyxl.load_workbook(tmp_path / "out" / "in.xlsx", data_only=True)


def _has_calc():
    if not shutil.which("soffice"):
        return False
    return any(
        "calc" in line
        for line in subprocess.run(
            ["dpkg", "-l"], capture_output=True, text=True, check=False
        ).stdout.splitlines()
        if "libreoffice-calc" in line
    )


@pytest.mark.skipif(not _has_calc(), reason="needs LibreOffice Calc")
class TestFormulas:
    @pytest.fixture(scope="class")
    def calc(self, tmp_path_factory):
        wb = _with_imported_balances(bt.build_workbook(_spec()))
        return _recalculate(wb, tmp_path_factory.mktemp("calc"))

    def test_monthly_expenses_sum_both_logs_by_month_this_year(self, calc):
        ws = calc[bt.MONTHLY_EXPENSES]
        assert ws["D5"].value == 100  # Jan groceries, both halves
        assert ws["E5"].value == 80
        assert ws["E6"].value == 3000  # the whole mortgage payment, once
        assert ws["P5"].value == 180  # last year's row left out

    def test_budget_totals_skip_categories_out_of_totals(self, calc):
        ws = calc[bt.BUDGET]
        assert ws["C21"].value == 180
        assert ws["C24"].value == 180  # mortgage's 3000 is In Totals = No
        assert ws["D24"].value == 7200

    def test_household_pay_is_both_incomes(self, calc):
        assert calc[bt.INCOME]["D19"].value == pytest.approx(120000)
        assert calc[bt.INCOME]["I19"].value == pytest.approx(96000)
        assert calc[bt.BUDGET]["D19"].value == pytest.approx(216000)

    def test_net_worth_rows_hold_full_balances(self, calc):
        ws = calc[bt.NET_WORTH]
        assert ws["H6"].value == 1000  # hand-entered, exact label
        assert ws["H7"].value == pytest.approx(110)  # 100 at 1.1
        assert ws["H8"].value == pytest.approx(10000)  # your import
        assert ws["H21"].value == pytest.approx(-500000)  # your partner's import

    def test_household_and_each_persons_net_worth(self, calc):
        ws = calc[bt.NET_WORTH]
        assert ws["H9"].value == pytest.approx(11110)
        # Home minus mortgage; the extra principal credit only moves equity
        assert ws["H23"].value == pytest.approx(0)
        total = _row_labelled(ws, bt.NET_WORTH_LABEL)
        assert ws[f"H{total}"].value == pytest.approx(13510)
        assert ws[f"A{total + 1}"].value.strip() == "Alex's share"
        alex = 1000 + 110 + 4000 + 500 + 2000 + 300000 - 300000 + 400 - 100
        sam = 6000 + 200000 - 200000 - 400
        assert ws[f"H{total + 1}"].value == pytest.approx(alex)
        assert ws[f"H{total + 2}"].value == pytest.approx(sam)
        assert alex + sam == 13510

    def test_dashboard_splits_spending_by_person(self, calc):
        ws = calc[bt.DASHBOARD]
        assert ws["A16"].value == "ALEX · NET WORTH"
        assert ws["E17"].value == 1930  # this year's, not last year's 999
        assert ws["G17"].value == 1250

    def test_dashboard_parser_reads_the_template(self, calc):
        def matrix(tab):
            convert = lambda v: (
                (v - datetime.datetime(1899, 12, 30)).days
                if isinstance(v, datetime.datetime)
                else ("" if v is None else v)
            )
            return [
                [convert(v) for v in r] for r in calc[tab].iter_rows(values_only=True)
            ]

        today = pd.Timestamp("2026-02-28")
        months = pf.months_of(2026, today)
        workbook = {tab: matrix(tab) for tab in bt.EXPENSE_LOGS}
        expenses = pf.parse_expense_logs(workbook, 2026, today)
        budgets = pf.parse_category_budgets(matrix(bt.MONTHLY_EXPENSES))
        net_worth = pf.parse_net_worth(matrix(bt.NET_WORTH), months)

        assert list(expenses["my_share"]) == [50, 50, 1800, 1200, 80]
        assert list(budgets["category"]) == ["Groceries", "Mortgage", "Rent"]
        _, take_home_budget = pf.parse_budget_items(matrix(bt.BUDGET))["take_home"]
        assert take_home_budget == pytest.approx(216000)
        assert list(net_worth[pf.CONTRIBUTIONS]) == [100, 50]
        assert net_worth[pf.NET_WORTH].iloc[0] == pytest.approx(13510)
