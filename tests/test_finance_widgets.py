from src.finance_widgets import ShareBar


def test_share_bar_defaults_to_nothing_selected():
    bar = ShareBar(names=["A", "B"], values=[1.0, 3.0], colors=["#000", "#fff"])

    assert bar.selected == ""
    assert bar.allow_none is False
    assert bar.chips == []


def test_share_bar_syncs_what_the_page_needs():
    synced = set(ShareBar().keys)

    assert {
        "names",
        "values",
        "colors",
        "chips",
        "selected",
        "allow_none",
        "height",
    } <= synced
