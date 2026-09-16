from __future__ import annotations

import pandas as pd

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
    "active_symbol",
    "isin",
)


class PaginationStabilityError(RuntimeError):
    """Raised when a requested complete TradingView universe cannot be proven complete."""


def build_query(cfg: ScreenConfig, *, offset: int = 0, page_size: int | None = None) -> Query:
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

    if offset < 0:
        raise ValueError("offset must be >= 0")
    size = cfg.limit if page_size is None else page_size
    if size <= 0:
        raise ValueError("page_size must be > 0")

    # tradingview-screener stores pagination as range=[start, end), despite the
    # public method being named limit().  Therefore page N must use
    # offset=start and limit=start+page_size.
    query = query.order_by(cfg.order_by, ascending=cfg.ascending)
    if offset:
        query = query.offset(offset)
    return query.limit(offset + size)


def _fetch_paginated_pass(cfg: ScreenConfig, *, overlap: int):
    page_size = cfg.limit
    if page_size <= 0:
        raise ValueError("Limit/page_size must be > 0")
    if overlap < 0 or overlap >= page_size:
        raise ValueError("PaginationOverlap must satisfy 0 <= overlap < Limit")
    step = page_size - overlap

    pages = []
    totals_seen: list[int] = []
    page_ranges: list[tuple[int, int]] = []
    issues: list[str] = []
    raw_rows = 0
    expected_total: int | None = None

    offset = 0
    while expected_total is None or offset < expected_total:
        total, page = build_query(cfg, offset=offset, page_size=page_size).get_scanner_data()
        total = int(total)
        totals_seen.append(total)
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            issues.append(f"totalCount drifted {expected_total}->{total} at offset {offset}")

        expected_rows = min(page_size, max(0, expected_total - offset))
        actual_rows = len(page)
        if actual_rows != expected_rows:
            issues.append(
                f"page {offset}:{offset + page_size} returned {actual_rows} rows, expected {expected_rows}"
            )

        pages.append(page)
        page_ranges.append((offset, offset + page_size))
        raw_rows += actual_rows
        if expected_total == 0:
            break
        offset += step

    if pages:
        merged = pd.concat(pages, ignore_index=True)
    else:
        merged = pd.DataFrame(columns=["ticker", *TV_COLUMNS])

    duplicate_rows = 0
    if "ticker" not in merged.columns:
        issues.append("TradingView response omitted ticker column")
        unique = merged
        ticker_set: frozenset[str] = frozenset()
    else:
        keys = merged["ticker"].astype(str).str.upper()
        duplicate_rows = int(keys.duplicated(keep="first").sum())
        unique = merged.loc[~keys.duplicated(keep="first")].copy()
        unique["ticker"] = unique["ticker"].astype(str).str.upper()
        # Client-side canonicalization makes the downstream order deterministic;
        # completeness is established by the exact ticker set, not server tie order.
        unique = unique.sort_values("ticker", kind="stable").reset_index(drop=True)
        ticker_set = frozenset(unique["ticker"].astype(str))

    expected_total = expected_total or 0
    if len(unique) != expected_total:
        issues.append(f"unique rows {len(unique)} != initial totalCount {expected_total}")

    meta = {
        "pagination": True,
        "page_size": page_size,
        "overlap": overlap,
        "step": step,
        "pages": len(pages),
        "raw_rows": raw_rows,
        "unique_rows": len(unique),
        "duplicate_rows": duplicate_rows,
        "total_count": expected_total,
        "totals_seen": tuple(totals_seen),
        "page_ranges": tuple(page_ranges),
        "stable": not issues,
        "issues": tuple(issues),
    }
    unique.attrs["tradingview_pagination"] = meta
    return expected_total, unique, ticker_set, meta


def fetch_screen(cfg: ScreenConfig):
    if not cfg.paginate:
        total, df = build_query(cfg).get_scanner_data()
        total = int(total)
        issues: list[str] = []
        duplicate_rows = 0

        if "ticker" not in df.columns:
            if cfg.require_complete_universe:
                issues.append("TradingView response omitted ticker column")
        else:
            keys = df["ticker"].astype(str).str.upper()
            duplicate_rows = int(keys.duplicated(keep=False).sum())
            if cfg.require_complete_universe and duplicate_rows:
                issues.append(f"duplicate ticker rows in single response: {duplicate_rows}")

        if cfg.require_complete_universe and len(df) != total:
            hint = f"; configured Limit={cfg.limit}" if total > cfg.limit else ""
            issues.append(f"returned rows {len(df)} != totalCount {total}{hint}")

        if issues:
            raise PaginationStabilityError(
                "TradingView single-shot full-universe fetch was incomplete: " + "; ".join(issues)
            )

        mode = "single_shot_complete" if cfg.require_complete_universe else "single_request"
        df.attrs["tradingview_pagination"] = {
            "pagination": False,
            "mode": mode,
            "range_limit": cfg.limit,
            "pages": 1,
            "raw_rows": len(df),
            "unique_rows": len(df),
            "duplicate_rows": duplicate_rows,
            "total_count": total,
            "totals_seen": (total,),
            "stable": True,
            "issues": (),
            "attempts": 1,
            "require_complete_universe": cfg.require_complete_universe,
        }
        return total, df

    attempts = 1 + cfg.pagination_retries
    last_issues: list[str] = []
    for attempt in range(1, attempts + 1):
        # Increase overlap on retries.  This specifically protects against
        # non-deterministic ordering inside equal-name tie groups.
        overlap = min(cfg.limit - 1, cfg.pagination_overlap * (2 ** (attempt - 1)))
        passes = []
        pass_sets = []
        attempt_issues: list[str] = []
        total_ref: int | None = None

        for pass_no in range(1, cfg.pagination_confirm_passes + 1):
            total, df, ticker_set, meta = _fetch_paginated_pass(cfg, overlap=overlap)
            passes.append((total, df, meta))
            pass_sets.append(ticker_set)
            if not meta["stable"]:
                attempt_issues.extend(f"pass {pass_no}: {x}" for x in meta["issues"])
                break
            if total_ref is None:
                total_ref = total
            elif total != total_ref:
                attempt_issues.append(
                    f"confirmation totalCount drifted {total_ref}->{total} on pass {pass_no}"
                )
                break

        if not attempt_issues and len(pass_sets) == cfg.pagination_confirm_passes:
            ref = pass_sets[0]
            for pass_no, current in enumerate(pass_sets[1:], start=2):
                if current != ref:
                    added = len(current - ref)
                    removed = len(ref - current)
                    attempt_issues.append(
                        f"membership drift between confirmation passes: +{added}/-{removed} on pass {pass_no}"
                    )
                    break

        if not attempt_issues and passes:
            total, df, meta = passes[-1]
            meta = dict(meta)
            meta.update({
                "attempts": attempt,
                "confirmation_passes": cfg.pagination_confirm_passes,
                "overlap": overlap,
            })
            df.attrs["tradingview_pagination"] = meta
            return total, df

        last_issues = attempt_issues or ["unknown pagination instability"]

    detail = "; ".join(last_issues)
    raise PaginationStabilityError(
        f"TradingView full-universe pagination remained unstable after {attempts} attempt(s): {detail}"
    )


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
            isin=(str(record.get("isin")).upper().strip() if record.get("isin") else None),
            active_symbol=_bool_or_none(record.get("active_symbol")),
        ))
    return rows



def probe_identifier_metadata(tickers: list[str]) -> dict[str, dict]:
    """Evidence-only TradingView probe for exact ticker identifiers.

    The normal universe query intentionally relies only on stable, already used
    columns.  CUSIP/FIGI are probed separately because TradingView exposes them
    in the Screener UI but they are not currently listed in the public field
    catalog used by ``tradingview-screener``.  Any unsupported field or network
    failure is returned as diagnostic metadata and can never affect admission.
    """
    requested = list(dict.fromkeys(
        str(x or "").strip().upper() for x in tickers if str(x or "").strip()
    ))
    result = {
        ticker: {
            "requested_ticker": ticker,
            "found": False,
            "active_symbol": None,
            "isin": None,
            "cusip": None,
            "figi": None,
            "field_sources": {},
            "errors": {},
        }
        for ticker in requested
    }
    if not requested:
        return result

    def fetch(columns: tuple[str, ...]):
        query = Query().select(*columns).set_tickers(*requested)
        # Exact ticker diagnostics must not inherit Query()'s is_primary=true
        # default, otherwise secondary German listings can disappear.
        query.query["filter"] = []
        return query.limit(max(50, len(requested))).get_scanner_data()

    core_columns = (
        "name", "description", "exchange", "market", "country", "currency",
        "type", "typespecs", "is_primary", "active_symbol", "isin",
    )
    try:
        _, frame = fetch(core_columns)
    except Exception as exc:  # diagnostic path must never break a production run
        error = f"{type(exc).__name__}: {exc}"
        for item in result.values():
            item["errors"]["core"] = error
        return result

    for record in frame.to_dict(orient="records"):
        ticker = str(record.get("ticker") or "").strip().upper()
        if ticker not in result:
            continue
        item = result[ticker]
        item.update({
            "found": True,
            "name": record.get("description") or record.get("name"),
            "exchange": record.get("exchange"),
            "market": record.get("market"),
            "country": record.get("country"),
            "currency": record.get("currency"),
            "type": record.get("type"),
            "typespecs": record.get("typespecs"),
            "is_primary": _bool_or_none(record.get("is_primary")),
            "active_symbol": _bool_or_none(record.get("active_symbol")),
            "isin": _text_or_none(record.get("isin")),
        })

    # Hidden/authorization-dependent identifier fields are intentionally probed
    # one at a time.  Lowercase matches the existing `isin` field convention;
    # uppercase is a bounded compatibility fallback if the first spelling is
    # rejected by the endpoint.
    for logical, aliases in {"cusip": ("cusip", "CUSIP"), "figi": ("figi", "FIGI")}.items():
        errors = []
        success = False
        for alias in aliases:
            try:
                _, extra = fetch(("name", alias))
            except Exception as exc:
                errors.append(f"{alias}: {type(exc).__name__}: {exc}")
                continue
            success = True
            for record in extra.to_dict(orient="records"):
                ticker = str(record.get("ticker") or "").strip().upper()
                if ticker not in result:
                    continue
                value = _text_or_none(record.get(alias))
                if value:
                    result[ticker][logical] = value
                    result[ticker]["field_sources"][logical] = alias
            break
        if not success and errors:
            for item in result.values():
                item["errors"][logical] = " | ".join(errors)
    return result


def _text_or_none(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    text = str(v).strip()
    return text.upper() if text else None


def _bool_or_none(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    text = str(v).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None

def _float(v):
    try:
        if v is None:
            return None
        return float(v)
    except (TypeError, ValueError):
        return None
