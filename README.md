# kleinanzeigen

Async Python client for [kleinanzeigen.de](https://www.kleinanzeigen.de) backed by
plain HTTP (curl_cffi + BeautifulSoup) — no Playwright, no browser. Ships a CLI
and an MCP server on top of the same client.

Requires Python 3.11+.

Based off the work done in [ebay-kleinanzeigen-api](https://github.com/DanielWTE/ebay-kleinanzeigen-api/) and ported to run without a browser.

> **Note:** this scrapes kleinanzeigen.de without a browser. Pages are fetched
> sequentially with delays to be polite - don't hammer it, and check
> kleinanzeigen.de's terms of service for your use case.

## Install

```bash
# With uv
uv add kleinanzeigen
# With pip
pip install kleinanzeigen
```

## Library

```python
import asyncio
from datetime import datetime

from kleinanzeigen import Kleinanzeigen, SearchParams


async def main():
    async with Kleinanzeigen() as ka:
        # keyword search; pages=0 fetches all pages
        result = await ka.search(
            SearchParams(query="fahrrad", location="Berlin", radius=25, pages=2)
        )
        for listing in result.listings:
            print(listing.title, listing.price, listing.url)
        print(result.total_results, result.total_pages, result.pages_fetched)

        # any saved/filtered search URL (page numbers injected automatically)
        result = await ka.search_url(
            "https://www.kleinanzeigen.de/s-suche/foo.html", pages=3
        )

        # drop listings older than a cutoff (naive = Europe/Berlin)
        result = await ka.search(
            SearchParams(query="fahrrad", published_after=datetime(2026, 1, 1))
        )

        # single ad, by URL or bare id — None when the ad is gone
        detail = await ka.get_listing("123456789")
        if detail:
            print(detail.title, detail.price.amount, detail.seller.name, detail.images)

        # streaming progress: yields (PageProgress, listings) per page
        async for progress, page_listings in ka.iter_search(
            SearchParams(query="fahrrad")
        ):
            print(progress.page, progress.total_pages, len(page_listings))


asyncio.run(main())
```

`SearchParams` fields: `query`, `location`, `radius`, `min_price`, `max_price`,
`page` (first page, 1-based), `pages` (0 = all), `published_after`.
`iter_search_url(url, pages=n)` is the streaming variant of `search_url`.
`iter_search_pages(url_for, first_page=, pages=)` is the low-level primitive
both streaming variants build on.

`ListingDetail` fields: `ad_id`, `url`, `title`, `status` (`active`/`sold`/
`reserved`/`deleted`), `price` (`amount` is `None` when the ad shows no
numeric price, e.g. "VB" or "Zu verschenken"; `negotiable` flags "VB"),
`categories`, `description`, `location` (`postal_code`/`city`/`state`),
`delivery` (`pickup`/`shipping`), `images`, `details`, `features`, `seller`
(`name`, `user_id`, `member_since`, `type`, `badges`), `created_at`,
`scraped_at`.


## CLI

Installed as `kleinanzeigen`:

```sh
# keyword search — all pages by default; Rich table with live spinner
kleinanzeigen search -q "fahrrad" -l "Berlin" --radius 5 --pages 3

# filters; --json prints raw JSON instead of the table
kleinanzeigen search -q "iphone" --min-price 100 --max-price 500 --json

# scrape a saved/filtered search URL
kleinanzeigen search-url "https://www.kleinanzeigen.de/s-suche/foo.html" --pages 3

# single ad by URL or bare id — prints JSON; exits 1 when the ad is gone
kleinanzeigen get 123456789
```

`search` options: `-q/--query` (required), `-l/--location`, `--radius`,
`--min-price`, `--max-price`, `--page`, `--pages`, `--published-after`,
`--json`. `search-url` accepts `--pages`, `--published-after`, `--json`.

## MCP server

Installed as `kleinanzeigen-mcp` (stdio). Tools: `search`, `search_url`,
`get_listing`. Search tools take the same arguments as the library plus a
`limit` cap on returned listings; both accept `published_after` (ISO
date/datetime). Responses are typed `SearchResponse` (`listings`,
`total_results`, `total_pages`, `pages_fetched`, `returned`) or
`ListingDetail`; a missing ad returns `{"error": "listing not found or removed"}`.

Claude Desktop-style config:

```json
{
  "mcpServers": {
    "kleinanzeigen": {
      "command": "kleinanzeigen-mcp"
    }
  }
}
```

From a source checkout: `uv run kleinanzeigen-mcp`.

## Notes

- Pages are fetched **sequentially** with a delay (`page_delay`, default 1s;
  `search_url` enforces at least 2s) — Kleinanzeigen blocks concurrent
  requests from one IP.
- `published_after` stops pagination early once older listings appear and
  trims them from results. Upstream timestamps are naive Europe/Berlin.
- `search`/`search_url` return `SearchResult` (`listings`, `total_results`,
  `total_pages`, `pages_fetched`); `get_listing` returns `ListingDetail` or
  `None`.
- Transient HTTP errors are retried (`max_retries`, exponential backoff);
  exhausted retries raise `KleinanzeigenError`.
