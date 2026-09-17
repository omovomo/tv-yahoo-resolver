from collections import defaultdict
from types import MethodType, SimpleNamespace
import pytest
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.resolver import BatchResolver


def row(prefix="OTC", tv_type="stock", specs=("common",), isin="US0000000001", symbol="TCGLF", currency="USD"):
    return TvRow(f"{prefix}:{symbol}", prefix, symbol, symbol, currency, tv_type, specs, None, None, None, isin)

def binding(r, reason="FINNHUB_TYPE_MISMATCH:?"):
    return Binding(r.tv_id,r.symbol,r.prefix,r.currency,r.tv_type,"REJECTED",finnhub_type=None,rejection_reason=reason)

def identity(figi="F1", share="SC1", st="Common Stock", st2="Common Stock", ticker="TCGLF"):
    return OpenFigiIdentity(figi,"C1",share,ticker,"Equity",st,st2,"US")

def candidate(symbol="TCGLF", exchange="PNK", qt="EQUITY"):
    return YahooSearchCandidate(symbol,exchange,qt,symbol,symbol)

def quote(symbol="TCGLF", exchange="PNK", currency="USD", qt="EQUITY"):
    names={"PNK":"OTC Markets Pink Sheet","OID":"OTC Markets OTCID","OQB":"OTC Markets OTCQB","NYQ":"NYSE"}
    return YahooQuote(symbol,exchange,names.get(exchange,exchange),currency,qt,"us_market",symbol,symbol,1.0,0)

def resolver(ids=None,candidates=None,quotes=None):
    ids=[identity()] if ids is None else ids; candidates=[candidate()] if candidates is None else candidates; quotes=[quote()] if quotes is None else quotes
    class OF:
        def map_jobs(self,jobs):
            assert all(j.get("micCode")=="OOTC" for j in jobs); return [ids for _ in jobs]
    class Y:
        def search_exact_isin(self,isin): return candidates
        def quotes(self,symbols): return {q.symbol:q for q in quotes if q.symbol in symbols}
    ns=SimpleNamespace(openfigi=OF(),yahoo=Y(),stats=defaultdict(int),verified_ttl=86400)
    ns._verified=MethodType(BatchResolver._verified,ns); return ns

def run(r=None,res=None,b=None):
    r=r or row(); res=res or resolver(ids=[identity(ticker=r.symbol)],candidates=[candidate(r.symbol)],quotes=[quote(r.symbol)])
    return BatchResolver._us_ootc_stock_common_unknown_type_rescue(res,[r],[b or binding(r)]),res

def test_positive_contract():
    out,res=run(); assert out[0].status=="VERIFIED"; assert out[0].mapping_method=="US_OOTC_STOCK_COMMON_FINNHUB_UNKNOWN_TYPE_EXACT_ISIN"; assert res.stats["us_ootc_stock_common_unknown_type_rescue_matches"]==1

@pytest.mark.parametrize("r",[row(prefix="NYSE"),row(tv_type="fund"),row(specs=("preferred",)),row(isin=None)])
def test_gate_fail_closed(r): assert run(r=r)[0][0].status=="REJECTED"

def test_exact_reason_required():
    r=row(); assert run(r=r,b=binding(r,"FINNHUB_TYPE_MISMATCH:PUBLIC"))[0][0].status=="REJECTED"

@pytest.mark.parametrize("ids",[[],[identity("F1"),identity("F2")],[identity(st="PUBLIC")],[identity(st2="Preferred Stock")],[identity(share=None)],[identity(ticker="OTHER")]])
def test_openfigi_contract(ids): assert run(res=resolver(ids=ids))[0][0].status=="REJECTED"

@pytest.mark.parametrize("candidates,quotes",[([],[]),([candidate("OTHER")],[quote("OTHER")]),([candidate(qt="ETF")],[quote()]),([candidate()],[quote(exchange="NYQ")]),([candidate()],[quote(currency="EUR")]),([candidate()],[quote(currency=None)]),([candidate()],[quote(qt="ETF")])])
def test_yahoo_contract(candidates,quotes): assert run(res=resolver(candidates=candidates,quotes=quotes))[0][0].status=="REJECTED"

def test_multiple_qualifying_candidates_rejected():
    assert run(res=resolver(candidates=[candidate(),candidate(exchange="OID")],quotes=[quote()]))[0][0].status=="REJECTED"

def test_nonqualifying_extra_candidate_ok():
    out,_=run(res=resolver(candidates=[candidate(),candidate("OTHER",exchange="NYQ")],quotes=[quote(),quote("OTHER",exchange="NYQ")]))
    assert out[0].status=="VERIFIED"

def test_policy429_reuses_policy426_verified_cache():
    from tv_market_identity.resolver import CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
    assert "0.4.26-policy426" in CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
