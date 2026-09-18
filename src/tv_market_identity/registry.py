from __future__ import annotations

import sqlite3


REGISTRY_SCHEMA_VERSION = 1
REGISTRY_SCHEMA_META_KEY = "identity_registry_schema_version"


class RegistrySchemaError(RuntimeError):
    """Raised when the on-disk Identity Registry schema is incompatible."""


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
