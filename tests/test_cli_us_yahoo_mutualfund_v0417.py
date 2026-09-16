from __future__ import annotations
import json, sys, types
from collections import defaultdict
from types import SimpleNamespace
m=types.ModuleType("tradingview_screener")
class Column:
    def __init__(self,*a,**k): pass
class Query:
    def __init__(self,*a,**k): self.query={}
m.Column=Column; m.Query=Query; sys.modules.setdefault("tradingview_screener",m)
from tv_market_identity.cli import _write_us_yahoo_mutualfund_audit
from tv_market_identity.models import Binding, TvRow

class OF:
    def __init__(self): self.jobs=[]
    def map_jobs(self,jobs): self.jobs.extend(jobs); return [[] for _ in jobs]
class Y:
    def __init__(self): self.searches=[]
    def search_exact_isin(self,isin): self.searches.append(isin); return []
    def quotes(self,symbols): return {}
    def chart_quotes(self,symbols): return {}

def test_v0417_mutualfund_audit_keeps_missing_isin_in_full_cohort(tmp_path):
    row=TvRow(tv_id="OTC:NOISIN",prefix="OTC",symbol="NOISIN",name="No Isin",currency="USD",tv_type="stock",type_specs=("common",),sector=None,market_cap=None,close=None,isin=None)
    b=Binding(tv_id=row.tv_id,tv_symbol=row.symbol,tv_prefix=row.prefix,tv_currency=row.currency,tv_type=row.tv_type,status="REJECTED",yahoo_symbol="NOISIN",yahoo_exchange="PNK",yahoo_quote_type="MUTUALFUND",yahoo_currency="USD",rejection_reason="YAHOO_TYPE_MISMATCH:MUTUALFUND")
    of,y=OF(),Y(); out=tmp_path/"mf.jsonl"
    _write_us_yahoo_mutualfund_audit(out,[row],{row.tv_id:b},SimpleNamespace(openfigi=of,yahoo=y,stats=defaultdict(int)))
    rec=json.loads(out.read_text().strip())
    assert rec["diagnostic_release"] == "0.4.17"
    assert rec["classification"] == "MISSING_TV_ISIN"
    assert rec["source_proof"] == "MISSING_TV_ISIN"
    assert of.jobs == [] and y.searches == []

def test_v0417_mutualfund_audit_emits_decomposition_fields(tmp_path):
    row=TvRow(tv_id="OTC:TEST",prefix="OTC",symbol="TEST",name="Test",currency="USD",tv_type="stock",type_specs=("common",),sector=None,market_cap=None,close=None,isin="US0000000001")
    b=Binding(tv_id=row.tv_id,tv_symbol=row.symbol,tv_prefix=row.prefix,tv_currency=row.currency,tv_type=row.tv_type,status="REJECTED",yahoo_symbol="TEST",yahoo_exchange="PNK",yahoo_quote_type="MUTUALFUND",yahoo_currency="USD",rejection_reason="YAHOO_TYPE_MISMATCH:MUTUALFUND")
    out=tmp_path/"mf.jsonl"; _write_us_yahoo_mutualfund_audit(out,[row],{row.tv_id:b},SimpleNamespace(openfigi=OF(),yahoo=Y(),stats=defaultdict(int)))
    rec=json.loads(out.read_text().strip())
    assert rec["tv_prefix"] == "OTC" and rec["taxonomy_key"] == "stock/common"
    assert "source_proof" in rec and "current_yahoo_chart" in rec
