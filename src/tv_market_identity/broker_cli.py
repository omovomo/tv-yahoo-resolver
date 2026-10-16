"""Read-only broker ISIN security reconciliation JSONL CLI."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .broker import BrokerInputError, IbkrSecurityRequest, reconcile_ibkr_security_batch


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tv-market-id-broker-map",
        description="Read-only IBKR/Flex security match; never authorizes Yahoo or TV listing routing",
    )
    p.add_argument("--cache", required=True, help="Existing SQLite Registry path")
    p.add_argument("--input", default="-", help="Broker request JSONL path or -")
    p.add_argument("--output", default="-", help="Broker result JSONL path or -")
    p.add_argument("--telemetry", action="store_true")
    p.add_argument("--verified-ttl-days", type=int, default=60)
    return p


def _read(path: str) -> list[IbkrSecurityRequest]:
    handle = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        result = []
        for line_no, raw in enumerate(handle, 1):
            if not raw.strip():
                continue
            try:
                result.append(IbkrSecurityRequest.from_mapping(json.loads(raw)))
            except (BrokerInputError, ValueError, TypeError) as exc:
                raise BrokerInputError(f"line {line_no}: {exc}") from exc
        return result
    finally:
        if handle is not sys.stdin:
            handle.close()


def run(args: argparse.Namespace) -> int:
    requests = _read(args.input)
    cache_path = Path(args.cache).resolve()
    if not cache_path.is_file():
        raise BrokerInputError("existing Registry database is required")
    # Physically read-only SQLite connection; never create an empty database.
    conn = sqlite3.connect(cache_path.as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        result = reconcile_ibkr_security_batch(
            conn, requests, verified_ttl_days=args.verified_ttl_days
        )
    finally:
        conn.close()
    output = sys.stdout if args.output == "-" else open(args.output, "w", encoding="utf-8")
    try:
        for item in result.results:
            output.write(json.dumps(item.as_dict(), sort_keys=True) + "\n")
    finally:
        if output is not sys.stdout:
            output.close()
    if args.telemetry:
        print(json.dumps(dict(result.telemetry), sort_keys=True), file=sys.stderr)
    return 0


def main() -> int:
    try:
        return run(parser().parse_args())
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
