from version_expectations import CURRENT_PACKAGE_VERSION
import json
from pathlib import Path
from tv_market_identity import cli
from tv_market_identity.models import Binding, TvRow, OpenFigiIdentity, YahooQuote, YahooSearchCandidate

class OF:
    def map_jobs(self, jobs):
        return [[OpenFigiIdentity('F1', None, 'SC1', 'ABC', 'ABC UNIT', 'Unit', 'Unit', 'US')] for _ in jobs]
class YH:
    def search_exact_isin(self, isin):
        return [YahooSearchCandidate('ABC', 'NYQ', 'EQUITY', None, None)]
    def quotes(self, symbols):
        return {'ABC': YahooQuote('ABC','NYQ','NYSE','USD','EQUITY','us_market',None,None,None,None)}
class R:
    openfigi=OF(); yahoo=YH()

def test_v0424_unit_audit_current_release_and_normalized_scoped_fields(tmp_path):
    row=TvRow('NYSE:ABC','NYSE','ABC','ABC UNIT','USD','stock',('common',),None,None,None,'US0000000001')
    b=Binding(row.tv_id,row.symbol,row.prefix,row.currency,row.tv_type,'REJECTED',finnhub_type='Unit',rejection_reason='FINNHUB_TYPE_MISMATCH:Unit')
    out=tmp_path/'unit.jsonl'
    cli._write_us_finnhub_unit_audit(out,[row],{row.tv_id:b},R())
    rec=json.loads(out.read_text().strip())
    assert rec['diagnostic_release']==CURRENT_PACKAGE_VERSION
    assert rec['source_scoped_openfigi_status']=='UNIQUE_FIGI'
    assert rec['source_scoped_share_class_figis']==['SC1']
    assert rec['classification']=='UNIQUE_SHARE_CLASS_AND_ONE_SAME_SOURCE_EQUITY_CANDIDATE'
