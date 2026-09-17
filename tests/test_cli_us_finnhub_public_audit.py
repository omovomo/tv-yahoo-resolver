from __future__ import annotations
import json
import sys, types
m=types.ModuleType("tradingview_screener")
class Column:
    def __init__(self,*a,**k): pass
class Query:
    def __init__(self,*a,**k): self.query={}
m.Column=Column; m.Query=Query; sys.modules.setdefault("tradingview_screener", m)
from collections import defaultdict
from types import SimpleNamespace
from tv_market_identity.cli import _write_us_finnhub_public_audit, parser
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate

def test_us_finnhub_public_audit_parser_and_evidence(tmp_path):
    out=tmp_path/'public.jsonl'
    args=parser().parse_args(['run','--us-finnhub-public-audit',str(out)])
    assert args.us_finnhub_public_audit == str(out)
    row=TvRow(tv_id='NASDAQ:TEST',prefix='NASDAQ',symbol='TEST',name='Test',currency='USD',tv_type='stock',type_specs=('common',),sector=None,market_cap=None,close=None,isin='US0000000001')
    binding=Binding(tv_id=row.tv_id,tv_symbol=row.symbol,tv_prefix=row.prefix,tv_currency=row.currency,tv_type=row.tv_type,status='REJECTED',yahoo_symbol='TEST',yahoo_exchange='NMS',yahoo_quote_type='EQUITY',yahoo_currency='USD',finnhub_type='PUBLIC',rejection_reason='FINNHUB_TYPE_MISMATCH:PUBLIC')
    ident=OpenFigiIdentity(figi='F1',composite_figi='C1',share_class_figi='S1',ticker='TEST',name='Test',security_type='Common Stock',security_type2='Common Stock',exch_code='US')
    class OF:
        def map_jobs(self,jobs): return [[ident] for _ in jobs]
    class Y:
        def search_exact_isin(self,isin): return [YahooSearchCandidate(symbol='TEST',exchange='NMS',quote_type='EQUITY',short_name='Test',long_name='Test')]
        def quotes(self,symbols): return {'TEST':YahooQuote(symbol='TEST',exchange='NMS',full_exchange_name='NasdaqGS',currency='USD',quote_type='EQUITY',market='us_market',short_name='Test',long_name='Test',price=1.0,delayed_by=0)}
    _write_us_finnhub_public_audit(out,[row],{row.tv_id:binding},SimpleNamespace(openfigi=OF(),yahoo=Y(),stats=defaultdict(int)))
    rec=json.loads(out.read_text().strip())
    assert rec['diagnostic_only'] is True
    assert rec['diagnostic_release'] == '0.4.39'
    assert rec['finnhub_type'] == 'PUBLIC'
    assert rec['source_mic'] == 'XNAS'
    assert rec['source_scoped_openfigi_status'] == 'UNIQUE_FIGI'
    assert rec['yahoo_strict_same_source_equity_candidate_count'] == 1
    assert rec['classification'] == 'SOURCE_SCOPED_AND_YAHOO_STRICT'
