from __future__ import annotations
from version_expectations import CURRENT_RESOLVER_VERSION
import json, sys, types
m=types.ModuleType('tradingview_screener')
class Column:
    def __init__(self,*a,**k): pass
class Query:
    def __init__(self,*a,**k): self.query={}
m.Column=Column; m.Query=Query; sys.modules.setdefault('tradingview_screener',m)
from types import SimpleNamespace
from tv_market_identity.cli import _write_us_finnhub_unknown_type_preferred_dr_audit, parser
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.policy import RESOLVER_VERSION

def test_v430_flag_and_policy_unchanged():
    a=parser().parse_args(['run','--us-finnhub-unknown-type-preferred-dr-audit','x.jsonl'])
    assert a.us_finnhub_unknown_type_preferred_dr_audit=='x.jsonl'
    assert RESOLVER_VERSION==CURRENT_RESOLVER_VERSION

def test_v430_focuses_preferred_and_dr(tmp_path):
    rows=[
      TvRow(tv_id='OTC:PREFP',prefix='OTC',symbol='PREFP',name='P',currency='USD',tv_type='stock',type_specs=('preferred',),sector=None,market_cap=None,close=None,isin='US0000000001'),
      TvRow(tv_id='OTC:DRY',prefix='OTC',symbol='DRY',name='D',currency='USD',tv_type='dr',type_specs=(),sector=None,market_cap=None,close=None,isin='US0000000002'),
      TvRow(tv_id='OTC:COMMON',prefix='OTC',symbol='COMMON',name='C',currency='USD',tv_type='stock',type_specs=('common',),sector=None,market_cap=None,close=None,isin='US0000000003'),
    ]
    bs={r.tv_id:Binding(tv_id=r.tv_id,tv_symbol=r.symbol,tv_prefix=r.prefix,tv_currency=r.currency,tv_type=r.tv_type,status='REJECTED',finnhub_type=None,rejection_reason='FINNHUB_TYPE_MISMATCH:?') for r in rows}
    ids={r.symbol:OpenFigiIdentity(figi='F'+r.symbol,composite_figi='C'+r.symbol,share_class_figi='S'+r.symbol,ticker=r.symbol,name=r.name,security_type='PUBLIC',security_type2='Preferred Stock',exch_code='US') for r in rows}
    class Cache:
      def load_finnhub_universe(self): return [{'symbol':r.symbol,'mic':'OOTC','currency':'USD','type':''} for r in rows]
    class OF:
      def map_jobs(self,jobs):
        return [[ids[rows[i].symbol]] for i,_ in enumerate(jobs)] if len(jobs)==len(rows) else [[next(iter(ids.values()))] for _ in jobs]
    class Y:
      def search_exact_isin(self,isin):
        r=next(r for r in rows if r.isin==isin); return [YahooSearchCandidate(symbol=r.symbol,exchange='PNK',quote_type='EQUITY',short_name=r.name,long_name=r.name)]
      def quotes(self,symbols): return {s:YahooQuote(symbol=s,exchange='PNK',full_exchange_name='OTC Markets',currency='USD',quote_type='EQUITY',market='us_market',short_name=s,long_name=s,price=1,delayed_by=0) for s in symbols}
    out=tmp_path/'a.jsonl'
    _write_us_finnhub_unknown_type_preferred_dr_audit(out,rows,bs,SimpleNamespace(cache=Cache(),openfigi=OF(),yahoo=Y()))
    recs=[json.loads(x) for x in out.read_text().splitlines()]
    assert {x['tv_id'] for x in recs}=={'OTC:PREFP','OTC:DRY'}
    assert {x['diagnostic_release'] for x in recs}=={'0.4.30'}
    assert {x['v430_focus'] for x in recs}=={'OOTC_STOCK_PREFERRED','OOTC_DR'}
