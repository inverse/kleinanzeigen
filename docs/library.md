# Python client

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

## Methods

| Method | Returns | Description |
| --- | --- | --- |
| `search(params)` | `SearchResult` | Keyword search built from a `SearchParams` |
| `iter_search(params)` | async iterator | Same as `search()`, yielding `(PageProgress, listings)` per page |
| `get_listing(url_or_id)` | `ListingDetail \| None` | Full ad details, or `None` if the ad was removed |

## Search parameters

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
| `sort` | `None` | `newest` (default), `price_asc`, `price_desc`, or `distance` |
| `published_after` | `None` | Drop listings older than this datetime |

Naive datetimes in `published_after` are read as Europe/Berlin local time,
the timezone the site uses. Results are newest first, so pagination stops as
soon as a page reaches older listings.

## Page by page

Handle each page as soon as it arrives, for example to show progress:

```python
async for progress, listings in ka.iter_search(SearchParams(query="fahrrad", pages=0)):
    print(f"page {progress.page} of {progress.total_pages}")
    for listing in listings:
        print(listing.title, listing.url)
```

## Results

All models are frozen pydantic models, exported from `kleinanzeigen`:

- **`SearchResult`**: `listings`, `total_results`, `total_pages`, `pages_fetched`.
- **`Listing`**: one search result: `ad_id`, `url`, `title`, `price`,
  `location`, `distance_km`, `description`, `published_at`, `is_top_ad`.
- **`ListingDetail`**: one ad page: `status` (`AdStatus`: active, sold,
  reserved, deleted), `price` (`Price`: amount, currency, negotiable),
  `categories`, `description`, `location` (`Location`), `delivery` (pickup or
  shipping), `images`, `details`, `features`, `seller` (`Seller`: name, type,
  member since, badges), `created_at`.

## Client options and errors

```python
Kleinanzeigen(timeout=60.0, page_delay=1.0, max_retries=2, session=None)
```

- `page_delay`: seconds to wait between search pages.
- `max_retries`: retries on failed requests, with backoff.
- `session`: bring your own `curl_cffi` `AsyncSession`. The client will not
  close a session you pass in.

When a mobile API request still fails after retrying, the client raises
`KleinanzeigenError`.
