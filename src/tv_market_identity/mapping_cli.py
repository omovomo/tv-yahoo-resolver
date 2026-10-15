from __future__ import annotations

import argparse
import json
import sys

from .api import MappingInputError, TvYahooMappingRequest, open_mapping_service


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tv-market-id-map",
        description="Versioned TV -> Yahoo application mapping boundary",
    )
    p.add_argument("--cache", required=True, help="SQLite Identity Registry/cache path")
    p.add_argument("--input", default="-", help="Input JSONL path or - for stdin")
    p.add_argument("--output", default="-", help="Output JSONL path or - for stdout")
    p.add_argument("--market", default=None, help="Optional TradingView market context")
    p.add_argument("--refresh", action="store_true", help="Bypass Registry/cache and resolve again")
    p.add_argument(
        "--refresh-rejected",
        action="store_true",
        help="Reuse VERIFIED mappings but re-resolve cached REJECTED rows",
    )
    p.add_argument("--strict-exit", action="store_true", help="Return 3 if any result is not VERIFIED")
    p.add_argument("--telemetry", action="store_true", help="Write aggregate telemetry JSON to stderr")
    p.add_argument("--yahoo-batch", type=int, default=75)
    p.add_argument("--verified-ttl-days", type=int, default=60)
    p.add_argument("--rejected-ttl-hours", type=int, default=6)
    p.add_argument("--finnhub-ttl-hours", type=int, default=24)
    return p


def _read_requests(path: str) -> list[TvYahooMappingRequest]:
    handle = sys.stdin if path == "-" else open(path, "r", encoding="utf-8")
    requests: list[TvYahooMappingRequest] = []
    try:
        for line_no, raw in enumerate(handle, 1):
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
                requests.append(TvYahooMappingRequest.from_mapping(payload))
            except (json.JSONDecodeError, MappingInputError, TypeError, ValueError) as exc:
                raise MappingInputError(f"invalid mapping input line {line_no}: {exc}") from exc
    finally:
        if handle is not sys.stdin:
            handle.close()
    return requests


def run(args: argparse.Namespace) -> int:
    try:
        requests = _read_requests(args.input)
    except MappingInputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    cache, service = open_mapping_service(
        args.cache,
        yahoo_batch=args.yahoo_batch,
        verified_ttl_days=args.verified_ttl_days,
        rejected_ttl_hours=args.rejected_ttl_hours,
        finnhub_ttl_hours=args.finnhub_ttl_hours,
    )
    try:
        batch = service.map_batch(
            requests,
            market=args.market,
            refresh=args.refresh,
            refresh_rejected=args.refresh_rejected,
        )
    finally:
        cache.close()

    output = sys.stdout if args.output == "-" else open(args.output, "w", encoding="utf-8")
    try:
        for result in batch.results:
            output.write(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    finally:
        if output is not sys.stdout:
            output.close()

    if args.telemetry:
        print(json.dumps(dict(batch.telemetry), sort_keys=True), file=sys.stderr)
    if args.strict_exit and any(not result.verified for result in batch.results):
        return 3
    return 0


def main() -> int:
    args = parser().parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
