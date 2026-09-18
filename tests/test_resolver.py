import pytest
from tv_market_identity.cache import CacheDB
from tv_market_identity.models import Binding, TvRow, YahooQuote
from tv_market_identity.resolver import BatchResolver


class FH:
    def us_symbols(self):
        return [
            {"symbol":"BRK.B","displaySymbol":"BRK.B","description":"BERKSHIRE HATHAWAY INC-CL B","currency":"USD","type":"Common Stock","mic":"XNYS","figi":"BBG000DWG505","shareClassFIGI":"BBG001S90346"},
            {"symbol":"SPY","displaySymbol":"SPY","description":"SPDR S&P 500 ETF TRUST-US","currency":"USD","type":"ETP","mic":"ARCX","figi":"BBG000BDTBL9","shareClassFIGI":"BBG001S72SM3"},
        ]


class OF:
    batch_size = 100
    def map_jobs(self, jobs):
        return []


class YH:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        if "BRK-B" in symbols:
            out["BRK-B"] = YahooQuote("BRK-B", "NYQ", "NYSE", "USD", "EQUITY", "us_market", "BERKSHIRE HATHAWAY INC-CL B", None, 500.0, 0)
        if "SPY" in symbols:
            out["SPY"] = YahooQuote("SPY", "PCX", "NYSE Arca", "USD", "ETF", "us_market", "SPDR S&P 500 ETF TRUST", None, 600.0, 0)
        return out


def test_us_batch_resolver(tmp_path):
    db = CacheDB(tmp_path / "x.sqlite")
    r = BatchResolver(db, FH(), OF(), YH())
    rows = [
        TvRow("NYSE:BRK.B", "NYSE", "BRK.B", None, "USD", "stock", ("common",), "Finance", 1e12, 500.0),
        TvRow("AMEX:SPY", "AMEX", "SPY", None, "USD", "fund", ("etf",), None, None, 600.0),
    ]
    got = r.resolve(rows)
    assert got["NYSE:BRK.B"].status == "VERIFIED"
    assert got["NYSE:BRK.B"].yahoo_symbol == "BRK-B"
    assert got["AMEX:SPY"].resolved_mic == "ARCX"
    db.close()


class FHDiscovery:
    def us_symbols(self):
        return [
            {"symbol":"DIDIY","displaySymbol":"DIDIY","description":"DIDI GLOBAL INC ADR","currency":"USD","type":"ADR","mic":"OOTC","figi":"BBG_COMP_DIDI","shareClassFIGI":"BBG_SHARE_DIDI"},
            {"symbol":"CBOE","displaySymbol":"CBOE","description":"CBOE GLOBAL MARKETS INC","currency":"USD","type":"Common Stock","mic":"BATS","figi":"BBG000QH56C1","shareClassFIGI":"BBG_SHARE_CBOE"},
            {"symbol":"BA-PRA","displaySymbol":"BA-PRA","description":"BOEING CO 6% SERIES A","currency":"USD","type":"Preferred Stock","mic":"XNYS","figi":"BBG_COMP_BAPRA","shareClassFIGI":"BBG_SHARE_BAPRA"},
            {"symbol":"ORCL-PD","displaySymbol":"ORCL-PD","description":"ORACLE CORP PREFERRED D","currency":"USD","type":"Preferred Stock","mic":"XNYS","figi":"BBG_COMP_ORCLPD","shareClassFIGI":"BBG_SHARE_ORCLPD"},
        ]


class YHDiscovery:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        if "DIDIY" in symbols:
            out["DIDIY"] = YahooQuote("DIDIY", "PNK", "OTC Markets OTCPK", "USD", "EQUITY", "us_market", "DIDI GLOBAL INC", None, 3.9, 15)
        if "CBOE" in symbols:
            out["CBOE"] = YahooQuote("CBOE", "BTS", "Cboe US", "USD", "EQUITY", "us_market", "CBOE GLOBAL MARKETS", None, 280.0, 0)
        if "BA-PA" in symbols:
            out["BA-PA"] = YahooQuote("BA-PA", "NYQ", "NYSE", "USD", "EQUITY", "us_market", "BOEING CO", None, 60.0, 0)
        if "ORCL-PD" in symbols:
            out["ORCL-PD"] = YahooQuote("ORCL-PD", "NYQ", "NYSE", "USD", "EQUITY", "us_market", "ORACLE CORP", None, 48.0, 0)
        return out


def test_otc_cboe_and_preferred_discovery(tmp_path):
    db = CacheDB(tmp_path / "disc.sqlite")
    r = BatchResolver(db, FHDiscovery(), OF(), YHDiscovery())
    rows = [
        TvRow("OTC:DIDIY", "OTC", "DIDIY", None, "USD", "dr", ("",), None, None, 3.9),
        TvRow("CBOE:CBOE", "CBOE", "CBOE", None, "USD", "stock", ("common",), "Finance", None, 280.0),
        TvRow("NYSE:BA/PA", "NYSE", "BA/PA", None, "USD", "stock", ("preferred",), None, None, 60.0),
        TvRow("NYSE:ORCL/PD", "NYSE", "ORCL/PD", None, "USD", "stock", ("preferred",), None, None, 48.0),
    ]
    got = r.resolve(rows)
    assert got["OTC:DIDIY"].status == "VERIFIED"
    assert got["OTC:DIDIY"].resolved_mic == "OOTC"
    assert got["CBOE:CBOE"].status == "VERIFIED"
    assert got["CBOE:CBOE"].resolved_mic == "BATS"
    assert got["NYSE:BA/PA"].status == "VERIFIED"
    assert got["NYSE:BA/PA"].yahoo_symbol == "BA-PA"
    assert got["NYSE:ORCL/PD"].status == "VERIFIED"
    assert got["NYSE:ORCL/PD"].yahoo_symbol == "ORCL-PD"
    db.close()


class OFGermanyPreferred:
    batch_size = 100
    def map_jobs(self, jobs):
        out = []
        from tv_market_identity.models import OpenFigiIdentity
        for job in jobs:
            if job["idValue"] == "VOW3" and job["micCode"] == "XETR" and job["securityType2"] == "Preference":
                out.append([OpenFigiIdentity(
                    figi="BBG_VOW3_XETR", composite_figi="BBG000BFCPY7",
                    share_class_figi="BBG001S6MP58", ticker="VOW3",
                    name="VOLKSWAGEN AG-PREF", security_type="Preference",
                    security_type2="Preference", exch_code="GR",
                )])
            else:
                out.append([])
        return out


class YHGermanyPreferred:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        if "VOW3.DE" in symbols:
            out["VOW3.DE"] = YahooQuote("VOW3.DE", "GER", "XETRA", "EUR", "EQUITY", "de_market", "VOLKSWAGEN AG", None, 90.0, 15)
        return out


def test_non_us_xetra_preferred_vow3(tmp_path):
    db = CacheDB(tmp_path / "de.sqlite")
    r = BatchResolver(db, None, OFGermanyPreferred(), YHGermanyPreferred())
    row = TvRow("XETR:VOW3", "XETR", "VOW3", "Volkswagen AG", "EUR", "stock", ("preferred",), "Consumer Durables", 1e11, 90.0)
    got = r.resolve([row])
    assert got["XETR:VOW3"].status == "VERIFIED"
    assert got["XETR:VOW3"].yahoo_symbol == "VOW3.DE"
    assert got["XETR:VOW3"].share_class_figi == "BBG001S6MP58"
    db.close()

class OFTradegateBridge:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            mic = job["micCode"]
            sym = job["idValue"]
            if sym == "DTE" and mic == "XGAT":
                out.append([OpenFigiIdentity(
                    figi="BBG000TL3QB8", composite_figi="BBG000TL3Q37",
                    share_class_figi="BBG001S5T4S5", ticker="DTE",
                    name="DEUTSCHE TELEKOM AG-REG", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="TH",
                )])
            elif sym == "DTE" and mic == "XETR":
                out.append([OpenFigiIdentity(
                    figi="BBG000HJTMS9", composite_figi="BBG000HJTKL0",
                    share_class_figi="BBG001S5T4S5", ticker="DTE",
                    name="DEUTSCHE TELEKOM AG-REG", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GY",
                )])
            else:
                out.append([])
        return out


class YHTradegateBridge:
    batch_size = 75
    def quotes(self, symbols):
        if "DTE.DE" in symbols:
            return {
                "DTE.DE": YahooQuote(
                    "DTE.DE", "GER", "XETRA", "EUR", "EQUITY", "de_market",
                    "DEUTSCHE TELEKOM AG", None, 29.08, 15,
                )
            }
        return {}


def test_tradegate_to_xetra_share_class_bridge(tmp_path):
    db = CacheDB(tmp_path / "tradegate.sqlite")
    r = BatchResolver(db, None, OFTradegateBridge(), YHTradegateBridge())
    row = TvRow(
        "TRADEGATE:DTE", "TRADEGATE", "DTE", "Deutsche Telekom AG", "EUR",
        "stock", ("common",), "Communications", 1e11, 29.08,
    )
    got = r.resolve([row])["TRADEGATE:DTE"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "DTE.DE"
    assert got.source_mic == "XGAT"
    assert got.target_mic == "XETR"
    assert got.resolved_mic == "XETR"
    assert got.mapping_method == "SHARE_CLASS_BRIDGE"
    assert got.share_class_figi == "BBG001S5T4S5"
    assert got.source_venue_figi == "BBG000TL3QB8"
    assert got.target_venue_figi == "BBG000HJTMS9"
    db.close()


class OFLondon:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            sym = job["idValue"]
            if sym == "INF" and job.get("micCode") == "XLON" and job.get("currency") == "GBp":
                out.append([OpenFigiIdentity(
                    figi="BBG_INF_XLON", composite_figi="BBG_INF_COMP",
                    share_class_figi="BBG_INF_SHARE", ticker="INF",
                    name="INFORMA PLC", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="LN",
                )])
            elif sym == "0Q0Y" and job.get("exchCode") == "LI" and job.get("currency") == "EUR":
                out.append([OpenFigiIdentity(
                    figi="BBG_AEGON_LI", composite_figi="BBG_AEGON_LI_COMP",
                    share_class_figi="BBG_AEGON_SHARE", ticker="0Q0Y",
                    name="AEGON LTD", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="LI",
                )])
            elif sym == "0Q0Y" and job.get("micCode") == "XLON" and job.get("currency") == "EUR":
                out.append([OpenFigiIdentity(
                    figi="BBG_AEGON_XLON", composite_figi="BBG_AEGON_LN_COMP",
                    share_class_figi="BBG_AEGON_SHARE", ticker="0Q0Y",
                    name="AEGON LTD", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="LN",
                )])
            elif sym == "SDIC" and job.get("micCode") == "XLON" and job.get("currency") == "USD":
                out.append([OpenFigiIdentity(
                    figi="BBG_SDIC_XLON", composite_figi="BBG_SDIC_COMP",
                    share_class_figi="BBG_SDIC_SHARE", ticker="SDIC",
                    name="SDIC POWER HOLDINGS CO LTD", security_type="Depositary Receipt",
                    security_type2="Depositary Receipt", exch_code="LN",
                )])
            else:
                out.append([])
        return out


class YHLondon:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        if "INF.L" in symbols:
            out["INF.L"] = YahooQuote(
                "INF.L", "LSE", "London Stock Exchange", "GBp", "EQUITY",
                "gb_market", "INFORMA PLC", None, 897.0, 15,
            )
        if "0Q0Y.L" in symbols:
            out["0Q0Y.L"] = YahooQuote(
                "0Q0Y.L", "LSE", "London Stock Exchange", "EUR", "EQUITY",
                "gb_market", "AEGON LTD", None, 7.9, 15,
            )
        if "SDIC.IL" in symbols:
            out["SDIC.IL"] = YahooQuote(
                "SDIC.IL", "IOB", "International Order Book", "USD", "EQUITY",
                "gb_market", "SDIC POWER HOLDINGS CO LTD", None, 12.0, 15,
            )
        return out


def test_lse_gbx_uses_gbp_for_openfigi_but_preserves_pence_quote_unit(tmp_path):
    db = CacheDB(tmp_path / "uk.sqlite")
    r = BatchResolver(db, None, OFLondon(), YHLondon())
    row = TvRow(
        "LSE:INF", "LSE", "INF", "Informa plc", "GBX",
        "stock", ("common",), "Commercial Services", 1e10, 897.0,
    )
    got = r.resolve([row])["LSE:INF"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "INF.L"
    assert got.tv_currency == "GBX"
    assert got.yahoo_currency == "GBp"
    assert got.yahoo_price == 897.0
    assert got.resolved_mic == "XLON"
    db.close()




def test_lsin_depositary_receipt_uses_iob_suffix(tmp_path):
    db = CacheDB(tmp_path / "lsin-adr.sqlite")
    r = BatchResolver(db, None, OFLondon(), YHLondon())
    row = TvRow(
        "LSIN:SDIC", "LSIN", "SDIC", "SDIC Power Holdings Co Ltd", "USD",
        "dr", ("",), "Utilities", 1e10, 12.0,
    )
    got = r.resolve([row])["LSIN:SDIC"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "SDIC.IL"
    assert got.resolved_mic == "XLON"
    assert got.mapping_method == "SAME_VENUE"
    assert got.yahoo_exchange == "IOB"
    db.close()

def test_lsin_maps_directly_to_xlon_namespace(tmp_path):
    db = CacheDB(tmp_path / "lsin.sqlite")
    r = BatchResolver(db, None, OFLondon(), YHLondon())
    row = TvRow(
        "LSIN:0Q0Y", "LSIN", "0Q0Y", "Aegon Ltd", "EUR",
        "stock", ("common",), "Finance", 1e10, 7.9,
    )
    got = r.resolve([row])["LSIN:0Q0Y"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "0Q0Y.L"
    assert got.source_mic == "XLON"
    assert got.source_venue_code is None
    assert got.target_mic == "XLON"
    assert got.resolved_mic == "XLON"
    assert got.mapping_method == "SAME_VENUE"
    assert got.share_class_figi == "BBG_AEGON_SHARE"
    assert got.source_venue_figi == "BBG_AEGON_XLON"
    assert got.target_venue_figi == "BBG_AEGON_XLON"
    assert r.stats["yahoo_lsin_alt_fallback_matches"] == 1
    db.close()

class OFLondonAmbiguous:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idValue") == "INF" and job.get("micCode") == "XLON":
                out.append([
                    OpenFigiIdentity(
                        figi="BBG_INF_A", composite_figi="BBG_INF_COMP",
                        share_class_figi="BBG_INF_SHARE", ticker="INF",
                        name="INFORMA PLC", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="LN",
                    ),
                    OpenFigiIdentity(
                        figi="BBG_INF_B", composite_figi="BBG_INF_COMP",
                        share_class_figi="BBG_INF_SHARE", ticker="INF",
                        name="INFORMA PLC", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="LO",
                    ),
                ])
            else:
                out.append([])
        return out


def test_lse_duplicate_venue_rows_collapse_at_security_level(tmp_path):
    db = CacheDB(tmp_path / "uk-amb.sqlite")
    r = BatchResolver(db, None, OFLondonAmbiguous(), YHLondon())
    row = TvRow(
        "LSE:INF", "LSE", "INF", "Informa plc", "GBX",
        "stock", ("common",), "Commercial Services", 1e10, 897.0,
    )
    got = r.resolve([row])["LSE:INF"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "SAME_VENUE_SHARE_CLASS_COLLAPSE"
    assert got.share_class_figi == "BBG_INF_SHARE"
    assert got.composite_figi == "BBG_INF_COMP"
    assert got.venue_figi is None
    assert got.source_venue_figi is None
    assert got.target_venue_figi is None
    assert r.stats["openfigi_share_class_collapses"] == 1
    db.close()



class OFReviewedIsinRose:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idType") == "ID_EXCH_SYMBOL" and job.get("idValue") == "ROSE":
                out.append([
                    OpenFigiIdentity(
                        figi="BBG_ROSE_OLD", composite_figi="BBG_ROSE_OLD_COMP",
                        share_class_figi="BBG_ROSE_OLD_SHARE", ticker="ROSE",
                        name="ROSEBANK INDUSTRIES PLC", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="LN",
                    ),
                    OpenFigiIdentity(
                        figi="BBG_ROSE_NEW", composite_figi="BBG_ROSE_NEW_COMP",
                        share_class_figi="BBG_ROSE_NEW_SHARE", ticker="ROSE",
                        name="ROSEBANK INDUSTRIES PLC", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="LN",
                    ),
                ])
            elif job.get("idType") == "ID_ISIN" and job.get("idValue") == "JE00BSBJ5M88" and job.get("micCode") == "XLON":
                out.append([OpenFigiIdentity(
                    figi="BBG01NKWNQL9", composite_figi="BBG_ROSE_COMP",
                    share_class_figi="BBG_ROSE_SHARE", ticker="ROSE",
                    name="ROSEBANK INDUSTRIES PLC", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="LN",
                )])
            else:
                out.append([])
        return out


class YHReviewedIsinRose:
    batch_size = 75
    def quotes(self, symbols):
        if "ROSE.L" in symbols:
            return {"ROSE.L": YahooQuote(
                "ROSE.L", "LSE", "London Stock Exchange", "GBp", "EQUITY",
                "gb_market", "Rosebank Industries plc", None, 340.0, 15,
            )}
        return {}


def test_reviewed_isin_fallback_resolves_provider_ambiguity(tmp_path):
    db = CacheDB(tmp_path / "rose-isin.sqlite")
    r = BatchResolver(db, None, OFReviewedIsinRose(), YHReviewedIsinRose())
    row = TvRow(
        "LSE:ROSE", "LSE", "ROSE", "Rosebank Industries plc", "GBX",
        "stock", ("common",), "Producer Manufacturing", 3.4e9, 340.0,
    )
    got = r.resolve([row])["LSE:ROSE"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "ROSE.L"
    assert got.mapping_method == "REVIEWED_ISIN_FALLBACK"
    assert got.venue_figi == "BBG01NKWNQL9"
    assert got.share_class_figi == "BBG_ROSE_SHARE"
    assert r.stats["openfigi_isin_fallback_jobs"] == 1
    assert r.stats["openfigi_isin_fallback_matches"] == 1
    db.close()

class OFSegroFallback:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idValue") != "SGRO" or job.get("micCode") != "XLON":
                out.append([])
            elif "securityType2" in job:
                # Simulate the live provider: strict Common Stock taxonomy misses.
                out.append([])
            else:
                out.append([OpenFigiIdentity(
                    figi="BBG_SGRO_XLON", composite_figi="BBG_SGRO_COMP",
                    share_class_figi="BBG_SGRO_SHARE", ticker="SGRO",
                    name="SEGRO PLC", security_type="REIT",
                    security_type2="REIT", exch_code="LN",
                )])
        return out


class YHSegro:
    batch_size = 75
    def quotes(self, symbols):
        if "SGRO.L" in symbols:
            return {"SGRO.L": YahooQuote(
                "SGRO.L", "LSE", "London Stock Exchange", "GBp", "EQUITY",
                "gb_market", "SEGRO PLC", None, 930.2, 15,
            )}
        return {}


def test_lse_reit_uses_type_fallback_without_weakening_identity(tmp_path):
    db = CacheDB(tmp_path / "sgro.sqlite")
    r = BatchResolver(db, None, OFSegroFallback(), YHSegro())
    row = TvRow(
        "LSE:SGRO", "LSE", "SGRO", "SEGRO PLC", "GBX",
        "stock", ("common",), "Finance", 1.2e10, 930.2,
    )
    got = r.resolve([row])["LSE:SGRO"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "SGRO.L"
    assert got.mapping_method == "SAME_VENUE_TYPE_FALLBACK"
    assert got.share_class_figi == "BBG_SGRO_SHARE"
    assert r.stats["openfigi_type_fallback_jobs"] == 1
    assert r.stats["openfigi_type_fallback_matches"] == 1
    db.close()


class OFLondonCurrencyMissing:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idValue") == "0QIU" and job.get("micCode") == "XLON" and job.get("currency") == "DKK":
                out.append([OpenFigiIdentity(
                    figi="BBG_0QIU_XLON", composite_figi="BBG_0QIU_COMP",
                    share_class_figi="BBG_0QIU_SHARE", ticker="0QIU",
                    name="TEST INTL", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="LN",
                )])
            else:
                out.append([])
        return out


class YHLondonCurrencyMissing:
    batch_size = 75
    def quotes(self, symbols):
        if "0QIU.L" in symbols:
            return {"0QIU.L": YahooQuote(
                "0QIU.L", "IOB", "International Order Book", None, "EQUITY",
                "gb_market", "TEST INTL", None, 100.0, 15,
            )}
        return {}


def test_non_us_yahoo_missing_currency_is_not_a_contradiction(tmp_path):
    db = CacheDB(tmp_path / "missing-currency.sqlite")
    resolver = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonCurrencyMissing())
    row = TvRow(
        "LSIN:0QIU", "LSIN", "0QIU", "Test Intl", "DKK",
        "stock", ("common",), "Finance", 1e10, 100.0,
    )
    first = resolver.resolve([row])["LSIN:0QIU"]
    assert first.status == "VERIFIED"
    assert first.yahoo_currency is None
    assert first.quote_status == "FRESH_CURRENCY_UNREPORTED"

    resolver2 = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonCurrencyMissing())
    second = resolver2.resolve([row])["LSIN:0QIU"]
    assert second.cache_hit is True
    resolver2.refresh_cached_quotes({row.tv_id: second})
    assert second.status == "VERIFIED"
    assert second.quote_status == "FRESH_CURRENCY_UNREPORTED"
    db.close()

class OFLondonDifferentComposites:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for job in jobs:
            if job.get("idValue") == "INF" and job.get("micCode") == "XLON":
                out.append([
                    OpenFigiIdentity("BBG_INF_A", "BBG_INF_COMP_A", "BBG_INF_SHARE", "INF", "INFORMA PLC", "Common Stock", "Common Stock", "LN"),
                    OpenFigiIdentity("BBG_INF_B", "BBG_INF_COMP_B", "BBG_INF_SHARE", "INF", "INFORMA PLC", "Common Stock", "Common Stock", "LO"),
                ])
            else:
                out.append([])
        return out


def test_lse_same_share_class_can_collapse_across_composites(tmp_path):
    db = CacheDB(tmp_path / "uk-amb-composites.sqlite")
    r = BatchResolver(db, None, OFLondonDifferentComposites(), YHLondon())
    row = TvRow("LSE:INF", "LSE", "INF", "Informa plc", "GBX", "stock", ("common",), "Commercial Services", 1e10, 897.0)
    got = r.resolve([row])["LSE:INF"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "SAME_VENUE_SHARE_CLASS_COLLAPSE"
    assert got.share_class_figi == "BBG_INF_SHARE"
    assert got.composite_figi is None
    assert got.venue_figi is None
    db.close()


class YHLondonTypeMissing:
    batch_size = 75
    def quotes(self, symbols):
        if "0QIU.L" in symbols:
            return {"0QIU.L": YahooQuote(
                "0QIU.L", "IOB", "International Order Book", "DKK", None,
                "gb_market", "TEST INTL", None, 100.0, 15,
            )}
        return {}


def test_non_us_yahoo_missing_type_is_not_a_contradiction(tmp_path):
    db = CacheDB(tmp_path / "missing-type.sqlite")
    resolver = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonTypeMissing())
    row = TvRow("LSIN:0QIU", "LSIN", "0QIU", "Test Intl", "DKK", "stock", ("common",), "Finance", 1e10, 100.0)
    first = resolver.resolve([row])["LSIN:0QIU"]
    assert first.status == "VERIFIED"
    assert first.yahoo_quote_type is None
    assert first.quote_status == "FRESH_TYPE_UNREPORTED"

    resolver2 = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonTypeMissing())
    second = resolver2.resolve([row])["LSIN:0QIU"]
    assert second.cache_hit is True
    resolver2.refresh_cached_quotes({row.tv_id: second})
    assert second.status == "VERIFIED"
    assert second.quote_status == "FRESH_TYPE_UNREPORTED"
    db.close()


def test_yahoo_provider_nullable_text_normalizes_string_none():
    from tv_market_identity.providers import _nullable_text
    assert _nullable_text(None) is None
    assert _nullable_text("NONE") is None
    assert _nullable_text(" null ") is None
    assert _nullable_text("N/A") is None
    assert _nullable_text("EQUITY") == "EQUITY"
    assert _nullable_text("GBp") == "GBp"

class OFSegroGbpOnly:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idValue") != "SGRO" or job.get("micCode") != "XLON":
                out.append([])
            elif job.get("currency") == "GBP" and "securityType2" not in job:
                out.append([OpenFigiIdentity(
                    figi="BBG_SGRO_XLON", composite_figi="BBG_SGRO_COMP",
                    share_class_figi="BBG_SGRO_SHARE", ticker="SGRO",
                    name="SEGRO PLC", security_type="REIT",
                    security_type2="Equity", exch_code="LN",
                )])
            else:
                out.append([])
        return out


def test_lse_gbx_can_use_reviewed_openfigi_gbp_currency_fallback(tmp_path):
    db = CacheDB(tmp_path / "sgro-gbp.sqlite")
    r = BatchResolver(db, None, OFSegroGbpOnly(), YHSegro())
    row = TvRow(
        "LSE:SGRO", "LSE", "SGRO", "SEGRO PLC", "GBX",
        "stock", ("common",), "Finance", 1.2e10, 930.2,
    )
    got = r.resolve([row])["LSE:SGRO"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "SGRO.L"
    assert got.mapping_method == "SAME_VENUE_TYPE_FALLBACK"
    assert r.stats["openfigi_currency_fallback_jobs"] == 1
    assert r.stats["openfigi_currency_fallback_matches"] == 1
    db.close()


class YHLondonVenueAndTypeMissing:
    batch_size = 75
    def quotes(self, symbols):
        if "0QIU.L" in symbols:
            return {"0QIU.L": YahooQuote(
                "0QIU.L", None, None, "DKK", None,
                "gb_market", "TEST INTL", None, 100.0, 15,
            )}
        return {}


def test_non_us_yahoo_missing_venue_uses_reviewed_market_bucket(tmp_path):
    db = CacheDB(tmp_path / "missing-venue.sqlite")
    resolver = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonVenueAndTypeMissing())
    row = TvRow(
        "LSIN:0QIU", "LSIN", "0QIU", "Test Intl", "DKK",
        "stock", ("common",), "Finance", 1e10, 100.0,
    )
    first = resolver.resolve([row])["LSIN:0QIU"]
    assert first.status == "VERIFIED"
    assert first.yahoo_exchange is None
    assert first.yahoo_market == "gb_market"
    assert first.quote_status == "FRESH_METADATA_UNREPORTED"

    resolver2 = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonVenueAndTypeMissing())
    second = resolver2.resolve([row])["LSIN:0QIU"]
    assert second.cache_hit is True
    resolver2.refresh_cached_quotes({row.tv_id: second})
    assert second.status == "VERIFIED"
    assert second.quote_status == "FRESH_METADATA_UNREPORTED"
    db.close()

class YHLondonAllVenueMetadataMissing:
    batch_size = 75
    def quotes(self, symbols):
        if "0QIU.L" in symbols:
            return {"0QIU.L": YahooQuote(
                "0QIU.L", None, None, None, None,
                None, "TEST INTL", None, 100.0, 15,
            )}
        return {}


def test_non_us_yahoo_can_be_sparse_when_openfigi_already_proved_listing(tmp_path):
    db = CacheDB(tmp_path / "sparse-yahoo.sqlite")
    resolver = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonAllVenueMetadataMissing())
    row = TvRow(
        "LSIN:0QIU", "LSIN", "0QIU", "Test Intl", "DKK",
        "stock", ("common",), "Finance", 1e10, 100.0,
    )
    first = resolver.resolve([row])["LSIN:0QIU"]
    assert first.status == "VERIFIED"
    assert first.yahoo_symbol == "0QIU.L"
    assert first.yahoo_exchange is None
    assert first.yahoo_market is None
    assert first.yahoo_currency is None
    assert first.yahoo_quote_type is None
    assert first.quote_status == "FRESH_METADATA_UNREPORTED"

    resolver2 = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonAllVenueMetadataMissing())
    second = resolver2.resolve([row])["LSIN:0QIU"]
    assert second.cache_hit is True
    resolver2.refresh_cached_quotes({row.tv_id: second})
    assert second.status == "VERIFIED"
    assert second.quote_status == "FRESH_METADATA_UNREPORTED"
    db.close()


class OFSegroNoCurrencyOnly:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idValue") != "SGRO" or job.get("micCode") != "XLON":
                out.append([])
            elif "currency" not in job and "securityType2" not in job:
                out.append([OpenFigiIdentity(
                    figi="BBG_SGRO_XLON", composite_figi="BBG_SGRO_COMP",
                    share_class_figi="BBG_SGRO_SHARE", ticker="SGRO",
                    name="SEGRO PLC", security_type="REIT",
                    security_type2="Equity", exch_code="LN",
                )])
            else:
                out.append([])
        return out


def test_lse_gbx_can_use_exact_mic_symbol_openfigi_without_currency(tmp_path):
    db = CacheDB(tmp_path / "sgro-no-currency.sqlite")
    r = BatchResolver(db, None, OFSegroNoCurrencyOnly(), YHSegro())
    row = TvRow(
        "LSE:SGRO", "LSE", "SGRO", "SEGRO PLC", "GBX",
        "stock", ("common",), "Finance", 1.2e10, 930.2,
    )
    got = r.resolve([row])["LSE:SGRO"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "SGRO.L"
    assert got.share_class_figi == "BBG_SGRO_SHARE"
    assert r.stats["openfigi_currency_omitted_jobs"] == 1
    assert r.stats["openfigi_currency_omitted_matches"] == 1
    db.close()

class YHLondonAllMetadataAndPriceMissing:
    batch_size = 75
    def quotes(self, symbols):
        if "0QIU.L" in symbols:
            return {"0QIU.L": YahooQuote(
                "0QIU.L", None, None, None, None,
                None, "TEST INTL", None, None, None,
            )}
        return {}


def test_non_us_sparse_yahoo_row_without_live_price_keeps_identity(tmp_path):
    db = CacheDB(tmp_path / "sparse-yahoo-no-price.sqlite")
    resolver = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonAllMetadataAndPriceMissing())
    row = TvRow(
        "LSIN:0QIU", "LSIN", "0QIU", "Test Intl", "DKK",
        "stock", ("common",), "Finance", 1e10, 100.0,
    )
    first = resolver.resolve([row])["LSIN:0QIU"]
    assert first.status == "VERIFIED"
    assert first.yahoo_symbol == "0QIU.L"
    assert first.yahoo_price is None
    assert first.quote_status == "UNAVAILABLE"

    resolver2 = BatchResolver(db, None, OFLondonCurrencyMissing(), YHLondonAllMetadataAndPriceMissing())
    second = resolver2.resolve([row])["LSIN:0QIU"]
    assert second.cache_hit is True
    resolver2.refresh_cached_quotes({row.tv_id: second})
    assert second.status == "VERIFIED"
    assert second.quote_status == "UNAVAILABLE"
    db.close()


class OFSegroNeverMaps:
    batch_size = 100
    def map_jobs(self, jobs):
        return [[] for _ in jobs]


def test_lse_openfigi_no_match_can_use_strict_yahoo_target_proof(tmp_path):
    db = CacheDB(tmp_path / "sgro-target-only.sqlite")
    r = BatchResolver(db, None, OFSegroNeverMaps(), YHSegro())
    row = TvRow(
        "LSE:SGRO", "LSE", "SGRO", "SEGRO PLC", "GBX",
        "stock", ("common",), "Finance", 1.2e10, 930.2,
    )
    got = r.resolve([row])["LSE:SGRO"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "SGRO.L"
    assert got.mapping_method == "TARGET_PROVIDER_STRICT_FALLBACK"
    assert got.share_class_figi is None
    assert got.composite_figi is None
    assert got.venue_figi is None
    assert r.stats["target_provider_strict_fallback_jobs"] == 1
    assert r.stats["target_provider_strict_fallback_matches"] == 1

    # The target-only fallback itself must also survive a warm-cache refresh,
    # but only because Yahoo continues to report complete compatible metadata.
    r2 = BatchResolver(db, None, OFSegroNeverMaps(), YHSegro())
    cached = r2.resolve([row])["LSE:SGRO"]
    assert cached.cache_hit is True
    r2.refresh_cached_quotes({row.tv_id: cached})
    assert cached.status == "VERIFIED"
    db.close()


class YHSegroSparse:
    batch_size = 75
    def quotes(self, symbols):
        if "SGRO.L" in symbols:
            return {"SGRO.L": YahooQuote(
                "SGRO.L", None, None, None, None, None,
                "SEGRO PLC", None, 930.2, None,
            )}
        return {}


def test_target_provider_fallback_rejects_sparse_yahoo_metadata(tmp_path):
    db = CacheDB(tmp_path / "sgro-target-only-sparse.sqlite")
    r = BatchResolver(db, None, OFSegroNeverMaps(), YHSegroSparse())
    row = TvRow(
        "LSE:SGRO", "LSE", "SGRO", "SEGRO PLC", "GBX",
        "stock", ("common",), "Finance", 1.2e10, 930.2,
    )
    got = r.resolve([row])["LSE:SGRO"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_CURRENCY_UNREPORTED_TARGET_ONLY"
    db.close()


class OFSwissSecondaryNoMatch:
    batch_size = 100
    def map_jobs(self, jobs):
        # Model the observed provider gap: exact SIX/XSWX secondary listings
        # are absent from OpenFIGI ID_EXCH_SYMBOL mapping, even without type.
        return [[] for _ in jobs]


class YHSwissSecondary:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        if "ISP.SW" in symbols:
            out["ISP.SW"] = YahooQuote(
                "ISP.SW", "EBS", "SIX Swiss Exchange", "CHF", "EQUITY",
                "ch_market", "INTESA SANPAOLO", None, 6.45, 15,
            )
        if "T.SW" in symbols:
            out["T.SW"] = YahooQuote(
                "T.SW", "EBS", "SIX Swiss Exchange", "CHF", "EQUITY",
                "ch_market", "AT&T INC", None, 21.36, 15,
            )
        return out


def test_six_secondary_listings_use_strict_target_provider_fallback(tmp_path):
    db = CacheDB(tmp_path / "six-secondary.sqlite")
    r = BatchResolver(db, None, OFSwissSecondaryNoMatch(), YHSwissSecondary())
    rows = [
        TvRow("SIX:ISP", "SIX", "ISP", "Intesa Sanpaolo", "CHF",
              "stock", ("common",), "Finance", 1e11, 6.45),
        TvRow("SIX:T", "SIX", "T", "AT&T Inc.", "CHF",
              "stock", ("common",), "Communications", 1e11, 21.36),
    ]
    got = r.resolve(rows)
    for tv_id, yahoo_symbol in (("SIX:ISP", "ISP.SW"), ("SIX:T", "T.SW")):
        b = got[tv_id]
        assert b.status == "VERIFIED"
        assert b.yahoo_symbol == yahoo_symbol
        assert b.resolved_mic == "XSWX"
        assert b.mapping_method == "TARGET_PROVIDER_STRICT_FALLBACK"
        assert b.share_class_figi is None
        assert b.composite_figi is None
        assert b.venue_figi is None
    assert r.stats["target_provider_strict_fallback_jobs"] == 2
    assert r.stats["target_provider_strict_fallback_matches"] == 2

    # Warm-cache quote validation must keep the same lower-evidence contract.
    r2 = BatchResolver(db, None, OFSwissSecondaryNoMatch(), YHSwissSecondary())
    cached = r2.resolve(rows)
    assert all(cached[x.tv_id].cache_hit for x in rows)
    r2.refresh_cached_quotes(cached)
    assert all(cached[x.tv_id].status == "VERIFIED" for x in rows)
    db.close()


class YHSwissSecondaryWrongVenue(YHSwissSecondary):
    def quotes(self, symbols):
        out = super().quotes(symbols)
        if "T.SW" in out:
            out["T.SW"] = YahooQuote(
                "T.SW", "NYQ", "NYSE", "CHF", "EQUITY",
                "us_market", "AT&T INC", None, 21.36, 0,
            )
        return out


def test_six_target_provider_fallback_rejects_wrong_yahoo_venue(tmp_path):
    db = CacheDB(tmp_path / "six-secondary-wrong-venue.sqlite")
    r = BatchResolver(db, None, OFSwissSecondaryNoMatch(), YHSwissSecondaryWrongVenue())
    row = TvRow("SIX:T", "SIX", "T", "AT&T Inc.", "CHF",
                "stock", ("common",), "Communications", 1e11, 21.36)
    b = r.resolve([row])[row.tv_id]
    assert b.status == "REJECTED"
    assert b.rejection_reason.startswith("YAHOO_VENUE_MISMATCH:XSWX")
    db.close()

class OFYahooChartFallback:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idValue") == "KAKU" and job.get("micCode") == "XLON":
                out.append([OpenFigiIdentity(
                    figi="BBG_KAKU_XLON", composite_figi="BBG_KAKU_COMP",
                    share_class_figi="BBG_KAKU_SHARE", ticker="KAKU",
                    name="KAKUZI PLC", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="LN",
                )])
            else:
                out.append([])
        return out


class YHYahooChartFallback:
    batch_size = 75
    def quotes(self, symbols):
        if "KAKU.L" in symbols:
            # v7/quote can misclassify thin London lines.
            return {"KAKU.L": YahooQuote(
                "KAKU.L", "LSE", "LSE", "GBp", "MUTUALFUND", "gb_market",
                "KAKUZI PLC", None, 92.5, 15,
            )}
        return {}

    def chart_quotes(self, symbols):
        if "KAKU.L" in symbols:
            return {"KAKU.L": YahooQuote(
                "KAKU.L", "LSE", "LSE", "GBp", "EQUITY", None,
                "KAKUZI PLC", None, 92.5, 15,
            )}
        return {}


def test_non_us_yahoo_chart_metadata_can_correct_bulk_type_misclassification(tmp_path):
    db = CacheDB(tmp_path / "chart-fallback.sqlite")
    r = BatchResolver(db, None, OFYahooChartFallback(), YHYahooChartFallback())
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "Kakuzi Plc", "GBX",
        "stock", ("common",), None, None, 92.5,
    )
    got = r.resolve([row])["LSE:KAKU"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "KAKU.L"
    assert got.yahoo_quote_type == "EQUITY"
    assert r.stats["yahoo_chart_fallback_jobs"] == 1
    assert r.stats["yahoo_chart_fallback_matches"] == 1
    db.close()


def test_yahoo_chart_provider_parses_meta_without_mutating_symbol():
    from tv_market_identity.providers import YahooProvider

    class Data:
        def get_raw_json(self, url, params=None, timeout=None):
            assert url.endswith('/KAKU.L')
            return {
                'chart': {'result': [{'meta': {
                    'symbol': 'KAKU.L',
                    'exchangeName': 'LSE',
                    'fullExchangeName': 'London Stock Exchange',
                    'currency': 'GBp',
                    'instrumentType': 'EQUITY',
                    'regularMarketPrice': 92.5,
                    'exchangeDataDelayedBy': 15,
                }}]}
            }

    p = YahooProvider.__new__(YahooProvider)
    p.batch_size = 75
    p.data = Data()
    q = p.chart_quotes(['KAKU.L'])['KAKU.L']
    assert q.symbol == 'KAKU.L'
    assert q.currency == 'GBp'
    assert q.quote_type == 'EQUITY'
    assert q.exchange == 'LSE'
    assert q.price == 92.5


class OFReviewedIsinBvs:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idType") == "ID_EXCH_SYMBOL" and job.get("idValue") == "BVS" and job.get("micCode") == "XLON":
                out.append([
                    OpenFigiIdentity("OLD1", "OLDC1", "SHARE_OLD", "BVS", "BRAVURA SOLUTIONS", "Common Stock", "Common Stock", "LN"),
                    OpenFigiIdentity("OLD2", "OLDC2", "SHARE_NEW", "BVS", "BRAVURA SOLUTIONS", "Common Stock", "Common Stock", "LN"),
                ])
            elif job.get("idType") == "ID_ISIN" and job.get("idValue") == "AU000000BVS9" and job.get("micCode") == "AIMX":
                out.append([OpenFigiIdentity(
                    "BVS_AIM_FIGI", "BVS_AIM_COMP", "BVS_SHARE", "BVS",
                    "BRAVURA SOLUTIONS LTD", "Common Stock", "Common Stock", "LN",
                )])
            else:
                out.append([])
        return out


class YHReviewedIsinBvs:
    batch_size = 75
    def quotes(self, symbols):
        if "BVS.L" in symbols:
            return {"BVS.L": YahooQuote(
                "BVS.L", "LSE", "London Stock Exchange", "GBp", "EQUITY",
                "gb_market", "Bravura Solutions Ltd", None, 120.0, 15,
            )}
        return {}


def test_reviewed_isin_fallback_can_override_provider_prefix_mic(tmp_path):
    db = CacheDB(tmp_path / "bvs-isin.sqlite")
    r = BatchResolver(db, None, OFReviewedIsinBvs(), YHReviewedIsinBvs())
    row = TvRow(
        "LSE:BVS", "LSE", "BVS", "Bravura Solutions Ltd", "GBX",
        "stock", ("common",), "Technology Services", 1e9, 120.0,
    )
    got = r.resolve([row])["LSE:BVS"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "REVIEWED_ISIN_FALLBACK"
    assert got.resolved_mic == "AIMX"
    assert got.source_mic == "AIMX"
    assert got.target_mic == "AIMX"
    assert got.yahoo_symbol == "BVS.L"
    assert got.venue_figi == "BVS_AIM_FIGI"
    db.close()


class OFLsinXlomFallback:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idValue") == "FEDS" and job.get("micCode") == "XLOM" and "securityType2" not in job:
                out.append([OpenFigiIdentity(
                    "FEDS_XLOM_FIGI", "FEDS_XLOM_COMP", "FEDS_SHARE", "FEDS",
                    "FEDERAL BANK LIMITED", "Depositary Receipt", "Depositary Receipt", "LI",
                )])
            else:
                out.append([])
        return out


class YHLsinXlomFallback:
    batch_size = 75
    def quotes(self, symbols):
        if "FEDS.IL" in symbols:
            return {"FEDS.IL": YahooQuote(
                "FEDS.IL", "IOB", "International Order Book", "USD", "EQUITY",
                "gb_market", "Federal Bank Limited", None, 0.92, 15,
            )}
        return {}


def test_lsin_can_fall_back_from_xlon_to_xlom(tmp_path):
    db = CacheDB(tmp_path / "lsin-xlom.sqlite")
    r = BatchResolver(db, None, OFLsinXlomFallback(), YHLsinXlomFallback())
    row = TvRow(
        "LSIN:FEDS", "LSIN", "FEDS", "Federal Bank Limited", "USD",
        "dr", ("",), "Finance", 1e9, 0.92,
    )
    got = r.resolve([row])["LSIN:FEDS"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "LSIN_SECONDARY_MIC_TYPE_FALLBACK"
    assert got.source_mic == "XLOM"
    assert got.target_mic == "XLOM"
    assert got.resolved_mic == "XLOM"
    assert got.yahoo_symbol == "FEDS.IL"
    assert got.yahoo_exchange == "IOB"
    assert got.venue_figi == "FEDS_XLOM_FIGI"
    assert r.stats["openfigi_secondary_mic_jobs"] == 1
    assert r.stats["openfigi_secondary_mic_matches"] == 1
    db.close()


class OFReviewedIsinBvsUnscoped:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idType") == "ID_EXCH_SYMBOL" and job.get("idValue") == "BVS" and job.get("micCode") == "XLON":
                out.append([
                    OpenFigiIdentity("OLD1", "OLDC1", "SHARE_OLD", "BVS", "BRAVURA SOLUTIONS", "Common Stock", "Common Stock", "LN"),
                    OpenFigiIdentity("OLD2", "OLDC2", "SHARE_NEW", "BVS", "BRAVURA SOLUTIONS", "Common Stock", "Common Stock", "LN"),
                ])
            elif job.get("idType") == "ID_ISIN" and job.get("idValue") == "AU000000BVS9" and job.get("micCode") == "AIMX":
                out.append([])
            elif job.get("idType") == "ID_ISIN" and job.get("idValue") == "AU000000BVS9" and "micCode" not in job:
                # OpenFIGI knows the older ASX venue. The fallback may use the
                # shared security identity, but must not relabel this venue FIGI
                # or Australian composite as AIMX.
                out.append([OpenFigiIdentity(
                    "BVS_ASX_FIGI", "BVS_AU_COMP", "BVS_SHARE", "BVS",
                    "BRAVURA SOLUTIONS LTD", "Common Stock", "Common Stock", "AU",
                )])
            else:
                out.append([])
        return out


def test_reviewed_isin_can_use_unscoped_security_identity_without_venue_figi_leak(tmp_path):
    db = CacheDB(tmp_path / "bvs-isin-unscoped.sqlite")
    r = BatchResolver(db, None, OFReviewedIsinBvsUnscoped(), YHReviewedIsinBvs())
    row = TvRow(
        "LSE:BVS", "LSE", "BVS", "Bravura Solutions Ltd", "GBX",
        "stock", ("common",), "Technology Services", 1e9, 120.0,
    )
    got = r.resolve([row])["LSE:BVS"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "REVIEWED_ISIN_SECURITY_FALLBACK"
    assert got.resolved_mic == "AIMX"
    assert got.source_mic == "AIMX"
    assert got.target_mic == "AIMX"
    assert got.yahoo_symbol == "BVS.L"
    assert got.share_class_figi == "BVS_SHARE"
    assert got.venue_figi is None
    assert got.composite_figi is None
    assert got.source_venue_figi is None
    assert got.target_venue_figi is None
    assert r.stats["openfigi_isin_unscoped_fallback_jobs"] == 1
    assert r.stats["openfigi_isin_unscoped_fallback_matches"] == 1
    assert r.stats["reviewed_isin_security_fallback_matches"] == 1
    db.close()


class YHReviewedIsinBvsMissingType:
    batch_size = 75
    def quotes(self, symbols):
        if "BVS.L" in symbols:
            return {"BVS.L": YahooQuote(
                "BVS.L", "LSE", "London Stock Exchange", "GBp", None,
                "gb_market", "Bravura Solutions Ltd", None, 120.0, 15,
            )}
        return {}


def test_reviewed_isin_unscoped_security_path_requires_explicit_yahoo_metadata(tmp_path):
    db = CacheDB(tmp_path / "bvs-isin-unscoped-strict.sqlite")
    r = BatchResolver(db, None, OFReviewedIsinBvsUnscoped(), YHReviewedIsinBvsMissingType())
    row = TvRow(
        "LSE:BVS", "LSE", "BVS", "Bravura Solutions Ltd", "GBX",
        "stock", ("common",), "Technology Services", 1e9, 120.0,
    )
    got = r.resolve([row])["LSE:BVS"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_TYPE_UNREPORTED_TARGET_ONLY"
    db.close()


class OFLsinXlomCurrencyOmitted:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if (
                job.get("idType") == "ID_EXCH_SYMBOL"
                and job.get("idValue") == "FEDS"
                and job.get("micCode") == "XLOM"
                and "currency" not in job
                and "securityType2" not in job
            ):
                out.append([OpenFigiIdentity(
                    "FEDS_XLOM_FIGI", "FEDS_XLOM_COMP", "FEDS_SHARE", "FEDS",
                    "FEDERAL BANK LIMITED", "Depositary Receipt", "Depositary Receipt", "LI",
                )])
            else:
                out.append([])
        return out


class YHLsinDrDotLOnly:
    batch_size = 75
    def quotes(self, symbols):
        if "FEDS.L" in symbols:
            return {"FEDS.L": YahooQuote(
                "FEDS.L", "LSE", "London Stock Exchange", "USD", "EQUITY",
                "gb_market", "Federal Bank Limited", None, 0.92, 15,
            )}
        return {}


def test_lsin_xlom_can_drop_only_currency_then_use_dot_l_for_openfigi_proven_dr(tmp_path):
    db = CacheDB(tmp_path / "lsin-xlom-no-currency-dot-l.sqlite")
    r = BatchResolver(db, None, OFLsinXlomCurrencyOmitted(), YHLsinDrDotLOnly())
    row = TvRow(
        "LSIN:FEDS", "LSIN", "FEDS", "Federal Bank Limited", "USD",
        "dr", ("",), "Finance", 1e9, 0.92,
    )
    got = r.resolve([row])["LSIN:FEDS"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "LSIN_SECONDARY_MIC_CURRENCY_OMITTED_FALLBACK"
    assert got.resolved_mic == "XLOM"
    assert got.source_mic == "XLOM"
    assert got.target_mic == "XLOM"
    assert got.yahoo_symbol == "FEDS.L"
    assert got.venue_figi == "FEDS_XLOM_FIGI"
    assert r.stats["openfigi_secondary_mic_jobs"] == 1
    assert r.stats["openfigi_secondary_mic_matches"] == 0
    assert r.stats["openfigi_secondary_mic_currency_omitted_jobs"] == 1
    assert r.stats["openfigi_secondary_mic_currency_omitted_matches"] == 1
    assert r.stats["yahoo_lsin_dr_alt_fallback_jobs"] == 1
    assert r.stats["yahoo_lsin_dr_alt_fallback_matches"] == 1
    db.close()


class OFLsinNeverMaps:
    batch_size = 100
    def map_jobs(self, jobs):
        return [[] for _ in jobs]


def test_lsin_dr_dot_l_is_not_used_when_only_yahoo_target_evidence_exists(tmp_path):
    db = CacheDB(tmp_path / "lsin-dr-target-only-no-dot-l.sqlite")
    r = BatchResolver(db, None, OFLsinNeverMaps(), YHLsinDrDotLOnly())
    row = TvRow(
        "LSIN:FEDS", "LSIN", "FEDS", "Federal Bank Limited", "USD",
        "dr", ("",), "Finance", 1e9, 0.92,
    )
    got = r.resolve([row])["LSIN:FEDS"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_NO_MATCH"
    assert r.stats["target_provider_strict_fallback_jobs"] == 1
    assert r.stats["yahoo_lsin_dr_alt_fallback_jobs"] == 0
    db.close()


class OFMntlCurrent:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if (
                job.get("idType") == "ID_EXCH_SYMBOL"
                and job.get("idValue") == "MNTL"
                and job.get("micCode") == "XLON"
            ):
                out.append([OpenFigiIdentity(
                    "MNTL_XLON_FIGI", "MNTL_XLON_COMP", "MNTL_SHARE", "MNTL",
                    "TECHNOLOGY MINERALS PLC", "Common Stock", "Common Stock", "LN",
                )])
            else:
                out.append([])
        return out


class YHMntlOldTicker:
    batch_size = 75
    def quotes(self, symbols):
        if "TM1.L" in symbols:
            return {"TM1.L": YahooQuote(
                "TM1.L", "LSE", "London Stock Exchange", "GBp", "EQUITY",
                "gb_market", "Technology Minerals Plc", None, 0.06, 15,
            )}
        return {}


def test_reviewed_recent_yahoo_ticker_alias_requires_current_openfigi_identity(tmp_path):
    db = CacheDB(tmp_path / "mntl-transition.sqlite")
    r = BatchResolver(db, None, OFMntlCurrent(), YHMntlOldTicker())
    row = TvRow(
        "LSE:MNTL", "LSE", "MNTL", "Technology Minerals Plc", "GBX",
        "stock", ("common",), "Non-Energy Minerals", 7.5e6, 0.06,
    )
    got = r.resolve([row])["LSE:MNTL"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "TM1.L"
    assert got.mapping_method == "REVIEWED_YAHOO_TRANSITION_ALIAS"
    assert got.resolved_mic == "XLON"
    assert got.share_class_figi == "MNTL_SHARE"
    assert r.stats["reviewed_yahoo_symbol_alias_jobs"] == 1
    assert r.stats["reviewed_yahoo_symbol_alias_rows"] == 1
    assert r.stats["reviewed_yahoo_symbol_alias_matches"] == 1
    assert r.stats["yahoo_lsin_alt_fallback_jobs"] == 0
    assert r.stats["yahoo_lsin_alt_fallback_rows"] == 0
    db.close()


class YHMntlWrongIssuer(YHMntlOldTicker):
    def quotes(self, symbols):
        if "TM1.L" in symbols:
            return {"TM1.L": YahooQuote(
                "TM1.L", "LSE", "London Stock Exchange", "GBp", "EQUITY",
                "gb_market", "Unrelated Issuer Plc", None, 0.06, 15,
            )}
        return {}


def test_reviewed_recent_yahoo_ticker_alias_rejects_wrong_issuer_name(tmp_path):
    db = CacheDB(tmp_path / "mntl-transition-wrong-name.sqlite")
    r = BatchResolver(db, None, OFMntlCurrent(), YHMntlWrongIssuer())
    row = TvRow(
        "LSE:MNTL", "LSE", "MNTL", "Technology Minerals Plc", "GBX",
        "stock", ("common",), "Non-Energy Minerals", 7.5e6, 0.06,
    )
    got = r.resolve([row])["LSE:MNTL"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_NO_MATCH"
    assert r.stats["reviewed_yahoo_symbol_alias_jobs"] == 1
    assert r.stats["reviewed_yahoo_symbol_alias_matches"] == 0
    db.close()


def test_lsin_stock_does_not_get_secondary_mic_currency_omitted_path(tmp_path):
    db = CacheDB(tmp_path / "lsin-stock-no-xlom-currency-omitted.sqlite")
    r = BatchResolver(db, None, OFLsinNeverMaps(), YHLsinDrDotLOnly())
    row = TvRow(
        "LSIN:TEST", "LSIN", "TEST", "Test Plc", "USD",
        "stock", ("common",), "Industrials", 1e9, 1.0,
    )
    got = r.resolve([row])["LSIN:TEST"]
    assert got.status == "REJECTED"
    assert r.stats["openfigi_secondary_mic_jobs"] == 1
    assert r.stats["openfigi_secondary_mic_currency_omitted_jobs"] == 0
    assert r.stats["target_provider_strict_fallback_jobs"] == 1
    db.close()

class YHLondonChartCurrencyConflict:
    batch_size = 75
    def quotes(self, symbols):
        return {}

    def chart_quotes(self, symbols):
        out = {}
        if "SDIC.IL" in symbols:
            out["SDIC.IL"] = YahooQuote(
                "SDIC.IL", "IOB", "International Order Book", "GBP", "EQUITY",
                "gb_market", "SDIC POWER HOLDINGS CO LTD", None, 12.0, 15,
            )
        return out


def test_incompatible_chart_row_preserves_exact_rejection_reason(tmp_path):
    db = CacheDB(tmp_path / "chart-conflict.sqlite")
    r = BatchResolver(db, None, OFLondon(), YHLondonChartCurrencyConflict())
    row = TvRow(
        "LSIN:SDIC", "LSIN", "SDIC", "SDIC Power Holdings Co Ltd", "USD",
        "dr", ("",), "Utilities", 1e10, 12.0,
    )
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_CHART_CURRENCY_MISMATCH:GBP"
    assert r.stats["yahoo_incompatible_evidence_rows"] == 1
    assert r.stats["yahoo_incompatible_currency_rows"] == 1
    assert r.stats["yahoo_lsin_dr_alt_fallback_jobs"] == 1
    db.close()


class YHLsinDrDotLMutualFund:
    batch_size = 75
    def quotes(self, symbols):
        if "FEDS.L" in symbols:
            return {"FEDS.L": YahooQuote(
                "FEDS.L", "LSE", "London Stock Exchange", "USD", "MUTUALFUND",
                "gb_market", "Federal Bank Limited", None, 0.92, 15,
            )}
        return {}


def test_lsin_openfigi_proven_dr_accepts_bounded_yahoo_mutualfund_taxonomy_anomaly(tmp_path):
    db = CacheDB(tmp_path / "lsin-dr-yahoo-mutualfund-taxonomy.sqlite")
    r = BatchResolver(db, None, OFLsinXlomCurrencyOmitted(), YHLsinDrDotLMutualFund())
    row = TvRow(
        "LSIN:FEDS", "LSIN", "FEDS", "Federal Bank Limited", "USD",
        "dr", ("",), "Finance", 1e9, 0.92,
    )
    got = r.resolve([row])["LSIN:FEDS"]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "FEDS.L"
    assert got.yahoo_quote_type == "MUTUALFUND"
    assert got.resolved_mic == "XLOM"
    assert got.mapping_method == "LSIN_SECONDARY_MIC_CURRENCY_OMITTED_FALLBACK"
    assert r.stats["yahoo_lsin_dr_alt_fallback_matches"] == 1
    assert r.stats["yahoo_lsin_dr_mutualfund_taxonomy_matches"] == 1
    db.close()


class OFLsinXlomCurrencyOmittedCommonStock:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if (
                job.get("idType") == "ID_EXCH_SYMBOL"
                and job.get("idValue") == "FEDS"
                and job.get("micCode") == "XLOM"
                and "currency" not in job
                and "securityType2" not in job
            ):
                out.append([OpenFigiIdentity(
                    "FEDS_XLOM_FIGI", "FEDS_XLOM_COMP", "FEDS_SHARE", "FEDS",
                    "FEDERAL BANK LIMITED", "Common Stock", "Common Stock", "LI",
                )])
            else:
                out.append([])
        return out


def test_lsin_yahoo_mutualfund_anomaly_requires_explicit_openfigi_dr_taxonomy(tmp_path):
    db = CacheDB(tmp_path / "lsin-mf-requires-of-dr.sqlite")
    r = BatchResolver(db, None, OFLsinXlomCurrencyOmittedCommonStock(), YHLsinDrDotLMutualFund())
    row = TvRow(
        "LSIN:FEDS", "LSIN", "FEDS", "Federal Bank Limited", "USD",
        "dr", ("",), "Finance", 1e9, 0.92,
    )
    got = r.resolve([row])["LSIN:FEDS"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_ALT_TYPE_MISMATCH:MUTUALFUND"
    assert r.stats["yahoo_lsin_dr_mutualfund_taxonomy_matches"] == 0
    db.close()


class YHLsinDrDotLMutualFundNoVenue:
    batch_size = 75
    def quotes(self, symbols):
        if "FEDS.L" in symbols:
            return {"FEDS.L": YahooQuote(
                "FEDS.L", None, None, "USD", "MUTUALFUND",
                "gb_market", "Federal Bank Limited", None, 0.92, 15,
            )}
        return {}


def test_lsin_yahoo_mutualfund_anomaly_requires_explicit_yahoo_venue(tmp_path):
    db = CacheDB(tmp_path / "lsin-mf-requires-yahoo-venue.sqlite")
    r = BatchResolver(db, None, OFLsinXlomCurrencyOmitted(), YHLsinDrDotLMutualFundNoVenue())
    row = TvRow(
        "LSIN:FEDS", "LSIN", "FEDS", "Federal Bank Limited", "USD",
        "dr", ("",), "Finance", 1e9, 0.92,
    )
    got = r.resolve([row])["LSIN:FEDS"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_ALT_TYPE_MISMATCH:MUTUALFUND"
    assert r.stats["yahoo_lsin_dr_mutualfund_taxonomy_matches"] == 0
    db.close()


def test_lsin_mutualfund_taxonomy_binding_survives_warm_cache_quote_refresh(tmp_path):
    db = CacheDB(tmp_path / "lsin-mf-warm-cache.sqlite")
    row = TvRow(
        "LSIN:FEDS", "LSIN", "FEDS", "Federal Bank Limited", "USD",
        "dr", ("",), "Finance", 1e9, 0.92,
    )
    cold = BatchResolver(db, None, OFLsinXlomCurrencyOmitted(), YHLsinDrDotLMutualFund())
    first = cold.resolve([row], refresh=True)[row.tv_id]
    assert first.status == "VERIFIED"
    assert first.yahoo_quote_type == "MUTUALFUND"

    warm = BatchResolver(db, None, OFLsinXlomCurrencyOmitted(), YHLsinDrDotLMutualFund())
    got = warm.resolve([row])
    assert got[row.tv_id].status == "VERIFIED"
    assert got[row.tv_id].cache_hit is True
    warm.refresh_cached_quotes(got)
    assert got[row.tv_id].status == "VERIFIED"
    assert got[row.tv_id].yahoo_quote_type == "MUTUALFUND"
    db.close()


class OFReviewedYahooMutualFundTaxonomy:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        metadata = {
            "BKM": ("BANKMUSCAT (S.A.O.G.)", "BKM_SHARE"),
            "EFGD": ("EFG HOLDING S.A.E.", "EFGD_SHARE"),
            "KAKU": ("KAKUZI LD", "KAKU_SHARE"),
            "TGE": ("THE GENERATION ESSENTIALS GROUP", "TGE_SHARE"),
        }
        out = []
        for job in jobs:
            sym = job.get("idValue")
            if job.get("idType") != "ID_EXCH_SYMBOL" or job.get("micCode") != "XLON" or sym not in metadata:
                out.append([])
                continue
            # Simulate the two real DR outliers: strict Depositary Receipt lookup
            # misses, while the taxonomy-relaxed exact ticker/MIC retry is exposed
            # by OpenFIGI as coarse Common Stock.
            if sym in {"BKM", "EFGD"} and job.get("securityType2") == "Depositary Receipt":
                out.append([])
                continue
            name, share = metadata[sym]
            out.append([OpenFigiIdentity(
                f"{sym}_FIGI", f"{sym}_COMP", share, sym, name,
                "Common Stock", "Common Stock", "LN",
            )])
        return out


class YHReviewedYahooMutualFundTaxonomy:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        rows = {
            "BKM.L": ("USD", "BANKMUSCAT (S.A.O.G.)", 3.84),
            "EFGD.L": ("USD", "EFG HOLDING S.A.E.", 1.00),
            "KAKU.L": ("GBp", "KAKUZI LD", 92.50),
            "TGE.L": ("USD", "THE GENERATION ESSENTIALS GROUP", 1.30),
        }
        for symbol, (currency, name, price) in rows.items():
            if symbol in symbols:
                out[symbol] = YahooQuote(
                    symbol, "LSE", "London Stock Exchange", currency, "MUTUALFUND",
                    "gb_market", name, None, price, 15,
                )
        return out


def test_reviewed_yahoo_mutualfund_registry_closes_two_coarse_openfigi_drs(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-drs.sqlite")
    r = BatchResolver(db, None, OFReviewedYahooMutualFundTaxonomy(), YHReviewedYahooMutualFundTaxonomy())
    rows = [
        TvRow("LSIN:BKM", "LSIN", "BKM", "BANKMUSCAT (S.A.O.G.)", "USD", "dr", ("",), "Finance", 1e9, 3.84),
        TvRow("LSIN:EFGD", "LSIN", "EFGD", "EFG HOLDING S.A.E.", "USD", "dr", ("",), "Finance", 1e9, 1.00),
    ]
    got = r.resolve(rows)
    assert got["LSIN:BKM"].status == "VERIFIED"
    assert got["LSIN:BKM"].yahoo_symbol == "BKM.L"
    assert got["LSIN:BKM"].yahoo_quote_type == "MUTUALFUND"
    assert got["LSIN:EFGD"].status == "VERIFIED"
    assert got["LSIN:EFGD"].yahoo_symbol == "EFGD.L"
    assert got["LSIN:EFGD"].yahoo_quote_type == "MUTUALFUND"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] == 2
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 2
    db.close()


def test_reviewed_yahoo_mutualfund_registry_closes_exact_lse_common_equities(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-equities.sqlite")
    r = BatchResolver(db, None, OFReviewedYahooMutualFundTaxonomy(), YHReviewedYahooMutualFundTaxonomy())
    rows = [
        TvRow("LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX", "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5),
        TvRow("LSE:TGE", "LSE", "TGE", "THE GENERATION ESSENTIALS GROUP", "USD", "stock", ("common",), "Consumer Services", 4e7, 1.30),
    ]
    got = r.resolve(rows)
    assert got["LSE:KAKU"].status == "VERIFIED"
    assert got["LSE:KAKU"].yahoo_quote_type == "MUTUALFUND"
    assert got["LSE:TGE"].status == "VERIFIED"
    assert got["LSE:TGE"].yahoo_quote_type == "MUTUALFUND"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] == 2
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 2
    db.close()


class OFNoReviewedIdentity:
    batch_size = 100
    def map_jobs(self, jobs):
        return [[] for _ in jobs]


class YHReviewedYahooMutualFundCurrencyUnreported:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        rows = {
            "BKM.L": ("BANKMUSCAT (S.A.O.G.)", 3.84),
            "EFGD.L": ("EFG HOLDING S.A.E.", 1.00),
            "KAKU.L": ("KAKUZI LD", 92.50),
            "TGE.L": ("THE GENERATION ESSENTIALS GROUP", 1.30),
        }
        for symbol, (name, price) in rows.items():
            if symbol in symbols:
                out[symbol] = YahooQuote(
                    symbol, "LSE", "London Stock Exchange", None, "MUTUALFUND",
                    "gb_market", name, None, price, 15,
                )
        return out


def test_reviewed_yahoo_mutualfund_registry_allows_unreported_currency_only(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-currency-unreported.sqlite")
    r = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundCurrencyUnreported(),
    )
    rows = [
        TvRow("LSIN:BKM", "LSIN", "BKM", "BANKMUSCAT (S.A.O.G.)", "USD", "dr", ("",), "Finance", 1e9, 3.84),
        TvRow("LSIN:EFGD", "LSIN", "EFGD", "EFG HOLDING S.A.E.", "USD", "dr", ("",), "Finance", 1e9, 1.00),
        TvRow("LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX", "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5),
        TvRow("LSE:TGE", "LSE", "TGE", "THE GENERATION ESSENTIALS GROUP", "USD", "stock", ("common",), "Consumer Services", 4e7, 1.30),
    ]
    got = r.resolve(rows, refresh=True)
    assert all(got[row.tv_id].status == "VERIFIED" for row in rows)
    assert all(got[row.tv_id].quote_status == "FRESH_CURRENCY_UNREPORTED" for row in rows)
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] == 4
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 4
    assert r.stats["reviewed_yahoo_mutualfund_currency_unreported_matches"] == 4
    assert r.stats["reviewed_yahoo_mutualfund_block_currency_unreported"] == 0
    db.close()


class YHReviewedYahooMutualFundWrongCurrency:
    batch_size = 75
    def quotes(self, symbols):
        if "KAKU.L" in symbols:
            return {"KAKU.L": YahooQuote(
                "KAKU.L", "LSE", "London Stock Exchange", "USD", "MUTUALFUND",
                "gb_market", "KAKUZI LD", None, 92.5, 15,
            )}
        return {}


def test_reviewed_yahoo_mutualfund_registry_still_rejects_explicit_wrong_currency(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-currency-mismatch.sqlite")
    r = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundWrongCurrency(),
    )
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    got = r.resolve([row], refresh=True)[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_CURRENCY_MISMATCH:USD"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 0
    assert r.stats["reviewed_yahoo_mutualfund_block_currency_mismatch"] == 1
    db.close()


def test_reviewed_yahoo_mutualfund_registry_never_replaces_openfigi_identity(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-needs-openfigi.sqlite")
    r = BatchResolver(db, None, OFNoReviewedIdentity(), YHReviewedYahooMutualFundTaxonomy())
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_TYPE_MISMATCH:MUTUALFUND"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 0
    db.close()


def test_reviewed_yahoo_mutualfund_registry_requires_reviewed_issuer_name(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-name-guard.sqlite")
    r = BatchResolver(db, None, OFReviewedYahooMutualFundTaxonomy(), YHReviewedYahooMutualFundTaxonomy())
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "UNRELATED ISSUER", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_TYPE_MISMATCH:MUTUALFUND"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 0
    db.close()


def test_reviewed_yahoo_mutualfund_binding_survives_warm_cache_quote_refresh(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-warm-cache.sqlite")
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    cold = BatchResolver(db, None, OFReviewedYahooMutualFundTaxonomy(), YHReviewedYahooMutualFundTaxonomy())
    first = cold.resolve([row], refresh=True)[row.tv_id]
    assert first.status == "VERIFIED"
    assert first.yahoo_quote_type == "MUTUALFUND"

    warm = BatchResolver(db, None, OFReviewedYahooMutualFundTaxonomy(), YHReviewedYahooMutualFundTaxonomy())
    got = warm.resolve([row])
    assert got[row.tv_id].status == "VERIFIED"
    assert got[row.tv_id].cache_hit is True
    warm.refresh_cached_quotes(got)
    assert got[row.tv_id].status == "VERIFIED"
    assert got[row.tv_id].yahoo_quote_type == "MUTUALFUND"
    db.close()


def test_reviewed_yahoo_mutualfund_missing_currency_survives_warm_cache_refresh(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-missing-currency-warm.sqlite")
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    cold = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundCurrencyUnreported(),
    )
    first = cold.resolve([row], refresh=True)[row.tv_id]
    assert first.status == "VERIFIED"
    assert first.quote_status == "FRESH_CURRENCY_UNREPORTED"

    warm = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundCurrencyUnreported(),
    )
    got = warm.resolve([row])
    assert got[row.tv_id].status == "VERIFIED"
    assert got[row.tv_id].cache_hit is True
    warm.refresh_cached_quotes(got)
    assert got[row.tv_id].status == "VERIFIED"
    assert got[row.tv_id].yahoo_quote_type == "MUTUALFUND"
    assert got[row.tv_id].quote_status == "FRESH_CURRENCY_UNREPORTED"
    db.close()


class OFCagpPreferred:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idValue") == "CAGP" and job.get("micCode") == "XLON":
                out.append([OpenFigiIdentity(
                    "CAGP_FIGI", "CAGP_COMP", "CAGP_SHARE", "CAGP",
                    "LLOYDS BANK PLC", "Preference", "Preference", "LN",
                )])
            else:
                out.append([])
        return out


class YHCagpBond:
    batch_size = 75
    def quotes(self, symbols):
        if "CAGP.L" in symbols:
            return {"CAGP.L": YahooQuote(
                "CAGP.L", "LSE", "London Stock Exchange", "GBP", "BOND",
                "gb_market", "LLOYDS BANK PLC 11 3/4% PERP SUB BDS", None, 177.5, 15,
            )}
        return {}


def test_cagp_bond_conflict_remains_fail_closed(tmp_path):
    db = CacheDB(tmp_path / "cagp-remains-bond.sqlite")
    r = BatchResolver(db, None, OFCagpPreferred(), YHCagpBond())
    row = TvRow(
        "LSE:CAGP", "LSE", "CAGP", "LLOYDS BANK PLC", "GBP",
        "stock", ("preferred",), "Finance", None, 177.5,
    )
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_TYPE_MISMATCH:BOND"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 0
    db.close()


def test_reviewed_mutualfund_diagnostics_report_no_openfigi_identity(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-diagnostic-no-openfigi.sqlite")
    r = BatchResolver(db, None, OFNoReviewedIdentity(), YHReviewedYahooMutualFundTaxonomy())
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    got = r.resolve([row], refresh=True)[row.tv_id]
    assert got.status == "REJECTED"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 0
    assert r.stats["reviewed_yahoo_mutualfund_block_no_openfigi_identity"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_block_LSE_KAKU_no_openfigi_identity"] == 1
    db.close()


def test_reviewed_mutualfund_diagnostics_report_name_mismatch(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-diagnostic-name.sqlite")
    r = BatchResolver(db, None, OFReviewedYahooMutualFundTaxonomy(), YHReviewedYahooMutualFundTaxonomy())
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "UNRELATED ISSUER", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    got = r.resolve([row], refresh=True)[row.tv_id]
    assert got.status == "REJECTED"
    assert r.stats["reviewed_yahoo_mutualfund_block_name_mismatch"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_block_LSE_KAKU_name_mismatch"] == 1
    db.close()


class YHReviewedYahooMutualFundUnexpectedVenue:
    batch_size = 75
    def quotes(self, symbols):
        if "KAKU.L" in symbols:
            return {"KAKU.L": YahooQuote(
                "KAKU.L", "FGI", "Yahoo Index", None, "MUTUALFUND",
                "gb_market", "KAKUZI LD", None, 92.5, 15,
            )}
        return {}


def test_reviewed_yahoo_mutualfund_venue_mismatch_exposes_observed_values(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-venue-observation.sqlite")
    r = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundUnexpectedVenue(),
    )
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    got = r.resolve([row], refresh=True)[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_TYPE_MISMATCH:MUTUALFUND"
    assert r.stats["reviewed_yahoo_mutualfund_block_LSE_KAKU_venue_mismatch"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_venue_LSE_KAKU_exchange_FGI"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_venue_LSE_KAKU_full_exchange_YAHOO_INDEX"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_venue_LSE_KAKU_market_GB_MARKET"] == 1
    db.close()


class YHReviewedYahooMutualFundVenueUnreported:
    batch_size = 75
    def quotes(self, symbols):
        if "KAKU.L" in symbols:
            return {"KAKU.L": YahooQuote(
                "KAKU.L", None, None, None, "MUTUALFUND",
                "gb_market", "KAKUZI LD", None, 92.5, 15,
            )}
        return {}


def test_reviewed_yahoo_mutualfund_venue_unreported_exposes_bounded_tokens(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-venue-unreported-observation.sqlite")
    r = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundVenueUnreported(),
    )
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    got = r.resolve([row], refresh=True)[row.tv_id]
    assert got.status == "REJECTED"
    assert r.stats["reviewed_yahoo_mutualfund_block_LSE_KAKU_venue_unreported"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_venue_LSE_KAKU_exchange_UNREPORTED"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_venue_LSE_KAKU_full_exchange_UNREPORTED"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_venue_LSE_KAKU_market_GB_MARKET"] == 1
    db.close()


class YHReviewedYahooMutualFundSyntheticYHD:
    batch_size = 75
    def quotes(self, symbols):
        out = {}
        rows = {
            "BKM.L": ("BANKMUSCAT (S.A.O.G.)", 3.84),
            "EFGD.L": ("EFG HOLDING S.A.E.", 1.00),
            "KAKU.L": ("KAKUZI LD", 92.50),
            "TGE.L": ("THE GENERATION ESSENTIALS GROUP", 1.30),
        }
        for symbol, (name, price) in rows.items():
            if symbol in symbols:
                out[symbol] = YahooQuote(
                    symbol, "YHD", "YHD", None, "MUTUALFUND",
                    "us_market", name, None, price, 15,
                )
        return out


def test_reviewed_yahoo_mutualfund_accepts_exact_synthetic_yhd_triplet(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-yhd-live-shape.sqlite")
    r = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundSyntheticYHD(),
    )
    rows = [
        TvRow("LSIN:BKM", "LSIN", "BKM", "BANKMUSCAT (S.A.O.G.)", "USD", "dr", ("",), "Finance", 1e9, 3.84),
        TvRow("LSIN:EFGD", "LSIN", "EFGD", "EFG HOLDING S.A.E.", "USD", "dr", ("",), "Finance", 1e9, 1.00),
        TvRow("LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX", "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5),
        TvRow("LSE:TGE", "LSE", "TGE", "THE GENERATION ESSENTIALS GROUP", "USD", "stock", ("common",), "Consumer Services", 4e7, 1.30),
    ]
    got = r.resolve(rows, refresh=True)
    assert all(got[row.tv_id].status == "VERIFIED" for row in rows)
    assert all(got[row.tv_id].yahoo_exchange == "YHD" for row in rows)
    assert all(got[row.tv_id].yahoo_market == "us_market" for row in rows)
    assert all(got[row.tv_id].yahoo_quote_type == "MUTUALFUND" for row in rows)
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] == 4
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 4
    assert r.stats["reviewed_yahoo_mutualfund_currency_unreported_matches"] == 4
    assert r.stats["reviewed_yahoo_mutualfund_yhd_venue_matches"] == 4
    assert r.stats["reviewed_yahoo_mutualfund_block_venue_mismatch"] == 0
    db.close()


class YHReviewedYahooMutualFundNearMissYHD:
    batch_size = 75
    def quotes(self, symbols):
        if "KAKU.L" in symbols:
            return {"KAKU.L": YahooQuote(
                "KAKU.L", "YHD", "YHD", None, "MUTUALFUND",
                "gb_market", "KAKUZI LD", None, 92.5, 15,
            )}
        return {}


def test_reviewed_yahoo_mutualfund_yhd_requires_exact_triplet(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-yhd-near-miss.sqlite")
    r = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundNearMissYHD(),
    )
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    got = r.resolve([row], refresh=True)[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_TYPE_MISMATCH:MUTUALFUND"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 0
    assert r.stats["reviewed_yahoo_mutualfund_block_venue_mismatch"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_yhd_venue_matches"] == 0
    db.close()


def test_reviewed_yahoo_mutualfund_yhd_survives_warm_cache_refresh(tmp_path):
    db = CacheDB(tmp_path / "reviewed-mf-yhd-warm.sqlite")
    row = TvRow(
        "LSE:KAKU", "LSE", "KAKU", "KAKUZI LD", "GBX",
        "stock", ("common",), "Consumer Non-Durables", 1e7, 92.5,
    )
    cold = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundSyntheticYHD(),
    )
    first = cold.resolve([row], refresh=True)[row.tv_id]
    assert first.status == "VERIFIED"
    assert first.yahoo_exchange == "YHD"
    assert first.yahoo_market == "us_market"

    warm = BatchResolver(
        db, None, OFReviewedYahooMutualFundTaxonomy(),
        YHReviewedYahooMutualFundSyntheticYHD(),
    )
    got = warm.resolve([row])
    assert got[row.tv_id].status == "VERIFIED"
    assert got[row.tv_id].cache_hit is True
    warm.refresh_cached_quotes(got)
    assert got[row.tv_id].status == "VERIFIED"
    assert got[row.tv_id].yahoo_exchange == "YHD"
    assert got[row.tv_id].yahoo_market == "us_market"
    assert got[row.tv_id].yahoo_quote_type == "MUTUALFUND"
    assert got[row.tv_id].quote_status == "FRESH_CURRENCY_UNREPORTED"
    db.close()



def test_policy49_reuses_policy44_verified_cache_entries(tmp_path):
    import time
    from tv_market_identity.models import Binding

    db = CacheDB(tmp_path / "compatible-policy-cache.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="XETR:DTE", tv_symbol="DTE", tv_prefix="XETR",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="DTE.DE", yahoo_exchange="GER", yahoo_market="de_market",
        yahoo_quote_type="EQUITY", yahoo_currency="EUR", resolved_mic="XETR",
        source_mic="XETR", target_mic="XETR", mapping_method="SAME_VENUE",
        resolver_version="0.3.44-policy44", validated_at=now,
        expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    row = TvRow(
        "XETR:DTE", "XETR", "DTE", "Deutsche Telekom AG", "EUR",
        "stock", ("common",), None, 1e11, 29.0,
    )
    binding = resolver.resolve([row])[row.tv_id]
    assert binding.status == "VERIFIED"
    assert binding.cache_hit is True
    assert binding.resolver_version == "0.3.44-policy44"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    assert resolver.stats["cache_hits"] == 1
    assert resolver.stats["cache_misses"] == 0
    db.close()

class FHPreferredIncomplete:
    def us_symbols(self):
        return [
            {"symbol":"BMNP","displaySymbol":"BMNP","description":"PREFERRED","currency":"USD","type":"PUBLIC","mic":"XNYS","figi":"FH_BMNP","shareClassFIGI":None},
            {"symbol":"SOJE","displaySymbol":"SOJE","description":"PREFERRED","currency":"USD","type":"?","mic":"XNYS","figi":"FH_SOJE","shareClassFIGI":None},
            {"symbol":"NASP","displaySymbol":"NASP","description":"PREFERRED","currency":"USD","type":"PUBLIC","mic":"XNAS","figi":"FH_NASP","shareClassFIGI":None},
        ]


class OFPreferredSameVenue:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("micCode") == "XNYS":
                out.append([OpenFigiIdentity(
                    figi="OF_" + job["idValue"], composite_figi="COMP", share_class_figi=None,
                    ticker="PREF", name="PREFERRED", security_type="PUBLIC",
                    security_type2="Preferred Stock", exch_code="US",
                )])
            else:
                out.append([])
        return out


class YHPreferredSameVenue:
    batch_size = 75
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        if isin == "US0000000001":
            return [YahooSearchCandidate("BMNP", "NYQ", "EQUITY", None, None)]
        return []

    def quotes(self, symbols):
        out = {}
        for symbol in symbols:
            if symbol in {"BMNP", "SOJE", "NASP"}:
                out[symbol] = YahooQuote(symbol, "NYQ" if symbol != "NASP" else "NMS", "NYSE" if symbol != "NASP" else "NasdaqGS", "USD", "EQUITY", "us_market", None, None, 25.0, 0)
        return out


def test_us_preferred_same_venue_exact_isin_yahoo_admission(tmp_path):
    db = CacheDB(tmp_path / "pref_isin.sqlite")
    r = BatchResolver(db, FHPreferredIncomplete(), OFPreferredSameVenue(), YHPreferredSameVenue())
    row = TvRow("NYSE:BMNP", "NYSE", "BMNP", None, "USD", "stock", ("preferred",), None, None, 25.0, "US0000000001")
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_PREFERRED_SAME_VENUE_EXACT_ISIN_YAHOO"
    assert got.source_mic == got.target_mic == "XNYS"
    assert got.source_venue_figi == got.target_venue_figi == "OF_US0000000001"
    assert got.share_class_figi is None
    db.close()


def test_us_preferred_same_venue_exact_tv_symbol_fallback_admission(tmp_path):
    db = CacheDB(tmp_path / "pref_tv.sqlite")
    r = BatchResolver(db, FHPreferredIncomplete(), OFPreferredSameVenue(), YHPreferredSameVenue())
    row = TvRow("NYSE:SOJE", "NYSE", "SOJE", None, "USD", "stock", ("preferred",), None, None, 25.0, "US0000000002")
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "SOJE"
    assert got.mapping_method == "US_PREFERRED_SAME_VENUE_EXACT_TV_SYMBOL"
    assert got.share_class_figi is None
    db.close()


def test_us_preferred_same_venue_requires_source_isin_mic_proof(tmp_path):
    db = CacheDB(tmp_path / "pref_fail.sqlite")
    r = BatchResolver(db, FHPreferredIncomplete(), OFPreferredSameVenue(), YHPreferredSameVenue())
    row = TvRow("NASDAQ:NASP", "NASDAQ", "NASP", None, "USD", "stock", ("preferred",), None, None, 25.0, "US0000000003")
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:PUBLIC"
    db.close()

class FHOTCPreferredIncomplete:
    def us_symbols(self):
        return [
            {"symbol":"OTCP","displaySymbol":"OTCP","description":"PREFERRED","currency":"USD","type":"?","mic":"OOTC","figi":"FH_OTCP","shareClassFIGI":None},
            {"symbol":"PINKP","displaySymbol":"PINKP","description":"PREFERRED","currency":"USD","type":"?","mic":"OOTC","figi":"FH_PINKP","shareClassFIGI":None},
            {"symbol":"CROSSF","displaySymbol":"CROSSF","description":"PREFERRED","currency":"USD","type":"?","mic":"OOTC","figi":"FH_CROSSF","shareClassFIGI":None},
            {"symbol":"AMBPF","displaySymbol":"AMBPF","description":"PREFERRED","currency":"USD","type":"?","mic":"OOTC","figi":"FH_AMBPF","shareClassFIGI":None},
        ]

class OFOTCPreferredDiscovery:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for job in jobs:
            isin=job.get("idValue"); mic=job.get("micCode")
            matched = mic == "OOTC" or (isin == "US0000000014" and mic == "OTCM")
            if matched:
                out.append([OpenFigiIdentity(
                    figi=f"OF_{isin}_{mic}", composite_figi="COMP", share_class_figi=None,
                    ticker="PREF", name="PREFERRED", security_type="PUBLIC",
                    security_type2="Preferred Stock", exch_code="US")])
            else:
                out.append([])
        return out

class YHOTCPreferred:
    batch_size=75
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        symbols={
            "US0000000011":("OTCP","OQB"),
            "US0000000012":("PINKP","PNK"),
            "US0000000013":("HOME.TO","TOR"),
            "US0000000014":("AMBPF","OQB"),
        }
        v=symbols.get(isin)
        return [YahooSearchCandidate(v[0],v[1],"EQUITY",None,None)] if v else []
    def quotes(self, symbols):
        out={}
        for symbol in symbols:
            if symbol == "OTCP":
                out[symbol]=YahooQuote(symbol,"OQB","OTC Markets OTCQB","USD","EQUITY","us_market",None,None,25.0,0)
            elif symbol == "PINKP":
                out[symbol]=YahooQuote(symbol,"PNK","OTC Markets OTCPK","USD","EQUITY","us_market",None,None,25.0,0)
            elif symbol == "HOME.TO":
                out[symbol]=YahooQuote(symbol,"TOR","Toronto","USD","EQUITY","ca_market",None,None,25.0,0)
            elif symbol == "AMBPF":
                out[symbol]=YahooQuote(symbol,"OQB","OTC Markets OTCQB","USD","EQUITY","us_market",None,None,25.0,0)
        return out


def test_us_otc_preferred_unique_ootc_oqb_admission(tmp_path):
    db=CacheDB(tmp_path/"otc_oqb.sqlite")
    r=BatchResolver(db,FHOTCPreferredIncomplete(),OFOTCPreferredDiscovery(),YHOTCPreferred())
    row=TvRow("OTC:OTCP","OTC","OTCP",None,"USD","stock",("preferred",),None,None,25.0,"US0000000011")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_OTC_PREFERRED_EXACT_ISIN_SAME_LISTING"
    assert got.source_mic == got.target_mic == "OOTC"
    assert got.yahoo_symbol == "OTCP"
    assert got.share_class_figi is None
    db.close()


def test_us_otc_preferred_unique_ootc_pnk_admission(tmp_path):
    db=CacheDB(tmp_path/"otc_pnk.sqlite")
    r=BatchResolver(db,FHOTCPreferredIncomplete(),OFOTCPreferredDiscovery(),YHOTCPreferred())
    row=TvRow("OTC:PINKP","OTC","PINKP",None,"USD","stock",("preferred",),None,None,25.0,"US0000000012")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "PINKP"
    db.close()


def test_us_otc_preferred_cross_market_yahoo_remains_rejected(tmp_path):
    db=CacheDB(tmp_path/"otc_cross.sqlite")
    r=BatchResolver(db,FHOTCPreferredIncomplete(),OFOTCPreferredDiscovery(),YHOTCPreferred())
    row=TvRow("OTC:CROSSF","OTC","CROSSF",None,"USD","stock",("preferred",),None,None,25.0,"US0000000013")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:?"
    db.close()


def test_us_otc_preferred_multiple_proven_mics_remains_rejected(tmp_path):
    db=CacheDB(tmp_path/"otc_amb.sqlite")
    r=BatchResolver(db,FHOTCPreferredIncomplete(),OFOTCPreferredDiscovery(),YHOTCPreferred())
    row=TvRow("OTC:AMBPF","OTC","AMBPF",None,"USD","stock",("preferred",),None,None,25.0,"US0000000014")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:?"
    db.close()

class FHNYSESlashPreferred:
    def us_symbols(self):
        return []

class OFNYSESlashPreferred:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        return [[OpenFigiIdentity(figi="OF_" + j["idValue"], composite_figi=None, share_class_figi=None, ticker="PSA", name="Preferred", security_type="PUBLIC", security_type2="Preferred Stock", exch_code="US")] for j in jobs]

class YHNYSESlashPreferred:
    def __init__(self, candidate="PSA-PU", exchange="NYQ", full="NYSE", currency="USD", qtype="EQUITY"):
        self.candidate, self.exchange, self.full, self.currency, self.qtype = candidate, exchange, full, currency, qtype
    def search_exact_isin(self, isin):
        from tv_market_identity.models import YahooSearchCandidate
        return [YahooSearchCandidate(self.candidate, self.exchange, self.qtype, None, None)]
    def quotes(self, symbols):
        return {s: YahooQuote(s, self.exchange, self.full, self.currency, self.qtype, "us_market", None, None, 25.0, 0) for s in symbols}

def _run_nyse_slash_rescue(tmp_path, yahoo, reason="YAHOO_SYMBOL_NOT_FOUND", tv_symbol="PSA/PU"):
    db = CacheDB(tmp_path / "slash.sqlite")
    r = BatchResolver(db, FHNYSESlashPreferred(), OFNYSESlashPreferred(), yahoo)
    row = TvRow("NYSE:" + tv_symbol, "NYSE", tv_symbol, None, "USD", "stock", ("preferred",), None, None, 25.0, "US74460W3622")
    # Test the rescue directly so the fixture precisely controls the prior rejection class.
    initial = [Binding(tv_id=row.tv_id, tv_symbol=row.symbol, tv_prefix=row.prefix, tv_currency=row.currency, tv_type=row.tv_type, status="REJECTED", rejection_reason=reason)]
    got = r._us_nyse_preferred_exact_isin_symbol_rescue([row], initial)[0]
    db.close()
    return got

def test_v077_nyse_slash_preferred_exact_isin_symbol_rescue(tmp_path):
    got = _run_nyse_slash_rescue(tmp_path, YHNYSESlashPreferred())
    assert got.status == "VERIFIED"
    assert got.yahoo_symbol == "PSA-PU"
    assert got.mapping_method == "US_NYSE_PREFERRED_EXACT_ISIN_SYMBOL"
    assert got.source_mic == got.target_mic == "XNYS"

def test_v077_nyse_slash_preferred_rescues_prior_yahoo_mutualfund_rejection(tmp_path):
    got = _run_nyse_slash_rescue(tmp_path, YHNYSESlashPreferred(candidate="TDS-PU"), "YAHOO_TYPE_MISMATCH:MUTUALFUND", "TDS/PU")
    assert got.status == "VERIFIED"

def test_v077_nyse_slash_preferred_rejects_cross_market_exact_isin(tmp_path):
    got = _run_nyse_slash_rescue(tmp_path, YHNYSESlashPreferred(candidate="PUP0.F", exchange="FRA", full="Frankfurt", currency="EUR"))
    assert got.status == "REJECTED"

def test_v077_nyse_slash_preferred_rejects_noncorrelated_yahoo_symbol(tmp_path):
    got = _run_nyse_slash_rescue(tmp_path, YHNYSESlashPreferred(candidate="OTHER-PU"))
    assert got.status == "REJECTED"

class FHUnitV079:
    def us_symbols(self):
        return [
            {"symbol":"FUNDU","displaySymbol":"FUNDU","description":"FUND UNIT","currency":"USD","type":"Unit","mic":"XNYS","figi":"FH_FUNDU","shareClassFIGI":"SC1"},
            {"symbol":"NASU","displaySymbol":"NASU","description":"NASDAQ UNIT","currency":"USD","type":"Unit","mic":"XNAS","figi":"FH_NASU","shareClassFIGI":"SC2"},
            {"symbol":"STKU","displaySymbol":"STKU","description":"STOCK UNIT","currency":"USD","type":"Unit","mic":"XNYS","figi":"FH_STKU","shareClassFIGI":"SC3"},
            {"symbol":"BADU","displaySymbol":"BADU","description":"BAD UNIT","currency":"USD","type":"Unit","mic":"XNYS","figi":"FH_BADU","shareClassFIGI":"SC4"},
        ]

class OFUnitV079:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for job in jobs:
            isin=job.get("idValue")
            mic=job.get("micCode")
            shares={"US0000000101":"SC1","US0000000102":"SC2","US0000000103":"SC3","US0000000104":"SC4"}
            sc=shares.get(isin)
            if not sc:
                out.append([]); continue
            if isin == "US0000000102" and mic == "XNAS":
                out.append([]); continue
            if isin == "US0000000104" and mic == "XNYS":
                sc="DIFFERENT"
            tickers={"US0000000101":"FUNDU","US0000000102":"NASU","US0000000103":"STKU","US0000000104":"BADU"}
            out.append([OpenFigiIdentity(
                figi=f"OF_{isin}_{mic or 'ALL'}", composite_figi=f"COMP_{isin}",
                share_class_figi=sc, ticker=tickers.get(isin, "UNIT"), name="UNIT TEST",
                security_type="Unit", security_type2="Unit", exch_code="US",
            )])
        return out

class YHUnitV079:
    batch_size = 75
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        symbols={"US0000000101":"FUNDU","US0000000102":"NASU","US0000000103":"STKU","US0000000104":"BADU"}
        s=symbols.get(isin)
        return [YahooSearchCandidate(s, "NYQ" if s != "NASU" else "NMS", "EQUITY", None, None)] if s else []
    def quotes(self, symbols):
        return {s: YahooQuote(s, "NMS" if s == "NASU" else "NYQ", "NasdaqGS" if s == "NASU" else "NYSE", "USD", "EQUITY", "us_market", None, None, 10.0, 0) for s in symbols}


def test_v079_xnys_fund_unit_exact_isin_admission(tmp_path):
    db=CacheDB(tmp_path / "v079-unit.sqlite")
    r=BatchResolver(db, FHUnitV079(), OFUnitV079(), YHUnitV079())
    row=TvRow("NYSE:FUNDU", "NYSE", "FUNDU", None, "USD", "fund", ("unit",), None, None, 10.0, "US0000000101")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNYS_FUND_UNIT_EXACT_ISIN"
    assert got.source_mic == got.target_mic == "XNYS"
    assert got.share_class_figi == "SC1"
    assert r.stats["us_xnys_fund_unit_source_proven"] == 1
    assert r.stats["us_xnys_fund_unit_rescue_matches"] == 1
    db.close()


def test_v079_xnys_rule_itself_does_not_claim_xnas(tmp_path):
    # v0.3.81 adds a separate audited XNAS rule; the original XNYS rule must
    # still not be the path that admits this row.
    db=CacheDB(tmp_path / "v079-xnas.sqlite")
    r=BatchResolver(db, FHUnitV079(), OFUnitV079(), YHUnitV079())
    row=TvRow("NASDAQ:NASU", "NASDAQ", "NASU", None, "USD", "fund", ("unit",), None, None, 10.0, "US0000000102")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNAS_FUND_UNIT_EXACT_ISIN"
    assert r.stats["us_xnys_fund_unit_rescue_matches"] == 0
    db.close()


def test_v079_unit_does_not_generalize_to_stock_common_without_v0415_share_class(tmp_path):
    # v0.4.15 deliberately adds a narrow XNYS stock/common Unit rescue. Keep
    # the historical non-generalization regression as a negative control that
    # falls outside the new contract: source evidence has no shareClassFIGI.
    class OFUnitNoShareV079(OFUnitV079):
        def map_jobs(self, jobs):
            mapped = super().map_jobs(jobs)
            out = []
            for identities in mapped:
                out.append([type(i)(
                    figi=i.figi, composite_figi=i.composite_figi,
                    share_class_figi=None, ticker=i.ticker, name=i.name,
                    security_type=i.security_type, security_type2=i.security_type2,
                    exch_code=i.exch_code,
                ) for i in identities])
            return out

    db=CacheDB(tmp_path / "v079-stock.sqlite")
    r=BatchResolver(db, FHUnitV079(), OFUnitNoShareV079(), YHUnitV079())
    row=TvRow("NYSE:STKU", "NYSE", "STKU", None, "USD", "stock", ("common",), None, None, 10.0, "US0000000103")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:Unit"
    assert r.stats["us_xnys_stock_common_unit_source_unconfirmed"] == 1
    db.close()


def test_v079_xnys_fund_unit_requires_matching_share_class(tmp_path):
    db=CacheDB(tmp_path / "v079-share.sqlite")
    r=BatchResolver(db, FHUnitV079(), OFUnitV079(), YHUnitV079())
    row=TvRow("NYSE:BADU", "NYSE", "BADU", None, "USD", "fund", ("unit",), None, None, 10.0, "US0000000104")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:Unit"
    assert r.stats["us_xnys_fund_unit_source_unconfirmed"] == 1
    db.close()

# v0.3.81: the v0.3.80 diagnostic established a homogeneous 146-row XNAS
# fund/unit provider-gap cohort.  These tests keep the rescue narrow.
def test_v081_xnas_fund_unit_exact_isin_admission(tmp_path):
    db=CacheDB(tmp_path / "v081-xnas-unit.sqlite")
    r=BatchResolver(db, FHUnitV079(), OFUnitV079(), YHUnitV079())
    row=TvRow("NASDAQ:NASU", "NASDAQ", "NASU", None, "USD", "fund", ("unit",), None, None, 10.0, "US0000000102")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNAS_FUND_UNIT_EXACT_ISIN"
    assert got.source_mic == got.target_mic == "XNAS"
    assert got.share_class_figi == "SC2"
    assert r.stats["us_xnas_fund_unit_identity_proven"] == 1
    assert r.stats["us_xnas_fund_unit_rescue_matches"] == 1
    db.close()


def test_v081_xnas_unit_does_not_generalize_to_stock_common(tmp_path):
    db=CacheDB(tmp_path / "v081-xnas-stock.sqlite")
    r=BatchResolver(db, FHUnitV079(), OFUnitV079(), YHUnitV079())
    row=TvRow("NASDAQ:NASU", "NASDAQ", "NASU", None, "USD", "stock", ("common",), None, None, 10.0, "US0000000102")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:Unit"
    assert r.stats["us_xnas_fund_unit_rescue_matches"] == 0
    db.close()


class YHUnitV081WrongSymbol(YHUnitV079):
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        if isin == "US0000000102":
            return [YahooSearchCandidate("OTHERU", "NMS", "EQUITY", None, None)]
        return super().search_exact_isin(isin, max_results)
    def quotes(self, symbols):
        return {s: YahooQuote(s, "NMS", "NasdaqGS", "USD", "EQUITY", "us_market", None, None, 10.0, 0) for s in symbols}


def test_v081_xnas_fund_unit_requires_exact_yahoo_symbol(tmp_path):
    db=CacheDB(tmp_path / "v081-xnas-symbol.sqlite")
    r=BatchResolver(db, FHUnitV079(), OFUnitV079(), YHUnitV081WrongSymbol())
    row=TvRow("NASDAQ:NASU", "NASDAQ", "NASU", None, "USD", "fund", ("unit",), None, None, 10.0, "US0000000102")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:Unit"
    assert r.stats["us_xnas_fund_unit_yahoo_unconfirmed"] == 1
    db.close()


class OFUnitV081ScopedConflict(OFUnitV079):
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=super().map_jobs(jobs)
        for i, job in enumerate(jobs):
            if job.get("idValue") == "US0000000102" and job.get("micCode") == "XNAS":
                out[i]=[OpenFigiIdentity(figi="CONFLICT", composite_figi="CONFLICT", share_class_figi="SC2", ticker="NASU", name="NASDAQ UNIT", security_type="Unit", security_type2="Unit", exch_code="US")]
        return out


def test_v081_xnas_fund_unit_requires_scoped_no_match_pattern(tmp_path):
    db=CacheDB(tmp_path / "v081-xnas-scoped.sqlite")
    r=BatchResolver(db, FHUnitV079(), OFUnitV081ScopedConflict(), YHUnitV079())
    row=TvRow("NASDAQ:NASU", "NASDAQ", "NASU", None, "USD", "fund", ("unit",), None, None, 10.0, "US0000000102")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:Unit"
    assert r.stats["us_xnas_fund_unit_identity_unconfirmed"] == 1
    db.close()

# v0.3.84: six audited NYSE fund/unit PUBLIC rows have direct same-venue proof.
class FHPublicV084:
    batch_size = 100
    def us_symbols(self):
        return [
            {"symbol":"PUBU","displaySymbol":"PUBU","description":"PUBLIC UNIT","currency":"USD","type":"PUBLIC","mic":"XNYS","figi":"FH_PUBU"},
            {"symbol":"PREF","displaySymbol":"PREF","description":"PREFERRED","currency":"USD","type":"PUBLIC","mic":"XNYS","figi":"FH_PREF"},
        ]

class OFPublicV084:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for job in jobs:
            isin=job.get("idValue"); mic=job.get("micCode")
            if isin == "US0000000841" and mic == "XNYS":
                out.append([OpenFigiIdentity("OF_PUBU", "COMP", None, "PUBU", "PUBLIC UNIT", "PUBLIC", "Preferred Stock", "US")])
            elif isin == "US0000000842" and mic == "XNYS":
                out.append([OpenFigiIdentity("OF_PREF", "COMP2", None, "PREF", "PREFERRED", "PUBLIC", "Preferred Stock", "US")])
            else:
                out.append([])
        return out

class YHPublicV084:
    batch_size = 75
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        s={"US0000000841":"PUBU","US0000000842":"PREF"}.get(isin)
        return [YahooSearchCandidate(s, "NYQ", "EQUITY", None, None)] if s else []
    def quotes(self, symbols):
        return {s: YahooQuote(s, "NYQ", "NYSE", "USD", "EQUITY", "us_market", None, None, 10.0, 0) for s in symbols}

def test_v084_xnys_fund_unit_public_exact_isin_admission(tmp_path):
    db=CacheDB(tmp_path / "v084-public.sqlite")
    r=BatchResolver(db, FHPublicV084(), OFPublicV084(), YHPublicV084())
    row=TvRow("NYSE:PUBU", "NYSE", "PUBU", None, "USD", "fund", ("unit",), None, None, 10.0, "US0000000841")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNYS_FUND_UNIT_PUBLIC_EXACT_ISIN"
    assert got.source_mic == got.target_mic == "XNYS"
    assert got.share_class_figi is None
    assert r.stats["us_xnys_fund_unit_public_source_proven"] == 1
    assert r.stats["us_xnys_fund_unit_public_rescue_matches"] == 1
    db.close()

def test_v084_public_rule_does_not_generalize_to_stock_preferred(tmp_path):
    db=CacheDB(tmp_path / "v084-public-preferred.sqlite")
    r=BatchResolver(db, FHPublicV084(), OFPublicV084(), YHPublicV084())
    row=TvRow("NYSE:PREF", "NYSE", "PREF", None, "USD", "stock", ("preferred",), None, None, 10.0, "US0000000842")
    got=r.resolve([row])[row.tv_id]
    # Existing preferred same-venue path is allowed to admit this independently;
    # the new fund/unit PUBLIC method must never be the admission route.
    assert got.mapping_method != "US_XNYS_FUND_UNIT_PUBLIC_EXACT_ISIN"
    assert r.stats["us_xnys_fund_unit_public_rescue_matches"] == 0
    db.close()

def test_v084_public_rule_does_not_claim_xnas(tmp_path):
    db=CacheDB(tmp_path / "v084-public-xnas.sqlite")
    r=BatchResolver(db, FHPublicV084(), OFPublicV084(), YHPublicV084())
    row=TvRow("NASDAQ:PUBU", "NASDAQ", "PUBU", None, "USD", "fund", ("unit",), None, None, 10.0, "US0000000841")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:PUBLIC"
    assert r.stats["us_xnys_fund_unit_public_rescue_matches"] == 0
    db.close()

# v0.3.87: audited OOTC preferred rows with empty Finnhub type and PUBLIC source proof.
class FHEmptyOOTCV087:
    batch_size = 100
    def us_symbols(self):
        return [{"symbol":"EPREF","displaySymbol":"EPREF","description":"EMPTY TYPE PREF","currency":"USD","type":"","mic":"OOTC","figi":"FH_EPREF"}]

class OFEmptyOOTCV087:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for job in jobs:
            if job.get("idValue") == "US0000000871" and job.get("micCode") == "OOTC":
                out.append([OpenFigiIdentity("OF_EPREF","COMP",None,"EPREF","EMPTY TYPE PREF","PUBLIC","Preferred Stock","US")])
            else:
                out.append([])
        return out

class YHEmptyOOTCV087:
    batch_size = 75
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        return [YahooSearchCandidate("EPREF","OID","EQUITY",None,None)] if isin == "US0000000871" else []
    def quotes(self, symbols):
        return {s: YahooQuote(s,"OID","OTC Markets OTCID","USD","EQUITY","us_market",None,None,10.0,0) for s in symbols}

def test_v087_ootc_preferred_empty_type_public_exact_isin_admission(tmp_path):
    db=CacheDB(tmp_path / "v087-ootc-empty.sqlite")
    r=BatchResolver(db,FHEmptyOOTCV087(),OFEmptyOOTCV087(),YHEmptyOOTCV087())
    row=TvRow("OTC:EPREF","OTC","EPREF",None,"USD","stock",("preferred",),None,None,10.0,"US0000000871")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_OOTC_PREFERRED_FINNHUB_EMPTY_TYPE_EXACT_ISIN"
    assert got.source_mic == got.target_mic == "OOTC"
    assert got.share_class_figi is None
    assert r.stats["us_ootc_preferred_empty_type_finnhub_source_proven"] == 1
    assert r.stats["us_ootc_preferred_empty_type_openfigi_source_proven"] == 1
    assert r.stats["us_ootc_preferred_empty_type_rescue_matches"] == 1
    db.close()

class OFPrivateOOTCV087(OFEmptyOOTCV087):
    def map_jobs(self,jobs):
        from tv_market_identity.models import OpenFigiIdentity
        return [[OpenFigiIdentity("OF_EPREF","COMP",None,"ES 4.5 PERP 1963","EMPTY TYPE PREF","PRIVATE","Preferred Stock","OTC US")] if j.get("micCode") == "OOTC" else [] for j in jobs]

def test_v432_ootc_empty_type_private_preferred_same_source_rescued(tmp_path):
    db=CacheDB(tmp_path / "v432-private.sqlite")
    r=BatchResolver(db,FHEmptyOOTCV087(),OFPrivateOOTCV087(),YHEmptyOOTCV087())
    row=TvRow("OTC:EPREF","OTC","EPREF",None,"USD","stock",("preferred",),None,None,10.0,"US0000000871")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_OOTC_STOCK_PREFERRED_FINNHUB_UNKNOWN_TYPE_EXACT_ISIN"
    db.close()

def test_v087_ootc_empty_type_common_stays_rejected(tmp_path):
    db=CacheDB(tmp_path / "v087-common.sqlite")
    r=BatchResolver(db,FHEmptyOOTCV087(),OFEmptyOOTCV087(),YHEmptyOOTCV087())
    row=TvRow("OTC:EPREF","OTC","EPREF",None,"USD","stock",("common",),None,None,10.0,"US0000000871")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "REJECTED"
    assert r.stats["us_ootc_preferred_empty_type_rescue_matches"] == 0
    db.close()

# v0.3.95: audited NYSE stock/common Royalty Trust exact-ISIN rescue.
class FHRoyaltyV095:
    batch_size = 100
    def us_symbols(self):
        return [
            {"symbol":"SJT","displaySymbol":"SJT","description":"ROYALTY TRUST","currency":"USD","type":"Royalty Trst","mic":"XNYS","figi":"FH_SJT"},
            {"symbol":"MARPS","displaySymbol":"MARPS","description":"ROYALTY TRUST","currency":"USD","type":"Royalty Trst","mic":"XNAS","figi":"FH_MARPS"},
            {"symbol":"ROYTL","displaySymbol":"ROYTL","description":"ROYALTY TRUST","currency":"USD","type":"Royalty Trst","mic":"OOTC","figi":"FH_ROYTL"},
            {"symbol":"OTHER","displaySymbol":"OTHER","description":"OTHER","currency":"USD","type":"Common Stock","mic":"XNYS","figi":"FH_OTHER"},
        ]

class OFRoyaltyV095:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for j in jobs:
            isin=j.get("idValue"); mic=j.get("micCode")
            if isin == "US0000000951" and mic == "XNYS":
                out.append([OpenFigiIdentity("OF_SJT","COMP",None,"SJT","TRUST","Royalty Trst","Common Stock","US")])
            else:
                out.append([])
        return out

class YHRoyaltyV095:
    batch_size = 75
    def __init__(self, symbol="SJT", exchange="NYQ"):
        self.symbol=symbol; self.exchange=exchange
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        if isin != "US0000000951": return []
        return [YahooSearchCandidate(self.symbol, self.exchange, "EQUITY", None, None)]
    def quotes(self, symbols):
        return {s: YahooQuote(s, self.exchange, "NYSE" if self.exchange=="NYQ" else "Nasdaq", "USD", "EQUITY", "us_market", None, None, 10.0, 0) for s in symbols}

def test_v095_xnys_stock_common_royalty_trust_admission(tmp_path):
    db=CacheDB(tmp_path / "v095-royalty.sqlite")
    r=BatchResolver(db, FHRoyaltyV095(), OFRoyaltyV095(), YHRoyaltyV095())
    row=TvRow("NYSE:SJT","NYSE","SJT",None,"USD","stock",("common",),None,None,10.0,"US0000000951")
    got=r.resolve([row])[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNYS_STOCK_COMMON_ROYALTY_TRUST_EXACT_ISIN"
    assert got.source_mic == got.target_mic == "XNYS"
    assert r.stats["us_xnys_stock_common_royalty_trust_source_proven"] == 1
    assert r.stats["us_xnys_stock_common_royalty_trust_rescue_matches"] == 1
    db.close()

def test_v095_royalty_rule_does_not_claim_xnas_or_otc(tmp_path):
    for prefix, symbol, isin in [("NASDAQ","MARPS","US0000000952"),("OTC","ROYTL","US0000000953")]:
        db=CacheDB(tmp_path / f"v095-{symbol}.sqlite")
        r=BatchResolver(db, FHRoyaltyV095(), OFRoyaltyV095(), YHRoyaltyV095())
        row=TvRow(f"{prefix}:{symbol}",prefix,symbol,None,"USD","stock",("common",),None,None,10.0,isin)
        got=r.resolve([row])[row.tv_id]
        assert got.status == "REJECTED"
        assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:Royalty Trst"
        assert r.stats["us_xnys_stock_common_royalty_trust_rescue_matches"] == 0
        db.close()

def test_v095_royalty_rule_requires_exact_yahoo_symbol_and_venue(tmp_path):
    for symbol, exchange in [("SJT-X","NYQ"),("SJT","NMS")]:
        db=CacheDB(tmp_path / f"v095-yahoo-{symbol}-{exchange}.sqlite")
        r=BatchResolver(db, FHRoyaltyV095(), OFRoyaltyV095(), YHRoyaltyV095(symbol,exchange))
        row=TvRow("NYSE:SJT","NYSE","SJT",None,"USD","stock",("common",),None,None,10.0,"US0000000951")
        got=r.resolve([row])[row.tv_id]
        assert got.status == "REJECTED"
        assert r.stats["us_xnys_stock_common_royalty_trust_rescue_matches"] == 0
        db.close()

def test_v095_royalty_rule_does_not_claim_non_royalty_taxonomy(tmp_path):
    db=CacheDB(tmp_path / "v095-other.sqlite")
    r=BatchResolver(db, FHRoyaltyV095(), OFRoyaltyV095(), YHRoyaltyV095())
    row=TvRow("NYSE:OTHER","NYSE","OTHER",None,"USD","stock",("common",),None,None,10.0,"US0000000954")
    got=r.resolve([row])[row.tv_id]
    assert got.mapping_method != "US_XNYS_STOCK_COMMON_ROYALTY_TRUST_EXACT_ISIN"
    assert r.stats["us_xnys_stock_common_royalty_trust_rescue_matches"] == 0
    db.close()

# v0.3.97: audited NYSE stock/common Ltd Part exact-ISIN rescue.
class FHLtdPartV097:
    batch_size = 100
    def us_symbols(self):
        return [
            {"symbol":"TXO","displaySymbol":"TXO","description":"PARTNERSHIP","currency":"USD","type":"Ltd Part","mic":"XNYS","figi":"FH_TXO"},
            {"symbol":"PAGP","displaySymbol":"PAGP","description":"PARTNERSHIP","currency":"USD","type":"Ltd Part","mic":"XNAS","figi":"FH_PAGP"},
        ]

class OFLtdPartV097:
    batch_size = 100
    def __init__(self, share=True, st2="Partnership Shares", ticker="TXO"):
        self.share=share; self.st2=st2; self.ticker=ticker
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for j in jobs:
            if j.get("idValue") == "US0000000971" and j.get("micCode") == "XNYS":
                out.append([OpenFigiIdentity(figi="OF_TXO", composite_figi=None, share_class_figi="SC_TXO" if self.share else None, ticker=self.ticker, name="PARTNERSHIP", security_type="Ltd Part", security_type2=self.st2, exch_code="US")])
            else: out.append([])
        return out

class YHLtdPartV097:
    batch_size = 75
    def __init__(self, symbol="TXO", exchange="NYQ", currency="USD", count=1):
        self.symbol=symbol; self.exchange=exchange; self.currency=currency; self.count=count
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        if isin != "US0000000971": return []
        return [YahooSearchCandidate(self.symbol, self.exchange, "EQUITY", None, None) for _ in range(self.count)]
    def quotes(self, symbols):
        return {s: YahooQuote(s,self.exchange,"NYSE" if self.exchange=="NYQ" else "Nasdaq",self.currency,"EQUITY","us_market",None,None,10.0,0) for s in symbols}

def _v097_row(prefix="NYSE", symbol="TXO", isin="US0000000971"):
    return TvRow(f"{prefix}:{symbol}",prefix,symbol,None,"USD","stock",("common",),None,None,10.0,isin)

def test_v097_xnys_stock_common_ltd_part_admission(tmp_path):
    db=CacheDB(tmp_path / "v097-ltd.sqlite")
    r=BatchResolver(db,FHLtdPartV097(),OFLtdPartV097(),YHLtdPartV097())
    got=r.resolve([_v097_row()])["NYSE:TXO"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNYS_STOCK_COMMON_LTD_PART_EXACT_ISIN"
    assert got.source_mic == got.target_mic == "XNYS"
    assert r.stats["us_xnys_stock_common_ltd_part_source_proven"] == 1
    assert r.stats["us_xnys_stock_common_ltd_part_rescue_matches"] == 1
    db.close()

def test_v097_ltd_part_rule_does_not_claim_xnas(tmp_path):
    db=CacheDB(tmp_path / "v097-xnas.sqlite")
    r=BatchResolver(db,FHLtdPartV097(),OFLtdPartV097(),YHLtdPartV097())
    got=r.resolve([_v097_row("NASDAQ","PAGP","US0000000972")])["NASDAQ:PAGP"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:Ltd Part"
    assert r.stats["us_xnys_stock_common_ltd_part_rescue_matches"] == 0
    db.close()

def test_v097_ltd_part_requires_shareclass_and_partnership_taxonomy(tmp_path):
    for of in [OFLtdPartV097(share=False), OFLtdPartV097(st2="Common Stock"), OFLtdPartV097(ticker="TXO-X")]:
        db=CacheDB(tmp_path / f"v097-of-{id(of)}.sqlite")
        r=BatchResolver(db,FHLtdPartV097(),of,YHLtdPartV097())
        got=r.resolve([_v097_row()])["NYSE:TXO"]
        assert got.status == "REJECTED"
        assert r.stats["us_xnys_stock_common_ltd_part_rescue_matches"] == 0
        db.close()

def test_v097_ltd_part_requires_unique_exact_yahoo_source_route(tmp_path):
    for yh in [YHLtdPartV097(symbol="TXO-X"),YHLtdPartV097(exchange="NMS"),YHLtdPartV097(currency="CAD"),YHLtdPartV097(count=2)]:
        db=CacheDB(tmp_path / f"v097-yh-{id(yh)}.sqlite")
        r=BatchResolver(db,FHLtdPartV097(),OFLtdPartV097(),yh)
        got=r.resolve([_v097_row()])["NYSE:TXO"]
        assert got.status == "REJECTED"
        assert r.stats["us_xnys_stock_common_ltd_part_rescue_matches"] == 0
        db.close()

# v0.3.99: audited NYSE stock/common Closed-End Fund exact-ISIN rescue.
class FHClosedEndV099:
    batch_size = 100
    def us_symbols(self):
        return [
            {"symbol":"PSUS","displaySymbol":"PSUS","description":"CEF","currency":"USD","type":"Closed-End Fund","mic":"XNYS","figi":"FH_PSUS"},
            {"symbol":"PWRL","displaySymbol":"PWRL","description":"CEF","currency":"USD","type":"Closed-End Fund","mic":"XNAS","figi":"FH_PWRL"},
        ]

class OFClosedEndV099:
    batch_size = 100
    def __init__(self, share=True, st2="Mutual Fund", ticker="PSUS"):
        self.share=share; self.st2=st2; self.ticker=ticker
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for j in jobs:
            if j.get("idValue") == "US0000000991" and j.get("micCode") == "XNYS":
                out.append([OpenFigiIdentity(figi="OF_PSUS", composite_figi=None, share_class_figi="SC_PSUS" if self.share else None, ticker=self.ticker, name="CEF", security_type="Closed-End Fund", security_type2=self.st2, exch_code="US")])
            else: out.append([])
        return out

class YHClosedEndV099:
    batch_size = 75
    def __init__(self, symbol="PSUS", exchange="NYQ", currency="USD", qtype="EQUITY", count=1):
        self.symbol=symbol; self.exchange=exchange; self.currency=currency; self.qtype=qtype; self.count=count
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        if isin != "US0000000991": return []
        return [YahooSearchCandidate(self.symbol, self.exchange, self.qtype, None, None) for _ in range(self.count)]
    def quotes(self, symbols):
        return {s: YahooQuote(s,self.exchange,"NYSE" if self.exchange=="NYQ" else "Nasdaq",self.currency,self.qtype,"us_market",None,None,10.0,0) for s in symbols}

def _v099_cef_row(prefix="NYSE", symbol="PSUS", isin="US0000000991"):
    return TvRow(f"{prefix}:{symbol}",prefix,symbol,None,"USD","stock",("common",),None,None,10.0,isin)

def test_v099_xnys_stock_common_closed_end_fund_admission(tmp_path):
    db=CacheDB(tmp_path / "v099-cef.sqlite")
    r=BatchResolver(db,FHClosedEndV099(),OFClosedEndV099(),YHClosedEndV099())
    got=r.resolve([_v099_cef_row()])["NYSE:PSUS"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNYS_STOCK_COMMON_CLOSED_END_FUND_EXACT_ISIN"
    assert got.source_mic == got.target_mic == "XNYS"
    assert r.stats["us_xnys_stock_common_closed_end_fund_source_proven"] == 1
    assert r.stats["us_xnys_stock_common_closed_end_fund_rescue_matches"] == 1
    db.close()

def test_v099_closed_end_fund_rule_does_not_claim_xnas(tmp_path):
    db=CacheDB(tmp_path / "v099-xnas.sqlite")
    r=BatchResolver(db,FHClosedEndV099(),OFClosedEndV099(),YHClosedEndV099())
    got=r.resolve([_v099_cef_row("NASDAQ","PWRL","US0000000992")])["NASDAQ:PWRL"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:Closed-End Fund"
    assert r.stats["us_xnys_stock_common_closed_end_fund_rescue_matches"] == 0
    db.close()

def test_v099_closed_end_fund_requires_shareclass_and_exact_taxonomy(tmp_path):
    for of in [OFClosedEndV099(share=False), OFClosedEndV099(st2="Common Stock"), OFClosedEndV099(ticker="PSUS-X")]:
        db=CacheDB(tmp_path / f"v099-of-{id(of)}.sqlite")
        r=BatchResolver(db,FHClosedEndV099(),of,YHClosedEndV099())
        got=r.resolve([_v099_cef_row()])["NYSE:PSUS"]
        assert got.status == "REJECTED"
        assert r.stats["us_xnys_stock_common_closed_end_fund_rescue_matches"] == 0
        db.close()

def test_v099_closed_end_fund_requires_unique_exact_yahoo_source_route(tmp_path):
    for yh in [YHClosedEndV099(symbol="PSUS-X"),YHClosedEndV099(exchange="NMS"),YHClosedEndV099(currency="CAD"),YHClosedEndV099(qtype="ETF"),YHClosedEndV099(count=2)]:
        db=CacheDB(tmp_path / f"v099-yh-{id(yh)}.sqlite")
        r=BatchResolver(db,FHClosedEndV099(),OFClosedEndV099(),yh)
        got=r.resolve([_v099_cef_row()])["NYSE:PSUS"]
        assert got.status == "REJECTED"
        assert r.stats["us_xnys_stock_common_closed_end_fund_rescue_matches"] == 0
        db.close()

class OFNoSymbolXNYSPreferredV048:
    batch_size = 100
    def __init__(self, security_type="PUBLIC", security_type2="Preferred Stock", count=1):
        self.security_type, self.security_type2, self.count = security_type, security_type2, count
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for j in jobs:
            ids=[OpenFigiIdentity(figi=f"OF{i}_{j['idValue']}", composite_figi=None, share_class_figi=None,
                 ticker="TY 6.125 PERP", name="Preferred", security_type=self.security_type,
                 security_type2=self.security_type2, exch_code="US") for i in range(self.count)]
            out.append(ids)
        return out


def _run_v048_no_symbol_rescue(tmp_path, yahoo=None, of=None, prefix="NYSE", symbol="TY/P"):
    db=CacheDB(tmp_path / "v048.sqlite")
    r=BatchResolver(db, FHNYSESlashPreferred(), of or OFNoSymbolXNYSPreferredV048(), yahoo or YHNYSESlashPreferred(candidate="TY-P"))
    row=TvRow(f"{prefix}:{symbol}", prefix, symbol, None, "USD", "stock", ("preferred",), None, None, 25.0, "US90214J3095")
    initial=[Binding(tv_id=row.tv_id, tv_symbol=row.symbol, tv_prefix=row.prefix, tv_currency=row.currency,
                     tv_type=row.tv_type, status="REJECTED", rejection_reason="FINNHUB_NO_SYMBOL")]
    got=r._us_xnys_finnhub_no_symbol_preferred_exact_isin_rescue([row], initial)[0]
    db.close()
    return got


def test_v048_xnys_no_symbol_preferred_same_source_rescue_without_shareclassfigi(tmp_path):
    got=_run_v048_no_symbol_rescue(tmp_path)
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNYS_FINNHUB_NO_SYMBOL_PREFERRED_EXACT_ISIN"
    assert got.source_mic == got.target_mic == "XNYS"
    assert got.yahoo_symbol == "TY-P"
    assert got.share_class_figi is None


def test_v048_xnys_no_symbol_preferred_rejects_multiple_scoped_figis(tmp_path):
    got=_run_v048_no_symbol_rescue(tmp_path, of=OFNoSymbolXNYSPreferredV048(count=2))
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_NO_SYMBOL"


def test_v048_xnys_no_symbol_preferred_rejects_cross_market_yahoo(tmp_path):
    got=_run_v048_no_symbol_rescue(tmp_path, yahoo=YHNYSESlashPreferred(candidate="TY-P", exchange="FRA", full="Frankfurt", currency="EUR"))
    assert got.status == "REJECTED"


def test_v048_xnys_no_symbol_preferred_does_not_apply_to_xase(tmp_path):
    got=_run_v048_no_symbol_rescue(tmp_path, prefix="AMEX", symbol="PHXE/P")
    assert got.status == "REJECTED"


def test_v048_xnys_no_symbol_preferred_rejects_noncorrelated_yahoo_symbol(tmp_path):
    got=_run_v048_no_symbol_rescue(tmp_path, yahoo=YHNYSESlashPreferred(candidate="OTHER-P"))
    assert got.status == "REJECTED"

# v0.4.11: XNAS preferred PUBLIC rescue requires exact OpenFIGI/Yahoo segment proof.
class FHPublicXnasV0411:
    batch_size = 100
    def us_symbols(self):
        return [{"symbol":"XPREF","displaySymbol":"XPREF","description":"XNAS PREF","currency":"USD","type":"PUBLIC","mic":"XNAS","figi":"FH_XPREF"}]

class OFPublicXnasV0411:
    batch_size = 100
    def __init__(self, exch="NASDAQ/NGS", scoped=False):
        self.exch, self.scoped = exch, scoped
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for job in jobs:
            if job.get("idValue") != "US0000004111": out.append([]); continue
            if job.get("micCode") == "XNAS":
                out.append([OpenFigiIdentity("SCOPED","C",None,"XPREF","PREF","PUBLIC","Preferred Stock","NASDAQ/NGS")]) if self.scoped else out.append([])
            else:
                out.append([OpenFigiIdentity("OF_XPREF","C",None,"XPREF","PREF","PUBLIC","Preferred Stock",self.exch)])
        return out

class YHPublicXnasV0411:
    batch_size = 75
    def __init__(self, exchange="NMS", full="NasdaqGS"):
        self.exchange, self.full = exchange, full
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        return [YahooSearchCandidate("XPREF",self.exchange,"EQUITY",None,None)] if isin == "US0000004111" else []
    def quotes(self, symbols):
        return {s: YahooQuote(s,self.exchange,self.full,"USD","EQUITY","us_market",None,None,10.0,0) for s in symbols}

def _v0411_row(tv_type="stock", specs=("preferred",)):
    return TvRow("NASDAQ:XPREF","NASDAQ","XPREF",None,"USD",tv_type,specs,None,None,10.0,"US0000004111")

def test_v0411_xnas_public_preferred_exact_segment_admission(tmp_path):
    db=CacheDB(tmp_path / "v0411-ok.sqlite")
    r=BatchResolver(db,FHPublicXnasV0411(),OFPublicXnasV0411(),YHPublicXnasV0411())
    got=r.resolve([_v0411_row()])["NASDAQ:XPREF"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "US_XNAS_FINNHUB_PUBLIC_PREFERRED_EXACT_ISIN_SEGMENT"
    assert got.source_mic == got.target_mic == "XNAS"
    assert got.share_class_figi is None
    assert r.stats["us_xnas_public_preferred_segment_rescue_matches"] == 1
    db.close()

def test_v0411_nasdaq_ngs_to_ngm_is_negative_control(tmp_path):
    db=CacheDB(tmp_path / "v0411-segment-mismatch.sqlite")
    r=BatchResolver(db,FHPublicXnasV0411(),OFPublicXnasV0411("NASDAQ/NGS"),YHPublicXnasV0411("NGM","NasdaqGM"))
    got=r.resolve([_v0411_row()])["NASDAQ:XPREF"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:PUBLIC"
    assert r.stats["us_xnas_public_preferred_segment_rescue_matches"] == 0
    db.close()

def test_v0411_xnas_public_segment_rule_excludes_fund_unit(tmp_path):
    db=CacheDB(tmp_path / "v0411-fund-unit.sqlite")
    r=BatchResolver(db,FHPublicXnasV0411(),OFPublicXnasV0411(),YHPublicXnasV0411())
    got=r.resolve([_v0411_row("fund",("unit",))])["NASDAQ:XPREF"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "FINNHUB_TYPE_MISMATCH:PUBLIC"
    assert r.stats["us_xnas_public_preferred_segment_rescue_matches"] == 0
    db.close()

def test_v0411_xnas_public_segment_requires_scoped_xnas_no_match(tmp_path):
    db=CacheDB(tmp_path / "v0411-scoped.sqlite")
    r=BatchResolver(db,FHPublicXnasV0411(),OFPublicXnasV0411(scoped=True),YHPublicXnasV0411())
    got=r.resolve([_v0411_row()])["NASDAQ:XPREF"]
    # Existing direct same-venue preferred proof may admit this row; v0.4.11
    # must not claim it because its audited contract requires scoped NO_MATCH.
    assert got.mapping_method != "US_XNAS_FINNHUB_PUBLIC_PREFERRED_EXACT_ISIN_SEGMENT"
    assert r.stats["us_xnas_public_preferred_segment_rescue_matches"] == 0
    db.close()

class FHMicMismatchSameVenue:
    def us_symbols(self):
        return [{"symbol":"NVA","currency":"USD","type":"Common Stock","mic":"XNAS","figi":"FH_NVA","shareClassFIGI":"SC_NVA"}]

class OFMicMismatchSameVenue:
    batch_size = 100
    def __init__(self, *, source_mic="XASE", source_ticker="NVA", source_share="SC_NVA", ambiguous=False):
        self.source_mic=source_mic; self.source_ticker=source_ticker; self.source_share=source_share; self.ambiguous=ambiguous
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out=[]
        for job in jobs:
            if job.get("micCode") is None:
                vals=[OpenFigiIdentity("OF_UN","COMP","SC_NVA","NVA",None,"Common Stock","Common Stock","US")]
                if self.ambiguous:
                    vals.append(OpenFigiIdentity("OF_UN2","COMP2","SC_OTHER","NVA",None,"Common Stock","Common Stock","US"))
                out.append(vals)
            elif job.get("micCode") == self.source_mic:
                out.append([OpenFigiIdentity("OF_SRC","COMP",self.source_share,self.source_ticker,None,"Common Stock","Common Stock","UA")])
            else:
                out.append([])
        return out

class YHMicMismatchSameVenue:
    batch_size=75
    def __init__(self, *, symbol="NVA", exchange="ASE"):
        self.symbol=symbol; self.exchange=exchange
    def search_exact_isin(self, isin, max_results=10):
        from tv_market_identity.models import YahooSearchCandidate
        return [YahooSearchCandidate(self.symbol,self.exchange,"EQUITY",None,None)]
    def quotes(self, symbols):
        return {s: YahooQuote(s,self.exchange,"NYSE American" if self.exchange=="ASE" else "NasdaqGS","USD","EQUITY","us_market",None,None,6.0,0) for s in symbols}

def _nva_row():
    return TvRow("AMEX:NVA","AMEX","NVA","Nova Minerals Corp","USD","stock",("common",),None,None,6.0,"US66982H1059")

def test_us_same_venue_mic_mismatch_exact_isin_admission(tmp_path):
    db=CacheDB(tmp_path/'mic-rescue.sqlite')
    r=BatchResolver(db,FHMicMismatchSameVenue(),OFMicMismatchSameVenue(),YHMicMismatchSameVenue())
    got=r.resolve([_nva_row()])['AMEX:NVA']
    assert got.status == 'VERIFIED'
    assert got.mapping_method == 'US_SAME_VENUE_MIC_MISMATCH_EXACT_ISIN'
    assert got.source_mic == got.target_mic == 'XASE'
    assert got.share_class_figi == 'SC_NVA'
    db.close()

def test_us_same_venue_mic_mismatch_rejects_wrong_yahoo_venue(tmp_path):
    db=CacheDB(tmp_path/'mic-wrong-venue.sqlite')
    r=BatchResolver(db,FHMicMismatchSameVenue(),OFMicMismatchSameVenue(),YHMicMismatchSameVenue(exchange='NMS'))
    got=r.resolve([_nva_row()])['AMEX:NVA']
    assert got.status == 'REJECTED' and got.rejection_reason == 'FINNHUB_MIC_MISMATCH:XNAS'
    db.close()

def test_us_same_venue_mic_mismatch_rejects_ambiguous_share_class(tmp_path):
    db=CacheDB(tmp_path/'mic-ambiguous.sqlite')
    r=BatchResolver(db,FHMicMismatchSameVenue(),OFMicMismatchSameVenue(ambiguous=True),YHMicMismatchSameVenue())
    got=r.resolve([_nva_row()])['AMEX:NVA']
    assert got.status == 'REJECTED' and got.rejection_reason == 'FINNHUB_MIC_MISMATCH:XNAS'
    db.close()

def test_us_same_venue_mic_mismatch_rejects_ticker_mismatch(tmp_path):
    db=CacheDB(tmp_path/'mic-ticker.sqlite')
    r=BatchResolver(db,FHMicMismatchSameVenue(),OFMicMismatchSameVenue(source_ticker='OTHER'),YHMicMismatchSameVenue())
    got=r.resolve([_nva_row()])['AMEX:NVA']
    assert got.status == 'REJECTED' and got.rejection_reason == 'FINNHUB_MIC_MISMATCH:XNAS'
    db.close()

def test_us_same_venue_mic_mismatch_rejects_share_class_conflict(tmp_path):
    db=CacheDB(tmp_path/'mic-share.sqlite')
    r=BatchResolver(db,FHMicMismatchSameVenue(),OFMicMismatchSameVenue(source_share='SC_OTHER'),YHMicMismatchSameVenue())
    got=r.resolve([_nva_row()])['AMEX:NVA']
    assert got.status == 'REJECTED' and got.rejection_reason == 'FINNHUB_MIC_MISMATCH:XNAS'
    db.close()


class OFIrelandIsinAlias:
    batch_size = 100

    def __init__(self, unscoped_rows=None):
        self.unscoped_rows = unscoped_rows

    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity

        default = [
            OpenFigiIdentity(
                figi="BBG_A5G_FRA", composite_figi="BBG_A5G_COMP",
                share_class_figi="BBG_AIB_SHARE", ticker="A5G",
                name="AIB GROUP PLC", security_type="Common Stock",
                security_type2="Common Stock", exch_code="GF",
            ),
            OpenFigiIdentity(
                figi="BBG_AIBG_ID", composite_figi="BBG_AIBG_COMP",
                share_class_figi="BBG_AIB_SHARE", ticker="AIBG",
                name="AIB GROUP PLC", security_type="Common Stock",
                security_type2="Common Stock", exch_code="ID",
            ),
            # Missing shareClassFIGI is non-evidence and must not create a
            # second security identity.
            OpenFigiIdentity(
                figi="BBG_AIBG_X1", composite_figi="BBG_AIBG_X1_COMP",
                share_class_figi=None, ticker="AIBGGBP",
                name="AIB GROUP PLC", security_type="Common Stock",
                security_type2="Common Stock", exch_code="X1",
            ),
        ]
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "IE00BF0L3536" and "micCode" not in job:
                out.append(self.unscoped_rows if self.unscoped_rows is not None else default)
            else:
                out.append([])
        return out


class YHIrelandA5G:
    batch_size = 75

    def quotes(self, symbols):
        if "A5G.IR" not in symbols:
            return {}
        return {"A5G.IR": YahooQuote(
            "A5G.IR", "ISE", "Irish", "EUR", "EQUITY",
            "ie_market", "AIB GROUP PLC", None, 11.6, 15,
        )}


def _ireland_a5g_row(*, isin="IE00BF0L3536", tv_type="stock", type_specs=("common",)):
    return TvRow(
        "EURONEXT:A5G", "EURONEXT", "A5G", "AIB GROUP PLC", "EUR",
        tv_type, type_specs, "Finance", 1e10, 11.6, isin, True,
    )


def test_ireland_exact_isin_unique_dublin_listing_can_bridge_ticker_alias(tmp_path):
    db = CacheDB(tmp_path / "ireland-isin-xdub.sqlite")
    r = BatchResolver(db, None, OFIrelandIsinAlias(), YHIrelandA5G())
    row = _ireland_a5g_row()
    got = r.resolve([row], market="ireland")[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "IRELAND_ISIN_UNIQUE_XDUB_LISTING"
    assert got.yahoo_symbol == "A5G.IR"
    assert got.resolved_mic == "XDUB"
    assert got.source_mic == "XDUB"
    assert got.source_venue_code == "ID"
    assert got.share_class_figi == "BBG_AIB_SHARE"
    assert got.venue_figi == "BBG_AIBG_ID"
    assert r.stats["ireland_isin_unscoped_jobs"] == 1
    assert r.stats["ireland_isin_unscoped_matches"] == 1
    db.close()


def test_ireland_isin_bridge_rejects_two_dublin_listings(tmp_path):
    from tv_market_identity.models import OpenFigiIdentity
    rows = [
        OpenFigiIdentity("ID1", "C1", "SC1", "AIBG", "AIB", "Common Stock", "Common Stock", "ID"),
        OpenFigiIdentity("ID2", "C2", "SC1", "AIB2", "AIB", "Common Stock", "Common Stock", "ID"),
    ]
    db = CacheDB(tmp_path / "ireland-two-id.sqlite")
    r = BatchResolver(db, None, OFIrelandIsinAlias(rows), YHIrelandA5G())
    got = r.resolve([_ireland_a5g_row()], market="ireland")["EURONEXT:A5G"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "OPENFIGI_NO_MATCH"
    assert r.stats["ireland_isin_unscoped_no_match"] == 1
    db.close()


def test_ireland_isin_bridge_rejects_multiple_share_classes(tmp_path):
    from tv_market_identity.models import OpenFigiIdentity
    rows = [
        OpenFigiIdentity("ID1", "C1", "SC1", "AIBG", "AIB", "Common Stock", "Common Stock", "ID"),
        OpenFigiIdentity("F1", "C2", "SC2", "A5G", "AIB", "Common Stock", "Common Stock", "GF"),
    ]
    db = CacheDB(tmp_path / "ireland-two-share.sqlite")
    r = BatchResolver(db, None, OFIrelandIsinAlias(rows), YHIrelandA5G())
    got = r.resolve([_ireland_a5g_row()], market="ireland")["EURONEXT:A5G"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "OPENFIGI_NO_MATCH"
    db.close()


def test_ireland_isin_bridge_is_not_enabled_for_other_market(tmp_path):
    db = CacheDB(tmp_path / "ireland-other-market.sqlite")
    r = BatchResolver(db, None, OFIrelandIsinAlias(), YHIrelandA5G())
    got = r.resolve([_ireland_a5g_row()], market="france")["EURONEXT:A5G"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "MIC_UNKNOWN"
    assert r.stats["ireland_isin_unscoped_jobs"] == 0
    db.close()


def test_ireland_isin_bridge_requires_isin(tmp_path):
    db = CacheDB(tmp_path / "ireland-no-isin.sqlite")
    r = BatchResolver(db, None, OFIrelandIsinAlias(), YHIrelandA5G())
    got = r.resolve([_ireland_a5g_row(isin=None)], market="ireland")["EURONEXT:A5G"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "OPENFIGI_NO_MATCH"
    assert r.stats["ireland_isin_unscoped_jobs"] == 0
    db.close()


def test_ireland_isin_bridge_rejects_type_conflict_or_wrong_source_venue(tmp_path):
    from tv_market_identity.models import OpenFigiIdentity
    cases = [
        [OpenFigiIdentity("ID1", "C1", "SC1", "AIBG", "AIB", "Corporate Bond", "Corporate Bond", "ID")],
        [OpenFigiIdentity("F1", "C1", "SC1", "A5G", "AIB", "Common Stock", "Common Stock", "GF")],
    ]
    for idx, rows in enumerate(cases):
        db = CacheDB(tmp_path / f"ireland-guard-{idx}.sqlite")
        r = BatchResolver(db, None, OFIrelandIsinAlias(rows), YHIrelandA5G())
        got = r.resolve([_ireland_a5g_row()], market="ireland")["EURONEXT:A5G"]
        assert got.status == "REJECTED"
        assert got.rejection_reason == "OPENFIGI_NO_MATCH"
        db.close()


def test_ireland_isin_bridge_requires_complete_matching_yahoo_venue(tmp_path):
    class YHWrongIrelandVenue:
        batch_size = 75
        def quotes(self, symbols):
            if "A5G.IR" not in symbols:
                return {}
            return {"A5G.IR": YahooQuote(
                "A5G.IR", "NYQ", "NYSE", "EUR", "EQUITY",
                "us_market", "AIB GROUP PLC", None, 11.6, 0,
            )}

    db = CacheDB(tmp_path / "ireland-yahoo-guard.sqlite")
    r = BatchResolver(db, None, OFIrelandIsinAlias(), YHWrongIrelandVenue())
    got = r.resolve([_ireland_a5g_row()], market="ireland")["EURONEXT:A5G"]
    assert got.status == "REJECTED"
    assert got.rejection_reason.startswith("YAHOO_VENUE_MISMATCH:XDUB")
    db.close()

@pytest.mark.parametrize(
    "isin,ticker,security_type,security_type2",
    [
        ("IE00BLP58571", "IR5B", "Unit", "Unit"),
        ("IE00BF2NR112", "GRP", "Closed-End Fund", "Mutual Fund"),
    ],
)
def test_ireland_isin_bridge_accepts_reviewed_xdub_taxonomy(
    tmp_path, isin, ticker, security_type, security_type2
):
    from tv_market_identity.models import OpenFigiIdentity

    class OFReviewedIreland:
        batch_size = 100
        def map_jobs(self, jobs):
            out = []
            for job in jobs:
                if job.get("idType") == "ID_ISIN" and job.get("idValue") == isin and "micCode" not in job:
                    out.append([OpenFigiIdentity(
                        f"FIGI_{ticker}", f"COMP_{ticker}", f"SC_{ticker}", ticker,
                        ticker, security_type, security_type2, "ID",
                    )])
                else:
                    out.append([])
            return out

    class YHReviewedIreland:
        batch_size = 75
        def quotes(self, symbols):
            symbol = f"{ticker}.IR"
            if symbol not in symbols:
                return {}
            return {symbol: YahooQuote(
                symbol, "ISE", "Irish", "EUR", "EQUITY",
                "ie_market", ticker, None, 10.0, 0,
            )}

    row = TvRow(
        f"EURONEXT:{ticker}", "EURONEXT", ticker, ticker, "EUR",
        "stock", ("common",), "", 1e9, 10.0, isin, True,
    )
    db = CacheDB(tmp_path / f"ireland-reviewed-{ticker}.sqlite")
    r = BatchResolver(db, None, OFReviewedIreland(), YHReviewedIreland())
    got = r.resolve([row], market="ireland")[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "IRELAND_ISIN_UNIQUE_XDUB_LISTING"
    assert got.yahoo_symbol == f"{ticker}.IR"
    assert got.source_venue_code == "ID"
    db.close()


def test_ireland_isin_bridge_does_not_generalize_reviewed_taxonomy(tmp_path):
    from tv_market_identity.models import OpenFigiIdentity

    rows = [OpenFigiIdentity(
        "ID1", "C1", "SC1", "OTHER", "OTHER",
        "Closed-End Fund", "Mutual Fund", "ID",
    )]
    db = CacheDB(tmp_path / "ireland-unreviewed-taxonomy.sqlite")
    r = BatchResolver(db, None, OFIrelandIsinAlias(rows), YHIrelandA5G())
    got = r.resolve([_ireland_a5g_row()], market="ireland")["EURONEXT:A5G"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "OPENFIGI_NO_MATCH"
    db.close()

class OFJapanReitFallback:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "JP3027670003" and job.get("micCode") == "XTKS":
                out.append([OpenFigiIdentity(
                    "BBG_REIT_XTKS", "BBG_REIT_COMP", "BBG_REIT_SHARE", "8951", "NIPPON BUILDING FUND INC",
                    "REIT", "REIT", "JT",
                )])
            else:
                out.append([])
        return out

class YHJapanReit:
    batch_size = 75
    def quotes(self, symbols):
        if "8951.T" not in symbols:
            return {}
        return {"8951.T": YahooQuote(
            "8951.T", "JPX", "Tokyo", "JPY", "EQUITY", "jp_market",
            "NIPPON BUILDING FUND INC", None, 122600.0, 0,
        )}

def _japan_reit_row(isin="JP3027670003"):
    return TvRow(
        "TSE:8951", "TSE", "8951", "NIPPON BUILDING FUND INC", "JPY",
        "stock", ("common",), "", 1e12, 122600.0, isin, True,
    )

def test_japan_xtks_reit_taxonomy_uses_exact_isin_and_venue(tmp_path):
    db = CacheDB(tmp_path / "japan-reit.sqlite")
    r = BatchResolver(db, None, OFJapanReitFallback(), YHJapanReit())
    got = r.resolve([_japan_reit_row()], market="japan")["TSE:8951"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "JAPAN_XTKS_REIT_TAXONOMY"
    assert got.yahoo_symbol == "8951.T"
    assert got.share_class_figi == "BBG_REIT_SHARE"
    assert r.stats["japan_xtks_reit_isin_jobs"] == 1
    assert r.stats["japan_xtks_reit_isin_matches"] == 1
    db.close()

def test_japan_xtks_reit_taxonomy_requires_reit_taxonomy(tmp_path):
    from tv_market_identity.models import OpenFigiIdentity
    class OFWrongType(OFJapanReitFallback):
        def map_jobs(self, jobs):
            out=[]
            for job in jobs:
                if job.get("idType") == "ID_ISIN":
                    out.append([OpenFigiIdentity("F","C","S","8951","X","Unit","Unit","JT")])
                else: out.append([])
            return out
    db = CacheDB(tmp_path / "japan-reit-wrong.sqlite")
    r = BatchResolver(db, None, OFWrongType(), YHJapanReit())
    got = r.resolve([_japan_reit_row()], market="japan")["TSE:8951"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "OPENFIGI_NO_MATCH"
    db.close()

def test_japan_xtks_reit_taxonomy_does_not_apply_outside_japan(tmp_path):
    db = CacheDB(tmp_path / "japan-reit-scope.sqlite")
    r = BatchResolver(db, None, OFJapanReitFallback(), YHJapanReit())
    got = r.resolve([_japan_reit_row()], market="germany")["TSE:8951"]
    assert got.status == "REJECTED"
    assert r.stats["japan_xtks_reit_isin_jobs"] == 0
    db.close()

class OFJapanInfrastructureFundFallback:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "JP3048360006" and job.get("micCode") == "XTKS":
                out.append([OpenFigiIdentity(
                    "BBG_UNIT_XTKS", "BBG_UNIT_COMP", "BBG_UNIT_SHARE", "9282", "ICHIGO GREEN INFRASTRUCTURE INVESTMENT CORP",
                    "Unit", "Unit", "JT",
                )])
            else:
                out.append([])
        return out

class YHJapanInfrastructureFund:
    batch_size = 75
    def quotes(self, symbols):
        if "9282.T" not in symbols:
            return {}
        return {"9282.T": YahooQuote(
            "9282.T", "JPX", "Tokyo", "JPY", "EQUITY", "jp_market",
            "ICHIGO GREEN INFRASTRUCTURE INVESTMENT CORP", None, 50000.0, 0,
        )}

def _japan_infrastructure_fund_row(isin="JP3048360006"):
    return TvRow(
        "TSE:9282", "TSE", "9282", "ICHIGO GREEN INFRASTRUCTURE INVESTMENT CORP", "JPY",
        "stock", ("common",), "", 1e11, 50000.0, isin, True,
    )

def test_japan_xtks_infrastructure_fund_taxonomy_uses_reviewed_isin_and_venue(tmp_path):
    db = CacheDB(tmp_path / "japan-infrastructure.sqlite")
    r = BatchResolver(db, None, OFJapanInfrastructureFundFallback(), YHJapanInfrastructureFund())
    got = r.resolve([_japan_infrastructure_fund_row()], market="japan")["TSE:9282"]
    assert got.status == "VERIFIED"
    assert got.mapping_method == "JAPAN_XTKS_INFRASTRUCTURE_FUND_TAXONOMY"
    assert got.yahoo_symbol == "9282.T"
    assert got.share_class_figi == "BBG_UNIT_SHARE"
    assert r.stats["japan_xtks_infrastructure_fund_isin_matches"] == 1
    db.close()

def test_japan_xtks_infrastructure_fund_taxonomy_rejects_unreviewed_unit_isin(tmp_path):
    from tv_market_identity.models import OpenFigiIdentity
    class OFUnreviewedUnit(OFJapanInfrastructureFundFallback):
        def map_jobs(self, jobs):
            out = []
            for job in jobs:
                if job.get("idType") == "ID_ISIN":
                    out.append([OpenFigiIdentity(
                        "F", "C", "S", "9282", "UNREVIEWED UNIT",
                        "Unit", "Unit", "JT",
                    )])
                else:
                    out.append([])
            return out
    db = CacheDB(tmp_path / "japan-infrastructure-unreviewed.sqlite")
    r = BatchResolver(db, None, OFUnreviewedUnit(), YHJapanInfrastructureFund())
    got = r.resolve([_japan_infrastructure_fund_row(isin="JP0000000001")], market="japan")["TSE:9282"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "OPENFIGI_NO_MATCH"
    assert r.stats["japan_xtks_infrastructure_fund_isin_matches"] == 0
    db.close()

class OFJapanRegionalExact:
    batch_size = 100
    def __init__(self, *, duplicate=False, wrong_ticker=False, missing_share=False):
        self.duplicate = duplicate
        self.wrong_ticker = wrong_ticker
        self.missing_share = missing_share
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if job.get("micCode") in {"XNGO", "XFKA"} and job.get("idType") == "ID_EXCH_SYMBOL":
                ticker = "9999" if self.wrong_ticker else job.get("idValue")
                share = None if self.missing_share else "BBG_JP_SHARE"
                rows = [OpenFigiIdentity(
                    "BBG_JP_LISTING", "BBG_JP_COMP", share, ticker, "JAPAN REGIONAL CO",
                    "Common Stock", "Common Stock", "JN" if job.get("micCode") == "XNGO" else "JF",
                )]
                if self.duplicate:
                    rows.append(OpenFigiIdentity(
                        "BBG_JP_LISTING_2", "BBG_JP_COMP_2", "BBG_JP_SHARE_2", ticker, "JAPAN REGIONAL CO",
                        "Common Stock", "Common Stock", "JN" if job.get("micCode") == "XNGO" else "JF",
                    ))
                out.append(rows)
            else:
                out.append([])
        return out

class YHJapanRegionalMissing:
    batch_size = 75
    def quotes(self, symbols):
        return {}
    def chart_quotes(self, symbols):
        return {}


def _japan_regional_row(prefix="NAG", symbol="8306", isin="JP3902900004"):
    return TvRow(
        f"{prefix}:{symbol}", prefix, symbol, "JAPAN REGIONAL CO", "JPY",
        "stock", ("common",), "", 1e12, 1000.0, isin, True,
    )


def test_japan_regional_exact_openfigi_listing_allows_known_yahoo_coverage_gap(tmp_path):
    db = CacheDB(tmp_path / "japan-regional-exact.sqlite")
    r = BatchResolver(db, None, OFJapanRegionalExact(), YHJapanRegionalMissing())
    got = r.resolve([_japan_regional_row()], market="japan")["NAG:8306"]
    assert got.status == "VERIFIED"
    assert got.resolved_mic == "XNGO"
    assert got.mapping_method == "JAPAN_REGIONAL_EXACT_OPENFIGI_LISTING"
    assert got.share_class_figi == "BBG_JP_SHARE"
    assert got.quote_status == "UNAVAILABLE"
    assert r.stats["japan_regional_exact_openfigi_listing_matches"] == 1
    db.close()


def test_japan_regional_exact_openfigi_listing_applies_to_fukuoka(tmp_path):
    db = CacheDB(tmp_path / "japan-regional-fukuoka.sqlite")
    r = BatchResolver(db, None, OFJapanRegionalExact(), YHJapanRegionalMissing())
    got = r.resolve([_japan_regional_row("FSE", "2164", "JP3167310006")], market="japan")["FSE:2164"]
    assert got.status == "VERIFIED"
    assert got.resolved_mic == "XFKA"
    assert got.mapping_method == "JAPAN_REGIONAL_EXACT_OPENFIGI_LISTING"
    db.close()


@pytest.mark.parametrize("kwargs", [
    {"duplicate": True},
    {"wrong_ticker": True},
    {"missing_share": True},
])
def test_japan_regional_exact_openfigi_listing_requires_unique_exact_complete_source(tmp_path, kwargs):
    db = CacheDB(tmp_path / ("japan-regional-negative-" + next(iter(kwargs)) + ".sqlite"))
    r = BatchResolver(db, None, OFJapanRegionalExact(**kwargs), YHJapanRegionalMissing())
    got = r.resolve([_japan_regional_row()], market="japan")["NAG:8306"]
    assert got.status == "REJECTED"
    assert r.stats["japan_regional_exact_openfigi_listing_matches"] == 0
    db.close()


def test_japan_regional_exact_openfigi_listing_requires_isin_and_japan_scope(tmp_path):
    db = CacheDB(tmp_path / "japan-regional-scope.sqlite")
    r = BatchResolver(db, None, OFJapanRegionalExact(), YHJapanRegionalMissing())
    no_isin = r.resolve([_japan_regional_row(isin=None)], market="japan")["NAG:8306"]
    assert no_isin.status == "REJECTED"
    db.close()

    db = CacheDB(tmp_path / "japan-regional-market.sqlite")
    r = BatchResolver(db, None, OFJapanRegionalExact(), YHJapanRegionalMissing())
    outside = r.resolve([_japan_regional_row()], market="germany")["NAG:8306"]
    assert outside.status == "REJECTED"
    db.close()


class OFJapanTorigoeReviewedMutualFund:
    batch_size = 100
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            if (job.get("idType") == "ID_EXCH_SYMBOL"
                    and job.get("idValue") == "2009"
                    and job.get("micCode") == "XFKA"):
                out.append([OpenFigiIdentity(
                    "BBG000BCTL39", "BBG000BCTFS5", "BBG001S6C4X5",
                    "2009", "TORIGOE CO LTD/THE",
                    "Common Stock", "Common Stock", "JF",
                )])
            else:
                out.append([])
        return out


class YHJapanTorigoeReviewedMutualFund:
    batch_size = 75
    def quotes(self, symbols):
        if "2009.F" not in symbols:
            return {}
        return {"2009.F": YahooQuote(
            "2009.F", "FKA", "Fukuoka", "JPY", "MUTUALFUND",
            "jp_market", "TORIGOE CO LTD (THE)", None, 755.0, 15,
        )}


def test_japan_xfka_reviewed_torigoe_mutualfund_taxonomy(tmp_path):
    db = CacheDB(tmp_path / "japan-torigoe-mf.sqlite")
    r = BatchResolver(db, None, OFJapanTorigoeReviewedMutualFund(), YHJapanTorigoeReviewedMutualFund())
    row = TvRow(
        "FSE:2009", "FSE", "2009", "Torigoe Co., Ltd.", "JPY",
        "stock", ("common",), "Process Industries", 1e10, 755.0,
    )
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.resolved_mic == "XFKA"
    assert got.yahoo_symbol == "2009.F"
    assert got.yahoo_quote_type == "MUTUALFUND"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] == 1
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 1
    db.close()


def test_japan_xfka_unreviewed_mutualfund_stays_rejected(tmp_path):
    db = CacheDB(tmp_path / "japan-torigoe-mf-unreviewed.sqlite")
    r = BatchResolver(db, None, OFJapanTorigoeReviewedMutualFund(), YHJapanTorigoeReviewedMutualFund())
    row = TvRow(
        "FSE:9999", "FSE", "2009", "Torigoe Co., Ltd.", "JPY",
        "stock", ("common",), "Process Industries", 1e10, 755.0,
    )
    got = r.resolve([row], market="japan")[row.tv_id]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_TYPE_MISMATCH:MUTUALFUND"
    assert r.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] == 0
    db.close()


class OFKoreaSegments:
    batch_size = 100

    def __init__(self, modes):
        self.modes = modes

    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        out = []
        for job in jobs:
            assert job["idType"] == "ID_ISIN"
            isin = job["idValue"]
            mic = job["micCode"]
            assert "currency" not in job
            assert "securityType2" not in job
            symbol, allowed = self.modes.get(isin, (None, set()))
            if symbol is not None and mic in allowed:
                out.append([OpenFigiIdentity(
                    figi=f"FIGI_{symbol}_{mic}", composite_figi=f"COMP_{symbol}_{mic}",
                    share_class_figi=f"SHARE_{symbol}", ticker=symbol,
                    name="KOREA TEST", security_type="Common Stock",
                    security_type2="Common Stock",
                    exch_code={"XKRX": "KP", "XKOS": "KQ", "XKON": "KE"}[mic],
                )])
            else:
                out.append([])
        return out


class YHKoreaSegments:
    batch_size = 75

    def quotes(self, symbols):
        out = {}
        if "005930.KS" in symbols:
            out["005930.KS"] = YahooQuote("005930.KS", "KSC", "Korea Stock Exchange", "KRW", "EQUITY", "kr_market", None, None, 100.0, 20)
        if "196170.KQ" in symbols:
            out["196170.KQ"] = YahooQuote("196170.KQ", "KOE", "KOSDAQ", "KRW", "EQUITY", "kr_market", None, None, 100.0, 20)
        return out


def _korea_row(symbol, isin):
    return TvRow(
        f"KRX:{symbol}", "KRX", symbol, "KOREA TEST", "KRW", "stock",
        ("common",), None, None, 100.0, isin=isin,
    )


def test_korea_krx_segment_probe_routes_kospi_and_kosdaq_without_ticker_heuristics(tmp_path):
    db = CacheDB(tmp_path / "kr.sqlite")
    of = OFKoreaSegments({
        "KR7005930003": ("005930", {"XKRX"}),
        "KR7196170005": ("196170", {"XKOS"}),
    })
    r = BatchResolver(db, FH(), of, YHKoreaSegments())
    got = r.resolve([
        _korea_row("005930", "KR7005930003"),
        _korea_row("196170", "KR7196170005"),
    ], market="korea")

    assert got["KRX:005930"].status == "VERIFIED"
    assert got["KRX:005930"].resolved_mic == "XKRX"
    assert got["KRX:005930"].yahoo_symbol == "005930.KS"
    assert got["KRX:196170"].status == "VERIFIED"
    assert got["KRX:196170"].resolved_mic == "XKOS"
    assert got["KRX:196170"].yahoo_symbol == "196170.KQ"
    assert r.stats["korea_krx_segment_probe_matches_XKRX"] == 1
    assert r.stats["korea_krx_segment_probe_matches_XKOS"] == 1
    db.close()


def test_korea_konex_source_is_recognized_but_rejected_without_yahoo_contract(tmp_path):
    db = CacheDB(tmp_path / "kr_konex.sqlite")
    isin = "KR7232530006"
    of = OFKoreaSegments({isin: ("232530", {"XKON"})})
    r = BatchResolver(db, FH(), of, YHKoreaSegments())
    got = r.resolve([_korea_row("232530", isin)], market="korea")["KRX:232530"]

    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_SUFFIX_UNKNOWN:XKON"
    assert r.stats["korea_krx_segment_probe_matches_XKON"] == 1
    db.close()


def test_korea_krx_segment_probe_fails_closed_on_both_or_neither(tmp_path):
    db = CacheDB(tmp_path / "kr_fail.sqlite")
    of = OFKoreaSegments({
        "KR7111111111": ("111111", {"XKRX", "XKOS"}),
        "KR7222222222": ("222222", set()),
    })
    r = BatchResolver(db, FH(), of, YHKoreaSegments())
    got = r.resolve([
        _korea_row("111111", "KR7111111111"),
        _korea_row("222222", "KR7222222222"),
    ], market="korea")

    assert got["KRX:111111"].status == "REJECTED"
    assert got["KRX:111111"].rejection_reason == "OPENFIGI_KOREA_SEGMENT_AMBIGUOUS:XKRX,XKOS"
    assert got["KRX:222222"].status == "REJECTED"
    assert got["KRX:222222"].rejection_reason.startswith("OPENFIGI_KOREA_SEGMENT_NO_MATCH")
    db.close()

class YHKoreaAmbiguity(YHKoreaSegments):
    def __init__(self, *, search_candidates=None, quote=None):
        self.search_candidates = search_candidates if search_candidates is not None else []
        self.quote = quote

    def search_exact_isin(self, isin, max_results=10):
        return list(self.search_candidates)

    def quotes(self, symbols):
        if self.quote is not None and self.quote.symbol in symbols:
            return {self.quote.symbol: self.quote}
        return super().quotes(symbols)


def _korea_search_candidate(symbol="03481K.KQ", exchange="KOE", quote_type="EQUITY"):
    from tv_market_identity.models import YahooSearchCandidate
    return YahooSearchCandidate(symbol, exchange, quote_type, "HaeSung(1P)", "Haesung Industrial Co., Ltd.")


def _korea_quote(symbol="03481K.KQ", exchange="KOE", currency="KRW", quote_type="EQUITY", full_exchange_name=None):
    full_name = full_exchange_name or ("KOSDAQ" if exchange == "KOE" else "KSE")
    return YahooQuote(symbol, exchange, full_name, currency, quote_type, "kr_market", "HaeSung(1P)", None, 6030.0, 20)


def test_korea_konex_and_kosdaq_same_share_class_remains_source_ambiguous(tmp_path):
    db = CacheDB(tmp_path / "kr_konex_amb.sqlite")
    isin = "KR7169670007"
    of = OFKoreaSegments({isin: ("169670", {"XKON", "XKOS"})})
    y = YHKoreaAmbiguity(
        search_candidates=[_korea_search_candidate("169670.KQ", "KOE")],
        quote=_korea_quote("169670.KQ", "KOE"),
    )
    r = BatchResolver(db, FH(), of, y)
    got = r.resolve([_korea_row("169670", isin)], market="korea")["KRX:169670"]

    assert got.status == "REJECTED"
    assert got.rejection_reason == "OPENFIGI_KOREA_SEGMENT_AMBIGUOUS:XKOS,XKON"
    assert r.stats["korea_krx_segment_ambiguity_yahoo_resolved"] == 0
    db.close()


def test_korea_ambiguous_exact_isin_resolves_with_unique_yahoo_exact_isin_venue(tmp_path):
    db = CacheDB(tmp_path / "kr_amb_resolve.sqlite")
    isin = "KR703481K019"
    of = OFKoreaSegments({isin: ("03481K", {"XKRX", "XKOS"})})
    y = YHKoreaAmbiguity(search_candidates=[_korea_search_candidate()], quote=_korea_quote())
    r = BatchResolver(db, FH(), of, y)
    got = r.resolve([_korea_row("03481K", isin)], market="korea")["KRX:03481K"]
    assert got.status == "VERIFIED"
    assert got.source_mic == "XKOS"
    assert got.resolved_mic == "XKOS"
    assert got.yahoo_symbol == "03481K.KQ"
    assert r.stats["korea_krx_segment_ambiguity_yahoo_resolved"] == 1
    db.close()


def test_korea_ambiguous_exact_isin_can_resolve_xkrx(tmp_path):
    db = CacheDB(tmp_path / "kr_amb_xkrx.sqlite")
    isin = "KR703481K019"
    of = OFKoreaSegments({isin: ("03481K", {"XKRX", "XKOS"})})
    y = YHKoreaAmbiguity(
        search_candidates=[_korea_search_candidate("03481K.KS", "KSC")],
        quote=_korea_quote("03481K.KS", "KSC"),
    )
    r = BatchResolver(db, FH(), of, y)
    got = r.resolve([_korea_row("03481K", isin)], market="korea")["KRX:03481K"]
    assert got.status == "VERIFIED"
    assert got.resolved_mic == "XKRX"
    db.close()


@pytest.mark.parametrize("candidates,quote", [
    ([], None),
    ([_korea_search_candidate(), _korea_search_candidate("03481K.KS", "KSC")], _korea_quote()),
    ([_korea_search_candidate("999999.KQ")], _korea_quote("999999.KQ")),
    ([_korea_search_candidate(quote_type="MUTUALFUND")], _korea_quote(quote_type="MUTUALFUND")),
    ([_korea_search_candidate()], _korea_quote(currency="USD")),
    ([_korea_search_candidate()], _korea_quote(exchange="NMS", full_exchange_name="NasdaqGS")),
])
def test_korea_ambiguous_exact_isin_yahoo_evidence_fails_closed(tmp_path, candidates, quote):
    db = CacheDB(tmp_path / "kr_amb_fail.sqlite")
    isin = "KR703481K019"
    of = OFKoreaSegments({isin: ("03481K", {"XKRX", "XKOS"})})
    r = BatchResolver(db, FH(), of, YHKoreaAmbiguity(search_candidates=candidates, quote=quote))
    got = r.resolve([_korea_row("03481K", isin)], market="korea")["KRX:03481K"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "OPENFIGI_KOREA_SEGMENT_AMBIGUOUS:XKRX,XKOS"
    db.close()


def test_korea_ambiguous_exact_isin_requires_same_non_null_share_class(tmp_path):
    from tv_market_identity.models import OpenFigiIdentity
    class OFDifferentShares(OFKoreaSegments):
        def map_jobs(self, jobs):
            out = super().map_jobs(jobs)
            changed = []
            for job, identities in zip(jobs, out):
                if identities and job["micCode"] == "XKOS":
                    x = identities[0]
                    identities = [OpenFigiIdentity(x.figi, x.composite_figi, "DIFFERENT_SHARE", x.ticker, x.name, x.security_type, x.security_type2, x.exch_code)]
                changed.append(identities)
            return changed
    db = CacheDB(tmp_path / "kr_amb_share.sqlite")
    isin = "KR703481K019"
    of = OFDifferentShares({isin: ("03481K", {"XKRX", "XKOS"})})
    y = YHKoreaAmbiguity(search_candidates=[_korea_search_candidate()], quote=_korea_quote())
    r = BatchResolver(db, FH(), of, y)
    got = r.resolve([_korea_row("03481K", isin)], market="korea")["KRX:03481K"]
    assert got.status == "REJECTED"
    assert r.stats["korea_krx_segment_ambiguity_yahoo_resolved"] == 0
    db.close()


class YHCachedCefRuntime:
    batch_size = 75
    def __init__(self, quote_type):
        self.quote_type = quote_type
    def quotes(self, symbols):
        if "FSSL" not in symbols:
            return {}
        return {"FSSL": YahooQuote(
            "FSSL", "NYQ", "NYSE", "USD", self.quote_type,
            "us_market", "FS Specialty Lending Fund", None, 11.94, 0,
        )}


def _cached_cef_binding():
    return Binding(
        tv_id="NYSE:FSSL", tv_symbol="FSSL", tv_prefix="NYSE",
        tv_currency="USD", tv_type="fund", status="VERIFIED",
        yahoo_symbol="FSSL", yahoo_exchange="NYQ", yahoo_market="us_market",
        yahoo_quote_type="EQUITY", yahoo_currency="USD", yahoo_price=11.94,
        quote_status="FRESH", resolved_mic="XNYS", source_mic="XNYS",
        target_mic="XNYS", mapping_method="SAME_VENUE",
        finnhub_symbol="FSSL", finnhub_type="Closed-End Fund",
        resolver_version="0.4.56-policy456", cache_hit=True,
    )


@pytest.mark.parametrize("runtime_type", ["EQUITY", "ETF"])
def test_closed_end_fund_warm_cache_refresh_accepts_policy456_yahoo_types(tmp_path, runtime_type):
    db = CacheDB(tmp_path / f"cef-runtime-{runtime_type}.sqlite")
    resolver = BatchResolver(db, None, OF(), YHCachedCefRuntime(runtime_type))
    binding = _cached_cef_binding()
    resolver.refresh_cached_quotes({binding.tv_id: binding})
    assert binding.status == "VERIFIED"
    assert binding.yahoo_quote_type == runtime_type
    assert binding.quote_status == "FRESH"
    db.close()


def test_closed_end_fund_warm_cache_refresh_rejects_incompatible_yahoo_type(tmp_path):
    db = CacheDB(tmp_path / "cef-runtime-mutualfund.sqlite")
    resolver = BatchResolver(db, None, OF(), YHCachedCefRuntime("MUTUALFUND"))
    binding = _cached_cef_binding()
    resolver.refresh_cached_quotes({binding.tv_id: binding})
    assert binding.status == "REJECTED"
    assert binding.rejection_reason == "YAHOO_RUNTIME_MISMATCH:NYQ/USD/MUTUALFUND"
    db.close()

class OFGermanyXetrEtfEquity:
    batch_size = 100
    def __init__(self, *, scoped_ambiguous=False):
        self.scoped_ambiguous = scoped_ambiguous
        self.jobs = []
    def map_jobs(self, jobs):
        from tv_market_identity.models import OpenFigiIdentity
        self.jobs.extend(jobs)
        out = []
        for job in jobs:
            if job.get("micCode") != "XETR":
                out.append([])
                continue
            if job.get("idType") == "ID_EXCH_SYMBOL" and job.get("idValue") == "B4NA":
                # Production-equivalent behavior for this cohort: both strict
                # and type-fallback exchange-symbol mappings can return no row.
                out.append([])
            elif job.get("idType") == "ID_ISIN" and job.get("idValue") == "DE000PB8ALU2":
                identities = [OpenFigiIdentity(
                    figi="BBG_XETR_ISIN", composite_figi="BBG_XETR_ISIN_COMP",
                    share_class_figi="BBG_SHARE_XETR", ticker="B4NA",
                    name="BNP PAR RICI ENH ALUMINIUM", security_type="ETP",
                    security_type2="Mutual Fund", exch_code="GY",
                )]
                if self.scoped_ambiguous:
                    identities.append(OpenFigiIdentity(
                        figi="BBG_XETR_ISIN_ALT", composite_figi="BBG_XETR_ISIN_ALT_COMP",
                        share_class_figi="BBG_SHARE_XETR_ALT", ticker="B4NA",
                        name="BNP PAR RICI ENH ALUMINIUM", security_type="ETP",
                        security_type2="Mutual Fund", exch_code="GY",
                    ))
                out.append(identities)
            else:
                out.append([])
        return out


class YHGermanyXetrEtfEquity:
    batch_size = 75
    def __init__(self, *, exchange="GER", full_exchange_name="XETRA", currency="USD"):
        self.exchange = exchange
        self.full_exchange_name = full_exchange_name
        self.currency = currency
    def quotes(self, symbols):
        if "B4NA.DE" not in symbols:
            return {}
        return {"B4NA.DE": YahooQuote(
            "B4NA.DE", self.exchange, self.full_exchange_name, self.currency,
            "EQUITY", "de_market", "BNP PAR RICI ENH ALUMINIUM", None, 1.0, 15,
        )}


def _germany_xetr_etf_row():
    return TvRow(
        "XETR:B4NA", "XETR", "B4NA", "BNP PAR RICI ENH ALUMINIUM",
        "USD", "fund", ("etf",), None, None, 1.0,
        isin="DE000PB8ALU2", active_symbol=True,
    )


def test_germany_xetr_etf_yahoo_equity_requires_scoped_isin_same_share_class(tmp_path):
    db = CacheDB(tmp_path / "de-xetr-etf-equity.sqlite")
    of = OFGermanyXetrEtfEquity()
    resolver = BatchResolver(db, None, of, YHGermanyXetrEtfEquity())
    got = resolver.resolve([_germany_xetr_etf_row()], market="germany")["XETR:B4NA"]
    assert got.status == "VERIFIED"
    assert got.resolved_mic == "XETR"
    assert got.yahoo_symbol == "B4NA.DE"
    assert got.yahoo_quote_type == "EQUITY"
    assert resolver.stats["openfigi_germany_xetr_etf_equity_source_proven"] == 1
    assert resolver.stats["yahoo_germany_xetr_etf_equity_matches"] == 1
    assert any(j.get("idType") == "ID_ISIN" and j.get("idValue") == "DE000PB8ALU2" and j.get("micCode") == "XETR" for j in of.jobs)
    db.close()


def test_germany_xetr_etf_yahoo_equity_rejects_ambiguous_scoped_isin(tmp_path):
    db = CacheDB(tmp_path / "de-xetr-etf-equity-ambiguous-scoped.sqlite")
    resolver = BatchResolver(
        db, None, OFGermanyXetrEtfEquity(scoped_ambiguous=True),
        YHGermanyXetrEtfEquity(),
    )
    got = resolver.resolve([_germany_xetr_etf_row()], market="germany")["XETR:B4NA"]
    assert got.status == "REJECTED"
    assert got.rejection_reason == "YAHOO_TYPE_MISMATCH:EQUITY"
    assert resolver.stats["openfigi_germany_xetr_etf_equity_source_unconfirmed"] == 1
    db.close()


def test_germany_xetr_etf_yahoo_equity_rejects_wrong_yahoo_venue(tmp_path):
    db = CacheDB(tmp_path / "de-xetr-etf-equity-wrong-venue.sqlite")
    resolver = BatchResolver(
        db, None, OFGermanyXetrEtfEquity(),
        YHGermanyXetrEtfEquity(exchange="STU", full_exchange_name="Stuttgart"),
    )
    got = resolver.resolve([_germany_xetr_etf_row()], market="germany")["XETR:B4NA"]
    assert got.status == "REJECTED"
    assert got.rejection_reason.startswith("YAHOO_")
    assert resolver.stats["yahoo_germany_xetr_etf_equity_matches"] == 0
    db.close()
