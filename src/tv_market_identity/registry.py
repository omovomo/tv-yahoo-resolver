from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Iterable

from .models import Binding, TvRow


REGISTRY_SCHEMA_VERSION = 1
REGISTRY_SCHEMA_META_KEY = "identity_registry_schema_version"


class RegistrySchemaError(RuntimeError):
    """Raised when the on-disk Identity Registry schema is incompatible."""


class RegistryConflictError(RuntimeError):
    """Raised when new proven evidence conflicts with existing Registry identity."""


@dataclass(frozen=True)
class RegistryLookupStats:
    requested: int = 0
    hits: int = 0
    misses: int = 0
    stale_or_incompatible: int = 0
    ambiguous: int = 0


REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS registry_securities (
    security_id INTEGER PRIMARY KEY,
    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS registry_security_identifiers (
    identifier_id INTEGER PRIMARY KEY,
    security_id INTEGER NOT NULL REFERENCES registry_securities(security_id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
    provenance TEXT,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    UNIQUE(namespace, identifier_value)
);
CREATE INDEX IF NOT EXISTS idx_registry_security_identifiers_security
    ON registry_security_identifiers(security_id);

CREATE TABLE IF NOT EXISTS registry_listings (
    listing_id INTEGER PRIMARY KEY,
    security_id INTEGER NOT NULL REFERENCES registry_securities(security_id) ON DELETE CASCADE,
    mic TEXT,
    currency TEXT,
    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_registry_listings_security
    ON registry_listings(security_id);
CREATE INDEX IF NOT EXISTS idx_registry_listings_mic
    ON registry_listings(mic);

CREATE TABLE IF NOT EXISTS registry_provider_identifiers (
    provider_identifier_id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    identifier_type TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    security_id INTEGER REFERENCES registry_securities(security_id) ON DELETE CASCADE,
    listing_id INTEGER REFERENCES registry_listings(listing_id) ON DELETE CASCADE,
    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
    metadata_json TEXT,
    first_seen_at INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    CHECK(security_id IS NOT NULL OR listing_id IS NOT NULL),
    UNIQUE(provider, identifier_type, identifier_value)
);
CREATE INDEX IF NOT EXISTS idx_registry_provider_identifiers_security
    ON registry_provider_identifiers(security_id);
CREATE INDEX IF NOT EXISTS idx_registry_provider_identifiers_listing
    ON registry_provider_identifiers(listing_id);

CREATE TABLE IF NOT EXISTS registry_mappings (
    mapping_id INTEGER PRIMARY KEY,
    source_provider_identifier_id INTEGER NOT NULL
        REFERENCES registry_provider_identifiers(provider_identifier_id) ON DELETE CASCADE,
    target_provider_identifier_id INTEGER NOT NULL
        REFERENCES registry_provider_identifiers(provider_identifier_id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    mapping_method TEXT,
    resolver_policy TEXT NOT NULL,
    identity_fingerprint TEXT,
    source_fingerprint TEXT,
    lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE',
    evidence_json TEXT,
    first_verified_at INTEGER,
    last_verified_at INTEGER,
    last_checked_at INTEGER NOT NULL,
    UNIQUE(source_provider_identifier_id, target_provider_identifier_id)
);
CREATE INDEX IF NOT EXISTS idx_registry_mappings_source
    ON registry_mappings(source_provider_identifier_id, status, lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_registry_mappings_target
    ON registry_mappings(target_provider_identifier_id, status, lifecycle_state);
CREATE INDEX IF NOT EXISTS idx_registry_mappings_policy
    ON registry_mappings(resolver_policy);
"""


def ensure_registry_schema(conn: sqlite3.Connection) -> None:
    """Create the Phase-B Registry schema without touching legacy bindings.

    Version 1 is intentionally additive: it creates normalized empty Registry
    tables beside the existing cache.  No legacy Binding is promoted here,
    because the legacy payload does not persist all source evidence (notably the
    exact TradingView ISIN) required for a safe canonical-security migration.
    """

    row = conn.execute(
        "SELECT value FROM meta WHERE key=?",
        (REGISTRY_SCHEMA_META_KEY,),
    ).fetchone()
    if row is not None:
        try:
            on_disk = int(row[0])
        except (TypeError, ValueError) as exc:
            raise RegistrySchemaError(
                f"Invalid {REGISTRY_SCHEMA_META_KEY}: {row[0]!r}"
            ) from exc
        if on_disk != REGISTRY_SCHEMA_VERSION:
            raise RegistrySchemaError(
                "Unsupported Identity Registry schema version "
                f"{on_disk}; expected {REGISTRY_SCHEMA_VERSION}"
            )

    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(REGISTRY_SCHEMA)

    if row is None:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?)",
            (REGISTRY_SCHEMA_META_KEY, str(REGISTRY_SCHEMA_VERSION)),
        )
        conn.commit()


def registry_schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(
        "SELECT value FROM meta WHERE key=?",
        (REGISTRY_SCHEMA_META_KEY,),
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def registry_counts(conn: sqlite3.Connection) -> dict[str, int | None]:
    return {
        "registry_schema_version": registry_schema_version(conn),
        "registry_securities": conn.execute(
            "SELECT COUNT(*) FROM registry_securities"
        ).fetchone()[0],
        "registry_listings": conn.execute(
            "SELECT COUNT(*) FROM registry_listings"
        ).fetchone()[0],
        "registry_provider_identifiers": conn.execute(
            "SELECT COUNT(*) FROM registry_provider_identifiers"
        ).fetchone()[0],
        "registry_mappings": conn.execute(
            "SELECT COUNT(*) FROM registry_mappings"
        ).fetchone()[0],
    }


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _norm_upper(value: str | None) -> str | None:
    text = _norm(value)
    return text.upper() if text is not None else None


def tv_source_fingerprint(row: TvRow) -> str:
    """Fingerprint source identity/lifecycle fields, not runtime market data."""

    payload = {
        "v": 1,
        "tv_id": _norm_upper(row.tv_id),
        "prefix": _norm_upper(row.prefix),
        "symbol": _norm_upper(row.symbol),
        "currency": _norm_upper(row.currency),
        "tv_type": (_norm(row.tv_type) or "").lower() or None,
        "type_specs": sorted({
            str(value).strip().lower()
            for value in row.type_specs
            if str(value).strip()
        }),
        "isin": _norm_upper(row.isin),
        "active_symbol": row.active_symbol,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _security_anchors(row: TvRow, binding: Binding) -> list[tuple[str, str]]:
    anchors: list[tuple[str, str]] = []
    isin = _norm_upper(row.isin)
    if isin:
        anchors.append(("ISIN", isin))
    share_class = _norm_upper(binding.share_class_figi)
    if share_class:
        anchors.append(("SHARE_CLASS_FIGI", share_class))
    return anchors


def _security_for_anchors(
    conn: sqlite3.Connection,
    anchors: list[tuple[str, str]],
    *,
    now: int,
) -> int:
    if not anchors:
        raise RegistryConflictError("No strong security anchor for Registry write")

    security_ids: set[int] = set()
    for namespace, value in anchors:
        row = conn.execute(
            """SELECT security_id
               FROM registry_security_identifiers
               WHERE namespace=? AND identifier_value=?""",
            (namespace, value),
        ).fetchone()
        if row is not None:
            security_ids.add(int(row[0]))

    if len(security_ids) > 1:
        raise RegistryConflictError(
            "Strong security identifiers resolve to different Registry securities"
        )

    if security_ids:
        security_id = next(iter(security_ids))
        conn.execute(
            """UPDATE registry_securities
               SET lifecycle_state='ACTIVE', updated_at=?
               WHERE security_id=?""",
            (now, security_id),
        )
    else:
        cur = conn.execute(
            """INSERT INTO registry_securities(lifecycle_state,created_at,updated_at)
               VALUES('ACTIVE',?,?)""",
            (now, now),
        )
        security_id = int(cur.lastrowid)

    for namespace, value in anchors:
        row = conn.execute(
            """SELECT security_id
               FROM registry_security_identifiers
               WHERE namespace=? AND identifier_value=?""",
            (namespace, value),
        ).fetchone()
        if row is not None and int(row[0]) != security_id:
            raise RegistryConflictError(
                f"{namespace} {value} already belongs to another Registry security"
            )
        active_same_namespace = {
            item[0]
            for item in conn.execute(
                """SELECT identifier_value
                   FROM registry_security_identifiers
                   WHERE security_id=? AND namespace=? AND lifecycle_state='ACTIVE'""",
                (security_id, namespace),
            ).fetchall()
        }
        if active_same_namespace and value not in active_same_namespace:
            raise RegistryConflictError(
                f"Registry security {security_id} already has a different active {namespace}"
            )
        conn.execute(
            """INSERT INTO registry_security_identifiers(
                   security_id,namespace,identifier_value,lifecycle_state,
                   provenance,first_seen_at,last_seen_at
               ) VALUES(?,?,?,'ACTIVE','RESOLVER_VERIFIED',?,?)
               ON CONFLICT(namespace,identifier_value) DO UPDATE SET
                   lifecycle_state='ACTIVE',
                   provenance='RESOLVER_VERIFIED',
                   last_seen_at=excluded.last_seen_at""",
            (security_id, namespace, value, now, now),
        )

    return security_id


def _compatible_listing_value(old: str | None, new: str | None) -> bool:
    return old is None or new is None or _norm_upper(old) == _norm_upper(new)


def _get_or_create_provider_listing(
    conn: sqlite3.Connection,
    *,
    provider: str,
    identifier_type: str,
    identifier_value: str,
    security_id: int,
    mic: str | None,
    currency: str | None,
    metadata: dict,
    now: int,
) -> tuple[int, int]:
    provider = provider.upper()
    identifier_type = identifier_type.upper()
    identifier_value = identifier_value.upper()
    mic = _norm_upper(mic)
    currency = _norm_upper(currency)
    metadata_json = json.dumps(metadata, sort_keys=True, separators=(",", ":"))

    existing = conn.execute(
        """SELECT provider_identifier_id,security_id,listing_id
           FROM registry_provider_identifiers
           WHERE provider=? AND identifier_type=? AND identifier_value=?""",
        (provider, identifier_type, identifier_value),
    ).fetchone()
    if existing is not None:
        existing_security = existing["security_id"]
        if existing_security is not None and int(existing_security) != security_id:
            raise RegistryConflictError(
                f"{provider} {identifier_value} already belongs to another Registry security"
            )
        listing_id = int(existing["listing_id"])
        listing = conn.execute(
            """SELECT security_id,mic,currency
               FROM registry_listings WHERE listing_id=?""",
            (listing_id,),
        ).fetchone()
        if listing is None or int(listing["security_id"]) != security_id:
            raise RegistryConflictError(
                f"{provider} {identifier_value} has inconsistent Registry listing ownership"
            )
        if not _compatible_listing_value(listing["mic"], mic):
            raise RegistryConflictError(
                f"{provider} {identifier_value} Registry MIC conflict: "
                f"{listing['mic']!r} vs {mic!r}"
            )
        if not _compatible_listing_value(listing["currency"], currency):
            raise RegistryConflictError(
                f"{provider} {identifier_value} Registry currency conflict: "
                f"{listing['currency']!r} vs {currency!r}"
            )
        conn.execute(
            """UPDATE registry_listings
               SET mic=COALESCE(mic,?), currency=COALESCE(currency,?),
                   lifecycle_state='ACTIVE', last_seen_at=?
               WHERE listing_id=?""",
            (mic, currency, now, listing_id),
        )
        conn.execute(
            """UPDATE registry_provider_identifiers
               SET security_id=?, lifecycle_state='ACTIVE', metadata_json=?, last_seen_at=?
               WHERE provider_identifier_id=?""",
            (security_id, metadata_json, now, int(existing["provider_identifier_id"])),
        )
        return int(existing["provider_identifier_id"]), listing_id

    cur = conn.execute(
        """INSERT INTO registry_listings(
               security_id,mic,currency,lifecycle_state,first_seen_at,last_seen_at
           ) VALUES(?,?,?,'ACTIVE',?,?)""",
        (security_id, mic, currency, now, now),
    )
    listing_id = int(cur.lastrowid)
    cur = conn.execute(
        """INSERT INTO registry_provider_identifiers(
               provider,identifier_type,identifier_value,security_id,listing_id,
               lifecycle_state,metadata_json,first_seen_at,last_seen_at
           ) VALUES(?,?,?,?,?,'ACTIVE',?,?,?)""",
        (
            provider,
            identifier_type,
            identifier_value,
            security_id,
            listing_id,
            metadata_json,
            now,
            now,
        ),
    )
    return int(cur.lastrowid), listing_id


def _registry_evidence(row: TvRow, binding: Binding) -> dict:
    return {
        "tv_isin": _norm_upper(row.isin),
        "share_class_figi": _norm_upper(binding.share_class_figi),
        "composite_figi": _norm_upper(binding.composite_figi),
        "source_venue_figi": _norm_upper(binding.source_venue_figi),
        "target_venue_figi": _norm_upper(binding.target_venue_figi),
        "venue_figi": _norm_upper(binding.venue_figi),
        "finnhub_symbol": _norm_upper(binding.finnhub_symbol),
        "finnhub_type": _norm(binding.finnhub_type),
        "source_venue_code": _norm_upper(binding.source_venue_code),
        "source_mic": _norm_upper(binding.source_mic),
        "target_mic": _norm_upper(binding.target_mic),
        "resolved_mic": _norm_upper(binding.resolved_mic),
        "yahoo_exchange": _norm_upper(binding.yahoo_exchange),
        "yahoo_market": _norm(binding.yahoo_market),
        "yahoo_quote_type": _norm_upper(binding.yahoo_quote_type),
        "yahoo_currency": _norm_upper(binding.yahoo_currency),
    }


def _write_verified_tv_yahoo(
    conn: sqlite3.Connection,
    row: TvRow,
    binding: Binding,
) -> None:
    if binding.status != "VERIFIED" or not binding.yahoo_symbol:
        raise ValueError("Registry write-through requires a VERIFIED Yahoo binding")
    if _norm_upper(binding.tv_id) != _norm_upper(row.tv_id):
        raise RegistryConflictError("TvRow and Binding tv_id differ")

    now = int(binding.validated_at or time.time())
    anchors = _security_anchors(row, binding)
    security_id = _security_for_anchors(conn, anchors, now=now)
    source_fingerprint = tv_source_fingerprint(row)

    tv_metadata = {
        "currency": _norm_upper(row.currency),
        "tv_type": (_norm(row.tv_type) or "").lower() or None,
        "type_specs": sorted({
            str(value).strip().lower()
            for value in row.type_specs
            if str(value).strip()
        }),
        "isin": _norm_upper(row.isin),
        "active_symbol": row.active_symbol,
        "source_mic": _norm_upper(binding.source_mic),
        "source_venue_code": _norm_upper(binding.source_venue_code),
        "source_fingerprint": source_fingerprint,
    }
    source_provider_id, _ = _get_or_create_provider_listing(
        conn,
        provider="TRADINGVIEW",
        identifier_type="QUALIFIED_ID",
        identifier_value=_norm_upper(row.tv_id) or row.tv_id,
        security_id=security_id,
        mic=binding.source_mic,
        currency=row.currency,
        metadata=tv_metadata,
        now=now,
    )

    yahoo_metadata = {
        "exchange": _norm_upper(binding.yahoo_exchange),
        "market": _norm(binding.yahoo_market),
        "quote_type": _norm_upper(binding.yahoo_quote_type),
        "currency": _norm_upper(binding.yahoo_currency),
        "target_mic": _norm_upper(binding.target_mic),
    }
    target_provider_id, _ = _get_or_create_provider_listing(
        conn,
        provider="YAHOO",
        identifier_type="SYMBOL",
        identifier_value=_norm_upper(binding.yahoo_symbol) or binding.yahoo_symbol,
        security_id=security_id,
        mic=binding.target_mic,
        currency=binding.yahoo_currency or row.currency,
        metadata=yahoo_metadata,
        now=now,
    )

    # A fresh proof for the same TV identifier may legitimately select a new
    # target listing. Preserve the old edge as history, but only one target edge
    # remains ACTIVE for this exact provider identifier.
    conn.execute(
        """UPDATE registry_mappings
           SET lifecycle_state='INACTIVE', last_checked_at=?
           WHERE source_provider_identifier_id=?
             AND target_provider_identifier_id<>?
             AND lifecycle_state='ACTIVE'""",
        (now, source_provider_id, target_provider_id),
    )

    evidence_json = json.dumps(
        _registry_evidence(row, binding), sort_keys=True, separators=(",", ":")
    )
    identity_fingerprint = binding.fingerprint or hashlib.sha256(
        evidence_json.encode()
    ).hexdigest()
    resolver_policy = _norm(binding.resolver_version)
    if not resolver_policy:
        raise RegistryConflictError("VERIFIED binding has no resolver policy")

    conn.execute(
        """INSERT INTO registry_mappings(
               source_provider_identifier_id,target_provider_identifier_id,status,
               mapping_method,resolver_policy,identity_fingerprint,source_fingerprint,
               lifecycle_state,evidence_json,first_verified_at,last_verified_at,last_checked_at
           ) VALUES(?,?,'VERIFIED',?,?,?,?, 'ACTIVE',?,?,?,?)
           ON CONFLICT(source_provider_identifier_id,target_provider_identifier_id)
           DO UPDATE SET
               status='VERIFIED',
               mapping_method=excluded.mapping_method,
               resolver_policy=excluded.resolver_policy,
               identity_fingerprint=excluded.identity_fingerprint,
               source_fingerprint=excluded.source_fingerprint,
               lifecycle_state='ACTIVE',
               evidence_json=excluded.evidence_json,
               first_verified_at=COALESCE(registry_mappings.first_verified_at,excluded.first_verified_at),
               last_verified_at=excluded.last_verified_at,
               last_checked_at=excluded.last_checked_at""",
        (
            source_provider_id,
            target_provider_id,
            binding.mapping_method,
            resolver_policy,
            identity_fingerprint,
            source_fingerprint,
            evidence_json,
            now,
            now,
            now,
        ),
    )


def write_verified_tv_yahoo(
    conn: sqlite3.Connection,
    rows_by_id: dict[str, TvRow],
    bindings: Iterable[Binding],
) -> dict[str, int]:
    """Write freshly VERIFIED TV -> Yahoo proofs into the normalized Registry.

    Legacy cache hits are deliberately not promoted here unless the caller also
    has the exact current ``TvRow`` and intentionally supplies them. The normal
    resolver integration calls this only for freshly resolved bindings, where
    source evidence and resolver output belong to the same resolution run.
    """

    metrics = {
        "attempted": 0,
        "written": 0,
        "skipped_unanchored": 0,
        "conflicts": 0,
    }
    canonical_rows = {_norm_upper(k): v for k, v in rows_by_id.items()}

    with conn:
        for binding in bindings:
            if binding.status != "VERIFIED" or not binding.yahoo_symbol:
                continue
            row = canonical_rows.get(_norm_upper(binding.tv_id))
            if row is None:
                continue
            metrics["attempted"] += 1
            if not _security_anchors(row, binding):
                metrics["skipped_unanchored"] += 1
                continue

            conn.execute("SAVEPOINT registry_write_row")
            try:
                _write_verified_tv_yahoo(conn, row, binding)
            except RegistryConflictError:
                conn.execute("ROLLBACK TO registry_write_row")
                conn.execute("RELEASE registry_write_row")
                metrics["conflicts"] += 1
                continue
            else:
                conn.execute("RELEASE registry_write_row")
                metrics["written"] += 1

    return metrics


def _rows_by_integer_id(
    conn: sqlite3.Connection,
    *,
    table: str,
    id_column: str,
    ids: list[int],
) -> dict[int, sqlite3.Row]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT * FROM {table} WHERE {id_column} IN ({marks})",
        ids,
    ).fetchall()
    return {int(row[id_column]): row for row in rows}


def _load_mapping_candidates(
    conn: sqlite3.Connection,
    tv_ids: list[str],
) -> dict[str, list[dict]]:
    """Load TV -> Yahoo edges with only indexed point/batch lookups.

    Do not express this as one multi-table join: SQLite may legally start that
    join from every Yahoo provider identifier and then probe mappings, which
    becomes effectively quadratic for a full market universe. The staged reads
    below start from the UNIQUE TV identifier index and the explicit mapping
    source index, then hydrate only the referenced target/listing rows.
    """

    out: dict[str, list[dict]] = {tv_id: [] for tv_id in tv_ids}
    for start in range(0, len(tv_ids), 400):
        chunk = tv_ids[start:start + 400]
        marks = ",".join("?" for _ in chunk)
        sources = conn.execute(
            f"""SELECT provider_identifier_id,identifier_value,security_id,
                       listing_id,lifecycle_state
                FROM registry_provider_identifiers
                WHERE provider='TRADINGVIEW'
                  AND identifier_type='QUALIFIED_ID'
                  AND identifier_value IN ({marks})""",
            chunk,
        ).fetchall()
        if not sources:
            continue

        source_by_id = {int(row["provider_identifier_id"]): row for row in sources}
        source_ids = list(source_by_id)
        id_marks = ",".join("?" for _ in source_ids)
        mappings = conn.execute(
            f"""SELECT *
                FROM registry_mappings INDEXED BY idx_registry_mappings_source
                WHERE source_provider_identifier_id IN ({id_marks})""",
            source_ids,
        ).fetchall()
        if not mappings:
            continue

        target_ids = sorted({int(row["target_provider_identifier_id"]) for row in mappings})
        targets = _rows_by_integer_id(
            conn,
            table="registry_provider_identifiers",
            id_column="provider_identifier_id",
            ids=target_ids,
        )
        listing_ids = sorted({
            int(row["listing_id"])
            for row in sources
            if row["listing_id"] is not None
        } | {
            int(row["listing_id"])
            for row in targets.values()
            if row["listing_id"] is not None
        })
        listings = _rows_by_integer_id(
            conn,
            table="registry_listings",
            id_column="listing_id",
            ids=listing_ids,
        )

        for mapping in mappings:
            source_id = int(mapping["source_provider_identifier_id"])
            target_id = int(mapping["target_provider_identifier_id"])
            source = source_by_id.get(source_id)
            target = targets.get(target_id)
            if source is None or target is None:
                continue
            if target["provider"] != "YAHOO" or target["identifier_type"] != "SYMBOL":
                continue
            source_listing = listings.get(int(source["listing_id"])) if source["listing_id"] is not None else None
            target_listing = listings.get(int(target["listing_id"])) if target["listing_id"] is not None else None
            if source_listing is None or target_listing is None:
                continue
            tv_id = source["identifier_value"]
            out.setdefault(tv_id, []).append({
                "source_provider_identifier_id": source_id,
                "security_id": source["security_id"],
                "source_listing_id": source["listing_id"],
                "source_provider_lifecycle": source["lifecycle_state"],
                "source_listing_lifecycle": source_listing["lifecycle_state"],
                "yahoo_symbol": target["identifier_value"],
                "yahoo_listing_id": target["listing_id"],
                "target_provider_lifecycle": target["lifecycle_state"],
                "yahoo_metadata_json": target["metadata_json"],
                "target_listing_lifecycle": target_listing["lifecycle_state"],
                "target_listing_mic": target_listing["mic"],
                "target_listing_currency": target_listing["currency"],
                "source_listing_mic": source_listing["mic"],
                "mapping_method": mapping["mapping_method"],
                "resolver_policy": mapping["resolver_policy"],
                "identity_fingerprint": mapping["identity_fingerprint"],
                "source_fingerprint": mapping["source_fingerprint"],
                "mapping_lifecycle": mapping["lifecycle_state"],
                "mapping_status": mapping["status"],
                "evidence_json": mapping["evidence_json"],
                "first_verified_at": mapping["first_verified_at"],
                "last_verified_at": mapping["last_verified_at"],
                "last_checked_at": mapping["last_checked_at"],
            })
    return out


def _project_binding(row: TvRow, candidate: dict, max_age_seconds: int) -> Binding:
    evidence = json.loads(candidate["evidence_json"] or "{}")
    yahoo_metadata = json.loads(candidate["yahoo_metadata_json"] or "{}")
    validated_at = int(candidate["last_verified_at"] or candidate["last_checked_at"])
    return Binding(
        tv_id=row.tv_id,
        tv_symbol=row.symbol,
        tv_prefix=row.prefix,
        tv_currency=row.currency,
        tv_type=row.tv_type,
        status="VERIFIED",
        yahoo_symbol=candidate["yahoo_symbol"],
        yahoo_exchange=yahoo_metadata.get("exchange") or evidence.get("yahoo_exchange"),
        yahoo_market=yahoo_metadata.get("market") or evidence.get("yahoo_market"),
        yahoo_quote_type=yahoo_metadata.get("quote_type") or evidence.get("yahoo_quote_type"),
        yahoo_currency=yahoo_metadata.get("currency") or evidence.get("yahoo_currency"),
        yahoo_price=None,
        yahoo_delayed_by=None,
        quote_status="STALE_CACHED",
        resolved_mic=evidence.get("resolved_mic") or candidate["target_listing_mic"],
        source_mic=evidence.get("source_mic") or candidate["source_listing_mic"],
        target_mic=evidence.get("target_mic") or candidate["target_listing_mic"],
        source_venue_code=evidence.get("source_venue_code"),
        mapping_method=candidate["mapping_method"],
        source_venue_figi=evidence.get("source_venue_figi"),
        target_venue_figi=evidence.get("target_venue_figi"),
        finnhub_symbol=evidence.get("finnhub_symbol"),
        finnhub_type=evidence.get("finnhub_type"),
        composite_figi=evidence.get("composite_figi"),
        share_class_figi=evidence.get("share_class_figi"),
        venue_figi=evidence.get("venue_figi"),
        fingerprint=candidate["identity_fingerprint"],
        resolver_version=candidate["resolver_policy"],
        validated_at=validated_at,
        expires_at=validated_at + max_age_seconds,
        cache_hit=True,
    )


def lookup_verified_tv_yahoo(
    conn: sqlite3.Connection,
    rows: Iterable[TvRow],
    *,
    accepted_policies: Iterable[str],
    max_age_seconds: int,
    now: int | None = None,
) -> tuple[dict[str, Binding], RegistryLookupStats]:
    """Return exact compatible Registry TV -> Yahoo hits.

    Reuse requires an ACTIVE VERIFIED edge, exact source snapshot fingerprint,
    accepted resolver policy, and identity verification age within the caller's
    current TTL horizon. Multiple surviving target edges fail closed as an
    ambiguous miss.
    """

    row_list = list(rows)
    if not row_list:
        return {}, RegistryLookupStats()
    accepted = {str(value) for value in accepted_policies if str(value)}
    if not accepted:
        return {}, RegistryLookupStats(requested=len(row_list), misses=len(row_list))
    if max_age_seconds <= 0:
        return {}, RegistryLookupStats(
            requested=len(row_list), stale_or_incompatible=len(row_list)
        )

    current_time = int(time.time()) if now is None else int(now)
    min_verified_at = current_time - int(max_age_seconds)
    canonical_rows = {_norm_upper(row.tv_id): row for row in row_list}
    candidates_by_id = _load_mapping_candidates(conn, list(canonical_rows))

    hits: dict[str, Binding] = {}
    misses = 0
    stale_or_incompatible = 0
    ambiguous = 0

    for canonical_id, row in canonical_rows.items():
        candidates = candidates_by_id.get(canonical_id, [])
        if not candidates:
            misses += 1
            continue

        fingerprint = tv_source_fingerprint(row)
        compatible = [
            candidate
            for candidate in candidates
            if candidate["mapping_status"] == "VERIFIED"
            and candidate["mapping_lifecycle"] == "ACTIVE"
            and candidate["source_provider_lifecycle"] == "ACTIVE"
            and candidate["source_listing_lifecycle"] == "ACTIVE"
            and candidate["target_provider_lifecycle"] == "ACTIVE"
            and candidate["target_listing_lifecycle"] == "ACTIVE"
            and candidate["resolver_policy"] in accepted
            and candidate["source_fingerprint"] == fingerprint
            and int(candidate["last_verified_at"] or 0) >= min_verified_at
        ]
        if not compatible:
            stale_or_incompatible += 1
            continue

        # Duplicate rows for the same exact target are harmless historical SQL
        # noise, but different active Yahoo targets are an ambiguity and must not
        # be selected by ordering or recency.
        targets = {candidate["yahoo_symbol"] for candidate in compatible}
        if len(targets) != 1:
            ambiguous += 1
            continue

        # All surviving candidates converge on the same target symbol and exact
        # source fingerprint. Use the most recently verified compatible proof.
        chosen = max(
            compatible,
            key=lambda candidate: int(candidate["last_verified_at"] or 0),
        )
        hits[row.tv_id] = _project_binding(row, chosen, max_age_seconds)

    stats = RegistryLookupStats(
        requested=len(row_list),
        hits=len(hits),
        misses=misses,
        stale_or_incompatible=stale_or_incompatible,
        ambiguous=ambiguous,
    )
    return hits, stats


def invalidate_tv_yahoo_mappings(
    conn: sqlite3.Connection,
    tv_ids: Iterable[str],
    *,
    now: int | None = None,
) -> int:
    ids = sorted({_norm_upper(value) for value in tv_ids if _norm_upper(value)})
    if not ids:
        return 0
    checked_at = int(time.time()) if now is None else int(now)
    changed = 0
    with conn:
        for start in range(0, len(ids), 400):
            chunk = ids[start:start + 400]
            marks = ",".join("?" for _ in chunk)
            cur = conn.execute(
                f"""UPDATE registry_mappings
                    SET lifecycle_state='INACTIVE', last_checked_at=?
                    WHERE lifecycle_state='ACTIVE'
                      AND source_provider_identifier_id IN (
                          SELECT provider_identifier_id
                          FROM registry_provider_identifiers
                          WHERE provider='TRADINGVIEW'
                            AND identifier_type='QUALIFIED_ID'
                            AND identifier_value IN ({marks})
                      )""",
                [checked_at, *chunk],
            )
            changed += max(0, int(cur.rowcount or 0))
    return changed


def clear_registry(conn: sqlite3.Connection) -> None:
    """Delete Registry data while preserving the installed schema version."""

    with conn:
        conn.execute("DELETE FROM registry_mappings")
        conn.execute("DELETE FROM registry_provider_identifiers")
        conn.execute("DELETE FROM registry_listings")
        conn.execute("DELETE FROM registry_security_identifiers")
        conn.execute("DELETE FROM registry_securities")
