"""Phase D1: broker ISIN can prove a security; it cannot choose a listing."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from tv_market_identity.broker import (
    BrokerInputError,
    IbkrSecurityRequest,
    reconcile_ibkr_security_batch,
)
from tv_market_identity.broker_cli import parser, run
from tv_market_identity.cache import CacheDB
from tv_market_identity.models import Binding, TvRow
from tv_market_identity.policy import RESOLVER_VERSION


def _tv(tv_id="NASDAQ:MSFT"):
    prefix, symbol = tv_id.split(":")
    return TvRow(tv_id, prefix, symbol, "Microsoft Corp", "USD", "stock", ("common",),
                 None, None, None, "US5949181045", True)


def _verified(row, yahoo="MSFT", timestamp=None):
    now = int(time.time()) if timestamp is None else timestamp
    return Binding(
        tv_id=row.tv_id, tv_symbol=row.symbol, tv_prefix=row.prefix,
        tv_currency=row.currency, tv_type=row.tv_type, status="VERIFIED",
        yahoo_symbol=yahoo, yahoo_exchange="NMS", yahoo_market="us_market",
        yahoo_quote_type="EQUITY", yahoo_currency="USD", yahoo_price=None,
        yahoo_delayed_by=None, quote_status="STALE_CACHED", resolved_mic="XNAS",
        source_mic="XNAS", target_mic="XNAS", mapping_method="SAME_VENUE",
        share_class_figi="BBG001S5TD05", fingerprint="test-proof",
        resolver_version=RESOLVER_VERSION, validated_at=now,
        expires_at=now + 3600,
    )


def _broker(conid="272093", isin="US5949181045", **kwargs):
    return IbkrSecurityRequest("a", conid, "MSFT", isin, "USD", "STK", **kwargs)


def test_read_only_security_match_never_returns_trusted_routing(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    tv = _tv()
    db.put_registry_tv_yahoo({tv.tv_id: tv}, [_verified(tv)])
    before = db.stats().copy()
    got = reconcile_ibkr_security_batch(db.conn, [_broker()])
    assert got.telemetry["security_matches"] == 1
    item = got.results[0]
    assert item.status == "SECURITY_MATCH"
    assert item.tv_candidates == ("NASDAQ:MSFT",)
    assert item.yahoo_candidates == ("MSFT",)
    wire = item.as_dict()
    assert wire["listing_verified"] is False
    assert wire["conid_verified"] is False
    assert wire["match_method"] == "EXACT_ISIN_REGISTRY"
    assert wire["tv_id"] is None
    assert wire["yahoo_symbol"] is None
    assert db.stats() == before
    db.close()


def test_legacy_only_never_backfills_or_implies_security_match(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    tv = _tv()
    db.put_bindings([_verified(tv)])
    item = reconcile_ibkr_security_batch(db.conn, [_broker()]).results[0]
    assert (item.status, item.reason) == ("UNRESOLVED", "NO_CURRENT_REGISTRY_PROOF")
    assert db.stats()["registry_securities"] == 0
    db.close()


def test_missing_isin_does_not_match_by_symbol_or_conid(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    tv = _tv()
    db.put_registry_tv_yahoo({tv.tv_id: tv}, [_verified(tv)])
    item = reconcile_ibkr_security_batch(db.conn, [_broker(isin=None)]).results[0]
    assert (item.status, item.reason) == ("UNRESOLVED", "ISIN_REQUIRED_FOR_SECURITY_MATCH")
    db.close()


def test_wrong_isin_and_inactive_registry_identifier(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    tv = _tv()
    db.put_registry_tv_yahoo({tv.tv_id: tv}, [_verified(tv)])
    assert reconcile_ibkr_security_batch(db.conn, [_broker(isin="US0378331005")]).results[0].status == "UNRESOLVED"
    db.conn.execute("UPDATE registry_security_identifiers SET lifecycle_state='INACTIVE' WHERE namespace='ISIN'")
    db.conn.commit()
    assert reconcile_ibkr_security_batch(db.conn, [_broker()]).results[0].status == "UNRESOLVED"
    db.close()


def test_stale_or_wrong_policy_proof_does_not_match(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    tv = _tv()
    db.put_registry_tv_yahoo({tv.tv_id: tv}, [_verified(tv)])
    db.conn.execute("UPDATE registry_mappings SET last_verified_at=?", (int(time.time()) - 70 * 86400,))
    db.conn.commit()
    assert reconcile_ibkr_security_batch(db.conn, [_broker()]).results[0].status == "UNRESOLVED"
    db.conn.execute("UPDATE registry_mappings SET last_verified_at=?,resolver_policy='unknown-policy'", (int(time.time()),))
    db.conn.commit()
    assert reconcile_ibkr_security_batch(db.conn, [_broker()]).results[0].status == "UNRESOLVED"
    db.close()


def test_mismatched_source_isin_metadata_or_proof_fingerprint(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    tv = _tv()
    db.put_registry_tv_yahoo({tv.tv_id: tv}, [_verified(tv)])
    db.conn.execute("UPDATE registry_mappings SET source_fingerprint='tampered'")
    db.conn.commit()
    assert reconcile_ibkr_security_batch(db.conn, [_broker()]).results[0].status == "UNRESOLVED"
    db.close()


def test_multiple_tv_listings_are_candidates_not_listing_verification(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    first = _tv()
    second = _tv("BATS:MSFT")
    metrics = db.put_registry_tv_yahoo(
        {first.tv_id: first, second.tv_id: second}, [_verified(first), _verified(second)]
    )
    assert metrics["written"] == 2
    item = reconcile_ibkr_security_batch(db.conn, [_broker()]).results[0]
    assert item.status == "SECURITY_MATCH"
    assert item.tv_candidates == ("BATS:MSFT", "NASDAQ:MSFT")
    assert item.yahoo_candidates == ("MSFT",)
    assert item.as_dict()["tv_id"] is None
    db.close()


def test_conid_conflicting_isin_fails_entire_batch(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    tv = _tv()
    db.put_registry_tv_yahoo({tv.tv_id: tv}, [_verified(tv)])
    batch = reconcile_ibkr_security_batch(db.conn, [
        IbkrSecurityRequest("a", "272093", "MSFT", "US5949181045", "USD", "STK"),
        IbkrSecurityRequest("b", "272093", "AAPL", "US0378331005", "USD", "STK"),
    ])
    assert [r.status for r in batch.results] == ["CONFLICT", "CONFLICT"]
    assert batch.telemetry["listing_verified"] == 0
    db.close()


def test_input_rejects_malformed_and_ticker_only():
    with pytest.raises(BrokerInputError):
        IbkrSecurityRequest("a", symbol="MSFT")
    for conid in ("-1", "xyz", "0"):
        with pytest.raises(BrokerInputError):
            IbkrSecurityRequest("a", conid=conid)
    with pytest.raises(BrokerInputError):
        IbkrSecurityRequest.from_mapping({"request_id":"a", "conid":"5", "manual_yahoo":"MSFT"})
    with pytest.raises(BrokerInputError):
        IbkrSecurityRequest("a", isin="bad")
    with pytest.raises(BrokerInputError):
        IbkrSecurityRequest("a", conid="5", asset_class="OPT")


def test_read_only_cli_and_same_number_of_output_lines(tmp_path, capsys):
    path = tmp_path / "ident.sqlite3"
    db = CacheDB(path)
    tv = _tv()
    db.put_registry_tv_yahoo({tv.tv_id: tv}, [_verified(tv)])
    db.close()
    inp = tmp_path / "input.jsonl"
    out = tmp_path / "result.jsonl"
    inp.write_text(json.dumps({"request_id":"a", "conid":"272093", "isin":tv.isin}) + "\n" +
                   json.dumps({"request_id":"b", "conid":"7"}) + "\n")
    args = parser().parse_args(["--cache", str(path), "--input", str(inp), "--output", str(out), "--telemetry"])
    assert run(args) == 0
    decisions = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(decisions) == 2
    assert [d["status"] for d in decisions] == ["SECURITY_MATCH", "UNRESOLVED"]
    assert json.loads(capsys.readouterr().err)["listing_verified"] == 0
    # Read-only transport must not leave an additional persistent table or mutate evidence.
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM registry_provider_identifiers WHERE provider='IBKR'").fetchone()[0] == 0
    conn.close()


def test_many_broker_records_one_isin_batch_indexed(tmp_path):
    db = CacheDB(tmp_path / "ident.sqlite3")
    tv = _tv()
    db.put_registry_tv_yahoo({tv.tv_id: tv}, [_verified(tv)])
    reqs = [IbkrSecurityRequest(str(i), str(100000 + i), "MSFT", tv.isin)
            for i in range(700)]
    got = reconcile_ibkr_security_batch(db.conn, reqs)
    assert len(got.results) == 700
    assert got.telemetry == {
        "requested": 700, "security_matches": 700, "unresolved": 0,
        "conflicts": 0, "listing_verified": 0,
    }
    assert all(r.as_dict()["yahoo_symbol"] is None for r in got.results)
    db.close()
