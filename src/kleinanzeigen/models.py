"""Typed models returned by the client."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AdStatus(StrEnum):
    ACTIVE = "active"
    SOLD = "sold"
    RESERVED = "reserved"
    DELETED = "deleted"


class SortField(StrEnum):
    """Server-side result ordering."""

    NEWEST = "newest"
    PRICE_ASC = "price_asc"
    PRICE_DESC = "price_desc"
    DISTANCE = "distance"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Price(_FrozenModel):
    amount: Decimal | None
    currency: str = "€"
    negotiable: bool = False


class Seller(_FrozenModel):
    name: str | None = None
    user_id: str | None = None
    member_since: str | None = None
    type: Literal["private", "business"] = "private"
    badges: list[str] = []


class SearchParams(_FrozenModel):
    """Core request for a keyword search; CLI/MCP adapters build one.

    Upstream ``published_at`` values are naive Europe/Berlin local time, so a
    naive ``published_after`` is compared in that zone. Passing an aware
    datetime compares across zones normally.
    """

    query: str | None = None
    location: str | None = None
    radius: Annotated[int | None, Field(ge=0)] = None
    min_price: Annotated[int | None, Field(ge=0)] = None
    max_price: Annotated[int | None, Field(ge=0)] = None
    page: Annotated[int, Field(ge=1)] = 1
    pages: Annotated[int, Field(ge=0)] = 1  # 0 = all pages
    sort: SortField | None = None
    published_after: datetime | None = None

    @model_validator(mode="after")
    def _check_price_range(self) -> Self:
        if (
            self.min_price is not None
            and self.max_price is not None
            and self.min_price > self.max_price
        ):
            raise ValueError("min_price must not exceed max_price")
        if self.sort is SortField.DISTANCE and not self.location:
            raise ValueError("sort='distance' requires a location")
        return self


class Location(_FrozenModel):
    postal_code: str = ""
    city: str = ""
    state: str = ""


class Listing(_FrozenModel):
    """One search-result card."""

    ad_id: str
    url: str
    title: str
    price: Decimal | None
    location: str
    distance_km: float | None
    description: str
    published_at: datetime | None
    is_top_ad: bool


class SearchResult(_FrozenModel):
    listings: list[Listing] = []
    total_results: int | None = None
    total_pages: int | None = None
    pages_fetched: int = 0


class ListingDetail(_FrozenModel):
    """Details returned by the mobile API for a single ad."""

    ad_id: str
    url: str
    title: str
    status: AdStatus
    price: Price
    categories: list[str] = []
    description: str | None = None
    location: Location = Location()
    delivery: Literal["pickup", "shipping"] | None = None
    images: list[str] = []
    details: dict[str, str] = {}
    features: list[str] = []
    seller: Seller = Seller()
    created_at: date | None = None
    scraped_at: datetime | None = None
