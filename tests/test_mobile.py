"""Offline tests for the mobile API ad->Listing mapping (no HTTP)."""

from datetime import datetime
from decimal import Decimal

import pytest

from kleinanzeigen.mobile import _listing_from_ad, _parse_published_at
from kleinanzeigen.models import SearchParams, SortField


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
