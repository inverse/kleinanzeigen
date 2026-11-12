"""Mobile JSON API transport (api.kleinanzeigen.de) for sorted searches.

The website's search URLs cannot express a sort order: the sort dropdown
submits ``sortingField`` to the legacy ``/s-suchanfrage.html`` endpoint,
which 301s to a canonical ``/s-…`` path that drops it. The Android app's
REST API does support ``sortType`` server-side, so sorted ``SearchParams``
are served from there instead of the HTML pages. Responses are mapped onto
the same ``Listing`` models the web parser produces.

Auth is the public Basic credential shipped inside the Android app
(overridable via env), plus per-request app headers — no account needed.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import os
import random
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any
from zoneinfo import ZoneInfo

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from kleinanzeigen.client import KleinanzeigenError, PageProgress
from kleinanzeigen.models import Listing, SearchParams, SortField

API_HOST = "https://api.kleinanzeigen.de"
APP_VERSION = "2026.25.0"
DEFAULT_BASIC_USER = "android"
DEFAULT_BASIC_PW = "TaR60pEttY"

ADS_NS = "{http://www.ebayclassifiedsgroup.com/schema/ad/v1}ads"
LOCATIONS_NS = "{http://www.ebayclassifiedsgroup.com/schema/location/v1}locations"
PAGE_SIZE = 25
UPSTREAM_TZ = ZoneInfo("Europe/Berlin")

_SORT_TYPES = {
    SortField.NEWEST: "DATE_DESCENDING",
    SortField.PRICE_ASC: "PRICE_ASCENDING",
    SortField.PRICE_DESC: "PRICE_DESCENDING",
    SortField.DISTANCE: "DISTANCE_ASCENDING",
}

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def _basic_auth() -> str:
    user = os.getenv("KLEINANZEIGEN_BASIC_USER", DEFAULT_BASIC_USER)
    pw = os.getenv("KLEINANZEIGEN_BASIC_PW", DEFAULT_BASIC_PW)
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


def _headers(xapp: str) -> dict[str, str]:
    return {
        "Authorization": _basic_auth(),
        "X-EBAYK-APP": xapp,
        "X-ECG-USER-AGENT": f"ebayk-android-app-{APP_VERSION}",
        "X-ECG-USER-VERSION": APP_VERSION,
        "User-Agent": f"Kleinanzeigen/{APP_VERSION} (Android 13; Pixel 7)",
        "Accept": "application/json",
        "Accept-Language": "de-DE",
    }


async def _get_json(
    session: AsyncSession,
    url: str,
    params: dict[str, Any],
    *,
    xapp: str,
    max_retries: int,
) -> Any:
    """GET -> parsed JSON. Retries on transport errors and 429/5xx."""
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = await session.get(
                url, params=params, headers=_headers(xapp), timeout=session.timeout
            )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise RequestException(f"HTTP {resp.status_code} from {url}")
            resp.raise_for_status()  # type: ignore[no-untyped-call]
            return resp.json()
        except RequestException as exc:
            last_exc = exc
            if attempt < max_retries:
                await asyncio.sleep(min(2**attempt + random.random() * 0.5, 5.0))
    raise KleinanzeigenError(f"mobile API request failed: {last_exc}") from last_exc


def _val(node: Any) -> Any:
    """Ecg schema nodes wrap scalars as {'value': x}; unwrap one level."""
    if isinstance(node, dict) and set(node) == {"value"}:
        return node["value"]
    return node


def _as_list(node: Any) -> list[Any]:
    if node is None:
        return []
    if isinstance(node, list):
        return node
    return [node]


def _flatten_locations(nodes: Any, out: list[tuple[str, str]]) -> None:
    """Nested location tree -> flat (id, label) pairs, parents before children."""
    for node in _as_list(nodes):
        if not isinstance(node, dict):
            continue
        lid = node.get("id")
        label = _val(node.get("localized-name")) or _val(node.get("id-name"))
        if lid is not None and label:
            out.append((str(lid), str(label)))
        _flatten_locations(node.get("location"), out)


def _best_location(candidates: list[tuple[str, str]], query: str) -> str | None:
    q = query.strip().lower()
    if not candidates:
        return None
    # Exact head match beats substring matches ("Berlin" over "Charlottenburg (Berlin)").
    for lid, label in candidates:
        head = label.split(" - ")[0].split(" (")[0].strip().lower()
        if head == q:
            return lid
    for lid, label in candidates:
        head = label.split(" - ")[0].split(" (")[0].strip().lower()
        if head.startswith(q):
            return lid
    return candidates[0][0]


async def resolve_location_id(
    session: AsyncSession, query: str, *, xapp: str, max_retries: int
) -> str | None:
    """Place name/PLZ -> mobile API location id, or None when unresolvable."""
    if query.strip().isdigit():
        return query.strip()
    data = await _get_json(
        session,
        f"{API_HOST}/api/locations.json",
        {"q": query},
        xapp=xapp,
        max_retries=max_retries,
    )
    block = data.get(LOCATIONS_NS, {})
    root = block.get("value", {}) if isinstance(block, dict) else {}
    nodes = root.get("location") if isinstance(root, dict) else None
    candidates: list[tuple[str, str]] = []
    _flatten_locations(nodes, candidates)
    return _best_location(candidates, query)


def _parse_amount(node: Any) -> Decimal | None:
    value = _val(node)
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_published_at(node: Any) -> datetime | None:
    """'2026-11-12T23:16:50.000+0100' -> naive Europe/Berlin, like web dates."""
    raw = _val(node)
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UPSTREAM_TZ).replace(tzinfo=None)


def _listing_location(ad: dict[str, Any]) -> str:
    """'PLZ City' like the web cards, from locations or ad-address."""
    locations = ad.get("locations") or {}
    for loc in _as_list(locations.get("location")):
        if isinstance(loc, dict):
            label = _val(loc.get("localized-name"))
            if label:
                return str(label)
    addr = ad.get("ad-address") or {}
    zip_code = _val(addr.get("zip-code")) or ""
    city = _val(addr.get("state")) or ""
    return " ".join(part for part in (str(zip_code), str(city)) if part).strip()


def _listing_from_ad(ad: dict[str, Any]) -> Listing | None:
    ad_id = str(ad.get("id") or "")
    links = {
        ln.get("rel"): ln.get("href", "")
        for ln in _as_list(ad.get("link"))
        if isinstance(ln, dict)
    }
    if not ad_id:
        self_href = links.get("self", "")
        ad_id = self_href.rstrip("/").rsplit("/", 1)[-1]
    if not ad_id:
        return None

    price = ad.get("price") or {}
    # FREE/RANGE price-types carry no single amount; web cards show none either.
    price_type = _val(price.get("price-type"))
    amount = (
        None if price_type in ("FREE", "RANGE") else _parse_amount(price.get("amount"))
    )

    distance = None
    sd = ad.get("search-distance") or {}
    dist_val = _val((sd.get("distance") or {}).get("value"))
    if dist_val is not None:
        try:
            distance = float(dist_val)
        except TypeError, ValueError:
            distance = None

    # Mobile descriptions are HTML fragments; flatten tags, keep line breaks.
    raw_desc = _val(ad.get("description")) or ""
    description = unescape(_BR_RE.sub("\n", raw_desc))
    description = unescape(_TAG_RE.sub("", description))

    return Listing(
        ad_id=ad_id,
        url=links.get("self-public-website") or links.get("self") or "",
        title=unescape(str(_val(ad.get("title")) or "")).strip(),
        price=amount,
        location=_listing_location(ad),
        distance_km=distance,
        description=" ".join(description.split()),
        published_at=_parse_published_at(ad.get("start-date-time")),
        is_top_ad=False,
    )


def _search_params(params: SearchParams, location_id: str | None) -> dict[str, Any]:
    sort = params.sort
    if sort is None:
        raise ValueError("mobile.iter_search requires params.sort")
    p: dict[str, Any] = {
        "page": params.page - 1,  # web pages are 1-based, API is 0-based
        "size": PAGE_SIZE,
        "sortType": _SORT_TYPES[sort],
    }
    if params.query:
        p["q"] = params.query
    if location_id:
        p["locationId"] = location_id
    if params.radius:
        p["distance"] = params.radius
    if params.min_price is not None:
        p["minPrice"] = params.min_price
    if params.max_price is not None:
        p["maxPrice"] = params.max_price
    return p


async def iter_search(
    session: AsyncSession,
    params: SearchParams,
    *,
    page_delay: float,
    max_retries: int,
) -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
    """Sorted keyword search via the mobile API. Same yield shape as the web path."""
    xapp = f"{uuid.uuid4()}{int(datetime.now(UTC).timestamp() * 1000)}"

    location_id = None
    if params.location:
        location_id = await resolve_location_id(
            session, params.location, xapp=xapp, max_retries=max_retries
        )
        if location_id is None:
            raise KleinanzeigenError(
                f"could not resolve location {params.location!r} via mobile API"
            )

    total_pages: int | None = None
    first_api_page = params.page - 1
    base_params = _search_params(params, location_id)
    page_range = (
        range(first_api_page, first_api_page + params.pages)
        if params.pages > 0
        else itertools.count(first_api_page)
    )
    for offset, api_page in enumerate(page_range):
        if total_pages is not None and api_page >= first_api_page + total_pages:
            break
        if offset > 0:
            await asyncio.sleep(page_delay + random.random() * 0.4)

        data = await _get_json(
            session,
            f"{API_HOST}/api/ads.json",
            {**base_params, "page": api_page},
            xapp=xapp,
            max_retries=max_retries,
        )
        block = data.get(ADS_NS, {})
        value = block.get("value", {}) if isinstance(block, dict) else {}
        if not isinstance(value, dict):
            value = {}
        paging = value.get("paging", {})
        total_results = _val(paging.get("numFound"))
        if isinstance(total_results, str):
            try:
                total_results = int(total_results)
            except ValueError:
                total_results = None
        if total_results is not None and total_pages is None:
            total_pages = -(-int(total_results) // PAGE_SIZE)

        listings = [
            listing
            for ad in _as_list(value.get("ad"))
            if isinstance(ad, dict) and (listing := _listing_from_ad(ad)) is not None
        ]
        yield PageProgress(api_page + 1, total_results, total_pages), listings
        if not listings:
            break
