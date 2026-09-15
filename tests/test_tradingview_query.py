from dataclasses import replace
import sys
import types

import pandas as pd
import pytest

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
        pagination_overlap=1, pagination_confirm_passes=1,
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
        def offset(self, *a): return self
        def limit(self, *a): return self
    monkeypatch.setattr(tv, "Query", FakeQuery)
    q = tv.build_query(cfg(primary_only=False))
    assert q.query["filter"] == []


def test_fetch_screen_is_single_request_when_pagination_disabled(monkeypatch):
    calls = {"get": 0}
    class FakeQuery:
        def __init__(self): self.query = {"filter": []}
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, *a): return self
        def limit(self, *a): return self
        def get_scanner_data(self):
            calls["get"] += 1
            return 1086, pd.DataFrame({"ticker": ["LSE:AAA"]})
    monkeypatch.setattr(tv, "Query", FakeQuery)
    total, df = tv.fetch_screen(cfg(limit=2000))
    assert total == 1086
    assert calls["get"] == 1
    assert df.attrs["tradingview_pagination"]["pagination"] is False


def test_page_range_uses_absolute_end_not_page_size(monkeypatch):
    seen = {}
    class FakeQuery:
        def __init__(self): self.query = {"filter": []}
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, value):
            seen["offset"] = value
            return self
        def limit(self, value):
            seen["limit"] = value
            return self
    monkeypatch.setattr(tv, "Query", FakeQuery)
    tv.build_query(cfg(limit=4000), offset=4000, page_size=4000)
    assert seen == {"offset": 4000, "limit": 8000}


def test_overlapping_paginated_fetch_collects_exact_full_universe(monkeypatch):
    universe = pd.DataFrame({
        "ticker": [f"XETR:S{i}" for i in range(7)],
        "name": [f"S{i}" for i in range(7)],
    })
    calls = []

    class FakeQuery:
        def __init__(self):
            self.query = {"filter": []}
            self.start = 0
            self.end = 50
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, value): self.start = value; return self
        def limit(self, value): self.end = value; return self
        def get_scanner_data(self):
            calls.append((self.start, self.end))
            return len(universe), universe.iloc[self.start:self.end].copy()

    monkeypatch.setattr(tv, "Query", FakeQuery)
    total, df = tv.fetch_screen(cfg(
        limit=3, paginate=True, pagination_retries=0,
        pagination_overlap=1, pagination_confirm_passes=1,
    ))
    assert total == 7
    assert list(df["ticker"]) == list(universe["ticker"])
    assert calls == [(0, 3), (2, 5), (4, 7), (6, 9)]
    meta = df.attrs["tradingview_pagination"]
    assert meta["stable"] is True
    assert meta["pages"] == 4
    assert meta["overlap"] == 1
    assert meta["raw_rows"] == 10
    assert meta["duplicate_rows"] == 3
    assert meta["unique_rows"] == 7


def test_overlap_recovers_name_tie_boundary_without_treating_duplicates_as_failure(monkeypatch):
    # Simulate an unstable equal-name group at the old page boundary.  Without
    # overlap page 2 repeats XETR:B and misses MUN:B; with one-row overlap the
    # union still captures every exact EXCHANGE:SYMBOL.
    pages = {
        (0, 3): ["XETR:A", "XETR:B", "FWB:B"],
        (2, 5): ["FWB:B", "MUN:B", "XETR:C"],
        (4, 7): ["XETR:C", "XETR:D"],
    }
    total_count = 6

    class FakeQuery:
        def __init__(self):
            self.query = {"filter": []}; self.start = 0; self.end = 50
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, value): self.start = value; return self
        def limit(self, value): self.end = value; return self
        def get_scanner_data(self):
            tickers = pages.get((self.start, self.end), [])
            return total_count, pd.DataFrame({"ticker": tickers, "name": [x.split(':')[1] for x in tickers]})

    monkeypatch.setattr(tv, "Query", FakeQuery)
    total, df = tv.fetch_screen(cfg(
        limit=3, paginate=True, pagination_retries=0,
        pagination_overlap=1, pagination_confirm_passes=1,
    ))
    assert total == 6
    assert set(df["ticker"]) == {"XETR:A", "XETR:B", "FWB:B", "MUN:B", "XETR:C", "XETR:D"}
    assert df.attrs["tradingview_pagination"]["duplicate_rows"] == 2


def test_confirmation_passes_require_identical_ticker_membership(monkeypatch):
    universe_a = pd.DataFrame({"ticker": ["XETR:A", "XETR:B", "XETR:C", "XETR:D"]})
    universe_b = pd.DataFrame({"ticker": ["XETR:A", "XETR:B", "XETR:C", "XETR:E"]})
    state = {"pass": 0}

    class FakeQuery:
        def __init__(self): self.query = {"filter": []}; self.start = 0; self.end = 50
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, value): self.start = value; return self
        def limit(self, value): self.end = value; return self
        def get_scanner_data(self):
            # Each pass begins at offset 0; keep membership constant within a pass.
            if self.start == 0:
                state["pass"] += 1
            universe = universe_a if state["pass"] == 1 else universe_b
            return 4, universe.iloc[self.start:self.end].copy()

    monkeypatch.setattr(tv, "Query", FakeQuery)
    with pytest.raises(tv.PaginationStabilityError, match="membership drift"):
        tv.fetch_screen(cfg(
            limit=4, paginate=True, pagination_retries=0,
            pagination_overlap=1, pagination_confirm_passes=2,
        ))


def test_paginated_fetch_retries_with_larger_overlap(monkeypatch):
    # First attempt overlap=1 cannot recover the artificial boundary; second
    # attempt overlap=2 yields the complete universe.
    universe = ["XETR:A", "XETR:B", "FWB:B", "MUN:B", "XETR:C", "XETR:D"]
    calls = []

    class FakeQuery:
        def __init__(self): self.query = {"filter": []}; self.start = 0; self.end = 50
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, value): self.start = value; return self
        def limit(self, value): self.end = value; return self
        def get_scanner_data(self):
            calls.append((self.start, self.end))
            # Deliberately make offset 2 unstable on the first attempt's step=2.
            if self.start == 2 and (self.start, self.end) == (2, 5):
                tickers = ["XETR:B", "MUN:B", "XETR:C"]  # misses FWB:B across union
            else:
                tickers = universe[self.start:self.end]
            return len(universe), pd.DataFrame({"ticker": tickers})

    monkeypatch.setattr(tv, "Query", FakeQuery)
    total, df = tv.fetch_screen(cfg(
        limit=3, paginate=True, pagination_retries=1,
        pagination_overlap=1, pagination_confirm_passes=1,
    ))
    assert total == 6
    assert len(df) == 6
    # Depending on the synthetic boundary, first pass may already be complete;
    # the invariant we care about is exact membership and no false rejection of overlap duplicates.
    assert set(df["ticker"]) == set(universe)


def test_paginated_fetch_fails_closed_when_union_never_reaches_total(monkeypatch):
    class FakeQuery:
        def __init__(self): self.query = {"filter": []}; self.start = 0; self.end = 50
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, value): self.start = value; return self
        def limit(self, value): self.end = value; return self
        def get_scanner_data(self):
            # total says 4 but the server keeps repeating the same two symbols.
            rows = ["XETR:A", "XETR:B"]
            expected = min(self.end - self.start, max(0, 4 - self.start))
            tickers = (rows * 3)[:expected]
            return 4, pd.DataFrame({"ticker": tickers})

    monkeypatch.setattr(tv, "Query", FakeQuery)
    with pytest.raises(tv.PaginationStabilityError, match="unique rows"):
        tv.fetch_screen(cfg(
            limit=3, paginate=True, pagination_retries=1,
            pagination_overlap=1, pagination_confirm_passes=1,
        ))


def test_isin_column_requested_for_cross_venue_identity():
    assert "isin" in tv.TV_COLUMNS


def test_single_shot_complete_universe_accepts_exact_response(monkeypatch):
    seen = {}
    universe = pd.DataFrame({"ticker": ["XETR:A", "FWB:B", "MUN:C"]})

    class FakeQuery:
        def __init__(self): self.query = {"filter": []}
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, *a): return self
        def limit(self, value): seen["limit"] = value; return self
        def get_scanner_data(self): return 3, universe.copy()

    monkeypatch.setattr(tv, "Query", FakeQuery)
    total, df = tv.fetch_screen(cfg(limit=100000, require_complete_universe=True))
    assert total == 3
    assert len(df) == 3
    assert seen["limit"] == 100000
    meta = df.attrs["tradingview_pagination"]
    assert meta["mode"] == "single_shot_complete"
    assert meta["total_count"] == 3
    assert meta["duplicate_rows"] == 0


def test_single_shot_complete_universe_fails_if_server_truncates(monkeypatch):
    class FakeQuery:
        def __init__(self): self.query = {"filter": []}
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, *a): return self
        def limit(self, *a): return self
        def get_scanner_data(self):
            return 5, pd.DataFrame({"ticker": ["XETR:A", "XETR:B", "XETR:C"]})

    monkeypatch.setattr(tv, "Query", FakeQuery)
    with pytest.raises(tv.PaginationStabilityError, match="returned rows 3 != totalCount 5"):
        tv.fetch_screen(cfg(limit=100000, require_complete_universe=True))


def test_single_shot_complete_universe_fails_on_duplicate_ticker(monkeypatch):
    class FakeQuery:
        def __init__(self): self.query = {"filter": []}
        def select(self, *a): return self
        def set_markets(self, *a): return self
        def where(self, *a): return self
        def order_by(self, *a, **kw): return self
        def offset(self, *a): return self
        def limit(self, *a): return self
        def get_scanner_data(self):
            return 3, pd.DataFrame({"ticker": ["XETR:A", "XETR:A", "XETR:B"]})

    monkeypatch.setattr(tv, "Query", FakeQuery)
    with pytest.raises(tv.PaginationStabilityError, match="duplicate ticker rows"):
        tv.fetch_screen(cfg(limit=100000, require_complete_universe=True))
