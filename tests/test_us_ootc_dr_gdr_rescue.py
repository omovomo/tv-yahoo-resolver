from collections import defaultdict
from types import MethodType, SimpleNamespace
import pytest
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.resolver import BatchResolver

def row(prefix="OTC", tv_type="dr", isin="US4380908057", symbol="HNHPF", currency="USD"):
    return TvRow(f"{prefix}:{symbol}", prefix, symbol, symbol, currency, tv_type, ("",), None, None, None, isin)
def binding(r, reason="FINNHUB_TYPE_MISMATCH:GDR"):
    return Binding(r.tv_id,r.symbol,r.prefix,r.currency,r.tv_type,"REJECTED",finnhub_type="GDR",rejection_reason=reason)
def identity(figi="F1",share="SC1",st="GDR",st2="Depositary Receipt",ticker="HNHPF"):
    return OpenFigiIdentity(figi,"C1",share,ticker,"GDR",st,st2,"US")
def candidate(symbol="HNHPF",qt="EQUITY"):
    return YahooSearchCandidate(symbol,"PNK",qt,symbol,symbol)
def quote(symbol="HNHPF",exchange="PNK",currency="USD",qt="EQUITY"):
    return YahooQuote(symbol,exchange,"OTC Markets Pink",currency,qt,"us_market",symbol,symbol,1.0,0)
def resolver(ids=None,candidates=None,q=None):
    ids=[identity()] if ids is None else ids; candidates=[candidate()] if candidates is None else candidates; q=quote() if q is None else q
    class OF:
        def map_jobs(self,jobs):
            assert all(j.get("micCode")=="OOTC" for j in jobs); return [ids for _ in jobs]
    class Y:
        def search_exact_isin(self,isin): return candidates
        def quotes(self,symbols): return {q.symbol:q} if q else {}
    ns=SimpleNamespace(openfigi=OF(),yahoo=Y(),stats=defaultdict(int),verified_ttl=86400)
    ns._verified=MethodType(BatchResolver._verified,ns); return ns
def run(r=None,res=None,b=None):
    r=r or row(); res=res or resolver(); b=b or binding(r)
    return BatchResolver._us_ootc_dr_gdr_rescue(res,[r],[b]),res

def test_ootc_dr_gdr_exact_isin_rescues_strict_contract():
    out,res=run(); assert out[0].status=="VERIFIED"; assert out[0].mapping_method=="US_OOTC_DR_FINNHUB_GDR_EXACT_ISIN"; assert out[0].source_mic==out[0].target_mic=="OOTC"; assert res.stats["us_ootc_dr_gdr_rescue_matches"]==1
@pytest.mark.parametrize("r",[row(prefix="NYSE"),row(tv_type="stock"),row(isin=None)])
def test_gdr_requires_otc_dr_and_isin(r): assert run(r=r)[0][0].status=="REJECTED"
def test_gdr_requires_exact_rejection_reason():
    r=row(); assert run(r=r,b=binding(r,"FINNHUB_TYPE_MISMATCH:CDI"))[0][0].status=="REJECTED"
@pytest.mark.parametrize("ids",[[],[identity("F1"),identity("F2")],[identity(st="PUBLIC")],[identity(st2="Common Stock")],[identity(share=None)],[identity(ticker="OTHER")]])
def test_gdr_requires_unique_scoped_gdr_depositary_receipt_shareclass_exact_ticker(ids): assert run(res=resolver(ids=ids))[0][0].status=="REJECTED"
@pytest.mark.parametrize("candidates,q",[([],quote()),([candidate(),candidate("OTHER")],quote()),([candidate("OTHER")],quote("OTHER")),([candidate(qt="MUTUALFUND")],quote()),([candidate()],quote(exchange="NYQ")),([candidate()],quote(currency="EUR")),([candidate()],quote(currency=None)),([candidate()],quote(qt="MUTUALFUND"))])
def test_gdr_requires_unique_exact_yahoo_ootc_usd_equity(candidates,q): assert run(res=resolver(candidates=candidates,q=q))[0][0].status=="REJECTED"
def test_policy420_reuses_policy419_verified_cache():
    from tv_market_identity.resolver import CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
    assert "0.4.19-policy419" in CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
