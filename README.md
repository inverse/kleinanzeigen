# kleinanzeigen

[![PyPI version](https://img.shields.io/pypi/v/kleinanzeigen)](https://pypi.org/project/kleinanzeigen/)
[![Python](https://img.shields.io/pypi/pyversions/kleinanzeigen)](https://pypi.org/project/kleinanzeigen/)
[![PyPI downloads](https://static.pepy.tech/badge/kleinanzeigen)](https://pepy.tech/projects/kleinanzeigen)
[![CI](https://github.com/inverse/kleinanzeigen/actions/workflows/ci.yml/badge.svg)](https://github.com/inverse/kleinanzeigen/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://github.com/python/mypy)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Async Python client for [kleinanzeigen.de](https://www.kleinanzeigen.de), using
plain HTTP with curl_cffi and BeautifulSoup. No browser required.

Search listings and fetch ad details through an [async library](#library),
a [CLI](#cli), or an [MCP server](#mcp-server).

Requests are made sequentially with delays between pages. Check
kleinanzeigen.de's terms of service before use.

## Requirements

- Python 3.14 or later.

## Installation

Add the package to your Python project:

```sh
uv add kleinanzeigen
```

Or install it with pip:

```sh
pip install kleinanzeigen
```

For standalone CLI and MCP commands, install with pipx:

```sh
pipx install kleinanzeigen
```

## Library

Use `Kleinanzeigen` as an async context manager to manage the HTTP session.
Searches return a `SearchResult` with listings and pagination totals;
single-ad lookups return a `ListingDetail` or `None` if the ad is gone.

### Search and fetch listings

```python
import asyncio

from kleinanzeigen import Kleinanzeigen, SearchParams


async def main():
    async with Kleinanzeigen() as ka:
        result = await ka.search(
            SearchParams(query="fahrrad", location="Berlin", radius=25, pages=2)
        )
        for listing in result.listings:
            print(listing.title, listing.price, listing.url)

        detail = await ka.get_listing("123456789")
        if detail is not None:
            print(detail.title, detail.price.amount, detail.seller.name)


asyncio.run(main())
```

### Saved searches and date cutoffs

Within the same async context, reuse a filtered search URL or restrict results
by publish date. Naive datetimes are interpreted as Europe/Berlin local time.

```python
from datetime import datetime

result = await ka.search_url("https://www.kleinanzeigen.de/s-fahrrad/k0", pages=3)

result = await ka.search(
    SearchParams(query="fahrrad", published_after=datetime(2026, 1, 1), pages=2)
)
```

### Page-by-page results

Use `iter_search()` or `iter_search_url()` to process each page as it arrives,
within the same async context:

```python
async for progress, listings in ka.iter_search(SearchParams(query="fahrrad", pages=2)):
    print(progress.page, progress.total_pages)
    for listing in listings:
        print(listing.title, listing.url)
```

Set `pages=0` to fetch all available pages. Keyword searches default to all
pages; URL searches default to one.

## CLI

Search from the terminal with progress updates and a results table. Use
`--json` on search commands for machine-readable output; `get` displays
formatted ad details and exits with status 1 if the ad is gone.

```sh
# Search by keyword and location
kleinanzeigen search -q 'fahrrad' -l 'Berlin' --radius 5 --pages 3

# Filter by price and return JSON
kleinanzeigen search -q 'iphone' --min-price 100 --max-price 500 --pages 1 --json

# Use a saved or filtered search URL
kleinanzeigen search-url 'https://www.kleinanzeigen.de/s-fahrrad/k0' --pages 3

# Fetch a single ad by URL or numeric ID
kleinanzeigen get 123456789
```

## MCP server

Connect an MCP-compatible client to the `kleinanzeigen-mcp` server to search
listings and retrieve ad details. The server uses the stdio transport.

| Tool | Description |
| --- | --- |
| `search` | Search listings by keyword, location, and price. |
| `search_url` | Search using a saved or filtered Kleinanzeigen URL. |
| `get_listing` | Fetch full ad details by URL or numeric ID. |

Add the server to your MCP client config:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "command": "kleinanzeigen-mcp"
    }
  }
}
```

Both search tools support publish-date filtering and a `limit` on returned
listings. Results include listings, pagination totals, and a `returned` count.
Missing ads return `{"error": "listing not found or removed"}`.

## Development

Set up the environment and run the offline tests and lint checks:

```sh
uv sync
uv run pytest
pre-commit run -a
```

Run the CLI directly from the checkout:

```sh
uv run kleinanzeigen search -q 'fahrrad' --pages 1
```

The included `.mcp.json` registers `kleinanzeigen-dev` using
`uv run kleinanzeigen-mcp`. MCP clients that support project-level
configuration can load it from this checkout.

## Acknowledgements

Based on [ebay-kleinanzeigen-api](https://github.com/DanielWTE/ebay-kleinanzeigen-api/),
adapted to work without a browser.
