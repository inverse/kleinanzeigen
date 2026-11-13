"""Offline tests for mobile API search and detail mapping."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import pytest_socket

from kleinanzeigen.client import Kleinanzeigen
from kleinanzeigen.mobile import (
    AD_NS,
    _detail_from_ad,
    _listing_from_ad,
    _parse_published_at,
    _search_params,
)
from kleinanzeigen.models import AdStatus, SearchParams, SortField


def _val(x):
    return {"value": x}


def _ad(**overrides):
    ad = {
        "id": "3569727847",
        "title": _val("Fahrradschuhe Shimano Größe 43"),
        "description": _val("Sehr gut erhalten.<br /><br />Privatverkauf."),
        "price": {
            "amount": _val(30),
            "price-type": _val("SPECIFIED_AMOUNT"),
        },
        "ad-address": {"state": _val("Hohentengen"), "zip-code": _val("88367")},
        "locations": {
            "location": [{"localized-name": _val("88367 Hohentengen"), "id": "8729"}]
        },
        "start-date-time": _val("2026-11-12T23:16:50.000+0100"),
        "link": [
            {"href": "https://api.kleinanzeigen.de/api/ads/3569727847", "rel": "self"},
            {
                "href": "https://www.kleinanzeigen.de/s-anzeige/fahrradschuhe-shimano-groesse-43/3569727847-230-8729",
                "rel": "self-public-website",
            },
        ],
    }
    ad.update(overrides)
    return ad


def test_listing_from_ad_maps_fields():
    listing = _listing_from_ad(_ad())
    assert listing is not None
    assert listing.ad_id == "3569727847"
    assert listing.url.endswith("/3569727847-230-8729")
    assert listing.title == "Fahrradschuhe Shimano Größe 43"
    assert listing.price == Decimal(30)
    assert listing.location == "88367 Hohentengen"
    assert listing.distance_km is None
    assert "Privatverkauf" in listing.description
    assert "<br" not in listing.description
    # +0100 offset -> naive Europe/Berlin local time, same convention as web dates.
    assert listing.published_at == datetime(2026, 11, 12, 23, 16, 50)
    assert listing.is_top_ad is False


def test_listing_from_ad_free_and_range_prices_are_none():
    free = _ad(price={"amount": _val(None), "price-type": _val("FREE")})
    assert _listing_from_ad(free).price is None
    ranged = _ad(
        price={
            "amount": _val(None),
            "range-amount": {"min": _val(100), "max": _val(200)},
            "price-type": _val("RANGE"),
        }
    )
    assert _listing_from_ad(ranged).price is None


def test_listing_from_ad_distance_and_adres_fallback():
    ad = _ad(
        locations={},
        **{"search-distance": {"distance": _val("0.5293582")}},
    )
    listing = _listing_from_ad(ad)
    assert listing.distance_km == pytest.approx(0.5293582)
    assert listing.location == "88367 Hohentengen"

    no_locations = _ad(locations={})
    assert _listing_from_ad(no_locations).location == "88367 Hohentengen"


def test_listing_from_ad_missing_id_returns_none():
    ad = _ad(id=None, link=[])
    assert _listing_from_ad(ad) is None


def test_parse_published_at_variants():
    assert _parse_published_at(_val("2026-11-12T23:16:50.000+0100")) == datetime(
        2026, 11, 12, 23, 16, 50
    )
    assert _parse_published_at(_val("")) is None
    assert _parse_published_at(_val("not a date")) is None
    assert _parse_published_at(None) is None


def test_search_params_sort_validation():
    with pytest.raises(ValueError, match="location"):
        SearchParams(query="x", sort=SortField.DISTANCE)
    params = SearchParams(query="x", location="Berlin", sort=SortField.DISTANCE)
    assert params.sort is SortField.DISTANCE
    # Other sorts don't need a location.
    assert SearchParams(query="x", sort=SortField.PRICE_ASC).sort is SortField.PRICE_ASC


def test_search_params_default_to_newest():
    request = _search_params(SearchParams(query="x"), None)
    assert request["sortType"] == "DATE_DESCENDING"
    assert request["page"] == 0


def test_detail_from_ad_maps_mobile_fields():
    scraped_at = datetime(2026, 11, 13, 10, tzinfo=UTC)
    ad = _ad(
        **{
            "ad-status": _val("RESERVED"),
            "contact-name": _val("Max"),
            "user-id": _val("42"),
            "user-since-date-time": _val("2020-01-05T20:59:31.000+0100"),
            "seller-account-type": _val("BUSINESS"),
            "userBadges": {"badges": [{"name": "friendliness", "value": ""}]},
            "category": {"localized-name": _val("Fahrräder & Zubehör")},
            "attributes": {
                "attribute": [
                    {
                        "localized-label": "Zustand",
                        "value": [{"value": "ok", "localized-label": "Gut"}],
                    }
                ]
            },
            "features-active": {
                "feature-active": [{"name": "gps", "localized-label": "GPS"}]
            },
            "shipping-options": {"shipping-option": []},
            "pictures": {
                "picture": [
                    {
                        "link": [
                            {"rel": "thumbnail", "href": "https://img.test/thumb"},
                            {"rel": "large", "href": "https://img.test/large"},
                        ]
                    }
                ]
            },
            "locations": {
                "location": [
                    {
                        "localized-name": _val("88367 Hohentengen"),
                        "regions": {
                            "region": [{"localized-name": _val("Baden-Württemberg")}]
                        },
                    }
                ]
            },
            "price": {
                "amount": _val(30),
                "price-type": _val("PLEASE_CONTACT"),
            },
        }
    )

    detail = _detail_from_ad(ad, scraped_at=scraped_at)

    assert detail.ad_id == "3569727847"
    assert detail.status is AdStatus.RESERVED
    assert detail.price.amount == Decimal(30)
    assert detail.price.negotiable is True
    assert detail.categories == ["Fahrräder & Zubehör"]
    assert detail.description == "Sehr gut erhalten.\n\nPrivatverkauf."
    assert detail.location.postal_code == "88367"
    assert detail.location.city == "Hohentengen"
    assert detail.location.state == "Baden-Württemberg"
    assert detail.delivery == "pickup"
    assert detail.images == ["https://img.test/large"]
    assert detail.details == {"Zustand": "Gut"}
    assert detail.features == ["GPS"]
    assert detail.seller.name == "Max"
    assert detail.seller.user_id == "42"
    assert detail.seller.member_since == "2020-01-05"
    assert detail.seller.type == "business"
    assert detail.seller.badges == ["friendliness"]
    assert detail.created_at.isoformat() == "2026-11-12"
    assert detail.scraped_at == scraped_at


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code

    def raise_for_status(self):
        pass

    def json(self):
        return {AD_NS: {"value": _ad()}}


class _Session:
    timeout = 30

    def __init__(self, status_code=200):
        self.status_code = status_code
        self.urls = []

    async def get(self, url, **kwargs):
        self.urls.append(url)
        return _Response(self.status_code)


def _run(awaitable):
    pytest_socket.enable_socket()
    try:
        return asyncio.run(awaitable)
    finally:
        pytest_socket.disable_socket()


def test_get_listing_extracts_id_from_url():
    session = _Session()
    ka = Kleinanzeigen(session=session)

    detail = _run(
        ka.get_listing(
            "https://www.kleinanzeigen.de/s-anzeige/shimano/3569727847-230-8729?source=test"
        )
    )

    assert detail is not None
    assert detail.ad_id == "3569727847"
    assert session.urls == ["https://api.kleinanzeigen.de/api/ads/3569727847.json"]


def test_get_listing_returns_none_for_missing_ad():
    session = _Session(status_code=404)
    ka = Kleinanzeigen(session=session)
    assert _run(ka.get_listing("0")) is None
