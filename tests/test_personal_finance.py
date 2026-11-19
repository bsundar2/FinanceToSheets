import pandas as pd
import pytest

from src import personal_finance as pf

TODAY = pd.Timestamp("2026-03-15")
MONTHS = pf.months_of(2026, TODAY)


def _serial(date: str) -> int:
    return (pd.Timestamp(date) - pd.Timestamp("1899-12-30")).days


EXPENSE_LOG = [
    [
        "Date",
        "Amount",
        "Category",
        "Description",
        "Details",
        "Split Type",
        "Participant Names",
        "My Paid",
        "My Owed",
        "My Net",
    ],
    [_serial("2026-01-05"), 100, "Groceries", "Costco", "", "partner", "", 100, 50, 50],
    [_serial("2026-01-20"), 40, "Dining out", "costco ", "", "self", "", 40, 40, 0],
    [_serial("2026-02-03"), 9000, "Car", "Car payoff", "", "self", "", 9000, 9000, 0],
    [_serial("2026-02-10"), -20, "Groceries", "Costco", "", "partner", "", 0, -10, 10],
    [_serial("2026-03-01"), 60, "Pets", "Vet", "", "self", "", 60, 60, 0],
    # Future-dated (Splitwise holds upcoming bills) and last year: both skipped
    [
        _serial("2026-04-01"),
        500,
        "Taxes",
        "Property tax",
        "",
        "partner",
        "",
        500,
        300,
        200,
    ],
    [_serial("2025-12-31"), 70, "Groceries", "Costco", "", "self", "", 70, 70, 0],
    ["", "", "", "", "", "", "", "", "", ""],
]

MONTHLY_EXPENSES = [
    ["Monthly Expense Tracker"],
    ["Enter actual monthly spend"],
    ["Category", "Sub-Category", "Monthly\nBudget", "Jan", "Feb"],
    ["Food and drink", "Dining out", 100, 0, 0],
    ["Food and drink", "Groceries", 200, 0, 0],
    ["Transportation", "Car", 300, 0, 0],
    ["TOTAL EXPENSES", "", 600, 0, 0],
]

BUDGET = [
    ["Budget & Taxes"],
    ["Category", "Item", "Actual Yearly", "Budget Yearly", "Monthly"],
    ["INCOME"],
    ["", "Gross Salary", 120000, 120000, 10000],
    ["💵 Take-Home Pay", "", 120000, 84000, 7000],
]

_MONTH_HEADER = [
    "",
    "Account",
    "Type",
    "Brokerage/Bank",
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
NET_WORTH = [
    ["Net Worth Tracker"],
    [],
    _MONTH_HEADER,
    ["Cash Accounts"],
    ["", "Checking", "Individual", "Bank", 100, 200, 300],
    ["Subtotal – Checking & Savings", "", "", "", 100, 200, 300],
    ["Subtotal – Investments", "", "", "", 1000, 1100, 900],
    ["Subtotal – Retirement", "", "", "", 5000, 5000, 5100],
    ["Subtotal – Real Estate", "", "", "", 0, 0, 0],
    ["Subtotal – Liabilities", "", "", "", -50, -80, -20],
    ["NET WORTH (Assets − Liabilities)", "", "", "", 6050, 6220, 6280],
    ["Monthly Savings Contributions  (enter cash deposited each month)"],
    ["", "Savings", "Individual", "", "", 100, 50],
    ["", "Brokerage", "Stocks", "", 0, "", 25],
    ["Total Contributed (YTD)", "", "", "", 0, 100, 75],
    ["Market Gains / (Losses)  =  Net Worth Change − Contributions"],
]


@pytest.fixture
def expenses():
    return pf.parse_expense_log(EXPENSE_LOG, 2026, TODAY)


@pytest.fixture
def budgets():
    return pf.parse_category_budgets(MONTHLY_EXPENSES)


class TestBudgetYear:
    def test_from_spreadsheet_name(self):
        assert pf.budget_year("Budget - 2025", TODAY) == 2025

    def test_falls_back_to_today(self):
        assert pf.budget_year("Budget", TODAY) == 2026


class TestWithoutYear:
    def test_drops_the_year_and_its_separator(self):
        assert pf.without_year("Budget - 2026") == "Budget"
        assert pf.without_year("Budget, 2026") == "Budget"
        assert pf.without_year("2026 Budget") == "Budget"

    def test_leaves_a_name_without_a_year(self):
        assert pf.without_year("Household Budget") == "Household Budget"


class TestMonthsOf:
    def test_current_year_stops_at_this_month(self):
        assert [str(m) for m in MONTHS] == ["2026-01", "2026-02", "2026-03"]

    def test_past_year_has_all_twelve(self):
        assert len(pf.months_of(2025, TODAY)) == 12


class TestParseExpenseLog:
    def test_keeps_this_years_rows_up_to_today(self, expenses):
        assert list(expenses["description"]) == [
            "Costco",
            "costco",
            "Car payoff",
            "Costco",
            "Vet",
        ]

    def test_share_is_my_owed(self, expenses):
        assert list(expenses["my_share"]) == [50, 40, 9000, -10, 60]

    def test_parses_text_dates_too(self):
        values = [
            EXPENSE_LOG[0],
            ["2026-01-05", 1, "Groceries", "X", "", "", "", 1, 1, 0],
        ]
        df = pf.parse_expense_log(values, 2026, TODAY)
        assert df["date"].iloc[0] == pd.Timestamp("2026-01-05")


class TestParseExpenseLogs:
    def test_without_a_partner_log_is_just_the_expense_log(self, expenses):
        workbook = {pf.EXPENSE_LOG_TAB: EXPENSE_LOG}
        df = pf.parse_expense_logs(workbook, 2026, TODAY)
        assert list(df["my_share"]) == list(expenses["my_share"])

    def test_adds_the_partners_share_in_date_order(self):
        partner = [
            EXPENSE_LOG[0],
            [_serial("2026-01-06"), 100, "Groceries", "Costco", "", "", "", 0, 50, -50],
        ]
        workbook = {
            pf.EXPENSE_LOG_TAB: EXPENSE_LOG,
            pf.PARTNER_EXPENSE_LOG_TAB: partner,
        }
        df = pf.parse_expense_logs(workbook, 2026, TODAY)
        assert len(df) == 6
        assert df["date"].is_monotonic_increasing
        assert df["my_share"].sum() == 50 + 40 + 9000 - 10 + 60 + 50

    def test_empty_partner_log_is_skipped(self, expenses):
        workbook = {pf.EXPENSE_LOG_TAB: EXPENSE_LOG, pf.PARTNER_EXPENSE_LOG_TAB: []}
        assert len(pf.parse_expense_logs(workbook, 2026, TODAY)) == len(expenses)


class TestParseCategoryBudgets:
    def test_reads_rows_until_total(self, budgets):
        assert list(budgets["category"]) == ["Dining out", "Groceries", "Car"]
        assert list(budgets["group"]) == [
            "Food and drink",
            "Food and drink",
            "Transportation",
        ]
        assert list(budgets["monthly_budget"]) == [100, 200, 300]


class TestSplitLarge:
    def test_splits_on_absolute_share(self, expenses):
        everyday, large = pf.split_large(expenses, 1000)
        assert list(large["description"]) == ["Car payoff"]
        assert len(everyday) == 4


class TestMonthlyByGroup:
    def test_pivots_with_every_month_and_other_group(self, expenses, budgets):
        everyday, _ = pf.split_large(expenses, 1000)
        table = pf.monthly_by_group(everyday, budgets, MONTHS)

        assert list(table.columns) == ["Food and drink", pf.OTHER_GROUP]
        assert list(table["Food and drink"]) == [90, -10, 0]
        assert list(table[pf.OTHER_GROUP]) == [0, 0, 60]


class TestMonthlyByCategory:
    def test_sub_categories_of_one_group_largest_first(self, expenses, budgets):
        everyday, _ = pf.split_large(expenses, 1000)
        table = pf.monthly_by_category(everyday, budgets, MONTHS, "Food and drink")

        assert list(table.columns) == ["Dining out", "Groceries"]
        assert list(table["Groceries"]) == [50, -10, 0]
        # The sub-categories add up to the group's bars
        group = pf.monthly_by_group(everyday, budgets, MONTHS)["Food and drink"]
        assert list(table.sum(axis=1)) == list(group)

    def test_smallest_beyond_the_limit_are_other(self, expenses, budgets):
        everyday, _ = pf.split_large(expenses, 1000)
        table = pf.monthly_by_category(
            everyday, budgets, MONTHS, "Food and drink", max_categories=1
        )

        assert list(table.columns) == ["Other"]
        assert list(table["Other"]) == [90, -10, 0]

    def test_unbudgeted_categories_are_in_the_other_group(self, expenses, budgets):
        table = pf.monthly_by_category(expenses, budgets, MONTHS, pf.OTHER_GROUP)

        assert list(table.columns) == ["Pets"]


class TestBudgetVsActual:
    def test_prorates_current_month_and_sorts_most_over_first(self, expenses, budgets):
        table = pf.budget_vs_actual(expenses, budgets, TODAY, 2026)
        elapsed = 2 + 15 / 31

        assert list(table["category"]) == ["Car", "Pets", "Dining out", "Groceries"]
        car = table.set_index("category").loc["Car"]
        assert car["budget"] == pytest.approx(300 * elapsed)
        assert car["over"] == pytest.approx(9000 - 300 * elapsed)
        assert car["annual"] == 3600
        assert table.set_index("category").loc["Pets", "group"] == pf.OTHER_GROUP

    def test_past_year_uses_twelve_months(self, expenses, budgets):
        table = pf.budget_vs_actual(expenses, budgets, TODAY, 2025)
        assert table.set_index("category").loc["Car", "budget"] == 3600


class TestTopMerchants:
    def test_groups_ignoring_case_and_spacing(self, expenses):
        table = pf.top_merchants(expenses, n=2)
        assert list(table["description"]) == ["Car payoff", "Costco"]
        assert table.iloc[1]["total"] == 80
        assert table.iloc[1]["count"] == 3


class TestParseBudgetItems:
    def test_actual_and_budget_by_label(self):
        values = [
            ["Category", "Item", "Actual Yearly", "Budget Yearly", "Monthly"],
            ["Income", "Total Gross Income", 328000, 327999.92, 21666.66],
            ["", "401k Contribution", 24500, 24500, 2166.66],
            ["", "401k Company Match", 7250, 7250, 1083.33],
            ["💵 Take-Home Pay", "", 205469.23, 191356.16, 11926.52],
            ["Savings", "Take-Home Savings", 64428.8, 57019.12, ""],
            ["Savings", "Total Savings", 88928.8, 81519.12, ""],
        ]

        assert pf.parse_budget_items(values) == {
            "gross_income": (328000, 327999.92),
            "401k": (24500, 24500),
            "401k_match": (7250, 7250),
            "take_home": (205469.23, 191356.16),
            "total_savings": (88928.8, 81519.12),
        }

    def test_rows_the_sheet_lacks_are_left_out(self):
        assert pf.parse_budget_items(BUDGET) == {"take_home": (120000, 84000)}


class TestParseSavingsLog:
    def test_reads_labelled_rows(self):
        values = [
            ["Conversion Rate", 0.0107, "", "Institution"],
            ["Stock Gain/Loss", -3485.71, "", "Interest Bank"],
            ["Dividends Received ", 312.9],
            ["Interest", 5321.66],
        ]

        assert pf.parse_savings_log(values) == {
            "stock_gain": -3485.71,
            "dividends": 312.9,
            "interest": 5321.66,
        }


class TestMarketChange:
    def test_change_less_contributions_and_401k(self):
        net_worth = pf.parse_net_worth(NET_WORTH, MONTHS)
        items = {"401k": (100, 0), "401k_match": (20, 0)}

        # 6280 - 6050 = 230 change; 175 contributed + 120 to the 401(k)
        market, share = pf.market_change(net_worth, items)

        assert market == -65
        assert share == -65 / 230


class TestParseNetWorth:
    def test_reads_subtotals_and_sums_contributions(self):
        df = pf.parse_net_worth(NET_WORTH, MONTHS)

        assert list(df["Cash & Savings"]) == [100, 200, 300]
        assert list(df["Liabilities"]) == [-50, -80, -20]
        assert list(df[pf.NET_WORTH]) == [6050, 6220, 6280]
        assert list(df[pf.CONTRIBUTIONS]) == [0, 100, 75]

    def test_missing_subtotal_raises(self):
        with pytest.raises(ValueError, match="Retirement"):
            pf.parse_net_worth(
                [r for r in NET_WORTH if "Retirement" not in str(r[:1])], MONTHS
            )


class TestContributionBuckets:
    def test_one_column_per_row_by_month(self):
        df = pf.contribution_buckets(NET_WORTH, MONTHS)

        assert list(df["Savings · Individual"]) == [0, 100, 50]
        assert list(df["Brokerage · Stocks"]) == [0, 0, 25]
        assert list(df.sum(axis=1)) == [0, 100, 75]

    def test_drops_empty_rows_and_sums_the_smallest_into_other(self):
        rows = [r for r in NET_WORTH if r[:1] != ["Total Contributed (YTD)"]]
        extra = [["", "Bonds", "I-Bonds", "", 0, 0, 0], ["", "Crypto", "", "", 0, 5, 0]]
        i = next(i for i, r in enumerate(rows) if r[1:2] == ["Brokerage"])
        df = pf.contribution_buckets(rows[: i + 1] + extra + rows[i + 1 :], MONTHS, 2)

        assert "Bonds · I-Bonds" not in df.columns
        assert list(df.columns) == ["Savings · Individual", "Other"]
        assert list(df["Other"]) == [0, 5, 25]

    def test_no_contribution_rows_is_empty(self):
        df = pf.contribution_buckets(NET_WORTH[:11], MONTHS)

        assert df.empty


class TestNetWorthChanges:
    def test_splits_change_into_saved_and_everything_else(self):
        changes = pf.net_worth_changes(pf.parse_net_worth(NET_WORTH, MONTHS))

        assert list(changes["change"]) == [170, 60]
        assert list(changes["saved"]) == [100, 75]
        assert list(changes["market"]) == [70, -15]


class TestNetWorthBreakdown:
    def test_accounts_under_each_subtotal(self):
        breakdown = pf.net_worth_breakdown(NET_WORTH, MONTHS)

        assert list(breakdown) == list(pf.NET_WORTH_COMPONENTS.values())
        # Named from institution, account and type, since column B alone is
        # often generic ("Savings")
        checking = "Bank · Checking · Individual"
        assert list(breakdown["Cash & Savings"].columns) == [checking]
        assert list(breakdown["Cash & Savings"][checking]) == [100, 200, 300]
        # No account rows, so the whole subtotal is unitemized; all-zero
        # Real Estate has nothing at all
        assert list(breakdown["Investments"][pf.UNLISTED]) == [1000, 1100, 900]
        assert breakdown["Real Estate"].empty

    def test_duplicates_gap_and_other(self):
        values = [
            _MONTH_HEADER,
            ["INVESTMENTS"],
            *[["", f"Fund {i}", "", "", i, i, i] for i in range(1, 6)],
            ["", "Fund 5", "", "", 10, 10, 10],
            ["", "Closed", "", "", 0, 0, 0],
            ["Subtotal – Investments", "", "", "", 100, 100, 100],
            ["NET WORTH", "", "", "", 100, 100, 100],
        ]
        df = pf.net_worth_breakdown(values, MONTHS, max_accounts=4)["Investments"]

        # Biggest three by latest balance, the rest summed into Other, and
        # the 100 - 25 the rows don't explain as Not itemized
        assert list(df.columns) == [
            "Fund 5 (2)",
            "Fund 5",
            "Fund 4",
            "Other",
            pf.UNLISTED,
        ]
        assert list(df["Other"]) == [6, 6, 6]
        assert list(df[pf.UNLISTED]) == [75, 75, 75]
        assert list(df.sum(axis=1)) == [100, 100, 100]


TEMPLATE_NET_WORTH = [
    ["Net Worth Tracker"],
    [],
    [
        "",
        "Account",
        "Type",
        "Institution",
        "Balance Key",
        "My Share %",
        *_MONTH_HEADER[4:],
    ],
    ["Cash Accounts"],
    ["", "Checking", "Individual", "Bank", "Checking", 1, 100, 200, 300],
    ["", "Joint HYSA", "Joint", "Online Bank", "(1111)", 0.5, 50, 50, 50],
    ["Subtotal – Checking & Savings", "", "", "", "", "", 150, 250, 350],
    ["INVESTMENTS"],
    ["", "Brokerage", "Stocks", "Robinhood", "Robinhood", 1, 900, 950, 1000],
    ["", "Joint brokerage", "Stocks", "Vanguard", "(4321)", 0.6, 0, 0, 600],
    ["", "Old account", "Stocks", "", "", "", 0, 0, 0],
    ["Subtotal – Investments", "", "", "", "", "", 900, 950, 1600],
    ["Subtotal – Retirement", "", "", "", "", "", 0, 0, 0],
    ["Subtotal – Real Estate", "", "", "", "", "", 0, 0, 0],
    ["Subtotal – Liabilities", "", "", "", "", "", 0, 0, 0],
    ["NET WORTH", "", "", "", "", "", 1050, 1200, 1950],
]


class TestNetWorthAccounts:
    def test_reads_key_share_and_latest_balance(self):
        accounts = pf.net_worth_accounts(TEMPLATE_NET_WORTH, MONTHS)

        # Old account is $0 all year, so it's left out
        assert list(accounts["Account"]) == [
            "Bank · Checking · Individual",
            "Online Bank · Joint HYSA · Joint",
            "Robinhood · Brokerage · Stocks",
            "Vanguard · Joint brokerage · Stocks",
        ]
        joint = accounts.iloc[1]
        assert (joint["Category"], joint["Key"], joint["Share"], joint["Balance"]) == (
            "Cash & Savings", "(1111)", 0.5, 50,
        )  # fmt: skip

    def test_old_layout_has_no_key_and_full_share(self):
        accounts = pf.net_worth_accounts(NET_WORTH, MONTHS)

        assert list(accounts["Key"]) == [""]
        assert list(accounts["Share"]) == [1.0]
        assert list(accounts["Institution"]) == ["Bank"]


# The older Budget sheet's Net Worth tab: no Balance Key or My Share %
# columns, a generic column B, and the mortgage kept positive and
# subtracted by the Real Estate subtotal's formula
OLD_NET_WORTH = [
    ["", "Account", "Type", "Brokerage/Bank", *_MONTH_HEADER[4:]],
    ["Cash Accounts"],
    ["", "Brokerage", "Uninvested", "Robinhood", 10, 10, 10],
    ["Subtotal – Checking & Savings", "", "", "", 10, 10, 10],
    ["INVESTMENTS"],
    ["", "Brokerage", "Stocks", "Wells Fargo", 100, 100, 150],
    ["", "Brokerage", "ETF", "Robinhood ", 50, 50, 50],
    ["", "Brokerage", "Crypto", "Robinhood", 20, 20, 20],
    ["", "Bonds", "I-Bonds", "TreasuryDirect", 5, 5, 5],
    ["Subtotal – Investments", "", "", "", 175, 175, 225],
    ["RETIREMENT"],
    ["", "Retirement", "401k", "Empower", 300, 300, 300],
    ["", "Retirement", "Roth IRA", "Fidelity", 40, 40, 40],
    ["Subtotal – Retirement", "", "", "", 340, 340, 340],
    ["REAL ESTATE"],
    ["", "Real Estate", "Home Value", "", 900, 900, 900],
    ["", "Liability", "Mortgage Balance", "", 700, 690, 680],
    ["Subtotal – Real Estate", "", "", "", 200, 210, 220],
    ["LIABILITIES"],
    ["", "Liability", "Credit Card", "Amex", -5, -5, -5],
    ["Subtotal – Liabilities", "", "", "", -5, -5, -5],
    ["NET WORTH", "", "", "", 720, 730, 790],
]

OLD_HOLDINGS = pd.DataFrame(
    {
        "Institution": [
            "Wells Fargo", "Robinhood", "Robinhood", "Empower Retirement",
            "Empower Retirement", "Fidelity Investments", "Fidelity Investments",
        ],
        "Account Name": [
            "WELLSTRADE (8888)", "Robinhood individual (8001)", "Crypto (8002)",
            "Acme Corp 401(k) Plan", "Acme Corp 401(k) Plan", "ROTH IRA (9999)",
            "Traditional IRA (8003)",
        ],
        "Symbol": ["NVDA", "VTI", "BTC", "SSPNLM", "SSPNLM", "FZROX", "SPAXX"],
        "Description": ["Nvidia", "Total Market", "Bitcoin", "S&P 500", "S&P 500",
                        "Zero Total", "Money market"],
        "Shares": [1, 2, 0.01, 10, 5, 3, 6],
        "Market Value": [150, 50, 20, 200, 100, 40, 6],
    }
)  # fmt: skip


class TestOldLayout:
    def test_debt_rows_count_as_negative(self):
        df = pf.net_worth_breakdown(OLD_NET_WORTH, MONTHS)["Real Estate"]

        assert list(df["Liability · Mortgage Balance"]) == [-700, -690, -680]
        # So the rows add up to the subtotal, with nothing unitemized
        assert pf.UNLISTED not in df.columns
        assert list(df.sum(axis=1)) == [200, 210, 220]

    def test_matches_holdings_by_institution_then_type(self):
        accounts = pf.net_worth_accounts(OLD_NET_WORTH, MONTHS)
        sources = pf.holdings_accounts(accounts, OLD_HOLDINGS)
        by_name = {accounts.at[i, "Account"]: v for i, v in sources.items()}

        # "Crypto" and "401k"/"401(k)" by type; Wells Fargo and Robinhood's
        # ETF row are their institution's only row left; Robinhood's
        # uninvested cash isn't an invested category, and TreasuryDirect
        # reports no holdings
        assert by_name == {
            "Robinhood · Brokerage · Uninvested": [],
            "Wells Fargo · Brokerage · Stocks": [("Wells Fargo", "WELLSTRADE (8888)")],
            "Robinhood · Brokerage · ETF": [("Robinhood", "Robinhood individual (8001)")],
            "Robinhood · Brokerage · Crypto": [("Robinhood", "Crypto (8002)")],
            "TreasuryDirect · Bonds · I-Bonds": [],
            "Empower · Retirement · 401k": [("Empower Retirement", "Acme Corp 401(k) Plan")],
            "Fidelity · Retirement · Roth IRA": [("Fidelity Investments", "ROTH IRA (9999)")],
            "Real Estate · Home Value": [],
            "Liability · Mortgage Balance": [],
            "Amex · Liability · Credit Card": [],
        }  # fmt: skip

    def test_merges_a_fund_listed_per_money_source(self):
        accounts = pf.net_worth_accounts(OLD_NET_WORTH, MONTHS)
        df = pf.category_holdings(OLD_HOLDINGS, accounts, "Retirement")

        assert list(df["Symbol"]) == ["SSPNLM", "FZROX"]
        assert list(df["Shares"]) == [15, 3]
        assert df["Value"].sum() == 340

    def test_no_weights_when_assets_and_debts_mix(self):
        accounts = pf.net_worth_accounts(OLD_NET_WORTH, MONTHS)
        df = pf.category_holdings(OLD_HOLDINGS, accounts, "Real Estate")

        assert list(df["Value"]) == [900, -680]
        assert df["Weight"].isna().all()


HOLDINGS = pd.DataFrame(
    {
        "Institution": ["Robinhood", "Robinhood", "Vanguard", "Wells Fargo"],
        "Account Name": [
            "Individual",
            "Crypto",
            "Joint Brokerage (4321)",
            "WellsTrade",
        ],
        "Symbol": ["AAPL", "BTC", "VTI", "NVDA"],
        "Description": ["Apple", "Bitcoin", "Total Market", "Nvidia"],
        "Shares": [2, 0.01, 4, 1],
        "Market Value": [600, 300, 1000, 150],
    }
)


class TestHoldingsDrillDown:
    @pytest.fixture
    def accounts(self):
        return pf.net_worth_accounts(TEMPLATE_NET_WORTH, MONTHS)

    def holdings_of(self, accounts, i):
        sources = pf.holdings_accounts(accounts, HOLDINGS)
        return pf.account_holdings(HOLDINGS, accounts.iloc[i], sources[i])

    def test_holdings_plus_cash_left_over(self, accounts):
        # The "Robinhood" key matches both Robinhood accounts by institution
        df = self.holdings_of(accounts, 2)

        assert list(df["Description"]) == ["Apple", "Bitcoin", pf.CASH_AND_OTHER]
        assert list(df["Value"]) == [600, 300, 100]

    def test_share_scales_holdings_matched_by_digits(self, accounts):
        df = self.holdings_of(accounts, 3)

        assert list(df["Symbol"]) == ["VTI"]
        assert list(df["Value"]) == [600]
        assert list(df["Shares"]) == [2.4]

    def test_no_row_for_holdings_above_the_balance(self, accounts):
        # Holdings worth more than the row is price timing, not a position
        account = accounts.iloc[3].copy()
        account["Balance"] = 500
        df = pf.account_holdings(
            HOLDINGS, account, [("Vanguard", "Joint Brokerage (4321)")]
        )

        assert list(df["Description"]) == ["Total Market"]
        assert list(df["Value"]) == [600]

    def test_account_without_holdings_is_one_row(self, accounts):
        df = self.holdings_of(accounts, 0)

        assert list(df["Description"]) == [pf.BALANCE_ONLY]
        assert list(df["Value"]) == [300]

    def test_category_rows_with_weights(self, accounts):
        df = pf.category_holdings(HOLDINGS, accounts, "Investments")

        assert list(df["Symbol"]) == ["AAPL", "VTI", "BTC", ""]
        assert df["Value"].sum() == 1600
        assert df["Weight"].iloc[0] == 600 / 1600

    def test_no_holdings_tab_still_lists_accounts(self, accounts):
        df = pf.category_holdings(pd.DataFrame(), accounts, "Cash & Savings")

        assert list(df["Account"]) == [
            "Bank · Checking · Individual",
            "Online Bank · Joint HYSA · Joint",
        ]
        assert list(df["Description"]) == [pf.BALANCE_ONLY] * 2


class TestAllocation:
    @pytest.fixture
    def split(self):
        net_worth = pf.parse_net_worth(OLD_NET_WORTH, MONTHS)
        accounts = pf.net_worth_accounts(OLD_NET_WORTH, MONTHS)
        return pf.allocation(accounts, net_worth)

    def test_asset_categories_without_liabilities(self, split):
        by_category, _ = split

        # Latest month: 10 + 225 + 340 + 220 = 795 in assets
        assert list(by_category["category"]) == [
            "Cash & Savings", "Investments", "Retirement", "Real Estate",
        ]  # fmt: skip
        assert list(by_category["value"]) == [10, 225, 340, 220]
        assert by_category["weight"].sum() == pytest.approx(1)
        assert by_category["weight"].iloc[2] == 340 / 795

    def test_types_within_a_category(self, split):
        _, by_type = split
        investments = by_type[by_type["category"] == "Investments"]

        # Robinhood's two rows have different types, so stay apart
        assert list(investments["type"]) == ["Stocks", "ETF", "Crypto", "I-Bonds"]
        assert list(investments["value"]) == [150, 50, 20, 5]
        assert investments["weight"].iloc[0] == 150 / 225
        assert investments["of_assets"].iloc[0] == 150 / 795

    def test_no_shares_when_assets_and_debts_mix(self, split):
        _, by_type = split
        real_estate = by_type[by_type["category"] == "Real Estate"]

        assert list(real_estate["value"]) == [900, -680]
        assert real_estate["weight"].isna().all()

    def test_same_type_however_written_is_one_group(self):
        values = [
            ["", "Account", "Type", "Institution", *_MONTH_HEADER[4:]],
            ["", "Brokerage", "ETF", "Robinhood", 1, 1, 30],
            ["", "Brokerage", "etf ", "Online Bank", 1, 1, 70],
            ["Subtotal – Investments", "", "", "", 2, 2, 100],
            ["NET WORTH", "", "", "", 2, 2, 100],
        ]
        net_worth = pf.parse_net_worth(
            [*values[:-1], *[[f"Subtotal – {k}", "", "", "", 0, 0, 0] for k in
                             ("Checking", "Retirement", "Real Estate", "Liabilities")],
             values[-1]],
            MONTHS,
        )  # fmt: skip
        _, by_type = pf.allocation(pf.net_worth_accounts(values, MONTHS), net_worth)

        assert list(by_type["type"]) == ["ETF"]
        assert list(by_type["value"]) == [100]


class TestAccountTypes:
    def test_type_column_or_account_name_with_spellings_merged(self):
        accounts = pd.DataFrame(
            {
                "Category": ["Investments", "Investments", "Investments", "Retirement"],
                "Account": [
                    "Robinhood · Brokerage",
                    "Online Bank",
                    "TreasuryDirect",
                    "Empower",
                ],
                "Type": ["ETF", " etf ", "", "ETF"],
            }
        )

        # Same type within a category takes its first spelling; a blank type
        # is the account's name
        assert list(pf.account_types(accounts)) == [
            "ETF",
            "ETF",
            "TreasuryDirect",
            "ETF",
        ]

    def test_matches_the_allocation_groups(self):
        accounts = pf.net_worth_accounts(OLD_NET_WORTH, MONTHS)
        _, by_type = pf.allocation(accounts, pf.parse_net_worth(OLD_NET_WORTH, MONTHS))
        types = pf.account_types(accounts)
        investments = accounts["Category"] == "Investments"

        assert set(types[investments]) <= set(
            by_type.loc[by_type["category"] == "Investments", "type"]
        )


class TestCategorySummary:
    def test_values_shares_and_change_since_the_first_month(self):
        net_worth = pf.parse_net_worth(OLD_NET_WORTH, MONTHS)
        summary = pf.category_summary(net_worth).set_index("category")

        assert list(summary.index) == list(pf.NET_WORTH_COMPONENTS.values())
        assert summary.loc[pf.ASSET_COMPONENTS, "weight"].sum() == pytest.approx(1)
        assert summary.loc["Retirement", "weight"] == 340 / 795
        assert pd.isna(summary.loc["Liabilities", "weight"])
        for category in summary.index:
            assert summary.loc[category, "value"] == net_worth[category].iloc[-1]
            assert summary.loc[category, "change"] == (
                net_worth[category].iloc[-1] - net_worth[category].iloc[0]
            )
