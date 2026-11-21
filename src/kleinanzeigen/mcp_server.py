"""MCP server exposing kleinanzeigen.de search over stdio.

Adapter boundary: tools take protocol-level arguments (strings, ints),
build core request models, and return typed response models so the SDK
publishes concrete output schemas.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, PositiveInt

from kleinanzeigen import Kleinanzeigen
from kleinanzeigen._version import package_version
from kleinanzeigen.format import (
    ErrorResponse,
    SearchResponse,
    search_response,
)
from kleinanzeigen.mobile import PageProgress
from kleinanzeigen.models import (
    AdType,
    Category,
    Listing,
    ListingDetail,
    PosterType,
    SearchParams,
    SortField,
)

mcp = FastMCP(f"kleinanzeigen {package_version()}")

READ_ONLY = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


async def _report_pages(
    ctx: Context,
    pages: AsyncIterator[tuple[PageProgress, list[Listing]]],
    params: SearchParams,
) -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
    """Report one progress step per fetched page; total is pages-to-fetch when known."""
    done = 0
    async for progress, listings in pages:
        done += 1
        total = None
        if progress.total_pages is not None:
            remaining = progress.total_pages - params.page + 1
            total = min(params.pages, remaining) if params.pages > 0 else remaining
        await ctx.report_progress(done, total, f"page {progress.page}")
        yield progress, listings


@mcp.tool(annotations=READ_ONLY)
async def search(
    ctx: Context,
    query: str,
    category: str | None = None,
    location: str | None = None,
    radius: Annotated[int | None, Field(ge=0)] = None,
    min_price: Annotated[int | None, Field(ge=0)] = None,
    max_price: Annotated[int | None, Field(ge=0)] = None,
    page: Annotated[int, Field(ge=1)] = 1,
    pages: Annotated[int | None, Field(ge=0)] = None,
    published_after: str | None = None,
    max_results: PositiveInt | None = None,
    sort: SortField | None = None,
    limit: PositiveInt | None = None,
    poster_type: PosterType | None = None,
    ad_type: AdType = AdType.OFFERED,
    picture_required: bool = False,
    shippable: bool = False,
    buy_now_only: bool = False,
    include_top_ads: bool = True,
    require: list[str] | None = None,
    exclude: list[str] | None = None,
    exclude_title_only: bool = False,
) -> SearchResponse:
    """Search kleinanzeigen.de for listings matching a keyword query.

    Args:
        query: Search keyword (e.g. "fahrrad", "iphone 13").
        category: Category id or German name (e.g. "217" or
            "Fahrräder & Zubehör"); parent categories include children.
        location: Location string (e.g. "Berlin" or "Mitte").
        radius: Search radius in km around the location.
        min_price: Minimum price in EUR.
        max_price: Maximum price in EUR.
        page: First page to fetch (1-based).
        pages: Number of pages to fetch, starting at `page`. Default: 1;
            0 = all remaining pages. E.g. page=3, pages=2 fetches pages
            3-4; to page through results call again with an incremented
            page (bounded by total_pages in the response). Setting
            max_results without pages fetches all pages until max_results
            listings are collected.
        published_after: ISO date/datetime; listings older than this are dropped.
        max_results: Stop fetching once this many unique listings are
            collected. With pages unset this also enables paging past page 1.
        sort: Server-side result ordering.
        limit: Cap the number of returned listings.
        poster_type: Filter by seller type ("private" or "commercial").
        ad_type: "offered" (for sale, default) or "wanted" (sought).
        picture_required: Only ads with photos.
        shippable: Only ads offering shipping.
        buy_now_only: Only ads with Buy Now.
        include_top_ads: Include highlighted top ads (default true; currently
            a no-op upstream — the mobile API returns none on page 1).
        require: Terms that must appear in the title or description.
        exclude: Terms that must not appear in title/description.
        exclude_title_only: Apply exclude to the title only.
    """
    params = SearchParams(
        query=query,
        category=category,
        location=location,
        radius=radius,
        min_price=min_price,
        max_price=max_price,
        page=page,
        pages=pages if pages is not None else (0 if max_results is not None else 1),
        published_after=(
            datetime.fromisoformat(published_after) if published_after else None
        ),
        sort=sort,
        poster_type=poster_type,
        ad_type=ad_type,
        picture_required=picture_required,
        shippable=shippable,
        buy_now_only=buy_now_only,
        include_top_ads=include_top_ads,
        require=require,
        exclude=exclude,
        exclude_title_only=exclude_title_only,
    )
    async with Kleinanzeigen() as ka:
        result = await ka.collect_search_pages(
            _report_pages(ctx, ka.iter_search(params), params),
            published_after=params.published_after,
            max_results=max_results,
        )
    return search_response(result, limit=limit)


@mcp.tool(annotations=READ_ONLY)
async def list_categories(query: str | None = None) -> list[Category]:
    """Find category IDs, names, and paths; empty query lists the full tree."""
    async with Kleinanzeigen() as ka:
        return await ka.list_categories(query)


@mcp.tool(annotations=READ_ONLY)
async def get_listing(url_or_id: str) -> ListingDetail | ErrorResponse:
    """Fetch a single listing by URL or bare ad id.

    Args:
        url_or_id: Full kleinanzeigen.de ad URL or the numeric ad id.
    """
    async with Kleinanzeigen() as ka:
        detail = await ka.get_listing(url_or_id)
    if detail is None:
        return ErrorResponse(error="listing not found or removed")
    return detail


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
