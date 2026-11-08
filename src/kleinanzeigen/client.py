"""Async client for kleinanzeigen.de over plain HTTP — no browser required.

Kleinanzeigen listing pages are server-rendered, so curl_cffi (with Chrome
TLS impersonation) + BeautifulSoup covers search and detail extraction.
Pages are fetched sequentially with a delay: Kleinanzeigen rate-limits
concurrent requests from one IP. The session persists cookies across calls
to avoid repeated consent/bot walls.
"""

from __future__ import annotations

import asyncio
import itertools
import random
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Self

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException

from kleinanzeigen import parsing
from kleinanzeigen.models import Listing, ListingDetail, SearchParams, SearchResult


@dataclass(frozen=True)
class PageProgress:
    """One fetched search page: page number plus breadcrumb totals when known."""

    page: int
    total_results: int | None
    total_pages: int | None


AD_URL_PREFIX = f"{parsing.BASE_URL}/s-anzeige/"


class KleinanzeigenError(Exception):
    """Raised when a request fails after all retries."""


class Kleinanzeigen:
    """Query kleinanzeigen.de. Use as an async context manager or call aclose()."""

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        page_delay: float = 1.0,
        max_retries: int = 2,
        session: AsyncSession | None = None,
    ):
        self._owns_session = session is None
        self._session = session or AsyncSession(
            impersonate="chrome",
            timeout=timeout,
            headers={"Accept-Language": "de-DE,de;q=0.9"},
        )
        self._page_delay = page_delay
        self._max_retries = max_retries

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_session:
            await self._session.close()

    async def _fetch(self, url: str) -> tuple[str, BeautifulSoup, str]:
        """GET url -> (raw_html, soup, final_url). Retries on HTTP errors."""
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._session.get(url, timeout=self._session.timeout)
                resp.raise_for_status()
                return (
                    resp.text,
                    BeautifulSoup(resp.text, "html.parser"),
                    str(resp.url),
                )
            except RequestException as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(min(2**attempt + random.random() * 0.5, 5.0))
        raise KleinanzeigenError(f"failed to fetch {url}: {last_exc}") from last_exc

    async def _fetch_search_page(
        self, url: str, *, want_breadcrumb: bool
    ) -> tuple[list[Listing], tuple[int | None, int | None]]:
        for attempt in range(3):
            html, soup, _ = await self._fetch(url)
            listings = []
            previews = parsing.parse_ad_previews(html)
            for card in soup.select("article[data-adid]"):
                listing = parsing.extract_listing(card, previews)
                if listing is not None:
                    listings.append(listing)
            if listings or attempt == 2:
                break
            await asyncio.sleep(3.0)
        breadcrumb = parsing.parse_breadcrumb(soup) if want_breadcrumb else (None, None)
        return listings, breadcrumb

    async def iter_search_pages(
        self,
        url_for: Callable[[int], str],
        *,
        first_page: int = 1,
        pages: int = 1,
        page_delay: float | None = None,
    ) -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
        """Yield ``(PageProgress, listings)`` per fetched page.

        ``url_for(p)`` builds the URL for page ``p``. ``pages`` counts pages
        starting at ``first_page``; 0 = all available. Stops on an empty page
        or once ``total_pages`` (from the first page's breadcrumb) is passed.
        ``page_delay`` overrides the inter-page delay. Callers wanting
        ``published_after`` filtering should stop iterating early.
        """
        delay = self._page_delay if page_delay is None else page_delay
        total_pages: int | None = None
        breadcrumb_page = first_page

        page_range = (
            range(first_page, first_page + pages)
            if pages > 0
            else itertools.count(first_page)
        )
        for p in page_range:
            if total_pages is not None and p > total_pages:
                break
            if p > first_page:
                await asyncio.sleep(delay)

            page_listings, (total, tp) = await self._fetch_search_page(
                url_for(p), want_breadcrumb=(p == breadcrumb_page)
            )
            if p == breadcrumb_page:
                total_pages = tp
            yield PageProgress(p, total, total_pages), page_listings
            if not page_listings:
                break  # successfully loaded but empty: past the last page

    def iter_search(
        self, params: SearchParams
    ) -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
        """Page iterator for a keyword ``SearchParams`` (CLI progress path)."""
        return self.iter_search_pages(
            lambda p: parsing.build_search_url(
                query=params.query,
                location=params.location,
                radius=params.radius,
                min_price=params.min_price,
                max_price=params.max_price,
                page=p,
            ),
            first_page=params.page,
            pages=params.pages,
        )

    async def search(self, params: SearchParams) -> SearchResult:
        """Keyword search. ``pages`` counts pages starting at ``page``; 0 = all."""
        return await self.collect_search_pages(
            self.iter_search(params), published_after=params.published_after
        )

    def iter_search_url(
        self, url: str, *, pages: int = 1
    ) -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
        """Page iterator for a saved/filtered search URL.

        Enforces a >= 2s inter-page delay; saved searches hit a different path
        shape that Kleinanzeigen rate-limits harder.
        """
        return self.iter_search_pages(
            lambda p: parsing.inject_page(url, p),
            first_page=1,
            pages=pages,
            page_delay=max(self._page_delay, 2.0),
        )

    async def search_url(
        self,
        url: str,
        *,
        pages: int = 1,
        published_after: datetime | None = None,
    ) -> SearchResult:
        """Scrape a saved/filtered search URL (any kleinanzeigen.de search link).

        Pages are injected via 'seite:N'/'s-seite:N' path segments.
        ``pages`` = 0 fetches all available pages.
        """
        return await self.collect_search_pages(
            self.iter_search_url(url, pages=pages),
            published_after=published_after,
        )

    @staticmethod
    async def collect_search_pages(
        pages_iter: AsyncIterator[tuple[PageProgress, list[Listing]]],
        *,
        published_after: datetime | None = None,
    ) -> SearchResult:
        listings: list[Listing] = []
        total_results = total_pages = None
        pages_fetched = 0

        async for progress, page_listings in pages_iter:
            pages_fetched += 1
            if pages_fetched == 1:
                total_results, total_pages = (
                    progress.total_results,
                    progress.total_pages,
                )

            if published_after is not None:
                page_listings, stop = parsing.apply_published_after(
                    page_listings, published_after
                )
            else:
                stop = False
            listings.extend(page_listings)
            if stop:
                break

        listings = parsing.dedupe_by_ad_id(listings)
        return SearchResult(
            listings=listings,
            total_results=total_results,
            total_pages=total_pages,
            pages_fetched=pages_fetched,
        )

    async def get_listing(self, url_or_id: str) -> ListingDetail | None:
        """Fetch one ad by URL or bare ad id. None when the ad is gone."""
        url = url_or_id if "://" in url_or_id else f"{AD_URL_PREFIX}{url_or_id}"
        _, soup, final_url = await self._fetch(url)

        # Redirect away from the ad URL or the expired-ad marker: ad is gone.
        if not final_url.startswith(AD_URL_PREFIX) or soup.select_one(
            "#srchrslt-adexpired"
        ):
            return None

        return parsing.extract_detail(soup, url=final_url, scraped_at=datetime.now(UTC))
