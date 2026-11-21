# kleinanzeigen

[![PyPI version](https://img.shields.io/pypi/v/kleinanzeigen)](https://pypi.org/project/kleinanzeigen/)
[![Python](https://img.shields.io/pypi/pyversions/kleinanzeigen)](https://pypi.org/project/kleinanzeigen/)
[![PyPI downloads](https://static.pepy.tech/badge/kleinanzeigen)](https://pepy.tech/projects/kleinanzeigen)
[![CI](https://github.com/inverse/kleinanzeigen/actions/workflows/ci.yml/badge.svg)](https://github.com/inverse/kleinanzeigen/actions/workflows/ci.yml)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)<br>
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://github.com/python/mypy)
[![M8ven Score](https://m8ven.ai/badge/mcp/inverse-kleinanzeigen-hsg9h3?v=a8713f566b3315691f3db25a4c8701a4)](https://m8ven.ai/mcp/inverse-kleinanzeigen-hsg9h3?s=readme)
[![codecov](https://codecov.io/gh/inverse/kleinanzeigen/graph/badge.svg?token=L95ZKUSN85)](https://codecov.io/gh/inverse/kleinanzeigen)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Browse [kleinanzeigen.de](https://www.kleinanzeigen.de) listings from Python,
your terminal, or an AI assistant. Search by keyword, location, radius, and
price, and fetch full ad details: price, seller, description, images, and status.

One package, three ways to use it:

| | What it is | Use it for |
| --- | --- | --- |
| [**Async client**](#async-client) | `Kleinanzeigen`, an `asyncio` Python library returning typed pydantic models | Scripts, scrapers, alerts, data pipelines |
| [**CLI**](#cli) | The `kleinanzeigen` command, with tables, live progress, and `--json` output | Quick searches and shell scripting |
| [**MCP server**](#mcp-server) | The `kleinanzeigen-mcp` command, a stdio [MCP](https://modelcontextprotocol.io) server | Letting Claude or other MCP clients search for you |

All three share the same core: kleinanzeigen.de's Android JSON API over HTTPX.
No browser, Selenium, Playwright, or account needed.


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

```python
async with Kleinanzeigen() as ka:
    result = await ka.search(SearchParams(query="fahrrad", pages=2))
    for listing in result.listings:
        print(listing.title, listing.price, listing.url)
```

`Kleinanzeigen` returns frozen pydantic models (`SearchResult`,
`ListingDetail`) and supports per-page iteration and a caller-owned HTTP
session. See [docs/library.md](docs/library.md) for the full API: methods,
`SearchParams`, options, and error handling.

## CLI

```sh
# Keyword search, all pages by default
kleinanzeigen search -q 'fahrrad' -l 'Berlin' --radius 5

# Limit to one category, by name or id
kleinanzeigen search -q 'velo' --category 'Fahrräder & Zubehör'

# Price range, first page only, as JSON
kleinanzeigen search -q 'iphone' --min-price 100 --max-price 500 --pages 1 --json

# Only listings published since a date
kleinanzeigen search -q 'sofa' -l 'Hamburg' --published-after 2026-11-01

# Full details for one ad, by ID or URL
kleinanzeigen get 123456789
```

| Command | Description |
| --- | --- |
| `search` | Keyword search. Options: `-q/--query` (required), `--category` (id or name), `-l/--location`, `--radius`, `--min-price`, `--max-price`, `--page`, `--pages` (default `0` = all), `--published-after`, `--json` |
| `categories [-q QUERY]` | List category IDs and paths for `--category`; `-q` filters by name or path; `--json` prints the same shape as the MCP tool |
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

| Tool | Description | Returns |
| --- | --- | --- |
| `search` | Keyword search; `query` is required, `category` optionally limits to one category (id or German name) | Search response |
| `list_categories` | Category IDs and paths; `query` filters by name or path, empty lists the full tree | List of `Category` (`id`, `name`, `parent_id`, `path`) |
| `get_listing` | Full details for one ad by URL or ID (`url_or_id`) | `ListingDetail`, or `{"error": "listing not found or removed"}` |


## Development

```sh
uv sync                 # set up .venv
uv run pytest           # offline API mapping and CLI tests
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
