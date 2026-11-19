from src import dashboard_nav as nav


class TestNavLinks:
    def test_defaults_are_the_combined_servers_paths(self, monkeypatch):
        for var in (
            "FINANCE_DASHBOARD_URL",
            "NET_WORTH_DASHBOARD_URL",
            "PNL_DASHBOARD_URL",
            "SPENDING_DASHBOARD_URL",
        ):
            monkeypatch.delenv(var, raising=False)
        assert nav.nav_links(nav.PNL) == [
            ("Overview", "/", False, False),
            ("Net Worth", "/net-worth", False, False),
            ("Swing Trading", "/pnl", True, True),
        ]

    def test_spending_link_appears_once_its_url_is_set(self, monkeypatch):
        monkeypatch.setenv("SPENDING_DASHBOARD_URL", "https://spending.example.com")
        assert (
            "Spending",
            "https://spending.example.com",
            False,
            True,
        ) in nav.nav_links(nav.OVERVIEW)

    def test_html_marks_the_current_page_and_escapes(self, monkeypatch):
        monkeypatch.setenv("SPENDING_DASHBOARD_URL", "https://x.example/?a=1&b=2")
        page = nav.nav_html(nav.OVERVIEW)
        assert '<a href="/" target="_top" class="active">Overview</a>' in page
        assert 'href="https://x.example/?a=1&amp;b=2"' in page
        assert ">Swing Trading<svg" in page

    def test_separate_apps_get_the_external_icon(self, monkeypatch):
        monkeypatch.setenv("SPENDING_DASHBOARD_URL", "https://spending.example.com")
        page = nav.nav_html(nav.OVERVIEW)
        assert page.count('class="t-nav-ext"') == 2
        assert ">Overview</a>" in page
        assert ">Net Worth</a>" in page
