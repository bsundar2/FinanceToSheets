"""Column headers of the brokerage tabs. The sheet's formulas read these tabs,
so the labels and their order are kept exactly as the original Robinhood and
Wells Fargo pipelines wrote them."""

TICKER = "Ticker"
NAME = "Name"
AVG_PRICE = "Avg Price"
QUANTITY = "Quantity"
TOTAL = "Total"
DIVERSITY = "Diversity"
DESCRIPTION = "Description"
SECTOR = "Sector"
INDUSTRY = "Industry"
DVD_RATE = "DVD Rate"
LAST_DIVIDEND = "Last Quarterly Dividend"
TOTAL_DVD_PAID = "Total DVD Paid"
PROJECTED_DVD = "Projected DVD"
LAST_YEAR_DVD = "Last Year's DVD"
YTD_DVD = "YTD DVD"

RH_STOCK_COLUMNS = [
    TICKER,
    NAME,
    AVG_PRICE,
    QUANTITY,
    TOTAL,
    DIVERSITY,
    DESCRIPTION,
    SECTOR,
    INDUSTRY,
    DVD_RATE,
    LAST_DIVIDEND,
    TOTAL_DVD_PAID,
    PROJECTED_DVD,
    LAST_YEAR_DVD,
    YTD_DVD,
]

RH_CRYPTO_COLUMNS = [TICKER, NAME, AVG_PRICE, QUANTITY, TOTAL]

# WF_stock_dump / WF_etf_dump, in the WellsTrade export's naming
WF_COLUMNS = [
    "Symbol",
    "Description",
    "Quantity",
    "Average Cost Basis",
    "Current Value",
    DVD_RATE,
    "Est. Annual Yield",
    PROJECTED_DVD,
]
