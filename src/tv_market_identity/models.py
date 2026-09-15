from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class TvRow:
    tv_id: str
    prefix: str
    symbol: str
    name: str | None
    currency: str | None
    tv_type: str | None
    type_specs: tuple[str, ...]
    sector: str | None
    market_cap: float | None
    close: float | None


@dataclass(frozen=True)
class FinnhubIdentity:
    symbol: str
    display_symbol: str | None
    description: str | None
    currency: str | None
    security_type: str | None
    mic: str | None
    composite_figi: str | None
    share_class_figi: str | None


@dataclass(frozen=True)
class OpenFigiIdentity:
    figi: str | None
    composite_figi: str | None
    share_class_figi: str | None
    ticker: str | None
    name: str | None
    security_type: str | None
    security_type2: str | None
    exch_code: str | None


@dataclass(frozen=True)
class YahooQuote:
    symbol: str
    exchange: str | None
    full_exchange_name: str | None
    currency: str | None
    quote_type: str | None
    market: str | None
    short_name: str | None
    long_name: str | None
    price: float | None
    delayed_by: int | None


@dataclass
class Binding:
    tv_id: str
    tv_symbol: str
    tv_prefix: str
    tv_currency: str | None
    tv_type: str | None
    status: str
    yahoo_symbol: str | None = None
    yahoo_exchange: str | None = None
    yahoo_market: str | None = None
    yahoo_quote_type: str | None = None
    yahoo_currency: str | None = None
    yahoo_price: float | None = None
    yahoo_delayed_by: int | None = None
    quote_status: str | None = None
    resolved_mic: str | None = None
    source_mic: str | None = None
    target_mic: str | None = None
    source_venue_code: str | None = None
    mapping_method: str | None = None
    source_venue_figi: str | None = None
    target_venue_figi: str | None = None
    finnhub_symbol: str | None = None
    finnhub_type: str | None = None
    composite_figi: str | None = None
    share_class_figi: str | None = None
    venue_figi: str | None = None
    rejection_reason: str | None = None
    fingerprint: str | None = None
    resolver_version: str | None = None
    validated_at: int | None = None
    expires_at: int | None = None
    cache_hit: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
