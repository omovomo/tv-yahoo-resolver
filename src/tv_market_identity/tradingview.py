from __future__ import annotations

from tradingview_screener import Column, Query

from .config import ScreenConfig
from .models import TvRow


TV_COLUMNS = (
    "name",
    "description",
    "exchange",
    "market",
    "country",
    "currency",
    "type",
    "typespecs",
    "sector",
    "market_cap_basic",
    "average_volume_90d_calc",
    "price_earnings_ttm",
    "close",
    "is_primary",
)


def build_query(cfg: ScreenConfig) -> Query:
    query = Query().select(*TV_COLUMNS).set_markets(cfg.market)

    # tradingview-screener Query() currently carries an implicit
    # is_primary=true stock filter. Make our config semantics explicit:
    # PrimaryOnly=false means no primary-listing restriction, while true
    # adds the filter below. Existing GARP presets already replaced the
    # library default through .where(...), so this also makes market-only
    # coverage presets consistent with filtered presets.
    if not cfg.primary_only:
        query.query["filter"] = []

    conditions = []
    if cfg.min_market_cap is not None:
        conditions.append(Column("market_cap_basic") > cfg.min_market_cap)
    if cfg.min_avg_volume_90d is not None:
        conditions.append(Column("average_volume_90d_calc") > cfg.min_avg_volume_90d)
    if cfg.min_pe is not None:
        conditions.append(Column("price_earnings_ttm") > cfg.min_pe)
    if cfg.sectors:
        conditions.append(Column("sector").isin(list(cfg.sectors)))
    if cfg.primary_only:
        conditions.append(Column("is_primary") == True)

    if conditions:
        query = query.where(*conditions)

    return query.order_by(cfg.order_by, ascending=cfg.ascending).limit(cfg.limit)


def fetch_screen(cfg: ScreenConfig):
    # Intentionally one deterministic TradingView request. Coverage profiles
    # should use a sufficiently high Limit (currently 2000). The CLI warns if
    # totalCount still exceeds the returned row count.
    return build_query(cfg).get_scanner_data()


def dataframe_to_tv_rows(df) -> list[TvRow]:
    rows: list[TvRow] = []
    for record in df.to_dict(orient="records"):
        tv_id = str(record.get("ticker") or "").upper()
        if ":" not in tv_id:
            continue
        prefix, symbol = tv_id.split(":", 1)
        specs = record.get("typespecs")
        if not isinstance(specs, (list, tuple)):
            specs = []
        rows.append(TvRow(
            tv_id=tv_id,
            prefix=prefix,
            symbol=symbol,
            name=record.get("description") or record.get("name"),
            currency=(str(record.get("currency")).upper() if record.get("currency") else None),
            tv_type=record.get("type"),
            type_specs=tuple(str(x) for x in specs),
            sector=record.get("sector"),
            market_cap=_float(record.get("market_cap_basic")),
            close=_float(record.get("close")),
        ))
    return rows


def _float(v):
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
