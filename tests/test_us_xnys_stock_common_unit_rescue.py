from collections import defaultdict
from types import SimpleNamespace, MethodType

from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.resolver import BatchResolver


def _row(tv_id="NYSE:VOC", symbol="VOC", isin="US91829B1035", prefix="NYSE"):
    return TvRow(tv_id, prefix, symbol, symbol, "USD", "stock", ("common",), None, None, None, isin)


def _binding(r):
    return Binding(tv_id=r.tv_id, tv_symbol=r.symbol, tv_prefix=r.prefix, tv_currency=r.currency,
                   tv_type=r.tv_type, status="REJECTED", finnhub_type="Unit",
                   rejection_reason="FINNHUB_TYPE_MISMATCH:Unit")


def _resolver(identity, candidate, quote):
    class OF:
        def map_jobs(self, jobs):
            assert all(j.get("micCode") == "XNYS" for j in jobs)
            return [[identity] for _ in jobs]
    class Y:
        def search_exact_isin(self, isin): return [candidate]
        def quotes(self, symbols): return {quote.symbol: quote}
    ns=SimpleNamespace(openfigi=OF(), yahoo=Y(), stats=defaultdict(int), verified_ttl=86400)
    ns._verified=MethodType(BatchResolver._verified, ns)
    return ns


def test_xnys_stock_common_unit_exact_isin_rescues_audited_contract():
    r=_row()
    of=OpenFigiIdentity("BBG001CSBC03","C","BBG001V03446","VOC","VOC","Unit","Unit","US")
    c=YahooSearchCandidate("VOC","NYQ","EQUITY","VOC","VOC")
    q=YahooQuote("VOC","NYQ","NYSE","USD","EQUITY","us_market","VOC","VOC",1.0,0)
    resolver=_resolver(of,c,q)
    out=BatchResolver._us_xnys_stock_common_unit_rescue(resolver,[r],[_binding(r)])
    assert out[0].status == "VERIFIED"
    assert out[0].mapping_method == "US_XNYS_STOCK_COMMON_FINNHUB_UNIT_EXACT_ISIN"
    assert resolver.stats["us_xnys_stock_common_unit_rescue_matches"] == 1


def test_xnys_stock_common_unit_requires_share_class_figi():
    r=_row()
    of=OpenFigiIdentity("F","C",None,"VOC","VOC","Unit","Unit","US")
    c=YahooSearchCandidate("VOC","NYQ","EQUITY","VOC","VOC")
    q=YahooQuote("VOC","NYQ","NYSE","USD","EQUITY","us_market","VOC","VOC",1.0,0)
    resolver=_resolver(of,c,q)
    out=BatchResolver._us_xnys_stock_common_unit_rescue(resolver,[r],[_binding(r)])
    assert out[0].status == "REJECTED"


def test_xnys_stock_common_unit_does_not_admit_xnas_or_otc():
    for tv_id,prefix in [("NASDAQ:NBRGU","NASDAQ"),("OTC:UCASU","OTC")]:
        r=_row(tv_id=tv_id,symbol=tv_id.split(':')[1],prefix=prefix)
        of=OpenFigiIdentity("F","C","S",r.symbol,r.symbol,"Unit","Unit","US")
        c=YahooSearchCandidate(r.symbol,"NCM" if prefix=="NASDAQ" else "OQB","EQUITY",r.symbol,r.symbol)
        q=YahooQuote(r.symbol,c.exchange,"NasdaqCM" if prefix=="NASDAQ" else "OTC Markets OTCQB","USD","EQUITY","us_market",r.symbol,r.symbol,1.0,0)
        resolver=_resolver(of,c,q)
        out=BatchResolver._us_xnys_stock_common_unit_rescue(resolver,[r],[_binding(r)])
        assert out[0].status == "REJECTED"
