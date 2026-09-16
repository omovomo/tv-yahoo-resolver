from collections import defaultdict

from tv_market_identity.cache import CacheDB
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.providers import YahooProvider
from tv_market_identity.resolver import BatchResolver, _home_market_local_symbol


def ofi(ticker, share, *, sec_type="Common Stock", sec_type2="Common Stock"):
    return OpenFigiIdentity(
        figi=f"FIGI_{ticker}",
        composite_figi=f"COMP_{ticker}",
        share_class_figi=share,
        ticker=ticker,
        name="HOME SECURITY",
        security_type=sec_type,
        security_type2=sec_type2,
        exch_code="US",
    )


class OFHome:
    batch_size = 100

    def __init__(self, identities):
        self.identities = identities
        self.jobs = []

    def map_jobs(self, jobs):
        self.jobs.extend(jobs)
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "US1234567890" and "micCode" not in job:
                out.append(list(self.identities))
            else:
                out.append([])
        return out


class YHHome:
    batch_size = 75

    def __init__(self, *, candidates=None, quote=None, chart=None):
        self.candidates = candidates or []
        self.quote = quote
        self.chart = chart
        self.searches = []

    def search_exact_isin(self, isin):
        self.searches.append(isin)
        return list(self.candidates)

    def quotes(self, symbols):
        if self.quote is not None and self.quote.symbol in symbols:
            return {self.quote.symbol: self.quote}
        return {}

    def chart_quotes(self, symbols):
        if self.chart is not None and self.chart.symbol in symbols:
            return {self.chart.symbol: self.chart}
        return {}


def row():
    return TvRow(
        "GETTEX:TTSH", "GETTEX", "TTSH", "Tile Shop Holdings", "EUR",
        "stock", ("common",), None, 1.0, 5.0, isin="US1234567890",
    )


def candidate(symbol="TTSH", exchange="NCM"):
    return YahooSearchCandidate(symbol, exchange, "EQUITY", "Tile Shop", "Tile Shop Holdings, Inc.")


def quote(symbol="TTSH", exchange="NCM", currency="USD", qtype="EQUITY"):
    return YahooQuote(
        symbol, exchange, "Nasdaq Capital Market", currency, qtype, "us_market",
        "Tile Shop", "Tile Shop Holdings, Inc.", 5.0, 0,
    )


def test_home_market_rescue_accepts_different_currency_with_exact_isin_share_class(tmp_path):
    db = CacheDB(tmp_path / "home.sqlite")
    of = OFHome([ofi("TTSH", "SHARE1")])
    yh = YHHome(candidates=[candidate()], quote=quote())
    resolver = BatchResolver(db, None, of, yh)

    b = resolver.resolve([row()])["GETTEX:TTSH"]

    assert b.status == "VERIFIED"
    assert b.mapping_method == "YAHOO_EXACT_ISIN_HOME_MARKET"
    assert b.yahoo_symbol == "TTSH"
    assert b.yahoo_currency == "USD"
    assert b.yahoo_exchange == "NCM"
    assert b.share_class_figi == "SHARE1"
    assert b.target_mic is None
    assert b.source_venue_code == "GETTEX"
    assert yh.searches == ["US1234567890"]
    assert resolver.stats["yahoo_home_market_rescue_matches"] == 1
    db.close()


def test_home_market_rescue_accepts_partial_share_class_when_candidate_matches_proven_row(tmp_path):
    db = CacheDB(tmp_path / "partial-share.sqlite")
    # Same exact ISIN: one OpenFIGI venue row carries the share class while
    # another has provider-missing shareClassFIGI. The missing row is not used
    # as evidence; Yahoo must match the explicitly tagged row.
    resolver = BatchResolver(
        db, None,
        OFHome([ofi("TTSH", "SHARE1"), ofi("OTHER", None)]),
        YHHome(candidates=[candidate("TTSH")], quote=quote("TTSH")),
    )
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "VERIFIED"
    assert b.share_class_figi == "SHARE1"
    assert resolver.stats["openfigi_home_market_partial_share_class_accepted"] == 1
    db.close()


def test_home_market_rescue_partial_share_class_cannot_use_missing_share_row_as_proof(tmp_path):
    db = CacheDB(tmp_path / "partial-no-proof.sqlite")
    resolver = BatchResolver(
        db, None,
        OFHome([ofi("OTHER", "SHARE1"), ofi("TTSH", None)]),
        YHHome(candidates=[candidate("TTSH")], quote=quote("TTSH")),
    )
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "REJECTED"
    assert resolver.stats["openfigi_home_market_partial_share_class_accepted"] == 1
    assert resolver.stats["yahoo_home_market_search_ticker_unconfirmed"] == 1
    db.close()


def test_home_market_rescue_rejects_when_all_compatible_share_classes_missing(tmp_path):
    db = CacheDB(tmp_path / "missing-share.sqlite")
    resolver = BatchResolver(
        db, None,
        OFHome([ofi("TTSH", None), ofi("OTHER", None)]),
        YHHome(candidates=[candidate("TTSH")], quote=quote("TTSH")),
    )
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "REJECTED"
    assert resolver.stats["openfigi_home_market_share_class_missing"] == 1
    assert resolver.stats["yahoo_home_market_search_jobs"] == 0
    db.close()


def test_home_market_rescue_rejects_ambiguous_share_class(tmp_path):
    db = CacheDB(tmp_path / "ambig.sqlite")
    resolver = BatchResolver(
        db, None,
        OFHome([ofi("TTSH", "SHARE1"), ofi("TTSH", "SHARE2")]),
        YHHome(candidates=[candidate()], quote=quote()),
    )
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "REJECTED"
    assert resolver.stats["openfigi_home_market_share_class_ambiguous"] == 1
    db.close()


def test_home_market_rescue_requires_yahoo_ticker_in_same_isin_evidence(tmp_path):
    db = CacheDB(tmp_path / "ticker.sqlite")
    resolver = BatchResolver(
        db, None,
        OFHome([ofi("OTHER", "SHARE1")]),
        YHHome(candidates=[candidate("TTSH")], quote=quote("TTSH")),
    )
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "REJECTED"
    assert resolver.stats["yahoo_home_market_search_ticker_unconfirmed"] == 1
    db.close()


def test_home_market_rescue_uses_chart_only_for_missing_quote_metadata(tmp_path):
    db = CacheDB(tmp_path / "chart.sqlite")
    incomplete = YahooQuote(
        "TTSH", None, None, None, "EQUITY", "us_market",
        "Tile Shop", None, 5.0, 0,
    )
    resolver = BatchResolver(
        db, None,
        OFHome([ofi("TTSH", "SHARE1")]),
        YHHome(candidates=[candidate()], quote=incomplete, chart=quote()),
    )
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "VERIFIED"
    assert resolver.stats["yahoo_home_market_chart_matches"] == 1
    db.close()


def test_home_market_rescue_does_not_override_explicit_quote_type_contradiction_with_chart(tmp_path):
    db = CacheDB(tmp_path / "contradiction.sqlite")
    bad = quote(qtype="MUTUALFUND")
    resolver = BatchResolver(
        db, None,
        OFHome([ofi("TTSH", "SHARE1")]),
        YHHome(candidates=[candidate()], quote=bad, chart=quote()),
    )
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "REJECTED"
    assert resolver.stats["yahoo_home_market_chart_matches"] == 0
    db.close()


def test_home_market_rescue_rejects_multiple_valid_yahoo_routes(tmp_path):
    db = CacheDB(tmp_path / "routes.sqlite")

    class YHMulti(YHHome):
        def quotes(self, symbols):
            return {
                "TTSH": quote("TTSH", "NCM"),
                "TTSH.MX": quote("TTSH.MX", "MEX", "MXN"),
            }

    resolver = BatchResolver(
        db, None,
        OFHome([ofi("TTSH", "SHARE1")]),
        YHMulti(candidates=[candidate("TTSH", "NCM"), candidate("TTSH.MX", "MEX")]),
    )
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "REJECTED"
    assert resolver.stats["yahoo_home_market_route_ambiguous"] == 1
    db.close()


def test_home_market_cached_refresh_requires_same_exchange_currency_and_equity(tmp_path):
    db = CacheDB(tmp_path / "refresh.sqlite")
    b = Binding(
        tv_id="GETTEX:TTSH", tv_symbol="TTSH", tv_prefix="GETTEX",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="TTSH", yahoo_exchange="NCM", yahoo_market="us_market",
        yahoo_quote_type="EQUITY", yahoo_currency="USD", mapping_method="YAHOO_EXACT_ISIN_HOME_MARKET",
        share_class_figi="SHARE1", resolver_version="0.3.58-policy58", cache_hit=True,
    )
    yh = YHHome(quote=quote(currency="CAD"))
    resolver = BatchResolver(db, None, OFHome([]), yh)
    bindings = {b.tv_id: b}
    resolver.refresh_cached_quotes(bindings)
    assert b.status == "REJECTED"
    assert b.rejection_reason.startswith("YAHOO_RUNTIME_HOME_MARKET_MISMATCH")
    db.close()


class SearchData:
    def __init__(self):
        self.calls = []

    def get_raw_json(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return {
            "quotes": [
                {
                    "symbol": "ORNAV.HE",
                    "exchange": "HEL",
                    "quoteType": "EQUITY",
                    "shortname": "Orion",
                    "longname": "Orion Oyj",
                },
                {
                    "symbol": "ORNAV.HE",
                    "exchange": "HEL",
                    "quoteType": "EQUITY",
                },
            ]
        }


def test_yahoo_provider_exact_isin_search_is_non_fuzzy_and_memoized():
    p = YahooProvider.__new__(YahooProvider)
    p.batch_size = 75
    p.data = SearchData()
    p._run_quote_memo = {}
    p._run_search_memo = {}
    p.metrics = defaultdict(int)

    first = p.search_exact_isin("FI0009014377")
    second = p.search_exact_isin("FI0009014377")

    assert [x.symbol for x in first] == ["ORNAV.HE"]
    assert [x.symbol for x in second] == ["ORNAV.HE"]
    assert len(p.data.calls) == 1
    _, params = p.data.calls[0]
    assert params["q"] == "FI0009014377"
    assert params["enableFuzzyQuery"] == "false"
    assert params["newsCount"] == 0
    assert p.metrics["search_memo_hits"] == 1


def test_policy59_reuses_policy56_verified_cache_entries(tmp_path):
    import time
    db = CacheDB(tmp_path / "policy56.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="XETR:DTE", tv_symbol="DTE", tv_prefix="XETR",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="DTE.DE", yahoo_exchange="GER", yahoo_market="de_market",
        yahoo_quote_type="EQUITY", yahoo_currency="EUR", resolved_mic="XETR",
        source_mic="XETR", target_mic="XETR", mapping_method="SAME_VENUE",
        resolver_version="0.3.56-policy56", validated_at=now, expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    r = TvRow(
        "XETR:DTE", "XETR", "DTE", "Deutsche Telekom AG", "EUR",
        "stock", ("common",), None, 1.0, 30.0, isin="DE0005557508",
    )
    b = resolver.resolve([r])[r.tv_id]
    assert b.status == "VERIFIED"
    assert b.cache_hit is True
    assert b.resolver_version == "0.3.56-policy56"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    db.close()


def test_policy59_reuses_policy58_home_market_verified_cache_entries(tmp_path):
    import time
    db = CacheDB(tmp_path / "policy58.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="GETTEX:TTSH", tv_symbol="TTSH", tv_prefix="GETTEX",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="TTSH", yahoo_exchange="NCM", yahoo_market="us_market",
        yahoo_quote_type="EQUITY", yahoo_currency="USD",
        share_class_figi="SHARE1", mapping_method="YAHOO_EXACT_ISIN_HOME_MARKET",
        resolver_version="0.3.58-policy58", validated_at=now, expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "VERIFIED"
    assert b.cache_hit is True
    assert b.resolver_version == "0.3.58-policy58"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    db.close()

class OFHomeVenueBridge(OFHome):
    def __init__(self, identities, venue_rows):
        super().__init__(identities)
        self.venue_rows = dict(venue_rows)

    def map_jobs(self, jobs):
        self.jobs.extend(jobs)
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "US1234567890" and "micCode" not in job:
                out.append(list(self.identities))
                continue
            key = (job.get("idType"), job.get("idValue"), job.get("micCode"))
            out.append(list(self.venue_rows.get(key, [])))
        return out


def test_home_market_rescue_confirms_home_listing_via_exact_isin_mic_share_class(tmp_path):
    db = CacheDB(tmp_path / "venue-isin-mic-bridge.sqlite")
    of = OFHomeVenueBridge(
        [ofi("ARXN", "SHARE1")],
        {
            ("ID_ISIN", "US1234567890", "XTSE"): [
                OpenFigiIdentity(
                    figi="FIGI_ARX_XTSE", composite_figi="COMP_ARX_XTSE",
                    share_class_figi="SHARE1", ticker="ARX_CN", name="ARC RESOURCES LTD",
                    security_type="Common Stock", security_type2="Common Stock", exch_code="CN",
                )
            ]
        },
    )
    yh = YHHome(
        candidates=[YahooSearchCandidate("ARX.TO", "TOR", "EQUITY", "ARC Resources", "ARC Resources Ltd.")],
        quote=YahooQuote(
            "ARX.TO", "TOR", "Toronto", "CAD", "EQUITY", "ca_market",
            "ARC Resources", "ARC Resources Ltd.", 33.9, 0,
        ),
    )
    resolver = BatchResolver(db, None, of, yh)
    r = TvRow(
        "GETTEX:8RC", "GETTEX", "8RC", "ARC Resources Ltd.", "EUR",
        "stock", ("common",), None, 1.0, 5.0, isin="US1234567890",
    )

    b = resolver.resolve([r])[r.tv_id]

    assert b.status == "VERIFIED"
    assert b.yahoo_symbol == "ARX.TO"
    assert b.yahoo_currency == "CAD"
    assert b.share_class_figi == "SHARE1"
    assert resolver.stats["openfigi_home_market_isin_mic_confirmation_jobs"] == 1
    assert resolver.stats["openfigi_home_market_isin_mic_confirmation_matches"] == 1
    assert resolver.stats["openfigi_home_market_symbol_confirmation_jobs"] == 0
    assert any(
        job == {"idType": "ID_ISIN", "idValue": "US1234567890", "micCode": "XTSE"}
        for job in of.jobs
    )
    db.close()


def test_home_market_isin_mic_bridge_rejects_conflicting_share_class_without_symbol_fallback(tmp_path):
    db = CacheDB(tmp_path / "venue-isin-mic-wrong-share.sqlite")
    of = OFHomeVenueBridge(
        [ofi("ARXN", "SHARE1")],
        {
            ("ID_ISIN", "US1234567890", "XTSE"): [
                OpenFigiIdentity(
                    figi="FIGI_OTHER", composite_figi="COMP_OTHER",
                    share_class_figi="SHARE2", ticker="ARX", name="OTHER SECURITY",
                    security_type="Common Stock", security_type2="Common Stock", exch_code="CN",
                )
            ],
            ("ID_EXCH_SYMBOL", "ARX", "XTSE"): [
                OpenFigiIdentity(
                    figi="FIGI_ARX_XTSE", composite_figi="COMP_ARX_XTSE",
                    share_class_figi="SHARE1", ticker="ARX", name="ARC RESOURCES LTD",
                    security_type="Common Stock", security_type2="Common Stock", exch_code="CN",
                )
            ],
        },
    )
    yh = YHHome(
        candidates=[YahooSearchCandidate("ARX.TO", "TOR", "EQUITY", "ARC Resources", "ARC Resources Ltd.")],
        quote=YahooQuote(
            "ARX.TO", "TOR", "Toronto", "CAD", "EQUITY", "ca_market",
            "ARC Resources", "ARC Resources Ltd.", 33.9, 0,
        ),
    )
    resolver = BatchResolver(db, None, of, yh)
    r = TvRow(
        "GETTEX:8RC", "GETTEX", "8RC", "ARC Resources Ltd.", "EUR",
        "stock", ("common",), None, 1.0, 5.0, isin="US1234567890",
    )

    b = resolver.resolve([r])[r.tv_id]

    assert b.status == "REJECTED"
    assert resolver.stats["openfigi_home_market_isin_mic_confirmation_share_conflict"] == 1
    assert resolver.stats["openfigi_home_market_symbol_confirmation_jobs"] == 0
    assert resolver.stats["yahoo_home_market_search_ticker_unconfirmed"] == 1
    db.close()


def test_home_market_rescue_confirms_missing_unscoped_ticker_via_exact_exchange_symbol_share_class(tmp_path):
    db = CacheDB(tmp_path / "venue-symbol-bridge.sqlite")
    of = OFHomeVenueBridge(
        [ofi("ARXN", "SHARE1")],
        {
            ("ID_EXCH_SYMBOL", "ARX", "XTSE"): [
                OpenFigiIdentity(
                    figi="FIGI_ARX_XTSE", composite_figi="COMP_ARX_XTSE",
                    share_class_figi="SHARE1", ticker="ARX", name="ARC RESOURCES LTD",
                    security_type="Common Stock", security_type2="Common Stock", exch_code="CN",
                )
            ]
        },
    )
    yh = YHHome(
        candidates=[YahooSearchCandidate("ARX.TO", "TOR", "EQUITY", "ARC Resources", "ARC Resources Ltd.")],
        quote=YahooQuote(
            "ARX.TO", "TOR", "Toronto", "CAD", "EQUITY", "ca_market",
            "ARC Resources", "ARC Resources Ltd.", 33.9, 0,
        ),
    )
    resolver = BatchResolver(db, None, of, yh)
    r = TvRow(
        "GETTEX:8RC", "GETTEX", "8RC", "ARC Resources Ltd.", "EUR",
        "stock", ("common",), None, 1.0, 5.0, isin="US1234567890",
    )

    b = resolver.resolve([r])[r.tv_id]

    assert b.status == "VERIFIED"
    assert b.yahoo_symbol == "ARX.TO"
    assert b.yahoo_currency == "CAD"
    assert b.share_class_figi == "SHARE1"
    assert resolver.stats["openfigi_home_market_symbol_confirmation_jobs"] == 1
    assert resolver.stats["openfigi_home_market_symbol_confirmation_matches"] == 1
    assert any(
        job == {"idType": "ID_EXCH_SYMBOL", "idValue": "ARX", "micCode": "XTSE"}
        for job in of.jobs
    )
    db.close()


def test_home_market_symbol_bridge_rejects_wrong_share_class(tmp_path):
    db = CacheDB(tmp_path / "venue-symbol-wrong-share.sqlite")
    of = OFHomeVenueBridge(
        [ofi("ARXN", "SHARE1")],
        {
            ("ID_EXCH_SYMBOL", "ARX", "XTSE"): [
                OpenFigiIdentity(
                    figi="FIGI_OTHER", composite_figi="COMP_OTHER",
                    share_class_figi="SHARE2", ticker="ARX", name="OTHER SECURITY",
                    security_type="Common Stock", security_type2="Common Stock", exch_code="CN",
                )
            ]
        },
    )
    yh = YHHome(
        candidates=[YahooSearchCandidate("ARX.TO", "TOR", "EQUITY", "ARC Resources", "ARC Resources Ltd.")],
        quote=YahooQuote(
            "ARX.TO", "TOR", "Toronto", "CAD", "EQUITY", "ca_market",
            "ARC Resources", "ARC Resources Ltd.", 33.9, 0,
        ),
    )
    resolver = BatchResolver(db, None, of, yh)
    r = TvRow(
        "GETTEX:8RC", "GETTEX", "8RC", "ARC Resources Ltd.", "EUR",
        "stock", ("common",), None, 1.0, 5.0, isin="US1234567890",
    )

    b = resolver.resolve([r])[r.tv_id]

    assert b.status == "REJECTED"
    assert resolver.stats["openfigi_home_market_symbol_confirmation_share_conflict"] == 1
    assert resolver.stats["yahoo_home_market_search_ticker_unconfirmed"] == 1
    db.close()


def test_home_market_symbol_bridge_does_not_guess_unreviewed_yahoo_exchange(tmp_path):
    db = CacheDB(tmp_path / "venue-symbol-unreviewed.sqlite")
    of = OFHomeVenueBridge([ofi("NOPE", "SHARE1")], {})
    yh = YHHome(
        candidates=[YahooSearchCandidate("OTHER.XY", "XYZ", "EQUITY", "Other", "Other Inc.")],
        quote=YahooQuote(
            "OTHER.XY", "XYZ", "Unknown Exchange", "USD", "EQUITY", "us_market",
            "Other", "Other Inc.", 1.0, 0,
        ),
    )
    resolver = BatchResolver(db, None, of, yh)

    b = resolver.resolve([row()])["GETTEX:TTSH"]

    assert b.status == "REJECTED"
    assert resolver.stats["openfigi_home_market_symbol_confirmation_jobs"] == 0
    assert resolver.stats["yahoo_home_market_search_ticker_unconfirmed"] == 1
    db.close()


def test_policy61_reuses_policy59_verified_cache_entries(tmp_path):
    import time
    db = CacheDB(tmp_path / "policy59.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="GETTEX:TTSH", tv_symbol="TTSH", tv_prefix="GETTEX",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="TTSH", yahoo_exchange="NCM", yahoo_market="us_market",
        yahoo_quote_type="EQUITY", yahoo_currency="USD",
        share_class_figi="SHARE1", mapping_method="YAHOO_EXACT_ISIN_HOME_MARKET",
        resolver_version="0.3.59-policy59", validated_at=now, expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "VERIFIED"
    assert b.cache_hit is True
    assert b.resolver_version == "0.3.59-policy59"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    db.close()


def test_policy62_reuses_policy61_verified_cache_entries(tmp_path):
    import time
    db = CacheDB(tmp_path / "policy61.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="GETTEX:TTSH", tv_symbol="TTSH", tv_prefix="GETTEX",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="TTSH", yahoo_exchange="NCM", yahoo_market="us_market",
        yahoo_quote_type="EQUITY", yahoo_currency="USD",
        share_class_figi="SHARE1", mapping_method="YAHOO_EXACT_ISIN_HOME_MARKET",
        resolver_version="0.3.61-policy61", validated_at=now, expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    b = resolver.resolve([row()])["GETTEX:TTSH"]
    assert b.status == "VERIFIED"
    assert b.cache_hit is True
    assert b.resolver_version == "0.3.61-policy61"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    db.close()


def test_home_market_local_symbol_is_bounded_to_reviewed_mic_suffix_contracts():
    assert _home_market_local_symbol("ARX.TO", "XTSE") == "ARX"
    assert _home_market_local_symbol("DAL.MI", "XMIL") == "DAL"
    assert _home_market_local_symbol("OPTT", "XASE") == "OPTT"
    assert _home_market_local_symbol("DAL.PA", "XMIL") is None
    assert _home_market_local_symbol("OPTT.X", "XASE") is None
