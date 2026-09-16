from tv_market_identity.cli import parser

def test_v093_currency_unknown_audit_flag():
    args = parser().parse_args(["run", "--us-yahoo-currency-unknown-audit", "audit.jsonl"])
    assert args.us_yahoo_currency_unknown_audit == "audit.jsonl"


def test_v0416_currency_unknown_audit_keeps_missing_isin(tmp_path, monkeypatch):
    import json
    import sys
    import types
    from types import SimpleNamespace
    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)
    import tv_market_identity.cli as cli
    from tv_market_identity.models import Binding, TvRow

    row = TvRow("NYSE:NOISIN", "NYSE", "NOISIN", None, "USD", "stock", ("common",), None, None, None, None)
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED",
                      rejection_reason="YAHOO_CURRENCY_MISMATCH:?")
    class OF:
        def map_jobs(self, jobs):
            assert jobs == []
            return []
    class Y:
        def quotes(self, symbols): return {}
        def chart_quotes(self, symbols): return {}
        def search_exact_isin(self, isin): raise AssertionError("missing ISIN must not be searched")
    out = tmp_path / "currency-missing.jsonl"
    cli._write_us_yahoo_currency_unknown_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text().strip())
    assert rec["diagnostic_release"] == "0.4.16"
    assert rec["classification"] == "MISSING_TV_ISIN"
    assert rec["tv_isin"] is None
    assert rec["source_scoped_openfigi"] == []
    assert rec["unscoped_openfigi"] == []
    assert rec["yahoo_exact_isin_candidate_count"] == 0
