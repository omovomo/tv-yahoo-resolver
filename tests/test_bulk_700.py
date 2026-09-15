from tv_market_identity.cache import CacheDB
from tv_market_identity.models import TvRow, YahooQuote
from tv_market_identity.resolver import BatchResolver


class FH700:
    def __init__(self):
        self.calls = 0

    def us_symbols(self):
        self.calls += 1
        return [
            {
                "symbol": f"T{i:03d}",
                "displaySymbol": f"T{i:03d}",
                "description": f"TEST {i}",
                "currency": "USD",
                "type": "Common Stock",
                "mic": "XNAS",
                "figi": f"COMP{i:08d}",
                "shareClassFIGI": f"SHARE{i:08d}",
            }
            for i in range(700)
        ]


class OFUnused:
    batch_size = 100

    def map_jobs(self, jobs):
        raise AssertionError("OpenFIGI must not be called for NASDAQ fast path")


class YH700:
    batch_size = 75

    def __init__(self):
        self.calls = 0

    def quotes(self, symbols):
        self.calls += 1
        return {
            s: YahooQuote(s, "NMS", "NasdaqGS", "USD", "EQUITY", "us_market", s, s, 100.0, 0)
            for s in symbols
        }


def make_rows():
    return [
        TvRow(
            tv_id=f"NASDAQ:T{i:03d}",
            prefix="NASDAQ",
            symbol=f"T{i:03d}",
            name=f"TEST {i}",
            currency="USD",
            tv_type="stock",
            type_specs=("common",),
            sector="Technology Services",
            market_cap=20e9,
            close=100.0,
        )
        for i in range(700)
    ]


def test_700_rows_warm_cache_skips_identity_providers(tmp_path):
    db = CacheDB(tmp_path / "bulk.sqlite")
    fh = FH700()
    yh = YH700()
    rows = make_rows()

    cold = BatchResolver(db, fh, OFUnused(), yh)
    first = cold.resolve(rows)
    assert len(first) == 700
    assert all(b.status == "VERIFIED" for b in first.values())
    assert fh.calls == 1
    assert cold.stats["yahoo_http_batches"] == 10

    warm = BatchResolver(db, fh, OFUnused(), yh)
    second = warm.resolve(rows)
    assert sum(b.cache_hit for b in second.values()) == 700
    assert fh.calls == 1  # no second Finnhub universe fetch

    warm.refresh_cached_quotes(second)
    assert warm.stats["yahoo_quote_refresh_batches"] == 10
    assert all(b.quote_status == "FRESH" for b in second.values())
    assert all(b.yahoo_price == 100.0 for b in second.values())
    db.close()
