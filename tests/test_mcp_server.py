"""Tests for the MCP search tool: argument validation and request mapping — no network."""

import asyncio
from collections.abc import Iterator
from typing import Any, Self

import pytest
import pytest_socket
from mcp.server.mcpserver.exceptions import ToolError

from kleinanzeigen import mcp_server
from kleinanzeigen.models import (
    AdType,
    Listing,
    PosterType,
    SearchParams,
    SearchResult,
    SortField,
)


class _FakeClient:
    """Stands in for ``Kleinanzeigen``; records the params the tool built."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls: list[tuple[SearchParams, int | None]] = []

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def search(
        self, params: SearchParams, *, max_results: int | None = None
    ) -> SearchResult:
        self.calls.append((params, max_results))
        listing = Listing(
            ad_id="1",
            url="https://www.kleinanzeigen.de/s-anzeige/x/1",
            title="Bike",
            price=None,
            location="Berlin",
            distance_km=None,
            description="",
            published_at=None,
            is_top_ad=False,
        )
        return SearchResult(
            listings=[listing], total_results=1, total_pages=1, pages_fetched=1
        )


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[_FakeClient]:
    client = _FakeClient()
    monkeypatch.setattr(mcp_server, "Kleinanzeigen", lambda *a, **k: client)
    yield client


def _call(args: dict[str, Any]) -> None:
    # asyncio needs socketpair; the autouse fixture re-disables sockets afterwards.
    pytest_socket.enable_socket()
    try:
        asyncio.run(mcp_server.mcp.call_tool("search", args))
    finally:
        pytest_socket.disable_socket()


def test_enum_fields_map_to_core_enums(fake_client: _FakeClient) -> None:
    _call(
        {
            "query": "bike",
            "sort": "price_asc",
            "poster_type": "private",
            "ad_type": "wanted",
        }
    )

    params, _ = fake_client.calls[0]
    assert params.sort is SortField.PRICE_ASC
    assert params.poster_type is PosterType.PRIVATE
    assert params.ad_type is AdType.WANTED


def test_ad_type_defaults_to_offered(fake_client: _FakeClient) -> None:
    _call({"query": "bike"})

    params, _ = fake_client.calls[0]
    assert params.ad_type is AdType.OFFERED


def test_invalid_enum_value_is_rejected_before_search(
    fake_client: _FakeClient,
) -> None:
    with pytest.raises(ToolError):
        _call({"query": "bike", "sort": "cheapest"})

    assert fake_client.calls == []


def test_max_results_without_pages_fetches_all_pages(
    fake_client: _FakeClient,
) -> None:
    _call({"query": "bike", "max_results": 5})

    params, max_results = fake_client.calls[0]
    assert params.pages == 0
    assert max_results == 5


def test_pages_default_to_one_without_max_results(
    fake_client: _FakeClient,
) -> None:
    _call({"query": "bike"})

    params, max_results = fake_client.calls[0]
    assert params.pages == 1
    assert max_results is None
