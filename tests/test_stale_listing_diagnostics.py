import json
import sys
import types

fake_tv = types.ModuleType("tradingview_screener")
fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
sys.modules.setdefault("tradingview_screener", fake_tv)

from tv_market_identity import cli
from tv_market_identity.models import Binding, TvRow


def test_rejection_audit_records_snapshot_activity_and_targeted_tv_identifiers(tmp_path, monkeypatch):
    row = TvRow(
        "GETTEX:OLD", "GETTEX", "OLD", "Old Listing", "EUR", "stock", ("common",),
        None, None, 1.0, "US0000000001", False,
    )
    binding = Binding(
        row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED",
        rejection_reason="OPENFIGI_SOURCE_NO_MATCH",
    )

    monkeypatch.setattr(cli, "probe_identifier_metadata", lambda tickers: {
        "GETTEX:OLD": {
            "requested_ticker": "GETTEX:OLD", "found": True,
            "active_symbol": False, "isin": "US0000000001",
            "cusip": "123456789", "figi": "BBG000TEST01",
            "field_sources": {"cusip": "cusip", "figi": "figi"}, "errors": {},
        }
    })

    class OF:
        def map_jobs(self, jobs):
            return [[] for _ in jobs]

    class Y:
        batch_size = 75
        def quotes(self, symbols): return {}

    out = tmp_path / "audit.jsonl"
    cli._write_rejection_audit(out, [row], {row.tv_id: binding}, types.SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    assert rec["active_symbol"] is False
    assert rec["tradingview_identifier_probe"]["found"] is True
    assert rec["tradingview_identifier_probe"]["cusip"] == "123456789"
    assert rec["tradingview_identifier_probe"]["figi"] == "BBG000TEST01"
