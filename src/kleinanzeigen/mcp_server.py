"""MCP server exposing kleinanzeigen.de search over stdio.

Adapter boundary: tools take protocol-level arguments (strings, ints),
build core request models, and return typed response models so the SDK
publishes concrete output schemas.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from mcp.server import MCPServer
from pydantic import Field, PositiveInt

from kleinanzeigen import Kleinanzeigen
from kleinanzeigen._version import package_version
from kleinanzeigen.format import ErrorResponse, SearchResponse, search_response
from kleinanzeigen.models import ListingDetail, SearchParams, SortField

mcp = MCPServer(f"kleinanzeigen {package_version()}")


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
    sort: Literal["newest", "price_asc", "price_desc", "distance"] | None = None,
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
        sort=SortField(sort) if sort else None,
    )
    async with Kleinanzeigen() as ka:
        result = await ka.search(params, max_results=max_results)
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
