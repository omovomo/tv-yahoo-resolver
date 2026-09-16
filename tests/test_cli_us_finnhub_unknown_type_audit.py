from __future__ import annotations
import json, sys, types
m=types.ModuleType("tradingview_screener")
class Column:
    def __init__(self,*a,**k): pass
class Query:
    def __init__(self,*a,**k): self.query={}
m.Column=Column; m.Query=Query; sys.modules.setdefault("tradingview_screener",m)
from types import SimpleNamespace
from tv_market_identity.cli import _write_us_finnhub_unknown_type_audit, parser
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate

def test_unknown_type_audit_parser_and_evidence(tmp_path):
    out=tmp_path/'unknown.jsonl'
    args=parser().parse_args(['run','--us-finnhub-unknown-type-audit',str(out)])
    assert args.us_finnhub_unknown_type_audit == str(out)
    row=TvRow(tv_id='NASDAQ:TEST',prefix='NASDAQ',symbol='TEST',name='Test',currency='USD',tv_type='stock',type_specs=('common',),sector=None,market_cap=None,close=None,isin='US0000000001')
    binding=Binding(tv_id=row.tv_id,tv_symbol=row.symbol,tv_prefix=row.prefix,tv_currency=row.currency,tv_type=row.tv_type,status='REJECTED',finnhub_type=None,rejection_reason='FINNHUB_TYPE_MISMATCH:?')
    ident=OpenFigiIdentity(figi='F1',composite_figi='C1',share_class_figi='S1',ticker='TEST',name='Test',security_type='Common Stock',security_type2='Common Stock',exch_code='US')
    class Cache:
        def load_finnhub_universe(self): return [{'symbol':'TEST','mic':'XNAS','currency':'USD','type':None,'description':'Test'}]
    class OF:
        def map_jobs(self,jobs): return [[ident] for _ in jobs]
    class Y:
        def search_exact_isin(self,isin): return [YahooSearchCandidate(symbol='TEST',exchange='NMS',quote_type='EQUITY',short_name='Test',long_name='Test')]
        def quotes(self,symbols): return {'TEST':YahooQuote(symbol='TEST',exchange='NMS',full_exchange_name='NasdaqGS',currency='USD',quote_type='EQUITY',market='us_market',short_name='Test',long_name='Test',price=1.0,delayed_by=0)}
    _write_us_finnhub_unknown_type_audit(out,[row],{row.tv_id:binding},SimpleNamespace(cache=Cache(),openfigi=OF(),yahoo=Y()))
    rec=json.loads(out.read_text().strip())
    assert rec['diagnostic_only'] is True
    assert rec['diagnostic_release'] == '0.4.15'
    assert rec['rejection_reason'] == 'FINNHUB_TYPE_MISMATCH:?'
    assert rec['source_mic'] == 'XNAS'
    assert rec['finnhub_matching_symbol_rows'][0]['type'] is None
    assert rec['source_scoped_openfigi_status'] == 'UNIQUE_FIGI'
    assert rec['yahoo_strict_same_source_equity_candidate_count'] == 1

def test_unknown_type_audit_otc_uses_unique_finnhub_mic_for_source_binding(tmp_path):
    out=tmp_path/'unknown-otc.jsonl'
    row=TvRow(tv_id='OTC:UEPEP',prefix='OTC',symbol='UEPEP',name='OTC Preferred',currency='USD',tv_type='stock',type_specs=('preferred',),sector=None,market_cap=None,close=None,isin='US0000000002')
    binding=Binding(tv_id=row.tv_id,tv_symbol=row.symbol,tv_prefix=row.prefix,tv_currency=row.currency,tv_type=row.tv_type,status='REJECTED',finnhub_type=None,rejection_reason='FINNHUB_TYPE_MISMATCH:?')
    ident=OpenFigiIdentity(figi='F2',composite_figi='C2',share_class_figi='S2',ticker='UEPEP',name='OTC Preferred',security_type='Preference',security_type2='Preferred Stock',exch_code='US')
    class Cache:
        def load_finnhub_universe(self): return [{'symbol':'UEPEP','mic':'OOTC','currency':'USD','type':'','description':'OTC Preferred'}]
    class OF:
        def __init__(self): self.jobs=[]
        def map_jobs(self,jobs):
            self.jobs.extend(jobs)
            return [[ident] for _ in jobs]
    class Y:
        def search_exact_isin(self,isin): return [YahooSearchCandidate(symbol='UEPEP',exchange='PNK',quote_type='EQUITY',short_name='OTC Preferred',long_name='OTC Preferred')]
        def quotes(self,symbols): return {'UEPEP':YahooQuote(symbol='UEPEP',exchange='PNK',full_exchange_name='OTC Markets',currency='USD',quote_type='EQUITY',market='us_market',short_name='OTC Preferred',long_name='OTC Preferred',price=1.0,delayed_by=0)}
    of=OF()
    _write_us_finnhub_unknown_type_audit(out,[row],{row.tv_id:binding},SimpleNamespace(cache=Cache(),openfigi=of,yahoo=Y()))
    rec=json.loads(out.read_text().strip())
    assert rec['source_mic'] == 'OOTC'
    assert rec['source_mic_origin'] == 'FINNHUB_EXACT_SYMBOL_UNIQUE_MIC'
    assert {'idType':'ID_ISIN','idValue':row.isin,'micCode':'OOTC'} in of.jobs
    assert rec['source_scoped_openfigi_status'] == 'UNIQUE_FIGI'
    assert rec['yahoo_strict_same_source_equity_candidate_count'] == 1
    assert rec['classification'] == 'SOURCE_SCOPED_AND_YAHOO_STRICT'

def test_unknown_type_audit_keeps_missing_isin_in_full_cohort(tmp_path):
    out=tmp_path/'unknown-missing-isin.jsonl'
    row=TvRow(tv_id='OTC:NOISIN',prefix='OTC',symbol='NOISIN',name='No ISIN',currency='USD',tv_type='stock',type_specs=('common',),sector=None,market_cap=None,close=None,isin=None)
    binding=Binding(tv_id=row.tv_id,tv_symbol=row.symbol,tv_prefix=row.prefix,tv_currency=row.currency,tv_type=row.tv_type,status='REJECTED',finnhub_type=None,rejection_reason='FINNHUB_TYPE_MISMATCH:?')
    class Cache:
        def load_finnhub_universe(self): return [{'symbol':'NOISIN','mic':'OOTC','currency':'USD','type':'','description':'No ISIN'}]
    class OF:
        def map_jobs(self,jobs): raise AssertionError('OpenFIGI must not be called without ISIN')
    class Y:
        def search_exact_isin(self,isin): raise AssertionError('Yahoo ISIN search must not be called without ISIN')
        def quotes(self,symbols): return {}
    _write_us_finnhub_unknown_type_audit(out,[row],{row.tv_id:binding},SimpleNamespace(cache=Cache(),openfigi=OF(),yahoo=Y()))
    rec=json.loads(out.read_text().strip())
    assert rec['tv_id'] == 'OTC:NOISIN'
    assert rec['tv_isin'] is None
    assert rec['classification'] == 'MISSING_TV_ISIN'
    assert rec['source_mic'] == 'OOTC'
    assert rec['unscoped_openfigi'] == []
    assert rec['source_scoped_openfigi'] == []
    assert rec['yahoo_exact_isin_candidate_count'] == 0
