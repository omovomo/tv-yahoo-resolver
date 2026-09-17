import json
from tv_market_identity import cli
from tv_market_identity.models import Binding, TvRow, OpenFigiIdentity, YahooQuote, YahooSearchCandidate

class Cache:
    def load_finnhub_universe(self):
        return [{'symbol':'ABC','mic':'OOTC','currency':'USD','type':'Unit'}]
class OF:
    def map_jobs(self,jobs):
        return [[OpenFigiIdentity('F1',None,'SC1','ABC','ABC UNIT','Unit','Unit','US')] for _ in jobs]
class YH:
    def search_exact_isin(self,isin): return [YahooSearchCandidate('ABC','PNK','EQUITY',None,None)]
    def quotes(self,symbols): return {'ABC':YahooQuote('ABC','PNK','OTC Markets','USD','EQUITY','us_market',None,None,None,None)}
class R: cache=Cache(); openfigi=OF(); yahoo=YH()

def test_v0425_unit_audit_recovers_otc_mic_for_cached_reject(tmp_path):
    r=TvRow('OTC:ABC','OTC','ABC','ABC UNIT','USD','stock',('common',),None,None,None,'US0000000001')
    b=Binding(r.tv_id,r.symbol,r.prefix,r.currency,r.tv_type,'REJECTED',finnhub_type='Unit',rejection_reason='FINNHUB_TYPE_MISMATCH:Unit')
    out=tmp_path/'a.jsonl'; cli._write_us_finnhub_unit_audit(out,[r],{r.tv_id:b},R())
    rec=json.loads(out.read_text())
    assert rec['diagnostic_release']=='0.4.29'
    assert rec['source_mic']=='OOTC'
    assert rec['source_mic_origin']=='FINNHUB_EXACT_SYMBOL_UNIQUE_MIC'
    assert rec['source_scoped_openfigi_status']=='UNIQUE_FIGI'
