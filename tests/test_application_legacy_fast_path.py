"""Application-only legacy reuse: identity admission is unchanged."""

import time

import pytest

from tv_market_identity.api import TvYahooMappingRequest, TvYahooMappingService
from tv_market_identity.cache import CacheDB
from tv_market_identity.models import Binding
from tv_market_identity.policy import RESOLVER_VERSION


OLD_POLICY = "0.3.67-policy67"


def request(symbol="AAPL", *, currency="USD", tv_type="stock", request_id="r"):
    return TvYahooMappingRequest(
        request_id=request_id,
        qualified_tv_id=f"NASDAQ:{symbol}",
        currency=currency,
        tv_type=tv_type,
        type_specs=("common",),
        isin="US0378331005",
        active_symbol=True,
    )


def binding(r, *, policy=OLD_POLICY, status="VERIFIED", expires_in=3600):
    row = r.to_tv_row()
    now = int(time.time())
    return Binding(
        tv_id=row.tv_id,
        tv_symbol=row.symbol,
        tv_prefix=row.prefix,
        tv_currency=row.currency,
        tv_type=row.tv_type,
        status=status,
        yahoo_symbol=row.symbol if status == "VERIFIED" else None,
        mapping_method="SAME_VENUE" if status == "VERIFIED" else None,
        fingerprint="strong-identity-fingerprint" if status == "VERIFIED" else None,
        resolver_version=policy,
        validated_at=now,
        expires_at=now + expires_in,
        yahoo_price=100.0,
        quote_status="FRESH",
    )


def forbidden_factory():
    raise AssertionError("cached application batch must not create a resolver")


def test_old_compatible_verified_uses_fast_path_without_resolver(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        a = request()
        cache.put_bindings([binding(a)])
        svc = TvYahooMappingService(cache, forbidden_factory)
        batch = svc.map_batch([a], market="america")
        assert batch.telemetry["legacy_hits"] == 1
        assert batch.telemetry["legacy_verified_hits"] == 1
        assert batch.telemetry["registry_hits"] == 0
        assert batch.telemetry["resolver_invocations"] == 0
        assert batch.telemetry["resolver_rows"] == 0
        assert batch.results[0].verified
        assert batch.results[0].source == "RESOLVER"  # v1 garp-cli compatibility
        assert batch.results[0].cache_hit is True
        assert batch.results[0].yahoo_symbol == "AAPL"
        assert cache.stats()["registry_mappings"] == 0  # no blind promotion
        original = cache.get_bindings([a.qualified_tv_id], OLD_POLICY,
                                      {a.qualified_tv_id: ("USD", "stock")})
        assert original[a.qualified_tv_id].yahoo_price is None
    finally:
        cache.close()


def test_current_policy_rejected_reused_unless_refresh_rejected(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        a = request()
        cache.put_bindings([binding(a, policy=RESOLVER_VERSION, status="REJECTED")])
        result = TvYahooMappingService(cache, forbidden_factory).map_batch([a])
        assert result.results[0].status == "REJECTED"
        assert result.telemetry["legacy_rejected_hits"] == 1
        assert result.telemetry["resolver_invocations"] == 0

        class Resolver:
            def resolve(self, rows, **kwargs):
                assert kwargs["refresh_rejected"] is True
                return {rows[0].tv_id: binding(a, policy=RESOLVER_VERSION)}

        result = TvYahooMappingService(cache, Resolver).map_batch([a], refresh_rejected=True)
        assert result.telemetry["legacy_hits"] == 0
        assert result.telemetry["resolver_rows"] == 1
        assert result.results[0].verified
    finally:
        cache.close()


@pytest.mark.parametrize("policy,status", [
    (OLD_POLICY, "REJECTED"),
    ("unknown-policy", "VERIFIED"),
])
def test_older_rejected_and_unknown_policy_are_not_fast_path_hits(tmp_path, policy, status):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        a = request()
        cache.put_bindings([binding(a, policy=policy, status=status)])
        class Resolver:
            def resolve(self, rows, **kwargs):
                return {rows[0].tv_id: binding(a, policy=RESOLVER_VERSION)}
        result = TvYahooMappingService(cache, Resolver).map_batch([a])
        assert result.telemetry["legacy_hits"] == 0
        assert result.telemetry["resolver_invocations"] == 1
        assert result.results[0].verified
    finally:
        cache.close()


@pytest.mark.parametrize("scenario", ["expired", "currency", "type"])
def test_stale_or_mismatched_legacy_binding_falls_to_resolver(tmp_path, scenario):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        a = request()
        cache.put_bindings([binding(a, expires_in=-10 if scenario == "expired" else 3600)])
        altered = request(currency="EUR") if scenario == "currency" else (
            request(tv_type="fund") if scenario == "type" else a
        )
        class Resolver:
            def resolve(self, rows, **kwargs):
                return {row.tv_id: binding(altered, policy=RESOLVER_VERSION) for row in rows}
        result = TvYahooMappingService(cache, Resolver).map_batch([altered])
        assert result.telemetry["legacy_hits"] == 0
        assert result.telemetry["resolver_rows"] == 1
    finally:
        cache.close()


def test_explicit_refresh_bypasses_all_cache_paths(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        a = request()
        cache.put_bindings([binding(a)])
        class Resolver:
            def resolve(self, rows, **kwargs):
                assert kwargs["refresh"] is True
                return {row.tv_id: binding(a, policy=RESOLVER_VERSION, status="REJECTED") for row in rows}
        result = TvYahooMappingService(cache, Resolver).map_batch([a], refresh=True)
        assert result.telemetry["legacy_hits"] == 0
        assert result.telemetry["registry_hits"] == 0
        assert result.results[0].status == "REJECTED"
    finally:
        cache.close()


def test_mixed_registry_legacy_and_unresolved_tail(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        r = request("MSFT", request_id="registry")
        l = request("AAPL", request_id="legacy")
        n = request("AMD", request_id="cold")
        rb = binding(r, policy=RESOLVER_VERSION)
        cache.put_registry_tv_yahoo({r.qualified_tv_id: r.to_tv_row()}, [rb])
        cache.put_bindings([binding(l)])
        seen = []
        class Resolver:
            def resolve(self, rows, **kwargs):
                seen.extend(row.tv_id for row in rows)
                return {n.qualified_tv_id: binding(n, policy=RESOLVER_VERSION)}
        result = TvYahooMappingService(cache, Resolver).map_batch([r, l, n])
        assert result.telemetry["registry_hits"] == 1
        assert result.telemetry["legacy_hits"] == 1
        assert result.telemetry["resolver_rows"] == 1
        assert seen == ["NASDAQ:AMD"]
        assert [x.source for x in result.results] == ["REGISTRY", "RESOLVER", "RESOLVER"]
    finally:
        cache.close()


def test_large_multi_policy_batch_requires_no_resolver_and_keeps_duplicates(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        rows = [request(f"S{i:04d}", request_id=f"row-{i}") for i in range(700)]
        bindings = [binding(r, policy="0.3.77-policy77" if i < 478 else OLD_POLICY)
                    for i, r in enumerate(rows)]
        cache.put_bindings(bindings)
        result = TvYahooMappingService(cache, forbidden_factory).map_batch(
            [*rows, request("S0000", request_id="duplicate")]
        )
        assert len(result.results) == 701
        assert result.telemetry["requested"] == 701
        assert result.telemetry["unique_tv_ids"] == 700
        assert result.telemetry["legacy_hits"] == 700
        assert result.telemetry["resolver_invocations"] == 0
        assert result.telemetry["resolver_rows"] == 0
        assert all(x.verified and x.cache_hit for x in result.results)
        assert cache.stats()["registry_mappings"] == 0
    finally:
        cache.close()


def test_inconsistent_persisted_legacy_metadata_does_not_bypass_resolver(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        a = request()
        cache.put_bindings([binding(a)])
        # A compromised/inconsistent legacy payload must not become a fast hit.
        import json
        row = cache.conn.execute("SELECT payload_json FROM bindings WHERE tv_id=?",
                                 (a.qualified_tv_id,)).fetchone()
        payload = json.loads(row["payload_json"])
        payload["resolver_version"] = "unknown-policy"
        with cache.conn:
            cache.conn.execute("UPDATE bindings SET payload_json=? WHERE tv_id=?",
                               (json.dumps(payload), a.qualified_tv_id))
        class Resolver:
            def resolve(self, rows, **kwargs):
                return {rows[0].tv_id: binding(a, policy=RESOLVER_VERSION)}
        result = TvYahooMappingService(cache, Resolver).map_batch([a])
        assert result.telemetry["legacy_hits"] == 0
        assert result.telemetry["resolver_rows"] == 1
    finally:
        cache.close()
