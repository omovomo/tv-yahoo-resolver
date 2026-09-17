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
    assert TV_PREFIX_TO_MIC["HKEX"] == "XHKG"
    assert MIC_TO_YAHOO_SUFFIX["XHKG"] == ".HK"
    assert MIC_TO_YAHOO_SUFFIX["AQSE"] == ".AQ"
    assert TV_PREFIX_TO_MIC["FWB"] == "XFRA"
    assert MIC_TO_YAHOO_SUFFIX["XFRA"] == ".F"
    assert TV_PREFIX_TO_MIC["DUS"] == "XDUS"
    assert MIC_TO_YAHOO_SUFFIX["XDUS"] == ".DU"
    assert TV_PREFIX_TO_MIC["HAM"] == "XHAM"
    assert MIC_TO_YAHOO_SUFFIX["XHAM"] == ".HM"
    assert TV_PREFIX_TO_MIC["SWB"] == "XSTU"
    assert MIC_TO_YAHOO_SUFFIX["XSTU"] == ".SG"
    assert TV_PREFIX_TO_MIC["MUN"] == "XMUN"
    assert MIC_TO_YAHOO_SUFFIX["XMUN"] == ".MU"
    assert TV_PREFIX_TO_MIC["HAN"] == "XHAN"
    assert MIC_TO_YAHOO_SUFFIX["XHAN"] == ".HA"
    assert TV_PREFIX_TO_MIC["GETTEX"] is None
    assert TV_PREFIX_TO_MIC["LSX"] is None
    assert TV_PREFIX_TO_MIC["LS"] is None
    assert yahoo_listing_symbol("SHEP", "AQSE") == "SHEP.AQ"
    assert yahoo_listing_symbol("QED.GB", "AQSE", "AQUIS") == "QED.AQ"
    assert yahoo_listing_symbol("FF24", "XFRA") == "FF24.F"


def test_reviewed_yahoo_venue_compatibility():
    aq = YahooQuote("SHEP.AQ", "AQSE", "Aquis AQSE", "GBp", "EQUITY", "gb_market", None, None, 470.0, 15)
    fra = YahooQuote("FF24.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market", None, None, 0.04, 15)
    dus = YahooQuote("75S.DU", "DUS", "Dusseldorf", "EUR", "EQUITY", "de_market", None, None, 1.0, 15)
    ham = YahooQuote("VTWR.HM", "HAM", "Hamburg", "EUR", "EQUITY", "de_market", None, None, 38.5, 15)
    stu = YahooQuote("SDF.SG", "STU", "Stuttgart", "EUR", "EQUITY", "de_market", None, None, 16.8, 15)
    mun = YahooQuote("SDF.MU", "MUN", "Munich", "EUR", "EQUITY", "de_market", None, None, 16.8, 15)
    han = YahooQuote("SDF.HA", "HAN", "Hanover", "EUR", "EQUITY", "de_market", None, None, 16.8, 15)
    assert yahoo_venue_compatible("AQSE", aq)
    assert yahoo_venue_compatible("XFRA", fra)
    assert yahoo_venue_compatible("XDUS", dus)
    assert yahoo_venue_compatible("XHAM", ham)
    assert yahoo_venue_compatible("XSTU", stu)
    assert yahoo_venue_compatible("XMUN", mun)
    assert yahoo_venue_compatible("XHAN", han)


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


class OFIsinBridge:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            isin = job.get("idValue")
            mic = job.get("micCode")
            if job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "HAML":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_HAML", composite_figi="BBG_BASF_HAML_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BASF11",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="HH",
                )])
            elif job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "XETR":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_XETR", composite_figi="BBG_BASF_XETR_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GY",
                )])
            else:
                out.append([])
        return out


class YHIsinBridge:
    batch_size = 75
    def quotes(self, symbols):
        if "BAS.DE" in symbols:
            return {"BAS.DE": YahooQuote(
                "BAS.DE", "GER", "XETRA", "EUR", "EQUITY", "de_market",
                "BASF SE", None, 45.0, 15,
            )}
        return {}


def test_lsx_isin_share_class_bridge_handles_wkn_style_symbol(tmp_path):
    db = CacheDB(tmp_path / "lsx-isin.sqlite")
    r = BatchResolver(db, None, OFIsinBridge(), YHIsinBridge())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "ISIN_SHARE_CLASS_BRIDGE"
    assert b.source_mic == "HAML"
    assert b.target_mic == "XETR"
    assert b.yahoo_symbol == "BAS.DE"
    assert b.share_class_figi == "BBG_BASF_SHARE"
    assert r.stats["openfigi_isin_bridge_jobs"] == 2
    assert r.stats["isin_bridge_share_class_matches"] == 1
    db.close()


def test_lsx_isin_bridge_fails_closed_without_tradingview_isin(tmp_path):
    db = CacheDB(tmp_path / "lsx-no-isin.sqlite")
    r = BatchResolver(db, None, OFNoMatch(), YHIsinBridge())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0,
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "TV_ISIN_UNKNOWN"
    db.close()


class OFIsinBridgeSourceMissingButUnscopedKnown:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            isin = job.get("idValue")
            mic = job.get("micCode")
            if job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "HAML":
                out.append([])
            elif job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "XETR":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_XETR", composite_figi="BBG_BASF_XETR_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GY",
                )])
            elif job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic is None and job.get("exchCode") is None:
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_OTHER", composite_figi="BBG_BASF_OTHER_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BASF",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GR",
                )])
            else:
                out.append([])
        return out


def test_lsx_tv_isin_target_bridge_when_openfigi_source_is_unindexed(tmp_path):
    db = CacheDB(tmp_path / "lsx-source-target-bridge.sqlite")
    r = BatchResolver(db, None, OFIsinBridgeSourceMissingButUnscopedKnown(), YHIsinBridge())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "TV_ISIN_TARGET_BRIDGE"
    assert b.source_mic == "HAML"
    assert b.target_mic == "XETR"
    assert b.source_venue_figi is None
    assert b.target_venue_figi == "BBG_BASF_XETR"
    assert b.yahoo_symbol == "BAS.DE"
    assert r.stats["bridge_rows_LSX"] == 1
    assert r.stats["bridge_source_no_match_LSX"] == 1
    assert r.stats["bridge_source_empty_LSX"] == 1
    assert r.stats["tv_isin_target_bridge_matches"] == 1
    assert r.stats["tv_isin_target_bridge_matches_LSX"] == 1
    # Accepted rows do not need the diagnostic unscoped probe.
    assert r.stats["openfigi_isin_bridge_unscoped_probe_jobs"] == 0
    db.close()


class OFIsinBridgeTargetMissingAndUnscopedUnknown:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            isin = job.get("idValue")
            mic = job.get("micCode")
            if job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "HAML":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_HAML", composite_figi="BBG_BASF_HAML_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BASF11",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="HH",
                )])
            else:
                out.append([])
        return out


def test_isin_bridge_diagnostics_target_empty_and_unscoped_unknown(tmp_path):
    db = CacheDB(tmp_path / "lsx-target-diag.sqlite")
    r = BatchResolver(db, None, OFIsinBridgeTargetMissingAndUnscopedUnknown(), YHIsinBridge())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_TARGET_NO_MATCH"
    assert r.stats["bridge_target_no_match_LSX"] == 1
    assert r.stats["bridge_target_empty_LSX"] == 1
    assert r.stats["openfigi_isin_bridge_unscoped_probe_jobs"] == 1
    assert r.stats["openfigi_isin_bridge_unscoped_unknown_LSX"] == 1
    db.close()


class OFGettexSourceMissingTargetPresent:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            isin = job.get("idValue")
            mic = job.get("micCode")
            if job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "XETR":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_XETR", composite_figi="BBG_BASF_XETR_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GY",
                )])
            elif job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic is None and job.get("exchCode") is None:
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_OTHER", composite_figi="BBG_BASF_OTHER_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GR",
                )])
            else:
                out.append([])
        return out


def test_gettex_does_not_guess_source_segment_when_both_source_mics_missing(tmp_path):
    db = CacheDB(tmp_path / "gettex-no-source-guess.sqlite")
    r = BatchResolver(db, None, OFGettexSourceMissingTargetPresent(), YHIsinBridge())
    row = TvRow(
        "GETTEX:BAS", "GETTEX", "BAS", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["GETTEX:BAS"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_SOURCE_NO_MATCH"
    assert r.stats["tv_isin_target_bridge_matches"] == 0
    assert r.stats["openfigi_isin_bridge_unscoped_probe_jobs"] == 1
    db.close()


class OFIsinTargetDuplicatesSameShare:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            isin = job.get("idValue")
            mic = job.get("micCode")
            if job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "HAML":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_HAML", composite_figi="BBG_BASF_HAML_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BASF11",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="HH",
                )])
            elif job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "XETR":
                out.append([
                    OpenFigiIdentity(
                        figi="BBG_BASF_XETR_1", composite_figi="BBG_BASF_XETR_C1",
                        share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GY",
                    ),
                    OpenFigiIdentity(
                        figi="BBG_BASF_XETR_2", composite_figi="BBG_BASF_XETR_C2",
                        share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GY",
                    ),
                ])
            else:
                out.append([])
        return out


def test_isin_bridge_collapses_duplicate_target_rows_with_same_share_and_ticker(tmp_path):
    db = CacheDB(tmp_path / "lsx-target-collapse.sqlite")
    r = BatchResolver(db, None, OFIsinTargetDuplicatesSameShare(), YHIsinBridge())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "ISIN_SHARE_CLASS_BRIDGE"
    assert b.target_venue_figi is None
    assert b.share_class_figi == "BBG_BASF_SHARE"
    assert r.stats["bridge_target_share_class_collapses"] == 1
    assert r.stats["bridge_target_share_class_collapses_LSX"] == 1
    db.close()


class OFIsinTargetDuplicatesDifferentTicker(OFIsinTargetDuplicatesSameShare):
    def map_jobs(self, jobs):
        out = super().map_jobs(jobs)
        for job, rows in zip(jobs, out):
            if job.get("micCode") == "XETR" and len(rows) == 2:
                rows[1] = OpenFigiIdentity(
                    figi="BBG_OTHER_XETR", composite_figi="BBG_OTHER_XETR_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="OTHER",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GY",
                )
        return out


def test_isin_bridge_does_not_collapse_target_rows_with_different_tickers(tmp_path):
    db = CacheDB(tmp_path / "lsx-target-ambiguous.sqlite")
    r = BatchResolver(db, None, OFIsinTargetDuplicatesDifferentTicker(), YHIsinBridge())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_TARGET_AMBIGUOUS:2"
    db.close()

class OFIsinBridgeTargetMissingUnscopedUniqueTickerNoShare:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            isin = job.get("idValue")
            mic = job.get("micCode")
            if job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "HAML":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_HAML", composite_figi="BBG_BASF_HAML_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BASF11",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="HH",
                )])
            elif job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic is None and job.get("exchCode") is None:
                out.append([
                    OpenFigiIdentity(
                        figi="BBG_BASF_OTHER1", composite_figi="BBG_BASF_OTHER_C1",
                        share_class_figi=None, ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GR",
                    ),
                    OpenFigiIdentity(
                        figi="BBG_BASF_OTHER2", composite_figi="BBG_BASF_OTHER_C2",
                        share_class_figi=None, ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GF",
                    ),
                ])
            else:
                out.append([])
        return out


def test_isin_bridge_unscoped_probe_reports_unique_ticker_without_share_class(tmp_path):
    db = CacheDB(tmp_path / "lsx-unscoped-ticker.sqlite")
    r = BatchResolver(db, None, OFIsinBridgeTargetMissingUnscopedUniqueTickerNoShare(), YHIsinBridge())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_TARGET_NO_MATCH"
    assert r.stats["openfigi_isin_bridge_unscoped_share_class_missing_LSX"] == 1
    assert r.stats["openfigi_isin_bridge_unscoped_unique_ticker_LSX"] == 1
    db.close()


class OFLsxXetraMicMissingWknPresent:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            isin = job.get("idValue")
            mic = job.get("micCode")
            if job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "HAML":
                out.append([])
            elif job.get("idType") == "ID_ISIN" and isin == "DE000BASF111" and mic == "XETR":
                out.append([])
            elif job.get("idType") == "ID_WERTPAPIER" and job.get("idValue") == "BASF11" and mic == "XETR":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_XETR", composite_figi="BBG_BASF_XETR_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GY",
                )])
            else:
                out.append([])
        return out


def test_lsx_wkn_to_xetra_fallback_removed_after_live_zero_match(tmp_path):
    db = CacheDB(tmp_path / "lsx-wkn-target-removed.sqlite")
    r = BatchResolver(db, None, OFLsxXetraMicMissingWknPresent(), YHIsinBridge())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_SOURCE_NO_MATCH"
    assert r.stats["openfigi_wkn_target_fallback_jobs"] == 0
    assert r.stats["openfigi_regional_target_probe_rows"] == 1
    assert r.stats["openfigi_regional_target_probe_jobs"] == 6
    db.close()


class OFLsWknTargetWithSource:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            mic = job.get("micCode")
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "JP3539250005" and mic == "LSSI":
                out.append([OpenFigiIdentity(
                    figi="BBG_THK_LSSI", composite_figi="BBG_THK_LSSI_C",
                    share_class_figi="BBG_THK_SHARE", ticker="887915",
                    name="THK CO LTD", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="LSSI",
                )])
            elif job.get("idType") == "ID_ISIN" and job.get("idValue") == "JP3539250005" and mic == "XETR":
                out.append([])
            elif job.get("idType") == "ID_WERTPAPIER" and job.get("idValue") == "887915" and mic == "XETR":
                out.append([OpenFigiIdentity(
                    figi="BBG_THK_XETR", composite_figi="BBG_THK_XETR_C",
                    share_class_figi="BBG_THK_SHARE", ticker="THK",
                    name="THK CO LTD", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GY",
                )])
            else:
                out.append([])
        return out


class YHThkXetra:
    batch_size = 75
    def quotes(self, symbols):
        if "THK.DE" in symbols:
            return {"THK.DE": YahooQuote(
                "THK.DE", "GER", "XETRA", "EUR", "EQUITY", "de_market",
                "THK Co., Ltd.", None, 20.0, 15,
            )}
        return {}


def test_ls_wkn_to_xetra_fallback_removed_even_when_source_exists(tmp_path):
    db = CacheDB(tmp_path / "ls-wkn-target-removed.sqlite")
    r = BatchResolver(db, None, OFLsWknTargetWithSource(), YHThkXetra())
    row = TvRow(
        "LS:887915", "LS", "887915", "THK Co., Ltd.", "EUR", "stock",
        ("common",), None, 4e9, 20.0, isin="JP3539250005",
    )
    b = r.resolve([row])["LS:887915"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_TARGET_NO_MATCH"
    assert r.stats["openfigi_wkn_target_fallback_jobs"] == 0
    assert r.stats["openfigi_regional_target_probe_rows"] == 1
    db.close()


class OFLsxTargetMissingNoWkn:
    batch_size = 100
    def map_jobs(self, jobs):
        out=[]
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "US0378331005" and job.get("micCode") == "HAML":
                out.append([])
            else:
                out.append([])
        return out


def test_lsx_non_wkn_symbol_still_gets_isin_regional_diagnostics(tmp_path):
    db = CacheDB(tmp_path / "lsx-non-wkn.sqlite")
    r = BatchResolver(db, None, OFLsxTargetMissingNoWkn(), YHIsinBridge())
    row = TvRow(
        "LSX:AAPL", "LSX", "AAPL", "Apple Inc.", "EUR", "stock",
        ("common",), None, 4e12, 200.0, isin="US0378331005",
    )
    b = r.resolve([row])["LSX:AAPL"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_SOURCE_NO_MATCH"
    assert r.stats["openfigi_wkn_target_fallback_jobs"] == 0
    assert r.stats["openfigi_regional_target_probe_jobs"] == 6
    db.close()


class OFGettexNoTargetButFakeWkn:
    batch_size = 100
    def map_jobs(self, jobs):
        out=[]
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "DE000BASF111" and job.get("micCode") == "MUNC":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_MUNC", composite_figi="BBG_BASF_MUNC_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BASF11",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GZ",
                )])
            else:
                out.append([])
        return out


def test_gettex_does_not_receive_wkn_target_shortcut(tmp_path):
    db = CacheDB(tmp_path / "gettex-no-wkn-shortcut.sqlite")
    r = BatchResolver(db, None, OFGettexNoTargetButFakeWkn(), YHIsinBridge())
    row = TvRow(
        "GETTEX:BASF11", "GETTEX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["GETTEX:BASF11"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_TARGET_NO_MATCH"
    assert r.stats["openfigi_wkn_target_fallback_jobs"] == 0
    db.close()


class OFLsxRegionalFrankfurtTarget:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "DE000BASF111" and job.get("micCode") == "XFRA":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_XFRA", composite_figi="BBG_BASF_XFRA_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GF",
                )])
            else:
                out.append([])
        return out


class YHLsxRegionalFrankfurtTarget:
    batch_size = 75
    def quotes(self, symbols):
        if "BAS.F" in symbols:
            return {"BAS.F": YahooQuote(
                "BAS.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "BASF SE", None, 45.0, 15,
            )}
        return {}


def test_regional_target_fallback_promotes_exact_isin_frankfurt_target(tmp_path):
    db = CacheDB(tmp_path / "lsx-regional-probe.sqlite")
    r = BatchResolver(db, None, OFLsxRegionalFrankfurtTarget(), YHLsxRegionalFrankfurtTarget())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "VERIFIED"
    assert b.rejection_reason is None
    assert b.source_mic == "HAML"
    assert b.target_mic == "XFRA"
    assert b.resolved_mic == "XFRA"
    assert b.yahoo_symbol == "BAS.F"
    assert b.mapping_method == "TV_ISIN_REGIONAL_TARGET_BRIDGE"
    assert r.stats["openfigi_regional_target_probe_matches_XFRA"] == 1
    assert r.stats["openfigi_regional_target_probe_unique_mic_rows_LSX"] == 1
    assert r.stats["yahoo_regional_target_probe_matches_XFRA"] == 1
    assert r.stats["yahoo_regional_target_probe_unique_mic_rows_LSX"] == 1
    assert r.stats["regional_target_bridge_matches_LSX"] == 1
    assert r.stats["tv_isin_regional_target_bridge_matches_LSX"] == 1
    db.close()


class OFLsxRegionalMultiSameSecurity:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "DE000BASF111":
                mic = job.get("micCode")
                if mic == "XFRA":
                    out.append([OpenFigiIdentity(
                        figi="BBG_BASF_XFRA", composite_figi="BBG_BASF_XFRA_C",
                        share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GF",
                    )])
                    continue
                if mic == "XMUN":
                    out.append([OpenFigiIdentity(
                        figi="BBG_BASF_XMUN", composite_figi="BBG_BASF_XMUN_C",
                        share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GM",
                    )])
                    continue
            out.append([])
        return out


class YHLsxRegionalMultiSameSecurity:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        if "BAS.F" in symbols:
            out["BAS.F"] = YahooQuote(
                "BAS.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "BASF SE", None, 45.0, 15,
            )
        if "BAS.MU" in symbols:
            out["BAS.MU"] = YahooQuote(
                "BAS.MU", "MUN", "Munich", "EUR", "EQUITY", "de_market",
                "BASF SE", None, 45.0, 15,
            )
        return out


def test_regional_target_multi_mic_same_security_uses_deterministic_priority(tmp_path):
    db = CacheDB(tmp_path / "lsx-regional-multi.sqlite")
    r = BatchResolver(db, None, OFLsxRegionalMultiSameSecurity(), YHLsxRegionalMultiSameSecurity())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "VERIFIED"
    assert b.target_mic == "XFRA"
    assert b.yahoo_symbol == "BAS.F"
    assert b.mapping_method == "TV_ISIN_REGIONAL_TARGET_BRIDGE"
    assert r.stats["yahoo_regional_target_probe_multi_mic_rows_LSX"] == 1
    assert r.stats["regional_target_bridge_multi_mic_matches_LSX"] == 1
    db.close()


class OFLsxRegionalConflictingShareClasses(OFLsxRegionalMultiSameSecurity):
    def map_jobs(self, jobs):
        out = super().map_jobs(jobs)
        for i, job in enumerate(jobs):
            if (job.get("idType") == "ID_ISIN" and job.get("idValue") == "DE000BASF111"
                    and job.get("micCode") == "XMUN" and out[i]):
                x = out[i][0]
                out[i] = [OpenFigiIdentity(
                    figi=x.figi, composite_figi=x.composite_figi,
                    share_class_figi="BBG_CONFLICTING_SHARE", ticker=x.ticker,
                    name=x.name, security_type=x.security_type,
                    security_type2=x.security_type2, exch_code=x.exch_code,
                )]
        return out


def test_regional_target_conflicting_share_classes_remains_fail_closed(tmp_path):
    db = CacheDB(tmp_path / "lsx-regional-conflict.sqlite")
    r = BatchResolver(db, None, OFLsxRegionalConflictingShareClasses(), YHLsxRegionalMultiSameSecurity())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["LSX:BASF11"]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_SOURCE_NO_MATCH"
    assert r.stats["regional_target_bridge_security_ambiguous_LSX"] == 1
    db.close()


class OFGettexRegionalShareClassMatch:
    batch_size = 100
    def map_jobs(self, jobs):
        out=[]
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "DE000BASF111":
                mic = job.get("micCode")
                if mic == "MUNC":
                    out.append([OpenFigiIdentity(
                        figi="BBG_BASF_MUNC", composite_figi="BBG_BASF_MUNC_C",
                        share_class_figi="BBG_BASF_SHARE", ticker="BASF11",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GZ",
                    )])
                    continue
                if mic == "XFRA":
                    out.append([OpenFigiIdentity(
                        figi="BBG_BASF_XFRA", composite_figi="BBG_BASF_XFRA_C",
                        share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GF",
                    )])
                    continue
            out.append([])
        return out


def test_gettex_regional_target_still_requires_source_share_class_proof(tmp_path):
    db = CacheDB(tmp_path / "gettex-regional-share.sqlite")
    r = BatchResolver(db, None, OFGettexRegionalShareClassMatch(), YHLsxRegionalFrankfurtTarget())
    row = TvRow(
        "GETTEX:BASF11", "GETTEX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])["GETTEX:BASF11"]
    assert b.status == "VERIFIED"
    assert b.source_mic == "MUNC"
    assert b.target_mic == "XFRA"
    assert b.mapping_method == "ISIN_REGIONAL_SHARE_CLASS_BRIDGE"
    assert b.source_venue_figi == "BBG_BASF_MUNC"
    assert b.target_venue_figi == "BBG_BASF_XFRA"
    assert r.stats["regional_share_class_bridge_matches_GETTEX"] == 1
    db.close()


def test_regional_target_binding_survives_warm_cache_refresh(tmp_path):
    db = CacheDB(tmp_path / "lsx-regional-warm.sqlite")
    of = OFLsxRegionalFrankfurtTarget()
    yh = YHLsxRegionalFrankfurtTarget()
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    cold = BatchResolver(db, None, of, yh).resolve([row])["LSX:BASF11"]
    assert cold.status == "VERIFIED"
    assert cold.mapping_method == "TV_ISIN_REGIONAL_TARGET_BRIDGE"
    warm_resolver = BatchResolver(db, None, of, yh)
    warm = warm_resolver.resolve([row])["LSX:BASF11"]
    assert warm.status == "VERIFIED"
    assert warm.cache_hit is True
    assert warm.mapping_method == "TV_ISIN_REGIONAL_TARGET_BRIDGE"
    assert warm.target_mic == "XFRA"
    assert warm.yahoo_symbol == "BAS.F"
    assert warm_resolver.stats["cache_hits"] == 1
    assert warm_resolver.stats["cache_misses"] == 0
    db.close()


class YHLsxRegionalFrankfurtMutualFund:
    batch_size = 75
    def quotes(self, symbols):
        if "BAS.F" in symbols:
            return {"BAS.F": YahooQuote(
                "BAS.F", "FRA", "Frankfurt", "EUR", "MUTUALFUND", "de_market",
                "BASF SE", None, 45.0, 15,
            )}
        return {}


class YHLsxRegionalFrankfurtEtf:
    batch_size = 75
    def quotes(self, symbols):
        if "BAS.F" in symbols:
            return {"BAS.F": YahooQuote(
                "BAS.F", "FRA", "Frankfurt", "EUR", "ETF", "de_market",
                "BASF SE", None, 45.0, 15,
            )}
        return {}


def test_german_regional_mutualfund_taxonomy_anomaly_is_bounded_and_admitted(tmp_path):
    db = CacheDB(tmp_path / "lsx-regional-mf-anomaly.sqlite")
    r = BatchResolver(db, None, OFLsxRegionalFrankfurtTarget(), YHLsxRegionalFrankfurtMutualFund())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.target_mic == "XFRA"
    assert b.yahoo_quote_type == "MUTUALFUND"
    assert r.stats["yahoo_germany_regional_fund_taxonomy_candidates"] == 1
    assert r.stats["yahoo_germany_regional_fund_taxonomy_matches"] == 1
    assert r.stats["yahoo_germany_regional_fund_taxonomy_matches_MUTUALFUND"] == 1
    db.close()


def test_german_regional_etf_taxonomy_anomaly_for_common_stock_is_admitted(tmp_path):
    db = CacheDB(tmp_path / "lsx-regional-etf-anomaly.sqlite")
    r = BatchResolver(db, None, OFLsxRegionalFrankfurtTarget(), YHLsxRegionalFrankfurtEtf())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.yahoo_quote_type == "ETF"
    assert r.stats["yahoo_germany_regional_fund_taxonomy_matches_ETF"] == 1
    db.close()


class OFSwbCommonStock:
    batch_size = 100
    def map_jobs(self, jobs):
        out=[]
        for job in jobs:
            if job.get("idValue") == "BAS" and job.get("micCode") == "XSTU":
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_XSTU", composite_figi="BBG_BASF_XSTU_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GS",
                )])
            else:
                out.append([])
        return out


def test_german_regional_taxonomy_anomaly_requires_explicit_currency(tmp_path):
    class YHMissingCurrency:
        batch_size = 75
        def quotes(self, symbols):
            if "BAS.SG" in symbols:
                return {"BAS.SG": YahooQuote(
                    "BAS.SG", "STU", "Stuttgart", None, "MUTUALFUND", "de_market",
                    "BASF SE", None, 45.0, 15,
                )}
            return {}

    db = CacheDB(tmp_path / "swb-regional-mf-no-currency.sqlite")
    r = BatchResolver(db, None, OFSwbCommonStock(), YHMissingCurrency())
    row = TvRow(
        "SWB:BAS", "SWB", "BAS", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "YAHOO_TYPE_MISMATCH:MUTUALFUND"
    assert r.stats["yahoo_germany_regional_fund_taxonomy_matches"] == 0
    db.close()


def test_german_regional_taxonomy_anomaly_survives_warm_cache(tmp_path):
    db = CacheDB(tmp_path / "lsx-regional-mf-warm.sqlite")
    of = OFLsxRegionalFrankfurtTarget()
    yh = YHLsxRegionalFrankfurtMutualFund()
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    cold = BatchResolver(db, None, of, yh).resolve([row])[row.tv_id]
    assert cold.status == "VERIFIED"
    warm_resolver = BatchResolver(db, None, of, yh)
    warm = warm_resolver.resolve([row])[row.tv_id]
    assert warm.status == "VERIFIED"
    assert warm.cache_hit is True
    assert warm.yahoo_quote_type == "MUTUALFUND"
    db.close()


class OFLsxXetraAndFrankfurtTargets:
    batch_size = 100
    def map_jobs(self, jobs):
        out=[]
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "DE000BASF111":
                mic = job.get("micCode")
                if mic == "HAML":
                    out.append([OpenFigiIdentity(
                        figi="BBG_BASF_HAML", composite_figi="BBG_BASF_HAML_C",
                        share_class_figi="BBG_BASF_SHARE", ticker="BASF11",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="HH",
                    )])
                    continue
                if mic == "XETR":
                    out.append([OpenFigiIdentity(
                        figi="BBG_BASF_XETR", composite_figi="BBG_BASF_XETR_C",
                        share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GY",
                    )])
                    continue
                if mic == "XFRA":
                    out.append([OpenFigiIdentity(
                        figi="BBG_BASF_XFRA", composite_figi="BBG_BASF_XFRA_C",
                        share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                        name="BASF SE", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GF",
                    )])
                    continue
            out.append([])
        return out


class YHXetraMissingFrankfurtPresent:
    batch_size = 75
    def quotes(self, symbols):
        out={}
        if "BAS.F" in symbols:
            out["BAS.F"] = YahooQuote(
                "BAS.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "BASF SE", None, 45.0, 15,
            )
        return out


def test_yahoo_failure_regional_probe_promotes_exact_share_class_target(tmp_path):
    db = CacheDB(tmp_path / "lsx-yahoo-failure-regional-probe.sqlite")
    r = BatchResolver(db, None, OFLsxXetraAndFrankfurtTargets(), YHXetraMissingFrankfurtPresent())
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_YAHOO_REGIONAL_TARGET_FALLBACK"
    assert b.source_mic == "HAML"
    assert b.target_mic == "XFRA"
    assert b.yahoo_symbol == "BAS.F"
    assert r.stats["yahoo_failure_regional_probe_rows"] == 1
    assert r.stats["yahoo_failure_regional_probe_matches"] == 1
    assert r.stats["yahoo_failure_regional_probe_matches_XFRA"] == 1
    assert r.stats["yahoo_failure_regional_probe_unique_mic_rows"] == 1
    assert r.stats["yahoo_failure_regional_fallback_matches"] == 1

    warm_resolver = BatchResolver(
        db, None, OFLsxXetraAndFrankfurtTargets(), YHXetraMissingFrankfurtPresent()
    )
    warm = warm_resolver.resolve([row])[row.tv_id]
    assert warm.status == "VERIFIED"
    assert warm.cache_hit is True
    assert warm.mapping_method == "GERMANY_YAHOO_REGIONAL_TARGET_FALLBACK"
    assert warm.target_mic == "XFRA"
    warm_resolver.refresh_cached_quotes({row.tv_id: warm})
    assert warm.status == "VERIFIED"
    assert warm.yahoo_symbol == "BAS.F"
    db.close()


class OFSwbIsinSameVenueFallback:
    batch_size = 100
    def map_jobs(self, jobs):
        out=[]
        for job in jobs:
            if (job.get("idType") == "ID_ISIN" and job.get("idValue") == "DE000BASF111"
                    and job.get("micCode") == "XSTU"):
                out.append([OpenFigiIdentity(
                    figi="BBG_BASF_XSTU", composite_figi="BBG_BASF_XSTU_C",
                    share_class_figi="BBG_BASF_SHARE", ticker="BAS",
                    name="BASF SE", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GS",
                )])
            else:
                out.append([])
        return out


class YHSwbMutualFund:
    batch_size = 75
    def quotes(self, symbols):
        if "BAS.SG" in symbols:
            return {"BAS.SG": YahooQuote(
                "BAS.SG", "STU", "Stuttgart", "EUR", "MUTUALFUND", "de_market",
                "BASF SE", None, 45.0, 15,
            )}
        return {}


def test_direct_isin_same_venue_fallback_enables_taxonomy_override(tmp_path):
    db = CacheDB(tmp_path / "swb-isin-same-venue-mf.sqlite")
    r = BatchResolver(db, None, OFSwbIsinSameVenueFallback(), YHSwbMutualFund())
    row = TvRow(
        "SWB:BAS", "SWB", "BAS", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "TV_ISIN_SAME_VENUE_FALLBACK"
    assert b.target_mic == "XSTU"
    assert b.yahoo_quote_type == "MUTUALFUND"
    assert r.stats["openfigi_direct_isin_fallback_jobs"] == 1
    assert r.stats["openfigi_direct_isin_fallback_matches"] == 1
    assert r.stats["target_provider_strict_fallback_jobs"] == 0
    assert r.stats["yahoo_germany_regional_fund_taxonomy_matches"] == 1
    db.close()


class YHSwbMissingCurrencyEquity:
    batch_size = 75
    def quotes(self, symbols):
        if "BAS.SG" in symbols:
            return {"BAS.SG": YahooQuote(
                "BAS.SG", "STU", "Stuttgart", None, "EQUITY", "de_market",
                "BASF SE", None, 45.0, 15,
            )}
        return {}


def test_direct_isin_same_venue_fallback_allows_missing_yahoo_currency(tmp_path):
    db = CacheDB(tmp_path / "swb-isin-same-venue-no-currency.sqlite")
    r = BatchResolver(db, None, OFSwbIsinSameVenueFallback(), YHSwbMissingCurrencyEquity())
    row = TvRow(
        "SWB:BAS", "SWB", "BAS", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "TV_ISIN_SAME_VENUE_FALLBACK"
    assert b.quote_status == "FRESH_CURRENCY_UNREPORTED"
    assert r.stats["target_provider_strict_fallback_jobs"] == 0
    db.close()


class OFTradegateExactIsinSourceFallback:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            id_type = job.get("idType")
            value = job.get("idValue")
            mic = job.get("micCode")
            if id_type == "ID_EXCH_SYMBOL" and value == "POJN" and mic == "XETR":
                out.append([OpenFigiIdentity(
                    figi="BBG_POJN_XETR", composite_figi="BBG_POJN_XETR_C",
                    share_class_figi="BBG_POJN_SHARE", ticker="POJN",
                    name="PROLOGIS INC", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GY",
                )])
            elif id_type == "ID_ISIN" and value == "US74340W1036" and mic == "XGAT":
                out.append([OpenFigiIdentity(
                    figi="BBG_POJN_XGAT", composite_figi="BBG_POJN_XGAT_C",
                    share_class_figi="BBG_POJN_SHARE", ticker="POJN",
                    name="PROLOGIS INC", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="TH",
                )])
            else:
                out.append([])
        return out


class YHTradegateExactIsinSourceFallback:
    batch_size = 75

    def quotes(self, symbols):
        if "POJN.DE" in symbols:
            return {"POJN.DE": YahooQuote(
                "POJN.DE", "GER", "XETRA", "EUR", "EQUITY", "de_market",
                "Prologis, Inc.", None, 116.0, 15,
            )}
        return {}


def test_tradegate_exact_isin_source_fallback_keeps_share_class_bridge(tmp_path):
    db = CacheDB(tmp_path / "tradegate-source-isin-fallback.sqlite")
    r = BatchResolver(
        db, None, OFTradegateExactIsinSourceFallback(),
        YHTradegateExactIsinSourceFallback(),
    )
    row = TvRow(
        "TRADEGATE:POJN", "TRADEGATE", "POJN", "Prologis, Inc.", "EUR",
        "stock", ("common",), None, 1e11, 116.0, isin="US74340W1036",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "ISIN_SOURCE_SHARE_CLASS_BRIDGE"
    assert b.source_mic == "XGAT"
    assert b.target_mic == "XETR"
    assert b.source_venue_figi == "BBG_POJN_XGAT"
    assert b.target_venue_figi == "BBG_POJN_XETR"
    assert b.share_class_figi == "BBG_POJN_SHARE"
    assert r.stats["bridge_source_no_match_TRADEGATE"] == 1
    assert r.stats["openfigi_bridge_source_isin_fallback_jobs"] == 2
    assert r.stats["openfigi_bridge_source_isin_fallback_matches"] == 1
    assert r.stats["bridge_source_isin_fallback_matches"] == 1
    db.close()


class OFSwbRegionalOneSidedFallback:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if (
                job.get("idType") == "ID_ISIN"
                and job.get("idValue") == "IE00BKVD2N49"
                and job.get("micCode") == "XDUS"
            ):
                out.append([OpenFigiIdentity(
                    figi="BBG_847_XDUS", composite_figi="BBG_847_XDUS_C",
                    share_class_figi="BBG_847_SHARE", ticker="847",
                    name="SEAGATE TECHNOLOGY HOLDINGS",
                    security_type="Common Stock", security_type2="Common Stock",
                    exch_code="GD",
                )])
            else:
                out.append([])
        return out


class YHSwbRegionalOneSidedFallback:
    batch_size = 75

    def quotes(self, symbols):
        out = {}
        if "847.SG" in symbols:
            out["847.SG"] = YahooQuote(
                "847.SG", "STU", "Stuttgart", "EUR", "MUTUALFUND", "de_market",
                "Seagate Technology Holdings PLC", None, 696.0, 15,
            )
        if "847.DU" in symbols:
            out["847.DU"] = YahooQuote(
                "847.DU", "DUS", "Dusseldorf", "EUR", "EQUITY", "de_market",
                "Seagate Technology Holdings PLC", None, 694.0, 15,
            )
        return out


def test_direct_german_strict_failure_can_use_exact_isin_regional_target(tmp_path):
    db = CacheDB(tmp_path / "swb-regional-one-sided.sqlite")
    r = BatchResolver(
        db, None, OFSwbRegionalOneSidedFallback(),
        YHSwbRegionalOneSidedFallback(),
    )
    row = TvRow(
        "SWB:847", "SWB", "847", "Seagate Technology Holdings PLC", "EUR",
        "stock", ("common",), None, 1e11, 696.0, isin="IE00BKVD2N49",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "TV_ISIN_GERMANY_REGIONAL_TARGET_FALLBACK"
    assert b.source_mic == "XSTU"
    assert b.target_mic == "XDUS"
    assert b.source_venue_figi is None
    assert b.target_venue_figi == "BBG_847_XDUS"
    assert b.yahoo_quote_type == "EQUITY"
    assert r.stats["target_provider_strict_fallback_jobs"] == 1
    assert r.stats["tv_isin_germany_regional_target_fallback_matches"] == 1
    assert r.stats["yahoo_failure_regional_fallback_matches"] == 1
    db.close()


class OFLsxRegionalShareMismatch:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") != "ID_ISIN" or job.get("idValue") != "DE000BASF111":
                out.append([])
                continue
            mic = job.get("micCode")
            if mic == "HAML":
                share = "BBG_BASF_SHARE"
                ticker = "BASF11"
            elif mic == "XETR":
                share = "BBG_BASF_SHARE"
                ticker = "BAS"
            elif mic == "XFRA":
                share = "BBG_OTHER_SHARE"
                ticker = "BAS"
            else:
                out.append([])
                continue
            out.append([OpenFigiIdentity(
                figi=f"BBG_BASF_{mic}", composite_figi=f"BBG_BASF_{mic}_C",
                share_class_figi=share, ticker=ticker,
                name="BASF SE", security_type="Common Stock",
                security_type2="Common Stock", exch_code="XX",
            )])
        return out


def test_yahoo_failure_regional_fallback_rejects_share_class_mismatch(tmp_path):
    db = CacheDB(tmp_path / "lsx-yahoo-failure-share-mismatch.sqlite")
    r = BatchResolver(
        db, None, OFLsxRegionalShareMismatch(),
        YHXetraMissingFrankfurtPresent(),
    )
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "YAHOO_NO_MATCH"
    assert r.stats["yahoo_failure_regional_probe_share_class_mismatch"] == 1
    assert r.stats["yahoo_failure_regional_fallback_matches"] == 0
    db.close()


class OFTradegateExactIsinSourceRegionalFallback:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            id_type = job.get("idType")
            value = job.get("idValue")
            mic = job.get("micCode")
            if id_type == "ID_ISIN" and value == "US74340W1036" and mic == "XGAT":
                out.append([OpenFigiIdentity(
                    figi="BBG_POJN_XGAT", composite_figi="BBG_POJN_XGAT_C",
                    share_class_figi="BBG_POJN_SHARE", ticker="POJN",
                    name="PROLOGIS INC", security_type="REIT",
                    security_type2="REIT", exch_code="TH",
                )])
            elif id_type == "ID_ISIN" and value == "US74340W1036" and mic == "XSTU":
                out.append([OpenFigiIdentity(
                    figi="BBG_POJN_XSTU", composite_figi="BBG_POJN_XSTU_C",
                    share_class_figi="BBG_POJN_SHARE", ticker="POJN",
                    name="PROLOGIS INC", security_type="REIT",
                    security_type2="REIT", exch_code="GS",
                )])
            else:
                out.append([])
        return out


class YHTradegateExactIsinSourceRegionalFallback:
    batch_size = 75

    def quotes(self, symbols):
        if "POJN.SG" in symbols:
            return {"POJN.SG": YahooQuote(
                "POJN.SG", "STU", "Stuttgart", "EUR", "EQUITY", "de_market",
                "Prologis, Inc.", None, 115.2, 15,
            )}
        return {}


def test_tradegate_exact_isin_source_fallback_can_feed_regional_target_bridge(tmp_path):
    db = CacheDB(tmp_path / "tradegate-source-isin-regional.sqlite")
    r = BatchResolver(
        db, None, OFTradegateExactIsinSourceRegionalFallback(),
        YHTradegateExactIsinSourceRegionalFallback(),
    )
    row = TvRow(
        "TRADEGATE:POJN", "TRADEGATE", "POJN", "Prologis, Inc.", "EUR",
        "stock", ("common",), None, 1e11, 115.2, isin="US74340W1036",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "ISIN_SOURCE_REGIONAL_SHARE_CLASS_BRIDGE"
    assert b.source_mic == "XGAT"
    assert b.target_mic == "XSTU"
    assert b.source_venue_figi == "BBG_POJN_XGAT"
    assert b.target_venue_figi == "BBG_POJN_XSTU"
    assert b.yahoo_quote_type == "EQUITY"
    assert r.stats["bridge_source_isin_fallback_matches"] == 1
    assert r.stats["regional_target_bridge_matches"] == 1
    db.close()


class YHXetraMutualFundFrankfurtEquity:
    batch_size = 75

    def quotes(self, symbols):
        out = {}
        if "BAS.DE" in symbols:
            out["BAS.DE"] = YahooQuote(
                "BAS.DE", "GER", "XETRA", "EUR", "MUTUALFUND", "de_market",
                "BASF SE", None, 45.0, 15,
            )
        if "BAS.F" in symbols:
            out["BAS.F"] = YahooQuote(
                "BAS.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "BASF SE", None, 45.0, 15,
            )
        return out


def test_yahoo_fund_type_failure_reroutes_to_ordinary_regional_equity(tmp_path):
    db = CacheDB(tmp_path / "lsx-yahoo-mf-to-regional-equity.sqlite")
    r = BatchResolver(
        db, None, OFLsxXetraAndFrankfurtTargets(),
        YHXetraMutualFundFrankfurtEquity(),
    )
    row = TvRow(
        "LSX:BASF11", "LSX", "BASF11", "BASF SE", "EUR", "stock",
        ("common",), None, 4e10, 45.0, isin="DE000BASF111",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_YAHOO_REGIONAL_TARGET_FALLBACK"
    assert b.target_mic == "XFRA"
    assert b.yahoo_symbol == "BAS.F"
    assert b.yahoo_quote_type == "EQUITY"
    assert r.stats["yahoo_failure_regional_fallback_matches"] == 1
    assert r.stats["yahoo_failure_regional_fallback_matches_reason_YAHOO_TYPE_MISMATCH_MUTUALFUND"] == 1
    db.close()


class OFGettexOneSidedRegionalTarget:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if (
                job.get("idType") == "ID_ISIN"
                and job.get("idValue") == "US1234567890"
                and job.get("micCode") == "XFRA"
            ):
                out.append([OpenFigiIdentity(
                    figi="BBG_GETTEX_XFRA", composite_figi="BBG_GETTEX_XFRA_C",
                    share_class_figi="BBG_GETTEX_SHARE", ticker="ABC",
                    name="ABC CORP", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GF",
                )])
            else:
                out.append([])
        return out


class YHRegionalRetryThenMatch:
    batch_size = 75

    def __init__(self):
        self.calls = 0

    def quotes(self, symbols):
        self.calls += 1
        if self.calls >= 2 and "ABC.F" in symbols:
            return {"ABC.F": YahooQuote(
                "ABC.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "ABC Corp", None, 42.0, 15,
            )}
        return {}


def test_gettex_exact_isin_can_use_one_sided_regional_target_with_retry(tmp_path):
    db = CacheDB(tmp_path / "gettex-one-sided-regional-retry.sqlite")
    yh = YHRegionalRetryThenMatch()
    r = BatchResolver(db, None, OFGettexOneSidedRegionalTarget(), yh)
    row = TvRow(
        "GETTEX:ABC", "GETTEX", "ABC", "ABC Corp", "EUR", "stock",
        ("common",), None, 1e9, 42.0, isin="US1234567890",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "TV_ISIN_GERMANY_REGIONAL_TARGET_BRIDGE"
    assert b.source_mic is None
    assert b.source_venue_code == "GETTEX"
    assert b.target_mic == "XFRA"
    assert b.target_venue_figi == "BBG_GETTEX_XFRA"
    assert b.share_class_figi == "BBG_GETTEX_SHARE"
    assert r.stats["yahoo_regional_target_retry_rows"] == 1
    assert r.stats["yahoo_regional_target_retry_matches"] == 1
    assert r.stats["tv_isin_germany_regional_target_bridge_matches_GETTEX"] == 1
    db.close()


class OFTradegateOneSidedRegionalTarget:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if (
                job.get("idType") == "ID_ISIN"
                and job.get("idValue") == "US0987654321"
                and job.get("micCode") == "XFRA"
            ):
                out.append([OpenFigiIdentity(
                    figi="BBG_TG_XFRA", composite_figi="BBG_TG_XFRA_C",
                    share_class_figi="BBG_TG_SHARE", ticker="TGX",
                    name="TGX CORP", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GF",
                )])
            else:
                out.append([])
        return out


class YHTradegateOneSidedRegionalTarget:
    batch_size = 75

    def quotes(self, symbols):
        if "TGX.F" in symbols:
            return {"TGX.F": YahooQuote(
                "TGX.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "TGX Corp", None, 50.0, 15,
            )}
        return {}


def test_tradegate_exact_isin_can_use_one_sided_regional_target(tmp_path):
    db = CacheDB(tmp_path / "tradegate-one-sided-regional.sqlite")
    r = BatchResolver(
        db, None, OFTradegateOneSidedRegionalTarget(),
        YHTradegateOneSidedRegionalTarget(),
    )
    row = TvRow(
        "TRADEGATE:TGX", "TRADEGATE", "TGX", "TGX Corp", "EUR", "stock",
        ("common",), None, 1e9, 50.0, isin="US0987654321",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "TV_ISIN_GERMANY_REGIONAL_TARGET_BRIDGE"
    assert b.source_mic is None
    assert b.source_venue_code == "TRADEGATE"
    assert b.target_mic == "XFRA"
    assert r.stats["tv_isin_germany_regional_target_bridge_matches_TRADEGATE"] == 1
    db.close()


class OFGettexConflictingRegionalTargets:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") != "ID_ISIN" or job.get("idValue") != "US1122334455":
                out.append([])
                continue
            mic = job.get("micCode")
            if mic == "XFRA":
                share = "BBG_SHARE_A"
                figi = "BBG_XFRA_A"
            elif mic == "XMUN":
                share = "BBG_SHARE_B"
                figi = "BBG_XMUN_B"
            else:
                out.append([])
                continue
            out.append([OpenFigiIdentity(
                figi=figi, composite_figi=f"{figi}_C", share_class_figi=share,
                ticker="AMB", name="AMB CORP", security_type="Common Stock",
                security_type2="Common Stock", exch_code="XX",
            )])
        return out


class YHGettexConflictingRegionalTargets:
    batch_size = 75

    def quotes(self, symbols):
        out = {}
        if "AMB.F" in symbols:
            out["AMB.F"] = YahooQuote(
                "AMB.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "AMB Corp", None, 10.0, 15,
            )
        if "AMB.MU" in symbols:
            out["AMB.MU"] = YahooQuote(
                "AMB.MU", "MUN", "Munich", "EUR", "EQUITY", "de_market",
                "AMB Corp", None, 10.0, 15,
            )
        return out


def test_gettex_one_sided_regional_target_stays_fail_closed_on_share_conflict(tmp_path):
    db = CacheDB(tmp_path / "gettex-one-sided-conflict.sqlite")
    r = BatchResolver(
        db, None, OFGettexConflictingRegionalTargets(),
        YHGettexConflictingRegionalTargets(),
    )
    row = TvRow(
        "GETTEX:AMB", "GETTEX", "AMB", "AMB Corp", "EUR", "stock",
        ("common",), None, 1e9, 10.0, isin="US1122334455",
    )
    b = r.resolve([row])[row.tv_id]
    assert b.status == "REJECTED"
    assert b.rejection_reason == "OPENFIGI_SOURCE_NO_MATCH"
    assert r.stats["regional_target_bridge_security_ambiguous_GETTEX"] == 1
    db.close()


class OFRegionalSecurityGrouping:
    batch_size = 100

    def __init__(self):
        self.calls = []

    def map_jobs(self, jobs):
        self.calls.append([dict(job) for job in jobs])
        out = []
        for job in jobs:
            id_type = job.get("idType")
            isin = job.get("idValue")
            mic = job.get("micCode")
            if id_type == "ID_ISIN" and isin == "US0000000001" and mic in {"MUND", "LSSI"}:
                out.append([OpenFigiIdentity(
                    figi=f"SRC-{mic}", composite_figi="COMP-SRC",
                    share_class_figi="SHARE-1", ticker="SRC",
                    name="SAME SECURITY", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GZ",
                )])
            elif id_type == "ID_ISIN" and isin == "US0000000001" and mic == "XFRA":
                out.append([OpenFigiIdentity(
                    figi="TGT-XFRA", composite_figi="COMP-TGT",
                    share_class_figi="SHARE-1", ticker="ABC",
                    name="SAME SECURITY", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GF",
                )])
            else:
                out.append([])
        return out


class YHRegionalSecurityGrouping:
    batch_size = 75

    def quotes(self, symbols):
        if "ABC.F" not in symbols:
            return {}
        return {"ABC.F": YahooQuote(
            "ABC.F", "FRA", "Frankfurt", "EUR", "EQUITY", "dr_market",
            "Same Security", None, 10.0, 15,
        )}


def test_regional_exact_isin_evidence_is_grouped_across_provider_rows(tmp_path):
    db = CacheDB(tmp_path / "regional-security-grouping.sqlite")
    of = OFRegionalSecurityGrouping()
    r = BatchResolver(db, None, of, YHRegionalSecurityGrouping())
    rows = [
        TvRow(
            "GETTEX:ABC", "GETTEX", "ABC", "Same Security", "EUR", "stock",
            ("common",), None, 1e9, 10.0, isin="US0000000001",
        ),
        TvRow(
            "LS:123456", "LS", "123456", "Same Security", "EUR", "stock",
            ("common",), None, 1e9, 10.0, isin="US0000000001",
        ),
    ]

    got = r.resolve(rows)
    assert got["GETTEX:ABC"].status == "VERIFIED"
    assert got["LS:123456"].status == "VERIFIED"
    assert got["GETTEX:ABC"].yahoo_symbol == "ABC.F"
    assert got["LS:123456"].yahoo_symbol == "ABC.F"

    germany_mics = {"XFRA", "XSTU", "XMUN", "XHAN", "XDUS", "XHAM"}
    regional_calls = [
        call for call in of.calls
        if call and {job.get("micCode") for job in call} == germany_mics
        and all(job.get("idValue") == "US0000000001" for job in call)
    ]
    assert len(regional_calls) == 1
    assert len(regional_calls[0]) == 6
    assert r.stats["openfigi_regional_target_probe_rows"] == 2
    assert r.stats["openfigi_regional_target_probe_security_groups"] == 1
    assert r.stats["openfigi_regional_target_probe_grouped_row_reuses"] == 1
    assert r.stats["openfigi_regional_target_probe_row_equivalent_jobs"] == 12
    assert r.stats["openfigi_regional_target_probe_jobs"] == 6
    assert r.stats["openfigi_regional_target_probe_jobs_saved_by_grouping"] == 6
    db.close()
