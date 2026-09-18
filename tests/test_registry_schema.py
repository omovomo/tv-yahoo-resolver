import json
import sqlite3
import time

import pytest

from tv_market_identity.cache import CacheDB, SCHEMA
from tv_market_identity.models import Binding
from tv_market_identity.policy import RESOLVER_VERSION
from tv_market_identity.registry import (
    REGISTRY_SCHEMA_META_KEY,
    REGISTRY_SCHEMA_VERSION,
    RegistrySchemaError,
)


def _table_names(conn):
    return {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }


def test_registry_schema_is_additive_and_idempotent(tmp_path):
    path = tmp_path / "registry.sqlite"

    db = CacheDB(path)
    try:
        assert {
            "registry_securities",
            "registry_security_identifiers",
            "registry_listings",
            "registry_provider_identifiers",
            "registry_mappings",
        } <= _table_names(db.conn)
        assert db.stats()["registry_schema_version"] == REGISTRY_SCHEMA_VERSION
        assert db.stats()["registry_securities"] == 0
        assert db.stats()["registry_mappings"] == 0
    finally:
        db.close()

    # Re-opening the same DB must not duplicate or mutate empty Registry state.
    db = CacheDB(path)
    try:
        assert db.stats()["registry_schema_version"] == REGISTRY_SCHEMA_VERSION
        assert db.stats()["registry_provider_identifiers"] == 0
    finally:
        db.close()


def test_registry_schema_upgrade_preserves_legacy_binding(tmp_path):
    path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    now = int(time.time())
    binding = Binding(
        tv_id="NASDAQ:MSFT",
        tv_symbol="MSFT",
        tv_prefix="NASDAQ",
        tv_currency="USD",
        tv_type="stock",
        status="VERIFIED",
        yahoo_symbol="MSFT",
        resolver_version=RESOLVER_VERSION,
        validated_at=now,
        expires_at=now + 3600,
    )
    payload = binding.to_dict()
    payload["cache_hit"] = False
    conn.execute(
        """INSERT INTO bindings(
               tv_id,payload_json,status,tv_currency,tv_type,
               resolver_version,validated_at,expires_at
           ) VALUES(?,?,?,?,?,?,?,?)""",
        (
            binding.tv_id,
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            binding.status,
            binding.tv_currency,
            binding.tv_type,
            binding.resolver_version,
            binding.validated_at,
            binding.expires_at,
        ),
    )
    conn.commit()
    conn.close()

    db = CacheDB(path)
    try:
        got = db.get_bindings(
            [binding.tv_id],
            RESOLVER_VERSION,
            {binding.tv_id: ("USD", "stock")},
        )
        assert got[binding.tv_id].yahoo_symbol == "MSFT"
        assert got[binding.tv_id].cache_hit is True

        # Phase B schema creation must not invent canonical Registry identity
        # from an old Binding that does not persist the source TV ISIN.
        stats = db.stats()
        assert stats["bindings"] == 1
        assert stats["registry_securities"] == 0
        assert stats["registry_provider_identifiers"] == 0
        assert stats["registry_mappings"] == 0
    finally:
        db.close()


def test_registry_schema_version_conflict_fails_closed(tmp_path):
    path = tmp_path / "future.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?)",
        (REGISTRY_SCHEMA_META_KEY, str(REGISTRY_SCHEMA_VERSION + 1)),
    )
    conn.commit()
    conn.close()

    with pytest.raises(RegistrySchemaError, match="Unsupported Identity Registry schema version"):
        CacheDB(path)

    # Fail closed before creating or mutating Registry tables in a DB that
    # advertises a schema version newer than this package understands.
    conn = sqlite3.connect(path)
    try:
        assert "registry_securities" not in _table_names(conn)
    finally:
        conn.close()
