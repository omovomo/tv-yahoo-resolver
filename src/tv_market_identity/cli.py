from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from . import __version__
from .cache import CacheDB
from .config import load_screen_config
from .providers import FinnhubProvider, OpenFigiProvider, ProviderError, YahooProvider
from .policy import (
    CROSS_VENUE_BRIDGES,
    GERMANY_REGIONAL_TARGET_MICS,
    ISIN_SHARE_CLASS_BRIDGES,
    TV_PREFIX_TO_MIC,
    TV_PREFIX_ALLOWED_MICS,
    bounded_symbol_variants,
    YAHOO_HOME_EXCHANGE_TO_MIC,
    currency_compatible,
    openfigi_currency,
    openfigi_type_compatible,
    punctuation_key,
    symbol_index_keys,
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
    """Write evidence-only JSONL for rejected rows.

    This never changes admission. Structural failures such as MIC_UNKNOWN are
    intentionally kept shallow: the TradingView identifier probe is retained,
    but expensive OpenFIGI/Yahoo route diagnostics are skipped because the
    unresolved source venue is already the terminal evidence gap.
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
    unscoped_rows = [
        r for r in rejected_rows
        if r.isin and (bindings[r.tv_id].rejection_reason or "") != "MIC_UNKNOWN"
    ]
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

    # v0.3.69 diagnostic-only US preferred same-venue proof.  Finnhub may
    # report listed preferred series as the coarse labels PUBLIC or ?.  For
    # rejected TV stock/preferred rows, independently test whether exact ISIN
    # + reviewed source MIC proves a Preferred Stock instrument, then discover
    # Yahoo candidates by exact ISIN and validate only candidates whose quote
    # contract points back to that same source venue.  This evidence never
    # changes admission or cache semantics.
    preferred_same_venue_by_tv = {}
    preferred_rows = [
        r for r in rejected_rows
        if r.isin
        and tv_type_kind(r) == "PREFERRED"
        and (bindings[r.tv_id].rejection_reason or "").startswith("FINNHUB_TYPE_MISMATCH:")
        and (TV_PREFIX_TO_MIC.get(r.prefix) or "") in {"XNYS", "XNAS"}
    ]
    if preferred_rows:
        preferred_jobs = [
            {"idType": "ID_ISIN", "idValue": r.isin, "micCode": TV_PREFIX_TO_MIC[r.prefix]}
            for r in preferred_rows
        ]
        try:
            preferred_mapped = resolver.openfigi.map_jobs(preferred_jobs)
        except ProviderError:
            preferred_mapped = [[] for _ in preferred_jobs]

        preferred_search = {}
        if callable(search_fn):
            for r in preferred_rows:
                token = str(r.isin).upper().strip()
                if token not in preferred_search:
                    try:
                        preferred_search[token] = list(search_fn(token))
                    except ProviderError:
                        preferred_search[token] = []
        preferred_symbols = list(dict.fromkeys(
            c.symbol for cs in preferred_search.values() for c in cs if c.symbol
        ))
        try:
            preferred_quotes = resolver.yahoo.quotes(preferred_symbols) if preferred_symbols else {}
        except ProviderError:
            preferred_quotes = {}

        # v0.3.70 diagnostic-only: when exact-ISIN Yahoo discovery returns no
        # candidates but exact ISIN + source MIC proves one preferred FIGI,
        # probe the exact TradingView ticker as a Yahoo symbol.  This is not
        # symbol guessing: the symbol is supplied by the source row and Yahoo
        # is used only to validate the same-venue quote contract.
        preferred_source_unique = {}
        for r, identities in zip(preferred_rows, preferred_mapped):
            compatible = [x for x in identities if openfigi_type_compatible(r, x)]
            source_figis = sorted({x.figi for x in compatible if x.figi})
            source_preferred = [
                x for x in compatible
                if (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
                or (x.security_type or "").strip().lower() in {"preferred stock", "preferred", "preference"}
            ]
            preferred_source_unique[r.tv_id] = len(source_figis) == 1 and bool(source_preferred)

        preferred_tv_symbols = list(dict.fromkeys(
            r.symbol for r in preferred_rows
            if preferred_source_unique.get(r.tv_id)
            and not preferred_search.get(str(r.isin).upper().strip(), [])
            and r.symbol
        ))
        try:
            preferred_tv_quotes = resolver.yahoo.quotes(preferred_tv_symbols) if preferred_tv_symbols else {}
        except ProviderError:
            preferred_tv_quotes = {}

        for r, identities in zip(preferred_rows, preferred_mapped):
            source_mic = TV_PREFIX_TO_MIC[r.prefix]
            compatible = [x for x in identities if openfigi_type_compatible(r, x)]
            source_figis = sorted({x.figi for x in compatible if x.figi})
            source_preferred = [
                x for x in compatible
                if (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
                or (x.security_type or "").strip().lower() in {"preferred stock", "preferred", "preference"}
            ]
            source_unique = len(source_figis) == 1 and bool(source_preferred)
            candidates = []
            for c in preferred_search.get(str(r.isin).upper().strip(), []):
                q = preferred_quotes.get(c.symbol)
                blocks = []
                if (c.quote_type or "").upper() != "EQUITY":
                    blocks.append(f"SEARCH_TYPE_MISMATCH:{c.quote_type}")
                if q is None:
                    blocks.append("YAHOO_NOT_RETURNED")
                else:
                    if not yahoo_type_compatible(r, q.quote_type):
                        blocks.append(f"QUOTE_TYPE_MISMATCH:{q.quote_type}")
                    if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                        blocks.append(f"CURRENCY_MISMATCH:{q.currency}")
                    if not yahoo_venue_compatible(source_mic, q):
                        blocks.append(f"VENUE_MISMATCH:{q.exchange}/{q.full_exchange_name}/{q.market}")
                candidates.append({
                    "symbol": c.symbol,
                    "search_exchange": c.exchange,
                    "search_quote_type": c.quote_type,
                    "quote_returned": q is not None,
                    "quote_exchange": q.exchange if q else None,
                    "quote_full_exchange_name": q.full_exchange_name if q else None,
                    "quote_market": q.market if q else None,
                    "quote_type": q.quote_type if q else None,
                    "quote_currency": q.currency if q else None,
                    "same_venue_contract_valid": source_unique and not blocks,
                    "admission_blocks": blocks if source_unique else ["SOURCE_ISIN_MIC_UNCONFIRMED", *blocks],
                })
            tv_q = preferred_tv_quotes.get(r.symbol) if source_unique and not candidates else None
            tv_blocks = []
            if source_unique and not candidates:
                if tv_q is None:
                    tv_blocks.append("YAHOO_NOT_RETURNED")
                else:
                    if not yahoo_type_compatible(r, tv_q.quote_type):
                        tv_blocks.append(f"QUOTE_TYPE_MISMATCH:{tv_q.quote_type}")
                    if r.currency and tv_q.currency and not currency_compatible(r.currency, tv_q.currency):
                        tv_blocks.append(f"CURRENCY_MISMATCH:{tv_q.currency}")
                    if not yahoo_venue_compatible(source_mic, tv_q):
                        tv_blocks.append(f"VENUE_MISMATCH:{tv_q.exchange}/{tv_q.full_exchange_name}/{tv_q.market}")
            tv_probe_attempted = source_unique and not candidates
            preferred_same_venue_by_tv[r.tv_id] = {
                "attempted": True,
                "source_mic": source_mic,
                "source_isin_mic_status": (
                    "UNIQUE_PREFERRED_FIGI" if source_unique
                    else "NO_MATCH" if not identities
                    else "NO_COMPATIBLE_PREFERRED" if not source_preferred
                    else "AMBIGUOUS_FIGI"
                ),
                "source_figis": source_figis,
                "source_openfigi": [
                    {
                        "figi": x.figi, "composite_figi": x.composite_figi,
                        "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                        "name": x.name, "security_type": x.security_type,
                        "security_type2": x.security_type2, "exch_code": x.exch_code,
                    } for x in identities
                ],
                "yahoo_exact_isin_candidate_count": len(candidates),
                "same_venue_valid_candidate_count": sum(
                    1 for c in candidates if c["same_venue_contract_valid"]
                ),
                "yahoo_exact_isin_candidates": candidates,
                "yahoo_exact_tv_symbol_probe": {
                    "attempted": tv_probe_attempted,
                    "symbol": r.symbol if tv_probe_attempted else None,
                    "quote_returned": tv_q is not None if tv_probe_attempted else False,
                    "quote_exchange": tv_q.exchange if tv_q else None,
                    "quote_full_exchange_name": tv_q.full_exchange_name if tv_q else None,
                    "quote_market": tv_q.market if tv_q else None,
                    "quote_type": tv_q.quote_type if tv_q else None,
                    "quote_currency": tv_q.currency if tv_q else None,
                    "same_venue_contract_valid": tv_probe_attempted and tv_q is not None and not tv_blocks,
                    "admission_blocks": tv_blocks if tv_probe_attempted else [],
                },
            }

    # v0.3.72 diagnostic-only OTC preferred MIC discovery. TradingView's OTC
    # prefix is deliberately NOT mapped to a MIC. Probe a bounded reviewed set
    # of current US OTC MICs with exact ISIN and record the venue evidence.
    # PINX/PINI are excluded because ISO 10383 lists them as expired in 2026.
    otc_preferred_mic_candidates = ("OTCM", "OTCB", "OOTC", "OTCD")
    otc_preferred_mic_discovery_by_tv = {}
    otc_preferred_rows = [
        r for r in rejected_rows
        if r.prefix == "OTC" and r.isin and tv_type_kind(r) == "PREFERRED"
        and (bindings[r.tv_id].rejection_reason or "").startswith("FINNHUB_TYPE_MISMATCH:")
    ]
    if otc_preferred_rows:
        otc_jobs = [
            {"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic}
            for r in otc_preferred_rows for mic in otc_preferred_mic_candidates
        ]
        try:
            otc_mapped = resolver.openfigi.map_jobs(otc_jobs)
        except ProviderError:
            otc_mapped = [[] for _ in otc_jobs]
        pos = 0
        for r in otc_preferred_rows:
            mic_results, proven_mics = [], []
            for mic in otc_preferred_mic_candidates:
                identities = list(otc_mapped[pos]); pos += 1
                compatible = [x for x in identities if openfigi_type_compatible(r, x)]
                preferred = [x for x in compatible if
                    (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
                    or (x.security_type or "").strip().lower() in {"preferred stock", "preferred", "preference"}]
                figis = sorted({x.figi for x in preferred if x.figi})
                if len(figis) == 1:
                    status = "UNIQUE_PREFERRED_FIGI"; proven_mics.append(mic)
                elif len(figis) > 1:
                    status = "AMBIGUOUS_PREFERRED_FIGI"
                elif identities and not preferred:
                    status = "NO_COMPATIBLE_PREFERRED"
                else:
                    status = "NO_MATCH"
                mic_results.append({
                    "mic": mic, "status": status, "preferred_figis": figis,
                    "openfigi": [{
                        "figi": x.figi, "composite_figi": x.composite_figi,
                        "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                        "name": x.name, "security_type": x.security_type,
                        "security_type2": x.security_type2, "exch_code": x.exch_code,
                    } for x in identities],
                })
            otc_preferred_mic_discovery_by_tv[r.tv_id] = {
                "attempted": True, "candidate_mics": list(otc_preferred_mic_candidates),
                "proven_mics": proven_mics, "proven_mic_count": len(proven_mics),
                "status": "UNIQUE_MIC" if len(proven_mics) == 1 else
                          "MULTIPLE_MICS" if len(proven_mics) > 1 else "NO_PROVEN_MIC",
                "mic_results": mic_results,
            }

    # v0.3.73 diagnostic-only Yahoo discovery for OTC preferred rows whose
    # exact ISIN proves exactly one reviewed OTC MIC.  Deliberately record raw
    # Yahoo venue metadata instead of assuming a Yahoo exchange code -> ISO MIC
    # equivalence.  Type/currency are evaluated independently; venue remains an
    # observation for this experiment and cannot affect admission.
    otc_preferred_yahoo_discovery_by_tv = {}
    otc_unique_rows = [
        r for r in otc_preferred_rows
        if otc_preferred_mic_discovery_by_tv.get(r.tv_id, {}).get("status") == "UNIQUE_MIC"
    ]
    otc_search = {}
    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    if callable(search_fn):
        for r in otc_unique_rows:
            token = str(r.isin).upper().strip()
            if token not in otc_search:
                try:
                    otc_search[token] = list(search_fn(token))
                except ProviderError:
                    otc_search[token] = []
    search_symbols = list(dict.fromkeys(
        c.symbol for cs in otc_search.values() for c in cs if c.symbol
    ))
    try:
        search_quotes = resolver.yahoo.quotes(search_symbols) if search_symbols else {}
    except ProviderError:
        search_quotes = {}
    tv_symbols = list(dict.fromkeys(
        r.symbol for r in otc_unique_rows
        if not otc_search.get(str(r.isin).upper().strip(), []) and r.symbol
    ))
    try:
        tv_quotes = resolver.yahoo.quotes(tv_symbols) if tv_symbols else {}
    except ProviderError:
        tv_quotes = {}

    def _otc_yahoo_quote_record(r, q):
        blocks = []
        if q is None:
            blocks.append("YAHOO_NOT_RETURNED")
        else:
            if not yahoo_type_compatible(r, q.quote_type):
                blocks.append(f"QUOTE_TYPE_MISMATCH:{q.quote_type}")
            if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                blocks.append(f"CURRENCY_MISMATCH:{q.currency}")
        return {
            "quote_returned": q is not None,
            "quote_exchange": q.exchange if q else None,
            "quote_full_exchange_name": q.full_exchange_name if q else None,
            "quote_market": q.market if q else None,
            "quote_type": q.quote_type if q else None,
            "quote_currency": q.currency if q else None,
            "non_venue_contract_valid": q is not None and not blocks,
            "non_venue_blocks": blocks,
        }

    for r in otc_unique_rows:
        diag = otc_preferred_mic_discovery_by_tv[r.tv_id]
        proven_mic = diag["proven_mics"][0]
        token = str(r.isin).upper().strip()
        candidates = []
        for c in otc_search.get(token, []):
            q = search_quotes.get(c.symbol)
            rec = {
                "symbol": c.symbol,
                "search_exchange": c.exchange,
                "search_quote_type": c.quote_type,
                **_otc_yahoo_quote_record(r, q),
            }
            candidates.append(rec)
        tv_probe_attempted = not candidates
        tv_q = tv_quotes.get(r.symbol) if tv_probe_attempted else None
        otc_preferred_yahoo_discovery_by_tv[r.tv_id] = {
            "attempted": True,
            "proven_mic": proven_mic,
            "venue_equivalence_assumed": False,
            "yahoo_exact_isin_candidate_count": len(candidates),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_tv_symbol_probe": {
                "attempted": tv_probe_attempted,
                "symbol": r.symbol if tv_probe_attempted else None,
                **(_otc_yahoo_quote_record(r, tv_q) if tv_probe_attempted else {
                    "quote_returned": False, "quote_exchange": None,
                    "quote_full_exchange_name": None, "quote_market": None,
                    "quote_type": None, "quote_currency": None,
                    "non_venue_contract_valid": False, "non_venue_blocks": [],
                }),
            },
        }

    # v0.3.75 diagnostic-only Yahoo anomaly matrix.  Keep this deliberately
    # independent of admission: it probes exact TV symbol, exact ISIN search,
    # chart metadata, and exact ISIN+source-MIC OpenFIGI evidence for the small
    # residual Yahoo failure classes.  No result produced here is consumed by
    # BatchResolver or cache policy.
    yahoo_anomaly_by_tv = {}
    yahoo_anomaly_rows = [
        r for r in rejected_rows
        if (bindings[r.tv_id].rejection_reason or "").startswith((
            "YAHOO_TYPE_MISMATCH:", "YAHOO_SYMBOL_NOT_FOUND", "YAHOO_RUNTIME_MISMATCH:"
        ))
    ]
    if yahoo_anomaly_rows:
        anomaly_symbols = list(dict.fromkeys(r.symbol for r in yahoo_anomaly_rows if r.symbol))
        try:
            anomaly_quotes = resolver.yahoo.quotes(anomaly_symbols) if anomaly_symbols else {}
        except ProviderError:
            anomaly_quotes = {}
        chart_fn = getattr(resolver.yahoo, "chart_quotes", None)
        try:
            anomaly_charts = chart_fn(anomaly_symbols) if callable(chart_fn) and anomaly_symbols else {}
        except ProviderError:
            anomaly_charts = {}

        anomaly_search = {}
        if callable(search_fn):
            for r in yahoo_anomaly_rows:
                if not r.isin:
                    continue
                token = str(r.isin).upper().strip()
                if token not in anomaly_search:
                    try:
                        anomaly_search[token] = list(search_fn(token))
                    except ProviderError:
                        anomaly_search[token] = []
        anomaly_search_symbols = list(dict.fromkeys(
            c.symbol for cs in anomaly_search.values() for c in cs if c.symbol
        ))
        try:
            anomaly_search_quotes = resolver.yahoo.quotes(anomaly_search_symbols) if anomaly_search_symbols else {}
        except ProviderError:
            anomaly_search_quotes = {}
        try:
            anomaly_search_charts = chart_fn(anomaly_search_symbols) if callable(chart_fn) and anomaly_search_symbols else {}
        except ProviderError:
            anomaly_search_charts = {}

        source_jobs, source_job_rows = [], []
        for r in yahoo_anomaly_rows:
            mic = TV_PREFIX_TO_MIC.get(r.prefix)
            if r.isin and mic:
                source_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
                source_job_rows.append(r)
        try:
            source_mapped = resolver.openfigi.map_jobs(source_jobs) if source_jobs else []
        except ProviderError:
            source_mapped = [[] for _ in source_jobs]
        anomaly_source = {r.tv_id: list(xs) for r, xs in zip(source_job_rows, source_mapped)}

        def quote_record(r, q, source_mic):
            if q is None:
                return {"returned": False, "symbol": None, "exchange": None,
                        "full_exchange_name": None, "market": None, "currency": None,
                        "quote_type": None, "type_compatible": False,
                        "currency_compatible": False, "venue_compatible": False}
            return {
                "returned": True, "symbol": q.symbol, "exchange": q.exchange,
                "full_exchange_name": q.full_exchange_name, "market": q.market,
                "currency": q.currency, "quote_type": q.quote_type,
                "type_compatible": yahoo_type_compatible(r, q.quote_type),
                "currency_compatible": (not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
                "venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            }

        for r in yahoo_anomaly_rows:
            source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
            source_ids = anomaly_source.get(r.tv_id, [])
            compatible_source = [x for x in source_ids if openfigi_type_compatible(r, x)]
            source_figis = sorted({x.figi for x in compatible_source if x.figi})
            source_proven = bool(source_mic and len(source_figis) == 1)
            tv_quote = quote_record(r, anomaly_quotes.get(r.symbol), source_mic)
            tv_chart = quote_record(r, anomaly_charts.get(r.symbol), source_mic)
            token = str(r.isin).upper().strip() if r.isin else ""
            candidates = []
            for c in anomaly_search.get(token, []):
                candidates.append({
                    "symbol": c.symbol, "search_exchange": c.exchange,
                    "search_quote_type": c.quote_type,
                    "exact_tv_symbol": c.symbol == r.symbol,
                    "quote": quote_record(r, anomaly_search_quotes.get(c.symbol), source_mic),
                    "chart": quote_record(r, anomaly_search_charts.get(c.symbol), source_mic),
                })

            observations = [tv_quote, tv_chart]
            observations += [x[k] for x in candidates for k in ("quote", "chart")]
            same_symbol = [x for x in observations if x["returned"] and x["symbol"] == r.symbol]
            strict = [x for x in same_symbol if x["type_compatible"] and x["currency_compatible"] and x["venue_compatible"]]
            taxonomy_only = [x for x in same_symbol if (not x["type_compatible"]) and x["currency_compatible"] and x["venue_compatible"]]
            venue_conflict = [x for x in same_symbol if source_mic and not x["venue_compatible"]]
            if source_proven and strict:
                classification = "SAME_SOURCE_INSTRUMENT_PROVEN"
            elif source_proven and taxonomy_only and not strict:
                classification = "YAHOO_TAXONOMY_ONLY_CONFLICT"
            elif venue_conflict:
                classification = "VENUE_CONTRADICTION"
            elif not same_symbol:
                classification = "YAHOO_SYMBOL_ABSENT"
            else:
                classification = "INSUFFICIENT_EVIDENCE"

            yahoo_anomaly_by_tv[r.tv_id] = {
                "attempted": True, "diagnostic_only": True,
                "source_mic": source_mic,
                "source_isin_mic_proven": source_proven,
                "source_figis": source_figis,
                "source_openfigi": [{
                    "figi": x.figi, "composite_figi": x.composite_figi,
                    "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                    "name": x.name, "security_type": x.security_type,
                    "security_type2": x.security_type2, "exch_code": x.exch_code,
                } for x in source_ids],
                "exact_tv_symbol_quote": tv_quote,
                "exact_tv_symbol_chart": tv_chart,
                "exact_isin_candidate_count": len(candidates),
                "exact_isin_candidates": candidates,
                "classification": classification,
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
        if (b.rejection_reason or "") != "MIC_UNKNOWN":
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

        # v0.3.64 diagnostic-only unresolved classification.  These labels do
        # not affect admission or cache semantics; they only make the rejection
        # audit actionable without collapsing distinct evidence failures into a
        # single resolver reason.  In particular, active_symbol=False is kept
        # as evidence, never treated as proof that a listing is retired.
        reason = b.rejection_reason or ""
        # v0.3.65: explicit provider taxonomy contradictions outrank
        # downstream metadata incompleteness.  UK validation exposed a case
        # (LSE:CAGP) where Yahoo explicitly returned BOND while OpenFIGI lacked
        # shareClassFIGI; classifying that as SHARE_CLASS_METADATA_MISSING hid
        # the materially stronger failure.
        valid_home_candidates = [
            c for c in home_market_search_candidates if c.get("resolver_candidate_valid")
        ]
        home_listing_unconfirmed = any(
            "OPENFIGI_HOME_LISTING_UNCONFIRMED" in c.get("admission_blocks", [])
            for c in home_market_search_candidates
        )
        if reason == "MIC_UNKNOWN":
            resolution_classification = "SOURCE_VENUE_UNKNOWN"
        elif reason.startswith("YAHOO_RUNTIME_HOME_MARKET_MISMATCH"):
            resolution_classification = "RUNTIME_CONTRACT_MISMATCH"
        elif reason.startswith("YAHOO_TYPE_MISMATCH"):
            resolution_classification = "TAXONOMY_CONFLICT"
        elif not r.isin:
            resolution_classification = "SOURCE_IDENTIFIER_MISSING"
        elif home_market_audit_status == "SHARE_CLASS_MISSING" or unscoped_status == "SHARE_CLASS_MISSING":
            resolution_classification = "SHARE_CLASS_METADATA_MISSING"
        elif len(valid_home_candidates) > 1:
            resolution_classification = "ROUTE_AMBIGUOUS"
        elif reason.startswith("OPENFIGI_NO_MATCH") and valid_home_candidates:
            resolution_classification = "SOURCE_IDENTITY_UNCONFIRMED"
        elif home_listing_unconfirmed:
            resolution_classification = "HOME_LISTING_UNCONFIRMED"
        elif home_market_audit_status == "CANDIDATES_RECORDED":
            resolution_classification = "HOME_ROUTE_UNCONFIRMED"
        elif home_market_audit_status == "NO_YAHOO_SEARCH_CANDIDATES":
            resolution_classification = "HOME_ROUTE_UNDISCOVERED"
        elif home_market_audit_status == "NO_COMPATIBLE_OPENFIGI_IDENTITY":
            # A populated OpenFIGI response with incompatible taxonomy is
            # materially different from OpenFIGI returning no identity at all.
            resolution_classification = (
                "TAXONOMY_CONFLICT" if unscoped else "IDENTITY_EVIDENCE_INSUFFICIENT"
            )
        else:
            resolution_classification = "IDENTITY_EVIDENCE_INSUFFICIENT"

        classification_evidence = {
            "active_symbol": r.active_symbol,
            "isin_present": bool(r.isin),
            "tradingview_probe_found": bool(tv_identifier_probe.get(r.tv_id, {}).get("found")),
            "tradingview_probe_isin": tv_identifier_probe.get(r.tv_id, {}).get("isin"),
            "tradingview_probe_cusip": tv_identifier_probe.get(r.tv_id, {}).get("cusip"),
            "tradingview_probe_figi": tv_identifier_probe.get(r.tv_id, {}).get("figi"),
            "unscoped_openfigi_status": unscoped_status,
            "home_market_audit_status": home_market_audit_status,
            "home_market_candidate_count": len(home_market_search_candidates),
            "home_market_valid_candidate_count": len(valid_home_candidates),
            "home_listing_unconfirmed": home_listing_unconfirmed,
        }

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
            "resolution_classification": resolution_classification,
            "classification_evidence": classification_evidence,
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
            "preferred_same_venue_audit": preferred_same_venue_by_tv.get(r.tv_id, {"attempted": False}),
            "otc_preferred_mic_discovery": otc_preferred_mic_discovery_by_tv.get(r.tv_id, {"attempted": False}),
            "otc_preferred_yahoo_discovery": otc_preferred_yahoo_discovery_by_tv.get(r.tv_id, {"attempted": False}),
            "yahoo_anomaly_audit": yahoo_anomaly_by_tv.get(r.tv_id, {"attempted": False}),
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




def _write_us_nyse_preferred_symbol_audit(path: Path, rows, resolver: BatchResolver) -> None:
    """Diagnostic-only cohort audit for NYSE preferred slash symbols.

    The cohort is selected from the TradingView snapshot, including already
    VERIFIED rows.  It tests whether exact ISIN discovery independently
    returns a unique Yahoo same-venue EQUITY candidate and records symbol
    punctuation correlation.  Nothing here participates in admission/cache.
    """
    cohort = [
        r for r in rows
        if r.prefix == "NYSE" and r.isin and "/" in r.symbol
        and tv_type_kind(r) == "PREFERRED"
        and "preferred" in {str(x).lower() for x in r.type_specs if x}
    ]
    source_jobs = [
        {"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"}
        for r in cohort
    ]
    try:
        source_mapped = resolver.openfigi.map_jobs(source_jobs) if source_jobs else []
    except ProviderError:
        source_mapped = [[] for _ in source_jobs]

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    records = []
    for r, identities in zip(cohort, source_mapped):
        compatible = [x for x in identities if openfigi_type_compatible(r, x)]
        preferred = [x for x in compatible if
            (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
            or (x.security_type or "").strip().lower() in {"preferred stock", "preferred", "preference"}]
        figis = sorted({x.figi for x in preferred if x.figi})
        source_proven = len(figis) == 1
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = quotes.get(c.symbol)
            slash_hyphen_equivalent = punctuation_key(c.symbol) == punctuation_key(r.symbol)
            ok = bool(
                q and (c.quote_type or "").upper() == "EQUITY"
                and yahoo_type_compatible(r, q.quote_type)
                and (not r.currency or not q.currency or currency_compatible(r.currency, q.currency))
                and yahoo_venue_compatible("XNYS", q)
            )
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type,
                "punctuation_equivalent_to_tv": slash_hyphen_equivalent,
                "quote_returned": q is not None,
                "quote_exchange": q.exchange if q else None,
                "quote_full_exchange_name": q.full_exchange_name if q else None,
                "quote_currency": q.currency if q else None,
                "quote_type": q.quote_type if q else None,
                "strict_same_venue_contract": ok,
            }
            candidates.append(rec)
            if ok:
                strict.append(rec)
        classification = "SOURCE_UNCONFIRMED"
        if source_proven:
            if len(cs) == 1 and len(strict) == 1 and strict[0]["punctuation_equivalent_to_tv"]:
                classification = "UNIQUE_EXACT_ISIN_SAME_VENUE_PUNCTUATION_EQUIVALENT"
            elif len(cs) == 0:
                classification = "YAHOO_ISIN_NOT_FOUND"
            elif len(cs) != 1:
                classification = "YAHOO_ISIN_AMBIGUOUS"
            else:
                classification = "YAHOO_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "tv_id": r.tv_id, "tv_symbol": r.symbol,
            "tv_isin": r.isin, "tv_currency": r.currency,
            "source_mic": "XNYS", "source_isin_mic_proven": source_proven,
            "source_figis": figis, "exact_isin_candidate_count": len(cs),
            "exact_isin_candidates": candidates, "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")



def _write_us_finnhub_unit_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only audit for FINNHUB_TYPE_MISMATCH:Unit.

    Collect exact-ISIN OpenFIGI evidence both unscoped and at the TradingView
    source MIC, plus Yahoo exact-ISIN discovery/quote metadata.  This function
    never changes resolver admission or cache state.
    """
    # v0.4.14: the audit is a true full residual cohort.  Keep rows without
    # TradingView ISIN in the JSONL as explicit fail-closed controls instead
    # of silently dropping them from the diagnostic denominator.
    cohort = [
        r for r in rows
        if (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:Unit"
    ]
    evidence_rows = [r for r in cohort if r.isin]

    # Diagnostic source-MIC recovery must also work for cached REJECTED rows.
    # Use the reviewed direct prefix mapping when it is singular. For provider
    # namespaces without one direct MIC (notably OTC and AMEX), recover a MIC
    # only when the cached Finnhub universe has exactly one MIC for the exact
    # symbol. This is evidence recovery, not admission logic.
    try:
        universe = resolver.cache.load_finnhub_universe()
    except Exception:
        universe = []
    norm_index = {}
    for raw in universe:
        sym = str(raw.get("symbol") or "").upper().strip()
        for key in symbol_index_keys(sym) if sym else []:
            norm_index.setdefault(key, []).append(raw)

    source_mics = {}
    source_mic_origins = {}
    for r in cohort:
        direct = TV_PREFIX_TO_MIC.get(r.prefix)
        if direct:
            source_mics[r.tv_id] = direct
            source_mic_origins[r.tv_id] = "TV_PREFIX_REVIEWED"
            continue
        raw_rows, seen = [], set()
        for key in symbol_index_keys(r.symbol):
            for raw in norm_index.get(key, []):
                marker = json.dumps(raw, sort_keys=True, default=str)
                if marker not in seen:
                    seen.add(marker); raw_rows.append(raw)
        allowed = TV_PREFIX_ALLOWED_MICS.get(r.prefix)
        mics = sorted({
            str(x.get("mic") or "").upper().strip() for x in raw_rows
            if x.get("mic") and (not allowed or str(x.get("mic") or "").upper().strip() in allowed)
        })
        if len(mics) == 1:
            source_mics[r.tv_id] = mics[0]
            source_mic_origins[r.tv_id] = "FINNHUB_EXACT_SYMBOL_UNIQUE_MIC"
        else:
            source_mics[r.tv_id] = None
            source_mic_origins[r.tv_id] = "UNRESOLVED"

    unscoped_jobs = [{"idType": "ID_ISIN", "idValue": r.isin} for r in evidence_rows]
    try:
        unscoped_mapped = resolver.openfigi.map_jobs(unscoped_jobs) if unscoped_jobs else []
    except ProviderError:
        unscoped_mapped = [[] for _ in unscoped_jobs]

    source_rows = [r for r in evidence_rows if source_mics.get(r.tv_id)]
    source_jobs = [
        {"idType": "ID_ISIN", "idValue": r.isin, "micCode": source_mics[r.tv_id]}
        for r in source_rows
    ]
    try:
        source_mapped = resolver.openfigi.map_jobs(source_jobs) if source_jobs else []
    except ProviderError:
        source_mapped = [[] for _ in source_jobs]
    source_by_tv = {r.tv_id: list(xs) for r, xs in zip(source_rows, source_mapped)}

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in evidence_rows:
            token = str(r.isin).upper().strip()
            if token in searches:
                continue
            try:
                searches[token] = list(search_fn(token))
            except ProviderError:
                searches[token] = []
    symbols = list(dict.fromkeys(
        c.symbol for cs in searches.values() for c in cs if c.symbol
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {
            "figi": x.figi, "composite_figi": x.composite_figi,
            "share_class_figi": x.share_class_figi, "ticker": x.ticker,
            "name": x.name, "security_type": x.security_type,
            "security_type2": x.security_type2, "exch_code": x.exch_code,
        }

    records = []
    unscoped_by_tv = {r.tv_id: list(xs) for r, xs in zip(evidence_rows, unscoped_mapped)}
    for r in cohort:
        unscoped = unscoped_by_tv.get(r.tv_id, [])
        b = bindings[r.tv_id]
        source_mic = source_mics.get(r.tv_id)
        source = source_by_tv.get(r.tv_id, [])
        unscoped_shares = sorted({x.share_class_figi for x in unscoped if x.share_class_figi})
        source_figis = sorted({x.figi for x in source if x.figi})
        source_shares = sorted({x.share_class_figi for x in source if x.share_class_figi})
        token = str(r.isin).upper().strip() if r.isin else ""
        cs = searches.get(token, []) if token else []
        candidates = []
        for c in cs:
            q = quotes.get(c.symbol)
            candidates.append({
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type,
                "quote_returned": q is not None,
                "quote_exchange": q.exchange if q else None,
                "quote_full_exchange_name": q.full_exchange_name if q else None,
                "quote_currency": q.currency if q else None,
                "quote_type": q.quote_type if q else None,
                "source_venue_compatible": bool(q and source_mic and yahoo_venue_compatible(source_mic, q)),
                "currency_compatible": bool(q and (not r.currency or not q.currency or currency_compatible(r.currency, q.currency))),
            })
        if not unscoped:
            unscoped_status = "UNKNOWN"
        elif len(unscoped_shares) == 1:
            unscoped_status = "UNIQUE_SHARE_CLASS"
        elif len(unscoped_shares) == 0:
            unscoped_status = "SHARE_CLASS_MISSING"
        else:
            unscoped_status = "AMBIGUOUS_SHARE_CLASS"
        if not r.isin:
            classification = "MISSING_TV_ISIN"
        elif len(source_figis) == 1 and len(cs) == 1 and any(
            str(c.get("symbol") or "").upper().strip() == str(r.symbol or "").upper().strip()
            and c.get("source_venue_compatible")
            and c.get("currency_compatible")
            and str(c.get("quote_type") or "").upper() == "EQUITY"
            for c in candidates
        ):
            classification = "UNIQUE_SHARE_CLASS_AND_ONE_SAME_SOURCE_EQUITY_CANDIDATE"
        elif len(source_figis) == 1:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        else:
            classification = "IDENTITY_EVIDENCE_INCOMPLETE"
        records.append({
            "diagnostic_only": True,
            "diagnostic_release": __version__,
            "classification": classification,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs),
            "finnhub_type": b.finnhub_type,
            "rejection_reason": b.rejection_reason,
            "source_mic": source_mic,
            "source_mic_origin": source_mic_origins.get(r.tv_id),
            "unscoped_openfigi_status": unscoped_status,
            "unscoped_share_class_figis": unscoped_shares,
            "unscoped_openfigi": [of_record(x) for x in unscoped],
            "source_openfigi_figis": source_figis,
            "source_openfigi_share_class_figis": source_shares,
            "source_scoped_openfigi_status": ("UNIQUE_FIGI" if len(source_figis) == 1 else ("NO_MATCH" if not source else "AMBIGUOUS")),
            "source_scoped_share_class_figis": source_shares,
            "source_openfigi_unique_figi": len(source_figis) == 1,
            "source_openfigi": [of_record(x) for x in source],
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_us_finnhub_unit_residual_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.3.91 diagnostic-only classification of residual Finnhub Unit rejects.

    Reuses the full exact-ISIN evidence collector, then evaluates every current
    residual against the already-shipped XNYS (v0.3.79) and XNAS (v0.3.81)
    fund/unit contracts.  It never changes resolver admission or cache state.
    """
    import tempfile
    with tempfile.NamedTemporaryFile(prefix="tvmi-unit-v091-", suffix=".jsonl", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _write_us_finnhub_unit_audit(tmp_path, rows, bindings, resolver)
        base = []
        if tmp_path.exists():
            with tmp_path.open("r", encoding="utf-8") as f:
                base = [json.loads(line) for line in f if line.strip()]
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass

    records = []
    for rec in base:
        tv_type = str(rec.get("tv_type") or "").lower()
        specs = {str(x).lower() for x in rec.get("tv_type_specs") or [] if x}
        source_mic = rec.get("source_mic")
        unscoped = rec.get("unscoped_openfigi") or []
        source = rec.get("source_openfigi") or []
        candidates = rec.get("yahoo_exact_isin_candidates") or []
        tv_symbol = str(rec.get("tv_symbol") or "").upper().strip()

        unit_unscoped = [x for x in unscoped if (
            str(x.get("security_type") or "").strip().lower() == "unit"
            or str(x.get("security_type2") or "").strip().lower() == "unit"
        )]
        exact_ticker_units = [x for x in unit_unscoped if str(x.get("ticker") or "").upper().strip() == tv_symbol]
        unit_source = [x for x in source if (
            str(x.get("security_type") or "").strip().lower() == "unit"
            or str(x.get("security_type2") or "").strip().lower() == "unit"
        )]
        unscoped_shares = set(rec.get("unscoped_share_class_figis") or [])
        source_unit_figis = {x.get("figi") for x in unit_source if x.get("figi")}
        source_unit_shares = {x.get("share_class_figi") for x in unit_source if x.get("share_class_figi")}

        yahoo_strict = []
        for c in candidates:
            exact_symbol = str(c.get("symbol") or "").upper().strip() == tv_symbol
            search_equity = str(c.get("search_quote_type") or "").upper() == "EQUITY"
            quote_equity = str(c.get("quote_type") or "").upper() == "EQUITY"
            if exact_symbol and search_equity and quote_equity and c.get("source_venue_compatible") and c.get("currency_compatible"):
                yahoo_strict.append(c)

        if tv_type != "fund" or "unit" not in specs:
            blocker = "OUTSIDE_TV_FUND_UNIT_COHORT"
        elif source_mic not in {"XNYS", "XNAS"}:
            blocker = "SOURCE_MIC_NOT_XNYS_OR_XNAS"
        elif len(unscoped_shares) != 1:
            blocker = "OPENFIGI_UNSCOPED_SHARE_CLASS_NOT_UNIQUE"
        elif source_mic == "XNYS" and (len(source_unit_figis) != 1 or source_unit_shares != unscoped_shares):
            blocker = "XNYS_SCOPED_UNIT_SOURCE_NOT_UNIQUE"
        elif source_mic == "XNAS" and source:
            blocker = "XNAS_SCOPED_OPENFIGI_NOT_NO_MATCH"
        elif source_mic == "XNAS" and not exact_ticker_units:
            blocker = "XNAS_UNSCOPED_EXACT_TICKER_UNIT_NOT_PROVEN"
        elif len(candidates) != 1:
            blocker = "YAHOO_EXACT_ISIN_NOT_UNIQUE"
        elif len(yahoo_strict) != 1:
            c = candidates[0] if candidates else {}
            if str(c.get("symbol") or "").upper().strip() != tv_symbol:
                blocker = "YAHOO_SYMBOL_MISMATCH"
            elif not c.get("source_venue_compatible"):
                blocker = "YAHOO_SOURCE_VENUE_UNCONFIRMED"
            elif not c.get("currency_compatible"):
                blocker = "YAHOO_CURRENCY_UNCONFIRMED"
            else:
                blocker = "YAHOO_EQUITY_UNCONFIRMED"
        else:
            blocker = "CURRENTLY_SATISFIES_EXISTING_UNIT_CONTRACT"

        rec["diagnostic_release"] = "0.3.91"
        rec["existing_contract"] = (
            "US_XNYS_FUND_UNIT_EXACT_ISIN" if source_mic == "XNYS"
            else "US_XNAS_FUND_UNIT_EXACT_ISIN" if source_mic == "XNAS"
            else None
        )
        rec["unit_unscoped_exact_ticker_count"] = len(exact_ticker_units)
        rec["source_unit_figi_count"] = len(source_unit_figis)
        rec["yahoo_strict_exact_symbol_source_equity_count"] = len(yahoo_strict)
        rec["first_existing_contract_blocker"] = blocker
        records.append(rec)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")



def _write_us_xase_fund_unit_cohort_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.3.92 diagnostic-only audit of the complete TV AMEX/XASE fund+unit cohort.

    Includes VERIFIED and REJECTED rows.  It measures whether XASE exhibits a
    systematic provider gap analogous to XNAS without changing admission.
    """
    cohort = [
        r for r in rows
        if r.prefix == "AMEX" and r.isin
        and str(r.tv_type or "").lower() == "fund"
        and "unit" in {str(x).lower() for x in r.type_specs if x}
    ]
    jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XASE"} for r in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(jobs) if jobs else []
    except ProviderError:
        mapped = [[] for _ in jobs]

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token in searches:
                continue
            try:
                searches[token] = list(search_fn(token))
            except ProviderError:
                searches[token] = []
    symbols = list(dict.fromkeys(c.symbol for cs in searches.values() for c in cs if c.symbol))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    records = []
    for r, identities in zip(cohort, mapped):
        b = bindings.get(r.tv_id)
        unit_ids = [x for x in identities if (
            str(x.security_type or "").strip().lower() == "unit"
            or str(x.security_type2 or "").strip().lower() == "unit"
        )]
        figis = sorted({x.figi for x in unit_ids if x.figi})
        shares = sorted({x.share_class_figi for x in unit_ids if x.share_class_figi})
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = quotes.get(c.symbol)
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "quote_returned": q is not None,
                "quote_exchange": q.exchange if q else None,
                "quote_full_exchange_name": q.full_exchange_name if q else None,
                "quote_currency": q.currency if q else None, "quote_type": q.quote_type if q else None,
                "exact_tv_symbol": str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip(),
                "xase_venue_compatible": bool(q and yahoo_venue_compatible("XASE", q)),
                "currency_compatible": bool(q and (not r.currency or not q.currency or currency_compatible(r.currency, q.currency))),
                "equity": bool(q and str(c.quote_type or "").upper() == "EQUITY" and str(q.quote_type or "").upper() == "EQUITY"),
            }
            rec["strict_same_source_contract"] = bool(rec["exact_tv_symbol"] and rec["xase_venue_compatible"] and rec["currency_compatible"] and rec["equity"])
            candidates.append(rec)
            if rec["strict_same_source_contract"]:
                strict.append(rec)
        if len(figis) == 1 and len(cs) == 1 and len(strict) == 1:
            classification = "XASE_SCOPED_UNIT_AND_YAHOO_STRICT"
        elif not identities:
            classification = "XASE_SCOPED_OPENFIGI_NO_MATCH"
        elif len(figis) != 1:
            classification = "XASE_SCOPED_UNIT_NOT_UNIQUE"
        elif len(cs) != 1:
            classification = "YAHOO_EXACT_ISIN_NOT_UNIQUE"
        else:
            classification = "YAHOO_XASE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type, "tv_type_specs": list(r.type_specs),
            "identity_status": b.status if b else None,
            "rejection_reason": b.rejection_reason if b and b.status == "REJECTED" else None,
            "mapping_method": b.mapping_method if b and b.status == "VERIFIED" else None,
            "source_mic": "XASE", "xase_scoped_identity_count": len(identities),
            "xase_scoped_unit_figis": figis, "xase_scoped_unit_share_class_figis": shares,
            "xase_scoped_openfigi": [{"figi": x.figi, "share_class_figi": x.share_class_figi, "ticker": x.ticker, "security_type": x.security_type, "security_type2": x.security_type2, "exch_code": x.exch_code} for x in identities],
            "yahoo_exact_isin_candidate_count": len(cs), "yahoo_exact_isin_candidates": candidates,
            "yahoo_strict_same_source_count": len(strict), "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

def _write_us_yahoo_currency_unknown_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.4.16 diagnostic-only full-cohort audit of YAHOO_CURRENCY_MISMATCH:?.

    Records exact source identity evidence, Yahoo quote/chart currency metadata,
    and exact-ISIN discovery. Missing ISIN stays in the cohort and never causes
    an OpenFIGI/Yahoo ISIN lookup. Nothing here participates in admission/cache.
    """
    cohort = [
        r for r in rows
        if (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED" and b.rejection_reason == "YAHOO_CURRENCY_MISMATCH:?"
    ]

    # OpenFIGI: source-scoped proof plus unscoped exact-ISIN context.
    scoped_jobs, scoped_indexes = [], []
    unscoped_jobs, unscoped_indexes = [], []
    for i, r in enumerate(cohort):
        if not r.isin:
            continue
        unscoped_indexes.append(i)
        unscoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin})
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    unscoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass
    try:
        mapped = resolver.openfigi.map_jobs(unscoped_jobs) if unscoped_jobs else []
        for i, xs in zip(unscoped_indexes, mapped):
            unscoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    direct_symbols = []
    variants_by_tv = {}
    for r in cohort:
        variants = bounded_symbol_variants(r.symbol)
        variants_by_tv[r.tv_id] = variants
        direct_symbols.extend(variants)
    direct_symbols = list(dict.fromkeys(direct_symbols))
    try:
        quotes = resolver.yahoo.quotes(direct_symbols) if direct_symbols else {}
    except ProviderError:
        quotes = {}
    try:
        charts = resolver.yahoo.chart_quotes(direct_symbols) if direct_symbols and hasattr(resolver.yahoo, "chart_quotes") else {}
    except ProviderError:
        charts = {}

    searches = {}
    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    if callable(search_fn):
        for r in cohort:
            if not r.isin:
                continue
            token = str(r.isin).upper().strip()
            if token and token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    search_symbols = list(dict.fromkeys(c.symbol for cs in searches.values() for c in cs if c.symbol))
    try:
        search_quotes = resolver.yahoo.quotes(search_symbols) if search_symbols else {}
    except ProviderError:
        search_quotes = {}
    try:
        search_charts = resolver.yahoo.chart_quotes(search_symbols) if search_symbols and hasattr(resolver.yahoo, "chart_quotes") else {}
    except ProviderError:
        search_charts = {}

    def figirec(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "security_type": x.security_type, "security_type2": x.security_type2,
                "exch_code": x.exch_code}

    def qrec(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "currency": q.currency,
            "quote_type": q.quote_type, "market": q.market,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_reported": q.currency is not None,
            "currency_compatible": bool(q.currency is not None and currency_compatible(r.currency, q.currency)),
            "type_compatible": bool(q.quote_type is not None and yahoo_type_compatible(r, q.quote_type)),
        }

    records = []
    for i, r in enumerate(cohort):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped = scoped_mapped[i]
        unscoped = unscoped_mapped[i]
        direct = []
        for sym in variants_by_tv.get(r.tv_id, []):
            direct.append({"requested_symbol": sym,
                           "quote": qrec(quotes.get(sym), r, source_mic),
                           "chart": qrec(charts.get(sym), r, source_mic)})
        token = str(r.isin or "").upper().strip()
        cs = searches.get(token, []) if token else []
        discovered = []
        for c in cs:
            discovered.append({
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type,
                "exact_tv_symbol": bool(c.symbol and c.symbol.upper() == r.symbol.upper()),
                "quote": qrec(search_quotes.get(c.symbol), r, source_mic),
                "chart": qrec(search_charts.get(c.symbol), r, source_mic),
            })

        direct_chart_good = [x for x in direct if x["chart"] and x["chart"]["currency_compatible"] and x["chart"]["source_venue_compatible"] and x["chart"]["type_compatible"]]
        direct_quote_explicit_bad = [x for x in direct if x["quote"] and x["quote"]["currency_reported"] and not x["quote"]["currency_compatible"]]
        exact_same_source_good = []
        for x in discovered:
            for key in ("quote", "chart"):
                q = x.get(key)
                if q and x["exact_tv_symbol"] and q["currency_compatible"] and q["source_venue_compatible"] and q["type_compatible"]:
                    exact_same_source_good.append((x["symbol"], key))

        if not r.isin:
            classification = "MISSING_TV_ISIN"
        elif direct_quote_explicit_bad:
            classification = "EXPLICIT_CURRENCY_CONTRADICTION"
        elif direct_chart_good:
            classification = "QUOTE_CURRENCY_MISSING_CHART_STRICT_MATCH"
        elif len(exact_same_source_good) == 1:
            classification = "EXACT_ISIN_SAME_SOURCE_STRICT_MATCH"
        elif not cs:
            classification = "CURRENCY_MISSING_AND_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "IDENTITY_OR_CURRENCY_EVIDENCE_INCOMPLETE"

        records.append({
            "diagnostic_only": True, "diagnostic_release": "0.4.16",
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type, "tv_type_specs": list(r.type_specs),
            "rejection_reason": b.rejection_reason, "source_mic": source_mic,
            "source_scoped_openfigi_count": len(scoped),
            "source_scoped_openfigi": [figirec(x) for x in scoped],
            "unscoped_openfigi_count": len(unscoped),
            "unscoped_openfigi": [figirec(x) for x in unscoped],
            "source_scoped_unique_figi": len(scoped) == 1,
            "source_scoped_share_class_figis": sorted({x.share_class_figi for x in scoped if x.share_class_figi}),
            "unscoped_share_class_figis": sorted({x.share_class_figi for x in unscoped if x.share_class_figi}),
            "direct_symbol_variants": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": discovered,
            "direct_chart_strict_match_count": len(direct_chart_good),
            "exact_isin_same_source_strict_match_count": len(exact_same_source_good),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_us_finnhub_royalty_trust_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.3.94 diagnostic-only exact-ISIN/source audit for Royalty Trst rejects.

    The audit deliberately does not treat Finnhub Royalty Trst as compatible with
    ordinary equity.  It records exact source-MIC OpenFIGI evidence and Yahoo
    exact-ISIN/direct-symbol metadata so a later policy decision can be based on
    the whole cohort rather than on ticker or name heuristics.
    """
    cohort = [
        r for r in rows
        if r.isin and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:Royalty Trst"
    ]
    scoped_jobs = []
    scoped_indexes = []
    for i, r in enumerate(cohort):
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [r.symbol for r in cohort if r.symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "market": q.market,
            "currency": q.currency, "quote_type": q.quote_type,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
            "equity": str(q.quote_type or "").upper() == "EQUITY",
        }

    records = []
    for r, scoped in zip(cohort, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        direct = q_record(quotes.get(r.symbol), r, source_mic)
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = q_record(quotes.get(c.symbol), r, source_mic)
            exact_symbol = str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip()
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "exact_tv_symbol": exact_symbol,
                "quote": q,
            }
            rec["strict_same_source_equity"] = bool(
                exact_symbol and str(c.quote_type or "").upper() == "EQUITY" and q
                and q["source_venue_compatible"] and q["currency_compatible"] and q["equity"]
            )
            candidates.append(rec)
            if rec["strict_same_source_equity"]:
                strict.append(rec)
        direct_strict = bool(direct and direct["source_venue_compatible"] and direct["currency_compatible"] and direct["equity"])
        if len(scoped_figis) == 1 and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_EXACT_ISIN_STRICT"
        elif len(scoped_figis) == 1 and direct_strict:
            classification = "SOURCE_SCOPED_AND_YAHOO_DIRECT_STRICT_ONLY"
        elif not scoped:
            classification = "OPENFIGI_SOURCE_NO_MATCH"
        elif len(scoped_figis) != 1:
            classification = "OPENFIGI_SOURCE_AMBIGUOUS"
        elif not cs:
            classification = "YAHOO_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "rejection_reason": b.rejection_reason, "finnhub_type": b.finnhub_type,
            "source_mic": source_mic, "source_scoped_figi_count": len(scoped_figis),
            "source_scoped_figis": scoped_figis,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_direct_symbol": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_isin_strict_same_source_count": len(strict),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
def _write_us_finnhub_ltd_part_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.3.96 diagnostic-only exact-ISIN/source audit for Ltd Part rejects.

    The audit deliberately does not treat Finnhub Ltd Part as compatible with
    ordinary equity.  It records exact source-MIC OpenFIGI evidence and Yahoo
    exact-ISIN/direct-symbol metadata so a later policy decision can be based on
    the whole cohort rather than on ticker or name heuristics.
    """
    cohort = [
        r for r in rows
        if r.isin and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:Ltd Part"
    ]
    scoped_jobs = []
    scoped_indexes = []
    for i, r in enumerate(cohort):
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [r.symbol for r in cohort if r.symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "market": q.market,
            "currency": q.currency, "quote_type": q.quote_type,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
            "equity": str(q.quote_type or "").upper() == "EQUITY",
        }

    records = []
    for r, scoped in zip(cohort, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        direct = q_record(quotes.get(r.symbol), r, source_mic)
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = q_record(quotes.get(c.symbol), r, source_mic)
            exact_symbol = str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip()
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "exact_tv_symbol": exact_symbol,
                "quote": q,
            }
            rec["strict_same_source_equity"] = bool(
                exact_symbol and str(c.quote_type or "").upper() == "EQUITY" and q
                and q["source_venue_compatible"] and q["currency_compatible"] and q["equity"]
            )
            candidates.append(rec)
            if rec["strict_same_source_equity"]:
                strict.append(rec)
        direct_strict = bool(direct and direct["source_venue_compatible"] and direct["currency_compatible"] and direct["equity"])
        if len(scoped_figis) == 1 and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_EXACT_ISIN_STRICT"
        elif len(scoped_figis) == 1 and direct_strict:
            classification = "SOURCE_SCOPED_AND_YAHOO_DIRECT_STRICT_ONLY"
        elif not scoped:
            classification = "OPENFIGI_SOURCE_NO_MATCH"
        elif len(scoped_figis) != 1:
            classification = "OPENFIGI_SOURCE_AMBIGUOUS"
        elif not cs:
            classification = "YAHOO_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "rejection_reason": b.rejection_reason, "finnhub_symbol": b.finnhub_symbol,
            "finnhub_type": b.finnhub_type,
            "finnhub_exact_tv_symbol": str(b.finnhub_symbol or "").upper().strip() == str(r.symbol or "").upper().strip(),
            "source_mic": source_mic, "source_scoped_figi_count": len(scoped_figis),
            "source_scoped_figis": scoped_figis,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_direct_symbol": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_isin_strict_same_source_count": len(strict),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

def _write_us_finnhub_closed_end_fund_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.3.98 diagnostic-only exact-ISIN/source audit for Closed-End Fund rejects.

    The audit deliberately does not treat Finnhub Closed-End Fund as compatible with
    ordinary equity.  It records exact source-MIC OpenFIGI evidence and Yahoo
    exact-ISIN/direct-symbol metadata so a later policy decision can be based on
    the whole cohort rather than on ticker or name heuristics.
    """
    cohort = [
        r for r in rows
        if r.isin and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:Closed-End Fund"
    ]
    scoped_jobs = []
    scoped_indexes = []
    for i, r in enumerate(cohort):
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [r.symbol for r in cohort if r.symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "market": q.market,
            "currency": q.currency, "quote_type": q.quote_type,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
            "equity": str(q.quote_type or "").upper() == "EQUITY",
        }

    records = []
    for r, scoped in zip(cohort, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        direct = q_record(quotes.get(r.symbol), r, source_mic)
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = q_record(quotes.get(c.symbol), r, source_mic)
            exact_symbol = str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip()
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "exact_tv_symbol": exact_symbol,
                "quote": q,
            }
            rec["strict_same_source_equity"] = bool(
                exact_symbol and str(c.quote_type or "").upper() == "EQUITY" and q
                and q["source_venue_compatible"] and q["currency_compatible"] and q["equity"]
            )
            candidates.append(rec)
            if rec["strict_same_source_equity"]:
                strict.append(rec)
        direct_strict = bool(direct and direct["source_venue_compatible"] and direct["currency_compatible"] and direct["equity"])
        if len(scoped_figis) == 1 and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_EXACT_ISIN_STRICT"
        elif len(scoped_figis) == 1 and direct_strict:
            classification = "SOURCE_SCOPED_AND_YAHOO_DIRECT_STRICT_ONLY"
        elif not scoped:
            classification = "OPENFIGI_SOURCE_NO_MATCH"
        elif len(scoped_figis) != 1:
            classification = "OPENFIGI_SOURCE_AMBIGUOUS"
        elif not cs:
            classification = "YAHOO_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "rejection_reason": b.rejection_reason, "finnhub_symbol": b.finnhub_symbol,
            "finnhub_type": b.finnhub_type,
            "finnhub_exact_tv_symbol": str(b.finnhub_symbol or "").upper().strip() == str(r.symbol or "").upper().strip(),
            "source_mic": source_mic, "source_scoped_figi_count": len(scoped_figis),
            "source_scoped_figis": scoped_figis,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_direct_symbol": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_isin_strict_same_source_count": len(strict),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

def _write_us_finnhub_cdi_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.4.0 diagnostic-only exact-ISIN/source audit for CDI rejects.

    The audit deliberately does not treat Finnhub CDI as compatible with
    ordinary equity.  It records exact source-MIC OpenFIGI evidence and Yahoo
    exact-ISIN/direct-symbol metadata so a later policy decision can be based on
    the whole cohort rather than on ticker or name heuristics.
    """
    cohort = [
        r for r in rows
        if r.isin and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:CDI"
    ]
    scoped_jobs = []
    scoped_indexes = []
    for i, r in enumerate(cohort):
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [r.symbol for r in cohort if r.symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "market": q.market,
            "currency": q.currency, "quote_type": q.quote_type,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
            "equity": str(q.quote_type or "").upper() == "EQUITY",
        }

    records = []
    for r, scoped in zip(cohort, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        direct = q_record(quotes.get(r.symbol), r, source_mic)
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = q_record(quotes.get(c.symbol), r, source_mic)
            exact_symbol = str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip()
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "exact_tv_symbol": exact_symbol,
                "quote": q,
            }
            rec["strict_same_source_equity"] = bool(
                exact_symbol and str(c.quote_type or "").upper() == "EQUITY" and q
                and q["source_venue_compatible"] and q["currency_compatible"] and q["equity"]
            )
            candidates.append(rec)
            if rec["strict_same_source_equity"]:
                strict.append(rec)
        direct_strict = bool(direct and direct["source_venue_compatible"] and direct["currency_compatible"] and direct["equity"])
        if len(scoped_figis) == 1 and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_EXACT_ISIN_STRICT"
        elif len(scoped_figis) == 1 and direct_strict:
            classification = "SOURCE_SCOPED_AND_YAHOO_DIRECT_STRICT_ONLY"
        elif not scoped:
            classification = "OPENFIGI_SOURCE_NO_MATCH"
        elif len(scoped_figis) != 1:
            classification = "OPENFIGI_SOURCE_AMBIGUOUS"
        elif not cs:
            classification = "YAHOO_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "rejection_reason": b.rejection_reason, "finnhub_symbol": b.finnhub_symbol,
            "finnhub_type": b.finnhub_type,
            "finnhub_exact_tv_symbol": str(b.finnhub_symbol or "").upper().strip() == str(r.symbol or "").upper().strip(),
            "source_mic": source_mic, "source_scoped_figi_count": len(scoped_figis),
            "source_scoped_figis": scoped_figis,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_direct_symbol": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_isin_strict_same_source_count": len(strict),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
def _write_us_finnhub_stapled_security_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.4.1 diagnostic-only exact-ISIN/source audit for Stapled Security rejects.

    The audit deliberately does not treat Finnhub Stapled Security as compatible with
    ordinary equity.  It records exact source-MIC OpenFIGI evidence and Yahoo
    exact-ISIN/direct-symbol metadata so a later policy decision can be based on
    the whole cohort rather than on ticker or name heuristics.
    """
    cohort = [
        r for r in rows
        if r.isin and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:Stapled Security"
    ]
    scoped_jobs = []
    scoped_indexes = []
    for i, r in enumerate(cohort):
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [r.symbol for r in cohort if r.symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "market": q.market,
            "currency": q.currency, "quote_type": q.quote_type,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
            "equity": str(q.quote_type or "").upper() == "EQUITY",
        }

    records = []
    for r, scoped in zip(cohort, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        direct = q_record(quotes.get(r.symbol), r, source_mic)
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = q_record(quotes.get(c.symbol), r, source_mic)
            exact_symbol = str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip()
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "exact_tv_symbol": exact_symbol,
                "quote": q,
            }
            rec["strict_same_source_equity"] = bool(
                exact_symbol and str(c.quote_type or "").upper() == "EQUITY" and q
                and q["source_venue_compatible"] and q["currency_compatible"] and q["equity"]
            )
            candidates.append(rec)
            if rec["strict_same_source_equity"]:
                strict.append(rec)
        direct_strict = bool(direct and direct["source_venue_compatible"] and direct["currency_compatible"] and direct["equity"])
        if len(scoped_figis) == 1 and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_EXACT_ISIN_STRICT"
        elif len(scoped_figis) == 1 and direct_strict:
            classification = "SOURCE_SCOPED_AND_YAHOO_DIRECT_STRICT_ONLY"
        elif not scoped:
            classification = "OPENFIGI_SOURCE_NO_MATCH"
        elif len(scoped_figis) != 1:
            classification = "OPENFIGI_SOURCE_AMBIGUOUS"
        elif not cs:
            classification = "YAHOO_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "rejection_reason": b.rejection_reason, "finnhub_symbol": b.finnhub_symbol,
            "finnhub_type": b.finnhub_type,
            "finnhub_exact_tv_symbol": str(b.finnhub_symbol or "").upper().strip() == str(r.symbol or "").upper().strip(),
            "source_mic": source_mic, "source_scoped_figi_count": len(scoped_figis),
            "source_scoped_figis": scoped_figis,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_direct_symbol": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_isin_strict_same_source_count": len(strict),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
def _write_us_finnhub_preference_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.4.2 diagnostic-only exact-ISIN/source audit for Preference rejects.

    The audit deliberately does not treat Finnhub Preference as compatible with
    ordinary equity.  It records exact source-MIC OpenFIGI evidence and Yahoo
    exact-ISIN/direct-symbol metadata so a later policy decision can be based on
    the whole cohort rather than on ticker or name heuristics.
    """
    cohort = [
        r for r in rows
        if r.isin and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:Preference"
    ]
    scoped_jobs = []
    scoped_indexes = []
    for i, r in enumerate(cohort):
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [r.symbol for r in cohort if r.symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "market": q.market,
            "currency": q.currency, "quote_type": q.quote_type,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
            "equity": str(q.quote_type or "").upper() == "EQUITY",
        }

    records = []
    for r, scoped in zip(cohort, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        direct = q_record(quotes.get(r.symbol), r, source_mic)
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = q_record(quotes.get(c.symbol), r, source_mic)
            exact_symbol = str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip()
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "exact_tv_symbol": exact_symbol,
                "quote": q,
            }
            rec["strict_same_source_equity"] = bool(
                exact_symbol and str(c.quote_type or "").upper() == "EQUITY" and q
                and q["source_venue_compatible"] and q["currency_compatible"] and q["equity"]
            )
            candidates.append(rec)
            if rec["strict_same_source_equity"]:
                strict.append(rec)
        direct_strict = bool(direct and direct["source_venue_compatible"] and direct["currency_compatible"] and direct["equity"])
        if len(scoped_figis) == 1 and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_EXACT_ISIN_STRICT"
        elif len(scoped_figis) == 1 and direct_strict:
            classification = "SOURCE_SCOPED_AND_YAHOO_DIRECT_STRICT_ONLY"
        elif not scoped:
            classification = "OPENFIGI_SOURCE_NO_MATCH"
        elif len(scoped_figis) != 1:
            classification = "OPENFIGI_SOURCE_AMBIGUOUS"
        elif not cs:
            classification = "YAHOO_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "rejection_reason": b.rejection_reason, "finnhub_symbol": b.finnhub_symbol,
            "finnhub_type": b.finnhub_type,
            "finnhub_exact_tv_symbol": str(b.finnhub_symbol or "").upper().strip() == str(r.symbol or "").upper().strip(),
            "source_mic": source_mic, "source_scoped_figi_count": len(scoped_figis),
            "source_scoped_figis": scoped_figis,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_direct_symbol": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_isin_strict_same_source_count": len(strict),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
def _write_us_finnhub_gdr_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.4.3 diagnostic-only exact-ISIN/source audit for GDR rejects.

    The audit deliberately does not treat Finnhub GDR as compatible with
    ordinary equity.  It records exact source-MIC OpenFIGI evidence and Yahoo
    exact-ISIN/direct-symbol metadata so a later policy decision can be based on
    the whole cohort rather than on ticker or name heuristics.
    """
    cohort = [
        r for r in rows
        if r.isin and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:GDR"
    ]
    scoped_jobs = []
    scoped_indexes = []
    for i, r in enumerate(cohort):
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [r.symbol for r in cohort if r.symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "market": q.market,
            "currency": q.currency, "quote_type": q.quote_type,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
            "equity": str(q.quote_type or "").upper() == "EQUITY",
        }

    records = []
    for r, scoped in zip(cohort, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        direct = q_record(quotes.get(r.symbol), r, source_mic)
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = q_record(quotes.get(c.symbol), r, source_mic)
            exact_symbol = str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip()
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "exact_tv_symbol": exact_symbol,
                "quote": q,
            }
            rec["strict_same_source_equity"] = bool(
                exact_symbol and str(c.quote_type or "").upper() == "EQUITY" and q
                and q["source_venue_compatible"] and q["currency_compatible"] and q["equity"]
            )
            candidates.append(rec)
            if rec["strict_same_source_equity"]:
                strict.append(rec)
        direct_strict = bool(direct and direct["source_venue_compatible"] and direct["currency_compatible"] and direct["equity"])
        if len(scoped_figis) == 1 and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_EXACT_ISIN_STRICT"
        elif len(scoped_figis) == 1 and direct_strict:
            classification = "SOURCE_SCOPED_AND_YAHOO_DIRECT_STRICT_ONLY"
        elif not scoped:
            classification = "OPENFIGI_SOURCE_NO_MATCH"
        elif len(scoped_figis) != 1:
            classification = "OPENFIGI_SOURCE_AMBIGUOUS"
        elif not cs:
            classification = "YAHOO_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "rejection_reason": b.rejection_reason, "finnhub_symbol": b.finnhub_symbol,
            "finnhub_type": b.finnhub_type,
            "finnhub_exact_tv_symbol": str(b.finnhub_symbol or "").upper().strip() == str(r.symbol or "").upper().strip(),
            "source_mic": source_mic, "source_scoped_figi_count": len(scoped_figis),
            "source_scoped_figis": scoped_figis,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_direct_symbol": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_isin_strict_same_source_count": len(strict),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
def _write_us_finnhub_named_type_audit(
    path: Path, rows, bindings: dict, resolver: BatchResolver,
    finnhub_type: str | None = None, *, rejection_reason: str | None = None,
) -> None:
    """Diagnostic-only exact-ISIN/source audit for one Finnhub rejection cohort."""
    target_reason = rejection_reason or f"FINNHUB_TYPE_MISMATCH:{finnhub_type}"
    cohort = [
        r for r in rows
        if r.isin and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == target_reason
    ]
    scoped_jobs = []
    scoped_indexes = []
    for i, r in enumerate(cohort):
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_indexes.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    scoped_mapped = [[] for _ in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_indexes, mapped):
            scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [r.symbol for r in cohort if r.symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None:
            return None
        return {
            "symbol": q.symbol, "exchange": q.exchange,
            "full_exchange_name": q.full_exchange_name, "market": q.market,
            "currency": q.currency, "quote_type": q.quote_type,
            "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
            "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
            "equity": str(q.quote_type or "").upper() == "EQUITY",
        }

    records = []
    for r, scoped in zip(cohort, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        direct = q_record(quotes.get(r.symbol), r, source_mic)
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        strict = []
        for c in cs:
            q = q_record(quotes.get(c.symbol), r, source_mic)
            exact_symbol = str(c.symbol or "").upper().strip() == str(r.symbol or "").upper().strip()
            rec = {
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "exact_tv_symbol": exact_symbol,
                "quote": q,
            }
            rec["strict_same_source_equity"] = bool(
                exact_symbol and str(c.quote_type or "").upper() == "EQUITY" and q
                and q["source_venue_compatible"] and q["currency_compatible"] and q["equity"]
            )
            candidates.append(rec)
            if rec["strict_same_source_equity"]:
                strict.append(rec)
        direct_strict = bool(direct and direct["source_venue_compatible"] and direct["currency_compatible"] and direct["equity"])
        if len(scoped_figis) == 1 and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_EXACT_ISIN_STRICT"
        elif len(scoped_figis) == 1 and direct_strict:
            classification = "SOURCE_SCOPED_AND_YAHOO_DIRECT_STRICT_ONLY"
        elif not scoped:
            classification = "OPENFIGI_SOURCE_NO_MATCH"
        elif len(scoped_figis) != 1:
            classification = "OPENFIGI_SOURCE_AMBIGUOUS"
        elif not cs:
            classification = "YAHOO_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        records.append({
            "diagnostic_only": True, "diagnostic_release": __version__,
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "rejection_reason": b.rejection_reason, "finnhub_symbol": b.finnhub_symbol,
            "finnhub_type": b.finnhub_type,
            "finnhub_exact_tv_symbol": str(b.finnhub_symbol or "").upper().strip() == str(r.symbol or "").upper().strip(),
            "source_mic": source_mic, "source_scoped_figi_count": len(scoped_figis),
            "source_scoped_figis": scoped_figis,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_direct_symbol": direct,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_exact_isin_candidates": candidates,
            "yahoo_exact_isin_strict_same_source_count": len(strict),
            "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

def _write_us_finnhub_common_stock_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    _write_us_finnhub_named_type_audit(path, rows, bindings, resolver, "Common Stock")

def _write_us_finnhub_nvdr_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    _write_us_finnhub_named_type_audit(path, rows, bindings, resolver, "NVDR")

def _write_us_finnhub_sdr_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    _write_us_finnhub_named_type_audit(path, rows, bindings, resolver, "SDR")

def _write_us_finnhub_no_symbol_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    _write_us_finnhub_named_type_audit(
        path, rows, bindings, resolver, rejection_reason="FINNHUB_NO_SYMBOL"
    )


def _write_us_finnhub_no_symbol_xnys_preferred_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only audit for XNYS slash-symbol FINNHUB_NO_SYMBOL rows.

    Tests whether exact ISIN independently yields one scoped XNYS OpenFIGI preferred
    record and one Yahoo same-source USD/EQUITY candidate whose provider symbol is
    the slash-preferred notation counterpart. This is evidence only; no admission.
    """
    cohort = [
        r for r in rows
        if r.isin and TV_PREFIX_TO_MIC.get(r.prefix) == "XNYS" and "/" in str(r.symbol or "")
        and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED" and b.rejection_reason == "FINNHUB_NO_SYMBOL"
    ]
    jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"} for r in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(jobs) if jobs else []
    except ProviderError:
        mapped = [[] for _ in jobs]
    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            try: searches[token] = list(search_fn(token))
            except ProviderError: searches[token] = []
    symbols = list(dict.fromkeys(c.symbol for cs in searches.values() for c in cs if c.symbol))
    try: quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError: quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    records=[]
    for r, scoped in zip(cohort, mapped):
        b=bindings[r.tv_id]
        figis=sorted({x.figi for x in scoped if x.figi})
        preferred=[x for x in scoped if (x.security_type or "").upper()=="PUBLIC" and (x.security_type2 or "").upper()=="PREFERRED STOCK"]
        cs=searches.get(str(r.isin).upper().strip(), [])
        candidates=[]
        for c in cs:
            q=quotes.get(c.symbol)
            venue_ok=bool(q and yahoo_venue_compatible("XNYS", q))
            currency_ok=bool(q and (not r.currency or not q.currency or currency_compatible(r.currency,q.currency)))
            equity_ok=bool(q and (q.quote_type or "").upper()=="EQUITY" and (c.quote_type or "").upper()=="EQUITY")
            # Relation is checked, never used to construct a provider symbol.
            slash_counterpart = str(r.symbol or "").upper().replace("/", "-") == str(c.symbol or "").upper()
            strict=bool(q and venue_ok and currency_ok and equity_ok and slash_counterpart)
            candidates.append({"symbol":c.symbol,"search_exchange":c.exchange,"search_quote_type":c.quote_type,
                "quote_exchange":q.exchange if q else None,"quote_full_exchange_name":q.full_exchange_name if q else None,
                "quote_currency":q.currency if q else None,"quote_type":q.quote_type if q else None,
                "xnys_venue_compatible":venue_ok,"currency_compatible":currency_ok,"equity_compatible":equity_ok,
                "slash_preferred_counterpart":slash_counterpart,"strict_same_source_counterpart":strict})
        strict_count=sum(1 for x in candidates if x["strict_same_source_counterpart"])
        source_unique=len(figis)==1
        source_preferred=source_unique and len(preferred)==1
        if source_preferred and strict_count==1 and len(cs)==1:
            classification="XNYS_UNIQUE_SOURCE_PREFERRED_AND_UNIQUE_YAHOO_COUNTERPART"
        elif not source_unique:
            classification="XNYS_SOURCE_NOT_UNIQUE"
        elif not source_preferred:
            classification="XNYS_SOURCE_TAXONOMY_UNCONFIRMED"
        elif strict_count!=1 or len(cs)!=1:
            classification="YAHOO_COUNTERPART_UNCONFIRMED_OR_AMBIGUOUS"
        else:
            classification="EVIDENCE_INCOMPLETE"
        records.append({"diagnostic_only":True,"diagnostic_release":__version__,"tv_id":r.tv_id,"tv_symbol":r.symbol,
            "tv_isin":r.isin,"tv_currency":r.currency,"tv_type":r.tv_type,"tv_type_specs":list(r.type_specs),
            "rejection_reason":b.rejection_reason,"source_mic":"XNYS","source_scoped_figi_count":len(figis),
            "source_scoped_openfigi":[of_record(x) for x in scoped],"source_unique_public_preferred":source_preferred,
            "source_share_class_figi_present":any(x.share_class_figi for x in scoped),
            "yahoo_exact_isin_candidate_count":len(cs),"yahoo_strict_same_source_counterpart_count":strict_count,
            "yahoo_exact_isin_candidates":candidates,"classification":classification})
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as f:
        for record in records: f.write(json.dumps(record,ensure_ascii=False,sort_keys=True)+"\n")

def _write_us_xnas_source_binding_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only audit of rejected rows whose reviewed source MIC is XNAS."""
    cohort = [r for r in rows if r.isin and TV_PREFIX_TO_MIC.get(r.prefix) == "XNAS" and (b := bindings.get(r.tv_id)) is not None and b.status == "REJECTED"]
    unscoped_jobs = [{"idType": "ID_ISIN", "idValue": r.isin} for r in cohort]
    scoped_jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNAS"} for r in cohort]
    try:
        unscoped_mapped = resolver.openfigi.map_jobs(unscoped_jobs) if unscoped_jobs else []
    except ProviderError:
        unscoped_mapped = [[] for _ in unscoped_jobs]
    try:
        scoped_mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
    except ProviderError:
        scoped_mapped = [[] for _ in scoped_jobs]
    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try: searches[token] = list(search_fn(token))
                except ProviderError: searches[token] = []
    symbols = list(dict.fromkeys(c.symbol for cs in searches.values() for c in cs if c.symbol))
    try: quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError: quotes = {}
    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi, "share_class_figi": x.share_class_figi, "ticker": x.ticker, "name": x.name, "security_type": x.security_type, "security_type2": x.security_type2, "exch_code": x.exch_code}
    records = []
    for r, unscoped, scoped in zip(cohort, unscoped_mapped, scoped_mapped):
        b = bindings[r.tv_id]
        unscoped_shares = sorted({x.share_class_figi for x in unscoped if x.share_class_figi})
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        scoped_shares = sorted({x.share_class_figi for x in scoped if x.share_class_figi})
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        for c in cs:
            q = quotes.get(c.symbol)
            venue_ok = bool(q and yahoo_venue_compatible("XNAS", q))
            currency_ok = bool(q and (not r.currency or not q.currency or currency_compatible(r.currency, q.currency)))
            type_ok = bool(q and (q.quote_type or "").upper() == "EQUITY")
            search_equity = (c.quote_type or "").upper() == "EQUITY"
            strict = bool(q and venue_ok and currency_ok and type_ok and search_equity)
            candidates.append({"symbol": c.symbol, "search_exchange": c.exchange, "search_quote_type": c.quote_type, "quote_returned": q is not None, "quote_exchange": q.exchange if q else None, "quote_full_exchange_name": q.full_exchange_name if q else None, "quote_market": q.market if q else None, "quote_currency": q.currency if q else None, "quote_type": q.quote_type if q else None, "xnas_venue_compatible": venue_ok, "currency_compatible": currency_ok, "type_compatible": type_ok, "strict_xnas_contract": strict})
        strict_count = sum(1 for c in candidates if c["strict_xnas_contract"])
        if not unscoped: unscoped_status = "UNKNOWN"
        elif len(unscoped_shares) == 1: unscoped_status = "UNIQUE_SHARE_CLASS"
        elif not unscoped_shares: unscoped_status = "SHARE_CLASS_MISSING"
        else: unscoped_status = "AMBIGUOUS_SHARE_CLASS"
        if len(scoped_figis) == 1: scoped_status = "UNIQUE_FIGI"
        elif not scoped: scoped_status = "NO_MATCH"
        else: scoped_status = "AMBIGUOUS_OR_NO_FIGI"
        if scoped_status == "NO_MATCH" and unscoped_status == "UNIQUE_SHARE_CLASS" and strict_count == 1: classification = "XNAS_SCOPED_NO_MATCH_BUT_UNSCOPED_AND_YAHOO_STRICT"
        elif scoped_status == "UNIQUE_FIGI" and strict_count == 1: classification = "XNAS_SCOPED_AND_YAHOO_STRICT"
        elif strict_count > 1: classification = "YAHOO_STRICT_AMBIGUOUS"
        elif strict_count == 0: classification = "YAHOO_XNAS_CONTRACT_UNCONFIRMED"
        else: classification = "IDENTITY_EVIDENCE_INCOMPLETE"
        records.append({"diagnostic_only": True, "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin, "tv_currency": r.currency, "tv_type": r.tv_type, "tv_type_specs": list(r.type_specs), "finnhub_type": b.finnhub_type, "rejection_reason": b.rejection_reason, "source_mic": "XNAS", "unscoped_openfigi_status": unscoped_status, "unscoped_share_class_figis": unscoped_shares, "unscoped_openfigi": [of_record(x) for x in unscoped], "xnas_scoped_status": scoped_status, "xnas_scoped_figis": scoped_figis, "xnas_scoped_share_class_figis": scoped_shares, "xnas_scoped_openfigi": [of_record(x) for x in scoped], "yahoo_exact_isin_candidate_count": len(cs), "yahoo_strict_xnas_candidate_count": strict_count, "yahoo_exact_isin_candidates": candidates, "classification": classification})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records: f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_us_yahoo_mutualfund_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.4.17 diagnostic-only full-cohort decomposition of US Yahoo MUTUALFUND rejects.

    Keeps missing-ISIN rows, separates source identity proof from Yahoo provider
    evidence, and records venue / TV taxonomy / exact-ISIN outcomes. Nothing in
    this audit participates in resolver admission or cache policy.
    """
    cohort = [
        r for r in rows
        if (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "YAHOO_TYPE_MISMATCH:MUTUALFUND"
    ]

    unscoped_mapped = [[] for _ in cohort]
    scoped_mapped = [[] for _ in cohort]
    unscoped_jobs, unscoped_idx = [], []
    scoped_jobs, scoped_idx = [], []
    for i, r in enumerate(cohort):
        if not r.isin:
            continue
        unscoped_idx.append(i)
        unscoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin})
        mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if mic:
            scoped_idx.append(i)
            scoped_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
    try:
        mapped = resolver.openfigi.map_jobs(unscoped_jobs) if unscoped_jobs else []
        for i, xs in zip(unscoped_idx, mapped): unscoped_mapped[i] = list(xs)
    except ProviderError:
        pass
    try:
        mapped = resolver.openfigi.map_jobs(scoped_jobs) if scoped_jobs else []
        for i, xs in zip(scoped_idx, mapped): scoped_mapped[i] = list(xs)
    except ProviderError:
        pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            if not r.isin: continue
            token = str(r.isin).upper().strip()
            if token and token not in searches:
                try: searches[token] = list(search_fn(token))
                except ProviderError: searches[token] = []

    direct_symbols = list(dict.fromkeys(
        b.yahoo_symbol for r in cohort if (b := bindings[r.tv_id]).yahoo_symbol
    ))
    discovered_symbols = [c.symbol for cs in searches.values() for c in cs if c.symbol]
    symbols = list(dict.fromkeys(direct_symbols + discovered_symbols))
    try: quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError: quotes = {}
    try: charts = resolver.yahoo.chart_quotes(symbols) if symbols and hasattr(resolver.yahoo, "chart_quotes") else {}
    except ProviderError: charts = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    def q_record(q, r, source_mic):
        if q is None: return None
        return {"symbol": q.symbol, "exchange": q.exchange,
                "full_exchange_name": q.full_exchange_name, "market": q.market,
                "currency": q.currency, "quote_type": q.quote_type,
                "source_venue_compatible": bool(source_mic and yahoo_venue_compatible(source_mic, q)),
                "currency_compatible": bool(not r.currency or not q.currency or currency_compatible(r.currency, q.currency)),
                "equity_quote": (q.quote_type or "").upper() == "EQUITY"}

    records = []
    for i, r in enumerate(cohort):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        unscoped, scoped = unscoped_mapped[i], scoped_mapped[i]
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        scoped_shares = sorted({x.share_class_figi for x in scoped if x.share_class_figi})
        unscoped_shares = sorted({x.share_class_figi for x in unscoped if x.share_class_figi})
        token = str(r.isin or "").upper().strip()
        cs = searches.get(token, []) if token else []
        candidates = []
        strict = []
        for c in cs:
            q = quotes.get(c.symbol); ch = charts.get(c.symbol)
            qr = q_record(q, r, source_mic); chr_ = q_record(ch, r, source_mic)
            same = punctuation_key(c.symbol.split('.')[0]) == punctuation_key(r.symbol)
            rec = {"symbol": c.symbol, "search_exchange": c.exchange,
                   "search_quote_type": c.quote_type, "same_tv_ticker": same,
                   "quote": qr, "chart": chr_}
            candidates.append(rec)
            for provider_kind, meta in (("quote", qr), ("chart", chr_)):
                if same and meta and meta["source_venue_compatible"] and meta["currency_compatible"] and meta["equity_quote"]:
                    strict.append((c.symbol, provider_kind))
        strict = sorted(set(strict))
        strict_symbols = sorted({x[0] for x in strict})
        current_q = quotes.get(b.yahoo_symbol) if b.yahoo_symbol else None
        current_ch = charts.get(b.yahoo_symbol) if b.yahoo_symbol else None

        if not r.isin:
            source_proof = "MISSING_TV_ISIN"
        elif len(scoped_figis) == 1:
            source_proof = "SCOPED_UNIQUE_FIGI"
        elif len(scoped_figis) > 1:
            source_proof = "SCOPED_AMBIGUOUS"
        elif len(unscoped_shares) == 1:
            source_proof = "UNSCOPED_UNIQUE_SHARE_CLASS_ONLY"
        elif len(unscoped_shares) > 1:
            source_proof = "UNSCOPED_SHARE_CLASS_AMBIGUOUS"
        else:
            source_proof = "SOURCE_UNPROVEN"

        if not r.isin:
            classification = "MISSING_TV_ISIN"
        elif len(scoped_figis) == 1 and len(strict_symbols) == 1:
            classification = "UNIQUE_SHARE_CLASS_AND_ONE_SAME_SOURCE_EQUITY_CANDIDATE"
        elif len(strict_symbols) > 1:
            classification = "MULTIPLE_YAHOO_STRICT_CANDIDATES"
        elif len(scoped_figis) != 1:
            classification = "SOURCE_IDENTITY_EVIDENCE_INCOMPLETE"
        elif not cs:
            classification = "SOURCE_PROVEN_EXACT_ISIN_NOT_DISCOVERED"
        else:
            classification = "SOURCE_PROVEN_YAHOO_CONTRACT_UNCONFIRMED"

        records.append({
            "diagnostic_only": True, "diagnostic_release": "0.4.17",
            "tv_id": r.tv_id, "tv_prefix": r.prefix, "tv_symbol": r.symbol,
            "tv_isin": r.isin, "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "taxonomy_key": f"{r.tv_type}/{'|'.join(r.type_specs)}",
            "source_mic": source_mic, "source_proof": source_proof,
            "rejection_reason": b.rejection_reason, "resolver_yahoo_symbol": b.yahoo_symbol,
            "resolver_yahoo_exchange": b.yahoo_exchange, "resolver_yahoo_currency": b.yahoo_currency,
            "resolver_yahoo_quote_type": b.yahoo_quote_type,
            "current_yahoo_quote": q_record(current_q, r, source_mic),
            "current_yahoo_chart": q_record(current_ch, r, source_mic),
            "unscoped_share_class_figis": unscoped_shares,
            "unscoped_openfigi_count": len(unscoped), "unscoped_openfigi": [of_record(x) for x in unscoped],
            "source_scoped_openfigi_status": "NO_MATCH" if not scoped else ("UNIQUE_FIGI" if len(scoped_figis) == 1 else "AMBIGUOUS"),
            "source_scoped_openfigi_count": len(scoped), "source_scoped_openfigi": [of_record(x) for x in scoped],
            "source_scoped_share_class_figis": scoped_shares,
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_same_source_equity_candidate_count": len(strict_symbols),
            "yahoo_strict_same_source_observation_count": len(strict),
            "yahoo_strict_same_source_observations": [{"symbol": x[0], "provider": x[1]} for x in strict],
            "yahoo_exact_isin_candidates": candidates, "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")



def _write_us_finnhub_public_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only exact-ISIN/source-binding audit for US Finnhub PUBLIC rejects."""
    cohort = [
        r for r in rows
        if r.isin
        and (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:PUBLIC"
    ]
    unscoped_jobs = [{"idType": "ID_ISIN", "idValue": r.isin} for r in cohort]
    scoped_jobs = [
        {"idType": "ID_ISIN", "idValue": r.isin, "micCode": TV_PREFIX_TO_MIC[r.prefix]}
        if TV_PREFIX_TO_MIC.get(r.prefix) else None
        for r in cohort
    ]
    try:
        unscoped_mapped = resolver.openfigi.map_jobs(unscoped_jobs) if unscoped_jobs else []
    except ProviderError:
        unscoped_mapped = [[] for _ in unscoped_jobs]
    scoped_mapped = [[] for _ in cohort]
    real_scoped = [(i, job) for i, job in enumerate(scoped_jobs) if job]
    if real_scoped:
        try:
            mapped = resolver.openfigi.map_jobs([job for _, job in real_scoped])
            for (i, _), result in zip(real_scoped, mapped):
                scoped_mapped[i] = result
        except ProviderError:
            pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [b.yahoo_symbol for r in cohort if (b := bindings[r.tv_id]).yahoo_symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    records = []
    for r, unscoped, scoped in zip(cohort, unscoped_mapped, scoped_mapped):
        b = bindings[r.tv_id]
        source_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        shares = sorted({x.share_class_figi for x in unscoped if x.share_class_figi})
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        scoped_shares = sorted({x.share_class_figi for x in scoped if x.share_class_figi})
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        for c in cs:
            q = quotes.get(c.symbol)
            venue_ok = bool(q and source_mic and yahoo_venue_compatible(source_mic, q))
            currency_ok = bool(q and (not r.currency or not q.currency or currency_compatible(r.currency, q.currency)))
            equity_ok = bool(q and (q.quote_type or "").upper() == "EQUITY")
            search_equity = (c.quote_type or "").upper() == "EQUITY"
            ticker_ok = punctuation_key(c.symbol.split('.')[0]) == punctuation_key(r.symbol)
            candidates.append({
                "symbol": c.symbol, "search_exchange": c.exchange,
                "search_quote_type": c.quote_type, "quote_returned": q is not None,
                "quote_exchange": q.exchange if q else None,
                "quote_full_exchange_name": q.full_exchange_name if q else None,
                "quote_market": q.market if q else None,
                "quote_currency": q.currency if q else None,
                "quote_type": q.quote_type if q else None,
                "same_tv_ticker": ticker_ok, "source_venue_compatible": venue_ok,
                "currency_compatible": currency_ok, "equity_quote": equity_ok,
                "strict_same_source_equity": bool(ticker_ok and venue_ok and currency_ok and equity_ok and search_equity),
            })
        strict = [c for c in candidates if c["strict_same_source_equity"]]
        if len(scoped_figis) == 1:
            scoped_status = "UNIQUE_FIGI"
        elif not scoped:
            scoped_status = "NO_MATCH"
        else:
            scoped_status = "AMBIGUOUS"
        if not unscoped:
            unscoped_status = "UNKNOWN"
        elif len(shares) == 1:
            unscoped_status = "UNIQUE_SHARE_CLASS"
        elif not shares:
            unscoped_status = "SHARE_CLASS_MISSING"
        else:
            unscoped_status = "AMBIGUOUS_SHARE_CLASS"
        if scoped_status == "UNIQUE_FIGI" and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_STRICT"
        elif scoped_status == "NO_MATCH" and unscoped_status == "UNIQUE_SHARE_CLASS" and len(strict) == 1:
            classification = "SOURCE_SCOPED_NO_MATCH_BUT_UNSCOPED_AND_YAHOO_STRICT"
        elif len(strict) > 1:
            classification = "YAHOO_STRICT_AMBIGUOUS"
        elif not strict:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        else:
            classification = "IDENTITY_EVIDENCE_INCOMPLETE"
        records.append({
            "diagnostic_only": True, "diagnostic_release": "0.4.27",
            "tv_id": r.tv_id, "tv_symbol": r.symbol,
            "tv_isin": r.isin, "tv_currency": r.currency, "tv_type": r.tv_type,
            "tv_type_specs": list(r.type_specs), "tv_type_kind": tv_type_kind(r),
            "source_mic": source_mic, "finnhub_type": b.finnhub_type,
            "rejection_reason": b.rejection_reason,
            "resolver_yahoo_symbol": b.yahoo_symbol, "resolver_yahoo_exchange": b.yahoo_exchange,
            "resolver_yahoo_currency": b.yahoo_currency, "resolver_yahoo_quote_type": b.yahoo_quote_type,
            "unscoped_openfigi_status": unscoped_status,
            "unscoped_share_class_figis": shares, "unscoped_openfigi": [of_record(x) for x in unscoped],
            "source_scoped_openfigi_status": scoped_status,
            "source_scoped_figis": scoped_figis, "source_scoped_share_class_figis": scoped_shares,
            "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_strict_same_source_equity_candidate_count": len(strict),
            "yahoo_exact_isin_candidates": candidates, "classification": classification,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")



def _write_us_finnhub_public_xnas_segment_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only XNAS segment proof audit for Finnhub PUBLIC preferred rejects."""
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        _write_us_finnhub_public_audit(tmp_path, rows, bindings, resolver)
        base = [json.loads(line) for line in tmp_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    finally:
        tmp_path.unlink(missing_ok=True)

    segment_map = {"NASDAQ/NGS": "NMS", "NASDAQ/NGM": "NGM", "NASDAQ/NCM": "NCM"}
    records = []
    for rec in base:
        if rec.get("source_mic") != "XNAS" or rec.get("tv_type_kind") != "PREFERRED":
            continue
        unscoped = rec.get("unscoped_openfigi") or []
        strict = [c for c in rec.get("yahoo_exact_isin_candidates", []) if c.get("strict_same_source_equity")]
        of = unscoped[0] if len(unscoped) == 1 else None
        exch = of.get("exch_code") if of else None
        expected = segment_map.get(exch)
        yahoo_exchange = strict[0].get("quote_exchange") if len(strict) == 1 else None
        segment_consistent = bool(expected and yahoo_exchange == expected)
        identity_contract = bool(
            rec.get("source_scoped_openfigi_status") == "NO_MATCH"
            and of
            and of.get("security_type") == "PUBLIC"
            and of.get("security_type2") == "Preferred Stock"
            and expected
            and len(strict) == 1
        )
        rec.update({
            "diagnostic_release": __version__,
            "xnas_segment_expected_yahoo_exchange": expected,
            "xnas_segment_actual_yahoo_exchange": yahoo_exchange,
            "xnas_segment_consistent": segment_consistent,
            "xnas_segment_identity_contract": identity_contract,
            "xnas_segment_strict_contract": bool(identity_contract and segment_consistent),
            "classification": ("XNAS_SEGMENT_STRICT" if identity_contract and segment_consistent
                               else "XNAS_SEGMENT_MISMATCH" if identity_contract
                               else "XNAS_SEGMENT_EVIDENCE_INCOMPLETE"),
        })
        records.append(rec)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

_V0418_FINNHUB_RESIDUAL_TYPES = {
    "Closed-End Fund", "Ltd Part", "CDI", "Royalty Trst", "Stapled Security",
    "Preference", "GDR", "Common Stock", "NVDR", "SDR",
}


def _write_us_finnhub_residual_taxonomy_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """v0.4.18 diagnostic-only audit of the remaining reviewed Finnhub taxonomy cohorts."""
    cohort = [
        r for r in rows
        if (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason.startswith("FINNHUB_TYPE_MISMATCH:")
        and b.rejection_reason.removeprefix("FINNHUB_TYPE_MISMATCH:") in _V0418_FINNHUB_RESIDUAL_TYPES
    ]

    try:
        universe = resolver.cache.load_finnhub_universe()
    except Exception:
        universe = []
    norm_index = {}
    for raw in universe:
        sym = str(raw.get("symbol") or "").upper().strip()
        for key in symbol_index_keys(sym) if sym else []:
            norm_index.setdefault(key, []).append(raw)

    source_mics, source_origins, matching_rows = [], [], {}
    for r in cohort:
        raws, seen = [], set()
        for key in symbol_index_keys(r.symbol):
            for raw in norm_index.get(key, []):
                sig = json.dumps(raw, sort_keys=True, default=str)
                if sig not in seen:
                    seen.add(sig); raws.append(raw)
        matching_rows[r.tv_id] = raws
        direct = TV_PREFIX_TO_MIC.get(r.prefix)
        if direct:
            source_mics.append(direct); source_origins.append("TV_PREFIX_REVIEWED")
        else:
            mics = sorted({str(x.get("mic") or "").upper().strip() for x in raws if x.get("mic")})
            if len(mics) == 1:
                source_mics.append(mics[0]); source_origins.append("FINNHUB_EXACT_SYMBOL_UNIQUE_MIC")
            else:
                source_mics.append(None); source_origins.append("UNRESOLVED")

    unscoped = [[] for _ in cohort]; scoped = [[] for _ in cohort]
    uj = [(i, {"idType":"ID_ISIN","idValue":r.isin}) for i,r in enumerate(cohort) if r.isin]
    sj = [(i, {"idType":"ID_ISIN","idValue":r.isin,"micCode":mic}) for i,(r,mic) in enumerate(zip(cohort,source_mics)) if r.isin and mic]
    for jobs, dest in ((uj, unscoped), (sj, scoped)):
        if jobs:
            try:
                mapped = resolver.openfigi.map_jobs([j for _,j in jobs])
                for (i,_), xs in zip(jobs,mapped): dest[i] = list(xs)
            except ProviderError:
                pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin or "").upper().strip()
            if token and token not in searches:
                try: searches[token] = list(search_fn(token))
                except ProviderError: searches[token] = []
    symbols = list(dict.fromkeys(
        [b.yahoo_symbol for r in cohort if (b := bindings[r.tv_id]).yahoo_symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try: quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError: quotes = {}

    def of_record(x):
        return {"figi":x.figi,"composite_figi":x.composite_figi,"share_class_figi":x.share_class_figi,
                "ticker":x.ticker,"name":x.name,"security_type":x.security_type,
                "security_type2":x.security_type2,"exch_code":x.exch_code}

    records=[]
    for r, us, ss, mic, origin in zip(cohort,unscoped,scoped,source_mics,source_origins):
        b=bindings[r.tv_id]
        u_shares=sorted({x.share_class_figi for x in us if x.share_class_figi})
        s_figis=sorted({x.figi for x in ss if x.figi})
        s_shares=sorted({x.share_class_figi for x in ss if x.share_class_figi})
        u_status="UNKNOWN" if not us else ("UNIQUE_SHARE_CLASS" if len(u_shares)==1 else ("SHARE_CLASS_MISSING" if not u_shares else "AMBIGUOUS_SHARE_CLASS"))
        s_status="UNIQUE_FIGI" if len(s_figis)==1 else ("NO_MATCH" if not ss else "AMBIGUOUS")
        cs=searches.get(str(r.isin or "").upper().strip(),[])
        candidates=[]
        for c in cs:
            q=quotes.get(c.symbol)
            ticker_ok=punctuation_key(c.symbol.split('.')[0]) == punctuation_key(r.symbol)
            venue_ok=bool(q and mic and yahoo_venue_compatible(mic,q))
            currency_ok=bool(q and (not r.currency or not q.currency or currency_compatible(r.currency,q.currency)))
            equity_ok=bool(q and (q.quote_type or "").upper()=="EQUITY")
            search_equity=(c.quote_type or "").upper()=="EQUITY"
            candidates.append({"symbol":c.symbol,"search_exchange":c.exchange,"search_quote_type":c.quote_type,
                "quote_returned":q is not None,"quote_exchange":q.exchange if q else None,
                "quote_full_exchange_name":q.full_exchange_name if q else None,"quote_market":q.market if q else None,
                "quote_currency":q.currency if q else None,"quote_type":q.quote_type if q else None,
                "same_tv_ticker":ticker_ok,"source_venue_compatible":venue_ok,"currency_compatible":currency_ok,
                "equity_quote":equity_ok,"strict_same_source_equity":bool(ticker_ok and venue_ok and currency_ok and equity_ok and search_equity)})
        strict=[x for x in candidates if x["strict_same_source_equity"]]
        if not r.isin: classification="MISSING_TV_ISIN"
        elif s_status=="UNIQUE_FIGI" and len(strict)==1: classification="SOURCE_SCOPED_AND_YAHOO_STRICT"
        elif s_status=="NO_MATCH" and u_status=="UNIQUE_SHARE_CLASS" and len(strict)==1: classification="SOURCE_SCOPED_NO_MATCH_BUT_UNSCOPED_AND_YAHOO_STRICT"
        elif len(strict)>1: classification="YAHOO_STRICT_AMBIGUOUS"
        elif not strict: classification="YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        else: classification="IDENTITY_EVIDENCE_INCOMPLETE"
        records.append({"diagnostic_only":True,"diagnostic_release":"0.4.18","tv_id":r.tv_id,"tv_symbol":r.symbol,
            "tv_isin":r.isin,"tv_currency":r.currency,"tv_type":r.tv_type,"tv_type_specs":list(r.type_specs),
            "tv_type_kind":tv_type_kind(r),"finnhub_type":(b.finnhub_type or b.rejection_reason.removeprefix("FINNHUB_TYPE_MISMATCH:")),"rejection_reason":b.rejection_reason,
            "source_mic":mic,"source_mic_origin":origin,"finnhub_matching_symbol_rows":matching_rows[r.tv_id],
            "unscoped_openfigi_status":u_status,"unscoped_share_class_figis":u_shares,"unscoped_openfigi":[of_record(x) for x in us],
            "source_scoped_openfigi_status":s_status,"source_scoped_figis":s_figis,"source_scoped_share_class_figis":s_shares,
            "source_scoped_openfigi":[of_record(x) for x in ss],"yahoo_exact_isin_candidate_count":len(cs),
            "yahoo_strict_same_source_equity_candidate_count":len(strict),"yahoo_exact_isin_candidates":candidates,
            "classification":classification})
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w",encoding="utf-8") as f:
        for rec in records: f.write(json.dumps(rec,ensure_ascii=False,sort_keys=True)+"\n")


def _write_us_finnhub_unknown_type_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only evidence audit for US FINNHUB_TYPE_MISMATCH:? rejects."""
    # Full rejection cohort: missing ISIN is diagnostic evidence and must not
    # silently remove a rejected row from this audit.
    cohort = [
        r for r in rows
        if (b := bindings.get(r.tv_id)) is not None
        and b.status == "REJECTED"
        and b.rejection_reason == "FINNHUB_TYPE_MISMATCH:?"
    ]
    # Preserve the exact Finnhub rows that produced the unknown taxonomy.
    try:
        universe = resolver.cache.load_finnhub_universe()
    except Exception:
        universe = []
    norm_index = {}
    for raw in universe:
        sym = str(raw.get("symbol") or "").upper().strip()
        for key in symbol_index_keys(sym) if sym else []:
            norm_index.setdefault(key, []).append(raw)

    # Resolve source MIC before scoped diagnostics. For provider namespaces with
    # no reviewed direct mapping (notably TradingView OTC), accept a diagnostic
    # MIC only when all exact-symbol Finnhub universe rows agree on one MIC.
    matching_rows_by_tv_id = {}
    source_mics = []
    source_mic_origins = []
    for r in cohort:
        raw_rows, seen = [], set()
        for key in symbol_index_keys(r.symbol):
            for raw in norm_index.get(key, []):
                marker = json.dumps(raw, sort_keys=True, default=str)
                if marker not in seen:
                    seen.add(marker); raw_rows.append(raw)
        matching_rows_by_tv_id[r.tv_id] = raw_rows
        direct_mic = TV_PREFIX_TO_MIC.get(r.prefix)
        if direct_mic:
            source_mics.append(direct_mic)
            source_mic_origins.append("TV_PREFIX_REVIEWED")
        else:
            mics = sorted({str(x.get("mic") or "").upper().strip() for x in raw_rows if x.get("mic")})
            if len(mics) == 1:
                source_mics.append(mics[0])
                source_mic_origins.append("FINNHUB_EXACT_SYMBOL_UNIQUE_MIC")
            else:
                source_mics.append(None)
                source_mic_origins.append("UNRESOLVED")

    unscoped_jobs = [
        {"idType": "ID_ISIN", "idValue": r.isin} if r.isin else None
        for r in cohort
    ]
    scoped_jobs = [
        {"idType": "ID_ISIN", "idValue": r.isin, "micCode": source_mic}
        if r.isin and source_mic else None
        for r, source_mic in zip(cohort, source_mics)
    ]
    unscoped_mapped = [[] for _ in cohort]
    real_unscoped = [(i, job) for i, job in enumerate(unscoped_jobs) if job]
    if real_unscoped:
        try:
            mapped = resolver.openfigi.map_jobs([job for _, job in real_unscoped])
            for (i, _), result in zip(real_unscoped, mapped):
                unscoped_mapped[i] = result
        except ProviderError:
            pass
    scoped_mapped = [[] for _ in cohort]
    real_scoped = [(i, job) for i, job in enumerate(scoped_jobs) if job]
    if real_scoped:
        try:
            mapped = resolver.openfigi.map_jobs([job for _, job in real_scoped])
            for (i, _), result in zip(real_scoped, mapped):
                scoped_mapped[i] = result
        except ProviderError:
            pass

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin or "").upper().strip()
            if not token:
                continue
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
    symbols = list(dict.fromkeys(
        [b.yahoo_symbol for r in cohort if (b := bindings[r.tv_id]).yahoo_symbol]
        + [c.symbol for cs in searches.values() for c in cs if c.symbol]
    ))
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    records = []
    for r, unscoped, scoped, source_mic, source_mic_origin in zip(
        cohort, unscoped_mapped, scoped_mapped, source_mics, source_mic_origins
    ):
        b = bindings[r.tv_id]
        shares = sorted({x.share_class_figi for x in unscoped if x.share_class_figi})
        scoped_figis = sorted({x.figi for x in scoped if x.figi})
        scoped_shares = sorted({x.share_class_figi for x in scoped if x.share_class_figi})
        raw_rows = matching_rows_by_tv_id[r.tv_id]
        cs = searches.get(str(r.isin or "").upper().strip(), [])
        candidates = []
        for c in cs:
            q = quotes.get(c.symbol)
            ticker_ok = punctuation_key(c.symbol.split('.')[0]) == punctuation_key(r.symbol)
            venue_ok = bool(q and source_mic and yahoo_venue_compatible(source_mic, q))
            currency_ok = bool(q and (not r.currency or not q.currency or currency_compatible(r.currency, q.currency)))
            equity_ok = bool(q and (q.quote_type or "").upper() == "EQUITY")
            search_equity = (c.quote_type or "").upper() == "EQUITY"
            candidates.append({
                "symbol": c.symbol, "search_exchange": c.exchange, "search_quote_type": c.quote_type,
                "quote_returned": q is not None, "quote_exchange": q.exchange if q else None,
                "quote_full_exchange_name": q.full_exchange_name if q else None,
                "quote_market": q.market if q else None, "quote_currency": q.currency if q else None,
                "quote_type": q.quote_type if q else None, "same_tv_ticker": ticker_ok,
                "source_venue_compatible": venue_ok, "currency_compatible": currency_ok,
                "equity_quote": equity_ok,
                "strict_same_source_equity": bool(ticker_ok and venue_ok and currency_ok and equity_ok and search_equity),
            })
        strict = [c for c in candidates if c["strict_same_source_equity"]]
        scoped_status = "UNIQUE_FIGI" if len(scoped_figis) == 1 else ("NO_MATCH" if not scoped else "AMBIGUOUS")
        unscoped_status = "UNKNOWN" if not unscoped else ("UNIQUE_SHARE_CLASS" if len(shares) == 1 else ("SHARE_CLASS_MISSING" if not shares else "AMBIGUOUS_SHARE_CLASS"))
        if not r.isin:
            classification = "MISSING_TV_ISIN"
        elif scoped_status == "UNIQUE_FIGI" and len(strict) == 1:
            classification = "SOURCE_SCOPED_AND_YAHOO_STRICT"
        elif scoped_status == "NO_MATCH" and unscoped_status == "UNIQUE_SHARE_CLASS" and len(strict) == 1:
            classification = "SOURCE_SCOPED_NO_MATCH_BUT_UNSCOPED_AND_YAHOO_STRICT"
        elif len(strict) > 1:
            classification = "YAHOO_STRICT_AMBIGUOUS"
        elif not strict:
            classification = "YAHOO_SOURCE_CONTRACT_UNCONFIRMED"
        else:
            classification = "IDENTITY_EVIDENCE_INCOMPLETE"
        records.append({
            "diagnostic_only": True, "diagnostic_release": "0.4.28",
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type, "tv_type_specs": list(r.type_specs),
            "tv_type_kind": tv_type_kind(r), "source_mic": source_mic,
            "source_mic_origin": source_mic_origin, "finnhub_type": b.finnhub_type,
            "finnhub_symbol": b.finnhub_symbol, "finnhub_matching_symbol_rows": raw_rows,
            "rejection_reason": b.rejection_reason, "resolver_yahoo_symbol": b.yahoo_symbol,
            "resolver_yahoo_exchange": b.yahoo_exchange, "resolver_yahoo_currency": b.yahoo_currency,
            "resolver_yahoo_quote_type": b.yahoo_quote_type, "unscoped_openfigi_status": unscoped_status,
            "unscoped_share_class_figis": shares, "unscoped_openfigi": [of_record(x) for x in unscoped],
            "source_scoped_openfigi_status": scoped_status, "source_scoped_figis": scoped_figis,
            "source_scoped_share_class_figis": scoped_shares, "source_scoped_openfigi": [of_record(x) for x in scoped],
            "yahoo_exact_isin_candidate_count": len(cs),
            "yahoo_strict_same_source_equity_candidate_count": len(strict),
            "yahoo_exact_isin_candidates": candidates, "classification": classification,
            "v428_cohort_key": {
                "source_mic": source_mic,
                "tv_type_kind": tv_type_kind(r),
                "tv_type": r.tv_type,
                "tv_type_specs": list(r.type_specs),
                "openfigi_scoped_status": scoped_status,
                "openfigi_scoped_taxonomy": sorted({
                    f"{x.security_type or '?'}/{x.security_type2 or '?'}" for x in scoped
                }),
                "openfigi_unscoped_status": unscoped_status,
                "yahoo_strict_same_source_equity_count": len(strict),
            },
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_us_finnhub_unknown_type_residual_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only v0.3.90 audit of residual FINNHUB_TYPE_MISMATCH:? rows.

    Reuses the established exact-ISIN/source evidence audit, then adds a
    deterministic explanation of why each residual row is outside or blocked
    by the v0.3.87 OOTC preferred empty-type PUBLIC rescue contract.
    """
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        base = Path(td) / "unknown.jsonl"
        _write_us_finnhub_unknown_type_audit(base, rows, bindings, resolver)
        records = [json.loads(line) for line in base.read_text(encoding="utf-8").splitlines() if line.strip()]

    for rec in records:
        specs = {str(x).lower() for x in rec.get("tv_type_specs") or [] if x}
        raw_rows = rec.get("finnhub_matching_symbol_rows") or []
        exact_same_currency = []
        seen = set()
        tv_symbol = str(rec.get("tv_symbol") or "").upper().strip()
        tv_currency = rec.get("tv_currency")
        for raw in raw_rows:
            if str(raw.get("symbol") or "").upper().strip() != tv_symbol:
                continue
            if not currency_compatible(tv_currency, raw.get("currency")):
                continue
            key = (raw.get("symbol"), raw.get("mic"), raw.get("currency"), raw.get("type"), raw.get("figi"), raw.get("shareClassFIGI"))
            if key not in seen:
                seen.add(key); exact_same_currency.append(raw)

        scoped = rec.get("source_scoped_openfigi") or []
        public_pref_figis = sorted({x.get("figi") for x in scoped if x.get("figi") and str(x.get("security_type") or "").lower() == "public" and str(x.get("security_type2") or "").lower() in {"preferred stock", "preferred", "preference"}})
        candidates = rec.get("yahoo_exact_isin_candidates") or []

        if rec.get("tv_type_kind") != "PREFERRED" or "preferred" not in specs:
            reason = "OUTSIDE_V087_TV_PREFERRED_COHORT"
        elif len(exact_same_currency) != 1:
            reason = "FINNHUB_EXACT_SOURCE_NOT_UNIQUE"
        elif str(exact_same_currency[0].get("mic") or "").upper().strip() != "OOTC":
            reason = "FINNHUB_SOURCE_NOT_OOTC"
        elif str(exact_same_currency[0].get("type") or "").strip():
            reason = "FINNHUB_TYPE_NOT_EMPTY"
        elif len(public_pref_figis) != 1:
            reason = "OPENFIGI_OOTC_PUBLIC_PREFERRED_NOT_UNIQUE"
        elif len(candidates) != 1:
            reason = "YAHOO_EXACT_ISIN_NOT_UNIQUE"
        elif not candidates[0].get("same_tv_ticker"):
            reason = "YAHOO_SYMBOL_MISMATCH"
        elif not candidates[0].get("source_venue_compatible"):
            reason = "YAHOO_OOTC_VENUE_UNCONFIRMED"
        elif not candidates[0].get("currency_compatible"):
            reason = "YAHOO_CURRENCY_UNCONFIRMED"
        elif not candidates[0].get("equity_quote") or str(candidates[0].get("search_quote_type") or "").upper() != "EQUITY":
            reason = "YAHOO_EQUITY_UNCONFIRMED"
        else:
            reason = "CURRENTLY_SATISFIES_V087_CONTRACT_PROVIDER_DRIFT_OR_CACHE_TIMING"
        rec["v090_residual_reason"] = reason
        rec["v087_tv_cohort_eligible"] = rec.get("tv_type_kind") == "PREFERRED" and "preferred" in specs
        rec["v087_finnhub_exact_same_currency_count"] = len(exact_same_currency)
        rec["v087_openfigi_public_preferred_figi_count"] = len(public_pref_figis)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n")

def _write_us_ootc_preferred_empty_type_rescue_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only provenance audit for v0.3.87 OOTC preferred rescue matches."""
    cohort = [
        r for r in rows
        if r.isin
        and (b := bindings.get(r.tv_id)) is not None
        and b.status == "VERIFIED"
        and b.mapping_method == "US_OOTC_PREFERRED_FINNHUB_EMPTY_TYPE_EXACT_ISIN"
    ]
    try:
        universe = resolver.cache.load_finnhub_universe()
    except Exception:
        universe = []

    exact_rows = {}
    for r in cohort:
        seen, found = set(), []
        for raw in universe:
            if str(raw.get("symbol") or "").upper().strip() != str(r.symbol or "").upper().strip():
                continue
            if not currency_compatible(r.currency, raw.get("currency")):
                continue
            marker = json.dumps(raw, sort_keys=True, default=str)
            if marker not in seen:
                seen.add(marker); found.append(raw)
        exact_rows[r.tv_id] = found

    jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in cohort]
    try:
        mapped = resolver.openfigi.map_jobs(jobs) if jobs else []
    except ProviderError:
        mapped = [[] for _ in jobs]

    search_fn = getattr(resolver.yahoo, "search_exact_isin", None)
    searches = {}
    if callable(search_fn):
        for r in cohort:
            token = str(r.isin).upper().strip()
            try:
                searches[token] = list(search_fn(token))
            except ProviderError:
                searches[token] = []
    symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
    try:
        quotes = resolver.yahoo.quotes(symbols) if symbols else {}
    except ProviderError:
        quotes = {}

    def of_record(x):
        return {"figi": x.figi, "composite_figi": x.composite_figi,
                "share_class_figi": x.share_class_figi, "ticker": x.ticker,
                "name": x.name, "security_type": x.security_type,
                "security_type2": x.security_type2, "exch_code": x.exch_code}

    records = []
    for r, scoped in zip(cohort, mapped):
        b = bindings[r.tv_id]
        public_preferred = [x for x in scoped if (
            (x.security_type or "").strip().lower() == "public"
            and (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
        )]
        figis = sorted({x.figi for x in public_preferred if x.figi})
        raw_rows = exact_rows[r.tv_id]
        finnhub_contract = bool(
            len(raw_rows) == 1
            and str(raw_rows[0].get("mic") or "").upper().strip() == "OOTC"
            and not str(raw_rows[0].get("type") or "").strip()
        )
        cs = searches.get(str(r.isin).upper().strip(), [])
        candidates = []
        for c in cs:
            q = quotes.get(c.symbol)
            ticker_ok = c.symbol == r.symbol
            venue_ok = bool(q and yahoo_venue_compatible("OOTC", q))
            currency_ok = bool(q and q.currency and currency_compatible(r.currency, q.currency))
            equity_ok = bool(q and (q.quote_type or "").upper() == "EQUITY")
            search_equity = (c.quote_type or "").upper() == "EQUITY"
            candidates.append({
                "symbol": c.symbol, "search_exchange": c.exchange, "search_quote_type": c.quote_type,
                "quote_returned": q is not None, "quote_exchange": q.exchange if q else None,
                "quote_full_exchange_name": q.full_exchange_name if q else None,
                "quote_market": q.market if q else None, "quote_currency": q.currency if q else None,
                "quote_type": q.quote_type if q else None, "exact_tv_ticker": ticker_ok,
                "ootc_venue_compatible": venue_ok, "currency_compatible": currency_ok,
                "equity_quote": equity_ok,
                "strict_contract": bool(ticker_ok and venue_ok and currency_ok and equity_ok and search_equity),
            })
        strict = [x for x in candidates if x["strict_contract"]]
        openfigi_contract = len(figis) == 1
        yahoo_contract = len(cs) == 1 and len(strict) == 1
        records.append({
            "diagnostic_only": True, "audit": "V087_RESCUE_PROVENANCE",
            "tv_id": r.tv_id, "tv_symbol": r.symbol, "tv_isin": r.isin,
            "tv_currency": r.currency, "tv_type": r.tv_type, "tv_type_specs": list(r.type_specs),
            "mapping_method": b.mapping_method, "resolver_version": b.resolver_version,
            "resolved_mic": b.resolved_mic, "source_mic": b.source_mic, "target_mic": b.target_mic,
            "finnhub_exact_symbol_rows": raw_rows, "finnhub_contract_confirmed": finnhub_contract,
            "openfigi_source_scoped": [of_record(x) for x in scoped],
            "openfigi_public_preferred_figis": figis, "openfigi_contract_confirmed": openfigi_contract,
            "yahoo_exact_isin_candidate_count": len(cs), "yahoo_exact_isin_candidates": candidates,
            "yahoo_contract_confirmed": yahoo_contract,
            "full_v087_contract_confirmed": bool(finnhub_contract and openfigi_contract and yahoo_contract),
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_us_v087_slmnp_admission_audit(path: Path, rows, bindings: dict, resolver: BatchResolver) -> None:
    """Diagnostic-only targeted audit for the v0.3.87 SLMNP admission provenance.

    The v0.3.87 mapping method is reachable only after an exact-ISIN Yahoo
    search returned exactly one exact-ticker EQUITY candidate and its quote
    passed OOTC venue/currency/EQUITY checks.  Search candidates were not
    persisted, so this audit records the cached VERIFIED binding plus two
    fresh exact-ISIN observations separated by a Yahoo run-cache reset.
    """
    target = next((r for r in rows if str(r.symbol or '').upper() == 'SLMNP' and r.isin), None)
    records = []
    if target is not None:
        b = bindings.get(target.tv_id)
        search_fn = getattr(resolver.yahoo, 'search_exact_isin', None)
        def snap(cs):
            return [{
                'symbol': c.symbol, 'exchange': c.exchange, 'quote_type': c.quote_type,
                'short_name': c.short_name, 'long_name': c.long_name,
            } for c in cs]
        first = []
        second = []
        first_error = second_error = None
        if callable(search_fn):
            try:
                first = list(search_fn(str(target.isin).upper().strip()))
            except ProviderError as exc:
                first_error = str(exc)
            # Force a second network observation rather than reusing search memo.
            try:
                resolver.yahoo.reset_run_cache()
                second = list(search_fn(str(target.isin).upper().strip()))
            except ProviderError as exc:
                second_error = str(exc)
        quote = {}
        try:
            qmap = resolver.yahoo.quotes([target.symbol])
            q = qmap.get(target.symbol)
            if q is not None:
                quote = {
                    'symbol': q.symbol, 'exchange': q.exchange,
                    'full_exchange_name': q.full_exchange_name, 'market': q.market,
                    'currency': q.currency, 'quote_type': q.quote_type,
                    'ootc_venue_compatible': yahoo_venue_compatible('OOTC', q),
                    'currency_compatible': bool(q.currency and currency_compatible(target.currency, q.currency)),
                }
        except ProviderError as exc:
            quote = {'error': str(exc)}
        method = getattr(b, 'mapping_method', None) if b else None
        records.append({
            'diagnostic_only': True, 'audit': 'V087_SLMNP_ADMISSION_PROVENANCE',
            'tv_id': target.tv_id, 'tv_symbol': target.symbol, 'tv_isin': target.isin,
            'tv_currency': target.currency, 'binding_status': getattr(b, 'status', None) if b else None,
            'mapping_method': method, 'binding_resolver_version': getattr(b, 'resolver_version', None) if b else None,
            'binding_yahoo_symbol': getattr(b, 'yahoo_symbol', None) if b else None,
            'binding_yahoo_exchange': getattr(b, 'yahoo_exchange', None) if b else None,
            'binding_yahoo_currency': getattr(b, 'yahoo_currency', None) if b else None,
            'binding_yahoo_quote_type': getattr(b, 'yahoo_quote_type', None) if b else None,
            'v087_code_path_requires_exact_isin_search': method == 'US_OOTC_PREFERRED_FINNHUB_EMPTY_TYPE_EXACT_ISIN',
            'search_candidate_persisted_at_admission': False,
            'fresh_exact_isin_search_1': snap(first), 'fresh_exact_isin_search_1_error': first_error,
            'fresh_exact_isin_search_2_after_memo_reset': snap(second), 'fresh_exact_isin_search_2_error': second_error,
            'fresh_direct_symbol_quote': quote,
            'interpretation': (
                'CURRENT_SEARCH_DRIFT_IF_BOTH_EMPTY' if not first and not second and method == 'US_OOTC_PREFERRED_FINNHUB_EMPTY_TYPE_EXACT_ISIN'
                else 'CURRENT_SEARCH_AVAILABLE_OR_INCONCLUSIVE'
            ),
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
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
        if args.nyse_preferred_symbol_audit:
            audit_path = Path(args.nyse_preferred_symbol_audit)
            _write_us_nyse_preferred_symbol_audit(audit_path, rows, resolver)
            print(f"NYSE preferred symbol audit: {audit_path.resolve()}")
        if args.us_finnhub_unit_audit:
            audit_path = Path(args.us_finnhub_unit_audit)
            _write_us_finnhub_unit_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub Unit audit: {audit_path.resolve()}")
        if args.us_finnhub_unit_residual_audit:
            audit_path = Path(args.us_finnhub_unit_residual_audit)
            _write_us_finnhub_unit_residual_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub Unit residual audit: {audit_path.resolve()}")
        if args.us_xase_fund_unit_cohort_audit:
            audit_path = Path(args.us_xase_fund_unit_cohort_audit)
            _write_us_xase_fund_unit_cohort_audit(audit_path, rows, bindings, resolver)
            print(f"US XASE fund/unit cohort audit: {audit_path.resolve()}")
        if args.us_yahoo_currency_unknown_audit:
            audit_path = Path(args.us_yahoo_currency_unknown_audit)
            _write_us_yahoo_currency_unknown_audit(audit_path, rows, bindings, resolver)
            print(f"US Yahoo unknown-currency audit: {audit_path.resolve()}")
        if args.us_finnhub_royalty_trust_audit:
            audit_path = Path(args.us_finnhub_royalty_trust_audit)
            _write_us_finnhub_royalty_trust_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub Royalty Trust audit: {audit_path.resolve()}")
        if args.us_finnhub_ltd_part_audit:
            audit_path = Path(args.us_finnhub_ltd_part_audit)
            _write_us_finnhub_ltd_part_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub Ltd Part audit: {audit_path.resolve()}")
        if args.us_finnhub_closed_end_fund_audit:
            audit_path = Path(args.us_finnhub_closed_end_fund_audit)
            _write_us_finnhub_closed_end_fund_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub Closed-End Fund audit: {audit_path.resolve()}")
        if args.us_finnhub_cdi_audit:
            audit_path = Path(args.us_finnhub_cdi_audit)
            _write_us_finnhub_cdi_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub CDI audit: {audit_path.resolve()}")
        if args.us_finnhub_stapled_security_audit:
            audit_path = Path(args.us_finnhub_stapled_security_audit)
            _write_us_finnhub_stapled_security_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub Stapled Security audit: {audit_path.resolve()}")
        if args.us_finnhub_preference_audit:
            audit_path = Path(args.us_finnhub_preference_audit)
            _write_us_finnhub_preference_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub Preference audit: {audit_path.resolve()}")
        if args.us_finnhub_gdr_audit:
            audit_path = Path(args.us_finnhub_gdr_audit)
            _write_us_finnhub_gdr_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub GDR audit: {audit_path.resolve()}")
        if args.us_finnhub_common_stock_audit:
            audit_path = Path(args.us_finnhub_common_stock_audit)
            _write_us_finnhub_common_stock_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub Common Stock audit: {audit_path.resolve()}")
        if args.us_finnhub_nvdr_audit:
            audit_path = Path(args.us_finnhub_nvdr_audit)
            _write_us_finnhub_nvdr_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub NVDR audit: {audit_path.resolve()}")
        if args.us_finnhub_sdr_audit:
            audit_path = Path(args.us_finnhub_sdr_audit)
            _write_us_finnhub_sdr_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub SDR audit: {audit_path.resolve()}")
        if args.us_finnhub_no_symbol_audit:
            audit_path = Path(args.us_finnhub_no_symbol_audit)
            _write_us_finnhub_no_symbol_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub NO_SYMBOL audit: {audit_path.resolve()}")
        if args.us_finnhub_no_symbol_xnys_preferred_audit:
            audit_path = Path(args.us_finnhub_no_symbol_xnys_preferred_audit)
            _write_us_finnhub_no_symbol_xnys_preferred_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub NO_SYMBOL XNYS preferred audit: {audit_path.resolve()}")
        if args.us_xnas_source_binding_audit:
            audit_path = Path(args.us_xnas_source_binding_audit)
            _write_us_xnas_source_binding_audit(audit_path, rows, bindings, resolver)
            print(f"US XNAS source-binding audit: {audit_path.resolve()}")
        if args.us_yahoo_mutualfund_audit:
            audit_path = Path(args.us_yahoo_mutualfund_audit)
            _write_us_yahoo_mutualfund_audit(audit_path, rows, bindings, resolver)
            print(f"US Yahoo MUTUALFUND audit: {audit_path.resolve()}")
        if args.us_finnhub_public_audit:
            audit_path = Path(args.us_finnhub_public_audit)
            _write_us_finnhub_public_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub PUBLIC audit: {audit_path.resolve()}")
        if args.us_finnhub_public_xnas_segment_audit:
            audit_path = Path(args.us_finnhub_public_xnas_segment_audit)
            _write_us_finnhub_public_xnas_segment_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub PUBLIC XNAS segment audit: {audit_path.resolve()}")
        if args.us_finnhub_residual_taxonomy_audit:
            audit_path = Path(args.us_finnhub_residual_taxonomy_audit)
            _write_us_finnhub_residual_taxonomy_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub residual taxonomy audit: {audit_path.resolve()}")
        if args.us_finnhub_unknown_type_audit:
            audit_path = Path(args.us_finnhub_unknown_type_audit)
            _write_us_finnhub_unknown_type_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub unknown-type audit: {audit_path.resolve()}")
        if args.us_finnhub_unknown_type_residual_audit:
            audit_path = Path(args.us_finnhub_unknown_type_residual_audit)
            _write_us_finnhub_unknown_type_residual_audit(audit_path, rows, bindings, resolver)
            print(f"US Finnhub unknown-type residual audit: {audit_path.resolve()}")
        if args.us_ootc_preferred_empty_type_rescue_audit:
            audit_path = Path(args.us_ootc_preferred_empty_type_rescue_audit)
            _write_us_ootc_preferred_empty_type_rescue_audit(audit_path, rows, bindings, resolver)
            print(f"US OOTC preferred empty-type rescue audit: {audit_path.resolve()}")
        if args.us_v087_slmnp_admission_audit:
            audit_path = Path(args.us_v087_slmnp_admission_audit)
            _write_us_v087_slmnp_admission_audit(audit_path, rows, bindings, resolver)
            print(f"US v0.3.87 SLMNP admission audit: {audit_path.resolve()}")
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
    r.add_argument(
        "--nyse-preferred-symbol-audit",
        default=None,
        help="Write diagnostic-only JSONL for all NYSE stock/preferred slash-symbol rows in the TV snapshot",
    )
    r.add_argument(
        "--us-finnhub-unit-audit",
        default=None,
        help="Write diagnostic-only JSONL for rejected US FINNHUB_TYPE_MISMATCH:Unit rows",
    )
    r.add_argument(
        "--us-finnhub-unit-residual-audit",
        default=None,
        help="Write v0.3.91 diagnostic-only residual classification for US FINNHUB_TYPE_MISMATCH:Unit rejects",
    )
    r.add_argument(
        "--us-xase-fund-unit-cohort-audit",
        default=None,
        help="Write v0.3.92 diagnostic-only JSONL for the complete US AMEX/XASE TV fund+unit cohort",
    )
    r.add_argument(
        "--us-yahoo-currency-unknown-audit",
        default=None,
        help="Write v0.4.16 diagnostic-only full-cohort JSONL for US YAHOO_CURRENCY_MISMATCH:? rejects",
    )
    r.add_argument(
        "--us-finnhub-royalty-trust-audit",
        default=None,
        help="Write v0.3.94 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:Royalty Trst rejects",
    )
    r.add_argument(
        "--us-finnhub-ltd-part-audit",
        default=None,
        help="Write v0.3.96 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:Ltd Part rejects",
    )
    r.add_argument(
        "--us-finnhub-closed-end-fund-audit",
        default=None,
        help="Write v0.3.98 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:Closed-End Fund rejects",
    )
    r.add_argument(
        "--us-finnhub-cdi-audit",
        default=None,
        help="Write v0.4.0 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:CDI rejects",
    )
    r.add_argument(
        "--us-finnhub-stapled-security-audit",
        default=None,
        help="Write v0.4.1 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:Stapled Security rejects",
    )
    r.add_argument(
        "--us-finnhub-preference-audit",
        default=None,
        help="Write v0.4.2 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:Preference rejects",
    )
    r.add_argument(
        "--us-finnhub-gdr-audit",
        default=None,
        help="Write v0.4.3 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:GDR rejects",
    )
    r.add_argument(
        "--us-finnhub-common-stock-audit",
        default=None,
        help="Write v0.4.4 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:Common Stock rejects",
    )
    r.add_argument(
        "--us-finnhub-nvdr-audit",
        default=None,
        help="Write v0.4.5 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:NVDR rejects",
    )
    r.add_argument(
        "--us-finnhub-sdr-audit",
        default=None,
        help="Write v0.4.5 diagnostic-only JSONL for US FINNHUB_TYPE_MISMATCH:SDR rejects",
    )
    r.add_argument(
        "--us-finnhub-no-symbol-audit",
        default=None,
        help="Write v0.4.6 diagnostic-only exact-ISIN/source JSONL for US FINNHUB_NO_SYMBOL rejects",
    )
    r.add_argument(
        "--us-finnhub-no-symbol-xnys-preferred-audit",
        default=None,
        help="Write v0.4.7 diagnostic-only same-source exact-ISIN audit for XNYS slash-symbol FINNHUB_NO_SYMBOL rejects",
    )
    r.add_argument(
        "--us-xnas-source-binding-audit",
        default=None,
        help="Write diagnostic-only JSONL for rejected US rows whose reviewed TradingView source MIC is XNAS",
    )
    r.add_argument(
        "--us-yahoo-mutualfund-audit",
        default=None,
        help="Write v0.4.17 diagnostic-only full-cohort decomposition JSONL for US YAHOO_TYPE_MISMATCH:MUTUALFUND rejects",
    )
    r.add_argument(
        "--us-finnhub-public-audit",
        default=None,
        help="Write v0.4.27 diagnostic-only full-cohort exact-ISIN/source-binding JSONL for US FINNHUB_TYPE_MISMATCH:PUBLIC rejects",
    )
    r.add_argument(
        "--us-finnhub-public-xnas-segment-audit",
        default=None,
        help="Write v0.4.10 diagnostic-only XNAS preferred OpenFIGI/Yahoo segment-consistency JSONL",
    )
    r.add_argument(
        "--us-finnhub-residual-taxonomy-audit",
        default=None,
        help="Write v0.4.18 diagnostic-only full residual Finnhub taxonomy JSONL for 10 reviewed mismatch types",
    )
    r.add_argument(
        "--us-finnhub-unknown-type-audit",
        default=None,
        help="Write v0.4.28 diagnostic-only full-cohort decomposition JSONL for US FINNHUB_TYPE_MISMATCH:? rejects",
    )
    r.add_argument(
        "--us-finnhub-unknown-type-residual-audit",
        default=None,
        help="Write v0.3.90 diagnostic-only residual classification for US FINNHUB_TYPE_MISMATCH:? rejects",
    )
    r.add_argument(
        "--us-ootc-preferred-empty-type-rescue-audit",
        default=None,
        help="Write diagnostic-only provenance JSONL for v0.3.87 OOTC preferred empty-type rescue matches",
    )
    r.add_argument(
        "--us-v087-slmnp-admission-audit",
        default=None,
        help="Write targeted diagnostic-only admission provenance for v0.3.87 SLMNP rescue",
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
