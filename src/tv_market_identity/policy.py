from __future__ import annotations

from .models import FinnhubIdentity, TvRow, YahooQuote


RESOLVER_VERSION = "0.3.34-policy34"

# Direct mappings are used only when TradingView's prefix semantics are clear.
TV_PREFIX_TO_MIC = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "TSX": "XTSE",
    "TSXV": "XTSX",
    "XETR": "XETR",
    # TradingView TRADEGATE is handled by a cross-venue share-class bridge.
    # The exact source segment is discovered from OpenFIGI (XGAT/XGRM); do not
    # collapse it to Xetra.
    "TRADEGATE": None,
    "LSE": "XLON",
    # TradingView LSIN is London Stock Exchange (International Companies), a
    # provider namespace rather than one ISO MIC. XLON is the primary probe
    # (confirmed for lines such as LSIN:0Q0Y); XLOM is handled as a reviewed
    # secondary MIC for Professional Securities Market / ATT IOB lines.
    "LSIN": "XLON",
    "MIL": "XMIL",
    # TradingView SIX = SIX Swiss Exchange. Current Swiss blue-chip/main
    # equity venue MIC is XSWX; SIX is the provider prefix, not the MIC.
    "SIX": "XSWX",
    # TradingView AQUIS = Aquis Stock Exchange (AQSE operating MIC).
    "AQUIS": "AQSE",
    # Reviewed German regional/Frankfurt provider prefixes.
    "FWB": "XFRA",
    "DUS": "XDUS",
    "HAM": "XHAM",
    "EURONEXT": None,
}


# Non-US venues for which Yahoo exposes a different primary/listing venue.
# Admission requires OpenFIGI shareClassFIGI equality between source and target.
CROSS_VENUE_BRIDGES = {
    "TRADEGATE": {
        "source_mics": ("XGAT", "XGRM"),
        "target_mic": "XETR",
    },
}

# Source provider namespace is an OpenFIGI exchange code rather than an ISO MIC.
# Admission requires exact shareClassFIGI equality with the target MIC listing.
EXCHCODE_SHARE_CLASS_BRIDGES = {}

# TradingView AMEX includes instruments whose primary listing may be NYSE Arca.
# It is therefore a reviewed allowed set, not a 1:1 prefix->MIC map.

# Reviewed direct non-US namespaces where a strict target-provider fallback may
# be used after exhaustive OpenFIGI no-match. This does not invent FIGIs: Yahoo
# must explicitly confirm exact symbol, quote currency, security type and venue.
# Keep this list narrow and evidence-driven.
TARGET_PROVIDER_STRICT_FALLBACK_PREFIXES = {"LSE", "LSIN", "SIX", "AQUIS", "XETR", "FWB", "DUS", "HAM"}

# Rare exact-reference fallbacks for provider ambiguities that cannot be
# disambiguated by TradingView ticker+MIC alone.  Each entry is a reviewed
# TradingView provider identity -> authoritative ISIN binding, confirmed by the
# issuer/listing venue.  Resolver still asks OpenFIGI to validate the ISIN and
# target MIC; the registry is never treated as a direct Yahoo proof.
REVIEWED_ISIN_FALLBACKS = {
    # Rosebank Industries moved to the LSE Main Market; reviewed listing MIC XLON.
    "LSE:ROSE": {"isin": "JE00BSBJ5M88", "mic": "XLON"},
    # Bravura Solutions is represented on LSE AIM; AIM operating MIC is AIMX.
    "LSE:BVS": {"isin": "AU000000BVS9", "mic": "AIMX"},
}

# Reviewed temporary Yahoo ticker aliases for very recent exchange symbol changes.
# These aliases are never identity proof: they are tried only when an independent
# OpenFIGI-backed current TradingView identity already exists and the canonical
# Yahoo symbol is absent/incompatible.  Name tokens guard against ticker reuse.
REVIEWED_YAHOO_SYMBOL_ALIASES = {
    # Technology Minerals changed TIDM TM1 -> MNTL effective 2026-09-15.
    # Yahoo can lag the exchange and still expose the same issuer as TM1.L.
    "LSE:MNTL": {
        "symbol": "TM1.L",
        "name_tokens": ("TECHNOLOGY MINERALS", "MANTLE"),
    },
}

# Exact provider-taxonomy overrides backed by reviewed primary-source listing
# evidence. These entries never establish identity by themselves: production
# resolution must already have an independent OpenFIGI identity, and Yahoo must
# return the exact bounded symbol plus a non-conflicting currency (missing is
# tolerated). Normal London venue metadata must remain compatible; the only
# reviewed venue anomaly is Yahoo's exact synthetic tuple YHD/YHD/us_market,
# admitted together with quoteType=MUTUALFUND for these exact identities.
# The registry never establishes identity itself. ISIN is retained as auditable
# evidence metadata.
REVIEWED_YAHOO_MUTUALFUND_TAXONOMY = {
    # LSE: Primary MIC XLON; listing category certificates/depository receipts.
    # Citi DR directory independently identifies GDR - Reg S.
    "LSIN:BKM": {
        "kind": "ADR", "mic": "XLON", "isin": "US0637462005",
        "name_tokens": ("BANKMUSCAT", "BANK MUSCAT"),
    },
    # LSE: EFGD GDR (Reg S), ISIN US2684254020; Citi: GDR - Reg S.
    "LSIN:EFGD": {
        "kind": "ADR", "mic": "XLON", "isin": "US2684254020",
        "name_tokens": ("EFG HOLDING", "EFG HERMES"),
    },
    # LSE: Kakuzi equity shares, Primary MIC XLON, ISIN KE0000000281.
    "LSE:KAKU": {
        "kind": "STOCK", "mic": "XLON", "isin": "KE0000000281",
        "name_tokens": ("KAKUZI",),
    },
    # LSE: TGE Class A ordinary equity/CDI, Primary MIC XLON, ISIN KYG382681016.
    "LSE:TGE": {
        "kind": "STOCK", "mic": "XLON", "isin": "KYG382681016",
        "name_tokens": ("GENERATION ESSENTIALS",),
    },
}

# TradingView LSIN spans more than one London ISO MIC. XLON remains the
# primary probe for backward compatibility and Main Market/IOB lines; if an
# exact OpenFIGI lookup has no match, probe these reviewed secondary MICs
# before falling back to weaker target-provider-only evidence.
SECONDARY_MIC_FALLBACKS = {
    "LSIN": ("XLOM",),
}

TV_PREFIX_ALLOWED_MICS = {
    "NASDAQ": {"XNAS"},
    "NYSE": {"XNYS"},
    "AMEX": {"XASE", "ARCX"},
    # TradingView CBOE listings are Cboe BZX listings. BZX equity MIC = BATS.
    "CBOE": {"BATS"},
}

MIC_TO_YAHOO_SUFFIX = {
    "XTSE": ".TO",
    "XTSX": ".V",
    "XETR": ".DE",
    "XLON": ".L",
    # London Stock Exchange Professional Securities Market / ATT. Yahoo uses
    # the same International Order Book representation (.IL) for these lines.
    "XLOM": ".IL",
    "AIMX": ".L",
    "XPAR": ".PA",
    "XAMS": ".AS",
    "XMIL": ".MI",
    "XSWX": ".SW",
    "AQSE": ".AQ",
    "XFRA": ".F",
    "XDUS": ".DU",
    "XHAM": ".HM",
    "XHKG": ".HK",
    "XTKS": ".T",
    "XASX": ".AX",
}


def is_us_tv(row: TvRow) -> bool:
    # OTC is intentionally routed through the US Finnhub universe without a
    # prefix->MIC assumption. The actual MIC must be discovered from one unique
    # symbol/currency/type-compatible Finnhub row.
    return row.prefix in {"NASDAQ", "NYSE", "AMEX", "CBOE", "OTC"}


def punctuation_key(value: str) -> str:
    return value.upper().replace(".", "").replace("-", "").replace("/", "").replace(" ", "")


def preferred_series_key(value: str) -> str | None:
    """Canonical key for US preferred-series spelling only.

    Examples that intentionally collapse to the same key:
      BA/PA, BA-PA, BA-PRA, BA.PA, BA.PRA
      ORCL/PD, ORCL-PD, ORCL-PRD

    This is bounded to an explicit separator + P/PR + one series letter. It is
    not a generic fuzzy ticker normalizer.
    """
    import re
    v = value.upper().strip()
    m = re.fullmatch(r"([A-Z0-9.]+)[/ .-]P(?:R)?([A-Z])", v)
    if not m:
        return None
    root = punctuation_key(m.group(1))
    return f"{root}#P#{m.group(2)}"


def symbol_index_keys(value: str) -> list[str]:
    keys = ["P:" + punctuation_key(value)]
    ps = preferred_series_key(value)
    if ps:
        keys.append("PR:" + ps)
    return keys


def preferred_yahoo_variants(value: str) -> list[str]:
    """Small Yahoo candidate set for a preferred-series ticker."""
    import re
    v = value.upper().strip()
    m = re.fullmatch(r"([A-Z0-9.]+)[/ .-]P(?:R)?([A-Z])", v)
    if not m:
        return []
    root, series = m.group(1), m.group(2)
    # Yahoo commonly uses ROOT-PX; some upstream/reference feeds use ROOT-PRX.
    return [f"{root}-P{series}", f"{root}-PR{series}"]


def bounded_symbol_variants(symbol: str) -> list[str]:
    values = [symbol.upper()]
    values.extend(preferred_yahoo_variants(symbol))
    if "." in symbol:
        values.append(symbol.upper().replace(".", "-"))
    if "/" in symbol:
        values.append(symbol.upper().replace("/", "-"))
    if " " in symbol:
        values.append(symbol.upper().replace(" ", "-"))
    return list(dict.fromkeys(values))


def tv_type_kind(row: TvRow) -> str:
    t = (row.tv_type or "").lower()
    specs = {s.lower() for s in row.type_specs}
    # TradingView sometimes emits REITs as type=fund + typespecs=[reit].
    # REIT is an equity identity here, not an ETF/fund identity.
    if "reit" in specs:
        return "STOCK"
    if t == "fund" or "etf" in specs:
        return "ETF"
    if "preferred" in specs or t in {"preferred", "preferred stock"}:
        return "PREFERRED"
    if t in {"dr", "depositary receipt", "depositary_receipt"} or "dr" in specs or "depositary" in specs:
        return "ADR"
    return "STOCK"


EQUITY_LIKE_FINNHUB_TYPES = {
    "common stock",
    "reit",
    "mlp",
    "ny reg shrs",
    "tracking stk",
}


def finnhub_type_compatible(row: TvRow, fh_type: str | None) -> bool:
    """Identity compatibility, not investment eligibility.

    TradingView's ``type=stock`` is broader than Finnhub's security subtype
    taxonomy. REIT/MLP/NY registered shares/tracking stocks are still equity
    instruments for cross-provider identity purposes. The exact Finnhub subtype
    remains preserved on the Binding so a portfolio policy can exclude it later.
    """
    kind = tv_type_kind(row)
    v = (fh_type or "").lower()
    if kind == "ETF":
        return v in {"etp", "etf"}
    if kind == "PREFERRED":
        # Finnhub occasionally exposes listed preferred series with the coarse
        # security type ``PUBLIC``.  Accept that label only when TradingView
        # explicitly identifies the instrument as preferred *and* the ticker
        # has a bounded preferred-series spelling (e.g. BA/PA, ORCL/PD).
        if v == "public":
            return preferred_series_key(row.symbol) is not None
        return v in {"preferred stock", "preferred", "depositary receipt"}
    if kind == "ADR":
        return v in {"adr", "common stock", "ny reg shrs"}
    return v in EQUITY_LIKE_FINNHUB_TYPES


def yahoo_type_compatible(row: TvRow, quote_type: str | None) -> bool:
    kind = tv_type_kind(row)
    q = (quote_type or "").upper()
    if kind == "ETF":
        return q in {"ETF", "MUTUALFUND"}
    return q == "EQUITY"


def currency_unit(value: str | None) -> str | None:
    """Canonical quote unit without collapsing pounds into pence.

    TradingView uses ISO-style ``GBX`` for penny sterling while Yahoo uses the
    mixed-case display code ``GBp``.  ``GBP`` is pounds sterling and must remain
    distinct because silently treating GBP and GBX as equal creates a 100x price
    error.
    """
    if not value:
        return None
    raw = str(value).strip()
    if raw == "GBp" or raw.upper() == "GBX":
        return "GBX"
    if raw == "GBP":
        return "GBP"
    return raw.upper()


def currency_compatible(expected: str | None, actual: str | None) -> bool:
    a = currency_unit(expected)
    b = currency_unit(actual)
    return bool(a and b and a == b)


def openfigi_currency(value: str | None) -> str | None:
    """Currency to send to OpenFIGI mapping jobs.

    OpenFIGI distinguishes pounds sterling (GBP) from penny sterling (GBp).
    TradingView uses GBX and Yahoo uses GBp for penny-quoted London equities, so
    the mapping job must use OpenFIGI's exact mixed-case GBp enum value. The
    original TV/Yahoo quote units remain stored and validated separately.
    """
    if not value:
        return None
    unit = currency_unit(value)
    return "GBp" if unit == "GBX" else unit


def finnhub_identity_from_row(row: dict) -> FinnhubIdentity:
    return FinnhubIdentity(
        symbol=str(row.get("symbol") or ""),
        display_symbol=row.get("displaySymbol"),
        description=row.get("description"),
        currency=(str(row.get("currency")).upper() if row.get("currency") else None),
        security_type=row.get("type"),
        mic=(str(row.get("mic")).upper() if row.get("mic") else None),
        composite_figi=row.get("figi"),
        share_class_figi=row.get("shareClassFIGI"),
    )


def _london_yahoo_root(local_symbol: str) -> str:
    symbol = (local_symbol or "").upper().strip()
    symbol = symbol.rstrip("./")
    symbol = symbol.replace("/", "-")
    symbol = symbol.replace(".", "-")
    return symbol


def yahoo_listing_symbol(
    local_symbol: str,
    mic: str,
    tv_prefix: str | None = None,
    tv_kind: str | None = None,
) -> str:
    """Create the primary bounded Yahoo candidate for a verified local listing.

    Candidate generation is provider-aware but never identity proof by itself.
    Yahoo metadata is still validated before admission.

    * LSE/XLON ordinary London symbols use ``.L``.
    * TradingView ``LSIN`` is a provider namespace spanning International/IOB
      lines. Live wide-universe tests show that Yahoo frequently exposes these
      as ``.IL`` even when TradingView's broad type is ``stock``. Therefore
      ``.IL`` remains the primary LSIN candidate. For non-ADR LSIN rows the
      resolver may try one bounded ``.L`` alternative only if ``.IL`` fails the
      same strict Yahoo metadata contract.
    * TradingView Aquis symbols may carry a provider decoration ``.GB``
      (QED.GB); Yahoo AQSE uses the local root plus ``.AQ`` (QED.AQ).
    """
    symbol = (local_symbol or "").upper().strip()
    prefix = (tv_prefix or "").upper()
    if mic == "XLON":
        symbol = _london_yahoo_root(symbol)
        if prefix == "LSIN":
            return symbol + ".IL"
    if mic == "AQSE" and symbol.endswith(".GB"):
        symbol = symbol[:-3]
    suffix = MIC_TO_YAHOO_SUFFIX.get(mic, "")
    return symbol + suffix


def yahoo_listing_alternative_symbol(
    local_symbol: str,
    mic: str,
    tv_prefix: str | None = None,
    tv_kind: str | None = None,
) -> str | None:
    """Return one reviewed alternate Yahoo candidate, or ``None``.

    This is deliberately *not* a generic suffix search. The only current case
    is TradingView ``LSIN``: London international lines, including depositary
    receipts, can appear at Yahoo under ``.L`` rather than the primary ``.IL``
    representation. Resolver admission remains evidence-gated: ADR ``.L`` is
    tried only after independent OpenFIGI identity/venue proof, never on the
    Yahoo-only target-provider fallback. The normal exact Yahoo
    symbol/currency/type/venue checks still apply.
    """
    prefix = (tv_prefix or "").upper()
    # LSIN is a TradingView provider namespace. Yahoo can expose the same
    # London international line as either .IL or .L. Candidate generation is
    # intentionally bounded to exactly one alternate; resolver.py decides
    # whether the evidence level is strong enough to try it (ADR target-only
    # fallbacks remain prohibited because Yahoo alone cannot disambiguate
    # XLON from XLOM).
    if mic in {"XLON", "XLOM"} and prefix == "LSIN":
        return _london_yahoo_root(local_symbol) + ".L"
    return None


def yahoo_venue_compatible(mic: str | None, q: YahooQuote) -> bool:
    if not mic:
        return False
    code = (q.exchange or "").upper()
    name = (q.full_exchange_name or "").upper()
    allowed_codes = {
        "XNAS": {"NMS", "NGM", "NCM", "NAS"},
        "XNYS": {"NYQ", "NYS"},
        "ARCX": {"PCX"},
        "XASE": {"ASE", "YHD"},
        "XTSE": {"TOR"},
        "XTSX": {"VAN"},
        "XETR": {"GER"},
        "XLON": {"LSE", "IOB"},
        "XLOM": {"IOB", "LSE"},
        "AIMX": {"LSE"},
        "XSWX": {"EBS"},
        "AQSE": {"AQSE", "AQX"},
        "XFRA": {"FRA"},
        "XDUS": {"DUS"},
        "XHAM": {"HAM"},
        # Cboe BZX equity MIC / Yahoo exchange code.
        "BATS": {"BTS"},
        # OTCM is the ISO 10383 operating MIC for OTC Markets. Yahoo exposes
        # the market tier (OTCQX/OTCQB/Pink) rather than the operating MIC, so
        # an exact symbol + currency + security-type match may be admitted at
        # operating-MIC granularity when Yahoo confirms one of those tiers.
        "OTCM": {"OQX", "OQB", "PNK"},
        "OTCQ": {"OQX"},
        "OTCB": {"OQB"},
        "OTCD": {"PNK"},
        "PINX": {"PNK"},
        "PINC": {"PNK"},
        "PINI": {"PNK"},
        "PINL": {"PNK"},
        # Finnhub currently uses OOTC as a broad US OTC venue for symbols that
        # Yahoo further classifies into OTCQX/OTCQB/Pink/OTCID.  We therefore
        # treat OOTC as provider-level umbrella evidence, not as a segment MIC.
        # This compatibility is reached only after exact symbol, currency and
        # security-type checks have already succeeded.
        "OOTC": {"OEM", "OQX", "OQB", "PNK", "OID"},
    }
    if code in allowed_codes.get(mic, set()):
        return True
    hints = {
        "XNAS": ("NASDAQ",),
        "XNYS": ("NYSE", "NEW YORK STOCK EXCHANGE"),
        "ARCX": ("NYSE ARCA", "ARCA"),
        "XASE": ("NYSE AMERICAN", "AMERICAN STOCK EXCHANGE"),
        "XTSE": ("TORONTO",),
        "XTSX": ("TSX VENTURE",),
        "XETR": ("XETRA",),
        "XLON": ("LONDON", "IOB"),
        "XLOM": ("LONDON", "IOB", "PROFESSIONAL SECURITIES MARKET"),
        "AIMX": ("LONDON", "AIM"),
        "XSWX": ("SWISS", "SIX SWISS"),
        "AQSE": ("AQUIS", "AQSE"),
        "XFRA": ("FRANKFURT",),
        "XDUS": ("DUSSELDORF", "DÜSSELDORF"),
        "XHAM": ("HAMBURG",),
        "BATS": ("CBOE US", "CBOE BZX", "BZX"),
        "OTCM": ("OTC MARKETS OTCQX", "OTC MARKETS OTCQB", "OTC MARKETS OTCPK", "OTCQX", "OTCQB", "OTCPK"),
        "OTCQ": ("OTCQX",),
        "OTCB": ("OTCQB",),
        "OTCD": ("OTC MARKETS OTCPK", "OTCPK", "OTCID"),
        "PINX": ("OTC MARKETS OTCPK", "OTCPK", "OTC PINK"),
        "PINC": ("OTC MARKETS OTCPK", "OTCPK", "OTC PINK"),
        "PINI": ("OTC MARKETS OTCPK", "OTCPK", "OTC PINK"),
        "PINL": ("OTC MARKETS OTCPK", "OTCPK", "OTC PINK"),
        "OOTC": (
            "OTHER OTC",
            "OTC MARKETS OTCQX",
            "OTC MARKETS OTCQB",
            "OTC MARKETS OTCPK",
            "OTC MARKETS OTCID",
            "OTCQX",
            "OTCQB",
            "OTCPK",
            "OTCID",
        ),
    }
    return any(h in name for h in hints.get(mic, ()))


def yahoo_market_compatible(mic: str | None, market: str | None) -> bool:
    """Fallback evidence when Yahoo omits exchange/fullExchangeName.

    This is intentionally narrow.  A Yahoo market bucket is weaker than an
    exchange code, so it is used only when venue metadata is completely absent
    and only for reviewed non-US targets.  Exact Yahoo symbol plus OpenFIGI
    listing proof are still required by the resolver before this helper is used.
    """
    if not mic or not market:
        return False
    allowed = {
        "XLON": {"GB_MARKET"},
        "XLOM": {"GB_MARKET"},
        "AIMX": {"GB_MARKET"},
        "XETR": {"DE_MARKET"},
        "XTSE": {"CA_MARKET"},
        "XSWX": {"CH_MARKET"},
        "AQSE": {"GB_MARKET"},
        "XFRA": {"DE_MARKET"},
        "XDUS": {"DE_MARKET"},
        "XHAM": {"DE_MARKET"},
    }
    return market.upper() in allowed.get(mic, set())


def openfigi_security_type(row: TvRow) -> str:
    """Return OpenFIGI securityType2 for the TradingView instrument kind.

    OpenFIGI uses ``Preference`` (not ``Common Stock``) for German preferred
    shares such as XETR:VOW3. Keep this provider taxonomy explicit rather
    than weakening the mapping job and accepting unrelated equity classes.
    """
    kind = tv_type_kind(row)
    if kind == "ETF":
        return "Exchange Traded Product"
    if kind == "PREFERRED":
        return "Preference"
    if kind == "ADR":
        return "Depositary Receipt"
    return "Common Stock"


def openfigi_type_compatible(row: TvRow, identity) -> bool:
    """Post-response guard for OpenFIGI security taxonomy."""
    kind = tv_type_kind(row)
    t1 = (getattr(identity, "security_type", None) or "").lower()
    t2 = (getattr(identity, "security_type2", None) or "").lower()
    values = {t1, t2}
    if kind == "ETF":
        return bool(values & {"exchange traded product", "etp", "etf"})
    if kind == "PREFERRED":
        return bool(values & {"preference", "preferred", "preferred stock"})
    if kind == "ADR":
        return bool(values & {"depositary receipt", "adr", "common stock"})
    # TradingView's broad stock type includes equity subtypes that OpenFIGI may
    # classify more specifically. These remain identity-compatible; investment
    # eligibility is a separate policy layer.
    return bool(values & {
        "common stock",
        "reit",
        "real estate investment trust",
        "mlp",
        "master limited partnership",
        "tracking stock",
        "tracking stk",
        "registered shares",
        "ny reg shrs",
        # OpenFIGI may expose REIT/common-equity listings under the broader
        # securityType2="Equity" taxonomy. This is accepted only after the
        # mapping job has already constrained exact local ticker + MIC +
        # currency; it is not a symbol-level heuristic.
        "equity",
    })
