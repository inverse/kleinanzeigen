"""Tests for CLI helpers and argument validation — no network."""

import inspect
import re

import pytest
from click.testing import CliRunner
from rich.console import Console

from kleinanzeigen import cli
from kleinanzeigen.models import (
    ListingDetail,
    Location,
    Price,
    SearchParams,
    Seller,
)

_ANSI_RE = re.compile(r"\x1b\][^\x1b\x07]*(?:\x07|\x1b\\)|\x1b\[[0-9;:]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


def test_search_pages_iter_dispatches_params():
    ka = cli.Kleinanzeigen.__new__(cli.Kleinanzeigen)
    ka._page_delay = 1.0
    it = cli._search_pages_iter(ka, SearchParams(query="x"), pages=0)
    assert inspect.isasyncgen(it)


def test_search_pages_iter_dispatches_url():
    ka = cli.Kleinanzeigen.__new__(cli.Kleinanzeigen)
    ka._page_delay = 1.0
    it = cli._search_pages_iter(ka, "https://www.kleinanzeigen.de/s-markt/", pages=2)
    assert inspect.isasyncgen(it)


def test_render_detail_escapes_markup():
    detail = ListingDetail(
        ad_id="1",
        url="https://www.kleinanzeigen.de/s-anzeige/x/1",
        title="Bike [cheap] <offer>",
        status="active",
        price=Price(amount=100, negotiable=True),
        description="Line one\nLine [two]",
        location=Location(city="Berlin", postal_code="10115"),
        delivery="pickup",
        details={"Marke": "[Renn]rad"},
        features=["GPS [tracker]"],
        seller=Seller(name="Max [M]", member_since="01.01.2020", type="private"),
        images=["https://img.example.com/a.jpg"],
    )
    console = Console(width=100)
    with console.capture() as cap:
        console.print(cli._render_detail(detail))
    rendered = _strip_ansi(cap.get())
    assert "Bike [cheap] <offer>" in rendered
    assert "Line [two]" in rendered
    assert "[Renn]rad" in rendered
    assert "GPS [tracker]" in rendered
    assert "Max [M]" in rendered
    assert "100 €" in rendered
    assert "Pickup only" in rendered
    assert "image 1" in rendered


def _runner() -> CliRunner:
    return CliRunner()


def test_search_rejects_invalid_bounds():
    runner = _runner()
    for args in (
        ["search", "-q", "bike", "--page", "0"],
        ["search", "-q", "bike", "--pages", "-1"],
        ["search", "-q", "bike", "--radius", "-1"],
        ["search-url", "https://www.kleinanzeigen.de/s-x/", "--pages", "-1"],
    ):
        result = runner.invoke(cli.cli, args)
        assert result.exit_code == 2, args
        assert "Invalid value" in result.output, args


def test_search_rejects_bad_published_after():
    result = _runner().invoke(
        cli.cli, ["search", "-q", "bike", "--published-after", "not-a-date"]
    )
    assert result.exit_code == 2
    assert "not a valid ISO" in result.output


def test_search_rejects_inverted_price_range():
    result = _runner().invoke(
        cli.cli, ["search", "-q", "bike", "--min-price", "10", "--max-price", "5"]
    )
    assert result.exit_code == 2
    assert "min_price" in result.output


def test_iter_search_url_rejects_negative_pages():
    ka = cli.Kleinanzeigen.__new__(cli.Kleinanzeigen)
    ka._page_delay = 1.0
    it = ka.iter_search_url("https://www.kleinanzeigen.de/s-x/", pages=-1)
    # Drive the async generator manually: it raises before the first await.
    with pytest.raises(ValueError, match="pages must be >= 0"):
        it.asend(None).send(None)
