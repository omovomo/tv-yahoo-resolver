import time

from tv_market_identity.cache import CacheDB
from tv_market_identity.models import Binding, TvRow, YahooQuote
from tv_market_identity.policy import RESOLVER_VERSION
from tv_market_identity.resolver import BatchResolver
from tv_market_identity.registry import tv_source_fingerprint


def _row(
    tv_id="NASDAQ:MSFT",
    *,
    prefix="NASDAQ",
    symbol="MSFT",
    isin="US5949181045",
    currency="USD",
    tv_type="stock",
    type_specs=("common",),
    active_symbol=True,
):
    return TvRow(
        tv_id,
        prefix,
        symbol,
        "Microsoft Corp",
        currency,
        tv_type,
        type_specs,
        None,
        None,
        None,
        isin,
        active_symbol,
    )


def _binding(
    row,
    *,
    yahoo_symbol="MSFT",
    share_class_figi="BBG001S5TD05",
    source_mic="XNAS",
    target_mic="XNAS",
    validated_at=None,
):
    now = int(time.time()) if validated_at is None else validated_at
    return Binding(
        tv_id=row.tv_id,
        tv_symbol=row.symbol,
        tv_prefix=row.prefix,
        tv_currency=row.currency,
        tv_type=row.tv_type,
        status="VERIFIED",
        yahoo_symbol=yahoo_symbol,
        yahoo_exchange="NMS",
        yahoo_market="us_market",
        yahoo_quote_type="EQUITY",
        yahoo_currency="USD",
        yahoo_price=400.0,
        yahoo_delayed_by=0,
        quote_status="FRESH",
        resolved_mic=target_mic,
        source_mic=source_mic,
        target_mic=target_mic,
        mapping_method="SAME_VENUE",
        finnhub_symbol=row.symbol,
        finnhub_type="Common Stock",
        composite_figi="BBG000BPH459",
        share_class_figi=share_class_figi,
        venue_figi="BBG000BPH459",
        source_venue_figi="BBG000BPH459",
        target_venue_figi="BBG000BPH459",
        fingerprint=f"fingerprint:{row.tv_id}:{yahoo_symbol}",
        resolver_version=RESOLVER_VERSION,
        validated_at=now,
        expires_at=now + 3600,
    )


def test_registry_tv_yahoo_write_read_is_idempotent(tmp_path):
    db = CacheDB(tmp_path / "registry.sqlite")
    try:
        row = _row()
        binding = _binding(row)

        first = db.put_registry_tv_yahoo({row.tv_id: row}, [binding])
        second = db.put_registry_tv_yahoo({row.tv_id: row}, [binding])
        assert first == {
            "attempted": 1,
            "written": 1,
            "skipped_unanchored": 0,
            "conflicts": 0,
        }
        assert second["written"] == 1

        stats = db.stats()
        assert stats["registry_securities"] == 1
        assert stats["registry_listings"] == 2
        assert stats["registry_provider_identifiers"] == 2
        assert stats["registry_mappings"] == 1
        identifiers = db.conn.execute(
            """SELECT namespace,identifier_value
               FROM registry_security_identifiers
               ORDER BY namespace"""
        ).fetchall()
        assert [(x["namespace"], x["identifier_value"]) for x in identifiers] == [
            ("ISIN", "US5949181045"),
            ("SHARE_CLASS_FIGI", "BBG001S5TD05"),
        ]

        hits, lookup = db.get_registry_tv_yahoo(
            [row],
            accepted_policies=[RESOLVER_VERSION],
            max_age_seconds=3600,
        )
        assert lookup.hits == 1
        assert lookup.misses == 0
        got = hits[row.tv_id]
        assert got.status == "VERIFIED"
        assert got.yahoo_symbol == "MSFT"
        assert got.source_mic == "XNAS"
        assert got.target_mic == "XNAS"
        assert got.share_class_figi == "BBG001S5TD05"
        assert got.fingerprint == binding.fingerprint
        assert got.cache_hit is True
        assert got.quote_status == "STALE_CACHED"
        assert got.yahoo_price is None
    finally:
        db.close()


def test_registry_tv_yahoo_source_fingerprint_is_exact(tmp_path):
    db = CacheDB(tmp_path / "fingerprint.sqlite")
    try:
        row = _row()
        binding = _binding(row)
        db.put_registry_tv_yahoo({row.tv_id: row}, [binding])

        changed_isin = _row(isin="US0378331005")
        hits, stats = db.get_registry_tv_yahoo(
            [changed_isin],
            accepted_policies=[RESOLVER_VERSION],
            max_age_seconds=3600,
        )
        assert hits == {}
        assert stats.stale_or_incompatible == 1

        changed_specs = _row(type_specs=("preferred",))
        hits, stats = db.get_registry_tv_yahoo(
            [changed_specs],
            accepted_policies=[RESOLVER_VERSION],
            max_age_seconds=3600,
        )
        assert hits == {}
        assert stats.stale_or_incompatible == 1

        assert tv_source_fingerprint(row) != tv_source_fingerprint(changed_isin)
        assert tv_source_fingerprint(row) != tv_source_fingerprint(changed_specs)
    finally:
        db.close()


def test_registry_tv_yahoo_many_tv_listings_can_share_one_yahoo_target(tmp_path):
    db = CacheDB(tmp_path / "many_to_one.sqlite")
    try:
        first = _row()
        second = _row(
            tv_id="BATS:MSFT",
            prefix="BATS",
            isin=first.isin,
        )
        first_binding = _binding(first)
        second_binding = _binding(
            second,
            source_mic="BATS",
            target_mic="XNAS",
        )

        metrics = db.put_registry_tv_yahoo(
            {first.tv_id: first, second.tv_id: second},
            [first_binding, second_binding],
        )
        assert metrics["written"] == 2
        stats = db.stats()
        assert stats["registry_securities"] == 1
        assert stats["registry_listings"] == 3
        assert stats["registry_provider_identifiers"] == 3
        assert stats["registry_mappings"] == 2

        hits, lookup = db.get_registry_tv_yahoo(
            [first, second],
            accepted_policies=[RESOLVER_VERSION],
            max_age_seconds=3600,
        )
        assert lookup.hits == 2
        assert hits[first.tv_id].yahoo_symbol == "MSFT"
        assert hits[second.tv_id].yahoo_symbol == "MSFT"
        assert hits[second.tv_id].source_mic == "BATS"
        assert hits[second.tv_id].target_mic == "XNAS"
    finally:
        db.close()


def test_registry_tv_yahoo_conflicting_yahoo_symbol_fails_closed(tmp_path):
    db = CacheDB(tmp_path / "conflict.sqlite")
    try:
        first = _row()
        second = _row(
            tv_id="NASDAQ:OTHER",
            symbol="OTHER",
            isin="US0378331005",
        )
        first_binding = _binding(first)
        second_binding = _binding(
            second,
            yahoo_symbol="MSFT",
            share_class_figi="BBG004S68B31",
        )

        assert db.put_registry_tv_yahoo({first.tv_id: first}, [first_binding])["written"] == 1
        metrics = db.put_registry_tv_yahoo({second.tv_id: second}, [second_binding])
        assert metrics["conflicts"] == 1
        assert metrics["written"] == 0

        stats = db.stats()
        assert stats["registry_securities"] == 1
        assert stats["registry_provider_identifiers"] == 2
        assert stats["registry_mappings"] == 1
    finally:
        db.close()


def test_registry_tv_yahoo_age_and_explicit_invalidation_are_fail_closed(tmp_path):
    db = CacheDB(tmp_path / "stale.sqlite")
    try:
        now = int(time.time())
        row = _row()
        binding = _binding(row, validated_at=now - 1000)
        db.put_registry_tv_yahoo({row.tv_id: row}, [binding])

        hits, stats = db.get_registry_tv_yahoo(
            [row],
            accepted_policies=[RESOLVER_VERSION],
            max_age_seconds=10,
        )
        assert hits == {}
        assert stats.stale_or_incompatible == 1

        db.conn.execute(
            "UPDATE registry_mappings SET last_verified_at=?",
            (now,),
        )
        db.conn.commit()
        hits, stats = db.get_registry_tv_yahoo(
            [row],
            accepted_policies=[RESOLVER_VERSION],
            max_age_seconds=3600,
        )
        assert stats.hits == 1

        assert db.invalidate_registry_tv_yahoo([row.tv_id]) == 1
        hits, stats = db.get_registry_tv_yahoo(
            [row],
            accepted_policies=[RESOLVER_VERSION],
            max_age_seconds=3600,
        )
        assert hits == {}
        assert stats.stale_or_incompatible == 1
    finally:
        db.close()


class _FH:
    def us_symbols(self):
        return [
            {
                "symbol": "MSFT",
                "displaySymbol": "MSFT",
                "description": "MICROSOFT CORP",
                "currency": "USD",
                "type": "Common Stock",
                "mic": "XNAS",
                "figi": "BBG000BPH459",
                "shareClassFIGI": "BBG001S5TD05",
            }
        ]


class _OF:
    batch_size = 100

    def map_jobs(self, jobs):
        return [[] for _ in jobs]


class _YH:
    batch_size = 75

    def quotes(self, symbols):
        return {
            "MSFT": YahooQuote(
                "MSFT",
                "NMS",
                "NasdaqGS",
                "USD",
                "EQUITY",
                "us_market",
                "MICROSOFT CORP",
                None,
                400.0,
                0,
            )
        }


class _MustNotCall:
    batch_size = 75
    metrics = {}

    def __getattr__(self, name):
        if name.startswith("reset_"):
            return lambda: None
        raise AssertionError(f"provider call not expected: {name}")


def test_batch_resolver_uses_registry_before_legacy_cache_and_providers(tmp_path):
    db = CacheDB(tmp_path / "resolver.sqlite")
    try:
        row = _row()
        cold = BatchResolver(db, _FH(), _OF(), _YH())
        first = cold.resolve([row])[row.tv_id]
        assert first.status == "VERIFIED"
        assert cold.stats["registry_write_verified"] == 1

        # Prove the second resolution comes from Registry, not the legacy JSON
        # binding or Finnhub universe cache.
        with db.conn:
            db.conn.execute("DELETE FROM bindings")
            db.conn.execute("DELETE FROM finnhub_symbols")
            db.conn.execute("DELETE FROM meta WHERE key='finnhub_us_refreshed_at'")

        warm = BatchResolver(db, _MustNotCall(), _MustNotCall(), _MustNotCall())
        second = warm.resolve([row])[row.tv_id]
        assert second.status == "VERIFIED"
        assert second.yahoo_symbol == "MSFT"
        assert second.cache_hit is True
        assert warm.stats["registry_hits"] == 1
        assert warm.stats["legacy_cache_hits"] == 0
        assert warm.stats["cache_hits"] == 1
        assert warm.stats["cache_misses"] == 0
    finally:
        db.close()


def test_cache_clear_removes_registry_data_but_keeps_schema_version(tmp_path):
    db = CacheDB(tmp_path / "clear.sqlite")
    try:
        row = _row()
        db.put_registry_tv_yahoo({row.tv_id: row}, [_binding(row)])
        assert db.stats()["registry_mappings"] == 1

        db.clear()
        stats = db.stats()
        assert stats["registry_schema_version"] == 1
        assert stats["registry_securities"] == 0
        assert stats["registry_provider_identifiers"] == 0
        assert stats["registry_mappings"] == 0
    finally:
        db.close()


def test_legacy_verified_cache_hit_is_not_blindly_promoted(tmp_path):
    db = CacheDB(tmp_path / "legacy_no_promotion.sqlite")
    try:
        row = _row()
        binding = _binding(row)
        # Simulate a pre-Registry JSON binding: it may contain provider evidence,
        # but its persisted payload did not bind that evidence to the current
        # TvRow source fingerprint/ISIN snapshot.
        db.put_bindings([binding])

        resolver = BatchResolver(db, _MustNotCall(), _MustNotCall(), _MustNotCall())
        got = resolver.resolve([row])[row.tv_id]
        assert got.status == "VERIFIED"
        assert got.cache_hit is True
        assert resolver.stats["registry_hits"] == 0
        assert resolver.stats["legacy_cache_hits"] == 1
        assert db.stats()["registry_mappings"] == 0
    finally:
        db.close()


class _YHWrongVenue:
    batch_size = 75

    def quotes(self, symbols):
        return {
            "MSFT": YahooQuote(
                "MSFT",
                "NYQ",
                "NYSE",
                "USD",
                "EQUITY",
                "us_market",
                "MICROSOFT CORP",
                None,
                400.0,
                0,
            )
        }


def test_fresh_nontransient_rejection_deactivates_older_registry_verification(tmp_path):
    db = CacheDB(tmp_path / "rejection_invalidates.sqlite")
    try:
        row = _row()
        first = BatchResolver(db, _FH(), _OF(), _YH())
        assert first.resolve([row])[row.tv_id].status == "VERIFIED"
        assert db.stats()["registry_mappings"] == 1

        refreshed = BatchResolver(db, _FH(), _OF(), _YHWrongVenue())
        rejected = refreshed.resolve([row], refresh=True)[row.tv_id]
        assert rejected.status == "REJECTED"
        assert refreshed.stats["registry_resolution_invalidations"] == 1

        hits, lookup = db.get_registry_tv_yahoo(
            [row],
            accepted_policies=[RESOLVER_VERSION],
            max_age_seconds=3600,
        )
        assert hits == {}
        assert lookup.stale_or_incompatible == 1

        # Normal warm resolution now sees the newer cached rejection; it cannot
        # resurrect the older Registry VERIFIED edge.
        warm = BatchResolver(db, _MustNotCall(), _MustNotCall(), _MustNotCall())
        got = warm.resolve([row])[row.tv_id]
        assert got.status == "REJECTED"
        assert warm.stats["registry_hits"] == 0
        assert warm.stats["legacy_cache_hits"] == 1
    finally:
        db.close()


def test_registry_strong_anchor_conflict_does_not_merge_securities(tmp_path):
    db = CacheDB(tmp_path / "anchor_conflict.sqlite")
    try:
        first = _row()
        assert db.put_registry_tv_yahoo(
            {first.tv_id: first}, [_binding(first)]
        )["written"] == 1

        # Same shareClassFIGI but a different current ISIN is not silently added
        # to the existing security. Historical identifier migration needs an
        # explicit lifecycle rule; schema-v1 plumbing stays fail-closed.
        changed = _row(
            tv_id="BATS:MSFT",
            prefix="BATS",
            isin="US0378331005",
        )
        changed_binding = _binding(
            changed,
            source_mic="BATS",
            target_mic="XNAS",
        )
        metrics = db.put_registry_tv_yahoo(
            {changed.tv_id: changed}, [changed_binding]
        )
        assert metrics["conflicts"] == 1
        assert metrics["written"] == 0

        identifiers = db.conn.execute(
            """SELECT namespace,identifier_value
               FROM registry_security_identifiers
               ORDER BY namespace,identifier_value"""
        ).fetchall()
        assert [(row["namespace"], row["identifier_value"]) for row in identifiers] == [
            ("ISIN", "US5949181045"),
            ("SHARE_CLASS_FIGI", "BBG001S5TD05"),
        ]
    finally:
        db.close()
