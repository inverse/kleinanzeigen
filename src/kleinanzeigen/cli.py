"""CLI for searching kleinanzeigen.de — mirrors the lib's search API."""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import click
import humanize
from pydantic import ValidationError
from rich.console import Console, Group
from rich.markup import escape
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from kleinanzeigen import Kleinanzeigen
from kleinanzeigen._version import package_version
from kleinanzeigen.client import PageProgress
from kleinanzeigen.format import search_response_json
from kleinanzeigen.models import (
    AdStatus,
    Listing,
    ListingDetail,
    SearchParams,
    SearchResult,
)

console = Console()


class _IsoDateTime(click.ParamType):
    name = "datetime"

    def convert(self, value, param, ctx):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            self.fail(f"{value!r} is not a valid ISO date/datetime", param, ctx)


ISO_DATETIME = _IsoDateTime()


def _search_pages_iter(
    ka: Kleinanzeigen, query: SearchParams | str, pages: int
) -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
    if isinstance(query, SearchParams):
        return ka.iter_search(query)
    return ka.iter_search_url(query, pages=pages)


def _run_iter_search(
    query: SearchParams | str,
    *,
    first_page: int = 1,
    pages: int = 0,
    show_progress: bool = True,
    published_after: datetime | None = None,
) -> SearchResult:
    """Consume a search-page iterator on a worker thread.

    ``query`` is a ``SearchParams`` or a saved-search URL. Each
    ``PageProgress`` is pushed onto a queue so the main thread can render a
    live spinner while pages stream in; the collected ``SearchResult`` comes
    back via ``out``.
    """
    progress_q: queue.Queue[PageProgress | None] = queue.Queue()
    out: dict[str, Any] = {}

    async def _tee(
        pages_iter: AsyncIterator[tuple[PageProgress, list[Listing]]],
    ) -> AsyncIterator[tuple[PageProgress, list[Listing]]]:
        async for progress, listings in pages_iter:
            progress_q.put(progress)
            yield progress, listings

    def worker() -> None:
        try:

            async def run() -> SearchResult:
                async with Kleinanzeigen() as ka:
                    pages_iter = _tee(_search_pages_iter(ka, query, pages))
                    return await Kleinanzeigen.collect_search_pages(
                        pages_iter, published_after=published_after
                    )

            out["result"] = asyncio.run(run())
        except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
            out["error"] = exc
        finally:
            progress_q.put(None)

    threading.Thread(target=worker, daemon=True).start()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=False,
        disable=not show_progress,
    ) as progress:
        task = progress.add_task(description="Fetching results...", total=None)
        while True:
            item = progress_q.get()
            if item is None:
                break
            fetched = item.page - first_page + 1
            total_pages = item.total_pages
            total = (
                min(total_pages, first_page + pages - 1)
                if total_pages is not None and pages > 0
                else total_pages
            )
            if total:
                if fetched >= total:
                    description = f"Fetched {fetched} of {total} pages..."
                else:
                    description = (
                        f"Fetching pages {first_page}-{item.page} of {total}..."
                    )
            else:
                description = (
                    f"Fetching pages {first_page}-{item.page}..."
                    if fetched > 1
                    else f"Fetching page {item.page}..."
                )
            progress.update(task, description=description)

    if "error" in out:
        raise out["error"]
    return out["result"]


@click.group()
@click.version_option(package_version(), prog_name="kleinanzeigen")
def cli() -> None:
    """Search kleinanzeigen.de from the command line."""


@cli.command()
@click.option("--query", "-q", required=True, help="Search query")
@click.option(
    "--location", "-l", default=None, help="Location (e.g. 'Berlin' or 'Mitte')"
)
@click.option("--radius", type=click.IntRange(min=0), default=None, help="Radius in km")
@click.option(
    "--min-price", type=click.IntRange(min=0), default=None, help="Min price in EUR"
)
@click.option(
    "--max-price", type=click.IntRange(min=0), default=None, help="Max price in EUR"
)
@click.option(
    "--pages", type=click.IntRange(min=0), default=0, help="Pages to fetch (0 = all)"
)
@click.option("--page", type=click.IntRange(min=1), default=1, help="Starting page")
@click.option(
    "--json", "json_out", is_flag=True, help="Print raw JSON instead of a table"
)
@click.option(
    "--published-after",
    default=None,
    type=ISO_DATETIME,
    help="Drop listings older than this ISO date/datetime (naive = Europe/Berlin)",
)
def search(
    query: str,
    location: str | None,
    radius: int | None,
    min_price: int | None,
    max_price: int | None,
    pages: int,
    page: int,
    json_out: bool,
    published_after: datetime | None,
) -> None:
    """Keyword search."""
    try:
        params = SearchParams(
            query=query,
            location=location,
            radius=radius,
            min_price=min_price,
            max_price=max_price,
            page=page,
            pages=pages,
            published_after=published_after,
        )
    except ValidationError as exc:
        raise click.UsageError(exc.errors()[0]["msg"]) from exc
    result = _run_iter_search(
        params,
        first_page=page,
        pages=pages,
        show_progress=not json_out,
        published_after=params.published_after,
    )
    if json_out:
        click.echo(search_response_json(result))
        return
    _print_table(
        result,
        query=query,
        location=location,
        radius=radius,
        min_price=min_price,
        max_price=max_price,
    )


@cli.command("search-url")
@click.argument("url")
@click.option(
    "--pages", type=click.IntRange(min=0), default=1, help="Number of pages to fetch"
)
@click.option(
    "--json", "json_out", is_flag=True, help="Print raw JSON instead of a table"
)
@click.option(
    "--published-after",
    default=None,
    type=ISO_DATETIME,
    help="Drop listings older than this ISO date/datetime (naive = Europe/Berlin)",
)
def search_url_cmd(
    url: str, pages: int, json_out: bool, published_after: datetime | None
) -> None:
    """Scrape a saved/filtered kleinanzeigen.de search URL."""
    result = _run_iter_search(
        url,
        first_page=1,
        pages=pages,
        show_progress=not json_out,
        published_after=published_after,
    )
    if json_out:
        click.echo(search_response_json(result))
        return
    _print_table(result, query=url)


@cli.command("get")
@click.argument("url_or_id")
def get_cmd(url_or_id: str) -> None:
    """Fetch a single listing by URL or bare ad id."""

    async def run() -> ListingDetail | None:
        async with Kleinanzeigen() as ka:
            return await ka.get_listing(url_or_id)

    detail = asyncio.run(run())
    if detail is None:
        console.print("[red]Listing not found or removed.[/red]")
        raise SystemExit(1)
    console.print(_render_detail(detail))


TITLE_MAX_WIDTH = 32
# Upstream published_at values are naive Europe/Berlin local time.
UPSTREAM_TZ = ZoneInfo("Europe/Berlin")


def _print_table(
    result: SearchResult,
    *,
    query: str | None = None,
    location: str | None = None,
    radius: int | None = None,
    min_price: int | None = None,
    max_price: int | None = None,
) -> None:
    listings = result.listings
    if query is not None:
        parts = [f"'{escape(query)}'"]
        if location:
            parts.append(f"in '{escape(location)}'")
        if radius is not None:
            parts.append(f"(radius: {radius} km)")
        if min_price is not None or max_price is not None:
            price_range = (
                f"{min_price or 0}-{max_price} EUR"
                if max_price is not None
                else f">= {min_price} EUR"
            )
            parts.append(f"price: {price_range}")
        console.print(f"[bold]Search:[/bold] {' '.join(parts)}")

    if not listings:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search Results ({len(listings)})")
    table.add_column(
        "Title",
        style="cyan",
        no_wrap=True,
        overflow="ellipsis",
        max_width=TITLE_MAX_WIDTH,
    )
    table.add_column("Price", style="green", justify="right", no_wrap=True)
    table.add_column("Location", style="yellow", max_width=24, overflow="ellipsis")
    table.add_column("Dist.", justify="right", no_wrap=True)
    table.add_column(
        "Age", style="magenta", no_wrap=True, max_width=14, overflow="ellipsis"
    )

    for item in listings:
        title = escape(item.title.replace("\n", " ").strip())
        display_title = f"[link={escape(item.url)}]{title}[/link]"
        price = f"{item.price} €" if item.price is not None else "—"
        dist = f"{item.distance_km:g} km" if item.distance_km is not None else "—"
        table.add_row(
            display_title,
            price,
            escape(item.location) or "—",
            dist,
            _format_age(item.published_at),
        )
    console.print(table)

    total = result.total_results or "?"
    total_pages = result.total_pages
    pages = f"{result.pages_fetched}" + (f" of {total_pages}" if total_pages else "")
    console.print(f"[dim]{len(listings)} of {total} results ({pages} pages)[/dim]")


def _format_age(published_at: datetime | None) -> str:
    if published_at is None:
        return "—"
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UPSTREAM_TZ)
    delta = datetime.now(UTC) - published_at.astimezone(UTC)
    return humanize.naturaltime(delta, future=False)


def _render_detail(detail: ListingDetail) -> Group:
    header = f"[cyan][link={escape(detail.url)}]{escape(detail.title)}[/link][/cyan]"
    if detail.status != AdStatus.ACTIVE:
        header += f" [{_status_style(detail.status)}]{detail.status.value}[/]"

    facts = Table.grid(padding=(0, 2))
    price = detail.price
    price_text = (
        f"{price.amount:g} {price.currency}"
        if price.amount is not None
        else "[dim]Price on request[/dim]"
    )
    if price.negotiable:
        price_text += " [dim](negotiable)[/dim]"
    facts.add_row("[bold]Price[/bold]", price_text)

    loc = detail.location
    loc_parts = [p for p in (loc.city, loc.state, loc.postal_code) if p]
    facts.add_row(
        "[bold]Location[/bold]", ", ".join(escape(p) for p in loc_parts) or "—"
    )

    if detail.delivery is not None:
        facts.add_row(
            "[bold]Delivery[/bold]",
            "Pickup only" if detail.delivery == "pickup" else "Shipping available",
        )

    if detail.created_at is not None:
        created_dt = datetime.combine(
            detail.created_at, datetime.min.time(), tzinfo=UPSTREAM_TZ
        )
        age = humanize.naturaltime(datetime.now(UPSTREAM_TZ) - created_dt, future=False)
        facts.add_row("[bold]Listed[/bold]", f"{detail.created_at.isoformat()} ({age})")

    if detail.categories:
        facts.add_row(
            "[bold]Category[/bold]", " › ".join(escape(c) for c in detail.categories)
        )

    seller = detail.seller
    seller_parts: list[str] = []
    if seller.name:
        seller_parts.append(f"[bold]{escape(seller.name)}[/bold]")
    seller_parts.append(seller.type.capitalize())
    if seller.member_since:
        seller_parts.append(f"member since {escape(seller.member_since)}")
    if seller.badges:
        seller_parts.append(", ".join(escape(b) for b in seller.badges))
    facts.add_row("[bold]Seller[/bold]", " · ".join(seller_parts) or "—")

    sections: list[Any] = [header, facts]

    if detail.description:
        sections.append(
            f"[bold]Description[/bold]\n{escape(detail.description.strip())}"
        )

    if detail.details:
        spec_table = Table(title="Details", show_header=False, box=None, padding=(0, 2))
        spec_table.add_column(style="dim")
        spec_table.add_column()
        for key, value in detail.details.items():
            spec_table.add_row(escape(key), escape(value))
        sections.append(spec_table)

    if detail.features:
        sections.append(
            "[bold]Features[/bold]\n"
            + "\n".join(f"• {escape(f)}" for f in detail.features)
        )

    if detail.images:
        shown = detail.images[:5]
        lines = [f"[link={escape(u)}]image {i}[/link]" for i, u in enumerate(shown, 1)]
        if len(detail.images) > len(shown):
            lines.append(f"[dim]… and {len(detail.images) - len(shown)} more[/dim]")
        sections.append(
            f"[bold]Images ({len(detail.images)})[/bold]\n" + "\n".join(lines)
        )

    spaced: list[Any] = []
    for section in sections:
        spaced.extend((section, ""))
    spaced.pop()
    return Group(*spaced)


def _status_style(status: AdStatus) -> str:
    return {
        AdStatus.ACTIVE: "green",
        AdStatus.SOLD: "yellow",
        AdStatus.RESERVED: "cyan",
        AdStatus.DELETED: "red",
    }[status]


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
