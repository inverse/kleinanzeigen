"""Pure HTML -> model parsing. No I/O; everything takes bs4 objects or raw HTML."""

from __future__ import annotations

import html as html_lib
import json
import math
import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Literal
from urllib.parse import unquote, urlencode, urljoin, urlparse, urlunparse
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from kleinanzeigen.models import (
    AdStatus,
    Listing,
    ListingDetail,
    Location,
    Price,
    Seller,
)

BASE_URL = "https://www.kleinanzeigen.de"

_DATE_RE = re.compile(r"^((Heute|Gestern),\s*\d{1,2}:\d{2}|\d{2}\.\d{2}\.\d{4})$")
_ZIP_RE = re.compile(r"\b\d{5}\b")
_KM_ONLY_RE = re.compile(r"^\(\d+(?:[.,]\d+)?\s*km\)$")
_DISTANCE_RE = re.compile(r"\s*\((\d+(?:[.,]\d+)?)\s*km\)\s*$")
_PAGE_SEGMENT_RE = re.compile(r"^(s-seite|seite):(\d+)$")
_PAGE_LINK_RE = re.compile(r"(?<=/)((?:s-seite|seite):)(\d+)")
_ASTRO_PROPS_RE = re.compile(r"""<astro-island[^>]*props='([^']*sortingDate[^']*)'""")
_AD_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")


def _inner(tag: Tag | None) -> str:
    """Playwright inner_text equivalent for a bs4 Tag."""
    return tag.get_text("\n", strip=True) if tag is not None else ""


def _content(tag: Tag | None) -> str:
    """Playwright text_content equivalent."""
    return tag.get_text() if tag is not None else ""


# ---------------------------------------------------------------------------
# Prices and dates
# ---------------------------------------------------------------------------


def _parse_amount(text: str) -> Decimal | None:
    """'1.234 € VB' -> Decimal(1234); None when there is no amount."""
    cleaned = text.replace("€", "").replace("VB", "").replace(".", "").strip()
    cleaned = cleaned.replace(",", ".")
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        return None


def parse_price(text: str | None) -> Price:
    """Price block text -> Price; amount=None when no numeric price is shown."""
    if not text:
        return Price(amount=None)
    return Price(amount=_parse_amount(text), negotiable="VB" in text)


def parse_listing_date(text: str | None) -> datetime | None:
    """'Heute, 22:06' / 'Gestern, 19:30' / '26.04.2026' -> datetime."""
    if not text:
        return None
    text = text.strip()
    try:
        today = date.today()
        if text.startswith("Heute,"):
            h, m = map(int, text.split(",", 1)[1].strip().split(":"))
            return datetime(today.year, today.month, today.day, h, m)
        if text.startswith("Gestern,"):
            yesterday = today - timedelta(days=1)
            h, m = map(int, text.split(",", 1)[1].strip().split(":"))
            return datetime(yesterday.year, yesterday.month, yesterday.day, h, m)
        d, mo, y = text.split(".")
        return datetime(int(y), int(mo), int(d))
    except ValueError, AttributeError:
        return None


def parse_ad_date(text: str | None) -> date | None:
    """'01.01.2024' -> date; None when the format is unrecognized."""
    if not text:
        return None
    m = _AD_DATE_RE.search(text.strip())
    if not m:
        return None
    d, mo, y = m.groups()
    try:
        return date(int(y), int(mo), int(d))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Search page: breadcrumb, astro props, listing cards
# ---------------------------------------------------------------------------


def parse_breadcrumb(soup: BeautifulSoup) -> tuple[int | None, int | None]:
    """(total_results, total_pages) from '#srp-breadcrumb-summary'."""
    node = soup.select_one("#srp-breadcrumb-summary, .breadcrump-summary")
    text = _inner(node)
    match = re.search(r"(\d[\d.]*)\s*-\s*(\d[\d.]*)\s+von\s+([\d.]+)", text)
    if not match:
        return None, None
    page_start = int(match.group(1).replace(".", ""))
    page_end = int(match.group(2).replace(".", ""))
    total = int(match.group(3).replace(".", ""))
    if page_start != 1 or page_end <= 0:
        return total, None
    return total, math.ceil(total / page_end)


def _decode_astro_value(value: Any) -> Any:
    """Astro serializes props as [type, value] pairs (0 = scalar/object, 1 = array)."""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[0], int):
        kind, inner = value
        if kind == 0 and isinstance(inner, dict):
            return {k: _decode_astro_value(v) for k, v in inner.items()}
        if kind == 1 and isinstance(inner, list):
            return [_decode_astro_value(v) for v in inner]
        return inner
    return value


def _collect_ad_nodes(node: Any, previews: dict[str, dict[str, Any]]) -> None:
    if isinstance(node, dict):
        if "id" in node and "sortingDate" in node:
            previews[str(node["id"])] = node
        for v in node.values():
            _collect_ad_nodes(v, previews)
    elif isinstance(node, list):
        for v in node:
            _collect_ad_nodes(v, previews)


def parse_ad_previews(html_text: str) -> dict[str, dict[str, Any]]:
    """adid -> embedded preview props (sortingDate, topAd) from astro-island tags."""
    previews: dict[str, dict[str, Any]] = {}
    for raw in _ASTRO_PROPS_RE.findall(html_text):
        try:
            props = json.loads(html_lib.unescape(raw))
        except TypeError, ValueError:
            continue
        if isinstance(props, dict):
            _collect_ad_nodes(
                {k: _decode_astro_value(v) for k, v in props.items()}, previews
            )
    return previews


def _clean_location_text(text: str) -> str:
    if not text:
        return ""
    value = str(text).replace("\xa0", " ")
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    value = " ".join(lines)
    value = " ".join(value.split())
    for bad in ("Ort", "Standort"):
        if value.lower().startswith(bad.lower()):
            value = value[len(bad) :].strip(" :-|•")
    return value.strip()


def _split_location_distance(text: str) -> tuple[str, float | None]:
    match = _DISTANCE_RE.search(text)
    if not match:
        return text, None
    return (
        text[: match.start()].strip(),
        float(match.group(1).replace(",", ".")),
    )


def extract_ad_date(article: Tag) -> str:
    """Legacy date block first, then any <span> matching a KA date format."""
    legacy = article.select_one(".aditem-main--top--right")
    if legacy is not None:
        text = _inner(legacy)
        if text:
            return text
    for span in article.find_all("span"):
        text = _content(span).strip()
        if _DATE_RE.match(text):
            return text
    return ""


def extract_ad_location(article: Tag) -> str:
    for selector in (
        ".aditem-main--top--left",
        ".aditem-main--top--left--location",
        "[class*='aditem-main--top--left']",
        "[class*='location']",
        "[class*='Location']",
    ):
        node = article.select_one(selector)
        if node is not None:
            text = _inner(node)
            if text:
                return text

    # Fallback: scan text lines for a 5-digit ZIP.
    lines = [line.strip() for line in _inner(article).splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if _ZIP_RE.search(line):
            loc = line
            if i + 1 < len(lines) and _KM_ONLY_RE.match(lines[i + 1]):
                loc += " " + lines[i + 1]
            return loc
    return ""


def extract_jsonld_title(article: Tag) -> str | None:
    script = article.select_one('script[type="application/ld+json"]')
    raw = _content(script)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError, TypeError:
        return None
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict):
        title = data.get("title") or data.get("name")
        return str(title).strip() if title else None
    return None


def extract_listing(
    article: Tag, previews: dict[str, dict[str, Any]] | None = None
) -> Listing | None:
    ad_id = article.get("data-adid")
    href = article.get("data-href")
    if not ad_id or not href:
        return None

    preview = (previews or {}).get(str(ad_id), {})

    title_text = _inner(article.select_one("h2.text-module-begin a.ellipsis"))
    if not title_text.strip():
        title_text = extract_jsonld_title(article) or ""

    price_raw = _inner(
        article.select_one(
            "p.aditem-main--middle--price-shipping--price, [class*='price'], "
            "h3 ~ div > p.font-strong"
        )
    )
    description_text = _inner(
        article.select_one("p.aditem-main--middle--description, h3 + p")
    )
    date_raw = extract_ad_date(article)
    location_raw = extract_ad_location(article)

    published_at = parse_listing_date(date_raw)
    if published_at is None:
        # Top ads show no date; the embedded preview data does.
        sorting_date = preview.get("sortingDate")
        published_at = parse_listing_date(
            sorting_date if isinstance(sorting_date, str) else ""
        )

    location_text, distance_km = _split_location_distance(
        _clean_location_text(location_raw)
    )

    return Listing(
        ad_id=str(ad_id),
        url=f"{BASE_URL}{href}",
        title=title_text.strip(),
        price=_parse_amount(price_raw),
        location=location_text,
        distance_km=distance_km,
        description=description_text.strip(),
        published_at=published_at,
        is_top_ad=preview.get("topAd") is True,
    )


# ---------------------------------------------------------------------------
# Pagination helpers
# ---------------------------------------------------------------------------


def inject_page(url: str, page_num: int) -> str:
    """Set the page number on a URL that already carries a page segment.

    Replaces the first 's-seite:N'/'seite:N' path segment in place and drops
    any others: the site's canonical pagination keeps that segment mid-path
    (e.g. '/s-seite:2/fahrrad/k0'), so removing it yields a non-search URL.
    A URL without a page segment already serves page 1; requesting another
    page raises ValueError — discover page URLs from the page's own
    pagination links instead (see pagination_url_for).
    """
    parsed = urlparse(url)
    segments = [s for s in unquote(parsed.path).strip("/").split("/") if s]
    replaced = False
    kept: list[str] = []
    for segment in segments:
        match = _PAGE_SEGMENT_RE.match(segment)
        if match is None:
            kept.append(segment)
        elif not replaced:
            kept.append(f"{match.group(1)}:{page_num}")
            replaced = True
    if not replaced and page_num != 1:
        raise ValueError(
            "URL has no page segment; it already serves page 1. "
            "Use pagination_url_for() on a fetched page for page 2+."
        )
    return urlunparse(parsed._replace(path="/" + "/".join(kept)))


def pagination_url_for(
    soup: BeautifulSoup, *, base_url: str
) -> Callable[[int], str] | None:
    """Build ``url_for(page)`` from a search page's own pagination links.

    Page URLs cannot be derived from the input URL — the site canonicalizes
    them ('/s-fahrrad/k0' paginates as '/s-seite:2/fahrrad/k0',
    '/s-autos/k0c216' as '/s-autos/seite:2/autos/k0c216'). Returns None when
    the page has no pagination links (single page of results).
    """
    candidates: list[tuple[int, str]] = []
    for anchor in soup.select("a[href]"):
        href = anchor.get("href")
        if not isinstance(href, str) or "seite" not in href:
            continue
        absolute = urljoin(base_url, href)
        match = _PAGE_LINK_RE.search(urlparse(absolute).path)
        if match:
            candidates.append((int(match.group(2)), absolute))
    if not candidates:
        return None
    _, template = min(candidates, key=lambda candidate: candidate[0])

    def url_for(page: int) -> str:
        return _PAGE_LINK_RE.sub(rf"\g<1>{page}", template, count=1)

    return url_for


def build_search_url(
    *,
    query: str | None = None,
    location: str | None = None,
    radius: int | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
    page: int = 1,
) -> str:
    price_path = ""
    if min_price is not None or max_price is not None:
        min_str = str(min_price) if min_price is not None else ""
        max_str = str(max_price) if max_price is not None else ""
        price_path = f"/s-preis:{min_str}:{max_str}"

    params: dict[str, Any] = {}
    if query:
        params["keywords"] = query
    if location:
        params["locationStr"] = location
    if radius:
        params["radius"] = radius
    param_string = f"?{urlencode(params)}" if params else ""
    return f"{BASE_URL}{price_path}/s-seite:{page}{param_string}"


def apply_published_after(
    listings: list[Listing], published_after: datetime
) -> tuple[list[Listing], bool]:
    """Drop listings older than the cutoff; True = an old listing was seen.

    Top ads are pinned above the date-sorted list and always kept: an old
    one neither filters nor stops iteration. Listings without a date are
    kept.

    ``published_at`` values are naive Europe/Berlin local time. A naive
    ``published_after`` is compared in that zone; an aware one is converted
    to it first.
    """
    if published_after.tzinfo is not None:
        published_after = published_after.astimezone(ZoneInfo("Europe/Berlin"))
    else:
        published_after = published_after.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    kept = []
    stop = False
    for listing in listings:
        published = listing.published_at
        if listing.is_top_ad or published is None:
            kept.append(listing)
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=ZoneInfo("Europe/Berlin"))
        if published >= published_after:
            kept.append(listing)
        else:
            stop = True
    return kept, stop


def dedupe_by_ad_id(listings: list[Listing]) -> list[Listing]:
    """Drop repeat listings — top ads can appear on multiple pages."""
    return list({listing.ad_id: listing for listing in listings}.values())


# ---------------------------------------------------------------------------
# Detail page (/s-anzeige/...) extraction
# ---------------------------------------------------------------------------


def _extract_user_id(href: str) -> str | None:
    """Numeric user id from '/s-anzeigen-des-nutzers/123' or '?userId=123'."""
    m = re.search(r"s-anzeigen-des-nutzers/(\d+)", href)
    if m:
        return m.group(1)
    m = re.search(r"[?&]userId=(\d+)", href)
    return m.group(1) if m else None


def extract_seller(soup: BeautifulSoup) -> Seller:
    name = _inner(soup.select_one(".userprofile-vip")) or None

    user_id = None
    for selector in (
        "a.userprofile-vip",
        "a[href*='s-anzeigen-des-nutzers']",
        "a[href*='userId']",
    ):
        el = soup.select_one(selector)
        if el is not None:
            href = el.get("href")
            user_id = _extract_user_id(href) if isinstance(href, str) else None
            if user_id:
                break

    seller_type: Literal["private", "business"] = "private"
    member_since = None
    for node in soup.select(".userprofile-vip-details-text"):
        text = _inner(node).strip()
        if not text:
            continue
        if "Gewerblicher Nutzer" in text:
            seller_type = "business"
        elif "Privater Nutzer" in text:
            seller_type = "private"
        if "Aktiv seit" in text and member_since is None:
            member_since = text.replace("Aktiv seit ", "").strip()

    badges = [
        badge
        for badge in (
            _content(el).strip()
            for el in soup.select(".userprofile-vip-badges .userbadge-tag")
        )
        if badge
    ]

    return Seller(
        name=name,
        user_id=user_id,
        member_since=member_since,
        type=seller_type,
        badges=badges,
    )


def extract_details(soup: BeautifulSoup) -> dict[str, str]:
    details: dict[str, str] = {}
    for item in soup.select("#viewad-details .addetailslist--detail"):
        content = _content(item)
        value_span = item.select_one(".addetailslist--detail--value")
        if value_span is not None:
            value = _content(value_span)
            label = content.replace(value, "").strip()
            details[label] = value.strip()
    return details


def extract_features(soup: BeautifulSoup) -> list[str]:
    return [
        text
        for text in (
            _content(el).strip()
            for el in soup.select("#viewad-configuration .checktaglist .checktag")
        )
        if text
    ]


def extract_location(soup: BeautifulSoup) -> Location:
    text = _inner(soup.select_one("#viewad-locality"))
    if not text:
        return Location()
    parts = text.split(" - ") if " - " in text else [text]
    postal_state = parts[0].strip().split(" ", 1)
    return Location(
        postal_code=postal_state[0].strip(),
        city=parts[1].strip() if len(parts) > 1 else "",
        state=postal_state[1].strip() if len(postal_state) > 1 else "",
    )


def _extract_status(title_raw: str, title_node: Any, soup: BeautifulSoup) -> AdStatus:
    for marker, candidate in (
        ("Verkauft", AdStatus.SOLD),
        ("Reserviert •", AdStatus.RESERVED),
        ("Gelöscht •", AdStatus.DELETED),
    ):
        if marker in title_raw:
            status = candidate
            break
    else:
        status = AdStatus.ACTIVE
    if (title_node is not None and "is-sold" in (title_node.get("class") or [])) or (
        soup.select_one(".badge-sold")
    ):
        status = AdStatus.SOLD
    return status


def extract_detail(
    soup: BeautifulSoup, url: str, scraped_at: datetime | None
) -> ListingDetail:
    ad_id = _inner(soup.select_one("#viewad-ad-id-box > ul > li:nth-child(2)"))

    categories = [
        text
        for text in (_content(el).strip() for el in soup.select(".breadcrump-link"))
        if text
    ]

    title_node = soup.select_one("#viewad-title")
    title_raw = _inner(title_node)
    status = _extract_status(title_raw, title_node, soup)
    title = title_raw.split(" • ")[-1].strip() if title_raw else ""

    price = parse_price(_inner(soup.select_one("#viewad-price")))

    description = _inner(soup.select_one("#viewad-description-text"))
    if description:
        description = re.sub(r"[ \t]+", " ", description).strip()
        description = re.sub(r"\n+", "\n", description)

    seen: set[str] = set()
    images = []
    for img in soup.select(".galleryimage-element img"):
        src = img.get("src") or img.get("data-src") or ""
        if isinstance(src, str) and "prod-ads" in src and src not in seen:
            seen.add(src)
            images.append(src)

    shipping_text = _inner(soup.select_one(".boxedarticle--details--shipping"))
    delivery: Literal["pickup", "shipping"] | None = None
    if shipping_text:
        if "Nur Abholung" in shipping_text:
            delivery = "pickup"
        elif "Versand" in shipping_text:
            delivery = "shipping"

    created_at = parse_ad_date(
        _inner(soup.select_one("#viewad-extra-info > div:nth-child(1) > span"))
    )
    return ListingDetail(
        ad_id=ad_id,
        url=url,
        title=title,
        status=status,
        price=price,
        categories=categories,
        description=description or None,
        location=extract_location(soup),
        delivery=delivery,
        images=images,
        details=extract_details(soup),
        features=extract_features(soup),
        seller=extract_seller(soup),
        created_at=created_at,
        scraped_at=scraped_at,
    )
