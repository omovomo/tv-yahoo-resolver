from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScreenConfig:
    stock_filter_schema: int
    limit: int
    order_by: str
    ascending: bool
    market: str
    min_market_cap: float | None
    min_avg_volume_90d: float | None
    min_pe: float | None
    sectors: tuple[str, ...]
    primary_only: bool


def _bool(v: str) -> bool:
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _find_filter(filters: configparser.SectionProxy, field: str, *, required: bool = True) -> str | None:
    for _key, value in filters.items():
        raw = value.strip()
        if raw.startswith(field + "=") or raw.startswith(field + "|"):
            return raw
    if required:
        raise ValueError(f"Missing [Filters] entry for {field}")
    return None


def load_screen_config(path: str | Path) -> ScreenConfig:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    with open(path, "r", encoding="utf-8") as f:
        parser.read_file(f)

    tv = parser["TradingView"]
    filters = parser["Filters"]
    schema = int(tv.get("StockFilterSchema", "0"))
    if schema != 2:
        raise ValueError(f"Prototype expects StockFilterSchema=2, got {schema}")

    market_expr = _find_filter(filters, "market", required=True)
    assert market_expr is not None
    if "=" not in market_expr:
        raise ValueError(f"Expected market=VALUE, got {market_expr!r}")
    _, market = market_expr.split("=", 1)

    def above_optional(field: str) -> float | None:
        expr = _find_filter(filters, field, required=False)
        if expr is None:
            return None
        parts = expr.split("|")
        if len(parts) != 3 or parts[1] != "above":
            raise ValueError(f"Expected {field}|above|VALUE, got {expr!r}")
        return float(parts[2])

    sector_expr = _find_filter(filters, "sector", required=False)
    sectors: tuple[str, ...] = ()
    if sector_expr is not None:
        parts = sector_expr.split("|", 2)
        if len(parts) != 3 or parts[1] != "isin":
            raise ValueError(f"Expected sector|isin|..., got {sector_expr!r}")
        sectors = tuple(x.strip() for x in parts[2].split(",") if x.strip())

    return ScreenConfig(
        stock_filter_schema=schema,
        limit=int(tv.get("Limit", "1000")),
        order_by=tv.get("OrderBy", "market_cap_basic"),
        ascending=_bool(tv.get("Ascending", "true")),
        market=market.strip(),
        min_market_cap=above_optional("market_cap_basic"),
        min_avg_volume_90d=above_optional("average_volume_90d_calc"),
        min_pe=above_optional("price_earnings_ttm"),
        sectors=sectors,
        primary_only=_bool(tv.get("PrimaryOnly", "false")),
    )
