from tv_market_identity.providers import YahooProvider


class FakeData:
    def __init__(self):
        self.calls = []
        self.round = 0

    def get_raw_json(self, url, params=None, timeout=None):
        symbols = (params or {}).get("symbols", "").split(",") if params else []
        symbols = [s for s in symbols if s]
        self.calls.append(tuple(symbols))
        self.round += 1
        rows = []
        for symbol in symbols:
            # MISS is intentionally absent on its first request and returned on
            # its second request to model Yahoo's thin-listing bulk omission.
            if symbol == "MISS.DE" and sum("MISS.DE" in c for c in self.calls) == 1:
                continue
            rows.append({
                "symbol": symbol,
                "exchange": "GER",
                "fullExchangeName": "XETRA",
                "currency": "EUR",
                "quoteType": "EQUITY",
                "market": "de_market",
                "regularMarketPrice": 100.0,
                "exchangeDataDelayedBy": 15,
            })
        return {"quoteResponse": {"result": rows}}


def make_provider():
    p = YahooProvider.__new__(YahooProvider)
    p.batch_size = 75
    p.data = FakeData()
    p._run_quote_memo = {}
    from collections import defaultdict
    p.metrics = defaultdict(int)
    return p


def test_yahoo_positive_quotes_memoize_across_calls_but_missing_rows_retry():
    p = make_provider()

    first = p.quotes(["A.DE", "MISS.DE", "A.DE"])
    assert set(first) == {"A.DE"}
    assert p.data.calls == [("A.DE", "MISS.DE")]

    second = p.quotes(["A.DE", "MISS.DE"])
    assert set(second) == {"A.DE", "MISS.DE"}
    # A.DE is a positive memo hit; MISS.DE was not negative-cached and really
    # went back to Yahoo, allowing the targeted retry to recover it.
    assert p.data.calls == [("A.DE", "MISS.DE"), ("MISS.DE",)]
    assert p.metrics["memo_hits"] == 1
    assert p.metrics["network_symbols"] == 3
    assert p.metrics["network_batches"] == 2
    assert p.metrics["missing_symbols"] == 1


def test_yahoo_reset_run_cache_forces_fresh_positive_lookup():
    p = make_provider()
    p.quotes(["A.DE"])
    p.quotes(["A.DE"])
    assert len(p.data.calls) == 1

    p.reset_run_cache()
    p.quotes(["A.DE"])
    assert len(p.data.calls) == 2
    assert p.metrics["memo_hits"] == 0
    assert p.metrics["network_symbols"] == 1
