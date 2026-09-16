from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from .cache import CacheDB
from .config import load_screen_config
from .providers import FinnhubProvider, OpenFigiProvider, ProviderError, YahooProvider
from .policy import (
    CROSS_VENUE_BRIDGES,
    GERMANY_REGIONAL_TARGET_MICS,
    ISIN_SHARE_CLASS_BRIDGES,
    TV_PREFIX_TO_MIC,
    YAHOO_HOME_EXCHANGE_TO_MIC,
    currency_compatible,
    openfigi_currency,
    openfigi_type_compatible,
    punctuation_key,
    tv_type_kind,
    yahoo_listing_symbol,
    yahoo_type_compatible,
    yahoo_venue_compatible,
)
from .resolver import BatchResolver
from .tradingview import (
    PaginationStabilityError, dataframe_to_tv_rows, fetch_screen, probe_identifier_metadata,
)


def _load_environment() -> str | None:
    """Load .env from the current working directory or a parent directory."""
    path = find_dotenv(filename=".env", usecwd=True)
    if path:
        load_dotenv(path, override=False)
        return path
    return None


_ENV_FILE = _load_environment()


def _default_cache() -> Path:
    return Path(os.getenv("TV_MARKET_ID_CACHE", Path.home() / ".cache" / "tv-market-identity" / "identity.sqlite3"))


def _make_resolver(cache: CacheDB, args) -> BatchResolver:
    try:
        fh = FinnhubProvider()
    except ProviderError:
        fh = None
    return BatchResolver(
        cache=cache,
        finnhub=fh,
        openfigi=OpenFigiProvider(),
        yahoo=YahooProvider(batch_size=args.yahoo_batch),
        verified_ttl_days=args.verified_ttl_days,
        rejected_ttl_hours=args.rejected_ttl_hours,
        finnhub_ttl_hours=args.finnhub_ttl_hours,
    )


def _write_csv(path: Path, df, bindings: dict) -> None:
    records = []
    for row in df.to_dict(orient="records"):
        tv_id = str(row.get("ticker") or "").upper()
        b = bindings.get(tv_id)
        rec = dict(row)
        if b:
            rec.update({
                "identity_status": b.status,
                "cache_hit": b.cache_hit,
                "resolved_mic": b.resolved_mic,
                "source_mic": b.source_mic,
                "target_mic": b.target_mic,
                "source_venue_code": b.source_venue_code,
                "mapping_method": b.mapping_method,
                "source_venue_figi": b.source_venue_figi,
                "target_venue_figi": b.target_venue_figi,
                "yahoo_symbol": b.yahoo_symbol,
                "yahoo_exchange": b.yahoo_exchange,
                "yahoo_market": b.yahoo_market,
                "yahoo_quote_type": b.yahoo_quote_type,
                "yahoo_currency": b.yahoo_currency,
                "yahoo_price": b.yahoo_price,
                "yahoo_delayed_by": b.yahoo_delayed_by,
                "quote_status": b.quote_status,
                "finnhub_symbol": b.finnhub_symbol,
                "finnhub_type": b.finnhub_type,
                "composite_figi": b.composite_figi,
                "share_class_figi": b.share_class_figi,
                "venue_figi": b.venue_figi,
                "rejection_reason": b.rejection_reason,
                "identity_fingerprint": b.fingerprint,
            })
        records.append(rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not records:
        path.write_text("", encoding="utf-8")
        return
    fields = list(records[0].keys())
    for r in records[1:]:
        for k in r:
            if k not in fields:
                fields.append(k)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(records)



def _audit_yahoo_symbol_identity_keys(symbol: str | None) -> set[str]:
    """Mirror the bounded home-market ticker normalization for diagnostics only."""
    value = str(symbol or "").upper().strip()
    if not value:
        return set()
    keys = {punctuation_key(value)}
    if "." in value:
        root, suffix = value.rsplit(".", 1)
        if root and 1 <= len(suffix) <= 4 and suffix.isalnum():
            keys.add(punctuation_key(root))
    return {x for x in keys if x}


def _audit_home_quote_contract(candidate, quote) -> tuple[bool, list[str]]:
    """Explain the strict v0.3.59 home-market Yahoo quote contract."""
    blocks: list[str] = []
    if (candidate.quote_type or "").upper() != "EQUITY":
        blocks.append(f"SEARCH_TYPE_MISMATCH:{candidate.quote_type}")
    if quote is None:
        blocks.append("QUOTE_NOT_RETURNED")
        return False, blocks
    if quote.symbol != candidate.symbol:
        blocks.append(f"SYMBOL_MISMATCH:{quote.symbol}")
    if (quote.quote_type or "").upper() != "EQUITY":
        blocks.append(f"QUOTE_TYPE_MISMATCH:{quote.quote_type}")
    if not quote.currency:
        blocks.append("CURRENCY_UNREPORTED")
    if not quote.exchange:
        blocks.append("EXCHANGE_UNREPORTED")
    if candidate.exchange and quote.exchange and candidate.exchange.upper() != quote.exchange.upper():
        blocks.append(f"EXCHANGE_MISMATCH:{candidate.exchange}/{quote.exchange}")
    return not blocks, blocks


def _write_rejection_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Write evidence-only JSONL for rejected German rows.

    This never changes admission.  It re-probes exact TradingView ISIN across
    the row's source venue(s) and bounded German regional MICs, then records
    OpenFIGI identity metadata plus the corresponding Yahoo quote metadata.
    """
    rejected_rows = [
        r for r in rows
        if (b := bindings.get(r.tv_id)) is not None and b.status == "REJECTED"
    ]

    # v0.3.63 diagnostic-only TradingView reference-data probe.  This is kept
    # outside resolver admission so unsupported/lagging CUSIP/FIGI fields can
    # never turn a reject into a verified binding or break the main universe
    # acquisition.  `active_symbol` comes from the normal snapshot as well.
    tv_identifier_probe = probe_identifier_metadata([r.tv_id for r in rejected_rows])

    # Diagnostic-only exact-ISIN lookup without a MIC.  This does not affect
    # admission.  It exposes the global/home-market OpenFIGI identities needed
    # to design a future deterministic Yahoo home-listing fallback.  Batch the
    # jobs so an authenticated provider can fetch the whole residual set in one
    # request, and let OpenFigiProvider's run memo eliminate jobs the resolver
    # already issued earlier in the same run.
    unscoped_by_tv = {}
    unscoped_rows = [r for r in rejected_rows if r.isin]
    if unscoped_rows:
        jobs = [{"idType": "ID_ISIN", "idValue": r.isin} for r in unscoped_rows]
        try:
            mapped = resolver.openfigi.map_jobs(jobs)
        except ProviderError:
            mapped = [[] for _ in jobs]
        unscoped_by_tv = {r.tv_id: identities for r, identities in zip(unscoped_rows, mapped)}

    # Diagnostic-only mirror of the exact-ISIN Yahoo home-market discovery.
    # The resolver already attempted this path before rejection; the audit now
    # records the exact search candidates and why each candidate could not be
    # admitted.  This remains evidence-only and cannot change a Binding.
    home_search_by_isin = {}
    home_quotes = {}
    home_charts = {}
    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searchable_isins = set()
    for r in rejected_rows:
        if not r.isin:
            continue
        unscoped = list(unscoped_by_tv.get(r.tv_id, ()))
        compatible = [x for x in unscoped if openfigi_type_compatible(r, x)]
        observed_shares = {x.share_class_figi for x in compatible if x.share_class_figi}
        if compatible and len(observed_shares) == 1:
            searchable_isins.add(str(r.isin).upper().strip())
    if callable(search_fn):
        for isin in sorted(searchable_isins):
            try:
                home_search_by_isin[isin] = list(search_fn(isin))
            except ProviderError:
                home_search_by_isin[isin] = []
        home_symbols = list(dict.fromkeys(
            candidate.symbol
            for candidates in home_search_by_isin.values()
            for candidate in candidates
            if candidate.symbol
        ))
        try:
            home_quotes = resolver.yahoo.quotes(home_symbols) if home_symbols else {}
        except ProviderError:
            home_quotes = {}
        chart_fn = getattr(resolver.yahoo, "chart_quotes", None)
        if callable(chart_fn) and home_symbols:
            chart_needed = []
            by_symbol = {
                candidate.symbol: candidate
                for candidates in home_search_by_isin.values()
                for candidate in candidates
            }
            for symbol in home_symbols:
                candidate = by_symbol[symbol]
                quote = home_quotes.get(symbol)
                valid, blocks = _audit_home_quote_contract(candidate, quote)
                explicit = any(
                    block.startswith("SEARCH_TYPE_MISMATCH:")
                    or block.startswith("QUOTE_TYPE_MISMATCH:")
                    or block.startswith("EXCHANGE_MISMATCH:")
                    for block in blocks
                )
                if not valid and not explicit:
                    chart_needed.append(symbol)
            if chart_needed:
                try:
                    home_charts = chart_fn(list(dict.fromkeys(chart_needed)))
                except ProviderError:
                    home_charts = {}

    # v0.3.62 diagnostic mirror of targeted exact-ISIN + home-MIC proof.
    # This is evidence-only: it records whether OpenFIGI can prove that the
    # exact TradingView ISIN exists on the reviewed Yahoo home venue and which
    # shareClassFIGI values are returned there.
    home_isin_mic_by_key = {}
    home_isin_mic_keys = []
    seen_home_isin_mic_keys = set()
    for isin, candidates in home_search_by_isin.items():
        for candidate in candidates:
            home_mic = YAHOO_HOME_EXCHANGE_TO_MIC.get((candidate.exchange or "").upper())
            if not home_mic:
                continue
            key = (isin, home_mic)
            if key not in seen_home_isin_mic_keys:
                seen_home_isin_mic_keys.add(key)
                home_isin_mic_keys.append(key)
    if home_isin_mic_keys:
        jobs = [
            {"idType": "ID_ISIN", "idValue": isin, "micCode": mic}
            for isin, mic in home_isin_mic_keys
        ]
        try:
            mapped = resolver.openfigi.map_jobs(jobs)
        except ProviderError:
            mapped = [[] for _ in jobs]
        home_isin_mic_by_key = {
            key: list(identities) for key, identities in zip(home_isin_mic_keys, mapped)
        }

    records = []
    for r in rejected_rows:
        b = bindings[r.tv_id]
        source_mics = []
        direct = TV_PREFIX_TO_MIC.get(r.prefix)
        if direct:
            source_mics.append(direct)
        bridge = ISIN_SHARE_CLASS_BRIDGES.get(r.prefix)
        if bridge:
            source_mics.extend(bridge.get("source_mics", ()))
        cross = CROSS_VENUE_BRIDGES.get(r.prefix)
        if cross:
            source_mics.extend(cross.get("source_mics", ()))

        probe_mics = []
        for mic in [*source_mics, *GERMANY_REGIONAL_TARGET_MICS]:
            if mic and mic not in probe_mics:
                probe_mics.append(mic)

        evidence = []
        if r.isin:
            jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic} for mic in probe_mics]
            try:
                mapped = resolver.openfigi.map_jobs(jobs)
            except ProviderError:
                mapped = [[] for _ in jobs]

            yahoo_symbols = set()
            staged = []
            for mic, identities in zip(probe_mics, mapped):
                for x in identities:
                    symbol = yahoo_listing_symbol(x.ticker or r.symbol, mic, r.prefix, tv_type_kind(r))
                    yahoo_symbols.add(symbol)
                    staged.append((mic, x, symbol))
            try:
                quotes = resolver.yahoo.quotes(sorted(yahoo_symbols)) if yahoo_symbols else {}
            except ProviderError:
                quotes = {}

            for mic, x, symbol in staged:
                q = quotes.get(symbol)
                ordinary_blocks = []
                if q is None:
                    ordinary_blocks.append("YAHOO_NOT_RETURNED")
                else:
                    if q.currency is not None and not currency_compatible(r.currency, q.currency):
                        ordinary_blocks.append(f"CURRENCY_MISMATCH:{q.currency}")
                    if q.quote_type is not None and not yahoo_type_compatible(r, q.quote_type):
                        ordinary_blocks.append(f"TYPE_MISMATCH:{q.quote_type}")
                    if not yahoo_venue_compatible(mic, q):
                        ordinary_blocks.append(
                            f"VENUE_MISMATCH:{q.exchange}/{q.full_exchange_name}/{q.market}"
                        )
                evidence.append({
                    "mic": mic,
                    "role": "source" if mic in source_mics else "regional_target",
                    "figi": x.figi,
                    "composite_figi": x.composite_figi,
                    "share_class_figi": x.share_class_figi,
                    "openfigi_ticker": x.ticker,
                    "openfigi_name": x.name,
                    "openfigi_security_type": x.security_type,
                    "openfigi_security_type2": x.security_type2,
                    "openfigi_exch_code": x.exch_code,
                    "yahoo_symbol": symbol,
                    "yahoo_returned": q is not None,
                    "yahoo_exchange": q.exchange if q else None,
                    "yahoo_full_exchange_name": q.full_exchange_name if q else None,
                    "yahoo_market": q.market if q else None,
                    "yahoo_quote_type": q.quote_type if q else None,
                    "yahoo_currency": q.currency if q else None,
                    "yahoo_price": q.price if q else None,
                    "ordinary_contract_blocks": ordinary_blocks,
                })

        unscoped = list(unscoped_by_tv.get(r.tv_id, ()))
        unscoped_shares = sorted({x.share_class_figi for x in unscoped if x.share_class_figi})
        if not unscoped:
            unscoped_status = "UNKNOWN"
        elif not unscoped_shares:
            unscoped_status = "SHARE_CLASS_MISSING"
        elif len(unscoped_shares) > 1:
            unscoped_status = "AMBIGUOUS_SHARE_CLASS"
        elif any(not x.share_class_figi for x in unscoped):
            unscoped_status = "PARTIAL_SHARE_CLASS"
        else:
            unscoped_status = "UNIQUE_SHARE_CLASS"

        home_market_search_candidates = []
        home_market_audit_status = "NOT_ATTEMPTED"
        if r.isin and callable(search_fn):
            isin_key = str(r.isin).upper().strip()
            compatible_unscoped = [x for x in unscoped if openfigi_type_compatible(r, x)]
            observed_shares = {x.share_class_figi for x in compatible_unscoped if x.share_class_figi}
            if not compatible_unscoped:
                home_market_audit_status = "NO_COMPATIBLE_OPENFIGI_IDENTITY"
            elif not observed_shares:
                home_market_audit_status = "SHARE_CLASS_MISSING"
            elif len(observed_shares) != 1:
                home_market_audit_status = "SHARE_CLASS_AMBIGUOUS"
            else:
                share = next(iter(observed_shares))
                candidates = home_search_by_isin.get(isin_key, ())
                home_market_audit_status = "NO_YAHOO_SEARCH_CANDIDATES" if not candidates else "CANDIDATES_RECORDED"
                for candidate in candidates:
                    keys = _audit_yahoo_symbol_identity_keys(candidate.symbol)
                    matched = [
                        x for x in compatible_unscoped
                        if x.share_class_figi == share and x.ticker and punctuation_key(x.ticker) in keys
                    ]
                    home_mic = YAHOO_HOME_EXCHANGE_TO_MIC.get((candidate.exchange or "").upper())
                    targeted_identities = list(
                        home_isin_mic_by_key.get((isin_key, home_mic), ()) if home_mic else ()
                    )
                    targeted_compatible = [
                        x for x in targeted_identities if openfigi_type_compatible(r, x)
                    ]
                    targeted_share_matches = [
                        x for x in targeted_compatible if x.share_class_figi == share
                    ]
                    targeted_conflicting_shares = sorted({
                        x.share_class_figi for x in targeted_compatible
                        if x.share_class_figi and x.share_class_figi != share
                    })
                    identity_confirmed = bool(matched) or (
                        bool(targeted_share_matches) and not targeted_conflicting_shares
                    )
                    quote = home_quotes.get(candidate.symbol)
                    quote_valid, quote_blocks = _audit_home_quote_contract(candidate, quote)
                    chart = home_charts.get(candidate.symbol)
                    chart_valid, chart_blocks = _audit_home_quote_contract(candidate, chart)
                    explicit_quote_contradiction = any(
                        block.startswith("SEARCH_TYPE_MISMATCH:")
                        or block.startswith("QUOTE_TYPE_MISMATCH:")
                        or block.startswith("EXCHANGE_MISMATCH:")
                        for block in quote_blocks
                    )
                    effective_quote_valid = quote_valid or (not explicit_quote_contradiction and chart_valid)
                    effective_quote_source = (
                        "quote" if quote_valid else "chart" if (not explicit_quote_contradiction and chart_valid) else None
                    )
                    candidate_blocks = []
                    if (candidate.quote_type or "").upper() != "EQUITY":
                        candidate_blocks.append(f"SEARCH_TYPE_MISMATCH:{candidate.quote_type}")
                    if not identity_confirmed:
                        if targeted_conflicting_shares:
                            candidate_blocks.append("OPENFIGI_HOME_MIC_SHARE_CONFLICT")
                        else:
                            candidate_blocks.append("OPENFIGI_HOME_LISTING_UNCONFIRMED")
                    if not effective_quote_valid:
                        candidate_blocks.extend(quote_blocks)
                        if chart is not None and not explicit_quote_contradiction:
                            candidate_blocks.extend(f"CHART_{block}" for block in chart_blocks)
                    candidate_blocks = list(dict.fromkeys(candidate_blocks))
                    home_market_search_candidates.append({
                        "symbol": candidate.symbol,
                        "exchange": candidate.exchange,
                        "quote_type": candidate.quote_type,
                        "short_name": candidate.short_name,
                        "long_name": candidate.long_name,
                        "identity_keys": sorted(keys),
                        "expected_share_class_figi": share,
                        "openfigi_ticker_confirmed": bool(matched),
                        "matched_openfigi_tickers": sorted({x.ticker for x in matched if x.ticker}),
                        "home_mic": home_mic,
                        "targeted_isin_mic_share_confirmed": bool(targeted_share_matches) and not targeted_conflicting_shares,
                        "targeted_isin_mic_conflicting_share_class_figis": targeted_conflicting_shares,
                        "targeted_isin_mic_openfigi": [
                            {
                                "figi": x.figi,
                                "composite_figi": x.composite_figi,
                                "share_class_figi": x.share_class_figi,
                                "ticker": x.ticker,
                                "name": x.name,
                                "security_type": x.security_type,
                                "security_type2": x.security_type2,
                                "exch_code": x.exch_code,
                            }
                            for x in targeted_identities
                        ],
                        "quote_returned": quote is not None,
                        "quote_exchange": quote.exchange if quote else None,
                        "quote_full_exchange_name": quote.full_exchange_name if quote else None,
                        "quote_market": quote.market if quote else None,
                        "quote_type_returned": quote.quote_type if quote else None,
                        "quote_currency": quote.currency if quote else None,
                        "quote_price": quote.price if quote else None,
                        "quote_contract_valid": quote_valid,
                        "quote_contract_blocks": quote_blocks,
                        "chart_returned": chart is not None,
                        "chart_exchange": chart.exchange if chart else None,
                        "chart_quote_type": chart.quote_type if chart else None,
                        "chart_currency": chart.currency if chart else None,
                        "chart_contract_valid": chart_valid,
                        "chart_contract_blocks": chart_blocks,
                        "effective_quote_source": effective_quote_source,
                        "resolver_candidate_valid": identity_confirmed and effective_quote_valid and (candidate.quote_type or "").upper() == "EQUITY",
                        "admission_blocks": candidate_blocks,
                    })

        records.append({
            "tv_id": r.tv_id,
            "ticker": r.symbol,
            "name": r.name,
            "currency": r.currency,
            "type": r.tv_type,
            "typespecs": list(r.type_specs),
            "isin": r.isin,
            "active_symbol": r.active_symbol,
            "tradingview_identifier_probe": tv_identifier_probe.get(r.tv_id, {}),
            "rejection_reason": b.rejection_reason,
            "resolved_mic": b.resolved_mic,
            "source_mic": b.source_mic,
            "target_mic": b.target_mic,
            "mapping_method": b.mapping_method,
            "yahoo_symbol": b.yahoo_symbol,
            "source_probe_mics": source_mics,
            "evidence": evidence,
            "unscoped_openfigi_status": unscoped_status,
            "unscoped_share_class_figis": unscoped_shares,
            "home_market_audit_status": home_market_audit_status,
            "home_market_search_candidates": home_market_search_candidates,
            "unscoped_openfigi": [
                {
                    "figi": x.figi,
                    "composite_figi": x.composite_figi,
                    "share_class_figi": x.share_class_figi,
                    "ticker": x.ticker,
                    "name": x.name,
                    "security_type": x.security_type,
                    "security_type2": x.security_type2,
                    "exch_code": x.exch_code,
                }
                for x in unscoped
            ],
        })

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")



def _print_tradingview_pagination(df) -> None:
    meta = getattr(df, "attrs", {}).get("tradingview_pagination", {})
    if meta.get("mode") == "single_shot_complete":
        print(
            "TradingView full-universe single-shot: "
            f"range_limit={meta.get('range_limit')}, returned={meta.get('raw_rows')}, "
            f"unique_rows={meta.get('unique_rows')}, duplicate_rows={meta.get('duplicate_rows')}, "
            f"totalCount={meta.get('total_count')}"
        )
        return
    if not meta.get("pagination"):
        return
    print(
        "TradingView pagination: "
        f"pages={meta.get('pages')}, page_size={meta.get('page_size')}, "
        f"overlap={meta.get('overlap')}, confirm_passes={meta.get('confirmation_passes')}, "
        f"attempts={meta.get('attempts')}, raw_rows={meta.get('raw_rows')}, "
        f"unique_rows={meta.get('unique_rows')}, duplicate_observations={meta.get('duplicate_rows')}, "
        f"totalCount={meta.get('total_count')}"
    )

def cmd_run(args) -> int:
    cfg = load_screen_config(args.config)
    if cfg.paginate:
        mode = f"page_size={cfg.limit}, paginate=true"
    elif cfg.require_complete_universe:
        mode = f"limit={cfg.limit}, full=single-shot"
    else:
        mode = f"limit={cfg.limit}"
    print(f"TradingView: market={cfg.market}, {mode}, order={cfg.order_by} {'ASC' if cfg.ascending else 'DESC'}")
    filter_parts = []
    if cfg.min_market_cap is not None:
        filter_parts.append(f"cap>{cfg.min_market_cap:g}")
    if cfg.min_avg_volume_90d is not None:
        filter_parts.append(f"avgVol90>{cfg.min_avg_volume_90d:g}")
    if cfg.min_pe is not None:
        filter_parts.append(f"PE>{cfg.min_pe:g}")
    if cfg.sectors:
        filter_parts.append(f"sectors={len(cfg.sectors)}")
    if cfg.primary_only:
        filter_parts.append("primaryOnly=true")
    print("Filters: " + (", ".join(filter_parts) if filter_parts else "market only"))
    try:
        total, df = fetch_screen(cfg)
    except PaginationStabilityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4
    _print_tradingview_pagination(df)
    rows = dataframe_to_tv_rows(df)
    print(f"TradingView returned {len(df)} rows (totalCount={total}); resolvable rows={len(rows)}")
    if total > len(df):
        print(f"WARNING: TradingView result truncated: returned {len(df)} of totalCount={total} (Limit={cfg.limit})")

    cache = CacheDB(args.cache)
    try:
        resolver = _make_resolver(cache, args)
        bindings = resolver.resolve(rows, refresh=args.refresh, refresh_rejected=args.refresh_rejected)
        resolver.refresh_cached_quotes(bindings)
        verified = sum(1 for b in bindings.values() if b.status == "VERIFIED")
        rejected = sum(1 for b in bindings.values() if b.status == "REJECTED")
        hits = sum(1 for b in bindings.values() if b.cache_hit)
        print(f"Identity: VERIFIED={verified}, REJECTED={rejected}, CACHE_HIT={hits}")
        reasons = Counter(
            b.rejection_reason for b in bindings.values()
            if b.status == "REJECTED" and b.rejection_reason
        )
        if reasons:
            print("Rejection reasons:")
            for reason, count in reasons.most_common(20):
                print(f"  {count:4d}  {reason}")
            unknown_prefixes = Counter(
                b.tv_prefix for b in bindings.values()
                if b.status == "REJECTED" and b.rejection_reason == "MIC_UNKNOWN"
            )
            if unknown_prefixes:
                print("Unknown TV prefixes:")
                for prefix, count in unknown_prefixes.most_common():
                    print(f"  {count:4d}  {prefix}")
        special_types = Counter(
            b.finnhub_type for b in bindings.values()
            if b.status == "VERIFIED"
            and b.finnhub_type
            and b.finnhub_type.lower() != "common stock"
        )
        if special_types:
            print("Verified equity subtypes (identity only):")
            for subtype, count in special_types.most_common():
                print(f"  {count:4d}  {subtype}")
        print("Resolver stats:", json.dumps(dict(resolver.stats), sort_keys=True))
        _write_csv(Path(args.output), df, bindings)
        print(f"CSV: {Path(args.output).resolve()}")
        if args.rejection_audit:
            audit_path = Path(args.rejection_audit)
            _write_rejection_audit(audit_path, rows, bindings, resolver)
            print(f"Rejection audit: {audit_path.resolve()}")
        return 3 if (args.strict_exit and rejected) else 0
    finally:
        cache.close()


def cmd_screen(args) -> int:
    cfg = load_screen_config(args.config)
    try:
        total, df = fetch_screen(cfg)
    except PaginationStabilityError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 4
    _print_tradingview_pagination(df)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"TradingView rows={len(df)}, totalCount={total}, CSV={path.resolve()}")
    return 0


def cmd_cache_stats(args) -> int:
    cache = CacheDB(args.cache)
    try:
        print(json.dumps(cache.stats(), indent=2, sort_keys=True))
        return 0
    finally:
        cache.close()


def cmd_cache_clear(args) -> int:
    cache = CacheDB(args.cache)
    try:
        cache.clear()
        print(f"Cleared {Path(args.cache).resolve()}")
        return 0
    finally:
        cache.close()



def cmd_doctor(args) -> int:
    print(f".env: {_ENV_FILE or 'not found'}")
    print(f"FINNHUB_API_KEY: {'set' if os.getenv('FINNHUB_API_KEY') else 'MISSING'}")
    print(f"OPENFIGI_API_KEY: {'set' if os.getenv('OPENFIGI_API_KEY') else 'not set (optional)'}")
    cache = CacheDB(args.cache)
    try:
        print("Cache:", json.dumps(cache.stats(), sort_keys=True))
    finally:
        cache.close()
    return 0 if os.getenv("FINNHUB_API_KEY") else 2




def cmd_diagnose_tradegate(args) -> int:
    """Evidence-only diagnostic for a Tradegate -> Xetra/Yahoo bridge.

    TradingView's TRADEGATE prefix does not identify whether the listing is on
    XGAT or XGRM.  Query both Tradegate segment MICs (plus the TGAT operating
    MIC for visibility), then compare their OpenFIGI shareClassFIGI with the
    Xetra listing before considering Yahoo's .DE symbol.
    """
    of = OpenFigiProvider()
    yh = YahooProvider(batch_size=10)
    sec_type2 = args.security_type2
    mics = ["TGAT", "XGAT", "XGRM", "XETR"]
    jobs = [
        {
            "idType": "ID_EXCH_SYMBOL",
            "idValue": args.symbol,
            "micCode": mic,
            "currency": args.currency,
            "securityType2": sec_type2,
        }
        for mic in mics
    ]
    mapped = of.map_jobs(jobs)
    print(f"Tradegate diagnostic: symbol={args.symbol}, currency={args.currency}, securityType2={sec_type2}")
    by_mic = {}
    for mic, identities in zip(mics, mapped):
        rows = []
        for x in identities:
            if (x.ticker or "").upper() != args.symbol.upper():
                continue
            rows.append({
                "figi": x.figi,
                "compositeFIGI": x.composite_figi,
                "shareClassFIGI": x.share_class_figi,
                "ticker": x.ticker,
                "name": x.name,
                "securityType": x.security_type,
                "securityType2": x.security_type2,
                "exchCode": x.exch_code,
            })
        by_mic[mic] = rows
        print(f"\n{mic}: {len(rows)} exact result(s)")
        print(json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=True))

    source_rows = [x for mic in ("TGAT", "XGAT", "XGRM") for x in by_mic[mic]]
    target_rows = by_mic["XETR"]
    source_sc = {x["shareClassFIGI"] for x in source_rows if x.get("shareClassFIGI")}
    target_sc = {x["shareClassFIGI"] for x in target_rows if x.get("shareClassFIGI")}
    overlap = source_sc & target_sc
    print("\nShare-class evidence:")
    print("  Tradegate:", sorted(source_sc))
    print("  Xetra    :", sorted(target_sc))
    print("  overlap  :", sorted(overlap))

    quotes = yh.quotes([args.yahoo_symbol])
    q = quotes.get(args.yahoo_symbol)
    if q:
        print("\nYahoo:")
        print(json.dumps({
            "symbol": q.symbol,
            "exchange": q.exchange,
            "fullExchangeName": q.full_exchange_name,
            "currency": q.currency,
            "quoteType": q.quote_type,
            "market": q.market,
            "price": q.price,
        }, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"\nYahoo: {args.yahoo_symbol} not returned")

    yahoo_ok = bool(q and (q.currency or "").upper() == args.currency.upper() and (q.quote_type or "").upper() == "EQUITY")
    if overlap and yahoo_ok:
        print("\nCROSS_VENUE_SECURITY_MATCH")
        return 0
    print("\nUNRESOLVED")
    return 3


def cmd_diagnose_lsin(args) -> int:
    """Evidence-only LSIN -> XLON/Yahoo .L/.IL diagnostic."""
    from .policy import punctuation_key, yahoo_listing_symbol, yahoo_listing_alternative_symbol, yahoo_venue_compatible
    of = OpenFigiProvider()
    yh = YahooProvider(batch_size=10)
    job = {
        "idType": "ID_EXCH_SYMBOL",
        "idValue": args.symbol,
        "micCode": "XLON",
        "currency": openfigi_currency(args.currency),
        "securityType2": args.security_type2,
    }
    rows = of.map_jobs([job])[0]
    exact=[]
    for x in rows:
        if punctuation_key(x.ticker or "") != punctuation_key(args.symbol):
            continue
        exact.append({
            "figi": x.figi, "compositeFIGI": x.composite_figi,
            "shareClassFIGI": x.share_class_figi, "ticker": x.ticker,
            "name": x.name, "securityType": x.security_type,
            "securityType2": x.security_type2, "exchCode": x.exch_code,
        })
    print(f"LSIN diagnostic: symbol={args.symbol}, TV currency={args.currency}, OpenFIGI currency={openfigi_currency(args.currency)}")
    print(f"\nOpenFIGI micCode=XLON: {len(exact)} exact result(s)")
    print(json.dumps(exact, indent=2, ensure_ascii=False, sort_keys=True))
    primary = args.yahoo_symbol or yahoo_listing_symbol(args.symbol, "XLON", "LSIN", args.kind)
    alternate = None if args.yahoo_symbol else yahoo_listing_alternative_symbol(args.symbol, "XLON", "LSIN", args.kind)
    candidates = [primary] + ([alternate] if alternate and alternate != primary else [])
    quotes = yh.quotes(candidates)
    yahoo_ok = False
    matched_symbol = None
    for candidate in candidates:
        q = quotes.get(candidate)
        if q:
            print(f"\nYahoo candidate {candidate}:")
            print(json.dumps({
                "symbol":q.symbol,"exchange":q.exchange,"fullExchangeName":q.full_exchange_name,
                "currency":q.currency,"quoteType":q.quote_type,"market":q.market,"price":q.price,
            }, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print(f"\nYahoo candidate {candidate}: not returned")
        candidate_ok = bool(q and currency_compatible(args.currency,q.currency) and (q.quote_type or "").upper()=="EQUITY" and yahoo_venue_compatible("XLON", q))
        if candidate_ok and not yahoo_ok:
            yahoo_ok = True
            matched_symbol = candidate
    if len(exact)==1 and yahoo_ok:
        print(f"\nDIRECT_XLON_MATCH: {matched_symbol}")
        return 0
    print("\nUNRESOLVED")
    return 3



def cmd_diagnose_openfigi(args) -> int:
    """Print an OpenFIGI mapping matrix without changing resolver policy."""
    of = OpenFigiProvider()
    currencies = [x.strip() for x in args.currencies.split(",") if x.strip()]
    types = [x.strip() for x in args.security_types.split(",")]
    jobs=[]
    labels=[]
    for currency in currencies:
        for sec_type in types:
            job={
                "idType":"ID_EXCH_SYMBOL",
                "idValue":args.symbol,
                "micCode":args.mic,
                "currency":currency,
            }
            if sec_type:
                job["securityType2"]=sec_type
            jobs.append(job)
            labels.append((currency, sec_type or "<none>"))
    mapped=of.map_jobs(jobs)
    print(f"OpenFIGI matrix: symbol={args.symbol}, mic={args.mic}")
    for (currency, sec_type), identities in zip(labels, mapped):
        rows=[]
        for x in identities:
            rows.append({
                "figi":x.figi,"compositeFIGI":x.composite_figi,
                "shareClassFIGI":x.share_class_figi,"ticker":x.ticker,
                "name":x.name,"securityType":x.security_type,
                "securityType2":x.security_type2,"exchCode":x.exch_code,
            })
        print(f"\ncurrency={currency}, securityType2={sec_type}: {len(rows)} result(s)")
        print(json.dumps(rows, indent=2, ensure_ascii=False, sort_keys=True))
    return 0

def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="tv-market-id", description="Batch TV/Finnhub/OpenFIGI/Yahoo identity prototype")
    p.add_argument("--cache", default=str(_default_cache()), help="SQLite persistent cache path")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--config", default="config/garp_largecap.ini")
        sp.add_argument("--output", default="out/resolved.csv")

    s = sub.add_parser("screen", help="Run only TradingView screener")
    common(s)
    s.set_defaults(func=cmd_screen)

    r = sub.add_parser("run", help="Run TradingView + persistent identity resolution")
    common(r)
    r.add_argument("--refresh", action="store_true", help="Ignore binding cache and resolve again")
    r.add_argument(
        "--refresh-rejected",
        action="store_true",
        help="Reuse cached VERIFIED bindings but re-resolve cached REJECTED bindings",
    )
    r.add_argument(
        "--rejection-audit",
        default=None,
        help="Write evidence-only JSONL for rejected rows (exact ISIN/OpenFIGI + bounded German Yahoo probes)",
    )
    r.add_argument("--strict-exit", action="store_true", help="Return exit code 3 when any instrument is REJECTED")
    r.add_argument("--yahoo-batch", type=int, default=75)
    r.add_argument("--verified-ttl-days", type=int, default=60)
    r.add_argument("--rejected-ttl-hours", type=int, default=6)
    r.add_argument("--finnhub-ttl-hours", type=int, default=24)
    r.set_defaults(func=cmd_run)

    cs = sub.add_parser("cache-stats", help="Show persistent cache statistics")
    cs.set_defaults(func=cmd_cache_stats)
    cc = sub.add_parser("cache-clear", help="Clear persistent cache")
    cc.set_defaults(func=cmd_cache_clear)
    d = sub.add_parser("doctor", help="Check .env/API credentials/cache state")
    d.set_defaults(func=cmd_doctor)

    tg = sub.add_parser("diagnose-tradegate", help="Compare Tradegate and Xetra share-class identity via OpenFIGI")
    tg.add_argument("--symbol", default="DTE")
    tg.add_argument("--currency", default="EUR")
    tg.add_argument("--security-type2", default="Common Stock")
    tg.add_argument("--yahoo-symbol", default="DTE.DE")
    tg.set_defaults(func=cmd_diagnose_tradegate)

    ls = sub.add_parser("diagnose-lsin", help="Verify TradingView LSIN against OpenFIGI XLON and Yahoo .L/.IL")
    ls.add_argument("--symbol", default="0Q0Y")
    ls.add_argument("--currency", default="EUR")
    ls.add_argument("--security-type2", default="Common Stock")
    ls.add_argument("--kind", choices=("STOCK", "ADR", "ETF", "PREFERRED"), default="STOCK")
    ls.add_argument("--yahoo-symbol", default=None)
    ls.set_defaults(func=cmd_diagnose_lsin)

    og = sub.add_parser("diagnose-openfigi", help="Run an OpenFIGI currency/type matrix for one exact listing")
    og.add_argument("--symbol", required=True)
    og.add_argument("--mic", required=True)
    og.add_argument("--currencies", default="GBp,GBP")
    og.add_argument("--security-types", default="Common Stock,")
    og.set_defaults(func=cmd_diagnose_openfigi)
    return p


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
