"""Test-only compatibility stub for the optional live TradingView dependency.

The production package still imports and requires ``tradingview_screener`` at
runtime.  Unit tests replace Query/Column as needed and must not require network
or the third-party package merely during test collection.
"""
from __future__ import annotations

import importlib.util
import sys
import types


if importlib.util.find_spec("tradingview_screener") is None:
    stub = types.ModuleType("tradingview_screener")

    class _Column:
        def __init__(self, name):
            self.name = name

        def _condition(self, op, value):
            return (op, self.name, value)

        def __gt__(self, value):
            return self._condition("gt", value)

        def __eq__(self, value):
            return self._condition("eq", value)

        def isin(self, values):
            return self._condition("in", list(values))

    class _Query:
        def __init__(self, *args, **kwargs):
            self.query = {"filter": []}

        def select(self, *args, **kwargs): return self
        def set_markets(self, *args, **kwargs): return self
        def where(self, *args, **kwargs): return self
        def order_by(self, *args, **kwargs): return self
        def offset(self, *args, **kwargs): return self
        def limit(self, *args, **kwargs): return self

        def get_scanner_data(self):
            raise RuntimeError(
                "test TradingView stub cannot perform live scanner requests"
            )

    stub.Column = _Column
    stub.Query = _Query
    sys.modules["tradingview_screener"] = stub
