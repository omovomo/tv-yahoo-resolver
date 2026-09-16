import json
from collections import defaultdict
from types import SimpleNamespace
from tv_market_identity.cli import _write_us_finnhub_residual_taxonomy_audit, parser
from tv_market_identity.models import TvRow, Binding, OpenFigiIdentity, YahooSearchCandidate, YahooQuote

TYPES=("Closed-End Fund","Ltd Part","CDI","Royalty Trst","Stapled Security","Preference","GDR","Common Stock","NVDR","SDR")

def row(sym, ft, isin):
    r=TvRow(tv_id=f"NYSE:{sym}",prefix="NYSE",symbol=sym,name=sym,currency="USD",tv_type="stock",type_specs=("common",),sector=None,market_cap=None,close=None,isin=isin)
    b=Binding(tv_id=r.tv_id,tv_symbol=r.symbol,tv_prefix=r.prefix,tv_currency=r.currency,tv_type=r.tv_type,status="REJECTED",yahoo_symbol=sym,yahoo_exchange="NYQ",yahoo_quote_type="EQUITY",yahoo_currency="USD",finnhub_type=ft,rejection_reason=f"FINNHUB_TYPE_MISMATCH:{ft}")
    return r,b

class Cache:
    def load_finnhub_universe(self): return []
class OF:
    def map_jobs(self,jobs):
        return [[OpenFigiIdentity(figi="F"+j["idValue"][-2:],composite_figi="C",share_class_figi="S",ticker="T",name="T",security_type="Common Stock",security_type2="Common Stock",exch_code="US")] for j in jobs]
class Y:
    def search_exact_isin(self,isin):
        n=int(isin[-2:]); return [YahooSearchCandidate(symbol=f"T{n}",exchange="NYQ",quote_type="EQUITY",short_name="T",long_name="T")]
    def quotes(self,symbols):
        return {s:YahooQuote(symbol=s,exchange="NYQ",full_exchange_name="NYSE",currency="USD",quote_type="EQUITY",market="us_market",short_name=s,long_name=s,price=1.0,delayed_by=0) for s in symbols}

def test_v0418_parser():
    a=parser().parse_args(["run","--us-finnhub-residual-taxonomy-audit","x.jsonl"])
    assert a.us_finnhub_residual_taxonomy_audit=="x.jsonl"

def test_v0418_full_type_set_and_release(tmp_path):
    rows=[]; bs={}
    for i,ft in enumerate(TYPES,1):
        r,b=row(f"T{i}",ft,f"US00000000{i:02d}"); rows.append(r); bs[r.tv_id]=b
    out=tmp_path/"r.jsonl"
    _write_us_finnhub_residual_taxonomy_audit(out,rows,bs,SimpleNamespace(cache=Cache(),openfigi=OF(),yahoo=Y(),stats=defaultdict(int)))
    recs=[json.loads(x) for x in out.read_text().splitlines()]
    assert len(recs)==10
    assert {x["finnhub_type"] for x in recs}==set(TYPES)
    assert {x["diagnostic_release"] for x in recs}=={"0.4.18"}

def test_v0418_keeps_missing_isin(tmp_path):
    r,b=row("MISS","GDR",None); out=tmp_path/"r.jsonl"
    _write_us_finnhub_residual_taxonomy_audit(out,[r],{r.tv_id:b},SimpleNamespace(cache=Cache(),openfigi=OF(),yahoo=Y(),stats=defaultdict(int)))
    rec=json.loads(out.read_text())
    assert rec["classification"]=="MISSING_TV_ISIN"
    assert rec["yahoo_exact_isin_candidate_count"]==0


def test_v0418_cohort_uses_rejection_reason_when_binding_finnhub_type_is_not_persisted(tmp_path):
    out=tmp_path/"residual-cached.jsonl"
    r=TvRow(tv_id="NYSE:CACHED",prefix="NYSE",symbol="CACHED",name="Cached",currency="USD",tv_type="stock",type_specs=("common",),sector=None,market_cap=None,close=None,isin="US0000000099")
    b=Binding(tv_id=r.tv_id,tv_symbol=r.symbol,tv_prefix=r.prefix,tv_currency=r.currency,tv_type=r.tv_type,status="REJECTED",finnhub_type=None,rejection_reason="FINNHUB_TYPE_MISMATCH:Royalty Trst")
    _write_us_finnhub_residual_taxonomy_audit(out,[r],{r.tv_id:b},SimpleNamespace(cache=Cache(),openfigi=OF(),yahoo=Y(),stats=defaultdict(int)))
    rec=json.loads(out.read_text().strip())
    assert rec["rejection_reason"] == "FINNHUB_TYPE_MISMATCH:Royalty Trst"
    assert rec["finnhub_type"] == "Royalty Trst"
    assert rec["diagnostic_release"] == "0.4.18"
