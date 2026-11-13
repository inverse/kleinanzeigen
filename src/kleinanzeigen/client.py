"""Async client for kleinanzeigen.de's mobile JSON API.

Pages are fetched sequentially with a delay to avoid rate limits. One session
is shared by search, location resolution, and detail requests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Self
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from kleinanzeigen import mobile
from kleinanzeigen.mobile import KleinanzeigenError, PageProgress
from kleinanzeigen.models import Listing, ListingDetail, SearchParams, SearchResult

__all__ = ["Kleinanzeigen", "KleinanzeigenError", "PageProgress"]


def _apply_published_after(
    listings: list[Listing], published_after: datetime
) -> tuple[list[Listing], bool]:
    """Drop listings older than the cutoff; True = an old listing was seen.

    Naive datetimes use Europe/Berlin, matching the mobile API's local times.
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


class Kleinanzeigen:
    """Query kleinanzeigen.de. Use as an async context manager or call aclose()."""

    def __init__(
        self,
        *,
        timeout: float = 60.0,
        page_delay: float = 1.0,
        max_retries: int = 2,
        session: httpx.AsyncClient | None = None,
    ):
        self._owns_session = session is None
        self._session = session or httpx.AsyncClient(
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
            await self._session.aclose()

    def iter_search(
        self, params: SearchParams
    ) -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
        """Yield ``(PageProgress, listings)`` for each mobile API page."""
        return mobile.iter_search(
            self._session,
            params,
            page_delay=self._page_delay,
            max_retries=self._max_retries,
        )

    async def search(
        self, params: SearchParams, *, max_results: int | None = None
    ) -> SearchResult:
        """Keyword search. ``pages`` counts pages starting at ``page``; 0 = all.

        ``max_results`` stops paging once that many unique listings are
        collected (deduped); None/0 = no cap.
        """
        return await self.collect_search_pages(
            self.iter_search(params),
            published_after=params.published_after,
            max_results=max_results,
        )

    @staticmethod
    async def collect_search_pages(
        pages_iter: AsyncIterator[tuple[PageProgress, list[Listing]]],
        *,
        published_after: datetime | None = None,
        max_results: int | None = None,
    ) -> SearchResult:
        """Drain a page iterator into a SearchResult.

        ``max_results`` stops iterating once that many unique listings are
        collected (dedup applied as pages arrive); None or <= 0 = no cap.
        """
        listings: list[Listing] = []
        seen: set[str] = set()
        total_results = total_pages = None
        pages_fetched = 0
        limit = max_results if max_results is not None and max_results > 0 else None

        async for progress, page_listings in pages_iter:
            pages_fetched += 1
            if pages_fetched == 1:
                total_results, total_pages = (
                    progress.total_results,
                    progress.total_pages,
                )

            if published_after is not None:
                page_listings, stop = _apply_published_after(
                    page_listings, published_after
                )
            else:
                stop = False
            for listing in page_listings:
                if listing.ad_id not in seen:
                    seen.add(listing.ad_id)
                    listings.append(listing)
            if stop or (limit is not None and len(listings) >= limit):
                break

        if limit is not None:
            listings = listings[:limit]
        return SearchResult(
            listings=listings,
            total_results=total_results,
            total_pages=total_pages,
            pages_fetched=pages_fetched,
        )

    async def get_listing(self, url_or_id: str) -> ListingDetail | None:
        """Fetch one ad by URL or bare ad id. None when the ad is gone."""
        path = urlparse(url_or_id).path
        ad_id = path.rstrip("/").rsplit("/", 1)[-1].split("-", 1)[0]
        return await mobile.get_listing(
            self._session, ad_id, max_retries=self._max_retries
        )
