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
    currency_compatible,
    openfigi_currency,
    tv_type_kind,
    yahoo_listing_symbol,
    yahoo_type_compatible,
    yahoo_venue_compatible,
)
from .resolver import BatchResolver
from .tradingview import dataframe_to_tv_rows, fetch_screen


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

        records.append({
            "tv_id": r.tv_id,
            "ticker": r.symbol,
            "name": r.name,
            "currency": r.currency,
            "type": r.tv_type,
            "typespecs": list(r.type_specs),
            "isin": r.isin,
            "rejection_reason": b.rejection_reason,
            "resolved_mic": b.resolved_mic,
            "source_mic": b.source_mic,
            "target_mic": b.target_mic,
            "mapping_method": b.mapping_method,
            "yahoo_symbol": b.yahoo_symbol,
            "source_probe_mics": source_mics,
            "evidence": evidence,
        })

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

def cmd_run(args) -> int:
    cfg = load_screen_config(args.config)
    print(f"TradingView: market={cfg.market}, limit={cfg.limit}, order={cfg.order_by} {'ASC' if cfg.ascending else 'DESC'}")
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
    total, df = fetch_screen(cfg)
    rows = dataframe_to_tv_rows(df)
    print(f"TradingView returned {len(df)} rows (totalCount={total}); resolvable rows={len(rows)}")
    if total > len(df):
        print(f"WARNING: TradingView result truncated: returned {len(df)} of totalCount={total} (Limit={cfg.limit})")

    cache = CacheDB(args.cache)
    try:
        resolver = _make_resolver(cache, args)
        bindings = resolver.resolve(rows, refresh=args.refresh)
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
    total, df = fetch_screen(cfg)
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
