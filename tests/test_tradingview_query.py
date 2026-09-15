from dataclasses import replace
import sys
import types

# Stub optional live TradingView dependency for query construction tests.
fake_mod = types.ModuleType("tradingview_screener")
fake_mod.Column = lambda name: name
fake_mod.Query = object
sys.modules.setdefault("tradingview_screener", fake_mod)

from tv_market_identity.config import ScreenConfig
import tv_market_identity.tradingview as tv


def cfg(**kwargs):
    base = ScreenConfig(
        stock_filter_schema=2, limit=2000, order_by="market_cap_basic", ascending=False,
        market="uk", min_market_cap=None, min_avg_volume_90d=None, min_pe=None,
        sectors=(), primary_only=False,
    )
    return replace(base, **kwargs)


def test_market_only_explicitly_clears_library_primary_default(monkeypatch):
    class FakeQuery:
        def __init__(self):
            self.query = {"filter": [{"left": "is_primary", "operation": "equal", "right": True}]}
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a):
            self.query["filter"] = list(a)
            return self
        def order_by(self, *a, **kw): return self
        def limit(self, *a): return self
    monkeypatch.setattr(tv, "Query", FakeQuery)
    q = tv.build_query(cfg(primary_only=False))
    assert q.query["filter"] == []


def test_fetch_screen_is_single_request(monkeypatch):
    calls = {"get": 0}
    class FakeQuery:
        def __init__(self): self.query = {"filter": []}
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def limit(self, *a): return self
        def get_scanner_data(self):
            calls["get"] += 1
            return 1086, object()
    monkeypatch.setattr(tv, "Query", FakeQuery)
    total, _ = tv.fetch_screen(cfg(limit=2000))
    assert total == 1086
    assert calls["get"] == 1


def test_isin_column_requested_for_cross_venue_identity():
    assert "isin" in tv.TV_COLUMNS
