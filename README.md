# kleinanzeigen

[![PyPI version](https://img.shields.io/pypi/v/kleinanzeigen)](https://pypi.org/project/kleinanzeigen/)
[![Python](https://img.shields.io/pypi/pyversions/kleinanzeigen)](https://pypi.org/project/kleinanzeigen/)
[![PyPI downloads](https://static.pepy.tech/badge/kleinanzeigen)](https://pepy.tech/projects/kleinanzeigen)
[![CI](https://github.com/inverse/kleinanzeigen/actions/workflows/ci.yml/badge.svg)](https://github.com/inverse/kleinanzeigen/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://github.com/python/mypy)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Browse [kleinanzeigen.de](https://www.kleinanzeigen.de) listings from Python,
your terminal, or an AI assistant. Search by keyword, location, radius, and
price, reuse saved search URLs, and fetch full ad details: price, seller,
description, images, and status.

One package, three ways to use it:

| | What it is | Use it for |
| --- | --- | --- |
| [**Async client**](#async-client) | `Kleinanzeigen`, an `asyncio` Python library returning typed pydantic models | Scripts, scrapers, alerts, data pipelines |
| [**CLI**](#cli) | The `kleinanzeigen` command, with tables, live progress, and `--json` output | Quick searches and shell scripting |
| [**MCP server**](#mcp-server) | The `kleinanzeigen-mcp` command, a stdio [MCP](https://modelcontextprotocol.io) server | Letting Claude or other MCP clients search for you |

All three share the same core: plain HTTP requests through
[curl_cffi](https://github.com/lexiforest/curl_cffi) (Chrome TLS
impersonation), parsed with BeautifulSoup. No browser, Selenium, or
Playwright needed.


> [!NOTE]
> This is an unofficial project, not affiliated with kleinanzeigen.de. It
> fetches pages one at a time, with a delay between them, to stay polite.
> Check kleinanzeigen.de's terms of service before use.

## Installation

Requires Python 3.14 or later.

As a library in your project:

```sh
uv add kleinanzeigen    # or: pip install kleinanzeigen
```

As standalone `kleinanzeigen` and `kleinanzeigen-mcp` commands:

```sh
uv tool install kleinanzeigen    # or: pipx install kleinanzeigen
```

## Async client

Open a `Kleinanzeigen` client as an async context manager. It keeps one HTTP
session (and its cookies) for every request made inside the block.

```python
import asyncio

from kleinanzeigen import Kleinanzeigen, SearchParams


async def main():
    async with Kleinanzeigen() as ka:
        result = await ka.search(
            SearchParams(query="fahrrad", location="Berlin", radius=25, pages=2)
        )
        print(f"{len(result.listings)} of {result.total_results} results")
        for listing in result.listings:
            print(listing.title, listing.price, listing.url)

        detail = await ka.get_listing("123456789")  # ad ID or full URL
        if detail is not None:
            print(detail.title, detail.status, detail.price.amount, detail.seller.name)


asyncio.run(main())
```

### Methods

| Method | Returns | Description |
| --- | --- | --- |
| `search(params)` | `SearchResult` | Keyword search built from a `SearchParams` |
| `search_url(url, pages=1, published_after=None)` | `SearchResult` | Run any kleinanzeigen.de search URL, such as a saved or filtered search |
| `iter_search(params)` | async iterator | Same as `search()`, yielding `(PageProgress, listings)` per page |
| `iter_search_url(url, pages=1)` | async iterator | Same as `search_url()`, yielding page by page |
| `get_listing(url_or_id)` | `ListingDetail \| None` | Full ad details, or `None` if the ad was removed |

### Search parameters

`SearchParams` validates its fields when it is created (non-negative numbers,
`min_price <= max_price`):

| Field | Default | Description |
| --- | --- | --- |
| `query` | `None` | Search keywords |
| `location` | `None` | City or district, e.g. `"Berlin"` or `"Mitte"` |
| `radius` | `None` | Radius around `location`, in km |
| `min_price`, `max_price` | `None` | Price bounds in EUR |
| `page` | `1` | First page to fetch |
| `pages` | `1` | Number of pages to fetch; `0` fetches every page |
| `published_after` | `None` | Drop listings older than this datetime |

Naive datetimes in `published_after` are read as Europe/Berlin local time,
the timezone the site uses. Results are newest first, so pagination stops as
soon as a page reaches older listings.

### Saved searches

Set up filters on the website (category, condition, shipping, and so on),
then pass the resulting URL:

```python
result = await ka.search_url("https://www.kleinanzeigen.de/s-fahrrad/k0", pages=3)
```

### Page by page

Handle each page as soon as it arrives, for example to show progress:

```python
async for progress, listings in ka.iter_search(SearchParams(query="fahrrad", pages=0)):
    print(f"page {progress.page} of {progress.total_pages}")
    for listing in listings:
        print(listing.title, listing.url)
```

### Results

All models are frozen pydantic models, exported from `kleinanzeigen`:

- **`SearchResult`**: `listings`, `total_results`, `total_pages`, `pages_fetched`.
- **`Listing`**: one search result: `ad_id`, `url`, `title`, `price`,
  `location`, `distance_km`, `description`, `published_at`, `is_top_ad`.
- **`ListingDetail`**: one ad page: `status` (`AdStatus`: active, sold,
  reserved, deleted), `price` (`Price`: amount, currency, negotiable),
  `categories`, `description`, `location` (`Location`), `delivery` (pickup or
  shipping), `images`, `details`, `features`, `seller` (`Seller`: name, type,
  member since, badges), `created_at`.

### Client options and errors

```python
Kleinanzeigen(timeout=60.0, page_delay=1.0, max_retries=2, session=None)
```

- `page_delay`: seconds to wait between search pages. Searches by URL
  always wait at least 2 seconds, because the site rate-limits those harder.
- `max_retries`: retries on failed requests, with backoff.
- `session`: bring your own `curl_cffi` `AsyncSession`. The client will not
  close a session you pass in.

When a request still fails after retrying, or the site returns a block or
error page, the client raises `KleinanzeigenError`.

## CLI

```sh
# Keyword search, all pages by default
kleinanzeigen search -q 'fahrrad' -l 'Berlin' --radius 5

# Price range, first page only, as JSON
kleinanzeigen search -q 'iphone' --min-price 100 --max-price 500 --pages 1 --json

# Only listings published since a date
kleinanzeigen search -q 'sofa' -l 'Hamburg' --published-after 2026-11-01

# Saved or filtered search URL (1 page by default)
kleinanzeigen search-url 'https://www.kleinanzeigen.de/s-fahrrad/k0' --pages 3

# Full details for one ad, by ID or URL
kleinanzeigen get 123456789
```

| Command | Description |
| --- | --- |
| `search` | Keyword search. Options: `-q/--query` (required), `-l/--location`, `--radius`, `--min-price`, `--max-price`, `--page`, `--pages` (default `0` = all), `--published-after`, `--json` |
| `search-url URL` | Search with a website URL. Options: `--pages` (default `1`, `0` = all), `--published-after`, `--json` |
| `get URL_OR_ID` | Show price, location, seller, description, details, and image links. Exits with status 1 if the ad is gone |

Searches show a live progress spinner and a results table with clickable
titles in terminals that support links. With `--json`, the CLI prints the
[same JSON shape](#response-format) as the MCP server and shows no progress
spinner, so output can go straight into `jq`.

Run `kleinanzeigen --help` or `kleinanzeigen <command> --help` to see every
option.

## MCP server

`kleinanzeigen-mcp` gives MCP clients (Claude Desktop, Claude Code, Cursor,
and others) access to kleinanzeigen.de over the stdio transport. Once it is
connected, you can ask things like *"find used road bikes under 400 EUR within
10 km of Leipzig posted this week"*.

After installing the commands (`uv tool install kleinanzeigen`), add the
server to your client config:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "command": "kleinanzeigen-mcp"
    }
  }
}
```

Or run it with `uvx`, without installing it first:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "command": "uvx",
      "args": ["--from", "kleinanzeigen", "kleinanzeigen-mcp"]
    }
  }
}
```

### Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search` | `query`, `location`, `radius`, `min_price`, `max_price`, `page`, `pages` (default `0` = all), `published_after`, `limit` | Search response |
| `search_url` | `url`, `pages` (default `1`), `published_after`, `limit` | Search response |
| `get_listing` | `url_or_id` | `ListingDetail`, or `{"error": "listing not found or removed"}` |

`published_after` takes an ISO date or datetime. `limit` caps how many
listings are returned, which keeps responses small for the model. Every tool
publishes a typed output schema.

### Response format

Search responses from the MCP server and `--json` from the CLI share this
format:

```json
{
  "listings": [{ "ad_id": "...", "title": "...", "price": "250", "url": "...", "...": "..." }],
  "total_results": 1234,
  "total_pages": 50,
  "pages_fetched": 2,
  "returned": 25
}
```

`returned` is the number of listings in this response, after `limit` has been
applied.

## Development

```sh
uv sync                 # set up .venv
uv run pytest           # offline tests against saved HTML fixtures
pre-commit run -a       # ruff lint and format
```

Run the CLI from the checkout:

```sh
uv run kleinanzeigen search -q 'fahrrad' --pages 1
```

The included `.mcp.json` registers a `kleinanzeigen-dev` server that runs
`uv run kleinanzeigen-mcp`. MCP clients that support project-level config can
load it straight from this checkout.

The CLI demo GIF in `assets/` is recorded with [vhs](https://github.com/charmbracelet/vhs);
regenerate it with `vhs assets/cli-demo.tape` from the repo root.

## Acknowledgements

Based on [ebay-kleinanzeigen-api](https://github.com/DanielWTE/ebay-kleinanzeigen-api/),
adapted to work without a browser.
