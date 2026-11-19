from src import dashboard_nav as nav

_URL_VARS = (
    "FINANCE_DASHBOARD_URL",
    "NET_WORTH_DASHBOARD_URL",
    "PNL_DASHBOARD_URL",
    "SPENDING_DASHBOARD_URL",
)


class TestNavLinks:
    def test_by_default_only_this_app_is_linked(self, monkeypatch):
        for var in _URL_VARS:
            monkeypatch.delenv(var, raising=False)
        assert nav.nav_links(nav.PNL) == [("Swing Trading", "/", True, False)]

    def test_other_dashboards_appear_once_their_urls_are_set(self, monkeypatch):
        for var in _URL_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("FINANCE_DASHBOARD_URL", "https://finance.example.com/")
        monkeypatch.setenv(
            "NET_WORTH_DASHBOARD_URL", "https://finance.example.com/net-worth"
        )
        monkeypatch.setenv("SPENDING_DASHBOARD_URL", "https://spending.example.com")
        assert nav.nav_links(nav.PNL) == [
            ("Yearly Overview", "https://finance.example.com/", False, True),
            ("Net Worth", "https://finance.example.com/net-worth", False, True),
            ("Swing Trading", "/", True, False),
            ("Spending", "https://spending.example.com", False, True),
        ]

    def test_html_marks_the_current_page_and_escapes(self, monkeypatch):
        for var in _URL_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("SPENDING_DASHBOARD_URL", "https://x.example/?a=1&b=2")
        page = nav.nav_html(nav.PNL)
        assert '<a href="/" target="_top" class="active">Swing Trading</a>' in page
        assert 'href="https://x.example/?a=1&amp;b=2"' in page

    def test_separate_apps_get_the_external_icon(self, monkeypatch):
        for var in _URL_VARS:
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("FINANCE_DASHBOARD_URL", "https://finance.example.com/")
        monkeypatch.setenv("SPENDING_DASHBOARD_URL", "https://spending.example.com")
        page = nav.nav_html(nav.PNL)
        assert page.count('class="t-nav-ext"') == 2
        assert ">Swing Trading</a>" in page
