from tv_market_identity.cache import CacheDB
from tv_market_identity.models import OpenFigiIdentity, TvRow, YahooQuote
from tv_market_identity.policy import (
    MIC_TO_YAHOO_SUFFIX,
    TV_PREFIX_TO_MIC,
    yahoo_listing_symbol,
    yahoo_venue_compatible,
)
from tv_market_identity.resolver import BatchResolver


def test_reviewed_venue_mappings_and_suffixes():
    assert TV_PREFIX_TO_MIC["AQUIS"] == "AQSE"
    assert MIC_TO_YAHOO_SUFFIX["AQSE"] == ".AQ"
    assert TV_PREFIX_TO_MIC["FWB"] == "XFRA"
    assert MIC_TO_YAHOO_SUFFIX["XFRA"] == ".F"
    assert TV_PREFIX_TO_MIC["DUS"] == "XDUS"
    assert MIC_TO_YAHOO_SUFFIX["XDUS"] == ".DU"
    assert TV_PREFIX_TO_MIC["HAM"] == "XHAM"
    assert MIC_TO_YAHOO_SUFFIX["XHAM"] == ".HM"
    assert yahoo_listing_symbol("SHEP", "AQSE") == "SHEP.AQ"
    assert yahoo_listing_symbol("QED.GB", "AQSE", "AQUIS") == "QED.AQ"
    assert yahoo_listing_symbol("FF24", "XFRA") == "FF24.F"


def test_reviewed_yahoo_venue_compatibility():
    aq = YahooQuote("SHEP.AQ", "AQSE", "Aquis AQSE", "GBp", "EQUITY", "gb_market", None, None, 470.0, 15)
    fra = YahooQuote("FF24.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market", None, None, 0.04, 15)
    dus = YahooQuote("75S.DU", "DUS", "Dusseldorf", "EUR", "EQUITY", "de_market", None, None, 1.0, 15)
    ham = YahooQuote("VTWR.HM", "HAM", "Hamburg", "EUR", "EQUITY", "de_market", None, None, 38.5, 15)
    assert yahoo_venue_compatible("AQSE", aq)
    assert yahoo_venue_compatible("XFRA", fra)
    assert yahoo_venue_compatible("XDUS", dus)
    assert yahoo_venue_compatible("XHAM", ham)


class OFAquis:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idValue") == "SHEP" and job.get("micCode") == "AQSE":
                out.append([OpenFigiIdentity(
                    figi="BBG_SHEP", composite_figi="BBG_SHEP_C", share_class_figi="BBG_SHEP_S",
                    ticker="SHEP", name="SHEPHERD NEAME LTD", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="AQ",
                )])
            else:
                out.append([])
        return out


class YHAquis:
    batch_size = 75
    def quotes(self, symbols):
        if "SHEP.AQ" in symbols:
            return {"SHEP.AQ": YahooQuote(
                "SHEP.AQ", "AQSE", "Aquis AQSE", "GBp", "EQUITY", "gb_market",
                "Shepherd Neame Limited", None, 470.0, 15,
            )}
        return {}


def test_aquis_direct_listing(tmp_path):
    db = CacheDB(tmp_path / "aquis.sqlite")
    r = BatchResolver(db, None, OFAquis(), YHAquis())
    row = TvRow("AQUIS:SHEP", "AQUIS", "SHEP", "SHEP", "GBX", "stock", ("common",), None, 1.0, 470.0)
    b = r.resolve([row])["AQUIS:SHEP"]
    assert b.status == "VERIFIED"
    assert b.resolved_mic == "AQSE"
    assert b.yahoo_symbol == "SHEP.AQ"
    db.close()


class OFNoMatch:
    batch_size = 100
    def map_jobs(self, jobs):
        return [[] for _ in jobs]


class YHXetraFallback:
    batch_size = 75
    def quotes(self, symbols):
        if "HABA.DE" in symbols:
            return {"HABA.DE": YahooQuote(
                "HABA.DE", "GER", "XETRA", "EUR", "EQUITY", "de_market",
                "Hamborner REIT AG", None, 4.2, 15,
            )}
        return {}


def test_xetra_target_provider_strict_fallback(tmp_path):
    db = CacheDB(tmp_path / "xetra-fallback.sqlite")
    r = BatchResolver(db, None, OFNoMatch(), YHXetraFallback())
    row = TvRow("XETR:HABA", "XETR", "HABA", "Hamborner REIT AG", "EUR", "stock", ("common",), None, 1.0, 4.2)
    b = r.resolve([row])["XETR:HABA"]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "TARGET_PROVIDER_STRICT_FALLBACK"
    assert b.resolved_mic == "XETR"
    assert b.yahoo_symbol == "HABA.DE"
    assert b.share_class_figi is None
    db.close()
