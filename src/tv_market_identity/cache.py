from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Iterable

from .models import Binding
from .registry import ensure_registry_schema, registry_counts


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS bindings (
    tv_id TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    tv_currency TEXT,
    tv_type TEXT,
    resolver_version TEXT NOT NULL,
    validated_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bindings_expiry ON bindings(expires_at);

CREATE TABLE IF NOT EXISTS finnhub_symbols (
    provider_symbol TEXT NOT NULL,
    mic TEXT,
    currency TEXT,
    security_type TEXT,
    payload_json TEXT NOT NULL,
    refreshed_at INTEGER NOT NULL,
    PRIMARY KEY(provider_symbol, mic, currency, security_type)
);
CREATE INDEX IF NOT EXISTS idx_fh_symbol ON finnhub_symbols(provider_symbol);
CREATE INDEX IF NOT EXISTS idx_fh_refresh ON finnhub_symbols(refreshed_at);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class CacheDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        ensure_registry_schema(self.conn)

    def close(self) -> None:
        self.conn.close()

    def get_bindings(self, tv_ids: Iterable[str], resolver_version: str, current: dict[str, tuple[str | None, str | None]]) -> dict[str, Binding]:
        ids = list(dict.fromkeys(tv_ids))
        if not ids:
            return {}
        now = int(time.time())
        out: dict[str, Binding] = {}
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            marks = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"SELECT * FROM bindings WHERE tv_id IN ({marks}) AND resolver_version=? AND expires_at>?",
                [*chunk, resolver_version, now],
            ).fetchall()
            for row in rows:
                cur_currency, cur_type = current.get(row["tv_id"], (None, None))
                if (row["tv_currency"] or None) != (cur_currency or None):
                    continue
                if (row["tv_type"] or None) != (cur_type or None):
                    continue
                b = Binding(**json.loads(row["payload_json"]))
                b.cache_hit = True
                b.quote_status = "STALE_CACHED"
                b.yahoo_price = None
                out[b.tv_id] = b
        return out

    def put_bindings(self, bindings: Iterable[Binding]) -> None:
        rows = []
        for b in bindings:
            payload = b.to_dict()
            payload["cache_hit"] = False
            rows.append((
                b.tv_id,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                b.status,
                b.tv_currency,
                b.tv_type,
                b.resolver_version or "",
                b.validated_at or int(time.time()),
                b.expires_at or int(time.time()),
            ))
        with self.conn:
            self.conn.executemany(
                """INSERT INTO bindings(tv_id,payload_json,status,tv_currency,tv_type,resolver_version,validated_at,expires_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(tv_id) DO UPDATE SET
                     payload_json=excluded.payload_json,
                     status=excluded.status,
                     tv_currency=excluded.tv_currency,
                     tv_type=excluded.tv_type,
                     resolver_version=excluded.resolver_version,
                     validated_at=excluded.validated_at,
                     expires_at=excluded.expires_at""",
                rows,
            )

    def finnhub_age_seconds(self) -> int | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key='finnhub_us_refreshed_at'").fetchone()
        if row is None:
            return None
        return max(0, int(time.time()) - int(row["value"]))

    def replace_finnhub_us(self, rows: list[dict]) -> None:
        now = int(time.time())
        data = []
        for row in rows:
            symbol = str(row.get("symbol") or "").upper().strip()
            if not symbol:
                continue
            data.append((
                symbol,
                (row.get("mic") or None),
                (row.get("currency") or None),
                (row.get("type") or None),
                json.dumps(row, sort_keys=True, separators=(",", ":")),
                now,
            ))
        with self.conn:
            self.conn.execute("DELETE FROM finnhub_symbols")
            self.conn.executemany(
                "INSERT OR REPLACE INTO finnhub_symbols(provider_symbol,mic,currency,security_type,payload_json,refreshed_at) VALUES(?,?,?,?,?,?)",
                data,
            )
            self.conn.execute(
                "INSERT INTO meta(key,value) VALUES('finnhub_us_refreshed_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(now),),
            )

    def find_finnhub_symbols(self, symbols: Iterable[str]) -> dict[str, list[dict]]:
        syms = sorted({s.upper().strip() for s in symbols if s})
        out = {s: [] for s in syms}
        for start in range(0, len(syms), 500):
            chunk = syms[start:start + 500]
            marks = ",".join("?" for _ in chunk)
            rows = self.conn.execute(
                f"SELECT provider_symbol,payload_json FROM finnhub_symbols WHERE provider_symbol IN ({marks})",
                chunk,
            ).fetchall()
            for row in rows:
                out.setdefault(row["provider_symbol"], []).append(json.loads(row["payload_json"]))
        return out


    def load_finnhub_universe(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT payload_json FROM finnhub_symbols"
        ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def stats(self) -> dict[str, int | None]:
        now = int(time.time())
        b = self.conn.execute("SELECT COUNT(*) AS n FROM bindings").fetchone()["n"]
        valid = self.conn.execute("SELECT COUNT(*) AS n FROM bindings WHERE expires_at>?", (now,)).fetchone()["n"]
        fh = self.conn.execute("SELECT COUNT(*) AS n FROM finnhub_symbols").fetchone()["n"]
        out = {
            "bindings": b,
            "valid_bindings": valid,
            "finnhub_symbols": fh,
            "finnhub_age_seconds": self.finnhub_age_seconds(),
        }
        out.update(registry_counts(self.conn))
        return out

    def clear(self) -> None:
        with self.conn:
            self.conn.execute("DELETE FROM bindings")
            self.conn.execute("DELETE FROM finnhub_symbols")
            self.conn.execute("DELETE FROM meta")
