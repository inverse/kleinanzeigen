"""MCP server exposing kleinanzeigen.de search over stdio.

Adapter boundary: tools take protocol-level arguments (strings, ints),
build core request models, and return typed response models so FastMCP
publishes concrete output schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import Field, PositiveInt

from kleinanzeigen import Kleinanzeigen
from kleinanzeigen._version import package_version
from kleinanzeigen.format import ErrorResponse, SearchResponse, search_response
from kleinanzeigen.models import ListingDetail, SearchParams

mcp = FastMCP(f"kleinanzeigen {package_version()}")


@mcp.tool()
async def search(
    query: str,
    location: str | None = None,
    radius: Annotated[int | None, Field(ge=0)] = None,
    min_price: Annotated[int | None, Field(ge=0)] = None,
    max_price: Annotated[int | None, Field(ge=0)] = None,
    page: Annotated[int, Field(ge=1)] = 1,
    pages: Annotated[int | None, Field(ge=0)] = None,
    published_after: str | None = None,
    max_results: PositiveInt | None = None,
    limit: PositiveInt | None = None,
) -> SearchResponse:
    """Search kleinanzeigen.de for listings matching a keyword query.

    Args:
        query: Search keyword (e.g. "fahrrad", "iphone 13").
        location: Location string (e.g. "Berlin" or "Mitte").
        radius: Search radius in km around the location.
        min_price: Minimum price in EUR.
        max_price: Maximum price in EUR.
        page: First page to fetch (1-based).
        pages: Pages to fetch; default = 1 page, or all pages (capped by
            max_results) when max_results is set. 0 = all pages.
        published_after: ISO date/datetime; listings older than this are dropped.
        max_results: Stop fetching once this many unique listings are
            collected. With pages unset this also enables paging past page 1.
        limit: Cap the number of returned listings.
    """
    params = SearchParams(
        query=query,
        location=location,
        radius=radius,
        min_price=min_price,
        max_price=max_price,
        page=page,
        pages=(
            0
            if pages is None and max_results is not None
            else (1 if pages is None else pages)
        ),
        published_after=(
            datetime.fromisoformat(published_after) if published_after else None
        ),
    )
    async with Kleinanzeigen() as ka:
        result = await ka.search(params, max_results=max_results)
    return search_response(result, limit=limit)


@mcp.tool()
async def search_url(
    url: str,
    pages: Annotated[int | None, Field(ge=0)] = None,
    published_after: str | None = None,
    max_results: PositiveInt | None = None,
    limit: PositiveInt | None = None,
) -> SearchResponse:
    """Scrape a saved/filtered kleinanzeigen.de search URL.

    Args:
        url: Any kleinanzeigen.de search URL (e.g. a saved search link).
        pages: Pages to fetch; default = 1 page, or all pages (capped by
            max_results) when max_results is set. 0 = all pages.
        published_after: ISO date/datetime; listings older than this are dropped.
        max_results: Stop fetching once this many unique listings are
            collected. With pages unset this also enables paging past page 1.
        limit: Cap the number of returned listings.
    """
    async with Kleinanzeigen() as ka:
        result = await ka.search_url(
            url,
            pages=(
                0
                if pages is None and max_results is not None
                else (1 if pages is None else pages)
            ),
            published_after=(
                datetime.fromisoformat(published_after) if published_after else None
            ),
            max_results=max_results,
        )
    return search_response(result, limit=limit)


@mcp.tool()
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
