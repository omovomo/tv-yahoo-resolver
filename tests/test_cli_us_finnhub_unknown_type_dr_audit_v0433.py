from __future__ import annotations
import json, sys, types
m=types.ModuleType("tradingview_screener")
class Column:
    def __init__(self,*a,**k): pass
class Query:
    def __init__(self,*a,**k): self.query={}
m.Column=Column; m.Query=Query; sys.modules.setdefault("tradingview_screener",m)
from types import SimpleNamespace
from tv_market_identity.cli import _write_us_finnhub_unknown_type_dr_audit, parser
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.policy import RESOLVER_VERSION

def test_v433_flag_and_policy_unchanged():
    a=parser().parse_args(["run","--us-finnhub-unknown-type-dr-audit","x.jsonl"])
    assert a.us_finnhub_unknown_type_dr_audit=="x.jsonl"
    assert RESOLVER_VERSION=="0.4.32-policy432"

def test_v433_focuses_only_ootc_dr(tmp_path):
    rows=[TvRow(tv_id="OTC:DRY",prefix="OTC",symbol="DRY",name="D",currency="USD",tv_type="dr",type_specs=(),sector=None,market_cap=None,close=None,isin="US0000000002"), TvRow(tv_id="OTC:P",prefix="OTC",symbol="P",name="P",currency="USD",tv_type="stock",type_specs=("preferred",),sector=None,market_cap=None,close=None,isin="US0000000001")]
    bs={r.tv_id:Binding(tv_id=r.tv_id,tv_symbol=r.symbol,tv_prefix=r.prefix,tv_currency=r.currency,tv_type=r.tv_type,status="REJECTED",finnhub_type=None,rejection_reason="FINNHUB_TYPE_MISMATCH:?") for r in rows}
    class Cache:
      def load_finnhub_universe(self): return [{"symbol":r.symbol,"mic":"OOTC","currency":"USD","type":""} for r in rows]
    class OF:
      def map_jobs(self,jobs): return [[OpenFigiIdentity(figi="F",composite_figi="C",share_class_figi=None,ticker="X",name="D",security_type="PUBLIC",security_type2="Preferred Stock",exch_code="US")] for _ in jobs]
    class Y:
      def search_exact_isin(self,isin):
        r=next(r for r in rows if r.isin==isin); return [YahooSearchCandidate(symbol=r.symbol,exchange="PNK",quote_type="EQUITY",short_name=r.name,long_name=r.name)]
      def quotes(self,symbols): return {s:YahooQuote(symbol=s,exchange="PNK",full_exchange_name="OTC Markets",currency="USD",quote_type="EQUITY",market="us_market",short_name=s,long_name=s,price=1,delayed_by=0) for s in symbols}
    out=tmp_path/"a.jsonl"
    _write_us_finnhub_unknown_type_dr_audit(out,rows,bs,SimpleNamespace(cache=Cache(),openfigi=OF(),yahoo=Y()))
    recs=[json.loads(x) for x in out.read_text().splitlines()]
    assert [x["tv_id"] for x in recs]==["OTC:DRY"]
    assert recs[0]["diagnostic_release"]=="0.4.33"
    assert recs[0]["v433_public_preferred_scoped_unique"] is True
