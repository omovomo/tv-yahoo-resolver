from collections import defaultdict
from types import MethodType, SimpleNamespace
import pytest

from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.resolver import BatchResolver


def row(tv_type="stock", specs=("common",), prefix="OTC", isin="US0000000001", symbol="UCASU", currency="USD"):
    return TvRow(f"{prefix}:{symbol}", prefix, symbol, symbol, currency, tv_type, specs, None, None, None, isin)


def binding(r, reason="FINNHUB_TYPE_MISMATCH:Unit"):
    return Binding(r.tv_id, r.symbol, r.prefix, r.currency, r.tv_type, "REJECTED", finnhub_type="Unit", rejection_reason=reason)


def identity(figi="F1", share="SC1", st="Unit", st2="Unit", ticker="UCASU"):
    return OpenFigiIdentity(figi, "C1", share, ticker, "Equity", st, st2, "US")


def candidate(symbol="UCASU", exchange="OQB", qt="EQUITY"):
    return YahooSearchCandidate(symbol, exchange, qt, symbol, symbol)


def quote(symbol="UCASU", exchange="OQB", currency="USD", qt="EQUITY"):
    names={"OQB":"OTC Markets OTCQB","PNK":"OTC Markets Pink Sheet","OID":"OTC Markets OTCID","NYQ":"NYSE"}
    return YahooQuote(symbol, exchange, names.get(exchange, exchange), currency, qt, "us_market", symbol, symbol, 1.0, 0)


def resolver(ids=None, candidates=None, quotes=None):
    ids=[identity()] if ids is None else ids
    candidates=[candidate()] if candidates is None else candidates
    quotes=[quote()] if quotes is None else quotes
    class OF:
        def map_jobs(self,jobs):
            assert all(j.get("micCode")=="OOTC" for j in jobs)
            return [ids for _ in jobs]
    class Y:
        def search_exact_isin(self,isin): return candidates
        def quotes(self,symbols): return {q.symbol:q for q in quotes if q.symbol in symbols}
    ns=SimpleNamespace(openfigi=OF(), yahoo=Y(), stats=defaultdict(int), verified_ttl=86400)
    ns._verified=MethodType(BatchResolver._verified,ns)
    ns._us_ootc_unit_exact_isin_rescue=MethodType(BatchResolver._us_ootc_unit_exact_isin_rescue,ns)
    return ns


def run(method, r, res=None, b=None):
    res=res or resolver(ids=[identity(ticker=r.symbol)], candidates=[candidate(r.symbol)], quotes=[quote(r.symbol)])
    return method(res,[r],[b or binding(r)]),res


def test_stock_common_positive():
    r=row(); out,res=run(BatchResolver._us_ootc_stock_common_unit_rescue,r)
    assert out[0].status=="VERIFIED"
    assert out[0].mapping_method=="US_OOTC_STOCK_COMMON_FINNHUB_UNIT_EXACT_ISIN"
    assert res.stats["us_ootc_stock_common_unit_rescue_matches"]==1


def test_fund_unit_positive():
    r=row(tv_type="fund",specs=("unit",),symbol="JWSUF")
    out,res=run(BatchResolver._us_ootc_fund_unit_unit_rescue,r)
    assert out[0].status=="VERIFIED"
    assert out[0].mapping_method=="US_OOTC_FUND_UNIT_FINNHUB_UNIT_EXACT_ISIN"
    assert res.stats["us_ootc_fund_unit_unit_rescue_matches"]==1


@pytest.mark.parametrize("r",[
    row(prefix="NYSE"), row(prefix="AMEX"), row(isin=None),
    row(tv_type="fund",specs=("unit",)), row(specs=("preferred",)),
])
def test_stock_gate_wrong_venue_taxonomy_or_missing_isin(r):
    assert run(BatchResolver._us_ootc_stock_common_unit_rescue,r)[0][0].status=="REJECTED"


@pytest.mark.parametrize("r",[
    row(tv_type="fund",specs=("unit",),prefix="NYSE"),
    row(tv_type="fund",specs=("unit",),isin=None),
    row(tv_type="stock",specs=("common",)),
    row(tv_type="fund",specs=("common",)),
])
def test_fund_gate_wrong_venue_taxonomy_or_missing_isin(r):
    assert run(BatchResolver._us_ootc_fund_unit_unit_rescue,r)[0][0].status=="REJECTED"


@pytest.mark.parametrize("ids",[
    [], [identity("F1"),identity("F2")], [identity(st="PUBLIC")], [identity(st2="Common Stock")],
    [identity(share=None)], [identity(ticker="OTHER")],
])
def test_requires_unique_scoped_unit_identity_shareclass_exact_ticker(ids):
    r=row(); assert run(BatchResolver._us_ootc_stock_common_unit_rescue,r,resolver(ids=ids))[0][0].status=="REJECTED"


def test_requires_exact_unit_rejection_reason():
    r=row(); out,_=run(BatchResolver._us_ootc_stock_common_unit_rescue,r,b=binding(r,"FINNHUB_TYPE_MISMATCH:Ltd Part")); assert out[0].status=="REJECTED"


@pytest.mark.parametrize("candidates,quotes",[
    ([],[]),
    ([candidate("OTHER")],[quote("OTHER")]),
    ([candidate(qt="ETF")],[quote()]),
    ([candidate()],[quote(exchange="NYQ")]),
    ([candidate()],[quote(currency="EUR")]),
    ([candidate()],[quote(currency=None)]),
    ([candidate()],[quote(qt="ETF")]),
])
def test_yahoo_contract_fail_closed(candidates,quotes):
    r=row(); assert run(BatchResolver._us_ootc_stock_common_unit_rescue,r,resolver(candidates=candidates,quotes=quotes))[0][0].status=="REJECTED"


def test_multiple_qualifying_yahoo_candidates_rejected():
    # Two qualifying records with the exact symbol are still ambiguous even if Yahoo quote collapses by symbol.
    r=row(); cs=[candidate(),candidate(exchange="PNK")]
    out,_=run(BatchResolver._us_ootc_stock_common_unit_rescue,r,resolver(candidates=cs,quotes=[quote()])); assert out[0].status=="REJECTED"


def test_nonqualifying_extra_yahoo_candidate_does_not_create_false_ambiguity():
    r=row(); cs=[candidate(),candidate("OTHER",exchange="NYQ")]
    out,_=run(BatchResolver._us_ootc_stock_common_unit_rescue,r,resolver(candidates=cs,quotes=[quote(),quote("OTHER",exchange="NYQ")]))
    assert out[0].status=="VERIFIED"


def test_policy426_reuses_policy423_verified_cache():
    from tv_market_identity.resolver import CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
    assert "0.4.23-policy423" in CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
