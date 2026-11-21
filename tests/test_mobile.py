"""Offline tests for mobile API search and detail mapping."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import pytest_socket

from kleinanzeigen import mobile
from kleinanzeigen.client import Kleinanzeigen
from kleinanzeigen.mobile import (
    AD_NS,
    ADS_NS,
    _detail_from_ad,
    _listing_from_ad,
    _parse_published_at,
    _search_params,
    iter_search,
    resolve_category_id,
)
from kleinanzeigen.models import AdStatus, AdType, PosterType, SearchParams, SortField


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
    request = _search_params(SearchParams(query="x"), None, None)
    assert request["sortType"] == "DATE_DESCENDING"
    assert request["page"] == 0


def test_search_params_extended_filters():
    request = _search_params(
        SearchParams(
            query="x",
            poster_type=PosterType.COMMERCIAL,
            ad_type=AdType.WANTED,
            picture_required=True,
            shippable=True,
            buy_now_only=True,
            include_top_ads=False,
        ),
        None,
        None,
    )
    assert request["posterType"] == "COMMERCIAL"
    assert request["adType"] == "WANTED"
    assert request["pictureRequired"] == "true"
    assert request["shippable"] == "true"
    assert request["buyNowOnly"] == "true"
    assert request["includeTopAds"] == "false"


def test_search_params_default_omits_new_filters():
    request = _search_params(SearchParams(query="x"), None, None)
    assert request["adType"] == "OFFERED"
    for key in (
        "posterType",
        "pictureRequired",
        "shippable",
        "buyNowOnly",
        "includeTopAds",
    ):
        assert key not in request


def test_search_params_include_category_id():
    request = _search_params(SearchParams(query="x"), "1234", "217")
    assert request["categoryId"] == "217"
    assert request["locationId"] == "1234"


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


def _run(awaitable):
    pytest_socket.enable_socket()
    try:
        return asyncio.run(awaitable)
    finally:
        pytest_socket.disable_socket()


@pytest.fixture
def api_session():
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path.endswith("/0.json"):
            return httpx.Response(404)
        return httpx.Response(200, json={AD_NS: {"value": _ad()}})

    session = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30)
    yield session, requests
    _run(session.aclose())


def test_get_listing_extracts_id_from_url(api_session):
    session, requests = api_session
    ka = Kleinanzeigen(session=session)

    detail = _run(
        ka.get_listing(
            "https://www.kleinanzeigen.de/s-anzeige/shimano/3569727847-230-8729?source=test"
        )
    )

    assert detail is not None
    assert detail.ad_id == "3569727847"
    assert requests == ["https://api.kleinanzeigen.de/api/ads/3569727847.json"]


def test_get_listing_returns_none_for_missing_ad(api_session):
    session, _ = api_session
    ka = Kleinanzeigen(session=session)
    assert _run(ka.get_listing("0")) is None


@pytest.fixture
def categories_session():
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path.endswith("/api/categories.json"):
            tree = {
                "category": [
                    {
                        "id": "210",
                        "localized-name": _val("Auto, Rad & Boot"),
                        "category": [
                            {
                                "id": "217",
                                "localized-name": _val("Fahrräder & Zubehör"),
                            },
                            {
                                "id": "216",
                                "localized-name": _val("Autos"),
                            },
                        ],
                    }
                ]
            }
            return httpx.Response(
                200,
                json={
                    "{http://www.ebayclassifiedsgroup.com/schema/category/v1}categories": {
                        "value": tree
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                ADS_NS: {
                    "value": {
                        "paging": {"numFound": _val(1)},
                        "ad": [_ad()],
                    }
                }
            },
        )

    session = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=30)
    yield session, requests
    _run(session.aclose())


@pytest.fixture
def clean_category_cache(monkeypatch):
    monkeypatch.setattr(mobile, "_CATEGORY_CACHE", None)
    yield


def test_resolve_category_id_numeric_passthrough(
    categories_session, clean_category_cache
):
    session, requests = categories_session
    assert _run(resolve_category_id(session, "217", xapp="x", max_retries=0)) == "217"
    assert requests == []


def test_resolve_category_id_by_name(categories_session, clean_category_cache):
    session, requests = categories_session
    assert (
        _run(resolve_category_id(session, "fahrrad", xapp="x", max_retries=0)) == "217"
    )
    assert any("/api/categories.json" in r for r in requests)
    # second call served from cache
    assert _run(resolve_category_id(session, "autos", xapp="x", max_retries=0)) == "216"
    assert len([r for r in requests if "categories.json" in r]) == 1


def test_resolve_category_id_unknown_returns_none(
    categories_session, clean_category_cache
):
    session, _ = categories_session
    assert (
        _run(resolve_category_id(session, "fliegende Autos", xapp="x", max_retries=0))
        is None
    )


def test_iter_search_sends_category_id(categories_session, clean_category_cache):
    session, requests = categories_session

    async def drain():
        out = []
        async for progress, listings in iter_search(
            session,
            SearchParams(query="x", category="217"),
            page_delay=0,
            max_retries=0,
        ):
            out.append((progress, listings))
        return out

    pages = _run(drain())
    assert len(pages) == 1
    ads_req = next(r for r in requests if "/api/ads.json" in r)
    assert "categoryId=217" in ads_req


def test_list_categories_filters_by_query(categories_session, clean_category_cache):
    session, _ = categories_session
    paths = [
        c.path for c in _run(mobile.list_categories(session, "fahrr", max_retries=0))
    ]
    assert paths == ["Auto, Rad & Boot > Fahrräder & Zubehör"]


def test_list_categories_returns_full_tree_for_empty_query(
    categories_session, clean_category_cache
):
    session, _ = categories_session
    ids = [c.id for c in _run(mobile.list_categories(session, None, max_retries=0))]
    assert ids == ["210", "217", "216"]


def test_listing_from_ad_flags_images_and_top_ad():
    ad = _ad(
        pictures={
            "picture": [{"link": [{"rel": "large", "href": "https://img/x.jpg"}]}]
        },
        **{"features-active": {"feature-active": [{"name": _val("TOPAD")}]}},
    )
    listing = _listing_from_ad(ad)
    assert listing.has_images is True
    assert listing.is_top_ad is True


def test_iter_search_require_exclude_terms(categories_session, clean_category_cache):
    session, _ = categories_session

    async def drain(params):
        out = []
        async for _progress, listings in iter_search(
            session, params, page_delay=0, max_retries=0
        ):
            out.extend(listings)
        return out

    # The fixture ad's title contains "Shimano" and its description "Privatverkauf".
    assert _run(drain(SearchParams(query="x", require=["shimano"]))) != []
    assert (
        _run(drain(SearchParams(query="x", require=["fahrrad", "privatverkauf"]))) != []
    )
    assert _run(drain(SearchParams(query="x", require=["velo"]))) == []
    assert _run(drain(SearchParams(query="x", exclude=["shimano"]))) == []
    assert _run(drain(SearchParams(query="x", exclude=["privat"]))) == []


def test_iter_search_exclude_title_only(categories_session, clean_category_cache):
    session, _ = categories_session

    async def drain(params):
        out = []
        async for _progress, listings in iter_search(
            session, params, page_delay=0, max_retries=0
        ):
            out.extend(listings)
        return out

    # "Privatverkauf" appears only in the description, so title-only exclusion keeps it.
    assert (
        _run(
            drain(SearchParams(query="x", exclude=["privat"], exclude_title_only=True))
        )
        != []
    )
    # but "Shimano" is in the title, so it is dropped.
    assert (
        _run(
            drain(SearchParams(query="x", exclude=["shimano"], exclude_title_only=True))
        )
        == []
    )
