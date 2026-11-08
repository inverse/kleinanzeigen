"""Typed JSON response boundary shared by the CLI and MCP server.

Responses embed the core models directly — ``Listing`` stays the single
source of truth for listing fields; this module only shapes the envelope
(upstream totals plus ``returned`` after a response-level ``limit``).
"""

import json

from pydantic import BaseModel

from kleinanzeigen.models import Listing, SearchResult


class SearchResponse(BaseModel):
    """Serialized search result. ``returned`` counts listings after ``limit``."""

    listings: list[Listing]
    total_results: int | None
    total_pages: int | None
    pages_fetched: int
    returned: int


class ErrorResponse(BaseModel):
    """Wire-level error shape for a failed lookup."""

    error: str


def search_response(
    result: SearchResult, *, limit: int | None = None
) -> SearchResponse:
    listings = result.listings[:limit] if limit and limit > 0 else result.listings
    return SearchResponse(
        listings=listings,
        total_results=result.total_results,
        total_pages=result.total_pages,
        pages_fetched=result.pages_fetched,
        returned=len(listings),
    )


def search_response_json(result: SearchResult, *, limit: int | None = None) -> str:
    return json.dumps(
        search_response(result, limit=limit).model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
