from tv_market_identity.models import TvRow, YahooQuote
from tv_market_identity.policy import bounded_symbol_variants, finnhub_type_compatible, yahoo_venue_compatible, preferred_series_key, symbol_index_keys


def tv(symbol="BRK.B", prefix="NYSE", tv_type="stock", specs=("common",)):
    return TvRow(f"{prefix}:{symbol}", prefix, symbol, None, "USD", tv_type, specs, None, None, None)


def test_bounded_share_class_candidate():
    assert bounded_symbol_variants("BRK.B") == ["BRK.B", "BRK-B"]


def test_stock_type():
    assert finnhub_type_compatible(tv(), "Common Stock")
    assert not finnhub_type_compatible(tv(), "ETP")


def test_spy_arca_yahoo_venue():
    q = YahooQuote("SPY", "PCX", "NYSE Arca", "USD", "ETF", "us_market", None, None, 1.0, 0)
    assert yahoo_venue_compatible("ARCX", q)


def test_tv_dr_is_adr():
    assert finnhub_type_compatible(tv(symbol="BABA", prefix="NYSE", tv_type="dr", specs=("dr",)), "ADR")


def test_normalized_punctuation_is_candidate_only():
    from tv_market_identity.policy import punctuation_key
    assert punctuation_key("BRK.B") == punctuation_key("BRK-B") == punctuation_key("BRK/B") == punctuation_key("BRK B")


def test_stock_accepts_equity_like_finnhub_subtypes_for_identity():
    for subtype in ("REIT", "MLP", "NY Reg Shrs", "Tracking Stk"):
        assert finnhub_type_compatible(tv(), subtype)


def test_preferred_series_canonicalization_is_bounded():
    assert preferred_series_key("BA/PA") == preferred_series_key("BA-PRA") == preferred_series_key("BA-PA")
    assert preferred_series_key("ORCL/PD") == preferred_series_key("ORCL-PD") == preferred_series_key("ORCL-PRD")
    assert preferred_series_key("BRK.B") is None


def test_preferred_yahoo_candidates():
    vals = bounded_symbol_variants("BA-PRA")
    assert "BA-PA" in vals
    assert "BA-PRA" in vals


def test_preferred_type_is_identity_compatible():
    row = tv(symbol="BA/PA", prefix="NYSE", tv_type="stock", specs=("preferred",))
    assert finnhub_type_compatible(row, "Preferred Stock")
    assert not finnhub_type_compatible(row, "Common Stock")


def test_otc_and_bzx_yahoo_venues():
    otc = YahooQuote("DIDIY", "PNK", "OTC Markets OTCPK", "USD", "EQUITY", "us_market", None, None, 1.0, 15)
    bzx = YahooQuote("CBOE", "BTS", "Cboe US", "USD", "EQUITY", "us_market", None, None, 1.0, 0)
    assert yahoo_venue_compatible("PINX", otc)
    assert yahoo_venue_compatible("BATS", bzx)
    assert not yahoo_venue_compatible("OTCQ", otc)


def test_otcm_operating_mic_accepts_yahoo_otc_markets_tiers():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    for code, name in [
        ("OQX", "OTC Markets OTCQX"),
        ("OQB", "OTC Markets OTCQB"),
        ("PNK", "OTC Markets OTCPK"),
    ]:
        q = YahooQuote(
            symbol="DIDIY", exchange=code, full_exchange_name=name,
            currency="USD", quote_type="EQUITY", market="us_market",
            short_name="x", long_name="x", price=1.0, delayed_by=15,
        )
        assert yahoo_venue_compatible("OTCM", q)


def test_public_is_only_compatible_for_bounded_preferred_series():
    from tv_market_identity.models import TvRow
    from tv_market_identity.policy import finnhub_type_compatible
    pref = TvRow(
        tv_id="NYSE:BA/PA", prefix="NYSE", symbol="BA/PA", name="",
        currency="USD", tv_type="stock", type_specs=("preferred",),
        sector="Finance", market_cap=1.0, close=1.0,
    )
    common = TvRow(
        tv_id="NYSE:BA", prefix="NYSE", symbol="BA", name="",
        currency="USD", tv_type="stock", type_specs=("common",),
        sector="Finance", market_cap=1.0, close=1.0,
    )
    assert finnhub_type_compatible(pref, "PUBLIC")
    assert not finnhub_type_compatible(common, "PUBLIC")


def test_ootc_finnhub_umbrella_accepts_observed_yahoo_otc_tiers():
    for code, name in [
        ("PNK", "OTC Markets OTCPK"),
        ("OQX", "OTC Markets OTCQX"),
        ("OQB", "OTC Markets OTCQB"),
        ("OID", "OTC Markets OTCID"),
        ("OEM", "Other OTC"),
    ]:
        q = YahooQuote(
            symbol="DIDIY", exchange=code, full_exchange_name=name,
            currency="USD", quote_type="EQUITY", market="us_market",
            short_name="x", long_name="x", price=1.0, delayed_by=15,
        )
        assert yahoo_venue_compatible("OOTC", q)


def test_ootc_umbrella_still_rejects_non_otc_venue():
    q = YahooQuote(
        symbol="DIDIY", exchange="NMS", full_exchange_name="NasdaqGS",
        currency="USD", quote_type="EQUITY", market="us_market",
        short_name="x", long_name="x", price=1.0, delayed_by=0,
    )
    assert not yahoo_venue_compatible("OOTC", q)


def test_openfigi_preferred_uses_preference_taxonomy():
    from tv_market_identity.policy import openfigi_security_type
    row = tv(symbol="VOW3", prefix="XETR", tv_type="stock", specs=("preferred",))
    assert openfigi_security_type(row) == "Preference"


def test_uk_pence_currency_unit_is_distinct_from_pounds():
    from tv_market_identity.policy import currency_compatible, openfigi_currency
    assert currency_compatible("GBX", "GBp")
    assert currency_compatible("GBp", "GBX")
    assert not currency_compatible("GBX", "GBP")
    assert not currency_compatible("GBP", "GBp")
    assert openfigi_currency("GBX") == "GBp"
    assert openfigi_currency("EUR") == "EUR"


def test_openfigi_adr_uses_depositary_receipt_taxonomy():
    from tv_market_identity.policy import openfigi_security_type
    row = tv(symbol="0K8D", prefix="LSE", tv_type="dr", specs=("",))
    assert openfigi_security_type(row) == "Depositary Receipt"


def test_xlon_yahoo_symbol_punctuation_is_bounded():
    from tv_market_identity.policy import yahoo_listing_symbol
    assert yahoo_listing_symbol("INF", "XLON") == "INF.L"
    assert yahoo_listing_symbol("BT.A", "XLON") == "BT-A.L"
    assert yahoo_listing_symbol("BT/A", "XLON") == "BT-A.L"
    assert yahoo_listing_symbol("AV.", "XLON") == "AV.L"
    assert yahoo_listing_symbol("BA.", "XLON") == "BA.L"
    assert yahoo_listing_symbol("RR.", "XLON") == "RR.L"
    assert yahoo_listing_symbol("SAP", "XETR") == "SAP.DE"
    assert yahoo_listing_symbol("700", "XHKG", "HKEX", "STOCK") == "0700.HK"
    assert yahoo_listing_symbol("5", "XHKG", "HKEX", "STOCK") == "0005.HK"
    assert yahoo_listing_symbol("939", "XHKG", "HKEX", "STOCK") == "0939.HK"
    assert yahoo_listing_symbol("9988", "XHKG", "HKEX", "STOCK") == "9988.HK"
    assert yahoo_listing_symbol("12345", "XHKG", "HKEX", "STOCK") == "12345.HK"
    assert yahoo_listing_symbol("A5G", "XDUB", "EURONEXT", "STOCK") == "A5G.IR"


def test_openfigi_broad_equity_type_is_compatible_after_exact_listing_constraints():
    from tv_market_identity.models import OpenFigiIdentity, TvRow
    from tv_market_identity.policy import openfigi_type_compatible
    row = TvRow("LSE:SGRO", "LSE", "SGRO", "SEGRO PLC", "GBX", "stock", ("common",), "Finance", 1e10, 900.0)
    identity = OpenFigiIdentity(
        figi="BBG_SGRO", composite_figi="BBG_SGRO_C", share_class_figi="BBG_SGRO_S",
        ticker="SGRO", name="SEGRO PLC", security_type="REIT", security_type2="Equity", exch_code="LN",
    )
    assert openfigi_type_compatible(row, identity)


def test_reviewed_yahoo_market_bucket_is_narrow():
    from tv_market_identity.policy import yahoo_market_compatible
    assert yahoo_market_compatible("XLON", "gb_market")
    assert not yahoo_market_compatible("XLON", "de_market")
    assert not yahoo_market_compatible("XNYS", "us_market")


def test_six_maps_to_current_swiss_mic_and_yahoo_suffix():
    from tv_market_identity.policy import TV_PREFIX_TO_MIC, MIC_TO_YAHOO_SUFFIX
    assert TV_PREFIX_TO_MIC["SIX"] == "XSWX"
    assert MIC_TO_YAHOO_SUFFIX["XSWX"] == ".SW"


def test_yahoo_swiss_venue_compatibility():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible, yahoo_market_compatible
    q = YahooQuote(symbol="LOGN.SW", currency="CHF", quote_type="EQUITY", exchange="EBS", full_exchange_name="Swiss", market="ch_market", short_name="Logitech", long_name="Logitech International S.A.", price=75.0, delayed_by=15)
    assert yahoo_venue_compatible("XSWX", q)
    assert yahoo_market_compatible("XSWX", "ch_market")


def test_lsin_suffix_depends_on_security_kind_and_both_london_venues_are_compatible():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_listing_symbol, yahoo_listing_alternative_symbol, yahoo_venue_compatible
    assert yahoo_listing_symbol("0QIU", "XLON", "LSIN", "STOCK") == "0QIU.IL"
    assert yahoo_listing_alternative_symbol("0QIU", "XLON", "LSIN", "STOCK") == "0QIU.L"
    assert yahoo_listing_symbol("SDIC", "XLON", "LSIN", "ADR") == "SDIC.IL"
    assert yahoo_listing_alternative_symbol("SDIC", "XLON", "LSIN", "ADR") == "SDIC.L"
    q_lse = YahooQuote("0QIU.L", "LSE", "London Stock Exchange", "DKK", "EQUITY", "gb_market", "Novo Nordisk", None, 300.0, 15)
    q_iob = YahooQuote("SDIC.IL", "IOB", "International Order Book", "USD", "EQUITY", "gb_market", "SDIC", None, 10.0, 15)
    assert yahoo_venue_compatible("XLON", q_lse)
    assert yahoo_venue_compatible("XLON", q_iob)


def test_tradingview_fund_reit_is_equity_identity_not_etf():
    from tv_market_identity.models import TvRow
    from tv_market_identity.policy import tv_type_kind, yahoo_type_compatible
    row = TvRow("LSIN:0YO9", "LSIN", "0YO9", "REIT", "EUR", "fund", ("reit",), None, 1.0, 1.0)
    assert tv_type_kind(row) == "STOCK"
    assert yahoo_type_compatible(row, "EQUITY")


def test_bx_swiss_prefix_maps_to_active_operating_mic_xbrn():
    from tv_market_identity.policy import TV_PREFIX_TO_MIC
    assert TV_PREFIX_TO_MIC["BX"] == "XBRN"


def test_yahoo_hongkong_venue_contract_accepts_reviewed_hkg_hkse_representation():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    q = YahooQuote(
        symbol="0700.HK", exchange="HKG", full_exchange_name="HKSE",
        currency="HKD", quote_type="EQUITY", market="hk_market",
        short_name="Tencent", long_name="Tencent Holdings Limited",
        price=600.0, delayed_by=15,
    )
    assert yahoo_venue_compatible("XHKG", q)


def test_yahoo_hongkong_venue_contract_rejects_other_exchange():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    q = YahooQuote(
        symbol="0700.HK", exchange="NMS", full_exchange_name="NasdaqGS",
        currency="HKD", quote_type="EQUITY", market="us_market",
        short_name="Tencent", long_name="Tencent Holdings Limited",
        price=600.0, delayed_by=15,
    )
    assert not yahoo_venue_compatible("XHKG", q)



def test_yahoo_ireland_venue_contract_accepts_reviewed_ise_irish_representation():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    q = YahooQuote(
        symbol="A5G.IR", exchange="ISE", full_exchange_name="Irish",
        currency="EUR", quote_type="EQUITY", market="ie_market",
        short_name="AIB Group", long_name="AIB Group plc",
        price=7.0, delayed_by=15,
    )
    assert yahoo_venue_compatible("XDUB", q)


def test_yahoo_ireland_venue_contract_rejects_other_exchange():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    q = YahooQuote(
        symbol="A5G.IR", exchange="NMS", full_exchange_name="NasdaqGS",
        currency="EUR", quote_type="EQUITY", market="us_market",
        short_name="AIB Group", long_name="AIB Group plc",
        price=7.0, delayed_by=15,
    )
    assert not yahoo_venue_compatible("XDUB", q)

def test_market_scoped_euronext_ireland_mic():
    from tv_market_identity.policy import tv_prefix_mic
    assert tv_prefix_mic("EURONEXT", "ireland") == "XDUB"
    assert tv_prefix_mic("euronext", "IRELAND") == "XDUB"


def test_euronext_is_not_globally_collapsed_to_dublin():
    from tv_market_identity.policy import tv_prefix_mic
    assert tv_prefix_mic("EURONEXT") is None
    assert tv_prefix_mic("EURONEXT", "france") is None
    assert tv_prefix_mic("EURONEXT", "netherlands") is None
    assert tv_prefix_mic("EURONEXT", "belgium") is None
    assert tv_prefix_mic("EURONEXT", "portugal") is None


def test_japan_tradingview_prefix_mics_are_distinct():
    from tv_market_identity.policy import tv_prefix_mic
    assert tv_prefix_mic("TSE", "japan") == "XTKS"
    assert tv_prefix_mic("NAG", "japan") == "XNGO"
    assert tv_prefix_mic("FSE", "japan") == "XFKA"
    assert tv_prefix_mic("SAPSE", "japan") == "XSAP"


def test_japan_regional_prefixes_do_not_collapse_to_tokyo():
    from tv_market_identity.policy import tv_prefix_mic
    assert tv_prefix_mic("NAG", "japan") != "XTKS"
    assert tv_prefix_mic("FSE", "japan") != "XTKS"
    assert tv_prefix_mic("SAPSE", "japan") != "XTKS"


def test_yahoo_tokyo_venue_contract_accepts_reviewed_jpx_tokyo_representation():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    q = YahooQuote(
        symbol="7203.T", exchange="JPX", full_exchange_name="Tokyo",
        currency="JPY", quote_type="EQUITY", market="jp_market",
        short_name="Toyota Motor", long_name="Toyota Motor Corporation",
        price=3000.0, delayed_by=20,
    )
    assert yahoo_venue_compatible("XTKS", q)


def test_yahoo_tokyo_venue_contract_rejects_other_exchange():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    q = YahooQuote(
        symbol="7203.T", exchange="NMS", full_exchange_name="NasdaqGS",
        currency="JPY", quote_type="EQUITY", market="us_market",
        short_name="Toyota Motor", long_name="Toyota Motor Corporation",
        price=3000.0, delayed_by=20,
    )
    assert not yahoo_venue_compatible("XTKS", q)


def test_japan_regional_yahoo_suffixes_are_venue_specific():
    from tv_market_identity.policy import MIC_TO_YAHOO_SUFFIX

    assert MIC_TO_YAHOO_SUFFIX["XTKS"] == ".T"
    assert MIC_TO_YAHOO_SUFFIX["XNGO"] == ".N"
    assert MIC_TO_YAHOO_SUFFIX["XFKA"] == ".F"
    assert MIC_TO_YAHOO_SUFFIX["XSAP"] == ".S"
    assert len({MIC_TO_YAHOO_SUFFIX[mic] for mic in ("XTKS", "XNGO", "XFKA", "XSAP")}) == 4


def test_yahoo_fukuoka_venue_contract_accepts_observed_representation():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    q = YahooQuote(
        symbol="5401.F", exchange="FKA", full_exchange_name="Fukuoka",
        currency="JPY", quote_type="EQUITY", market="jp_market",
        short_name="Nippon Steel", long_name="Nippon Steel Corporation",
        price=600.0, delayed_by=20,
    )
    assert yahoo_venue_compatible("XFKA", q)


def test_yahoo_sapporo_venue_contract_accepts_observed_representation():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    q = YahooQuote(
        symbol="5401.S", exchange="SAP", full_exchange_name="Sapporo",
        currency="JPY", quote_type="EQUITY", market="jp_market",
        short_name="Nippon Steel", long_name="Nippon Steel Corporation",
        price=600.0, delayed_by=20,
    )
    assert yahoo_venue_compatible("XSAP", q)


def test_yahoo_regional_japan_venue_contracts_reject_cross_venue_metadata():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import yahoo_venue_compatible
    fukuoka = YahooQuote(
        symbol="5401.F", exchange="FKA", full_exchange_name="Fukuoka",
        currency="JPY", quote_type="EQUITY", market="jp_market",
        short_name="Nippon Steel", long_name="Nippon Steel Corporation",
        price=600.0, delayed_by=20,
    )
    sapporo = YahooQuote(
        symbol="5401.S", exchange="SAP", full_exchange_name="Sapporo",
        currency="JPY", quote_type="EQUITY", market="jp_market",
        short_name="Nippon Steel", long_name="Nippon Steel Corporation",
        price=600.0, delayed_by=20,
    )
    assert not yahoo_venue_compatible("XSAP", fukuoka)
    assert not yahoo_venue_compatible("XFKA", sapporo)
    assert not yahoo_venue_compatible("XNGO", fukuoka)
    assert not yahoo_venue_compatible("XNGO", sapporo)


def test_korea_yahoo_suffixes_and_venue_contracts_are_segment_specific():
    from tv_market_identity.models import YahooQuote
    from tv_market_identity.policy import KOREA_KRX_CANDIDATE_MICS, MIC_TO_YAHOO_SUFFIX, yahoo_venue_compatible

    assert KOREA_KRX_CANDIDATE_MICS == ("XKRX", "XKOS")
    assert MIC_TO_YAHOO_SUFFIX["XKRX"] == ".KS"
    assert MIC_TO_YAHOO_SUFFIX["XKOS"] == ".KQ"

    kospi = YahooQuote("005930.KS", "KSC", "Korea Stock Exchange", "KRW", "EQUITY", "kr_market", None, None, 100.0, 20)
    kosdaq = YahooQuote("196170.KQ", "KOE", "KOSDAQ", "KRW", "EQUITY", "kr_market", None, None, 100.0, 20)
    assert yahoo_venue_compatible("XKRX", kospi)
    assert not yahoo_venue_compatible("XKOS", kospi)
    assert yahoo_venue_compatible("XKOS", kosdaq)
    assert not yahoo_venue_compatible("XKRX", kosdaq)
