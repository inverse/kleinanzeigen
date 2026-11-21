# kleinanzeigen

Async Python client for [kleinanzeigen.de](https://www.kleinanzeigen.de) over its
Android JSON API using native async HTTPX. No browser.

## Structure

- `src/kleinanzeigen/client.py` — `Kleinanzeigen` async client. `search()`
  takes a `SearchParams` and returns a `SearchResult`; `iter_search()` streams
  `(PageProgress, listings)` per page for progress UIs, and
  `collect_search_pages()` drains an iterator into a `SearchResult`.
  `get_listing()` accepts an ad URL or ID and returns `None` when gone.
- `src/kleinanzeigen/mobile.py` — search and detail transport via the Android
  app's JSON API (`api.kleinanzeigen.de`). Public Basic auth + app headers, no
  account. Maps ad JSON onto `Listing` and `ListingDetail`; resolves `location`
  names to `locationId` via `/api/locations.json`. Pagination delays and retry
  policy live here.
- `src/kleinanzeigen/models.py` — frozen pydantic models: `SearchParams`
  (validated request: page/pages/price bounds/sort plus poster_type, ad_type,
  picture_required/shippable/buy_now_only flags, include_top_ads toggle and
  require/exclude term filters), `SortField`, `PosterType`, `AdType`, `Listing`
  (is_top_ad, has_images), `ListingDetail`, `SearchResult`, `Price`, `Seller`,
  `Location`, `AdStatus`. Upstream `published_at` is naive Europe/Berlin local
  time.
- `src/kleinanzeigen/format.py` — typed JSON response boundary shared by CLI
  and MCP: `SearchResponse` (envelope with `returned` after a response-level
  `limit`), `ErrorResponse`, `search_response*()`. Responses embed core
  models directly; keep adapter-only fields (limit/returned) out of
  `SearchResult`.
- `src/kleinanzeigen/cli.py` — `kleinanzeigen` command: `search`, `get`.
  Rich table renders `SearchResult` directly; `--json` serializes via
  `search_response_json`. Progress spinner consumes `iter_search*` on a
  worker thread — keep CLI/presentation concerns out of `client.py`.
- `src/kleinanzeigen/mcp_server.py` — `kleinanzeigen-mcp` MCP server exposing
  the same search/get operations to MCP clients. Tools return typed models
  (`SearchResponse`, `ListingDetail | ErrorResponse`) so FastMCP publishes
  concrete output schemas.
- `tests/` — offline pytest suite (`test_mobile.py`, `test_cli.py`).

## Setup

Managed with `uv`; the venv is `.venv/`.

```sh
uv sync
```

## Run

```sh
kleinanzeigen search -q "fahrrad" -l "Berlin" --radius 5   # all pages by default
kleinanzeigen get <url-or-ad-id>
```

## Tests

```sh
uv run pytest
```

Config lives in `pyproject.toml` (`testpaths = ["tests"]`, `pythonpath = ["src"]`).
Tests are offline — they use synthetic API payloads and disable network access.

## Release

Version is derived from git tags via `hatch-vcs` (`dynamic = ["version"]` in
`pyproject.toml`) — never edit a version field by hand. To release `X.Y.Z`,
create a GitHub Release with tag `X.Y.Z` on the target commit;
`.github/workflows/publish.yml` builds and publishes it to PyPI. Commits after
a tag build as `X.Y.(Z+1).devN+g<sha>.d<date>` dev versions.

## Lint / format

Lint/format run through pre-commit only — ruff is not installed in the venv
(pre-commit pins its own version via `ruff-pre-commit`):

```sh
pre-commit run -a
```

Ruff config is in `pyproject.toml` (`src = ["src", "tests"]`); pre-commit's
pinned ruff version is the single source of truth for the linter version.
