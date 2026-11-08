# kleinanzeigen

Async Python client for [kleinanzeigen.de](https://www.kleinanzeigen.de) over plain
HTTP (`curl_cffi` with Chrome TLS impersonation + BeautifulSoup). No browser.

## Structure

- `src/kleinanzeigen/client.py` — `Kleinanzeigen` async client. `search()` takes
  a `SearchParams` and `search_url()` takes a URL; both return a
  `SearchResult`. `iter_search()` / `iter_search_url()` stream
  `(PageProgress, listings)` per page for progress UIs;
  `iter_search_pages(url_for)` is the low-level primitive, and
  `collect_search_pages()` drains an iterator into a `SearchResult`.
  `get_listing()` fetches a single ad (`None` when gone). All pagination
  policy (delays, URL building) lives here — adapters never touch it.
- `src/kleinanzeigen/parsing.py` — HTML extraction: search cards, breadcrumb
  totals, ad detail pages, URL building, date/price/location parsing.
  `apply_min_publish_date()` filters a page's listings and reports whether
  an old listing ends pagination.
- `src/kleinanzeigen/models.py` — frozen pydantic models: `SearchParams`
  (validated request: page/pages/price bounds), `Listing`, `ListingDetail`,
  `SearchResult`, `Price`, `Seller`, `Location`, `AdStatus`. Upstream
  `published_at` is naive Europe/Berlin local time.
- `src/kleinanzeigen/format.py` — typed JSON response boundary shared by CLI
  and MCP: `SearchResponse` (envelope with `returned` after a response-level
  `limit`), `ErrorResponse`, `search_response*()`. Responses embed core
  models directly; keep adapter-only fields (limit/returned) out of
  `SearchResult`.
- `src/kleinanzeigen/cli.py` — `kleinanzeigen` command: `search`, `search-url`,
  `get`. Rich table renders `SearchResult` directly; `--json` serializes via
  `search_response_json`. Progress spinner consumes `iter_search*` on a
  worker thread — keep CLI/presentation concerns out of `client.py`.
- `src/kleinanzeigen/mcp_server.py` — `kleinanzeigen-mcp` MCP server exposing
  the same search/get operations to MCP clients. Tools return typed models
  (`SearchResponse`, `ListingDetail | ErrorResponse`) so FastMCP publishes
  concrete output schemas.
- `tests/` — pytest suite (currently `test_parsing.py`).

## Setup

Managed with `uv`; the venv is `.venv/`.

```sh
uv sync
```

## Run

```sh
kleinanzeigen search -q "fahrrad" -l "Berlin" --radius 5   # all pages by default
kleinanzeigen search-url "<saved search URL>" --pages 3
kleinanzeigen get <url-or-ad-id>
```

## Tests

```sh
uv run pytest
```

Config lives in `pyproject.toml` (`testpaths = ["tests"]`, `pythonpath = ["src"]`).
Tests are offline — they exercise `parsing.py` against fixtures, not live HTTP.

## Lint / format

Lint/format run through pre-commit only — ruff is not installed in the venv
(pre-commit pins its own version via `ruff-pre-commit`):

```sh
pre-commit run -a
```

Ruff config is in `pyproject.toml` (`src = ["src", "tests"]`); pre-commit's
pinned ruff version is the single source of truth for the linter version.
