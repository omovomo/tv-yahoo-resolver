import time

from tv_market_identity.cache import CacheDB
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote
from tv_market_identity.resolver import BatchResolver


def ofi(ticker, share, sec_type="Common Stock", sec_type2="Common Stock", figi=None):
    return OpenFigiIdentity(
        figi=figi or f"FIGI_{ticker}",
        composite_figi=f"COMP_{ticker}",
        share_class_figi=share,
        ticker=ticker,
        name="TEST SECURITY",
        security_type=sec_type,
        security_type2=sec_type2,
        exch_code=None,
    )


class OFRegionalAlias:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "IT0001472171" and job.get("micCode") == "XSTU":
                # One exact ISIN/share class, but two provider ticker aliases.
                out.append([
                    ofi("EDJ", "SHARE1", figi="FIGI_EDJ"),
                    ofi("CED", "SHARE1", figi="FIGI_CED"),
                ])
            else:
                out.append([])
        return out


class YHRegionalAlias:
    batch_size = 75

    def quotes(self, symbols):
        out = {}
        if "EDJ.SG" in symbols:
            out["EDJ.SG"] = YahooQuote(
                "EDJ.SG", "STU", "Stuttgart", "EUR", "EQUITY", "de_market",
                "Caltagirone Editore", None, 2.62, 15,
            )
        return out


def test_final_exact_isin_rescue_allows_same_share_class_ticker_aliases(tmp_path):
    db = CacheDB(tmp_path / "alias.sqlite")
    resolver = BatchResolver(db, None, OFRegionalAlias(), YHRegionalAlias())
    row = TvRow(
        "LSX:502374", "LSX", "502374", "Caltagirone Editore S.p.A.", "EUR",
        "stock", ("common",), None, 1.0, 2.62, isin="IT0001472171",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_FINAL_EXACT_ISIN_RESCUE"
    assert b.target_mic == "XSTU"
    assert b.yahoo_symbol == "EDJ.SG"
    assert b.share_class_figi == "SHARE1"
    assert resolver.stats["germany_final_exact_isin_rescue_matches"] == 1
    db.close()


class OFReviewedUnit:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "US49435R1023" and job.get("micCode") == "XFRA":
                out.append([ofi("0R3", "UNIT_SHARE", "Unit", "Unit", "FIGI_UNIT")])
            else:
                out.append([])
        return out


class YHReviewedUnit:
    batch_size = 75

    def quotes(self, symbols):
        if "0R3.F" in symbols:
            return {"0R3.F": YahooQuote(
                "0R3.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "Kimbell Royalty Partners LP", None, 12.0, 15,
            )}
        return {}


def test_final_exact_isin_rescue_allows_reviewed_unit_only_with_normal_yahoo_equity(tmp_path):
    db = CacheDB(tmp_path / "unit.sqlite")
    resolver = BatchResolver(db, None, OFReviewedUnit(), YHReviewedUnit())
    row = TvRow(
        "GETTEX:0R3", "GETTEX", "0R3", "Kimbell Royalty Partners LP", "EUR",
        "stock", ("common",), None, 1.0, 12.0, isin="US49435R1023",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_FINAL_EXACT_ISIN_RESCUE_EQUITY_LIKE"
    assert b.target_mic == "XFRA"
    assert b.yahoo_symbol == "0R3.F"
    assert resolver.stats["germany_final_exact_isin_rescue_taxonomy_matches"] == 1
    db.close()


class OFClosedEnd:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "CH0038389992" and job.get("micCode") == "XFRA":
                out.append([ofi("BBZA", "CEF_SHARE", "Closed-End Fund", "Mutual Fund", "FIGI_CEF")])
            else:
                out.append([])
        return out


class YHClosedEnd:
    batch_size = 75

    def quotes(self, symbols):
        if "BBZA.F" in symbols:
            return {"BBZA.F": YahooQuote(
                "BBZA.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "BB Biotech AG", None, 55.0, 15,
            )}
        return {}


def test_final_exact_isin_rescue_allows_pure_listed_closed_end_fund_identity(tmp_path):
    db = CacheDB(tmp_path / "cef.sqlite")
    resolver = BatchResolver(db, None, OFClosedEnd(), YHClosedEnd())
    row = TvRow(
        "GETTEX:BBZA", "GETTEX", "BBZA", "BB Biotech AG", "EUR",
        "stock", ("common",), None, 1.0, 55.0, isin="CH0038389992",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_FINAL_EXACT_ISIN_RESCUE_LISTED_FUND"
    assert b.yahoo_symbol == "BBZA.F"
    assert resolver.stats["germany_final_exact_isin_rescue_listed_fund_matches"] == 1
    db.close()


class OFMixedFundTaxonomy:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "CH0006089921" and job.get("micCode") == "XFRA":
                out.append([
                    ofi("PEQ", "PEQ_SHARE", "Closed-End Fund", "Mutual Fund", "FIGI_CEF"),
                    ofi("PEQ", "PEQ_SHARE", "Pvt Eqty Fund", "Mutual Fund", "FIGI_PEF"),
                ])
            else:
                out.append([])
        return out


class YHMixedFundTaxonomy:
    batch_size = 75

    def quotes(self, symbols):
        if "PEQ.F" in symbols:
            return {"PEQ.F": YahooQuote(
                "PEQ.F", "FRA", "Frankfurt", "EUR", "EQUITY", "de_market",
                "Private Equity Holding AG", None, 70.0, 15,
            )}
        return {}


def test_final_exact_isin_rescue_keeps_mixed_private_equity_fund_taxonomy_fail_closed(tmp_path):
    db = CacheDB(tmp_path / "mixed_fund.sqlite")
    resolver = BatchResolver(db, None, OFMixedFundTaxonomy(), YHMixedFundTaxonomy())
    row = TvRow(
        "GETTEX:PEQ", "GETTEX", "PEQ", "Private Equity Holding AG", "EUR",
        "stock", ("common",), None, 1.0, 70.0, isin="CH0006089921",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "REJECTED"
    assert resolver.stats["germany_final_exact_isin_rescue_listed_fund_taxonomy_conflict"] == 1
    db.close()


class OFConflictingShares:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idType") == "ID_ISIN" and job.get("idValue") == "FR0000000001" and job.get("micCode") == "XSTU":
                out.append([
                    ofi("AAA", "SHARE_A", figi="FIGI_A"),
                    ofi("AAB", "SHARE_B", figi="FIGI_B"),
                ])
            else:
                out.append([])
        return out


class YHConflictingShares:
    batch_size = 75

    def quotes(self, symbols):
        out = {}
        for symbol in ("AAA.SG", "AAB.SG"):
            if symbol in symbols:
                out[symbol] = YahooQuote(
                    symbol, "STU", "Stuttgart", "EUR", "EQUITY", "de_market",
                    "Conflict", None, 1.0, 15,
                )
        return out


def test_final_exact_isin_rescue_rejects_conflicting_share_classes(tmp_path):
    db = CacheDB(tmp_path / "conflict.sqlite")
    resolver = BatchResolver(db, None, OFConflictingShares(), YHConflictingShares())
    row = TvRow(
        "LSX:CONFLICT", "LSX", "CONFLICT", "Conflict", "EUR",
        "stock", ("common",), None, 1.0, 1.0, isin="FR0000000001",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "REJECTED"
    assert resolver.stats["germany_final_exact_isin_rescue_target_share_ambiguous"] == 1
    db.close()


def test_policy53_reuses_policy49_verified_cache_entries(tmp_path):
    db = CacheDB(tmp_path / "policy49.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="XETR:DTE", tv_symbol="DTE", tv_prefix="XETR",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="DTE.DE", yahoo_exchange="GER", yahoo_market="de_market",
        yahoo_quote_type="EQUITY", yahoo_currency="EUR", resolved_mic="XETR",
        source_mic="XETR", target_mic="XETR", mapping_method="SAME_VENUE",
        resolver_version="0.3.49-policy49", validated_at=now,
        expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    row = TvRow(
        "XETR:DTE", "XETR", "DTE", "Deutsche Telekom AG", "EUR",
        "stock", ("common",), None, 1e11, 29.0,
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.cache_hit is True
    assert b.resolver_version == "0.3.49-policy49"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    db.close()

class OFShareSubtype:
    batch_size = 100

    def __init__(self, isin, ticker, share, sec_type, sec_type2, mic="XFRA"):
        self.isin = isin
        self.ticker = ticker
        self.share = share
        self.sec_type = sec_type
        self.sec_type2 = sec_type2
        self.mic = mic

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if (job.get("idType") == "ID_ISIN" and job.get("idValue") == self.isin
                    and job.get("micCode") == self.mic):
                out.append([ofi(self.ticker, self.share, self.sec_type, self.sec_type2)])
            else:
                out.append([])
        return out


class YHShareSubtype:
    batch_size = 75

    def __init__(self, symbol):
        self.symbol = symbol

    def quotes(self, symbols):
        if self.symbol not in symbols:
            return {}
        suffix = self.symbol.rsplit(".", 1)[-1]
        exchange = {"F": "FRA", "SG": "STU", "MU": "MUN"}.get(suffix, "FRA")
        name = {"FRA": "Frankfurt", "STU": "Stuttgart", "MUN": "Munich"}[exchange]
        return {self.symbol: YahooQuote(
            self.symbol, exchange, name, "EUR", "EQUITY", "de_market",
            "Subtype test", None, 10.0, 15,
        )}


def test_final_exact_isin_rescue_reconciles_tv_preferred_to_openfigi_common_stock(tmp_path):
    db = CacheDB(tmp_path / "preferred_common.sqlite")
    resolver = BatchResolver(
        db, None,
        OFShareSubtype("CH0010570767", "LSPP", "LINDT_PC", "Common Stock", "Common Stock"),
        YHShareSubtype("LSPP.F"),
    )
    row = TvRow(
        "GETTEX:LSPP", "GETTEX", "LSPP", "Lindt Partizipschein", "EUR",
        "stock", ("preferred",), None, 1.0, 10.0, isin="CH0010570767",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_FINAL_EXACT_ISIN_RESCUE_SHARE_SUBTYPE"
    assert b.yahoo_symbol == "LSPP.F"
    assert resolver.stats["germany_final_exact_isin_rescue_share_subtype_matches"] == 1
    db.close()


def test_final_exact_isin_rescue_reconciles_tv_common_to_openfigi_preference(tmp_path):
    db = CacheDB(tmp_path / "common_preference.sqlite")
    resolver = BatchResolver(
        db, None,
        OFShareSubtype("SE0010714311", "BJV0", "BJV_PREF", "Preference", "Preference"),
        YHShareSubtype("BJV0.F"),
    )
    row = TvRow(
        "LSX:A2JBXL", "LSX", "A2JBXL", "Test preference", "EUR",
        "stock", ("common",), None, 1.0, 10.0, isin="SE0010714311",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_FINAL_EXACT_ISIN_RESCUE_SHARE_SUBTYPE"
    assert resolver.stats["germany_final_exact_isin_rescue_share_subtype_matches"] == 1
    db.close()


def test_final_exact_isin_rescue_reconciles_tv_preferred_to_savings_share(tmp_path):
    db = CacheDB(tmp_path / "preferred_savings.sqlite")
    resolver = BatchResolver(
        db, None,
        OFShareSubtype("IT0003372205", "EDXR", "EDISON_SAV", "Savings Share", "Common Stock"),
        YHShareSubtype("EDXR.F"),
    )
    row = TvRow(
        "GETTEX:EDXR", "GETTEX", "EDXR", "Edison SpA", "EUR",
        "stock", ("preferred",), None, 1.0, 10.0, isin="IT0003372205",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_FINAL_EXACT_ISIN_RESCUE_SHARE_SUBTYPE"
    assert resolver.stats["germany_final_exact_isin_rescue_share_subtype_matches"] == 1
    db.close()


def test_policy54_reuses_policy53_verified_cache_entries(tmp_path):
    db = CacheDB(tmp_path / "policy53.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="XETR:DTE", tv_symbol="DTE", tv_prefix="XETR",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="DTE.DE", yahoo_exchange="GER", yahoo_market="de_market",
        yahoo_quote_type="EQUITY", yahoo_currency="EUR", resolved_mic="XETR",
        source_mic="XETR", target_mic="XETR", mapping_method="SAME_VENUE",
        resolver_version="0.3.53-policy53", validated_at=now,
        expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    row = TvRow(
        "XETR:DTE", "XETR", "DTE", "Deutsche Telekom AG", "EUR",
        "stock", ("common",), None, 1e11, 29.0,
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.cache_hit is True
    assert b.resolver_version == "0.3.53-policy53"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    db.close()


def test_policy55_reuses_policy54_verified_cache_entries(tmp_path):
    db = CacheDB(tmp_path / "policy54.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="XETR:DTE", tv_symbol="DTE", tv_prefix="XETR",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="DTE.DE", yahoo_exchange="GER", yahoo_market="de_market",
        yahoo_quote_type="EQUITY", yahoo_currency="EUR", resolved_mic="XETR",
        source_mic="XETR", target_mic="XETR", mapping_method="SAME_VENUE",
        resolver_version="0.3.54-policy54", validated_at=now,
        expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    row = TvRow(
        "XETR:DTE", "XETR", "DTE", "Deutsche Telekom AG", "EUR",
        "stock", ("common",), None, 1e11, 29.0,
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.cache_hit is True
    assert b.resolver_version == "0.3.54-policy54"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    db.close()


class OFEquityLikeEtf:
    batch_size = 100

    def __init__(self, isin, ticker, share, sec_type="Unit", sec_type2="Unit", mic="XFRA"):
        self.isin = isin
        self.ticker = ticker
        self.share = share
        self.sec_type = sec_type
        self.sec_type2 = sec_type2
        self.mic = mic

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if (job.get("idType") == "ID_ISIN" and job.get("idValue") == self.isin
                    and job.get("micCode") == self.mic):
                out.append([ofi(self.ticker, self.share, self.sec_type, self.sec_type2)])
            else:
                out.append([])
        return out


class YHEquityLikeEtf:
    batch_size = 75

    def __init__(self, symbol, quote_type="ETF", currency="EUR", exchange="FRA", full_exchange="Frankfurt", market="de_market"):
        self.symbol = symbol
        self.quote_type = quote_type
        self.currency = currency
        self.exchange = exchange
        self.full_exchange = full_exchange
        self.market = market

    def quotes(self, symbols):
        if self.symbol not in symbols:
            return {}
        return {self.symbol: YahooQuote(
            self.symbol, self.exchange, self.full_exchange, self.currency,
            self.quote_type, self.market, "ETF taxonomy test", None, 10.0, 15,
        )}


def test_final_exact_isin_rescue_allows_unit_with_explicit_matching_yahoo_etf_metadata(tmp_path):
    db = CacheDB(tmp_path / "unit_etf.sqlite")
    resolver = BatchResolver(
        db, None,
        OFEquityLikeEtf("CA23344H1091", "3IJ0", "DRI_SHARE", "Unit", "Unit", "XFRA"),
        YHEquityLikeEtf("3IJ0.F"),
    )
    row = TvRow(
        "FWB:3IJ0", "FWB", "3IJ0", "DRI Healthcare Trust", "EUR",
        "stock", ("common",), None, 1.0, 10.0, isin="CA23344H1091",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_FINAL_EXACT_ISIN_RESCUE_EQUITY_LIKE_YAHOO_ETF_TAXONOMY"
    assert b.yahoo_symbol == "3IJ0.F"
    assert resolver.stats["germany_final_exact_isin_rescue_yahoo_etf_taxonomy_matches"] == 1
    db.close()


def test_final_exact_isin_rescue_allows_stapled_unit_with_explicit_matching_yahoo_etf_metadata(tmp_path):
    db = CacheDB(tmp_path / "stapled_etf.sqlite")
    resolver = BatchResolver(
        db, None,
        OFEquityLikeEtf("AU000000BWP3", "GJZ", "BWP_SHARE", "Stapled Security", "Unit", "XFRA"),
        YHEquityLikeEtf("GJZ.F"),
    )
    row = TvRow(
        "LS:577633", "LS", "577633", "BWP Trust", "EUR",
        "stock", ("common",), None, 1.0, 2.0, isin="AU000000BWP3",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.mapping_method == "GERMANY_FINAL_EXACT_ISIN_RESCUE_EQUITY_LIKE_YAHOO_ETF_TAXONOMY"
    assert b.yahoo_symbol == "GJZ.F"
    db.close()


def test_final_exact_isin_rescue_does_not_stack_equity_like_with_yahoo_mutualfund(tmp_path):
    db = CacheDB(tmp_path / "unit_mutualfund.sqlite")
    resolver = BatchResolver(
        db, None,
        OFEquityLikeEtf("CA23344H1091", "3IJ0", "DRI_SHARE", "Unit", "Unit", "XFRA"),
        YHEquityLikeEtf("3IJ0.F", quote_type="MUTUALFUND"),
    )
    row = TvRow(
        "FWB:3IJ0", "FWB", "3IJ0", "DRI Healthcare Trust", "EUR",
        "stock", ("common",), None, 1.0, 10.0, isin="CA23344H1091",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "REJECTED"
    assert resolver.stats["germany_final_exact_isin_rescue_yahoo_etf_taxonomy_matches"] == 0
    db.close()


def test_final_exact_isin_rescue_yahoo_etf_requires_explicit_matching_currency_and_venue(tmp_path):
    db = CacheDB(tmp_path / "unit_etf_badmeta.sqlite")
    resolver = BatchResolver(
        db, None,
        OFEquityLikeEtf("CA23344H1091", "3IJ0", "DRI_SHARE", "Unit", "Unit", "XFRA"),
        YHEquityLikeEtf("3IJ0.F", currency=None, exchange="YHD", full_exchange="YHD", market="us_market"),
    )
    row = TvRow(
        "FWB:3IJ0", "FWB", "3IJ0", "DRI Healthcare Trust", "EUR",
        "stock", ("common",), None, 1.0, 10.0, isin="CA23344H1091",
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "REJECTED"
    assert resolver.stats["germany_final_exact_isin_rescue_yahoo_etf_taxonomy_matches"] == 0
    db.close()


def test_policy56_reuses_policy55_verified_cache_entries(tmp_path):
    db = CacheDB(tmp_path / "policy55.sqlite")
    now = int(time.time())
    db.put_bindings([Binding(
        tv_id="XETR:DTE", tv_symbol="DTE", tv_prefix="XETR",
        tv_currency="EUR", tv_type="stock", status="VERIFIED",
        yahoo_symbol="DTE.DE", yahoo_exchange="GER", yahoo_market="de_market",
        yahoo_quote_type="EQUITY", yahoo_currency="EUR", resolved_mic="XETR",
        source_mic="XETR", target_mic="XETR", mapping_method="SAME_VENUE",
        resolver_version="0.3.55-policy55", validated_at=now,
        expires_at=now + 86400,
    )])
    resolver = BatchResolver(db, None, None, None)
    row = TvRow(
        "XETR:DTE", "XETR", "DTE", "Deutsche Telekom AG", "EUR",
        "stock", ("common",), None, 1e11, 29.0,
    )
    b = resolver.resolve([row])[row.tv_id]
    assert b.status == "VERIFIED"
    assert b.cache_hit is True
    assert b.resolver_version == "0.3.55-policy55"
    assert resolver.stats["cache_compatible_verified_hits"] == 1
    db.close()
