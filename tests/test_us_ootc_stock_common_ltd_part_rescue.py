from collections import defaultdict
from types import MethodType, SimpleNamespace
import pytest
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.resolver import BatchResolver

def row(prefix="OTC", tv_type="stock", specs=("common",), isin="US3152932097", symbol="FGPR", currency="USD"):
    return TvRow(f"{prefix}:{symbol}", prefix, symbol, symbol, currency, tv_type, specs, None, None, None, isin)
def binding(r, reason="FINNHUB_TYPE_MISMATCH:Ltd Part"):
    return Binding(r.tv_id, r.symbol, r.prefix, r.currency, r.tv_type, "REJECTED", finnhub_type="Ltd Part", rejection_reason=reason)
def identity(figi="F1", share="SC1", st="Ltd Part", st2="Partnership Shares", ticker="FGPR"):
    return OpenFigiIdentity(figi, "C1", share, ticker, "Equity", st, st2, "US")
def candidate(symbol="FGPR", qt="EQUITY"):
    return YahooSearchCandidate(symbol, "OID", qt, symbol, symbol)
def quote(symbol="FGPR", exchange="OID", currency="USD", qt="EQUITY"):
    return YahooQuote(symbol, exchange, "OTC Markets OTCID" if exchange == "OID" else "NYSE", currency, qt, "us_market", symbol, symbol, 1.0, 0)
def resolver(ids=None, candidates=None, q=None):
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
    return BatchResolver._us_ootc_stock_common_ltd_part_rescue(res,[r],[b]),res

def test_rescues_strict_audited_ootc_ltd_part_contract():
    out,res=run(); assert out[0].status=="VERIFIED"; assert out[0].mapping_method=="US_OOTC_STOCK_COMMON_FINNHUB_LTD_PART_EXACT_ISIN"; assert out[0].source_mic==out[0].target_mic=="OOTC"; assert res.stats["us_ootc_stock_common_ltd_part_rescue_matches"]==1
@pytest.mark.parametrize("r",[row(prefix="AMEX"),row(prefix="NYSE"),row(tv_type="fund"),row(specs=("preferred",)),row(isin=None)])
def test_requires_otc_stock_common_exact_isin(r):
    assert run(r=r)[0][0].status=="REJECTED"
def test_requires_exact_rejection_reason():
    r=row(); assert run(r=r,b=binding(r,"FINNHUB_TYPE_MISMATCH:Closed-End Fund"))[0][0].status=="REJECTED"
@pytest.mark.parametrize("ids",[[],[identity("F1"),identity("F2")],[identity(st="PUBLIC")],[identity(st2="Common Stock")],[identity(share=None)],[identity(ticker="OTHER")]])
def test_requires_unique_scoped_ltd_part_partnership_exact_ticker_shareclass(ids):
    assert run(res=resolver(ids=ids))[0][0].status=="REJECTED"
@pytest.mark.parametrize("candidates,q",[([],quote()),([candidate(),candidate("OTHER")],quote()),([candidate("OTHER")],quote("OTHER")),([candidate(qt="ETF")],quote()),([candidate()],quote(exchange="NYQ")),([candidate()],quote(currency="EUR")),([candidate()],quote(currency=None)),([candidate()],quote(qt="ETF"))])
def test_requires_unique_exact_yahoo_ootc_usd_equity(candidates,q):
    assert run(res=resolver(candidates=candidates,q=q))[0][0].status=="REJECTED"
def test_policy423_reuses_policy422_verified_cache():
    from tv_market_identity.resolver import CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
    assert "0.4.22-policy422" in CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
