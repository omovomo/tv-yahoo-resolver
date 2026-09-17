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
