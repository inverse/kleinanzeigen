"""Tests for the MCP search tool: argument validation and request mapping — no network."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from typing import Any, Self

import pytest
import pytest_socket
from fastmcp.exceptions import ToolError, ValidationError

from kleinanzeigen import mcp_server
from kleinanzeigen.mobile import PageProgress
from kleinanzeigen.models import (
    AdType,
    Listing,
    PosterType,
    SearchParams,
    SearchResult,
    SortField,
)


class _FakeClient:
    """Stands in for ``Kleinanzeigen``; records the params and max_results the tool built."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.calls: list[tuple[SearchParams, int | None]] = []
        self._params: SearchParams | None = None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    def iter_search(self, params: SearchParams) -> AsyncIterator[Any]:
        self._params = params

        async def _no_pages() -> AsyncIterator[Any]:
            return
            yield  # pragma: no cover - makes this an async generator

        return _no_pages()

    async def collect_search_pages(
        self,
        pages: AsyncIterator[Any],
        *,
        published_after: datetime | None = None,
        max_results: int | None = None,
    ) -> SearchResult:
        assert self._params is not None
        self.calls.append((self._params, max_results))
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
    with pytest.raises((ToolError, ValidationError)):
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


def test_published_after_maps_to_datetime(fake_client: _FakeClient) -> None:
    _call({"query": "bike", "published_after": "2026-11-01"})

    params, _ = fake_client.calls[0]
    assert params.published_after == datetime(2026, 11, 1)


def test_invalid_published_after_is_rejected_before_search(
    fake_client: _FakeClient,
) -> None:
    with pytest.raises((ToolError, ValidationError)):
        _call({"query": "bike", "published_after": "yesterday"})

    assert fake_client.calls == []


class _ProgressCtx:
    """Minimal stand-in for fastmcp.Context; records report_progress calls."""

    def __init__(self) -> None:
        self.reports: list[tuple[int, int | None]] = []

    async def report_progress(
        self, progress: int, total: int | None, message: str
    ) -> None:
        self.reports.append((progress, total))


async def _reported_totals(exact_total: bool) -> list[tuple[int, int | None]]:
    ctx = _ProgressCtx()
    params = SearchParams(query="bike", page=1, pages=2)

    async def pages() -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
        yield PageProgress(1, 60, 3), []
        yield PageProgress(2, 60, 3), []

    async for _progress, _listings in mcp_server._report_pages(
        ctx,
        pages(),
        params,
        exact_total=exact_total,
    ):
        pass
    return ctx.reports


def test_report_pages_total_only_when_fetch_count_is_exact() -> None:
    pytest_socket.enable_socket()
    try:
        exact = asyncio.run(_reported_totals(exact_total=True))
        unknown = asyncio.run(_reported_totals(exact_total=False))
    finally:
        pytest_socket.disable_socket()

    # page=1, pages=2, total_pages=3 -> exactly 2 pages will be fetched.
    assert exact == [(1, 2), (2, 2)]
    assert unknown == [(1, None), (2, None)]
