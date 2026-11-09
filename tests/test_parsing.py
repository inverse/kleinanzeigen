"""Tests for the pure parsing helpers — no network, real captured HTML."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup

from kleinanzeigen import parsing
from kleinanzeigen.models import AdStatus, Listing


def test_parse_listing_date():
    today = date.today()
    assert parsing.parse_listing_date("Heute, 10:30") == datetime(
        today.year, today.month, today.day, 10, 30
    )
    yesterday = today - timedelta(days=1)
    assert parsing.parse_listing_date("Gestern, 19:30") == datetime(
        yesterday.year, yesterday.month, yesterday.day, 19, 30
    )
    assert parsing.parse_listing_date("25.12.2020") == datetime(2020, 12, 25)
    assert parsing.parse_listing_date("") is None
    assert parsing.parse_listing_date("garbage") is None


def test_parse_breadcrumb(search_html):
    soup = BeautifulSoup(search_html, "html.parser")
    # Real page: "1 - 25 von 836.909 Ergebnissen ..."
    assert parsing.parse_breadcrumb(soup) == (836909, 33477)
    assert parsing.parse_breadcrumb(BeautifulSoup("<p>nothing</p>", "html.parser")) == (
        None,
        None,
    )


def test_inject_page():
    # Canonical paginated URLs: the page segment is replaced in place.
    assert (
        parsing.inject_page("https://www.kleinanzeigen.de/s-seite:3/fahrrad/k0", 2)
        == "https://www.kleinanzeigen.de/s-seite:2/fahrrad/k0"
    )
    assert (
        parsing.inject_page(
            "https://www.kleinanzeigen.de/s-autos/seite:3/autos/k0c216", 5
        )
        == "https://www.kleinanzeigen.de/s-autos/seite:5/autos/k0c216"
    )
    # Page-1 normalization keeps paginated URLs usable.
    assert (
        parsing.inject_page("https://www.kleinanzeigen.de/s-seite:3/fahrrad/k0", 1)
        == "https://www.kleinanzeigen.de/s-seite:1/fahrrad/k0"
    )
    # A URL without a page segment already serves page 1.
    assert (
        parsing.inject_page("https://www.kleinanzeigen.de/s-fahrrad/k0", 1)
        == "https://www.kleinanzeigen.de/s-fahrrad/k0"
    )
    # Deeper pages are not derivable — they come from pagination links.
    with pytest.raises(ValueError):
        parsing.inject_page("https://www.kleinanzeigen.de/s-fahrrad/k0", 2)


def test_pagination_url_for():
    html = """
    <html><body>
      <a href="/s-seite:2/fahrrad/k0">2</a>
      <a href="/s-seite:3/fahrrad/k0">3</a>
      <a href="/s-unternehmensseiten-verzeichnis.html">other</a>
    </body></html>
    """
    url_for = parsing.pagination_url_for(
        BeautifulSoup(html, "html.parser"),
        base_url="https://www.kleinanzeigen.de/s-fahrrad/k0",
    )
    assert url_for is not None
    assert url_for(7) == "https://www.kleinanzeigen.de/s-seite:7/fahrrad/k0"

    # Category-style pagination keeps 'seite:' mid-path.
    html = '<a href="/s-autos/seite:2/autos/k0c216">2</a>'
    url_for = parsing.pagination_url_for(
        BeautifulSoup(html, "html.parser"),
        base_url="https://www.kleinanzeigen.de/s-autos/k0c216",
    )
    assert url_for is not None
    assert url_for(4) == "https://www.kleinanzeigen.de/s-autos/seite:4/autos/k0c216"

    # No pagination links -> single page of results.
    assert (
        parsing.pagination_url_for(
            BeautifulSoup("<p>nothing</p>", "html.parser"),
            base_url="https://www.kleinanzeigen.de/",
        )
        is None
    )


def test_parse_ad_previews(search_html):
    previews = parsing.parse_ad_previews(search_html)
    assert previews
    # First fixture ad is a top ad pinned by sortingDate
    first = previews["3547139522"]
    assert first["sortingDate"] == "20.10.2026"
    assert first["topAd"] is True


def test_extract_listings_from_search_page(search_html):
    soup = BeautifulSoup(search_html, "html.parser")
    previews = parsing.parse_ad_previews(search_html)
    articles = soup.select("article[data-adid]")
    assert len(articles) == 3

    listings = [
        listing
        for article in articles
        if (listing := parsing.extract_listing(article, previews)) is not None
    ]
    assert len(listings) == 3

    first = listings[0]
    assert first.ad_id == "3547139522"
    assert first.url.endswith("/3547139522-217-4285")
    assert first.title == "TREK TOP FUEL 5.5"
    assert first.price == Decimal(1450)
    assert "Hanau" in first.location
    assert first.published_at is not None
    assert first.is_top_ad is True

    # Non-top ad gets its date from the card itself
    third = listings[2]
    assert third.ad_id == "3566143569"
    assert third.is_top_ad is False
    assert third.published_at is not None


def test_extract_listing_top_ad_date_fallback(search_html):
    """Top ads show no date on the card; sortingDate from astro props fills it."""
    soup = BeautifulSoup(search_html, "html.parser")
    previews = parsing.parse_ad_previews(search_html)
    article = soup.select_one('article[data-adid="3547139522"]')
    listing = parsing.extract_listing(article, previews)
    assert listing is not None
    assert listing.is_top_ad is True
    # sortingDate "20.10.2026" -> datetime at midnight
    assert listing.published_at == datetime(2026, 10, 20)


def test_extract_detail(detail_html):
    soup = BeautifulSoup(detail_html, "html.parser")
    detail = parsing.extract_detail(
        soup,
        url="https://www.kleinanzeigen.de/s-anzeige/trek-top-fuel-5-5/3547139522-217-4285",
        scraped_at=None,
    )

    assert detail.ad_id == "3547139522"
    assert detail.status is AdStatus.ACTIVE
    assert detail.title == "TREK TOP FUEL 5.5"
    assert detail.price.amount == Decimal(1450)
    assert detail.price.negotiable is True
    assert detail.categories == [
        "Kleinanzeigen Hanau",
        "Auto, Rad & Boot",
        "Fahrräder & Zubehör",
    ]
    assert detail.description is not None
    assert len(detail.images) == 8
    assert detail.details  # non-empty key/value pairs
    assert detail.location.postal_code == "63450"
    assert detail.location.city == "Hanau"
    assert detail.location.state == "Hessen"
    assert detail.delivery == "pickup"
    # Seller fields present without pinning PII values
    assert detail.seller.name
    assert detail.seller.user_id
    assert detail.seller.type == "private"
    assert detail.seller.member_since
    assert detail.created_at == date(2026, 10, 20)


def _listing(ad_id: str, published_at=None, is_top_ad=False):
    return Listing(
        ad_id=ad_id,
        url=f"https://x/{ad_id}",
        title=ad_id,
        price=None,
        location="",
        distance_km=None,
        description="",
        published_at=published_at,
        is_top_ad=is_top_ad,
    )


def test_parse_price():
    assert parsing.parse_price("5.000 € VB").amount == Decimal(5000)
    assert parsing.parse_price("5.000 € VB").negotiable is True
    assert parsing.parse_price("1.234,56 €").amount == Decimal("1234.56")
    # No numeric price: amount is None, not a fabricated 0.
    assert parsing.parse_price("").amount is None
    assert parsing.parse_price("VB").amount is None
    assert parsing.parse_price("VB").negotiable is True
    assert parsing.parse_price(None).amount is None


def test_apply_published_after():
    cutoff = datetime(2026, 6, 1)
    old = _listing("old", published_at=datetime(2026, 1, 1))
    new = _listing("new", published_at=datetime(2026, 7, 1))
    undated = _listing("undated", published_at=None)
    old_top = _listing("old-top", published_at=datetime(2020, 1, 1), is_top_ad=True)

    kept, stop = parsing.apply_published_after([old_top, new, undated, old], cutoff)
    assert kept == [old_top, new, undated]
    assert stop is True

    kept, stop = parsing.apply_published_after([old_top, new, undated], cutoff)
    assert kept == [old_top, new, undated]
    assert stop is False


def test_dedupe_by_ad_id():
    a = _listing("1")
    b = _listing("2")
    assert parsing.dedupe_by_ad_id([a, b, a]) == [a, b]
