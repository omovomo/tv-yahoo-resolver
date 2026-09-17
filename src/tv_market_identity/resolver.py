from __future__ import annotations

import hashlib
import json
import re
import time
from collections import defaultdict

from .cache import CacheDB
from .models import Binding, FinnhubIdentity, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from .policy import (
    CROSS_VENUE_BRIDGES,
    EXCHCODE_SHARE_CLASS_BRIDGES,
    ISIN_SHARE_CLASS_BRIDGES,
    GERMANY_REGIONAL_TARGET_MICS,
    KOREA_KRX_CANDIDATE_MICS,
    MIC_TO_YAHOO_SUFFIX,
    RESOLVER_VERSION,
    REVIEWED_ISIN_FALLBACKS,
    REVIEWED_YAHOO_SYMBOL_ALIASES,
    REVIEWED_YAHOO_MUTUALFUND_TAXONOMY,
    SECONDARY_MIC_FALLBACKS,
    TV_PREFIX_ALLOWED_MICS,
    TARGET_PROVIDER_STRICT_FALLBACK_PREFIXES,
    TV_PREFIX_TO_MIC,
    tv_prefix_mic,
    YAHOO_HOME_EXCHANGE_TO_MIC,
    bounded_symbol_variants,
    currency_compatible,
    finnhub_identity_from_row,
    finnhub_type_compatible,
    germany_exact_isin_listed_fund_compatible,
    germany_exact_isin_share_subtype_compatible,
    germany_exact_isin_stock_type_compatible,
    is_us_tv,
    openfigi_currency,
    openfigi_security_type,
    openfigi_type_compatible,
    punctuation_key,
    yahoo_listing_symbol,
    yahoo_listing_alternative_symbol,
    symbol_index_keys,
    tv_type_kind,
    yahoo_type_compatible,
    yahoo_venue_compatible,
    yahoo_market_compatible,
)
from .providers import FinnhubProvider, OpenFigiProvider, ProviderError, YahooProvider

CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS = ("0.4.50-policy450", "0.4.49-policy449", "0.4.48-policy448", "0.4.47-policy447", "0.4.46-policy446", "0.4.45-policy445", "0.4.44-policy444", "0.4.43-policy443", "0.4.42-policy442", "0.4.41-policy441", "0.4.40-policy440", "0.4.39-policy439", "0.4.38-policy438", "0.4.37-policy437", "0.4.36-policy436", "0.4.35-policy435", "0.4.34-policy434", "0.4.32-policy432", "0.4.29-policy429", "0.4.26-policy426", "0.4.23-policy423", "0.4.22-policy422", "0.4.21-policy421", "0.4.20-policy420", "0.4.19-policy419", "0.4.15-policy415", "0.4.8-policy48", "0.3.99-policy99", "0.3.95-policy95", "0.3.87-policy87", "0.3.84-policy84", "0.3.81-policy81", "0.3.79-policy79", "0.3.77-policy77", "0.3.74-policy74", "0.3.71-policy71", "0.3.67-policy67", "0.3.66-policy66", "0.3.62-policy62", "0.3.61-policy61", "0.3.59-policy59", "0.3.58-policy58", "0.3.56-policy56", "0.3.55-policy55", "0.3.54-policy54", "0.3.53-policy53", "0.3.49-policy49", "0.3.44-policy44")


def _telemetry_token(value: str | None) -> str:
    """Bound provider metadata into a stable, low-cardinality stats token."""
    if value is None:
        return "UNREPORTED"
    token = re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")
    return (token or "EMPTY")[:48]


def _yahoo_symbol_identity_keys(symbol: str | None) -> set[str]:
    """Return bounded ticker keys for a Yahoo search symbol.

    Yahoo home-market symbols usually append one venue suffix (``ORNAV.HE``,
    ``ALTRA.PA``).  The exact ISIN search supplies the full Yahoo symbol while
    OpenFIGI normally reports the local ticker without that suffix.  We compare
    only the full symbol and one rightmost-dot-stripped root after punctuation
    normalization; no name matching or suffix guessing is performed.
    """
    value = str(symbol or "").upper().strip()
    if not value:
        return set()
    keys = {punctuation_key(value)}
    if "." in value:
        root, suffix = value.rsplit(".", 1)
        if root and 1 <= len(suffix) <= 4 and suffix.isalnum():
            keys.add(punctuation_key(root))
    return {x for x in keys if x}


def _home_market_local_symbol(symbol: str | None, mic: str | None) -> str | None:
    """Return the exact local exchange symbol for one reviewed Yahoo MIC.

    This is not suffix guessing.  The MIC is first established from the
    reviewed Yahoo exchange-code map.  If that MIC has a configured Yahoo
    suffix, the exact suffix must already be present and is stripped once; for
    suffixless venues the Yahoo symbol itself must contain no dot suffix.
    """
    value = str(symbol or "").upper().strip()
    if not value or not mic:
        return None
    suffix = MIC_TO_YAHOO_SUFFIX.get(mic)
    if suffix:
        suffix = suffix.upper()
        if not value.endswith(suffix) or len(value) <= len(suffix):
            return None
        return value[:-len(suffix)]
    if "." in value:
        return None
    return value


def _home_market_quote_compatible(
    candidate: YahooSearchCandidate,
    q: YahooQuote | None,
) -> bool:
    """Strict Yahoo contract for exact-ISIN home-market quote routing."""
    if q is None or q.symbol != candidate.symbol:
        return False
    if (candidate.quote_type or "").upper() != "EQUITY":
        return False
    if (q.quote_type or "").upper() != "EQUITY":
        return False
    if not q.currency or not q.exchange:
        return False
    if candidate.exchange and candidate.exchange.upper() != q.exchange.upper():
        return False
    return True



def _select_openfigi_identity(row: TvRow, identities: list[OpenFigiIdentity]):
    """Select one security identity without inventing a venue-level FIGI.

    OpenFIGI can return multiple venue rows for the same exact ticker/MIC query.
    If every surviving row has the same non-null shareClassFIGI, the share-class
    identity is unambiguous even when OpenFIGI returns multiple composite/venue
    rows. Return a synthetic security-level identity with figi/compositeFIGI
    unset so the cache does not pretend one arbitrary lower-level identifier
    was authoritative.
    """
    exact = [
        x for x in identities
        if punctuation_key(x.ticker or "") == punctuation_key(row.symbol)
        and openfigi_type_compatible(row, x)
    ]
    if not exact:
        return None, False, "OPENFIGI_NO_MATCH"
    if len(exact) == 1:
        return exact[0], False, None

    shares = {x.share_class_figi for x in exact if x.share_class_figi}
    composites = {x.composite_figi for x in exact if x.composite_figi}
    all_have_share = all(bool(x.share_class_figi) for x in exact)
    # Share-class FIGI is explicitly the OpenFIGI level that links multiple
    # composite/venue FIGIs representing the same class of the same equity.
    # Therefore multiple exact ticker+MIC+currency rows are security-level
    # unambiguous when *all* surviving rows share one shareClassFIGI, even if
    # their compositeFIGIs differ. A compositeFIGI is retained only when all
    # rows agree on that level; venue FIGI is never chosen arbitrarily.
    if all_have_share and len(shares) == 1:
        first = exact[0]
        return OpenFigiIdentity(
            figi=None,
            composite_figi=(next(iter(composites)) if len(composites) == 1 else None),
            share_class_figi=next(iter(shares)),
            ticker=first.ticker or row.symbol,
            name=first.name,
            security_type=first.security_type,
            security_type2=first.security_type2,
            exch_code=None,
        ), True, None
    return None, False, f"OPENFIGI_AMBIGUOUS:{len(exact)}"


def _select_isin_bridge_target(
    row: TvRow,
    identities: list[OpenFigiIdentity],
    *,
    required_share_class: str | None = None,
) -> tuple[OpenFigiIdentity | None, bool]:
    """Select one security-level target from an exact ``ID_ISIN + MIC`` job.

    ``ID_ISIN`` already fixes the security identifier, so duplicate venue rows
    can be collapsed only when they also agree on one non-null shareClassFIGI
    and one normalized ticker.  No arbitrary venue FIGI is retained.
    """
    exact = [
        x for x in identities
        if openfigi_type_compatible(row, x)
        and (required_share_class is None or x.share_class_figi == required_share_class)
    ]
    if not exact:
        return None, False
    if len(exact) == 1:
        return exact[0], False

    shares = {x.share_class_figi for x in exact if x.share_class_figi}
    tickers = {punctuation_key(x.ticker or "") for x in exact if x.ticker}
    if (
        all(bool(x.share_class_figi) for x in exact)
        and all(bool(x.ticker) for x in exact)
        and len(shares) == 1
        and len(tickers) == 1
    ):
        composites = {x.composite_figi for x in exact if x.composite_figi}
        first = exact[0]
        return OpenFigiIdentity(
            figi=None,
            composite_figi=(next(iter(composites)) if len(composites) == 1 else None),
            share_class_figi=next(iter(shares)),
            ticker=first.ticker,
            name=first.name,
            security_type=first.security_type,
            security_type2=first.security_type2,
            exch_code=None,
        ), True
    return None, False


_IRELAND_XDUB_REVIEWED_OPENFIGI_TAXONOMY = {
    # Irish Continental Group: Euronext Dublin DOL describes the instrument as
    # units comprising an ordinary share; OpenFIGI reports Unit / Unit.
    "IE00BLP58571": {("unit", "unit")},
    # Greencoat Renewables: Euronext Dublin lists ordinary shares, while
    # OpenFIGI classifies the investment company as Closed-End Fund / Mutual Fund.
    "IE00BF2NR112": {("closed-end fund", "mutual fund")},
}


def _ireland_xdub_reviewed_type_compatible(row: TvRow, identity: OpenFigiIdentity) -> bool:
    if (row.tv_type or "").strip().lower() != "stock":
        return False
    isin = (row.isin or "").strip().upper()
    allowed = _IRELAND_XDUB_REVIEWED_OPENFIGI_TAXONOMY.get(isin, set())
    observed = (
        (identity.security_type or "").strip().lower(),
        (identity.security_type2 or "").strip().lower(),
    )
    return observed in allowed


def _select_ireland_isin_xdub_listing(
    row: TvRow, identities: list[OpenFigiIdentity]
) -> OpenFigiIdentity | None:
    """Select one Dublin listing from an unscoped exact-ISIN response.

    This is deliberately narrower than a generic UNIQUE_SHARE_CLASS rescue.
    The exact ISIN may return many venue rows; rows with missing shareClassFIGI
    are non-evidence, while all observed non-null share classes must agree.
    Admission then requires exactly one type-compatible Dublin (OpenFIGI
    ``exchCode=ID``) listing carrying that same shareClassFIGI and a venue FIGI.
    """
    compatible = [
        x for x in identities
        if openfigi_type_compatible(row, x)
        or _ireland_xdub_reviewed_type_compatible(row, x)
    ]
    shares = {x.share_class_figi for x in compatible if x.share_class_figi}
    if len(shares) != 1:
        return None
    share_class = next(iter(shares))
    dublin = [
        x for x in compatible
        if (x.exch_code or "").upper() == "ID"
        and x.share_class_figi == share_class
        and bool(x.figi)
    ]
    if len(dublin) != 1:
        return None
    return dublin[0]


def _strict_yahoo_mapping(mapping_method: str | None) -> bool:
    """Whether Yahoo must explicitly confirm currency, type and venue.

    These paths lack an ordinary provider-scoped OpenFIGI mapping or use a
    bounded alternate listing proof. They remain admissible only when Yahoo
    returns complete, non-conflicting metadata.
    """
    return mapping_method in {
        "TARGET_PROVIDER_STRICT_FALLBACK",
        "REVIEWED_ISIN_SECURITY_FALLBACK",
        "IRELAND_ISIN_UNIQUE_XDUB_LISTING",
        "JAPAN_XTKS_REIT_TAXONOMY",
        "JAPAN_XTKS_INFRASTRUCTURE_FUND_TAXONOMY",
    }


def _openfigi_explicit_depositary_receipt(identity: OpenFigiIdentity | None) -> bool:
    """Require explicit OpenFIGI DR taxonomy, not merely equity compatibility.

    ``openfigi_type_compatible`` intentionally accepts a few coarse provider
    labels for discovery.  The Yahoo MUTUALFUND exception below is narrower:
    it is allowed only when OpenFIGI itself explicitly identifies the security
    as a depositary receipt / ADR.
    """
    if identity is None:
        return False
    values = {
        (identity.security_type or "").strip().lower(),
        (identity.security_type2 or "").strip().lower(),
    }
    return bool(values & {
        "depositary receipt",
        "depositary receipts",
        "adr",
        "global depositary receipt",
        "gdr",
    })


def _lsin_dr_mutualfund_taxonomy_anomaly_compatible(
    row: TvRow,
    target_mic: str,
    expected_symbol: str,
    q: YahooQuote | None,
    identity: OpenFigiIdentity | None,
    mapping_method: str | None,
) -> bool:
    """Bounded Yahoo taxonomy exception for independently proven LSIN DRs.

    Yahoo currently labels some London IOB/PSM depositary receipts as
    ``MUTUALFUND`` even though TradingView and OpenFIGI identify the security as
    a DR.  This exception does *not* let Yahoo establish identity: it requires
    explicit OpenFIGI DR proof, a London MIC, the exact bounded Yahoo symbol,
    explicit matching currency, and explicit compatible venue metadata.

    Target-provider-only mappings are excluded because they have no independent
    OpenFIGI identity proof.
    """
    if row.prefix != "LSIN" or tv_type_kind(row) != "ADR":
        return False
    if target_mic not in {"XLON", "XLOM"}:
        return False
    if _strict_yahoo_mapping(mapping_method):
        return False
    if not _openfigi_explicit_depositary_receipt(identity):
        return False
    if q is None or q.symbol != expected_symbol:
        return False
    if (q.quote_type or "").upper() != "MUTUALFUND":
        return False
    # Unlike the ordinary OpenFIGI-backed path, this provider-taxonomy anomaly
    # requires Yahoo to corroborate both currency and venue explicitly.
    if q.currency is None or not currency_compatible(row.currency, q.currency):
        return False
    if q.exchange is None and q.full_exchange_name is None:
        return False
    return yahoo_venue_compatible(target_mic, q)




def _reviewed_yahoo_synthetic_yhd_venue(q: YahooQuote | None) -> bool:
    """Match Yahoo's exact synthetic delayed-quote venue artifact.

    Live Yahoo chart metadata can label reviewed non-US securities as
    ``MUTUALFUND`` while simultaneously reporting ``exchange=YHD``,
    ``fullExchangeName=YHD`` and ``market=us_market``.  This triplet is not
    treated as a real venue.  It is admissible only inside the exact reviewed
    taxonomy override, never by the generic venue policy.
    """
    if q is None:
        return False
    return (
        (q.exchange or "").upper() == "YHD"
        and (q.full_exchange_name or "").upper() == "YHD"
        and (q.market or "").lower() == "us_market"
    )


def _cached_reviewed_yahoo_mutualfund_yhd_compatible(
    binding: Binding, q: YahooQuote | None
) -> bool:
    """Preserve a cold-path reviewed YHD anomaly across cache refreshes."""
    rule = REVIEWED_YAHOO_MUTUALFUND_TAXONOMY.get(binding.tv_id)
    if not rule or q is None:
        return False
    if _strict_yahoo_mapping(binding.mapping_method):
        return False
    if binding.resolved_mic != str(rule.get("mic") or ""):
        return False
    if q.symbol != binding.yahoo_symbol:
        return False
    if (binding.yahoo_quote_type or "").upper() != "MUTUALFUND":
        return False
    if (q.quote_type or "").upper() != "MUTUALFUND":
        return False
    if q.currency is not None and not currency_compatible(binding.tv_currency, q.currency):
        return False
    return _reviewed_yahoo_synthetic_yhd_venue(q)

def _reviewed_yahoo_mutualfund_taxonomy_block_reason(
    row: TvRow,
    target_mic: str,
    expected_symbol: str,
    q: YahooQuote | None,
    identity: OpenFigiIdentity | None,
    mapping_method: str | None,
) -> str | None:
    """Return the first guard blocking the exact reviewed taxonomy override.

    ``None`` means every guard passed.  This helper intentionally mirrors the
    admission contract so live coverage runs can distinguish a provider-data
    limitation from an overly strict reviewed guard without weakening policy.
    """
    rule = REVIEWED_YAHOO_MUTUALFUND_TAXONOMY.get(row.tv_id)
    if not rule:
        return "NOT_REVIEWED"
    if identity is None:
        return "NO_OPENFIGI_IDENTITY"
    if _strict_yahoo_mapping(mapping_method):
        return "STRICT_MAPPING"
    if tv_type_kind(row) != str(rule.get("kind") or ""):
        return "KIND_MISMATCH"
    if target_mic != str(rule.get("mic") or ""):
        return "MIC_MISMATCH"
    if q is None:
        return "NO_YAHOO_ROW"
    if q.symbol != expected_symbol:
        return "SYMBOL_MISMATCH"
    if (q.quote_type or "").upper() != "MUTUALFUND":
        return "TYPE_NOT_MUTUALFUND"
    # The ordinary OpenFIGI-backed non-US contract already treats missing Yahoo
    # currency as absence of corroboration rather than a contradiction.  The
    # exact reviewed taxonomy override follows the same rule: an explicit Yahoo
    # currency must agree, but an unreported currency does not veto otherwise
    # independently proven identity.
    if q.currency is not None and not currency_compatible(row.currency, q.currency):
        return "CURRENCY_MISMATCH"
    if q.exchange is None and q.full_exchange_name is None:
        return "VENUE_UNREPORTED"
    if not yahoo_venue_compatible(target_mic, q) and not _reviewed_yahoo_synthetic_yhd_venue(q):
        return "VENUE_MISMATCH"
    tokens = tuple(str(x).upper() for x in rule.get("name_tokens", ()))
    row_name = (row.name or "").upper()
    if tokens and not any(token in row_name for token in tokens):
        return "NAME_MISMATCH"
    return None


def _reviewed_yahoo_mutualfund_taxonomy_anomaly_compatible(
    row: TvRow,
    target_mic: str,
    expected_symbol: str,
    q: YahooQuote | None,
    identity: OpenFigiIdentity | None,
    mapping_method: str | None,
) -> bool:
    """Exact reviewed exception for Yahoo ``MUTUALFUND`` misclassification."""
    return _reviewed_yahoo_mutualfund_taxonomy_block_reason(
        row, target_mic, expected_symbol, q, identity, mapping_method
    ) is None


def _germany_regional_yahoo_fund_taxonomy_anomaly_compatible(
    row: TvRow,
    target_mic: str,
    expected_symbol: str,
    q: YahooQuote | None,
    identity: OpenFigiIdentity | None,
    mapping_method: str | None,
) -> bool:
    """Bounded German regional Yahoo fund-taxonomy anomaly.

    Some thin German regional equity quotes are exposed by Yahoo as
    ``MUTUALFUND`` or ``ETF`` even though TradingView and an independent exact
    OpenFIGI mapping prove a common equity / REIT.  This exception never creates
    identity and is intentionally narrower than the ordinary non-US contract:
    it requires an exact ISIN-bearing common-stock TV row, explicit matching EUR
    currency, an explicit compatible German regional venue, and non-strict
    OpenFIGI-backed mapping evidence.
    """
    if q is None or identity is None or _strict_yahoo_mapping(mapping_method):
        return False
    if target_mic not in GERMANY_REGIONAL_TARGET_MICS:
        return False
    if row.prefix not in {"GETTEX", "LS", "LSX", "TRADEGATE", "FWB", "DUS", "HAM", "SWB", "MUN", "HAN"}:
        return False
    if not row.isin or tv_type_kind(row) != "STOCK":
        return False
    specs = {str(x).lower() for x in row.type_specs if x}
    if "common" not in specs:
        return False
    if q.symbol != expected_symbol or (q.quote_type or "").upper() not in {"MUTUALFUND", "ETF"}:
        return False
    if q.currency is None or not currency_compatible(row.currency, q.currency):
        return False
    if not yahoo_venue_compatible(target_mic, q):
        return False
    return openfigi_type_compatible(row, identity)


def _germany_final_equity_like_yahoo_etf_taxonomy_compatible(
    row: TvRow,
    target_mic: str,
    expected_symbol: str,
    q: YahooQuote | None,
    identity: OpenFigiIdentity | None,
) -> bool:
    """Exact-ISIN-only Yahoo ETF taxonomy anomaly for reviewed equity-like forms.

    This is deliberately narrower than the generic German Yahoo fund-taxonomy
    exception.  It is used only by the final exact-ISIN rescue after OpenFIGI
    has already identified a reviewed Unit/Stapled/Dutch-certificate/savings
    share under one non-null shareClassFIGI.  Yahoo may then disagree only on
    the *classification* (ETF), while symbol, EUR currency and German venue must
    explicitly corroborate the target listing.  MUTUALFUND, synthetic YHD,
    missing venue/currency and any other contradiction remain fail-closed.
    """
    if q is None or identity is None:
        return False
    if not germany_exact_isin_stock_type_compatible(row, identity):
        return False
    if target_mic not in GERMANY_REGIONAL_TARGET_MICS:
        return False
    if q.symbol != expected_symbol or (q.quote_type or "").upper() != "ETF":
        return False
    if q.currency is None or not currency_compatible(row.currency, q.currency):
        return False
    if q.exchange is None and q.full_exchange_name is None:
        return False
    return yahoo_venue_compatible(target_mic, q)


def _non_us_quote_compatible(row: TvRow, target_mic: str, expected_symbol: str, q: YahooQuote | None, target_only: bool) -> bool:
    """Return whether a Yahoo row satisfies the current non-US evidence contract.

    Normal OpenFIGI-backed mappings tolerate missing Yahoo metadata but never an
    explicit contradiction. Target-provider-only mappings require all key Yahoo
    metadata to be present because no OpenFIGI identity was available.
    """
    if q is None or q.symbol != expected_symbol:
        return False
    if target_only:
        if q.currency is None or not currency_compatible(row.currency, q.currency):
            return False
        if q.quote_type is None or not yahoo_type_compatible(row, q.quote_type):
            return False
        if q.exchange is None and q.full_exchange_name is None:
            return False
        return yahoo_venue_compatible(target_mic, q)
    if q.currency is not None and not currency_compatible(row.currency, q.currency):
        return False
    if q.quote_type is not None and not yahoo_type_compatible(row, q.quote_type):
        return False
    if q.exchange is None and q.full_exchange_name is None:
        return q.market is None or yahoo_market_compatible(target_mic, q.market)
    return yahoo_venue_compatible(target_mic, q)


def _non_us_quote_rejection_reason(
    row: TvRow,
    target_mic: str,
    expected_symbol: str,
    q: YahooQuote | None,
    target_only: bool,
    *,
    source: str | None = None,
) -> str | None:
    """Return the first exact Yahoo contradiction for diagnostics.

    Compatibility remains defined by ``_non_us_quote_compatible``. This helper
    exists only so a chart row that was returned but rejected is not later
    flattened into ``YAHOO_NO_MATCH``. Missing metadata on normal OpenFIGI-backed
    mappings remains tolerated exactly as before; target-only paths still require
    explicit metadata.
    """
    prefix = f"YAHOO_{source.upper()}_" if source else "YAHOO_"
    if q is None:
        return None
    if q.symbol != expected_symbol:
        return f"{prefix}SYMBOL_MISMATCH:{q.symbol}"

    if target_only and q.currency is None:
        return f"{prefix}CURRENCY_UNREPORTED_TARGET_ONLY"
    if q.currency is not None and not currency_compatible(row.currency, q.currency):
        return f"{prefix}CURRENCY_MISMATCH:{q.currency}"

    if target_only and q.quote_type is None:
        return f"{prefix}TYPE_UNREPORTED_TARGET_ONLY"
    if q.quote_type is not None and not yahoo_type_compatible(row, q.quote_type):
        return f"{prefix}TYPE_MISMATCH:{q.quote_type}"

    venue_missing = q.exchange is None and q.full_exchange_name is None
    if target_only and venue_missing:
        return f"{prefix}VENUE_UNREPORTED_TARGET_ONLY"
    if venue_missing:
        if q.market is not None and not yahoo_market_compatible(target_mic, q.market):
            return f"{prefix}MARKET_MISMATCH:{target_mic}->{q.market}"
    elif not yahoo_venue_compatible(target_mic, q):
        return f"{prefix}VENUE_MISMATCH:{target_mic}->{q.exchange}/{q.full_exchange_name}/{q.market}"

    return None


def _cached_home_market_quote_compatible(binding: Binding, q: YahooQuote | None) -> bool:
    """Refresh contract for a persisted exact-ISIN home-market binding."""
    if q is None or q.symbol != binding.yahoo_symbol:
        return False
    if (q.quote_type or "").upper() != "EQUITY":
        return False
    if not q.exchange or not q.currency:
        return False
    if not binding.yahoo_exchange or q.exchange.upper() != binding.yahoo_exchange.upper():
        return False
    if not binding.yahoo_currency or q.currency.upper() != binding.yahoo_currency.upper():
        return False
    return True


def _cached_non_us_quote_compatible(binding: Binding, q: YahooQuote | None) -> bool:
    if q is None or q.symbol != binding.yahoo_symbol:
        return False
    target_only = _strict_yahoo_mapping(binding.mapping_method)
    quote_type = (q.quote_type or "").upper()
    if q.quote_type is None and not target_only:
        type_ok = True
    elif binding.yahoo_quote_type and quote_type == (binding.yahoo_quote_type or "").upper():
        # The cached binding already records the Yahoo type that was admitted
        # during full discovery (including special TV classifications such as
        # REIT represented as fund+reit). Preserve that exact contract.
        type_ok = True
    else:
        type_ok = ((binding.tv_type or "").lower() == "fund" and quote_type in {"ETF", "MUTUALFUND"}) or \
                  ((binding.tv_type or "").lower() != "fund" and quote_type == "EQUITY")
    if target_only and q.quote_type is None:
        type_ok = False
    if target_only:
        currency_ok = q.currency is not None and currency_compatible(binding.tv_currency, q.currency)
    else:
        currency_ok = q.currency is None or currency_compatible(binding.tv_currency, q.currency)
    venue_missing = q.exchange is None and q.full_exchange_name is None
    if target_only:
        venue_ok = (not venue_missing) and yahoo_venue_compatible(binding.resolved_mic, q)
    elif venue_missing:
        venue_ok = q.market is None or yahoo_market_compatible(binding.resolved_mic, q.market)
    else:
        venue_ok = yahoo_venue_compatible(binding.resolved_mic, q)
        if not venue_ok and _cached_reviewed_yahoo_mutualfund_yhd_compatible(binding, q):
            venue_ok = True
    return type_ok and currency_ok and venue_ok


class BatchResolver:
    def __init__(
        self,
        cache: CacheDB,
        finnhub: FinnhubProvider | None,
        openfigi: OpenFigiProvider,
        yahoo: YahooProvider,
        verified_ttl_days: int = 60,
        rejected_ttl_hours: int = 6,
        finnhub_ttl_hours: int = 24,
    ):
        self.cache = cache
        self.finnhub = finnhub
        self.openfigi = openfigi
        self.yahoo = yahoo
        self.verified_ttl = verified_ttl_days * 86400
        self.rejected_ttl = rejected_ttl_hours * 3600
        self.finnhub_ttl = finnhub_ttl_hours * 3600
        self.stats = defaultdict(int)

    def resolve(
        self,
        rows: list[TvRow],
        refresh: bool = False,
        market: str | None = None,
        refresh_rejected: bool = False,
    ) -> dict[str, Binding]:
        self.market = market
        reset_openfigi_run_cache = getattr(self.openfigi, "reset_run_cache", None)
        if callable(reset_openfigi_run_cache):
            reset_openfigi_run_cache()
        reset_yahoo_run_cache = getattr(self.yahoo, "reset_run_cache", None)
        if callable(reset_yahoo_run_cache):
            reset_yahoo_run_cache()

        current = {r.tv_id: (r.currency, r.tv_type) for r in rows}
        ids = [r.tv_id for r in rows]
        cached = {} if refresh else self.cache.get_bindings(ids, RESOLVER_VERSION, current)
        if not refresh:
            for compatible_version in CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS:
                if compatible_version == RESOLVER_VERSION:
                    continue
                legacy = self.cache.get_bindings(ids, compatible_version, current)
                legacy_verified = {
                    tv_id: binding for tv_id, binding in legacy.items()
                    if binding.status == "VERIFIED" and tv_id not in cached
                }
                legacy_rejected = sum(
                    1 for tv_id, binding in legacy.items()
                    if binding.status == "REJECTED" and tv_id not in cached
                )
                cached.update(legacy_verified)
                self.stats["cache_compatible_verified_hits"] += len(legacy_verified)
                self.stats["cache_compatible_rejected_ignored"] += legacy_rejected
        if refresh_rejected and not refresh:
            rejected_cached_ids = {
                tv_id for tv_id, binding in cached.items()
                if binding.status == "REJECTED"
            }
            if rejected_cached_ids:
                cached = {
                    tv_id: binding for tv_id, binding in cached.items()
                    if tv_id not in rejected_cached_ids
                }
            self.stats["cache_rejected_refreshes"] += len(rejected_cached_ids)
        self.stats["cache_hits"] += len(cached)
        missing = [r for r in rows if r.tv_id not in cached]
        self.stats["cache_misses"] += len(missing)

        us = [r for r in missing if is_us_tv(r)]
        non_us = [r for r in missing if not is_us_tv(r)]
        new_bindings: list[Binding] = []
        if us:
            us_bindings = self._resolve_us(us)
            us_bindings = self._us_same_venue_mic_mismatch_rescue(us, us_bindings)
            us_bindings = self._us_same_venue_preferred_rescue(us, us_bindings)
            us_bindings = self._us_xnys_fund_unit_rescue(us, us_bindings)
            us_bindings = self._us_xnys_fund_unit_public_rescue(us, us_bindings)
            us_bindings = self._us_xnas_finnhub_public_preferred_segment_rescue(us, us_bindings)
            us_bindings = self._us_xnys_stock_common_unit_rescue(us, us_bindings)
            us_bindings = self._us_xnys_stock_common_royalty_trust_rescue(us, us_bindings)
            us_bindings = self._us_xnys_stock_common_ltd_part_rescue(us, us_bindings)
            us_bindings = self._us_arcx_stock_common_ltd_part_rescue(us, us_bindings)
            us_bindings = self._us_ootc_stock_common_ltd_part_rescue(us, us_bindings)
            us_bindings = self._us_ootc_stock_common_unit_rescue(us, us_bindings)
            us_bindings = self._us_ootc_fund_unit_unit_rescue(us, us_bindings)
            us_bindings = self._us_ootc_stock_common_unknown_type_rescue(us, us_bindings)
            us_bindings = self._us_ootc_stock_preferred_unknown_type_rescue(us, us_bindings)
            us_bindings = self._us_ootc_dr_unknown_type_public_preferred_rescue(us, us_bindings)
            us_bindings = self._us_xnys_stock_common_closed_end_fund_rescue(us, us_bindings)
            us_bindings = self._us_ootc_stock_common_royalty_trust_rescue(us, us_bindings)
            us_bindings = self._us_ootc_stock_common_closed_end_fund_rescue(us, us_bindings)
            us_bindings = self._us_ootc_dr_gdr_rescue(us, us_bindings)
            us_bindings = self._us_xnas_fund_unit_rescue(us, us_bindings)
            us_bindings = self._us_ootc_preferred_empty_type_public_rescue(us, us_bindings)
            us_bindings = self._us_otc_preferred_rescue(us, us_bindings)
            us_bindings = self._us_nyse_preferred_exact_isin_symbol_rescue(us, us_bindings)
            us_bindings = self._us_xnys_finnhub_no_symbol_preferred_exact_isin_rescue(us, us_bindings)
            new_bindings.extend(us_bindings)
        if non_us:
            new_bindings.extend(self._resolve_non_us(non_us))

        persistent = [b for b in new_bindings if not self._is_transient_rejection(b)]
        self.cache.put_bindings(persistent)
        self.stats["transient_rejections_not_cached"] += len(new_bindings) - len(persistent)
        out = dict(cached)
        out.update({b.tv_id: b for b in new_bindings})

        provider_metrics = getattr(self.openfigi, "metrics", None)
        if provider_metrics:
            for name, value in provider_metrics.items():
                self.stats[f"openfigi_provider_{name}"] = value
        yahoo_metrics = getattr(self.yahoo, "metrics", None)
        if yahoo_metrics:
            for name, value in yahoo_metrics.items():
                self.stats[f"yahoo_provider_{name}"] = value
        return out

    @staticmethod
    def _is_transient_rejection(binding: Binding) -> bool:
        if binding.status != "REJECTED":
            return False
        reason = binding.rejection_reason or ""
        return reason.startswith((
            "FINNHUB_UNAVAILABLE:",
            "OPENFIGI_UNAVAILABLE:",
            "YAHOO_UNAVAILABLE:",
        ))

    def _ensure_finnhub_us(self) -> None:
        age = self.cache.finnhub_age_seconds()
        if age is not None and age < self.finnhub_ttl:
            self.stats["finnhub_universe_cache_hits"] += 1
            return
        if self.finnhub is None:
            raise ProviderError("Finnhub US universe cache is stale/missing and FINNHUB_API_KEY is unavailable")
        rows = self.finnhub.us_symbols()
        self.stats["finnhub_http_calls"] += 1
        self.cache.replace_finnhub_us(rows)
        self.stats["finnhub_rows_refreshed"] += len(rows)

    def _resolve_us(self, rows: list[TvRow]) -> list[Binding]:
        try:
            self._ensure_finnhub_us()
        except ProviderError as exc:
            return [self._reject(r, f"FINNHUB_UNAVAILABLE: {exc}") for r in rows]

        # Load the ~31k-symbol US universe once and index locally.  The normalized
        # key is candidate generation only; admission still requires exact
        # currency/type/MIC compatibility and a unique surviving row.
        universe = self.cache.load_finnhub_universe()
        norm_index: dict[str, list[dict]] = defaultdict(list)
        for raw in universe:
            symbol = str(raw.get("symbol") or "").upper().strip()
            if symbol:
                for key in symbol_index_keys(symbol):
                    norm_index[key].append(raw)
        self.stats["finnhub_local_rows_indexed"] += len(universe)

        candidates: dict[str, tuple[TvRow, FinnhubIdentity, list[str]]] = {}
        rejected: list[Binding] = []
        all_yahoo_candidates: set[str] = set()

        for r in rows:
            raw_symbol_rows: list[dict] = []
            seen_raw: set[tuple] = set()
            for key in symbol_index_keys(r.symbol):
                for raw in norm_index.get(key, []):
                    identity_key = (
                        raw.get("symbol"), raw.get("mic"), raw.get("currency"),
                        raw.get("type"), raw.get("figi"), raw.get("shareClassFIGI"),
                    )
                    if identity_key not in seen_raw:
                        seen_raw.add(identity_key)
                        raw_symbol_rows.append(raw)
            if not raw_symbol_rows:
                rejected.append(self._reject(r, "FINNHUB_NO_SYMBOL"))
                continue

            identities = [finnhub_identity_from_row(raw) for raw in raw_symbol_rows]

            currency_ok = [fh for fh in identities if currency_compatible(r.currency, fh.currency)]
            if not currency_ok:
                actual = sorted({str(fh.currency or "?") for fh in identities})
                rejected.append(self._reject(r, f"FINNHUB_CURRENCY_MISMATCH:{','.join(actual)}"))
                continue

            type_ok = [fh for fh in currency_ok if finnhub_type_compatible(r, fh.security_type)]
            if not type_ok:
                actual = sorted({str(fh.security_type or "?") for fh in currency_ok})
                rejected.append(self._reject(r, f"FINNHUB_TYPE_MISMATCH:{','.join(actual)}"))
                continue

            allowed = TV_PREFIX_ALLOWED_MICS.get(r.prefix)
            mic_ok = type_ok if not allowed else [fh for fh in type_ok if fh.mic in allowed]
            if not mic_ok:
                actual = sorted({str(fh.mic or "?") for fh in type_ok})
                rejected.append(self._reject(r, f"FINNHUB_MIC_MISMATCH:{','.join(actual)}"))
                continue

            # De-duplicate identical provider identities before ambiguity check.
            unique: dict[tuple, FinnhubIdentity] = {}
            for fh in mic_ok:
                key = (fh.symbol, fh.mic, fh.currency, fh.security_type, fh.composite_figi, fh.share_class_figi)
                unique[key] = fh
            possible = list(unique.values())

            if len(possible) != 1:
                rejected.append(self._reject(r, f"FINNHUB_AMBIGUOUS:{len(possible)}"))
                continue

            fh = possible[0]
            yvars = bounded_symbol_variants(fh.symbol)
            candidates[r.tv_id] = (r, fh, yvars)
            all_yahoo_candidates.update(yvars)

        try:
            yahoo_quotes = self.yahoo.quotes(sorted(all_yahoo_candidates))
            self.stats["yahoo_http_batches"] += (len(all_yahoo_candidates) + self.yahoo.batch_size - 1) // self.yahoo.batch_size
        except ProviderError as exc:
            rejected.extend(self._reject(r, f"YAHOO_UNAVAILABLE: {exc}") for r, _, _ in candidates.values())
            return rejected

        verified: list[Binding] = []
        for r, fh, yvars in candidates.values():
            returned = [yahoo_quotes[ys] for ys in yvars if ys in yahoo_quotes]
            currency_ok = [q for q in returned if currency_compatible(r.currency, q.currency)]
            type_ok = [q for q in currency_ok if yahoo_type_compatible(r, q.quote_type)]
            admitted = [q for q in type_ok if yahoo_venue_compatible(fh.mic, q)]

            if len(admitted) != 1:
                if len(admitted) > 1:
                    reason = f"YAHOO_AMBIGUOUS:{len(admitted)}"
                elif not returned:
                    reason = "YAHOO_SYMBOL_NOT_FOUND"
                elif not currency_ok:
                    actual = sorted({str(q.currency or "?") for q in returned})
                    reason = f"YAHOO_CURRENCY_MISMATCH:{','.join(actual)}"
                elif not type_ok:
                    actual = sorted({str(q.quote_type or "?") for q in currency_ok})
                    reason = f"YAHOO_TYPE_MISMATCH:{','.join(actual)}"
                else:
                    venues = sorted({f"{q.exchange or '?'}|{q.full_exchange_name or '?'}" for q in type_ok})
                    reason = f"YAHOO_VENUE_MISMATCH:{fh.mic or '?'}->{';'.join(venues)}"
                rejected.append(self._reject(r, reason))
                continue
            verified.append(self._verified(r, fh=fh, of=None, y=admitted[0], mic=fh.mic))

        return verified + rejected

    def _us_same_venue_mic_mismatch_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue a US common-stock Finnhub MIC mismatch with exact source proof.

        Finnhub venue metadata is not allowed to override independently proven
        listing identity.  This path is same-venue only and requires exact TV
        ISIN, a reviewed one-to-one source MIC, one unscoped shareClassFIGI, one
        source-MIC OpenFIGI FIGI with the exact TV ticker and the same share
        class, plus one Yahoo exact-ISIN result whose symbol is exactly the TV
        symbol and whose quote satisfies currency/type/source-venue checks.
        Any missing, conflicting, or ambiguous evidence remains fail-closed.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            reason = b.rejection_reason if b else None
            source_mic = tv_prefix_mic(r.prefix, self.market)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not reason or not reason.startswith("FINNHUB_MIC_MISMATCH:"):
                continue
            if not r.isin or tv_type_kind(r) != "STOCK" or "common" not in specs:
                continue
            # Only a reviewed 1:1 prefix -> MIC is admissible here.  AMEX is
            # intentionally special-cased to XASE: its normal allowed set also
            # contains ARCX, so the rescue must prove the actual AMEX venue.
            if r.prefix == "AMEX":
                source_mic = "XASE"
            elif not source_mic:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = []
        for r in eligible:
            source_mic = "XASE" if r.prefix == "AMEX" else tv_prefix_mic(r.prefix, self.market)
            jobs.append({"idType": "ID_ISIN", "idValue": r.isin})
            jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": source_mic})
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_same_venue_mic_mismatch_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_same_venue_mic_mismatch_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, tuple[str, OpenFigiIdentity]] = {}
        for i, r in enumerate(eligible):
            source_mic = "XASE" if r.prefix == "AMEX" else tv_prefix_mic(r.prefix, self.market)
            unscoped = [x for x in mapped[2 * i] if openfigi_type_compatible(r, x)]
            source = [x for x in mapped[2 * i + 1] if openfigi_type_compatible(r, x)]
            shares = {x.share_class_figi for x in unscoped if x.share_class_figi}
            if len(shares) != 1:
                self.stats["us_same_venue_mic_mismatch_share_unconfirmed"] += 1
                continue
            share = next(iter(shares))
            source = [x for x in source if x.share_class_figi == share and str(x.ticker or "").upper() == r.symbol.upper()]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_same_venue_mic_mismatch_source_unconfirmed"] += 1
                continue
            of = next(x for x in source if x.figi == next(iter(figis)))
            proven[r.tv_id] = (source_mic, of)

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings

        rescued: dict[str, Binding] = {}
        for r in eligible:
            proof = proven.get(r.tv_id)
            if proof is None:
                continue
            source_mic, of = proof
            try:
                cs = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                continue
            # Exact-ISIN discovery itself must be unique and identify the exact
            # TradingView local symbol; quote filtering must not choose identity.
            if (
                len(cs) != 1
                or str(cs[0].symbol or "").upper() != r.symbol.upper()
                or str(cs[0].quote_type or "").upper() != "EQUITY"
            ):
                self.stats["us_same_venue_mic_mismatch_yahoo_search_unconfirmed"] += 1
                continue
            try:
                quotes = self.yahoo.quotes([cs[0].symbol])
            except ProviderError:
                continue
            q = quotes.get(cs[0].symbol)
            if q is None or not yahoo_type_compatible(r, q.quote_type):
                continue
            if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                continue
            if not yahoo_venue_compatible(source_mic, q):
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic=source_mic,
                source_mic=source_mic, target_mic=source_mic,
                mapping_method="US_SAME_VENUE_MIC_MISMATCH_EXACT_ISIN",
                source_of=of, target_of=of,
            )
            self.stats["us_same_venue_mic_mismatch_rescue_matches"] += 1

        if not rescued:
            return bindings
        return [rescued.get(b.tv_id, b) for b in bindings]

    def _us_same_venue_preferred_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue a US preferred share only with exact same-venue evidence.

        This path is deliberately narrower than the generic home-market rescue.
        It never crosses venues and therefore does not use a missing
        shareClassFIGI as a bridge.  Admission requires:

        * TradingView ``stock/preferred`` with an exact ISIN;
        * a reviewed source MIC;
        * exactly one compatible OpenFIGI FIGI from ``ID_ISIN + source MIC``
          whose taxonomy explicitly says Preferred Stock;
        * either one unique exact-ISIN Yahoo candidate satisfying the strict
          same-venue/currency/EQUITY quote contract, or, only when Yahoo exact
          ISIN discovery returns no candidates at all, the exact TradingView
          source symbol satisfying that same quote contract.

        Finnhub ``PUBLIC``/missing type is treated as incomplete taxonomy only
        inside this independently proven path.  Any ambiguity or contradiction
        remains fail-closed.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            reason = b.rejection_reason if b else None
            specs = {str(x).lower() for x in r.type_specs if x}
            if not reason or not reason.startswith("FINNHUB_TYPE_MISMATCH:"):
                continue
            actual = reason.split(":", 1)[1]
            if actual not in {"PUBLIC", "?"}:
                continue
            if tv_type_kind(r) != "PREFERRED" or "preferred" not in specs or not r.isin:
                continue
            if not tv_prefix_mic(r.prefix, self.market):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [
            {"idType": "ID_ISIN", "idValue": r.isin, "micCode": tv_prefix_mic(r.prefix, self.market)}
            for r in eligible
        ]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_preferred_same_venue_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_preferred_same_venue_openfigi_unavailable"] += len(jobs)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            compatible = [x for x in identities if openfigi_type_compatible(r, x)]
            preferred = [
                x for x in compatible
                if (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
                or (x.security_type or "").strip().lower() in {"preferred stock", "preferred", "preference"}
            ]
            figis = {x.figi for x in preferred if x.figi}
            # Exactly one venue FIGI is required.  If several provider rows
            # describe that same FIGI, retain one deterministically.
            if len(figis) != 1:
                self.stats["us_preferred_same_venue_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            chosen = next(x for x in preferred if x.figi == figi)
            proven[r.tv_id] = chosen
            self.stats["us_preferred_same_venue_source_proven"] += 1

        if not proven:
            return bindings

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not callable(search_fn):
            return bindings

        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []

        search_symbols = sorted({
            c.symbol for cs in searches.values() for c in cs if c.symbol
        })
        try:
            search_quotes = self.yahoo.quotes(search_symbols) if search_symbols else {}
        except ProviderError:
            search_quotes = {}

        # Exact TV symbol is a fallback only when exact-ISIN discovery returned
        # no candidates at all, matching the evidence tested in v0.3.70.
        tv_symbols = sorted({
            r.symbol for r in eligible
            if r.tv_id in proven and not searches.get(str(r.isin).upper().strip(), []) and r.symbol
        })
        try:
            tv_quotes = self.yahoo.quotes(tv_symbols) if tv_symbols else {}
        except ProviderError:
            tv_quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            if of is None:
                continue
            source_mic = tv_prefix_mic(r.prefix, self.market)
            cs = searches.get(str(r.isin).upper().strip(), [])
            admitted: list[YahooQuote] = []
            for c in cs:
                q = search_quotes.get(c.symbol)
                if (c.quote_type or "").upper() != "EQUITY" or q is None:
                    continue
                if not yahoo_type_compatible(r, q.quote_type):
                    continue
                if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                    continue
                if not yahoo_venue_compatible(source_mic, q):
                    continue
                admitted.append(q)

            method = "US_PREFERRED_SAME_VENUE_EXACT_ISIN_YAHOO"
            if cs:
                # Search ambiguity is fail-closed even if only one candidate
                # happens to survive quote filtering: exact-ISIN discovery must
                # identify one route, not ask quote metadata to choose among
                # multiple discovered symbols.
                if len(cs) != 1 or len(admitted) != 1:
                    self.stats["us_preferred_same_venue_yahoo_search_unconfirmed"] += 1
                    continue
                y = admitted[0]
            else:
                q = tv_quotes.get(r.symbol)
                if q is None or not yahoo_type_compatible(r, q.quote_type):
                    self.stats["us_preferred_same_venue_tv_symbol_unconfirmed"] += 1
                    continue
                if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                    self.stats["us_preferred_same_venue_tv_symbol_unconfirmed"] += 1
                    continue
                if not yahoo_venue_compatible(source_mic, q):
                    self.stats["us_preferred_same_venue_tv_symbol_unconfirmed"] += 1
                    continue
                y = q
                method = "US_PREFERRED_SAME_VENUE_EXACT_TV_SYMBOL"

            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=y, mic=source_mic,
                source_mic=source_mic, target_mic=source_mic,
                mapping_method=method, source_of=of, target_of=of,
            )
            self.stats["us_preferred_same_venue_rescue_matches"] += 1
            self.stats[f"us_preferred_same_venue_rescue_matches_{_telemetry_token(source_mic)}"] += 1

        if not rescued:
            return bindings
        return [rescued.get(b.tv_id, b) for b in bindings]

    def _us_xnys_fund_unit_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue NYSE fund/unit rows when Finnhub calls the security ``Unit``.

        v0.3.78 audited the complete full-US ``FINNHUB_TYPE_MISMATCH:Unit``
        cohort.  The XNYS fund/unit subset formed a clean 33/33 contract.  This
        path encodes only that demonstrated subset; it deliberately does not
        generalize to XNAS or TradingView stock/common rows.

        Admission requires exact ISIN, TradingView ``fund`` + ``unit``, XNYS,
        one unscoped OpenFIGI shareClassFIGI, one exact ``ID_ISIN + XNYS``
        venue FIGI explicitly classified Unit, matching shareClassFIGI, and one
        Yahoo exact-ISIN route confirmed as NYSE-compatible USD/EQUITY.  Yahoo
        symbols are discovered, never constructed.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Unit":
                continue
            if r.prefix != "NYSE" or (r.tv_type or "").lower() != "fund" or "unit" not in specs or not r.isin:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = []
        for r in eligible:
            jobs.append({"idType": "ID_ISIN", "idValue": r.isin})
            jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"})
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnys_fund_unit_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnys_fund_unit_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for i, r in enumerate(eligible):
            unscoped = mapped[2 * i]
            source = mapped[2 * i + 1]
            unscoped_shares = {x.share_class_figi for x in unscoped if x.share_class_figi}
            unit_source = [x for x in source if (
                (x.security_type or "").strip().lower() == "unit"
                or (x.security_type2 or "").strip().lower() == "unit"
            )]
            source_figis = {x.figi for x in unit_source if x.figi}
            source_shares = {x.share_class_figi for x in unit_source if x.share_class_figi}
            if len(unscoped_shares) != 1 or len(source_figis) != 1 or source_shares != unscoped_shares:
                self.stats["us_xnys_fund_unit_source_unconfirmed"] += 1
                continue
            figi = next(iter(source_figis))
            proven[r.tv_id] = next(x for x in unit_source if x.figi == figi and x.share_class_figi in unscoped_shares)
            self.stats["us_xnys_fund_unit_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_xnys_fund_unit_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_xnys_fund_unit_yahoo_unconfirmed"] += 1
                continue
            if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                self.stats["us_xnys_fund_unit_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNYS", q):
                self.stats["us_xnys_fund_unit_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNYS", source_mic="XNYS", target_mic="XNYS",
                mapping_method="US_XNYS_FUND_UNIT_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_xnys_fund_unit_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_xnys_fund_unit_public_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the audited NYSE fund/unit cohort reported as Finnhub PUBLIC.

        v0.3.83 found six fund/unit PUBLIC rejects with direct same-venue proof:
        exact TradingView ISIN + XNYS maps to exactly one OpenFIGI FIGI whose
        taxonomy is PUBLIC / Preferred Stock, while Yahoo exact-ISIN discovery
        returns exactly one ticker-correlated NYSE-compatible USD/EQUITY route.
        No shareClassFIGI is required because this path never crosses venues.
        XNAS and stock/preferred rows are deliberately outside this rule.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:PUBLIC":
                continue
            if r.prefix != "NYSE" or (r.tv_type or "").lower() != "fund" or "unit" not in specs or not r.isin:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnys_fund_unit_public_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnys_fund_unit_public_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            preferred_public = [x for x in identities if (
                (x.security_type or "").strip().lower() == "public"
                and (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
            )]
            figis = {x.figi for x in preferred_public if x.figi}
            if len(figis) != 1:
                self.stats["us_xnys_fund_unit_public_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in preferred_public if x.figi == figi)
            self.stats["us_xnys_fund_unit_public_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_xnys_fund_unit_public_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            ticker_ok = punctuation_key(r.symbol) in _yahoo_symbol_identity_keys(c.symbol)
            if not ticker_ok or (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_xnys_fund_unit_public_yahoo_unconfirmed"] += 1
                continue
            if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                self.stats["us_xnys_fund_unit_public_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNYS", q):
                self.stats["us_xnys_fund_unit_public_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNYS", source_mic="XNYS", target_mic="XNYS",
                mapping_method="US_XNYS_FUND_UNIT_PUBLIC_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_xnys_fund_unit_public_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_xnas_finnhub_public_preferred_segment_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue audited XNAS preferred PUBLIC mismatches with exact segment proof.

        OpenFIGI currently fails scoped ``ID_ISIN + XNAS`` for this cohort while
        its unscoped exact-ISIN record reports a concrete Nasdaq listing segment.
        Admission is therefore limited to a single unscoped PUBLIC / Preferred
        Stock FIGI and an independently discovered Yahoo exact-ISIN candidate on
        the *same* Nasdaq segment.  This is same-source evidence; it is not a
        cross-venue bridge and does not require shareClassFIGI.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:PUBLIC":
                continue
            if r.prefix != "NASDAQ" or tv_type_kind(r) != "PREFERRED" or not r.isin:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = []
        for r in eligible:
            jobs.append({"idType": "ID_ISIN", "idValue": r.isin})
            jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNAS"})
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnas_public_preferred_segment_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnas_public_preferred_segment_openfigi_unavailable"] += len(eligible)
            return bindings

        segment_pairs = {
            "NASDAQ/NGS": ("NMS", "NASDAQGS"),
            "NASDAQ/NGM": ("NGM", "NASDAQGM"),
            "NASDAQ/NCM": ("NCM", "NASDAQCM"),
        }
        proven: dict[str, tuple[OpenFigiIdentity, tuple[str, str]]] = {}
        for i, r in enumerate(eligible):
            unscoped = mapped[2 * i]
            scoped = mapped[2 * i + 1]
            qualifying = [x for x in unscoped if (
                x.figi
                and (x.security_type or "").strip().lower() == "public"
                and (x.security_type2 or "").strip().lower() == "preferred stock"
                and (x.exch_code or "").upper() in segment_pairs
            )]
            # The audited pathology is specifically scoped XNAS NO_MATCH.  Any
            # scoped result changes the evidence shape and must use another rule.
            if scoped or len(qualifying) != 1 or len(unscoped) != 1:
                self.stats["us_xnas_public_preferred_segment_identity_unconfirmed"] += 1
                continue
            of = qualifying[0]
            proven[r.tv_id] = (of, segment_pairs[(of.exch_code or "").upper()])
            self.stats["us_xnas_public_preferred_segment_identity_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            proof = proven.get(r.tv_id)
            if proof is None:
                continue
            of, (expected_code, expected_name) = proof
            qualifying = []
            for c in searches.get(r.tv_id, []):
                q = quotes.get(c.symbol)
                ticker_ok = punctuation_key(c.symbol.split('.')[0]) == punctuation_key(r.symbol)
                if not ticker_ok or (c.quote_type or "").upper() != "EQUITY" or q is None:
                    continue
                if (q.quote_type or "").upper() != "EQUITY":
                    continue
                if not q.currency or not r.currency or not currency_compatible(r.currency, q.currency):
                    continue
                if (q.exchange or "").upper() != expected_code:
                    continue
                if (q.full_exchange_name or "").upper() != expected_name:
                    continue
                qualifying.append((c, q))
            if len(qualifying) != 1:
                self.stats["us_xnas_public_preferred_segment_yahoo_unconfirmed"] += 1
                continue
            _, q = qualifying[0]
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNAS", source_mic="XNAS", target_mic="XNAS",
                mapping_method="US_XNAS_FINNHUB_PUBLIC_PREFERRED_EXACT_ISIN_SEGMENT",
                source_of=of, target_of=of,
            )
            self.stats["us_xnas_public_preferred_segment_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_xnys_stock_common_unit_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.4.14-audited XNYS stock/common Finnhub Unit cohort.

        Admission is same-venue and exact-identity only: exact TV ISIN, NYSE
        stock/common, one ``ID_ISIN + XNYS`` OpenFIGI FIGI classified
        Unit/Unit with a non-null shareClassFIGI, and one Yahoo exact-ISIN
        candidate equal to the TV ticker whose quote is NYSE-compatible,
        USD-compatible, and EQUITY. XNAS and OTC remain fail-closed.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Unit":
                continue
            if (r.prefix != "NYSE" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnys_stock_common_unit_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnys_stock_common_unit_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "unit"
                and (x.security_type2 or "").strip().lower() == "unit"
                and bool(x.share_class_figi)
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_xnys_stock_common_unit_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_xnys_stock_common_unit_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_xnys_stock_common_unit_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_xnys_stock_common_unit_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_xnys_stock_common_unit_yahoo_unconfirmed"] += 1
                continue
            if not q.currency or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_xnys_stock_common_unit_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNYS", q):
                self.stats["us_xnys_stock_common_unit_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNYS", source_mic="XNYS", target_mic="XNYS",
                mapping_method="US_XNYS_STOCK_COMMON_FINNHUB_UNIT_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_xnys_stock_common_unit_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_xnys_stock_common_royalty_trust_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.3.94-audited XNYS stock/common Royalty Trust cohort.

        Admission is deliberately same-venue and exact-identity only: TradingView
        must provide an exact ISIN for NYSE stock/common; the current rejection
        must be Finnhub ``Royalty Trst``; ``ID_ISIN + XNYS`` must yield exactly
        one Royalty Trst/Common Stock FIGI with the exact TV ticker; and Yahoo
        exact-ISIN discovery must yield exactly one exact-TV-symbol route whose
        quote is NYSE-compatible, reports a compatible currency, and is EQUITY.
        OTC and XNAS are outside this audited rule.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Royalty Trst":
                continue
            if (r.prefix != "NYSE" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnys_stock_common_royalty_trust_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnys_stock_common_royalty_trust_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "royalty trst"
                and (x.security_type2 or "").strip().lower() == "common stock"
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_xnys_stock_common_royalty_trust_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_xnys_stock_common_royalty_trust_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_xnys_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_xnys_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_xnys_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            if not q.currency or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_xnys_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNYS", q):
                self.stats["us_xnys_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNYS", source_mic="XNYS", target_mic="XNYS",
                mapping_method="US_XNYS_STOCK_COMMON_ROYALTY_TRUST_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_xnys_stock_common_royalty_trust_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_xnys_stock_common_ltd_part_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.3.96-audited XNYS stock/common Ltd Part cohort.

        This is intentionally narrower than a taxonomy override. Admission requires
        exact TV ISIN, an XNYS-scoped unique OpenFIGI source identity classified
        ``Ltd Part / Partnership Shares`` with exact ticker and a shareClassFIGI,
        plus exactly one Yahoo exact-ISIN candidate for the exact TV symbol whose
        quote is NYSE-compatible, currency-compatible, and EQUITY.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Ltd Part":
                continue
            if (r.prefix != "NYSE" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnys_stock_common_ltd_part_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnys_stock_common_ltd_part_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "ltd part"
                and (x.security_type2 or "").strip().lower() == "partnership shares"
                and bool((x.share_class_figi or "").strip())
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_xnys_stock_common_ltd_part_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_xnys_stock_common_ltd_part_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_xnys_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_xnys_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_xnys_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if not q.currency or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_xnys_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNYS", q):
                self.stats["us_xnys_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNYS", source_mic="XNYS", target_mic="XNYS",
                mapping_method="US_XNYS_STOCK_COMMON_LTD_PART_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_xnys_stock_common_ltd_part_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_arcx_stock_common_ltd_part_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.4.18-audited ARCX stock/common Ltd Part cohort.

        Admission requires exact TV ISIN, one ARCX-scoped OpenFIGI source FIGI
        classified ``Ltd Part / Partnership Shares`` with exact ticker and a
        shareClassFIGI, plus exactly one Yahoo exact-ISIN candidate for the exact
        TV symbol whose quote is ARCX-compatible, USD, and EQUITY.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Ltd Part":
                continue
            if (r.prefix != "AMEX" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "ARCX"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_arcx_stock_common_ltd_part_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_arcx_stock_common_ltd_part_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "ltd part"
                and (x.security_type2 or "").strip().lower() == "partnership shares"
                and bool((x.share_class_figi or "").strip())
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_arcx_stock_common_ltd_part_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_arcx_stock_common_ltd_part_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_arcx_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_arcx_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_arcx_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if (q.currency or "").upper() != "USD" or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_arcx_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("ARCX", q):
                self.stats["us_arcx_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="ARCX", source_mic="ARCX", target_mic="ARCX",
                mapping_method="US_ARCX_STOCK_COMMON_FINNHUB_LTD_PART_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_arcx_stock_common_ltd_part_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_stock_common_ltd_part_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.4.18-audited OOTC stock/common Ltd Part cohort.

        Admission requires exact TV ISIN, one OOTC-scoped OpenFIGI source FIGI
        classified ``Ltd Part / Partnership Shares`` with exact ticker and a
        shareClassFIGI, plus exactly one Yahoo exact-ISIN candidate for the exact
        TV symbol whose quote is OOTC-compatible, USD, and EQUITY.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Ltd Part":
                continue
            if (r.prefix != "OTC" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_ootc_stock_common_ltd_part_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_ootc_stock_common_ltd_part_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "ltd part"
                and (x.security_type2 or "").strip().lower() == "partnership shares"
                and bool((x.share_class_figi or "").strip())
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_ootc_stock_common_ltd_part_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_ootc_stock_common_ltd_part_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_ootc_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_ootc_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_ootc_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if (q.currency or "").upper() != "USD" or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_ootc_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("OOTC", q):
                self.stats["us_ootc_stock_common_ltd_part_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OOTC_STOCK_COMMON_FINNHUB_LTD_PART_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_ootc_stock_common_ltd_part_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_unit_exact_isin_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
        *,
        tv_type: str,
        required_spec: str,
        stat_prefix: str,
        mapping_method: str,
    ) -> list[Binding]:
        """Shared exact-identity backbone for the two v0.4.26 OOTC Unit gates."""
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Unit":
                continue
            if (r.prefix != "OTC" or (r.tv_type or "").lower() != tv_type
                    or required_spec not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats[f"{stat_prefix}_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats[f"{stat_prefix}_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "unit"
                and (x.security_type2 or "").strip().lower() == "unit"
                and bool((x.share_class_figi or "").strip())
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats[f"{stat_prefix}_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats[f"{stat_prefix}_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            qualifying: list[tuple[YahooSearchCandidate, YahooQuote]] = []
            if of is not None:
                for c in searches.get(r.tv_id, []):
                    if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                        continue
                    if (c.quote_type or "").upper() != "EQUITY":
                        continue
                    q = quotes.get(c.symbol)
                    if q is None or (q.quote_type or "").upper() != "EQUITY":
                        continue
                    if (q.currency or "").upper() != "USD":
                        continue
                    if r.currency and not currency_compatible(r.currency, q.currency):
                        continue
                    if not yahoo_venue_compatible("OOTC", q):
                        continue
                    qualifying.append((c, q))
            if len(qualifying) != 1:
                self.stats[f"{stat_prefix}_yahoo_unconfirmed"] += 1
                continue
            _, q = qualifying[0]
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method=mapping_method, source_of=of, target_of=of,
            )
            self.stats[f"{stat_prefix}_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_stock_common_unit_rescue(self, rows: list[TvRow], bindings: list[Binding]) -> list[Binding]:
        """v0.4.26: OOTC stock/common + Finnhub Unit, exact-ISIN only."""
        return self._us_ootc_unit_exact_isin_rescue(
            rows, bindings, tv_type="stock", required_spec="common",
            stat_prefix="us_ootc_stock_common_unit",
            mapping_method="US_OOTC_STOCK_COMMON_FINNHUB_UNIT_EXACT_ISIN",
        )

    def _us_ootc_fund_unit_unit_rescue(self, rows: list[TvRow], bindings: list[Binding]) -> list[Binding]:
        """v0.4.26: OOTC fund/unit + Finnhub Unit, exact-ISIN only."""
        return self._us_ootc_unit_exact_isin_rescue(
            rows, bindings, tv_type="fund", required_spec="unit",
            stat_prefix="us_ootc_fund_unit_unit",
            mapping_method="US_OOTC_FUND_UNIT_FINNHUB_UNIT_EXACT_ISIN",
        )

    def _us_ootc_stock_common_unknown_type_rescue(
        self, rows: list[TvRow], bindings: list[Binding]
    ) -> list[Binding]:
        """v0.4.29: rescue audited OOTC stock/common rows with empty Finnhub type.

        This is a narrow functional rule, not generic compatibility for an unknown
        Finnhub taxonomy. Exact ISIN + OOTC must expose exactly one Common Stock /
        Common Stock FIGI with a non-null shareClassFIGI and exact TV ticker. Yahoo
        exact-ISIN discovery must then yield exactly one qualifying exact-ticker,
        OOTC-compatible, USD, EQUITY route.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:?":
                continue
            if (r.prefix != "OTC" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_ootc_stock_common_unknown_type_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_ootc_stock_common_unknown_type_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "common stock"
                and (x.security_type2 or "").strip().lower() == "common stock"
                and bool((x.share_class_figi or "").strip())
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_ootc_stock_common_unknown_type_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_ootc_stock_common_unknown_type_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            qualifying: list[tuple[YahooSearchCandidate, YahooQuote]] = []
            if of is not None:
                for c in searches.get(r.tv_id, []):
                    if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                        continue
                    if (c.quote_type or "").upper() != "EQUITY":
                        continue
                    q = quotes.get(c.symbol)
                    if q is None or (q.quote_type or "").upper() != "EQUITY":
                        continue
                    if (q.currency or "").upper() != "USD":
                        continue
                    if r.currency and not currency_compatible(r.currency, q.currency):
                        continue
                    if not yahoo_venue_compatible("OOTC", q):
                        continue
                    qualifying.append((c, q))
            if len(qualifying) != 1:
                self.stats["us_ootc_stock_common_unknown_type_yahoo_unconfirmed"] += 1
                continue
            _, q = qualifying[0]
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OOTC_STOCK_COMMON_FINNHUB_UNKNOWN_TYPE_EXACT_ISIN",
                source_of=of, target_of=of,
            )
            self.stats["us_ootc_stock_common_unknown_type_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_stock_preferred_unknown_type_rescue(
        self, rows: list[TvRow], bindings: list[Binding]
    ) -> list[Binding]:
        """v0.4.32: narrow same-source OOTC stock/preferred rescue for Finnhub '?'.

        v0.4.30 showed that OOTC-scoped exact-ISIN OpenFIGI returns a unique
        preferred-security FIGI for the positive cohort, but its ticker is the
        preferred-series description (not the provider ticker) and shareClassFIGI
        is absent.  Admission therefore binds identity by exact ISIN + OOTC scope
        + unique FIGI + PRIVATE/Preferred Stock + OTC US exchCode, while Yahoo
        independently proves the exact TV ticker as OOTC/USD/EQUITY.  This is a
        same-source exception only; no cross-venue or generic '?' compatibility.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:?":
                continue
            if (r.prefix != "OTC" or (r.tv_type or "").lower() != "stock"
                    or "preferred" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_ootc_stock_preferred_unknown_type_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_ootc_stock_preferred_unknown_type_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "private"
                and (x.security_type2 or "").strip().lower() == "preferred stock"
                and (x.exch_code or "").strip().upper() == "OTC US"
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_ootc_stock_preferred_unknown_type_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_ootc_stock_preferred_unknown_type_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            qualifying: list[tuple[YahooSearchCandidate, YahooQuote]] = []
            if of is not None:
                for c in searches.get(r.tv_id, []):
                    if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                        continue
                    if (c.quote_type or "").upper() != "EQUITY":
                        continue
                    q = quotes.get(c.symbol)
                    if q is None or (q.quote_type or "").upper() != "EQUITY":
                        continue
                    if (q.currency or "").upper() != "USD":
                        continue
                    if r.currency and not currency_compatible(r.currency, q.currency):
                        continue
                    if not yahoo_venue_compatible("OOTC", q):
                        continue
                    qualifying.append((c, q))
            if len(qualifying) != 1:
                self.stats["us_ootc_stock_preferred_unknown_type_yahoo_unconfirmed"] += 1
                continue
            _, q = qualifying[0]
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OOTC_STOCK_PREFERRED_FINNHUB_UNKNOWN_TYPE_EXACT_ISIN",
                source_of=of, target_of=of,
            )
            self.stats["us_ootc_stock_preferred_unknown_type_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_dr_unknown_type_public_preferred_rescue(
        self, rows: list[TvRow], bindings: list[Binding]
    ) -> list[Binding]:
        """v0.4.34: same-source OOTC ADR rescue for Finnhub '?' + PUBLIC/Preferred Stock.

        v0.4.33 diagnostic proved a narrow OOTC DR/ADR cohort where exact-ISIN
        OpenFIGI source evidence is one OTC US PUBLIC/Preferred Stock FIGI with
        no shareClassFIGI, while Yahoo independently proves the exact TV ticker
        as OOTC/USD/EQUITY. This is an explicit taxonomy-boundary exception; it
        does not establish generic DR -> Preferred Stock compatibility.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:?":
                continue
            if (r.prefix != "OTC" or (r.tv_type or "").lower() != "dr"
                    or tv_type_kind(r) != "ADR" or not r.isin):
                continue
            if r.currency and str(r.currency).upper() != "USD":
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_ootc_dr_unknown_type_public_preferred_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_ootc_dr_unknown_type_public_preferred_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "public"
                and (x.security_type2 or "").strip().lower() == "preferred stock"
                and (x.exch_code or "").strip().upper() == "OTC US"
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_ootc_dr_unknown_type_public_preferred_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_ootc_dr_unknown_type_public_preferred_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            qualifying: list[tuple[YahooSearchCandidate, YahooQuote]] = []
            if of is not None:
                for c in searches.get(r.tv_id, []):
                    if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                        continue
                    if (c.quote_type or "").upper() != "EQUITY":
                        continue
                    q = quotes.get(c.symbol)
                    if q is None or (q.quote_type or "").upper() != "EQUITY":
                        continue
                    if (q.currency or "").upper() != "USD":
                        continue
                    if r.currency and not currency_compatible(r.currency, q.currency):
                        continue
                    if not yahoo_venue_compatible("OOTC", q):
                        continue
                    qualifying.append((c, q))
            if len(qualifying) != 1:
                self.stats["us_ootc_dr_unknown_type_public_preferred_yahoo_unconfirmed"] += 1
                continue
            _, q = qualifying[0]
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OOTC_DR_FINNHUB_UNKNOWN_TYPE_PUBLIC_PREFERRED_EXACT_ISIN",
                source_of=of, target_of=of,
            )
            self.stats["us_ootc_dr_unknown_type_public_preferred_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_xnys_stock_common_closed_end_fund_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.3.98-audited XNYS stock/common Closed-End Fund cohort.

        Admission requires exact TV ISIN, one XNYS-scoped OpenFIGI source FIGI
        with exact ticker, ``Closed-End Fund / Mutual Fund`` taxonomy and a
        shareClassFIGI, plus exactly one Yahoo exact-ISIN candidate for the
        exact TV symbol whose quote is NYSE-compatible, currency-compatible,
        and EQUITY.  No XNAS/OTC provider-gap exception is implied.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Closed-End Fund":
                continue
            if (r.prefix != "NYSE" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnys_stock_common_closed_end_fund_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnys_stock_common_closed_end_fund_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "closed-end fund"
                and (x.security_type2 or "").strip().lower() == "mutual fund"
                and bool((x.share_class_figi or "").strip())
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_xnys_stock_common_closed_end_fund_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_xnys_stock_common_closed_end_fund_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_xnys_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_xnys_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_xnys_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            if not q.currency or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_xnys_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNYS", q):
                self.stats["us_xnys_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNYS", source_mic="XNYS", target_mic="XNYS",
                mapping_method="US_XNYS_STOCK_COMMON_CLOSED_END_FUND_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_xnys_stock_common_closed_end_fund_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_xnas_fund_unit_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue NASDAQ fund/unit rows using the audited XNAS provider-gap contract.

        v0.3.80 found 146/146 rejected NASDAQ fund/unit rows with the same
        pattern: exact-ISIN OpenFIGI resolves one share class and classifies it
        as Unit, ``ID_ISIN + XNAS`` returns no rows, while Yahoo exact-ISIN
        independently returns the exact TradingView symbol on a Nasdaq venue
        with USD/EQUITY metadata.  The scoped OpenFIGI miss is therefore
        treated only as a demonstrated XNAS provider limitation for this narrow
        cohort, not as a generic permission to ignore source-MIC proof.

        Admission requires TV NASDAQ + fund/unit + exact ISIN, the existing
        Finnhub Unit rejection, exactly one unscoped OpenFIGI shareClassFIGI,
        at least one Unit identity in that share class whose ticker exactly
        equals the TV ticker, no scoped XNAS OpenFIGI rows, and exactly one
        Yahoo exact-ISIN candidate whose symbol exactly equals the TV ticker and
        whose quote is XNAS-compatible USD/EQUITY.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Unit":
                continue
            if r.prefix != "NASDAQ" or (r.tv_type or "").lower() != "fund" or "unit" not in specs or not r.isin:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = []
        for r in eligible:
            jobs.append({"idType": "ID_ISIN", "idValue": r.isin})
            jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNAS"})
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnas_fund_unit_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnas_fund_unit_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for i, r in enumerate(eligible):
            unscoped = mapped[2 * i]
            scoped = mapped[2 * i + 1]
            shares = {x.share_class_figi for x in unscoped if x.share_class_figi}
            if len(shares) != 1 or scoped:
                self.stats["us_xnas_fund_unit_identity_unconfirmed"] += 1
                continue
            share = next(iter(shares))
            units = [x for x in unscoped if (
                x.share_class_figi == share
                and ((x.security_type or "").strip().lower() == "unit"
                     or (x.security_type2 or "").strip().lower() == "unit")
                and (x.ticker or "").strip().upper() == r.symbol.strip().upper()
            )]
            if not units:
                self.stats["us_xnas_fund_unit_identity_unconfirmed"] += 1
                continue
            # Multiple venue FIGIs are normal in the unscoped response; the
            # share class, Unit taxonomy and exact ticker are the identity
            # invariants audited in v0.3.80.
            proven[r.tv_id] = units[0]
            self.stats["us_xnas_fund_unit_identity_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_xnas_fund_unit_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            if not c.symbol or c.symbol.strip().upper() != r.symbol.strip().upper():
                self.stats["us_xnas_fund_unit_yahoo_unconfirmed"] += 1
                continue
            q = quotes.get(c.symbol)
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_xnas_fund_unit_yahoo_unconfirmed"] += 1
                continue
            if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                self.stats["us_xnas_fund_unit_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNAS", q):
                self.stats["us_xnas_fund_unit_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNAS", source_mic="XNAS", target_mic="XNAS",
                mapping_method="US_XNAS_FUND_UNIT_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_xnas_fund_unit_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_nyse_preferred_exact_isin_symbol_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue NYSE slash-form preferred symbols via Yahoo exact-ISIN discovery.

        The Yahoo symbol is never constructed. Admission requires exact TV ISIN,
        exact XNYS OpenFIGI source proof for one Preferred Stock FIGI, exactly one
        Yahoo exact-ISIN candidate, punctuation correlation with the TV symbol,
        and an explicit NYSE/USD/EQUITY Yahoo quote for that returned candidate.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible = []
        for r in rows:
            b = by_id.get(r.tv_id)
            reason = b.rejection_reason if b else None
            specs = {str(x).lower() for x in r.type_specs if x}
            if r.prefix != "NYSE" or "/" not in (r.symbol or ""):
                continue
            if tv_type_kind(r) != "PREFERRED" or "preferred" not in specs or not r.isin:
                continue
            if not reason or not (reason.startswith("YAHOO_TYPE_MISMATCH:") or reason == "YAHOO_SYMBOL_NOT_FOUND"):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_nyse_preferred_symbol_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_nyse_preferred_symbol_openfigi_unavailable"] += len(jobs)
            return bindings

        proven = {}
        for r, identities in zip(eligible, mapped):
            preferred = [x for x in identities if openfigi_type_compatible(r, x) and (
                (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
                or (x.security_type or "").strip().lower() in {"preferred stock", "preferred", "preference"}
            )]
            figis = {x.figi for x in preferred if x.figi}
            if len(figis) != 1:
                self.stats["us_nyse_preferred_symbol_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in preferred if x.figi == figi)
            self.stats["us_nyse_preferred_symbol_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_nyse_preferred_symbol_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if punctuation_key(c.symbol) != punctuation_key(r.symbol):
                self.stats["us_nyse_preferred_symbol_punctuation_mismatch"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_nyse_preferred_symbol_yahoo_unconfirmed"] += 1
                continue
            if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                self.stats["us_nyse_preferred_symbol_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNYS", q):
                self.stats["us_nyse_preferred_symbol_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNYS", source_mic="XNYS", target_mic="XNYS",
                mapping_method="US_NYSE_PREFERRED_EXACT_ISIN_SYMBOL", source_of=of, target_of=of,
            )
            self.stats["us_nyse_preferred_symbol_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings


    def _us_xnys_finnhub_no_symbol_preferred_exact_isin_rescue(
        self, rows: list[TvRow], bindings: list[Binding]
    ) -> list[Binding]:
        """Rescue audited XNYS preferred listings missing from Finnhub universe.

        This is a same-source exact-ISIN rule, not a cross-venue bridge. The Yahoo
        symbol is discovered by exact ISIN and never constructed. shareClassFIGI
        is deliberately not required because OpenFIGI uniquely proves the exact
        ISIN on the same XNYS source venue.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if r.prefix != "NYSE" or "/" not in (r.symbol or "") or not r.isin:
                continue
            if not b or b.rejection_reason != "FINNHUB_NO_SYMBOL":
                continue
            if tv_type_kind(r) != "PREFERRED" or "preferred" not in specs:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "XNYS"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_xnys_no_symbol_preferred_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_xnys_no_symbol_preferred_openfigi_unavailable"] += len(jobs)
            return bindings

        proven = {}
        for r, identities in zip(eligible, mapped):
            preferred = [x for x in identities if
                (x.security_type or "").strip().upper() == "PUBLIC" and
                (x.security_type2 or "").strip().lower() == "preferred stock"]
            figis = {x.figi for x in preferred if x.figi}
            if len(figis) != 1:
                self.stats["us_xnys_no_symbol_preferred_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in preferred if x.figi == figi)
            self.stats["us_xnys_no_symbol_preferred_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_xnys_no_symbol_preferred_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if punctuation_key(c.symbol) != punctuation_key(r.symbol):
                self.stats["us_xnys_no_symbol_preferred_punctuation_mismatch"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_xnys_no_symbol_preferred_yahoo_unconfirmed"] += 1
                continue
            if (q.currency or "").upper() != "USD" or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_xnys_no_symbol_preferred_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("XNYS", q):
                self.stats["us_xnys_no_symbol_preferred_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="XNYS", source_mic="XNYS", target_mic="XNYS",
                mapping_method="US_XNYS_FINNHUB_NO_SYMBOL_PREFERRED_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_xnys_no_symbol_preferred_rescue_matches"] += 1
        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_stock_common_royalty_trust_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.4.18-audited OOTC stock/common Royalty Trst cohort.

        This is a same-source exact-identity rule, not a taxonomy override.
        Admission requires an OTC stock/common row with exact TV ISIN and a
        current ``FINNHUB_TYPE_MISMATCH:Royalty Trst`` rejection; exactly one
        ``ID_ISIN + OOTC`` OpenFIGI FIGI classified Royalty Trst/Common Stock
        with a non-null shareClassFIGI; and exactly one Yahoo exact-ISIN
        candidate whose symbol exactly equals the TV ticker and whose quote is
        OOTC-compatible, explicitly USD, and EQUITY.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Royalty Trst":
                continue
            if (r.prefix != "OTC" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_ootc_stock_common_royalty_trust_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_ootc_stock_common_royalty_trust_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "royalty trst"
                and (x.security_type2 or "").strip().lower() == "common stock"
                and bool(x.share_class_figi)
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_ootc_stock_common_royalty_trust_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_ootc_stock_common_royalty_trust_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_ootc_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_ootc_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_ootc_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            if (q.currency or "").upper() != "USD" or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_ootc_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("OOTC", q):
                self.stats["us_ootc_stock_common_royalty_trust_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OOTC_STOCK_COMMON_FINNHUB_ROYALTY_TRST_EXACT_ISIN",
                source_of=of, target_of=of,
            )
            self.stats["us_ootc_stock_common_royalty_trust_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_stock_common_closed_end_fund_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.4.18-audited OOTC stock/common Closed-End Fund cohort.

        This is a same-source exact-identity rule, not a taxonomy override.
        Admission requires an OTC stock/common row with exact TV ISIN and a
        current ``FINNHUB_TYPE_MISMATCH:Closed-End Fund`` rejection; exactly
        one ``ID_ISIN + OOTC`` OpenFIGI FIGI classified
        Closed-End Fund/Mutual Fund with exact TV ticker and non-null
        shareClassFIGI; and exactly one Yahoo exact-ISIN candidate whose symbol
        exactly equals the TV ticker and whose quote is OOTC-compatible,
        explicitly USD, and EQUITY.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:Closed-End Fund":
                continue
            if (r.prefix != "OTC" or (r.tv_type or "").lower() != "stock"
                    or "common" not in specs or not r.isin):
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_ootc_stock_common_closed_end_fund_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_ootc_stock_common_closed_end_fund_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "closed-end fund"
                and (x.security_type2 or "").strip().lower() == "mutual fund"
                and bool((x.share_class_figi or "").strip())
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_ootc_stock_common_closed_end_fund_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_ootc_stock_common_closed_end_fund_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_ootc_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_ootc_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_ootc_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            if (q.currency or "").upper() != "USD" or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_ootc_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("OOTC", q):
                self.stats["us_ootc_stock_common_closed_end_fund_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OOTC_STOCK_COMMON_FINNHUB_CLOSED_END_FUND_EXACT_ISIN",
                source_of=of, target_of=of,
            )
            self.stats["us_ootc_stock_common_closed_end_fund_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_dr_gdr_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the v0.4.18-audited OOTC DR/GDR exact-ISIN cohort.

        Admission is limited to OTC TradingView depositary receipts rejected as
        Finnhub GDR.  Exact ISIN must yield exactly one OOTC-scoped OpenFIGI
        FIGI classified GDR/Depositary Receipt with non-null shareClassFIGI,
        and Yahoo exact-ISIN discovery must yield exactly one candidate whose
        symbol is the exact TV ticker and whose quote is OOTC-compatible, USD,
        and EQUITY.  This is not a global GDR taxonomy compatibility rule.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:GDR":
                continue
            if r.prefix != "OTC" or (r.tv_type or "").lower() != "dr" or not r.isin:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in eligible]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_ootc_dr_gdr_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_ootc_dr_gdr_openfigi_unavailable"] += len(eligible)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(eligible, mapped):
            source = [x for x in identities if (
                (x.security_type or "").strip().lower() == "gdr"
                and (x.security_type2 or "").strip().lower() == "depositary receipt"
                and bool((x.share_class_figi or "").strip())
                and str(x.ticker or "").upper().strip() == str(r.symbol or "").upper().strip()
            )]
            figis = {x.figi for x in source if x.figi}
            if len(figis) != 1:
                self.stats["us_ootc_dr_gdr_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in source if x.figi == figi)
            self.stats["us_ootc_dr_gdr_source_proven"] += 1

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not proven or not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_ootc_dr_gdr_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if str(c.symbol or "").upper().strip() != str(r.symbol or "").upper().strip():
                self.stats["us_ootc_dr_gdr_yahoo_unconfirmed"] += 1
                continue
            if (c.quote_type or "").upper() != "EQUITY" or q is None or (q.quote_type or "").upper() != "EQUITY":
                self.stats["us_ootc_dr_gdr_yahoo_unconfirmed"] += 1
                continue
            if (q.currency or "").upper() != "USD" or (r.currency and not currency_compatible(r.currency, q.currency)):
                self.stats["us_ootc_dr_gdr_yahoo_unconfirmed"] += 1
                continue
            if not yahoo_venue_compatible("OOTC", q):
                self.stats["us_ootc_dr_gdr_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OOTC_DR_FINNHUB_GDR_EXACT_ISIN", source_of=of, target_of=of,
            )
            self.stats["us_ootc_dr_gdr_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_ootc_preferred_empty_type_public_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue the audited OTC preferred cohort with empty Finnhub taxonomy.

        Admission is intentionally narrower than treating a missing Finnhub type
        as compatible.  The exact TradingView symbol must have exactly one
        same-currency Finnhub universe row, that row must explicitly bind the
        listing to OOTC and its type must be empty.  Exact ISIN + OOTC must then
        expose exactly one OpenFIGI FIGI explicitly classified PUBLIC /
        Preferred Stock.  Finally Yahoo exact-ISIN discovery must itself be
        unique and return the exact TV ticker with an OOTC-compatible USD/EQUITY
        quote.  This is same-source evidence; no shareClassFIGI bridge is used.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if r.prefix != "OTC" or not r.isin:
                continue
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:?":
                continue
            if tv_type_kind(r) != "PREFERRED" or "preferred" not in specs:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        universe = self.cache.load_finnhub_universe()
        source_bound: list[TvRow] = []
        for r in eligible:
            exact = []
            seen = set()
            for raw in universe:
                symbol = str(raw.get("symbol") or "").upper().strip()
                if symbol != str(r.symbol or "").upper().strip():
                    continue
                if not currency_compatible(r.currency, raw.get("currency")):
                    continue
                key = (raw.get("symbol"), raw.get("mic"), raw.get("currency"), raw.get("type"), raw.get("figi"), raw.get("shareClassFIGI"))
                if key not in seen:
                    seen.add(key); exact.append(raw)
            if len(exact) != 1:
                self.stats["us_ootc_preferred_empty_type_finnhub_source_unconfirmed"] += 1
                continue
            raw = exact[0]
            if str(raw.get("mic") or "").upper().strip() != "OOTC" or str(raw.get("type") or "").strip():
                self.stats["us_ootc_preferred_empty_type_finnhub_source_unconfirmed"] += 1
                continue
            source_bound.append(r)
            self.stats["us_ootc_preferred_empty_type_finnhub_source_proven"] += 1
        if not source_bound:
            return bindings

        jobs = [{"idType": "ID_ISIN", "idValue": r.isin, "micCode": "OOTC"} for r in source_bound]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_ootc_preferred_empty_type_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_ootc_preferred_empty_type_openfigi_unavailable"] += len(jobs)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        for r, identities in zip(source_bound, mapped):
            public_preferred = [x for x in identities if (
                (x.security_type or "").strip().lower() == "public"
                and (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
            )]
            figis = {x.figi for x in public_preferred if x.figi}
            if len(figis) != 1:
                self.stats["us_ootc_preferred_empty_type_openfigi_source_unconfirmed"] += 1
                continue
            figi = next(iter(figis))
            proven[r.tv_id] = next(x for x in public_preferred if x.figi == figi)
            self.stats["us_ootc_preferred_empty_type_openfigi_source_proven"] += 1
        if not proven:
            return bindings

        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not callable(search_fn):
            return bindings
        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in source_bound:
            if r.tv_id not in proven:
                continue
            try:
                searches[r.tv_id] = list(search_fn(str(r.isin).upper().strip()))
            except ProviderError:
                searches[r.tv_id] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in source_bound:
            of = proven.get(r.tv_id)
            cs = searches.get(r.tv_id, [])
            if of is None or len(cs) != 1:
                self.stats["us_ootc_preferred_empty_type_yahoo_unconfirmed"] += 1
                continue
            c = cs[0]
            q = quotes.get(c.symbol)
            if c.symbol != r.symbol or (c.quote_type or "").upper() != "EQUITY":
                self.stats["us_ootc_preferred_empty_type_yahoo_unconfirmed"] += 1
                continue
            if q is None or (q.quote_type or "").upper() != "EQUITY" or not yahoo_venue_compatible("OOTC", q):
                self.stats["us_ootc_preferred_empty_type_yahoo_unconfirmed"] += 1
                continue
            if not q.currency or not currency_compatible(r.currency, q.currency):
                self.stats["us_ootc_preferred_empty_type_yahoo_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC", source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OOTC_PREFERRED_FINNHUB_EMPTY_TYPE_EXACT_ISIN",
                source_of=of, target_of=of,
            )
            self.stats["us_ootc_preferred_empty_type_rescue_matches"] += 1

        return [rescued.get(b.tv_id, b) for b in bindings] if rescued else bindings

    def _us_otc_preferred_rescue(
        self,
        rows: list[TvRow],
        bindings: list[Binding],
    ) -> list[Binding]:
        """Rescue an OTC preferred only after discovering one exact source MIC.

        TradingView ``OTC`` is deliberately not mapped to a single ISO MIC.
        For a ``stock/preferred`` rejected solely because Finnhub reports an
        unspecified type (``?``), exact ISIN is probed against a bounded set of
        reviewed current OTC MICs.  Admission requires exactly one MIC to
        expose exactly one compatible Preferred Stock FIGI, and that MIC must
        be OOTC.  Yahoo exact-ISIN discovery must then return exactly one route,
        whose symbol is exactly the TradingView symbol and whose quote is an
        explicitly reviewed OTC Markets provider venue (OQB or PNK), with
        compatible currency and EQUITY taxonomy.

        OQB/PNK are treated as Yahoo provider venue codes compatible with the
        independently proven OOTC source context; they are not asserted to be
        ISO-MIC aliases.  No cross-venue fallback, ticker guessing, or missing
        shareClassFIGI bridge is permitted.
        """
        by_id = {b.tv_id: b for b in bindings}
        eligible: list[TvRow] = []
        for r in rows:
            b = by_id.get(r.tv_id)
            specs = {str(x).lower() for x in r.type_specs if x}
            if r.prefix != "OTC" or not r.isin:
                continue
            if not b or b.rejection_reason != "FINNHUB_TYPE_MISMATCH:?":
                continue
            if tv_type_kind(r) != "PREFERRED" or "preferred" not in specs:
                continue
            eligible.append(r)
        if not eligible:
            return bindings

        candidate_mics = ("OTCM", "OTCB", "OOTC", "OTCD")
        jobs = [
            {"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic}
            for r in eligible for mic in candidate_mics
        ]
        try:
            mapped = self.openfigi.map_jobs(jobs)
            self.stats["us_otc_preferred_openfigi_jobs"] += len(jobs)
        except ProviderError:
            self.stats["us_otc_preferred_openfigi_unavailable"] += len(jobs)
            return bindings

        proven: dict[str, OpenFigiIdentity] = {}
        pos = 0
        for r in eligible:
            proven_by_mic: dict[str, OpenFigiIdentity] = {}
            for mic in candidate_mics:
                identities = list(mapped[pos]); pos += 1
                compatible = [x for x in identities if openfigi_type_compatible(r, x)]
                preferred = [
                    x for x in compatible
                    if (x.security_type2 or "").strip().lower() in {"preferred stock", "preferred", "preference"}
                    or (x.security_type or "").strip().lower() in {"preferred stock", "preferred", "preference"}
                ]
                figis = {x.figi for x in preferred if x.figi}
                if len(figis) == 1:
                    figi = next(iter(figis))
                    proven_by_mic[mic] = next(x for x in preferred if x.figi == figi)
            if set(proven_by_mic) != {"OOTC"}:
                if len(proven_by_mic) > 1:
                    self.stats["us_otc_preferred_source_ambiguous"] += 1
                else:
                    self.stats["us_otc_preferred_source_unconfirmed"] += 1
                continue
            proven[r.tv_id] = proven_by_mic["OOTC"]
            self.stats["us_otc_preferred_source_proven_OOTC"] += 1

        if not proven:
            return bindings
        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not callable(search_fn):
            return bindings

        searches: dict[str, list[YahooSearchCandidate]] = {}
        for r in eligible:
            if r.tv_id not in proven:
                continue
            token = str(r.isin).upper().strip()
            if token not in searches:
                try:
                    searches[token] = list(search_fn(token))
                except ProviderError:
                    searches[token] = []
        symbols = sorted({c.symbol for cs in searches.values() for c in cs if c.symbol})
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
        except ProviderError:
            quotes = {}

        rescued: dict[str, Binding] = {}
        for r in eligible:
            of = proven.get(r.tv_id)
            if of is None:
                continue
            cs = searches.get(str(r.isin).upper().strip(), [])
            # Exact-ISIN discovery itself must be unique.  Quote filtering may
            # validate that route, but must never choose among search routes.
            if len(cs) != 1:
                self.stats["us_otc_preferred_yahoo_search_unconfirmed"] += 1
                continue
            c = cs[0]
            if c.symbol != r.symbol:
                self.stats["us_otc_preferred_yahoo_symbol_mismatch"] += 1
                continue
            q = quotes.get(c.symbol)
            if q is None or not yahoo_type_compatible(r, q.quote_type):
                self.stats["us_otc_preferred_yahoo_contract_unconfirmed"] += 1
                continue
            if r.currency and q.currency and not currency_compatible(r.currency, q.currency):
                self.stats["us_otc_preferred_yahoo_contract_unconfirmed"] += 1
                continue
            exchange = str(q.exchange or "").upper().strip()
            full_name = str(q.full_exchange_name or "").lower()
            if exchange not in {"OQB", "PNK"} or "otc markets" not in full_name:
                self.stats["us_otc_preferred_yahoo_venue_unconfirmed"] += 1
                continue
            rescued[r.tv_id] = self._verified(
                r, fh=None, of=of, y=q, mic="OOTC",
                source_mic="OOTC", target_mic="OOTC",
                mapping_method="US_OTC_PREFERRED_EXACT_ISIN_SAME_LISTING",
                source_of=of, target_of=of,
            )
            self.stats["us_otc_preferred_rescue_matches"] += 1
            self.stats[f"us_otc_preferred_rescue_matches_{_telemetry_token(exchange)}"] += 1

        if not rescued:
            return bindings
        return [rescued.get(b.tv_id, b) for b in bindings]

    def _resolve_non_us(self, rows: list[TvRow]) -> list[Binding]:
        """Resolve non-US listings with OpenFIGI as the identity authority.

        Direct venues use exact MIC + local symbol.  Cross-venue bridges (for
        example TradingView TRADEGATE -> Yahoo/Xetra) are admitted only when
        OpenFIGI proves that the source and target listings have the same
        shareClassFIGI.  The source venue is preserved separately from the Yahoo
        target venue; we never rewrite Tradegate as Xetra.
        """
        rejected: list[Binding] = []
        pending: list[dict] = []

        direct_rows: list[TvRow] = []
        direct_jobs: list[dict] = []
        bridge_rows: list[TvRow] = []
        exchcode_bridge_rows: list[TvRow] = []

        # TradingView's Korea universe exposes one provider prefix (KRX) for
        # both KOSPI and KOSDAQ.  Do not infer the segment from the numeric
        # ticker.  Probe the reviewed MIC candidates and admit routing only
        # when exact ISIN+MIC evidence selects exactly one segment. TradingView
        # supplies ISIN for the reviewed Korea universe; rows without it remain
        # fail-closed rather than falling back to ticker-range inference.
        mic_overrides: dict[str, str] = {}
        korea_identity_overrides: dict[str, OpenFigiIdentity] = {}
        korea_rows = [
            r for r in rows
            if (self.market or "").lower() == "korea" and r.prefix == "KRX"
            and r.currency and r.isin
        ]
        if korea_rows:
            korea_jobs = [
                {
                    "idType": "ID_ISIN",
                    "idValue": r.isin.strip().upper(),
                    "micCode": mic,
                }
                for r in korea_rows
                for mic in KOREA_KRX_CANDIDATE_MICS
            ]
            try:
                korea_mapped = self.openfigi.map_jobs(korea_jobs)
                self.stats["openfigi_jobs"] += len(korea_jobs)
                self.stats["korea_krx_segment_probe_jobs"] += len(korea_jobs)
                self.stats["openfigi_http_batches"] += (
                    len(korea_jobs) + self.openfigi.batch_size - 1
                ) // self.openfigi.batch_size
            except ProviderError as exc:
                rejected.extend(
                    self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}")
                    for r in korea_rows
                )
                korea_mapped = []

            if korea_mapped:
                width = len(KOREA_KRX_CANDIDATE_MICS)
                for idx, r in enumerate(korea_rows):
                    proven: list[str] = []
                    reasons: list[str] = []
                    for offset, mic in enumerate(KOREA_KRX_CANDIDATE_MICS):
                        identities = korea_mapped[idx * width + offset]
                        of, _collapsed = _select_isin_bridge_target(r, identities)
                        reason = None if of is not None else "OPENFIGI_NO_MATCH"
                        if of is not None:
                            proven.append(mic)
                            korea_identity_overrides[f"{r.tv_id}|{mic}"] = of
                        elif reason:
                            reasons.append(f"{mic}:{reason}")
                    if len(proven) == 1:
                        mic_overrides[r.tv_id] = proven[0]
                        self.stats["korea_krx_segment_probe_matches"] += 1
                        self.stats[f"korea_krx_segment_probe_matches_{proven[0]}"] += 1
                    elif len(proven) > 1:
                        # A security can legitimately have exact ISIN mappings on more
                        # than one Korean segment (for example during a venue transition).
                        # Resolve that listing ambiguity only when every OpenFIGI branch
                        # points at the same share class and Yahoo's exact-ISIN discovery
                        # independently identifies one exact local ticker whose validated
                        # quote belongs to exactly one of those already-proven MICs.
                        resolved_mic = None
                        identities = [
                            korea_identity_overrides.get(f"{r.tv_id}|{mic}")
                            for mic in proven
                        ]
                        shares = {x.share_class_figi for x in identities if x and x.share_class_figi}
                        search_fn = getattr(self.yahoo, "search_exact_isin", None)
                        if len(shares) == 1 and all(x and x.share_class_figi for x in identities) and callable(search_fn):
                            try:
                                candidates = list(search_fn(r.isin.strip().upper()))
                                self.stats["korea_krx_segment_ambiguity_yahoo_searches"] += 1
                            except ProviderError:
                                candidates = []
                                self.stats["korea_krx_segment_ambiguity_yahoo_search_unavailable"] += 1
                            if len(candidates) == 1:
                                candidate = candidates[0]
                                keys = _yahoo_symbol_identity_keys(candidate.symbol)
                                if (
                                    punctuation_key(r.symbol) in keys
                                    and str(candidate.quote_type or "").upper() == "EQUITY"
                                ):
                                    try:
                                        quotes = self.yahoo.quotes([candidate.symbol])
                                    except ProviderError:
                                        quotes = {}
                                    q = quotes.get(candidate.symbol)
                                    if (
                                        q is not None
                                        and yahoo_type_compatible(r, q.quote_type)
                                        and (not r.currency or not q.currency or currency_compatible(r.currency, q.currency))
                                    ):
                                        venue_matches = [mic for mic in proven if yahoo_venue_compatible(mic, q)]
                                        if len(venue_matches) == 1:
                                            resolved_mic = venue_matches[0]
                        if resolved_mic is not None:
                            mic_overrides[r.tv_id] = resolved_mic
                            self.stats["korea_krx_segment_probe_matches"] += 1
                            self.stats[f"korea_krx_segment_probe_matches_{resolved_mic}"] += 1
                            self.stats["korea_krx_segment_ambiguity_yahoo_resolved"] += 1
                        else:
                            rejected.append(self._reject(
                                r, "OPENFIGI_KOREA_SEGMENT_AMBIGUOUS:" + ",".join(proven)
                            ))
                            self.stats["korea_krx_segment_probe_ambiguous"] += 1
                    else:
                        rejected.append(self._reject(
                            r, "OPENFIGI_KOREA_SEGMENT_NO_MATCH"
                            + (":" + "|".join(reasons) if reasons else "")
                        ))
                        self.stats["korea_krx_segment_probe_no_match"] += 1

        for r in rows:
            if not r.currency:
                rejected.append(self._reject(r, "CURRENCY_UNKNOWN"))
                continue
            if r.prefix in CROSS_VENUE_BRIDGES:
                bridge_rows.append(r)
                continue
            if r.prefix in ISIN_SHARE_CLASS_BRIDGES:
                if not r.isin:
                    rejected.append(self._reject(r, "TV_ISIN_UNKNOWN"))
                    continue
                bridge_rows.append(r)
                continue
            if r.prefix in EXCHCODE_SHARE_CLASS_BRIDGES:
                exchcode_bridge_rows.append(r)
                continue
            if (self.market or "").lower() == "korea" and r.prefix == "KRX":
                # Exact ISIN+MIC segment discovery above already produced the
                # source listing identity. Reuse it below instead of issuing a
                # redundant ID_EXCH_SYMBOL OpenFIGI request.
                if not r.isin:
                    rejected.append(self._reject(r, "TV_ISIN_UNKNOWN"))
                # Otherwise a Korea-specific match/rejection was recorded above.
                continue
            mic = tv_prefix_mic(r.prefix, self.market)
            if not mic:
                rejected.append(self._reject(r, "MIC_UNKNOWN"))
                continue
            direct_rows.append(r)
            direct_jobs.append({
                "idType": "ID_EXCH_SYMBOL",
                "idValue": r.symbol,
                "micCode": mic,
                "currency": openfigi_currency(r.currency),
                "securityType2": openfigi_security_type(r),
            })

        # Queue Korea rows from the exact ISIN+MIC segment evidence above.
        def add_direct_pending(
            r: TvRow,
            of: OpenFigiIdentity,
            collapsed: bool,
            type_fallback: bool = False,
            method_override: str | None = None,
            japan_regional_exact_listing: bool = False,
            mic_override: str | None = None,
        ) -> None:
            mic = mic_override or tv_prefix_mic(r.prefix, self.market)
            suffix = MIC_TO_YAHOO_SUFFIX.get(mic)
            if suffix is None:
                rejected.append(self._reject(r, f"YAHOO_SUFFIX_UNKNOWN:{mic}"))
                return
            yahoo_symbol = yahoo_listing_symbol(of.ticker or r.symbol, mic, r.prefix, tv_type_kind(r))
            if method_override:
                method = method_override
            elif collapsed and type_fallback:
                method = "SAME_VENUE_TYPE_FALLBACK_SHARE_CLASS_COLLAPSE"
            elif collapsed:
                method = "SAME_VENUE_SHARE_CLASS_COLLAPSE"
            elif type_fallback:
                method = "SAME_VENUE_TYPE_FALLBACK"
            else:
                method = "SAME_VENUE"
            pending.append({
                "row": r,
                "identity": of,
                "source_identity": of,
                "target_identity": of,
                "source_mic": mic,
                "source_venue_code": None,
                "target_mic": mic,
                "yahoo_symbol": yahoo_symbol,
                "mapping_method": method,
                "japan_regional_exact_listing": japan_regional_exact_listing,
            })
            if collapsed:
                self.stats["openfigi_share_class_collapses"] += 1
            if type_fallback:
                self.stats["openfigi_type_fallback_matches"] += 1

        for r in korea_rows:
            mic = mic_overrides.get(r.tv_id)
            if not mic:
                continue
            of = korea_identity_overrides.get(f"{r.tv_id}|{mic}")
            if of is None:
                rejected.append(self._reject(r, f"OPENFIGI_KOREA_SEGMENT_IDENTITY_MISSING:{mic}"))
                continue
            add_direct_pending(
                r, of, False,
                method_override="KOREA_EXACT_ISIN_SEGMENT",
                mic_override=mic,
            )

        # Direct same-venue mappings. First use the strict provider taxonomy.
        # If that produces no match, retry only those rows without securityType2
        # and post-filter the response by exact ticker + compatible equity kind.
        # This handles provider taxonomy differences such as REIT without making
        # the primary mapping fuzzy.
        if direct_jobs:
            try:
                mapped = self.openfigi.map_jobs(direct_jobs)
                self.stats["openfigi_jobs"] += len(direct_jobs)
                self.stats["openfigi_http_batches"] += (len(direct_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
            except ProviderError as exc:
                rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in direct_rows)
                mapped = [[] for _ in direct_rows]

            retry_rows: list[TvRow] = []
            retry_jobs: list[dict] = []
            direct_isin_rows: list[TvRow] = []
            direct_isin_jobs: list[dict] = []
            isin_fallback_rows: list[tuple[TvRow, str]] = []
            isin_fallback_jobs: list[dict] = []
            isin_unscoped_rows: list[tuple[TvRow, str]] = []
            isin_unscoped_jobs: list[dict] = []

            def add_target_provider_strict_fallback(r: TvRow) -> bool:
                """Queue a lower-evidence same-venue Yahoo proof after OpenFIGI no-match.

                This is intentionally limited to reviewed provider namespaces. No FIGI
                is invented or copied from another venue. Final admission later requires
                Yahoo to explicitly confirm exact symbol, currency, type and venue.
                """
                if r.prefix not in TARGET_PROVIDER_STRICT_FALLBACK_PREFIXES:
                    return False
                mic = tv_prefix_mic(r.prefix, self.market)
                if not mic or MIC_TO_YAHOO_SUFFIX.get(mic) is None:
                    return False
                pending.append({
                    "row": r,
                    "identity": None,
                    "source_identity": None,
                    "target_identity": None,
                    "source_mic": mic,
                    "source_venue_code": None,
                    "target_mic": mic,
                    "yahoo_symbol": yahoo_listing_symbol(r.symbol, mic, r.prefix, tv_type_kind(r)),
                    "mapping_method": "TARGET_PROVIDER_STRICT_FALLBACK",
                })
                self.stats["target_provider_strict_fallback_jobs"] += 1
                return True

            for r, identities in zip(direct_rows, mapped):
                of, collapsed, reason = _select_openfigi_identity(r, identities)
                if of is not None:
                    mic = mic_overrides.get(r.tv_id) or tv_prefix_mic(r.prefix, self.market)
                    exact_source_candidates = [
                        x for x in identities
                        if punctuation_key(x.ticker or "") == punctuation_key(r.symbol)
                        and openfigi_type_compatible(r, x)
                        and bool(x.figi)
                        and bool(x.share_class_figi)
                    ]
                    japan_regional_exact_listing = (
                        self.market == "japan"
                        and mic in {"XNGO", "XFKA"}
                        and bool(r.isin)
                        and len(exact_source_candidates) == 1
                        and exact_source_candidates[0].figi == of.figi
                    )
                    add_direct_pending(
                        r, of, collapsed,
                        japan_regional_exact_listing=japan_regional_exact_listing,
                        mic_override=mic,
                    )
                    continue
                if reason and reason.startswith("OPENFIGI_AMBIGUOUS"):
                    reviewed = REVIEWED_ISIN_FALLBACKS.get(r.tv_id)
                    if reviewed:
                        mic = str(reviewed["mic"])
                        isin_fallback_rows.append((r, mic))
                        isin_fallback_jobs.append({
                            "idType": "ID_ISIN",
                            "idValue": str(reviewed["isin"]),
                            "micCode": mic,
                        })
                        continue
                    rejected.append(self._reject(r, reason))
                    continue
                mic = tv_prefix_mic(r.prefix, self.market)
                retry_rows.append(r)
                retry_jobs.append({
                    "idType": "ID_EXCH_SYMBOL",
                    "idValue": r.symbol,
                    "micCode": mic,
                    "currency": openfigi_currency(r.currency),
                })

            if isin_fallback_jobs:
                try:
                    isin_mapped = self.openfigi.map_jobs(isin_fallback_jobs)
                    self.stats["openfigi_jobs"] += len(isin_fallback_jobs)
                    self.stats["openfigi_isin_fallback_jobs"] += len(isin_fallback_jobs)
                    self.stats["openfigi_http_batches"] += (len(isin_fallback_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                except ProviderError as exc:
                    rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r, _ in isin_fallback_rows)
                    isin_mapped = [[] for _ in isin_fallback_rows]

                for (r, reviewed_mic), identities in zip(isin_fallback_rows, isin_mapped):
                    of, collapsed, reason = _select_openfigi_identity(r, identities)
                    if of is None:
                        suffix = reason or "OPENFIGI_NO_MATCH"
                        if suffix == "OPENFIGI_NO_MATCH":
                            reviewed = REVIEWED_ISIN_FALLBACKS[r.tv_id]
                            isin_unscoped_rows.append((r, reviewed_mic))
                            isin_unscoped_jobs.append({
                                "idType": "ID_ISIN",
                                "idValue": str(reviewed["isin"]),
                            })
                            continue
                        rejected.append(self._reject(r, f"REVIEWED_ISIN_{suffix}"))
                        continue
                    add_direct_pending(
                        r, of, collapsed,
                        method_override="REVIEWED_ISIN_FALLBACK",
                        mic_override=reviewed_mic,
                    )
                    self.stats["openfigi_isin_fallback_matches"] += 1

                if isin_unscoped_jobs:
                    try:
                        unscoped_mapped = self.openfigi.map_jobs(isin_unscoped_jobs)
                        self.stats["openfigi_jobs"] += len(isin_unscoped_jobs)
                        self.stats["openfigi_isin_unscoped_fallback_jobs"] += len(isin_unscoped_jobs)
                        self.stats["openfigi_http_batches"] += (len(isin_unscoped_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                    except ProviderError as exc:
                        rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r, _ in isin_unscoped_rows)
                        unscoped_mapped = [[] for _ in isin_unscoped_rows]

                    for (r, reviewed_mic), identities in zip(isin_unscoped_rows, unscoped_mapped):
                        of, collapsed, reason = _select_openfigi_identity(r, identities)
                        if of is None:
                            suffix = reason or "OPENFIGI_NO_MATCH"
                            rejected.append(self._reject(r, f"REVIEWED_ISIN_UNSCOPED_{suffix}"))
                            continue
                        # ID_ISIN without a MIC proves the reviewed security but
                        # may return a FIGI/composite for another venue (for BVS,
                        # typically the older ASX listing). Preserve only the
                        # security-level shareClassFIGI; never relabel that venue
                        # FIGI as AIMX/XLON. The reviewed MIC is authoritative
                        # listing evidence and Yahoo must pass strict metadata.
                        security_of = OpenFigiIdentity(
                            figi=None,
                            composite_figi=None,
                            share_class_figi=of.share_class_figi,
                            ticker=of.ticker or r.symbol,
                            name=of.name,
                            security_type=of.security_type,
                            security_type2=of.security_type2,
                            exch_code=None,
                        )
                        add_direct_pending(
                            r, security_of, collapsed,
                            method_override="REVIEWED_ISIN_SECURITY_FALLBACK",
                            mic_override=reviewed_mic,
                        )
                        self.stats["openfigi_isin_unscoped_fallback_matches"] += 1

            if retry_jobs:
                try:
                    retry_mapped = self.openfigi.map_jobs(retry_jobs)
                    self.stats["openfigi_jobs"] += len(retry_jobs)
                    self.stats["openfigi_type_fallback_jobs"] += len(retry_jobs)
                    self.stats["openfigi_http_batches"] += (len(retry_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                except ProviderError as exc:
                    rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in retry_rows)
                    retry_mapped = [[] for _ in retry_rows]

                currency_retry_rows: list[TvRow] = []
                currency_retry_jobs: list[dict] = []
                secondary_mic_layout: list[tuple[TvRow, tuple[str, ...], int]] = []
                secondary_mic_jobs: list[dict] = []
                ireland_isin_rows: list[TvRow] = []
                ireland_isin_jobs: list[dict] = []
                japan_reit_isin_rows: list[TvRow] = []
                japan_reit_isin_jobs: list[dict] = []
                for r, identities in zip(retry_rows, retry_mapped):
                    of, collapsed, reason = _select_openfigi_identity(r, identities)
                    if of is not None:
                        add_direct_pending(r, of, collapsed, type_fallback=True)
                        continue
                    if (reason or "OPENFIGI_NO_MATCH") == "OPENFIGI_NO_MATCH":
                        secondary_mics = tuple(SECONDARY_MIC_FALLBACKS.get(r.prefix, ()))
                        if secondary_mics:
                            offset = len(secondary_mic_jobs)
                            for secondary_mic in secondary_mics:
                                secondary_mic_jobs.append({
                                    "idType": "ID_EXCH_SYMBOL",
                                    "idValue": r.symbol,
                                    "micCode": secondary_mic,
                                    "currency": openfigi_currency(r.currency),
                                })
                            secondary_mic_layout.append((r, secondary_mics, offset))
                            continue
                    # Some XLON instruments are traded in GBX/GBp but OpenFIGI
                    # models the listing currency at the major-unit GBP level.
                    # Retry only this reviewed unit mismatch, while preserving
                    # exact ticker + MIC and keeping Yahoo price validation in
                    # GBX/GBp. This is not a generic currency fallback.
                    if r.prefix in {"LSE", "LSIN"} and (r.currency or "").upper() == "GBX":
                        mic = tv_prefix_mic(r.prefix, self.market)
                        currency_retry_rows.append(r)
                        currency_retry_jobs.append({
                            "idType": "ID_EXCH_SYMBOL",
                            "idValue": r.symbol,
                            "micCode": mic,
                            "currency": "GBP",
                        })
                        continue
                    if (
                        (reason or "OPENFIGI_NO_MATCH") == "OPENFIGI_NO_MATCH"
                        and (self.market or "").lower() == "japan"
                        and r.prefix == "TSE"
                        and tv_prefix_mic(r.prefix, self.market) == "XTKS"
                        and tv_type_kind(r) == "STOCK"
                        and r.isin
                    ):
                        japan_reit_isin_rows.append(r)
                        japan_reit_isin_jobs.append({
                            "idType": "ID_ISIN",
                            "idValue": r.isin,
                            "micCode": "XTKS",
                        })
                        continue
                    if (
                        (reason or "OPENFIGI_NO_MATCH") == "OPENFIGI_NO_MATCH"
                        and (self.market or "").lower() == "ireland"
                        and r.prefix == "EURONEXT"
                        and tv_prefix_mic(r.prefix, self.market) == "XDUB"
                        and r.isin
                    ):
                        ireland_isin_rows.append(r)
                        ireland_isin_jobs.append({
                            "idType": "ID_ISIN",
                            "idValue": r.isin,
                        })
                        continue
                    if ((reason or "OPENFIGI_NO_MATCH") == "OPENFIGI_NO_MATCH"
                            and r.prefix in {"FWB", "DUS", "HAM", "SWB", "MUN", "HAN", "BX"}
                            and r.isin):
                        direct_isin_rows.append(r)
                        direct_isin_jobs.append({
                            "idType": "ID_ISIN",
                            "idValue": r.isin,
                            "micCode": tv_prefix_mic(r.prefix, self.market),
                        })
                        continue
                    if (reason or "OPENFIGI_NO_MATCH") == "OPENFIGI_NO_MATCH" and add_target_provider_strict_fallback(r):
                        continue
                    rejected.append(self._reject(r, reason or "OPENFIGI_NO_MATCH"))

                if japan_reit_isin_jobs:
                    try:
                        japan_reit_mapped = self.openfigi.map_jobs(japan_reit_isin_jobs)
                        self.stats["openfigi_jobs"] += len(japan_reit_isin_jobs)
                        self.stats["japan_xtks_reit_isin_jobs"] += len(japan_reit_isin_jobs)
                        self.stats["openfigi_http_batches"] += (len(japan_reit_isin_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                    except ProviderError as exc:
                        rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in japan_reit_isin_rows)
                        japan_reit_mapped = [[] for _ in japan_reit_isin_rows]

                    for r, identities in zip(japan_reit_isin_rows, japan_reit_mapped):
                        exact_ticker_identities = [
                            x for x in identities
                            if punctuation_key(x.ticker or "") == punctuation_key(r.symbol)
                        ]
                        reit_identities = [
                            x for x in exact_ticker_identities
                            if ((x.security_type or "").lower() in {"reit", "real estate investment trust"}
                                or (x.security_type2 or "").lower() in {"reit", "real estate investment trust"})
                        ]
                        # These four JPX infrastructure funds are a reviewed, bounded
                        # provider-taxonomy exception. TradingView exposes them as
                        # stock/common while OpenFIGI models the exact XTKS listings as
                        # Unit. Do not generalize stock<->Unit compatibility beyond the
                        # reviewed ISINs.
                        reviewed_infrastructure_fund_isins = {
                            "JP3048360006",  # 9282
                            "JP3048590008",  # 9284
                            "JP3048780005",  # 9285
                            "JP3048820009",  # 9286
                        }
                        unit_identities = [
                            x for x in exact_ticker_identities
                            if r.isin in reviewed_infrastructure_fund_isins
                            and ((x.security_type or "").lower() == "unit"
                                 or (x.security_type2 or "").lower() == "unit")
                        ]
                        selected = reit_identities or unit_identities
                        shares = {x.share_class_figi for x in selected if x.share_class_figi}
                        if not selected or len(shares) != 1 or not all(x.share_class_figi for x in selected):
                            self.stats["japan_xtks_reit_isin_no_match"] += 1
                            rejected.append(self._reject(r, "OPENFIGI_NO_MATCH"))
                            continue
                        first = selected[0]
                        of = first if len(selected) == 1 else OpenFigiIdentity(
                            figi=None,
                            composite_figi=None,
                            share_class_figi=next(iter(shares)),
                            ticker=first.ticker or r.symbol,
                            name=first.name,
                            security_type=first.security_type,
                            security_type2=first.security_type2,
                            exch_code=None,
                        )
                        method = (
                            "JAPAN_XTKS_REIT_TAXONOMY"
                            if reit_identities
                            else "JAPAN_XTKS_INFRASTRUCTURE_FUND_TAXONOMY"
                        )
                        add_direct_pending(
                            r, of, len(selected) > 1,
                            method_override=method,
                            mic_override="XTKS",
                        )
                        if reit_identities:
                            self.stats["japan_xtks_reit_isin_matches"] += 1
                        else:
                            self.stats["japan_xtks_infrastructure_fund_isin_matches"] += 1

                if ireland_isin_jobs:
                    try:
                        ireland_isin_mapped = self.openfigi.map_jobs(ireland_isin_jobs)
                        self.stats["openfigi_jobs"] += len(ireland_isin_jobs)
                        self.stats["ireland_isin_unscoped_jobs"] += len(ireland_isin_jobs)
                        self.stats["openfigi_http_batches"] += (len(ireland_isin_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                    except ProviderError as exc:
                        rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in ireland_isin_rows)
                        ireland_isin_mapped = [[] for _ in ireland_isin_rows]

                    for r, identities in zip(ireland_isin_rows, ireland_isin_mapped):
                        target_of = _select_ireland_isin_xdub_listing(r, identities)
                        if target_of is None:
                            self.stats["ireland_isin_unscoped_no_match"] += 1
                            rejected.append(self._reject(r, "OPENFIGI_NO_MATCH"))
                            continue
                        # The exact ISIN + unique share class + unique Dublin
                        # listing proves the source listing independently of the
                        # provider ticker alias. Yahoo must then prove the exact
                        # TradingView symbol and complete XDUB venue metadata.
                        pending.append({
                            "row": r,
                            "identity": target_of,
                            "source_identity": target_of,
                            "target_identity": target_of,
                            "source_mic": "XDUB",
                            "source_venue_code": "ID",
                            "target_mic": "XDUB",
                            "yahoo_symbol": yahoo_listing_symbol(r.symbol, "XDUB", r.prefix, tv_type_kind(r)),
                            "mapping_method": "IRELAND_ISIN_UNIQUE_XDUB_LISTING",
                        })
                        self.stats["ireland_isin_unscoped_matches"] += 1

                if direct_isin_jobs:
                    try:
                        direct_isin_mapped = self.openfigi.map_jobs(direct_isin_jobs)
                        self.stats["openfigi_jobs"] += len(direct_isin_jobs)
                        self.stats["openfigi_direct_isin_fallback_jobs"] += len(direct_isin_jobs)
                        self.stats["openfigi_http_batches"] += (len(direct_isin_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                    except ProviderError as exc:
                        rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in direct_isin_rows)
                        direct_isin_mapped = [[] for _ in direct_isin_rows]

                    for r, identities in zip(direct_isin_rows, direct_isin_mapped):
                        of, collapsed = _select_isin_bridge_target(r, identities)
                        prefix_token = _telemetry_token(r.prefix)
                        if of is not None:
                            add_direct_pending(
                                r, of, collapsed,
                                method_override="TV_ISIN_SAME_VENUE_FALLBACK",
                            )
                            self.stats["openfigi_direct_isin_fallback_matches"] += 1
                            self.stats[f"openfigi_direct_isin_fallback_matches_{prefix_token}"] += 1
                            continue
                        self.stats["openfigi_direct_isin_fallback_no_match"] += 1
                        self.stats[f"openfigi_direct_isin_fallback_no_match_{prefix_token}"] += 1
                        if not add_target_provider_strict_fallback(r):
                            rejected.append(self._reject(r, "OPENFIGI_NO_MATCH"))

                if secondary_mic_jobs:
                    secondary_provider_failed = False
                    try:
                        secondary_mapped = self.openfigi.map_jobs(secondary_mic_jobs)
                        self.stats["openfigi_jobs"] += len(secondary_mic_jobs)
                        self.stats["openfigi_secondary_mic_jobs"] += len(secondary_mic_jobs)
                        self.stats["openfigi_secondary_mic_matches"] += 0
                        self.stats["openfigi_http_batches"] += (len(secondary_mic_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                    except ProviderError as exc:
                        rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r, _, _ in secondary_mic_layout)
                        secondary_mapped = [[] for _ in secondary_mic_jobs]
                        secondary_provider_failed = True

                    secondary_no_currency_layout: list[tuple[TvRow, tuple[str, ...], int]] = []
                    secondary_no_currency_jobs: list[dict] = []
                    if not secondary_provider_failed:
                        for r, secondary_mics, offset in secondary_mic_layout:
                            matches: list[tuple[str, OpenFigiIdentity, bool]] = []
                            for idx, secondary_mic in enumerate(secondary_mics):
                                identities = secondary_mapped[offset + idx] if offset + idx < len(secondary_mapped) else []
                                of, collapsed, _reason = _select_openfigi_identity(r, identities)
                                if of is not None:
                                    matches.append((secondary_mic, of, collapsed))
                            if len(matches) == 1:
                                secondary_mic, of, collapsed = matches[0]
                                add_direct_pending(
                                    r, of, collapsed, type_fallback=True,
                                    method_override="LSIN_SECONDARY_MIC_TYPE_FALLBACK",
                                    mic_override=secondary_mic,
                                )
                                self.stats["openfigi_secondary_mic_matches"] += 1
                                continue
                            if len(matches) > 1:
                                rejected.append(self._reject(r, f"OPENFIGI_SECONDARY_MIC_AMBIGUOUS:{len(matches)}"))
                                continue

                            # OpenFIGI can omit/model currency differently for thin
                            # IOB/Professional Securities Market depositary receipts.
                            # Keep this relaxation ADR-only: ordinary LSIN stocks do
                            # not gain a new currency-agnostic path. Drop only the
                            # currency filter while preserving exact ticker + exact
                            # reviewed secondary MIC.
                            if tv_type_kind(r) != "ADR":
                                if not add_target_provider_strict_fallback(r):
                                    rejected.append(self._reject(r, "OPENFIGI_NO_MATCH"))
                                continue
                            no_currency_offset = len(secondary_no_currency_jobs)
                            for secondary_mic in secondary_mics:
                                secondary_no_currency_jobs.append({
                                    "idType": "ID_EXCH_SYMBOL",
                                    "idValue": r.symbol,
                                    "micCode": secondary_mic,
                                })
                            secondary_no_currency_layout.append((r, secondary_mics, no_currency_offset))

                    if secondary_no_currency_jobs:
                        try:
                            secondary_no_currency_mapped = self.openfigi.map_jobs(secondary_no_currency_jobs)
                            self.stats["openfigi_jobs"] += len(secondary_no_currency_jobs)
                            self.stats["openfigi_secondary_mic_currency_omitted_jobs"] += len(secondary_no_currency_jobs)
                            self.stats["openfigi_secondary_mic_currency_omitted_matches"] += 0
                            self.stats["openfigi_http_batches"] += (len(secondary_no_currency_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                        except ProviderError as exc:
                            rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r, _, _ in secondary_no_currency_layout)
                            secondary_no_currency_mapped = [[] for _ in secondary_no_currency_jobs]
                            secondary_no_currency_layout = []

                        for r, secondary_mics, offset in secondary_no_currency_layout:
                            matches: list[tuple[str, OpenFigiIdentity, bool]] = []
                            for idx, secondary_mic in enumerate(secondary_mics):
                                identities = secondary_no_currency_mapped[offset + idx] if offset + idx < len(secondary_no_currency_mapped) else []
                                of, collapsed, _reason = _select_openfigi_identity(r, identities)
                                if of is not None:
                                    matches.append((secondary_mic, of, collapsed))
                            if len(matches) == 1:
                                secondary_mic, of, collapsed = matches[0]
                                add_direct_pending(
                                    r, of, collapsed, type_fallback=True,
                                    method_override="LSIN_SECONDARY_MIC_CURRENCY_OMITTED_FALLBACK",
                                    mic_override=secondary_mic,
                                )
                                self.stats["openfigi_secondary_mic_currency_omitted_matches"] += 1
                                continue
                            if len(matches) > 1:
                                rejected.append(self._reject(r, f"OPENFIGI_SECONDARY_MIC_AMBIGUOUS:{len(matches)}"))
                                continue
                            if not add_target_provider_strict_fallback(r):
                                rejected.append(self._reject(r, "OPENFIGI_NO_MATCH"))

                if currency_retry_jobs:
                    try:
                        currency_retry_mapped = self.openfigi.map_jobs(currency_retry_jobs)
                        self.stats["openfigi_jobs"] += len(currency_retry_jobs)
                        self.stats["openfigi_currency_fallback_jobs"] += len(currency_retry_jobs)
                        self.stats["openfigi_http_batches"] += (len(currency_retry_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                    except ProviderError as exc:
                        rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in currency_retry_rows)
                        currency_retry_mapped = [[] for _ in currency_retry_rows]

                    no_currency_rows: list[TvRow] = []
                    no_currency_jobs: list[dict] = []
                    for r, identities in zip(currency_retry_rows, currency_retry_mapped):
                        of, collapsed, reason = _select_openfigi_identity(r, identities)
                        if of is None:
                            # Final reviewed London fallback: OpenFIGI can omit or
                            # inconsistently model the quote currency for an otherwise
                            # exact XLON local symbol. Drop only the currency filter;
                            # ticker + MIC remain exact, and Yahoo must later confirm
                            # the .L symbol and GBX/GBp quote unit.
                            no_currency_rows.append(r)
                            no_currency_jobs.append({
                                "idType": "ID_EXCH_SYMBOL",
                                "idValue": r.symbol,
                                "micCode": tv_prefix_mic(r.prefix, self.market),
                            })
                            continue
                        add_direct_pending(r, of, collapsed, type_fallback=True)
                        self.stats["openfigi_currency_fallback_matches"] += 1

                    if no_currency_jobs:
                        try:
                            no_currency_mapped = self.openfigi.map_jobs(no_currency_jobs)
                            self.stats["openfigi_jobs"] += len(no_currency_jobs)
                            self.stats["openfigi_currency_omitted_jobs"] += len(no_currency_jobs)
                            self.stats["openfigi_http_batches"] += (len(no_currency_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                        except ProviderError as exc:
                            rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in no_currency_rows)
                            no_currency_mapped = [[] for _ in no_currency_rows]

                        for r, identities in zip(no_currency_rows, no_currency_mapped):
                            of, collapsed, reason = _select_openfigi_identity(r, identities)
                            if of is None:
                                # Last-resort *target-provider* proof for reviewed
                                # London same-venue symbols. OpenFIGI has returned
                                # no candidate even after exact ticker+XLON retries.
                                # Do not invent FIGIs: ask Yahoo for the bounded .L
                                # symbol and later require complete, explicit Yahoo
                                # currency + type + venue agreement.
                                if (reason or "OPENFIGI_NO_MATCH") == "OPENFIGI_NO_MATCH" and add_target_provider_strict_fallback(r):
                                    continue
                                rejected.append(self._reject(r, reason or "OPENFIGI_NO_MATCH"))
                                continue
                            add_direct_pending(r, of, collapsed, type_fallback=True)
                            self.stats["openfigi_currency_omitted_matches"] += 1

        # Cross-venue share-class bridges.  Jobs are still batched across all
        # bridge rows so one screen does not become N HTTP requests.
        bridge_jobs: list[dict] = []
        bridge_layout: list[tuple[TvRow, tuple[str, ...], str, int, int, bool]] = []
        for r in bridge_rows:
            isin_bridge = r.prefix in ISIN_SHARE_CLASS_BRIDGES
            cfg = ISIN_SHARE_CLASS_BRIDGES[r.prefix] if isin_bridge else CROSS_VENUE_BRIDGES[r.prefix]
            source_mics = tuple(cfg["source_mics"])
            target_mic = str(cfg["target_mic"])
            offset = len(bridge_jobs)
            for mic in (*source_mics, target_mic):
                if isin_bridge:
                    # TradingView LS/LSX often expose WKN-style symbols that do
                    # not equal the Xetra local ticker. Exact ISIN + exact MIC is
                    # therefore the bridge key; type remains a post-response guard.
                    bridge_jobs.append({
                        "idType": "ID_ISIN",
                        "idValue": r.isin,
                        "micCode": mic,
                    })
                else:
                    bridge_jobs.append({
                        "idType": "ID_EXCH_SYMBOL",
                        "idValue": r.symbol,
                        "micCode": mic,
                        "currency": openfigi_currency(r.currency),
                        "securityType2": openfigi_security_type(r),
                    })
            bridge_layout.append((r, source_mics, target_mic, offset, len(source_mics) + 1, isin_bridge))

        bridge_mapped: list[list[OpenFigiIdentity]] = []
        isin_bridge_probe_rows: list[TvRow] = []
        isin_bridge_probe_seen: set[str] = set()
        regional_target_probe_rows: list[TvRow] = []
        regional_target_probe_seen: set[str] = set()
        # Preserve the source-side bridge evidence for rows whose default Xetra
        # target is absent. Regional target routing later may reuse this exact
        # evidence, but never weakens the source-side contract.
        regional_bridge_context_by_id: dict[str, dict] = {}
        if bridge_jobs:
            try:
                bridge_mapped = self.openfigi.map_jobs(bridge_jobs)
                self.stats["openfigi_jobs"] += len(bridge_jobs)
                self.stats["openfigi_cross_venue_jobs"] += len(bridge_jobs)
                self.stats["openfigi_isin_bridge_jobs"] += sum(
                    len(tuple(ISIN_SHARE_CLASS_BRIDGES[r.prefix]["source_mics"])) + 1
                    for r in bridge_rows if r.prefix in ISIN_SHARE_CLASS_BRIDGES
                )
                self.stats["openfigi_http_batches"] += (len(bridge_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
            except ProviderError as exc:
                rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in bridge_rows)
                bridge_mapped = [[] for _ in bridge_jobs]

        # Germany cross-venue source rescue.  The primary TRADEGATE bridge
        # intentionally starts with ID_EXCH_SYMBOL + source MIC because that is
        # the strongest same-symbol proof.  Live audit evidence showed a small
        # class where that lookup is empty even though exact TradingView ISIN +
        # the same source MIC resolves cleanly in OpenFIGI.  Batch only those
        # primary source misses and preserve the exact source MIC; no source
        # venue is guessed and the later shareClassFIGI bridge remains mandatory.
        bridge_source_isin_fallback_by_id: dict[str, list[tuple[str, OpenFigiIdentity]]] = defaultdict(list)
        bridge_source_isin_jobs: list[dict] = []
        bridge_source_isin_layout: list[tuple[TvRow, str]] = []
        bridge_source_isin_rows: set[str] = set()
        for r, source_mics, _target_mic, offset, count, isin_bridge in bridge_layout:
            if isin_bridge or not r.isin:
                continue
            chunks = bridge_mapped[offset:offset + count]
            if len(chunks) != count:
                continue
            primary_source_matches = [
                (mic, x)
                for mic, identities in zip(source_mics, chunks[:-1])
                for x in identities
                if punctuation_key(x.ticker or "") == punctuation_key(r.symbol)
                and openfigi_type_compatible(r, x)
            ]
            if primary_source_matches:
                continue
            bridge_source_isin_rows.add(r.tv_id)
            for mic in source_mics:
                bridge_source_isin_jobs.append({
                    "idType": "ID_ISIN",
                    "idValue": r.isin,
                    "micCode": mic,
                })
                bridge_source_isin_layout.append((r, mic))

        if bridge_source_isin_jobs:
            self.stats["openfigi_bridge_source_isin_fallback_rows"] += len(bridge_source_isin_rows)
            self.stats["openfigi_bridge_source_isin_fallback_jobs"] += len(bridge_source_isin_jobs)
            try:
                source_isin_mapped = self.openfigi.map_jobs(bridge_source_isin_jobs)
                self.stats["openfigi_jobs"] += len(bridge_source_isin_jobs)
                self.stats["openfigi_http_batches"] += (
                    len(bridge_source_isin_jobs) + self.openfigi.batch_size - 1
                ) // self.openfigi.batch_size
            except ProviderError:
                source_isin_mapped = [[] for _ in bridge_source_isin_jobs]
                self.stats["openfigi_bridge_source_isin_fallback_unavailable"] += len(bridge_source_isin_jobs)

            for (r, mic), identities in zip(bridge_source_isin_layout, source_isin_mapped):
                selected, collapsed = _select_isin_bridge_target(r, identities)
                if selected is None:
                    continue
                bridge_source_isin_fallback_by_id[r.tv_id].append((mic, selected))
                self.stats["openfigi_bridge_source_isin_fallback_matches"] += 1
                self.stats[
                    f"openfigi_bridge_source_isin_fallback_matches_{_telemetry_token(r.prefix)}"
                ] += 1
                self.stats[
                    f"openfigi_bridge_source_isin_fallback_matches_{_telemetry_token(mic)}"
                ] += 1
                if collapsed:
                    self.stats["openfigi_bridge_source_isin_fallback_collapses"] += 1

        for r, source_mics, target_mic, offset, count, isin_bridge in bridge_layout:
            prefix_token = _telemetry_token(r.prefix)
            self.stats[f"bridge_rows_{prefix_token}"] += 1
            chunks = bridge_mapped[offset:offset + count]
            if len(chunks) != count:
                self.stats[f"bridge_response_mismatch_{prefix_token}"] += 1
                rejected.append(self._reject(r, "OPENFIGI_BRIDGE_RESPONSE_MISMATCH"))
                continue

            source_raw_count = sum(len(identities) for identities in chunks[:-1])
            target_raw_count = len(chunks[-1])
            source_matches: list[tuple[str, OpenFigiIdentity]] = []
            for mic, identities in zip(source_mics, chunks[:-1]):
                for x in identities:
                    symbol_ok = isin_bridge or punctuation_key(x.ticker or "") == punctuation_key(r.symbol)
                    if symbol_ok and openfigi_type_compatible(r, x):
                        source_matches.append((mic, x))

            target_matches = [
                x for x in chunks[-1]
                if (isin_bridge or punctuation_key(x.ticker or "") == punctuation_key(r.symbol))
                and openfigi_type_compatible(r, x)
            ]
            # Diagnostic only: distinguish a true scoped OpenFIGI coverage gap
            # from a provider taxonomy/symbol post-filter mismatch.  This does
            # not change the fail-closed bridge decision.
            if not source_matches:
                self.stats[f"bridge_source_no_match_{prefix_token}"] += 1
                self.stats[
                    f"bridge_source_{'empty' if source_raw_count == 0 else 'postfilter_mismatch'}_{prefix_token}"
                ] += 1

            source_isin_fallback_used = False
            if not source_matches:
                rescued_source_matches = list(bridge_source_isin_fallback_by_id.get(r.tv_id, ()))
                if rescued_source_matches:
                    source_matches.extend(rescued_source_matches)
                    source_isin_fallback_used = True
                    self.stats["bridge_source_isin_fallback_matches"] += 1
                    self.stats[f"bridge_source_isin_fallback_matches_{prefix_token}"] += 1

            if not target_matches:
                self.stats[f"bridge_target_no_match_{prefix_token}"] += 1
                self.stats[
                    f"bridge_target_{'empty' if target_raw_count == 0 else 'postfilter_mismatch'}_{prefix_token}"
                ] += 1
                if r.isin and r.tv_id not in regional_target_probe_seen:
                    regional_target_probe_seen.add(r.tv_id)
                    regional_target_probe_rows.append(r)
                    regional_bridge_context_by_id[r.tv_id] = {
                        "source_matches": tuple(source_matches),
                        "source_mics": source_mics,
                        "isin_bridge": isin_bridge,
                        "source_isin_fallback": source_isin_fallback_used,
                    }
            elif (
                not source_matches
                and r.isin
                and not (isin_bridge and target_matches and len(source_mics) == 1)
                and r.tv_id not in regional_target_probe_seen
            ):
                # The default target may exist even when the source venue is
                # absent from OpenFIGI.  For German bridge namespaces, keep the
                # row eligible for an exact-ISIN regional target proof rather
                # than stopping at OPENFIGI_SOURCE_NO_MATCH.  Admission below
                # still requires a non-null, unambiguous target shareClassFIGI
                # and Yahoo's ordinary German quote contract.
                regional_target_probe_seen.add(r.tv_id)
                regional_target_probe_rows.append(r)
                regional_bridge_context_by_id[r.tv_id] = {
                    "source_matches": tuple(source_matches),
                    "source_mics": source_mics,
                    "isin_bridge": isin_bridge,
                    "source_isin_fallback": source_isin_fallback_used,
                }
            # LS Exchange (HAML) and occasional LSSI rows are not always
            # represented by OpenFIGI at the source venue.  For an ISIN bridge
            # with exactly one reviewed source MIC, an exact TradingView ISIN
            # plus an unambiguous ``ID_ISIN + target MIC`` OpenFIGI result is
            # sufficient security-level evidence to reach Yahoo's target venue.
            # The source venue is preserved but no source FIGI is fabricated.
            if isin_bridge and not source_matches and target_matches and len(source_mics) == 1:
                target_of, target_collapsed = _select_isin_bridge_target(r, target_matches)
                if target_of is not None and target_of.ticker:
                    source_security = OpenFigiIdentity(
                        figi=None,
                        composite_figi=None,
                        share_class_figi=target_of.share_class_figi,
                        ticker=r.symbol,
                        name=r.name or target_of.name,
                        security_type=target_of.security_type,
                        security_type2=target_of.security_type2,
                        exch_code=None,
                    )
                    yahoo_symbol = yahoo_listing_symbol(
                        target_of.ticker, target_mic, r.prefix, tv_type_kind(r)
                    )
                    pending.append({
                        "row": r,
                        "identity": target_of,
                        "source_identity": source_security,
                        "target_identity": target_of,
                        "source_mic": source_mics[0],
                        "source_venue_code": None,
                        "target_mic": target_mic,
                        "yahoo_symbol": yahoo_symbol,
                        "mapping_method": "TV_ISIN_TARGET_BRIDGE",
                    })
                    self.stats["tv_isin_target_bridge_matches"] += 1
                    self.stats[f"tv_isin_target_bridge_matches_{prefix_token}"] += 1
                    if target_collapsed:
                        self.stats["bridge_target_share_class_collapses"] += 1
                        self.stats[f"bridge_target_share_class_collapses_{prefix_token}"] += 1
                    continue

            if isin_bridge and (not source_matches or not target_matches) and r.tv_id not in isin_bridge_probe_seen:
                isin_bridge_probe_seen.add(r.tv_id)
                isin_bridge_probe_rows.append(r)

            if not source_matches:
                rejected.append(self._reject(r, "OPENFIGI_SOURCE_NO_MATCH"))
                continue
            if not target_matches:
                rejected.append(self._reject(r, "OPENFIGI_TARGET_NO_MATCH"))
                continue

            source_share_classes = {x.share_class_figi for _, x in source_matches if x.share_class_figi}
            target_by_share = {x.share_class_figi: x for x in target_matches if x.share_class_figi}
            overlap = source_share_classes & set(target_by_share)
            if len(overlap) != 1:
                reason = "OPENFIGI_SHARE_CLASS_NO_MATCH" if not overlap else f"OPENFIGI_SHARE_CLASS_AMBIGUOUS:{len(overlap)}"
                rejected.append(self._reject(r, reason))
                continue

            share_class = next(iter(overlap))
            source_for_share = [(mic, x) for mic, x in source_matches if x.share_class_figi == share_class]
            target_for_share = [x for x in target_matches if x.share_class_figi == share_class]
            if len(source_for_share) != 1:
                self.stats[f"bridge_source_venue_ambiguous_{prefix_token}"] += 1
                rejected.append(self._reject(r, f"OPENFIGI_SOURCE_VENUE_AMBIGUOUS:{len(source_for_share)}"))
                continue

            if isin_bridge:
                target_of, target_collapsed = _select_isin_bridge_target(
                    r, target_for_share, required_share_class=share_class
                )
            elif len(target_for_share) == 1:
                target_of, target_collapsed = target_for_share[0], False
            else:
                target_of, target_collapsed = None, False
            if target_of is None:
                self.stats[f"bridge_target_ambiguous_{prefix_token}"] += 1
                rejected.append(self._reject(r, f"OPENFIGI_TARGET_AMBIGUOUS:{len(target_for_share)}"))
                continue
            if target_collapsed:
                self.stats["bridge_target_share_class_collapses"] += 1
                self.stats[f"bridge_target_share_class_collapses_{prefix_token}"] += 1

            source_mic, source_of = source_for_share[0]
            suffix = MIC_TO_YAHOO_SUFFIX.get(target_mic)
            if suffix is None:
                rejected.append(self._reject(r, f"YAHOO_SUFFIX_UNKNOWN:{target_mic}"))
                continue
            yahoo_symbol = yahoo_listing_symbol(target_of.ticker or r.symbol, target_mic, r.prefix, tv_type_kind(r))
            pending.append({
                "row": r,
                "identity": source_of,
                "source_identity": source_of,
                "target_identity": target_of,
                "source_mic": source_mic,
                "source_venue_code": None,
                "target_mic": target_mic,
                "yahoo_symbol": yahoo_symbol,
                "mapping_method": (
                    "ISIN_SHARE_CLASS_BRIDGE"
                    if isin_bridge
                    else "ISIN_SOURCE_SHARE_CLASS_BRIDGE"
                    if source_isin_fallback_used
                    else "SHARE_CLASS_BRIDGE"
                ),
            })
            self.stats["cross_venue_share_class_matches"] += 1
            if isin_bridge:
                self.stats["isin_bridge_share_class_matches"] += 1

        # Regional German target fallback for bridge rows whose Xetra target is
        # absent.  Exact TradingView ISIN is probed only at the bounded regional
        # MIC set already supported by the resolver, and every candidate must
        # independently satisfy Yahoo's normal currency/type/venue contract.
        #
        # Multiple valid regional venues are *quote-target* alternatives, not an
        # identity ambiguity, provided they still prove one security.  GETTEX and
        # TRADEGATE retain the original source-side shareClassFIGI bridge.  LSX/LS
        # may use the already-established one-sided exact-ISIN contract when their
        # source venue is absent from OpenFIGI.  A deterministic MIC priority then
        # chooses one Yahoo quote venue without changing security identity.
        if regional_target_probe_rows:
            # v0.3.52: build regional OpenFIGI work once per exact ISIN rather
            # than once per TradingView row.  The raw provider evidence is safe
            # to share because the lookup key is exact ID_ISIN + MIC. Selection
            # remains row-specific below, so TradingView type/taxonomy guards are
            # unchanged even when the same security is exposed by several German
            # provider namespaces (GETTEX/LS/LSX/TRADEGATE).
            regional_rows_by_isin: dict[str, list[TvRow]] = defaultdict(list)
            regional_isin_order: list[str] = []
            for r in regional_target_probe_rows:
                isin_key = (r.isin or "").upper().strip()
                if isin_key not in regional_rows_by_isin:
                    regional_isin_order.append(isin_key)
                regional_rows_by_isin[isin_key].append(r)

            regional_jobs: list[dict] = []
            regional_layout: list[tuple[str, str]] = []
            for isin_key in regional_isin_order:
                for mic in GERMANY_REGIONAL_TARGET_MICS:
                    regional_jobs.append({"idType": "ID_ISIN", "idValue": isin_key, "micCode": mic})
                    regional_layout.append((isin_key, mic))

            row_equivalent_jobs = len(regional_target_probe_rows) * len(GERMANY_REGIONAL_TARGET_MICS)
            self.stats["openfigi_regional_target_probe_rows"] += len(regional_target_probe_rows)
            self.stats["openfigi_regional_target_probe_security_groups"] += len(regional_isin_order)
            self.stats["openfigi_regional_target_probe_grouped_row_reuses"] += (
                len(regional_target_probe_rows) - len(regional_isin_order)
            )
            self.stats["openfigi_regional_target_probe_row_equivalent_jobs"] += row_equivalent_jobs
            self.stats["openfigi_regional_target_probe_jobs_saved_by_grouping"] += (
                row_equivalent_jobs - len(regional_jobs)
            )

            try:
                regional_mapped = self.openfigi.map_jobs(regional_jobs)
                self.stats["openfigi_regional_target_probe_jobs"] += len(regional_jobs)
                self.stats["openfigi_jobs"] += len(regional_jobs)
                self.stats["openfigi_http_batches"] += (len(regional_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
            except ProviderError:
                regional_mapped = [[] for _ in regional_jobs]
                self.stats["openfigi_regional_target_probe_unavailable"] += len(regional_jobs)

            regional_raw_by_isin_mic: dict[tuple[str, str], list[OpenFigiIdentity]] = {
                key: identities
                for key, identities in zip(regional_layout, regional_mapped)
            }

            regional_candidates: list[tuple[TvRow, str, str, OpenFigiIdentity]] = []
            openfigi_mics_by_row: dict[str, set[str]] = defaultdict(set)
            for isin_key in regional_isin_order:
                rows_for_isin = regional_rows_by_isin[isin_key]
                for r in rows_for_isin:
                    prefix_token = _telemetry_token(r.prefix)
                    for mic in GERMANY_REGIONAL_TARGET_MICS:
                        identities = regional_raw_by_isin_mic.get((isin_key, mic), [])
                        selected, collapsed = _select_isin_bridge_target(r, identities)
                        if selected is None or not selected.ticker:
                            continue
                        openfigi_mics_by_row[r.tv_id].add(mic)
                        self.stats["openfigi_regional_target_probe_matches"] += 1
                        self.stats[f"openfigi_regional_target_probe_matches_{mic}"] += 1
                        self.stats[f"openfigi_regional_target_probe_matches_{prefix_token}_{mic}"] += 1
                        if collapsed:
                            self.stats["openfigi_regional_target_probe_collapses"] += 1
                        regional_candidates.append((
                            r, mic,
                            yahoo_listing_symbol(selected.ticker, mic, r.prefix, tv_type_kind(r)),
                            selected,
                        ))

            for r in regional_target_probe_rows:
                mics = openfigi_mics_by_row.get(r.tv_id, set())
                prefix_token = _telemetry_token(r.prefix)
                if not mics:
                    self.stats["openfigi_regional_target_probe_no_match_rows"] += 1
                    self.stats[f"openfigi_regional_target_probe_no_match_rows_{prefix_token}"] += 1
                elif len(mics) == 1:
                    self.stats["openfigi_regional_target_probe_unique_mic_rows"] += 1
                    self.stats[f"openfigi_regional_target_probe_unique_mic_rows_{prefix_token}"] += 1
                else:
                    self.stats["openfigi_regional_target_probe_multi_mic_rows"] += 1
                    self.stats[f"openfigi_regional_target_probe_multi_mic_rows_{prefix_token}"] += 1

            yahoo_valid_by_row: dict[str, list[tuple[TvRow, str, str, OpenFigiIdentity]]] = defaultdict(list)
            if regional_candidates:
                symbols = [symbol for _, _, symbol, _ in regional_candidates]
                try:
                    regional_quotes = self.yahoo.quotes(symbols)
                    batch_size = max(1, int(getattr(self.yahoo, "batch_size", 75)))
                    self.stats["yahoo_regional_target_probe_candidates"] += len(regional_candidates)
                    self.stats["yahoo_regional_target_probe_batches"] += (len(dict.fromkeys(symbols)) + batch_size - 1) // batch_size
                except ProviderError:
                    regional_quotes = {}
                    self.stats["yahoo_regional_target_probe_unavailable"] += len(regional_candidates)

                yahoo_mics_by_row: dict[str, set[str]] = defaultdict(set)
                for r, mic, symbol, selected in regional_candidates:
                    q = regional_quotes.get(symbol)
                    prefix_token = _telemetry_token(r.prefix)
                    regular_ok = _non_us_quote_compatible(r, mic, symbol, q, False)
                    taxonomy_ok = _germany_regional_yahoo_fund_taxonomy_anomaly_compatible(
                        r, mic, symbol, q, selected, "REGIONAL_PROBE"
                    )
                    if regular_ok or taxonomy_ok:
                        yahoo_mics_by_row[r.tv_id].add(mic)
                        yahoo_valid_by_row[r.tv_id].append((r, mic, symbol, selected))
                        self.stats["yahoo_regional_target_probe_matches"] += 1
                        self.stats[f"yahoo_regional_target_probe_matches_{mic}"] += 1
                        self.stats[f"yahoo_regional_target_probe_matches_{prefix_token}_{mic}"] += 1
                        if taxonomy_ok and not regular_ok:
                            self.stats["yahoo_regional_target_probe_taxonomy_anomaly_matches"] += 1
                            self.stats[f"yahoo_regional_target_probe_taxonomy_anomaly_matches_{_telemetry_token(q.quote_type if q else None)}"] += 1
                    elif q is None:
                        self.stats["yahoo_regional_target_probe_missing"] += 1
                    else:
                        reason = _non_us_quote_rejection_reason(r, mic, symbol, q, False) or "INCOMPATIBLE"
                        reason_token = _telemetry_token(reason.split(":", 1)[0])
                        self.stats[f"yahoo_regional_target_probe_block_{reason_token}"] += 1

                # Yahoo v7 occasionally omits thin German regional rows from a
                # bulk response even though the same symbol is returned on a
                # subsequent request. Retry only rows that received *no* valid
                # candidate at all; this keeps the extra work bounded while
                # preserving the exact same currency/type/venue contract.
                retry_row_ids = {
                    r.tv_id for r in regional_target_probe_rows
                    if not yahoo_valid_by_row.get(r.tv_id)
                }
                if retry_row_ids:
                    retry_records = [
                        record for record in regional_candidates
                        if record[0].tv_id in retry_row_ids
                    ]
                    retry_symbols = list(dict.fromkeys(record[2] for record in retry_records))
                    try:
                        retry_quotes = self.yahoo.quotes(retry_symbols) if retry_symbols else {}
                        if retry_symbols:
                            self.stats["yahoo_regional_target_retry_rows"] += len(retry_row_ids)
                            self.stats["yahoo_regional_target_retry_candidates"] += len(retry_records)
                            self.stats["yahoo_regional_target_retry_batches"] += (
                                len(retry_symbols) + batch_size - 1
                            ) // batch_size
                    except ProviderError:
                        retry_quotes = {}
                        self.stats["yahoo_regional_target_retry_unavailable"] += len(retry_row_ids)

                    seen_retry: set[tuple[str, str, str]] = set()
                    for r, mic, symbol, selected in retry_records:
                        key = (r.tv_id, mic, symbol)
                        if key in seen_retry:
                            continue
                        seen_retry.add(key)
                        q = retry_quotes.get(symbol)
                        regular_ok = _non_us_quote_compatible(r, mic, symbol, q, False)
                        taxonomy_ok = _germany_regional_yahoo_fund_taxonomy_anomaly_compatible(
                            r, mic, symbol, q, selected, "REGIONAL_PROBE_RETRY"
                        )
                        if regular_ok or taxonomy_ok:
                            yahoo_mics_by_row[r.tv_id].add(mic)
                            yahoo_valid_by_row[r.tv_id].append((r, mic, symbol, selected))
                            self.stats["yahoo_regional_target_retry_matches"] += 1
                            self.stats[
                                f"yahoo_regional_target_retry_matches_{_telemetry_token(r.prefix)}"
                            ] += 1
                            self.stats[f"yahoo_regional_target_retry_matches_{mic}"] += 1
                            if taxonomy_ok and not regular_ok:
                                self.stats["yahoo_regional_target_retry_taxonomy_anomaly_matches"] += 1

                for r in regional_target_probe_rows:
                    mics = yahoo_mics_by_row.get(r.tv_id, set())
                    prefix_token = _telemetry_token(r.prefix)
                    if not mics:
                        self.stats["yahoo_regional_target_probe_no_match_rows"] += 1
                        self.stats[f"yahoo_regional_target_probe_no_match_rows_{prefix_token}"] += 1
                    elif len(mics) == 1:
                        self.stats["yahoo_regional_target_probe_unique_mic_rows"] += 1
                        self.stats[f"yahoo_regional_target_probe_unique_mic_rows_{prefix_token}"] += 1
                    else:
                        self.stats["yahoo_regional_target_probe_multi_mic_rows"] += 1
                        self.stats[f"yahoo_regional_target_probe_multi_mic_rows_{prefix_token}"] += 1

            priority = {mic: i for i, mic in enumerate(GERMANY_REGIONAL_TARGET_MICS)}
            regional_rescued_ids: set[str] = set()
            for r in regional_target_probe_rows:
                valid = yahoo_valid_by_row.get(r.tv_id, [])
                if not valid:
                    continue
                prefix_token = _telemetry_token(r.prefix)
                ctx = regional_bridge_context_by_id.get(r.tv_id) or {}
                source_matches = list(ctx.get("source_matches") or ())
                source_mics = tuple(ctx.get("source_mics") or ())
                isin_bridge = bool(ctx.get("isin_bridge"))

                eligible: list[tuple[TvRow, str, str, OpenFigiIdentity, str | None, OpenFigiIdentity | None]] = []
                one_sided_tv_isin = False
                if source_matches:
                    for vr, mic, symbol, target_of in valid:
                        share = target_of.share_class_figi
                        if not share:
                            continue
                        source_for_share = [
                            (source_mic, source_of)
                            for source_mic, source_of in source_matches
                            if source_of.share_class_figi == share
                        ]
                        if len(source_for_share) != 1:
                            continue
                        source_mic, source_of = source_for_share[0]
                        eligible.append((vr, mic, symbol, target_of, source_mic, source_of))
                    if not eligible:
                        self.stats["regional_target_bridge_source_share_class_no_match"] += 1
                        self.stats[f"regional_target_bridge_source_share_class_no_match_{prefix_token}"] += 1
                        continue
                elif r.isin and r.prefix in {"GETTEX", "LS", "LSX", "TRADEGATE"}:
                    # Security-level one-sided proof for German bridge namespaces.
                    # TradingView supplied the exact ISIN, every regional target
                    # candidate was independently resolved by ID_ISIN + exact MIC,
                    # and Yahoo already passed the ordinary German quote contract.
                    # We deliberately do not invent a source FIGI or an exact source
                    # MIC when a provider namespace spans more than one reviewed MIC.
                    source_mic_hint = source_mics[0] if len(source_mics) == 1 else None
                    eligible = [
                        (*record, source_mic_hint, None)
                        for record in valid
                        if record[3].share_class_figi
                    ]
                    if not eligible:
                        self.stats["regional_target_bridge_source_proof_missing"] += 1
                        self.stats[f"regional_target_bridge_source_proof_missing_{prefix_token}"] += 1
                        continue
                    one_sided_tv_isin = True
                else:
                    self.stats["regional_target_bridge_source_proof_missing"] += 1
                    self.stats[f"regional_target_bridge_source_proof_missing_{prefix_token}"] += 1
                    continue

                # All candidate targets came from the same exact ISIN.  Still
                # fail closed if OpenFIGI explicitly assigns conflicting non-null
                # share classes across otherwise-valid regional targets.
                target_shares = {
                    record[3].share_class_figi for record in eligible
                    if record[3].share_class_figi
                }
                if len(target_shares) > 1:
                    self.stats["regional_target_bridge_security_ambiguous"] += 1
                    self.stats[f"regional_target_bridge_security_ambiguous_{prefix_token}"] += 1
                    continue

                chosen = min(eligible, key=lambda x: priority.get(x[1], len(priority)))
                _, target_mic, yahoo_symbol, target_of, source_mic, source_of = chosen
                source_venue_code = None
                if source_of is None:
                    source_of = OpenFigiIdentity(
                        figi=None,
                        composite_figi=None,
                        share_class_figi=target_of.share_class_figi,
                        ticker=r.symbol,
                        name=r.name or target_of.name,
                        security_type=target_of.security_type,
                        security_type2=target_of.security_type2,
                        exch_code=None,
                    )
                    if one_sided_tv_isin and len(source_mics) != 1:
                        mapping_method = "TV_ISIN_GERMANY_REGIONAL_TARGET_BRIDGE"
                        source_venue_code = r.prefix
                        self.stats["tv_isin_germany_regional_target_bridge_matches"] += 1
                        self.stats[
                            f"tv_isin_germany_regional_target_bridge_matches_{prefix_token}"
                        ] += 1
                    else:
                        mapping_method = "TV_ISIN_REGIONAL_TARGET_BRIDGE"
                        self.stats["tv_isin_regional_target_bridge_matches"] += 1
                        self.stats[f"tv_isin_regional_target_bridge_matches_{prefix_token}"] += 1
                    identity = target_of
                else:
                    mapping_method = (
                        "ISIN_REGIONAL_SHARE_CLASS_BRIDGE"
                        if isin_bridge
                        else "ISIN_SOURCE_REGIONAL_SHARE_CLASS_BRIDGE"
                        if bool(ctx.get("source_isin_fallback"))
                        else "REGIONAL_SHARE_CLASS_BRIDGE"
                    )
                    identity = source_of
                    self.stats["regional_share_class_bridge_matches"] += 1
                    self.stats[f"regional_share_class_bridge_matches_{prefix_token}"] += 1

                pending.append({
                    "row": r,
                    "identity": identity,
                    "source_identity": source_of,
                    "target_identity": target_of,
                    "source_mic": source_mic,
                    "source_venue_code": source_venue_code,
                    "target_mic": target_mic,
                    "yahoo_symbol": yahoo_symbol,
                    "mapping_method": mapping_method,
                })
                regional_rescued_ids.add(r.tv_id)
                self.stats["regional_target_bridge_matches"] += 1
                self.stats[f"regional_target_bridge_matches_{prefix_token}"] += 1
                self.stats[f"regional_target_bridge_matches_{target_mic}"] += 1
                if len(eligible) > 1:
                    self.stats["regional_target_bridge_multi_mic_matches"] += 1
                    self.stats[f"regional_target_bridge_multi_mic_matches_{prefix_token}"] += 1

            if regional_rescued_ids:
                rejected = [b for b in rejected if b.tv_id not in regional_rescued_ids]
                # Once an exact regional target has been admitted, the old
                # unscoped diagnostic no longer adds evidence and would only
                # spend another OpenFIGI job for the same security.
                isin_bridge_probe_rows = [
                    row for row in isin_bridge_probe_rows
                    if row.tv_id not in regional_rescued_ids
                ]

        # Diagnostic-only unscoped ISIN probe for failed ISIN bridges.  The
        # official OpenFIGI mapping API permits ID_ISIN without micCode; use it
        # only to determine whether OpenFIGI knows the security at all when a
        # venue-scoped MUNC/MUND/HAML/LSSI/XETR job returned no compatible row.
        # Probe results never create or upgrade a binding.
        if isin_bridge_probe_rows:
            probe_jobs = [{"idType": "ID_ISIN", "idValue": r.isin} for r in isin_bridge_probe_rows]
            try:
                probe_mapped = self.openfigi.map_jobs(probe_jobs)
                self.stats["openfigi_isin_bridge_unscoped_probe_jobs"] += len(probe_jobs)
                self.stats["openfigi_jobs"] += len(probe_jobs)
                self.stats["openfigi_http_batches"] += (len(probe_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
            except ProviderError:
                probe_mapped = [[] for _ in probe_jobs]
                self.stats["openfigi_isin_bridge_unscoped_probe_unavailable"] += len(probe_jobs)

            for r, identities in zip(isin_bridge_probe_rows, probe_mapped):
                prefix_token = _telemetry_token(r.prefix)
                compatible = [x for x in identities if openfigi_type_compatible(r, x)]
                if not compatible:
                    self.stats["openfigi_isin_bridge_unscoped_unknown"] += 1
                    self.stats[f"openfigi_isin_bridge_unscoped_unknown_{prefix_token}"] += 1
                    continue
                self.stats["openfigi_isin_bridge_unscoped_known"] += 1
                self.stats[f"openfigi_isin_bridge_unscoped_known_{prefix_token}"] += 1
                shares = {x.share_class_figi for x in compatible if x.share_class_figi}
                if len(shares) == 1 and all(x.share_class_figi for x in compatible):
                    self.stats["openfigi_isin_bridge_unscoped_unique_share_class"] += 1
                    self.stats[f"openfigi_isin_bridge_unscoped_unique_share_class_{prefix_token}"] += 1
                elif len(shares) > 1:
                    self.stats["openfigi_isin_bridge_unscoped_share_class_ambiguous"] += 1
                    self.stats[f"openfigi_isin_bridge_unscoped_share_class_ambiguous_{prefix_token}"] += 1
                else:
                    self.stats["openfigi_isin_bridge_unscoped_share_class_missing"] += 1
                    self.stats[f"openfigi_isin_bridge_unscoped_share_class_missing_{prefix_token}"] += 1

                ticker_keys = {punctuation_key(x.ticker or "") for x in compatible if x.ticker}
                if len(ticker_keys) == 1 and all(x.ticker for x in compatible):
                    self.stats["openfigi_isin_bridge_unscoped_unique_ticker"] += 1
                    self.stats[f"openfigi_isin_bridge_unscoped_unique_ticker_{prefix_token}"] += 1
                elif len(ticker_keys) > 1:
                    self.stats["openfigi_isin_bridge_unscoped_ticker_ambiguous"] += 1
                    self.stats[f"openfigi_isin_bridge_unscoped_ticker_ambiguous_{prefix_token}"] += 1
                else:
                    self.stats["openfigi_isin_bridge_unscoped_ticker_missing"] += 1
                    self.stats[f"openfigi_isin_bridge_unscoped_ticker_missing_{prefix_token}"] += 1

        # OpenFIGI exchange-code -> MIC share-class bridges.  LSIN is TradingView's
        # London International namespace.  OpenFIGI models that source as exchCode
        # LI rather than a distinct ISO MIC, so require the source LI identity and
        # the XLON target listing to share exactly one shareClassFIGI.
        exch_jobs: list[dict] = []
        exch_layout: list[tuple[TvRow, str, str, int]] = []
        for r in exchcode_bridge_rows:
            cfg = EXCHCODE_SHARE_CLASS_BRIDGES[r.prefix]
            source_code = str(cfg["source_exch_code"])
            target_mic = str(cfg["target_mic"])
            offset = len(exch_jobs)
            exch_jobs.extend([
                {
                    "idType": "ID_EXCH_SYMBOL",
                    "idValue": r.symbol,
                    "exchCode": source_code,
                    "currency": openfigi_currency(r.currency),
                    "securityType2": openfigi_security_type(r),
                },
                {
                    "idType": "ID_EXCH_SYMBOL",
                    "idValue": r.symbol,
                    "micCode": target_mic,
                    "currency": openfigi_currency(r.currency),
                    "securityType2": openfigi_security_type(r),
                },
            ])
            exch_layout.append((r, source_code, target_mic, offset))

        exch_mapped: list[list[OpenFigiIdentity]] = []
        if exch_jobs:
            try:
                exch_mapped = self.openfigi.map_jobs(exch_jobs)
                self.stats["openfigi_jobs"] += len(exch_jobs)
                self.stats["openfigi_exchcode_bridge_jobs"] += len(exch_jobs)
                self.stats["openfigi_http_batches"] += (len(exch_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
            except ProviderError as exc:
                rejected.extend(self._reject(r, f"OPENFIGI_UNAVAILABLE: {exc}") for r in exchcode_bridge_rows)
                exch_mapped = [[] for _ in exch_jobs]

        for r, source_code, target_mic, offset in exch_layout:
            if offset + 1 >= len(exch_mapped):
                rejected.append(self._reject(r, "OPENFIGI_EXCHCODE_BRIDGE_RESPONSE_MISMATCH"))
                continue
            source_matches = [
                x for x in exch_mapped[offset]
                if punctuation_key(x.ticker or "") == punctuation_key(r.symbol)
                and openfigi_type_compatible(r, x)
            ]
            target_matches = [
                x for x in exch_mapped[offset + 1]
                if punctuation_key(x.ticker or "") == punctuation_key(r.symbol)
                and openfigi_type_compatible(r, x)
            ]
            if not source_matches:
                rejected.append(self._reject(r, "OPENFIGI_SOURCE_NO_MATCH"))
                continue
            if not target_matches:
                rejected.append(self._reject(r, "OPENFIGI_TARGET_NO_MATCH"))
                continue

            source_by_share: dict[str, list[OpenFigiIdentity]] = defaultdict(list)
            target_by_share: dict[str, list[OpenFigiIdentity]] = defaultdict(list)
            for x in source_matches:
                if x.share_class_figi:
                    source_by_share[x.share_class_figi].append(x)
            for x in target_matches:
                if x.share_class_figi:
                    target_by_share[x.share_class_figi].append(x)
            overlap = set(source_by_share) & set(target_by_share)
            if len(overlap) != 1:
                reason = "OPENFIGI_SHARE_CLASS_NO_MATCH" if not overlap else f"OPENFIGI_SHARE_CLASS_AMBIGUOUS:{len(overlap)}"
                rejected.append(self._reject(r, reason))
                continue
            share_class = next(iter(overlap))
            if len(source_by_share[share_class]) != 1:
                rejected.append(self._reject(r, f"OPENFIGI_SOURCE_AMBIGUOUS:{len(source_by_share[share_class])}"))
                continue
            if len(target_by_share[share_class]) != 1:
                rejected.append(self._reject(r, f"OPENFIGI_TARGET_AMBIGUOUS:{len(target_by_share[share_class])}"))
                continue
            source_of = source_by_share[share_class][0]
            target_of = target_by_share[share_class][0]
            suffix = MIC_TO_YAHOO_SUFFIX.get(target_mic)
            if suffix is None:
                rejected.append(self._reject(r, f"YAHOO_SUFFIX_UNKNOWN:{target_mic}"))
                continue
            yahoo_symbol = yahoo_listing_symbol(target_of.ticker or r.symbol, target_mic, r.prefix, tv_type_kind(r))
            pending.append({
                "row": r,
                "identity": source_of,
                "source_identity": source_of,
                "target_identity": target_of,
                "source_mic": None,
                "source_venue_code": source_code,
                "target_mic": target_mic,
                "yahoo_symbol": yahoo_symbol,
                "mapping_method": "EXCHCODE_SHARE_CLASS_BRIDGE",
            })
            self.stats["exchcode_share_class_matches"] += 1

        ysymbols = sorted({x["yahoo_symbol"] for x in pending})
        try:
            yahoo_quotes = self.yahoo.quotes(ysymbols)
            self.stats["yahoo_http_batches"] += (len(ysymbols) + self.yahoo.batch_size - 1) // self.yahoo.batch_size
        except ProviderError as exc:
            rejected.extend(self._reject(x["row"], f"YAHOO_UNAVAILABLE: {exc}") for x in pending)
            return rejected

        chart_needed: set[str] = set()
        for item in pending:
            r = item["row"]
            ys = item["yahoo_symbol"]
            q0 = yahoo_quotes.get(ys)
            if not _non_us_quote_compatible(
                r, item["target_mic"], ys, q0,
                _strict_yahoo_mapping(item["mapping_method"]),
            ):
                chart_needed.add(ys)
        chart_quotes: dict[str, YahooQuote] = {}
        if chart_needed and hasattr(self.yahoo, "chart_quotes"):
            chart_quotes = self.yahoo.chart_quotes(sorted(chart_needed))
            self.stats["yahoo_chart_fallback_jobs"] += len(chart_needed)
            self.stats["yahoo_chart_fallback_rows"] += len(chart_quotes)

        # Bounded Yahoo alternatives. LSIN may use .IL or .L, but an ADR may
        # try .L only when OpenFIGI already supplied independent identity/venue
        # evidence; Yahoo-only fallback cannot distinguish XLON from XLOM. A
        # small reviewed registry also covers fresh exchange ticker transitions
        # where Yahoo can lag the official TIDM change.
        alternate_by_tv_id: dict[str, str] = {}
        alternate_kind_by_tv_id: dict[str, str] = {}
        alternate_needed: set[str] = set()
        for item in pending:
            r = item["row"]
            ys = item["yahoo_symbol"]
            target_only = _strict_yahoo_mapping(item["mapping_method"])
            q0 = yahoo_quotes.get(ys)
            cq0 = chart_quotes.get(ys)
            primary_ok = _non_us_quote_compatible(r, item["target_mic"], ys, q0, target_only) \
                or _non_us_quote_compatible(r, item["target_mic"], ys, cq0, target_only)
            if primary_ok:
                continue

            reviewed_alias = REVIEWED_YAHOO_SYMBOL_ALIASES.get(r.tv_id)
            if reviewed_alias and item.get("identity") is not None and not target_only:
                alt = str(reviewed_alias["symbol"])
                if alt and alt != ys:
                    alternate_by_tv_id[r.tv_id] = alt
                    alternate_kind_by_tv_id[r.tv_id] = "REVIEWED_YAHOO_SYMBOL_ALIAS"
                    alternate_needed.add(alt)
                    continue

            alt = yahoo_listing_alternative_symbol(r.symbol, item["target_mic"], r.prefix, tv_type_kind(r))
            if alt and alt != ys:
                if tv_type_kind(r) == "ADR" and target_only:
                    continue
                alternate_by_tv_id[r.tv_id] = alt
                alternate_kind_by_tv_id[r.tv_id] = "LSIN_ALT"
                alternate_needed.add(alt)

        alternate_quotes: dict[str, YahooQuote] = {}
        alternate_chart_quotes: dict[str, YahooQuote] = {}
        if alternate_needed:
            alias_symbols = {
                alt for tv_id, alt in alternate_by_tv_id.items()
                if alternate_kind_by_tv_id.get(tv_id) == "REVIEWED_YAHOO_SYMBOL_ALIAS"
            }
            lsin_alt_symbols = {
                alt for tv_id, alt in alternate_by_tv_id.items()
                if alternate_kind_by_tv_id.get(tv_id) == "LSIN_ALT"
            }
            self.stats["reviewed_yahoo_symbol_alias_jobs"] += len(alias_symbols)
            self.stats["yahoo_lsin_alt_fallback_jobs"] += len(lsin_alt_symbols)
            self.stats["yahoo_lsin_dr_alt_fallback_jobs"] += sum(
                1 for item in pending
                if alternate_kind_by_tv_id.get(item["row"].tv_id) == "LSIN_ALT"
                and tv_type_kind(item["row"]) == "ADR"
            )
            self.stats["yahoo_lsin_dr_mutualfund_taxonomy_matches"] += 0
            try:
                alternate_quotes = self.yahoo.quotes(sorted(alternate_needed))
                self.stats["reviewed_yahoo_symbol_alias_rows"] += sum(
                    1 for symbol in alias_symbols if symbol in alternate_quotes
                )
                self.stats["yahoo_lsin_alt_fallback_rows"] += sum(
                    1 for symbol in lsin_alt_symbols if symbol in alternate_quotes
                )
                self.stats["yahoo_lsin_dr_mutualfund_taxonomy_candidates"] += sum(
                    1 for item in pending
                    if alternate_kind_by_tv_id.get(item["row"].tv_id) == "LSIN_ALT"
                    and tv_type_kind(item["row"]) == "ADR"
                    and (alternate_quotes.get(alternate_by_tv_id.get(item["row"].tv_id, "")) is not None)
                    and ((alternate_quotes[alternate_by_tv_id[item["row"].tv_id]].quote_type or "").upper() == "MUTUALFUND")
                )
                self.stats["yahoo_http_batches"] += (len(alternate_needed) + self.yahoo.batch_size - 1) // self.yahoo.batch_size
            except ProviderError:
                alternate_quotes = {}
            alt_chart_needed: set[str] = set()
            for item in pending:
                r = item["row"]
                alt = alternate_by_tv_id.get(r.tv_id)
                if not alt:
                    continue
                target_only = _strict_yahoo_mapping(item["mapping_method"])
                if not _non_us_quote_compatible(r, item["target_mic"], alt, alternate_quotes.get(alt), target_only):
                    alt_chart_needed.add(alt)
            if alt_chart_needed and hasattr(self.yahoo, "chart_quotes"):
                alternate_chart_quotes = self.yahoo.chart_quotes(sorted(alt_chart_needed))
                self.stats["yahoo_chart_fallback_jobs"] += len(alt_chart_needed)
                self.stats["yahoo_chart_fallback_rows"] += len(alternate_chart_quotes)

        verified: list[Binding] = []
        reviewed_mutualfund_candidate_ids: set[str] = set()
        reviewed_mutualfund_match_ids: set[str] = set()
        reviewed_mutualfund_block_by_id: dict[str, str] = {}
        reviewed_mutualfund_venue_observation_by_id: dict[str, tuple[str | None, str | None, str | None]] = {}
        germany_yahoo_failure_probe_items: list[tuple[dict, str]] = []
        germany_probe_prefixes = {"GETTEX", "LS", "LSX", "TRADEGATE", "FWB", "DUS", "HAM", "SWB", "MUN", "HAN"}
        for item in pending:
            r = item["row"]
            ys = item["yahoo_symbol"]
            q = yahoo_quotes.get(ys)
            target_only = _strict_yahoo_mapping(item["mapping_method"])
            cq = chart_quotes.get(ys)
            if not _non_us_quote_compatible(r, item["target_mic"], ys, q, target_only) \
                    and _non_us_quote_compatible(r, item["target_mic"], ys, cq, target_only):
                q = cq
                self.stats["yahoo_chart_fallback_matches"] += 1

            primary_regular_ok = _non_us_quote_compatible(
                r, item["target_mic"], ys, q, target_only
            )
            primary_reviewed_taxonomy_ok = _reviewed_yahoo_mutualfund_taxonomy_anomaly_compatible(
                r, item["target_mic"], ys, q, item.get("identity"), item.get("mapping_method")
            )
            primary_germany_taxonomy_ok = _germany_regional_yahoo_fund_taxonomy_anomaly_compatible(
                r, item["target_mic"], ys, q, item.get("identity"), item.get("mapping_method")
            )
            if (not primary_regular_ok and not primary_reviewed_taxonomy_ok
                    and not primary_germany_taxonomy_ok
                    and _germany_regional_yahoo_fund_taxonomy_anomaly_compatible(
                        r, item["target_mic"], ys, cq, item.get("identity"), item.get("mapping_method")
                    )):
                q = cq
                primary_germany_taxonomy_ok = True
                self.stats["yahoo_chart_fallback_matches"] += 1
            if (q is not None and (q.quote_type or "").upper() in {"MUTUALFUND", "ETF"}
                    and r.prefix in {"GETTEX", "LS", "LSX", "TRADEGATE", "FWB", "DUS", "HAM", "SWB", "MUN", "HAN"}
                    and item["target_mic"] in GERMANY_REGIONAL_TARGET_MICS
                    and tv_type_kind(r) == "STOCK"):
                self.stats["yahoo_germany_regional_fund_taxonomy_candidates"] += 1
                self.stats[f"yahoo_germany_regional_fund_taxonomy_candidates_{_telemetry_token(q.quote_type)}"] += 1
            if primary_germany_taxonomy_ok:
                item["yahoo_type_anomaly"] = "GERMANY_REGIONAL_FUND_TAXONOMY"
                self.stats["yahoo_germany_regional_fund_taxonomy_matches"] += 1
                self.stats[f"yahoo_germany_regional_fund_taxonomy_matches_{_telemetry_token(q.quote_type if q else None)}"] += 1
                self.stats[f"yahoo_germany_regional_fund_taxonomy_matches_{_telemetry_token(r.prefix)}"] += 1
                self.stats[f"yahoo_germany_regional_fund_taxonomy_matches_{_telemetry_token(item['target_mic'])}"] += 1
            if (q is not None and (q.quote_type or "").upper() == "MUTUALFUND"
                    and r.tv_id in REVIEWED_YAHOO_MUTUALFUND_TAXONOMY):
                reviewed_mutualfund_candidate_ids.add(r.tv_id)
                reviewed_mutualfund_venue_observation_by_id[r.tv_id] = (
                    q.exchange, q.full_exchange_name, q.market
                )
                block = _reviewed_yahoo_mutualfund_taxonomy_block_reason(
                    r, item["target_mic"], ys, q, item.get("identity"), item.get("mapping_method")
                )
                if block is not None:
                    reviewed_mutualfund_block_by_id[r.tv_id] = block
            if primary_reviewed_taxonomy_ok:
                item["yahoo_type_anomaly"] = "REVIEWED_MUTUALFUND"
                reviewed_mutualfund_match_ids.add(r.tv_id)
                if q is not None and q.currency is None:
                    self.stats["reviewed_yahoo_mutualfund_currency_unreported_matches"] += 1
                if _reviewed_yahoo_synthetic_yhd_venue(q):
                    item["yahoo_venue_anomaly"] = "REVIEWED_MUTUALFUND_YHD"
                    self.stats["reviewed_yahoo_mutualfund_yhd_venue_matches"] += 1

            # If the reviewed LSIN primary (.IL) is not compatible, try exactly
            # one pre-defined .L alternative. The same metadata contract applies.
            if not (primary_regular_ok or primary_reviewed_taxonomy_ok or primary_germany_taxonomy_ok):
                alt = alternate_by_tv_id.get(r.tv_id)
                if alt:
                    aq = alternate_quotes.get(alt)
                    acq = alternate_chart_quotes.get(alt)
                    aq_regular_ok = _non_us_quote_compatible(
                        r, item["target_mic"], alt, aq, target_only
                    )
                    aq_lsin_dr_taxonomy_ok = _lsin_dr_mutualfund_taxonomy_anomaly_compatible(
                        r, item["target_mic"], alt, aq, item.get("identity"), item.get("mapping_method")
                    )
                    aq_reviewed_taxonomy_ok = _reviewed_yahoo_mutualfund_taxonomy_anomaly_compatible(
                        r, item["target_mic"], alt, aq, item.get("identity"), item.get("mapping_method")
                    )
                    if (aq is not None and (aq.quote_type or "").upper() == "MUTUALFUND"
                            and r.tv_id in REVIEWED_YAHOO_MUTUALFUND_TAXONOMY):
                        reviewed_mutualfund_candidate_ids.add(r.tv_id)
                        reviewed_mutualfund_venue_observation_by_id[r.tv_id] = (
                            aq.exchange, aq.full_exchange_name, aq.market
                        )
                        block = _reviewed_yahoo_mutualfund_taxonomy_block_reason(
                            r, item["target_mic"], alt, aq, item.get("identity"), item.get("mapping_method")
                        )
                        if block is not None:
                            # For LSIN rows the alternate is the final reviewed
                            # candidate, so let it replace any primary-path reason.
                            reviewed_mutualfund_block_by_id[r.tv_id] = block
                    if not (aq_regular_ok or aq_lsin_dr_taxonomy_ok or aq_reviewed_taxonomy_ok) \
                            and _non_us_quote_compatible(r, item["target_mic"], alt, acq, target_only):
                        aq = acq
                        aq_regular_ok = True
                        aq_lsin_dr_taxonomy_ok = False
                        aq_reviewed_taxonomy_ok = False
                        self.stats["yahoo_chart_fallback_matches"] += 1
                    if aq_regular_ok or aq_lsin_dr_taxonomy_ok or aq_reviewed_taxonomy_ok:
                        alt_kind = alternate_kind_by_tv_id.get(r.tv_id)
                        if alt_kind == "REVIEWED_YAHOO_SYMBOL_ALIAS":
                            rule = REVIEWED_YAHOO_SYMBOL_ALIASES.get(r.tv_id) or {}
                            tokens = tuple(str(x).upper() for x in rule.get("name_tokens", ()))
                            yahoo_name = " ".join(x for x in (aq.short_name, aq.long_name) if x).upper()
                            if tokens and not any(token in yahoo_name for token in tokens):
                                aq = None
                        if aq is not None:
                            ys = alt
                            q = aq
                            item["yahoo_symbol"] = alt
                            if alt_kind == "REVIEWED_YAHOO_SYMBOL_ALIAS":
                                item["mapping_method"] = "REVIEWED_YAHOO_TRANSITION_ALIAS"
                                self.stats["reviewed_yahoo_symbol_alias_matches"] += 1
                            else:
                                self.stats["yahoo_lsin_alt_fallback_matches"] += 1
                                if tv_type_kind(r) == "ADR":
                                    self.stats["yahoo_lsin_dr_alt_fallback_matches"] += 1
                                    if aq_lsin_dr_taxonomy_ok:
                                        item["yahoo_type_anomaly"] = "LSIN_DR_MUTUALFUND"
                                        self.stats["yahoo_lsin_dr_mutualfund_taxonomy_matches"] += 1
                                    elif aq_reviewed_taxonomy_ok:
                                        item["yahoo_type_anomaly"] = "REVIEWED_MUTUALFUND"
                                        reviewed_mutualfund_match_ids.add(r.tv_id)
                                        if aq.currency is None:
                                            self.stats["reviewed_yahoo_mutualfund_currency_unreported_matches"] += 1
                                        if _reviewed_yahoo_synthetic_yhd_venue(aq):
                                            item["yahoo_venue_anomaly"] = "REVIEWED_MUTUALFUND_YHD"
                                            self.stats["reviewed_yahoo_mutualfund_yhd_venue_matches"] += 1
            if q is None:
                # A Yahoo chart row can exist for the exact requested symbol yet
                # fail the same compatibility contract. Preserve that explicit
                # contradiction instead of flattening it into YAHOO_NO_MATCH.
                # This is diagnostics only: it does not broaden admission.
                diagnostic_reason = _non_us_quote_rejection_reason(
                    r, item["target_mic"], ys, cq, target_only, source="CHART"
                )
                if diagnostic_reason is None:
                    alt = alternate_by_tv_id.get(r.tv_id)
                    if alt:
                        diagnostic_reason = _non_us_quote_rejection_reason(
                            r, item["target_mic"], alt, alternate_quotes.get(alt),
                            target_only, source="ALT"
                        )
                        if diagnostic_reason is None:
                            diagnostic_reason = _non_us_quote_rejection_reason(
                                r, item["target_mic"], alt, alternate_chart_quotes.get(alt),
                                target_only, source="ALT_CHART"
                            )
                if diagnostic_reason is not None:
                    self.stats["yahoo_incompatible_evidence_rows"] += 1
                    if "CURRENCY_" in diagnostic_reason:
                        self.stats["yahoo_incompatible_currency_rows"] += 1
                    elif "TYPE_" in diagnostic_reason:
                        self.stats["yahoo_incompatible_type_rows"] += 1
                    elif "VENUE_" in diagnostic_reason or "MARKET_" in diagnostic_reason:
                        self.stats["yahoo_incompatible_venue_rows"] += 1
                    elif "SYMBOL_" in diagnostic_reason:
                        self.stats["yahoo_incompatible_symbol_rows"] += 1
                    rejected.append(self._reject(r, diagnostic_reason))
                else:
                    if item.get("japan_regional_exact_listing"):
                        binding = self._verified(
                            r, fh=None, of=item["identity"], y=None,
                            mic=item["target_mic"],
                            source_mic=item["source_mic"],
                            target_mic=item["target_mic"],
                            source_venue_code=item.get("source_venue_code"),
                            mapping_method="JAPAN_REGIONAL_EXACT_OPENFIGI_LISTING",
                            source_of=item["source_identity"],
                            target_of=item["target_identity"],
                        )
                        binding.quote_status = "UNAVAILABLE"
                        verified.append(binding)
                        self.stats["japan_regional_exact_openfigi_listing_matches"] += 1
                    else:
                        rejected.append(self._reject(r, "YAHOO_NO_MATCH"))
                        if r.prefix in germany_probe_prefixes and r.isin:
                            germany_yahoo_failure_probe_items.append((item, "YAHOO_NO_MATCH"))
                continue
            # Normal non-US mappings already have independent OpenFIGI proof, so
            # missing Yahoo metadata is absence of corroboration, not conflict.
            # TARGET_PROVIDER_STRICT_FALLBACK is deliberately different: because
            # OpenFIGI supplied no identity at all, Yahoo must report every key
            # field explicitly and compatibly.
            yahoo_currency_unreported = q.currency is None
            if target_only and q.currency is None:
                rejected.append(self._reject(r, "YAHOO_CURRENCY_UNREPORTED_TARGET_ONLY"))
                if r.prefix in germany_probe_prefixes and r.isin:
                    germany_yahoo_failure_probe_items.append((item, "YAHOO_CURRENCY_UNREPORTED_TARGET_ONLY"))
                continue
            if q.currency is not None and not currency_compatible(r.currency, q.currency):
                rejected.append(self._reject(r, f"YAHOO_CURRENCY_MISMATCH:{q.currency}"))
                continue

            yahoo_type_unreported = q.quote_type is None
            if target_only and q.quote_type is None:
                rejected.append(self._reject(r, "YAHOO_TYPE_UNREPORTED_TARGET_ONLY"))
                continue
            if q.quote_type is not None and not yahoo_type_compatible(r, q.quote_type):
                if item.get("yahoo_type_anomaly") not in {"LSIN_DR_MUTUALFUND", "REVIEWED_MUTUALFUND", "GERMANY_REGIONAL_FUND_TAXONOMY"}:
                    reason = f"YAHOO_TYPE_MISMATCH:{q.quote_type}"
                    rejected.append(self._reject(r, reason))
                    if (
                        r.prefix in germany_probe_prefixes
                        and r.isin
                        and (q.quote_type or "").upper() in {"MUTUALFUND", "ETF"}
                    ):
                        germany_yahoo_failure_probe_items.append((item, reason))
                    continue

            target_mic = item["target_mic"]
            yahoo_venue_unreported = q.exchange is None and q.full_exchange_name is None
            if target_only:
                venue_ok = (not yahoo_venue_unreported) and yahoo_venue_compatible(target_mic, q)
            else:
                venue_ok = yahoo_venue_compatible(target_mic, q)
                if yahoo_venue_unreported:
                    # Yahoo returned a result row for the exact requested symbol.
                    # Identity does not require a live price; price availability is
                    # tracked separately in quote_status. If market is present it
                    # must still agree with the independently proven target MIC.
                    venue_ok = (
                        q.symbol == ys
                        and (q.market is None or yahoo_market_compatible(target_mic, q.market))
                    )
            if (not venue_ok
                    and item.get("yahoo_venue_anomaly") == "REVIEWED_MUTUALFUND_YHD"
                    and _reviewed_yahoo_synthetic_yhd_venue(q)):
                venue_ok = True
            if not venue_ok:
                rejected.append(self._reject(r, f"YAHOO_VENUE_MISMATCH:{target_mic}->{q.exchange}/{q.full_exchange_name}/{q.market}"))
                continue
            binding = self._verified(
                r,
                fh=None,
                of=item["identity"],
                y=q,
                mic=target_mic,
                source_mic=item["source_mic"],
                target_mic=target_mic,
                source_venue_code=item.get("source_venue_code"),
                mapping_method=item["mapping_method"],
                source_of=item["source_identity"],
                target_of=item["target_identity"],
            )
            if item["mapping_method"] == "TARGET_PROVIDER_STRICT_FALLBACK":
                self.stats["target_provider_strict_fallback_matches"] += 1
            elif item["mapping_method"] == "REVIEWED_ISIN_SECURITY_FALLBACK":
                self.stats["reviewed_isin_security_fallback_matches"] += 1
            missing_meta = sum((yahoo_currency_unreported, yahoo_type_unreported, yahoo_venue_unreported))
            if q.price is None:
                binding.quote_status = "UNAVAILABLE"
            elif missing_meta >= 2:
                binding.quote_status = "FRESH_METADATA_UNREPORTED"
            elif yahoo_currency_unreported:
                binding.quote_status = "FRESH_CURRENCY_UNREPORTED"
            elif yahoo_type_unreported:
                binding.quote_status = "FRESH_TYPE_UNREPORTED"
            elif yahoo_venue_unreported:
                binding.quote_status = "FRESH_VENUE_UNREPORTED"
            verified.append(binding)
        # Evidence-gated alternate German regional target fallback for Yahoo
        # coverage/taxonomy failures that remain after normal admission.
        #
        # Every candidate must independently prove the exact TradingView ISIN at
        # a bounded German MIC and pass the *ordinary* Yahoo contract there.  If
        # the current mapping already has OpenFIGI security evidence, the new
        # target must carry the same non-null shareClassFIGI.  A direct German
        # same-venue strict fallback may also be rescued one-sided: exact TV ISIN
        # + exact regional OpenFIGI target + ordinary Yahoo evidence, while the
        # original direct source MIC is retained and no source FIGI is invented.
        if germany_yahoo_failure_probe_items:
            probe_jobs: list[dict] = []
            probe_layout: list[tuple[dict, str, str, int]] = []
            for item, reason in germany_yahoo_failure_probe_items:
                r = item["row"]
                for mic in GERMANY_REGIONAL_TARGET_MICS:
                    if mic == item.get("target_mic"):
                        continue
                    offset = len(probe_jobs)
                    probe_jobs.append({"idType": "ID_ISIN", "idValue": r.isin, "micCode": mic})
                    probe_layout.append((item, reason, mic, offset))
            self.stats["yahoo_failure_regional_probe_rows"] += len(germany_yahoo_failure_probe_items)
            self.stats["yahoo_failure_regional_probe_openfigi_jobs"] += len(probe_jobs)
            try:
                probe_mapped = self.openfigi.map_jobs(probe_jobs)
                self.stats["openfigi_jobs"] += len(probe_jobs)
                self.stats["openfigi_http_batches"] += (len(probe_jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
            except ProviderError:
                probe_mapped = [[] for _ in probe_jobs]

            candidates: list[tuple[dict, str, str, OpenFigiIdentity, str]] = []
            openfigi_mics_by_id: dict[str, set[str]] = defaultdict(set)
            for item, reason, mic, offset in probe_layout:
                if offset >= len(probe_mapped):
                    continue
                r = item["row"]
                target_of, _ = _select_isin_bridge_target(r, probe_mapped[offset])
                if target_of is None:
                    continue
                ref = item.get("target_identity") or item.get("source_identity") or item.get("identity")
                ref_share = getattr(ref, "share_class_figi", None) if ref is not None else None
                if ref_share and target_of.share_class_figi and ref_share != target_of.share_class_figi:
                    self.stats["yahoo_failure_regional_probe_share_class_mismatch"] += 1
                    continue
                ticker = target_of.ticker or r.symbol
                symbol = yahoo_listing_symbol(ticker, mic, r.prefix, tv_type_kind(r))
                candidates.append((item, reason, mic, target_of, symbol))
                openfigi_mics_by_id[r.tv_id].add(mic)
                self.stats["yahoo_failure_regional_probe_openfigi_matches"] += 1
                self.stats[f"yahoo_failure_regional_probe_openfigi_matches_{_telemetry_token(mic)}"] += 1

            symbols = sorted({record[4] for record in candidates})
            try:
                probe_quotes = self.yahoo.quotes(symbols) if symbols else {}
                if symbols:
                    self.stats["yahoo_failure_regional_probe_batches"] += (len(symbols) + self.yahoo.batch_size - 1) // self.yahoo.batch_size
            except ProviderError:
                probe_quotes = {}

            yahoo_mics_by_id: dict[str, set[str]] = defaultdict(set)
            yahoo_valid_by_id: dict[
                str, list[tuple[dict, str, str, OpenFigiIdentity, str, YahooQuote]]
            ] = defaultdict(list)
            for item, reason, mic, target_of, symbol in candidates:
                r = item["row"]
                q = probe_quotes.get(symbol)
                if _non_us_quote_compatible(r, mic, symbol, q, False):
                    yahoo_mics_by_id[r.tv_id].add(mic)
                    yahoo_valid_by_id[r.tv_id].append((item, reason, mic, target_of, symbol, q))
                    self.stats["yahoo_failure_regional_probe_matches"] += 1
                    self.stats[f"yahoo_failure_regional_probe_matches_{_telemetry_token(mic)}"] += 1
                    self.stats[f"yahoo_failure_regional_probe_matches_{_telemetry_token(r.prefix)}"] += 1
                    self.stats[f"yahoo_failure_regional_probe_matches_reason_{_telemetry_token(reason)}"] += 1

            for item, reason in germany_yahoo_failure_probe_items:
                r = item["row"]
                mics = yahoo_mics_by_id.get(r.tv_id, set())
                if not mics:
                    self.stats["yahoo_failure_regional_probe_no_match_rows"] += 1
                    self.stats[f"yahoo_failure_regional_probe_no_match_rows_{_telemetry_token(r.prefix)}"] += 1
                elif len(mics) == 1:
                    self.stats["yahoo_failure_regional_probe_unique_mic_rows"] += 1
                else:
                    self.stats["yahoo_failure_regional_probe_multi_mic_rows"] += 1

            direct_german_prefixes = {"FWB", "DUS", "HAM", "SWB", "MUN", "HAN"}
            priority = {mic: i for i, mic in enumerate(GERMANY_REGIONAL_TARGET_MICS)}
            yahoo_failure_rescued_ids: set[str] = set()
            for item, reason in germany_yahoo_failure_probe_items:
                r = item["row"]
                valid = yahoo_valid_by_id.get(r.tv_id, [])
                if not valid:
                    continue

                ref = item.get("target_identity") or item.get("source_identity") or item.get("identity")
                ref_share = getattr(ref, "share_class_figi", None) if ref is not None else None
                eligible: list[
                    tuple[dict, str, str, OpenFigiIdentity, str, YahooQuote]
                ] = []

                if ref_share:
                    eligible = [
                        record for record in valid
                        if record[3].share_class_figi
                        and record[3].share_class_figi == ref_share
                    ]
                    if not eligible:
                        self.stats["yahoo_failure_regional_fallback_share_class_no_match"] += 1
                        self.stats[
                            f"yahoo_failure_regional_fallback_share_class_no_match_{_telemetry_token(r.prefix)}"
                        ] += 1
                        continue
                    one_sided_tv_isin = False
                elif (
                    item.get("mapping_method") == "TARGET_PROVIDER_STRICT_FALLBACK"
                    and r.prefix in direct_german_prefixes
                    and r.isin
                    and item.get("source_mic") == tv_prefix_mic(r.prefix, self.market)
                ):
                    # OpenFIGI could not prove the direct source listing, but
                    # TradingView supplied an exact ISIN and the direct prefix has
                    # one known source MIC.  The alternate target itself is exact
                    # ISIN + MIC OpenFIGI evidence and Yahoo must pass the normal
                    # OpenFIGI-backed contract there.
                    eligible = [
                        record for record in valid
                        if record[3].share_class_figi
                    ]
                    one_sided_tv_isin = True
                else:
                    self.stats["yahoo_failure_regional_fallback_source_proof_missing"] += 1
                    self.stats[
                        f"yahoo_failure_regional_fallback_source_proof_missing_{_telemetry_token(r.prefix)}"
                    ] += 1
                    continue

                target_shares = {record[3].share_class_figi for record in eligible if record[3].share_class_figi}
                if len(target_shares) != 1:
                    self.stats["yahoo_failure_regional_fallback_security_ambiguous"] += 1
                    self.stats[
                        f"yahoo_failure_regional_fallback_security_ambiguous_{_telemetry_token(r.prefix)}"
                    ] += 1
                    continue

                chosen = min(eligible, key=lambda record: priority.get(record[2], len(priority)))
                _, _reason, target_mic, target_of, yahoo_symbol, q = chosen

                source_of = item.get("source_identity")
                identity = item.get("identity")
                source_mic = item.get("source_mic")
                if one_sided_tv_isin:
                    source_of = OpenFigiIdentity(
                        figi=None,
                        composite_figi=None,
                        share_class_figi=target_of.share_class_figi,
                        ticker=r.symbol,
                        name=r.name or target_of.name,
                        security_type=target_of.security_type,
                        security_type2=target_of.security_type2,
                        exch_code=None,
                    )
                    identity = target_of
                    mapping_method = "TV_ISIN_GERMANY_REGIONAL_TARGET_FALLBACK"
                    self.stats["tv_isin_germany_regional_target_fallback_matches"] += 1
                    self.stats[
                        f"tv_isin_germany_regional_target_fallback_matches_{_telemetry_token(r.prefix)}"
                    ] += 1
                else:
                    mapping_method = "GERMANY_YAHOO_REGIONAL_TARGET_FALLBACK"

                binding = self._verified(
                    r,
                    fh=None,
                    of=identity or target_of,
                    y=q,
                    mic=target_mic,
                    source_mic=source_mic,
                    target_mic=target_mic,
                    source_venue_code=item.get("source_venue_code"),
                    mapping_method=mapping_method,
                    source_of=source_of,
                    target_of=target_of,
                )
                yahoo_currency_unreported = q.currency is None
                yahoo_type_unreported = q.quote_type is None
                yahoo_venue_unreported = q.exchange is None and q.full_exchange_name is None
                missing_meta = sum((yahoo_currency_unreported, yahoo_type_unreported, yahoo_venue_unreported))
                if q.price is None:
                    binding.quote_status = "UNAVAILABLE"
                elif missing_meta >= 2:
                    binding.quote_status = "FRESH_METADATA_UNREPORTED"
                elif yahoo_currency_unreported:
                    binding.quote_status = "FRESH_CURRENCY_UNREPORTED"
                elif yahoo_type_unreported:
                    binding.quote_status = "FRESH_TYPE_UNREPORTED"
                elif yahoo_venue_unreported:
                    binding.quote_status = "FRESH_VENUE_UNREPORTED"

                verified.append(binding)
                yahoo_failure_rescued_ids.add(r.tv_id)
                self.stats["yahoo_failure_regional_fallback_matches"] += 1
                self.stats[
                    f"yahoo_failure_regional_fallback_matches_{_telemetry_token(r.prefix)}"
                ] += 1
                self.stats[
                    f"yahoo_failure_regional_fallback_matches_{_telemetry_token(target_mic)}"
                ] += 1
                self.stats[
                    f"yahoo_failure_regional_fallback_matches_reason_{_telemetry_token(reason)}"
                ] += 1
                if len(eligible) > 1:
                    self.stats["yahoo_failure_regional_fallback_multi_mic_matches"] += 1

            if yahoo_failure_rescued_ids:
                rejected = [b for b in rejected if b.tv_id not in yahoo_failure_rescued_ids]

        final_rescued = self._germany_final_exact_isin_rescue(rows, rejected)
        if final_rescued:
            final_ids = {b.tv_id for b in final_rescued}
            verified.extend(final_rescued)
            rejected = [b for b in rejected if b.tv_id not in final_ids]

        home_rescued = self._exact_isin_yahoo_home_market_rescue(rows, rejected)
        if home_rescued:
            home_ids = {b.tv_id for b in home_rescued}
            verified.extend(home_rescued)
            rejected = [b for b in rejected if b.tv_id not in home_ids]

        self.stats["reviewed_yahoo_mutualfund_taxonomy_candidates"] += len(reviewed_mutualfund_candidate_ids)
        self.stats["reviewed_yahoo_mutualfund_taxonomy_matches"] += len(reviewed_mutualfund_match_ids)
        for tv_id in sorted(reviewed_mutualfund_candidate_ids - reviewed_mutualfund_match_ids):
            reason = reviewed_mutualfund_block_by_id.get(tv_id, "UNKNOWN")
            self.stats[f"reviewed_yahoo_mutualfund_block_{reason.lower()}"] += 1
            safe_id = tv_id.replace(":", "_").replace("/", "_")
            self.stats[f"reviewed_yahoo_mutualfund_block_{safe_id}_{reason.lower()}"] += 1
            observed = reviewed_mutualfund_venue_observation_by_id.get(tv_id)
            if observed is not None:
                exchange, full_name, market = observed
                for field, value in (
                    ("exchange", exchange),
                    ("full_exchange", full_name),
                    ("market", market),
                ):
                    token = _telemetry_token(value)
                    self.stats[f"reviewed_yahoo_mutualfund_venue_{safe_id}_{field}_{token}"] += 1
        return verified + rejected



    def _germany_final_exact_isin_rescue(
        self,
        rows: list[TvRow],
        rejected: list[Binding],
    ) -> list[Binding]:
        """Last bounded Germany rescue using exact-ISIN regional evidence.

        This pass exists for provider-shape gaps discovered by the full-universe
        audit, not as a generic relaxation.  It runs only for already-rejected
        German ``stock/common`` rows with an exact TradingView ISIN and only for
        the small set of rejection classes where extra exact-ISIN evidence can
        be decisive.

        OpenFIGI may return several ticker aliases for one exact ISIN + MIC.  A
        differing alias is a quote-routing ambiguity, not a security ambiguity,
        when every admissible alias has the same non-null shareClassFIGI.  Yahoo
        is therefore allowed to select the usable alias after identity has been
        fixed at the share-class level. Reviewed Unit/Stapled/Dutch-certificate
        forms and pure listed Closed-End Fund / Mutual Fund identities are accepted
        only here and only when Yahoo independently confirms a normal EQUITY/EUR
        German listing. Mixed/private-equity fund taxonomies remain fail-closed.
        """
        eligible_reasons = {
            "OPENFIGI_SOURCE_NO_MATCH",
            "OPENFIGI_TARGET_NO_MATCH",
            "YAHOO_NO_MATCH",
            "YAHOO_TYPE_MISMATCH:ETF",
            "YAHOO_TYPE_MISMATCH:MUTUALFUND",
        }
        eligible_prefixes = {
            "GETTEX", "LS", "LSX", "TRADEGATE",
            "FWB", "DUS", "HAM", "SWB", "MUN", "HAN",
        }
        rejected_by_id = {b.tv_id: b for b in rejected}
        candidate_rows = []
        for r in rows:
            b = rejected_by_id.get(r.tv_id)
            if b is None or b.rejection_reason not in eligible_reasons:
                continue
            kind = tv_type_kind(r)
            if r.prefix not in eligible_prefixes or not r.isin or kind not in {"STOCK", "PREFERRED"}:
                continue
            specs = {str(x).lower() for x in r.type_specs if x}
            if kind == "STOCK" and "common" not in specs:
                continue
            if kind == "PREFERRED" and "preferred" not in specs:
                continue
            candidate_rows.append(r)

        if not candidate_rows:
            return []

        self.stats["germany_final_exact_isin_rescue_rows"] += len(candidate_rows)

        source_mics_by_id: dict[str, tuple[str, ...]] = {}
        probe_keys: list[tuple[str, str]] = []
        seen_probe_keys: set[tuple[str, str]] = set()
        for r in candidate_rows:
            source_mics: list[str] = []
            direct = tv_prefix_mic(r.prefix, self.market)
            if direct:
                source_mics.append(direct)
            bridge = ISIN_SHARE_CLASS_BRIDGES.get(r.prefix)
            if bridge:
                source_mics.extend(str(x) for x in bridge.get("source_mics", ()))
            cross = CROSS_VENUE_BRIDGES.get(r.prefix)
            if cross:
                source_mics.extend(str(x) for x in cross.get("source_mics", ()))
            source_mics = list(dict.fromkeys(x for x in source_mics if x))
            source_mics_by_id[r.tv_id] = tuple(source_mics)
            for mic in [*source_mics, *GERMANY_REGIONAL_TARGET_MICS]:
                key = ((r.isin or "").upper().strip(), mic)
                if key in seen_probe_keys:
                    continue
                seen_probe_keys.add(key)
                probe_keys.append(key)

        jobs = [
            {"idType": "ID_ISIN", "idValue": isin, "micCode": mic}
            for isin, mic in probe_keys
        ]
        try:
            mapped = self.openfigi.map_jobs(jobs) if jobs else []
            self.stats["openfigi_jobs"] += len(jobs)
            self.stats["openfigi_germany_final_rescue_jobs"] += len(jobs)
            self.stats["openfigi_http_batches"] += (
                (len(jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                if jobs else 0
            )
        except ProviderError:
            mapped = [[] for _ in jobs]
            self.stats["openfigi_germany_final_rescue_unavailable"] += len(jobs)

        raw_by_key: dict[tuple[str, str], list[OpenFigiIdentity]] = {
            key: identities for key, identities in zip(probe_keys, mapped)
        }

        def identity_allowed(r: TvRow, x: OpenFigiIdentity) -> tuple[bool, str | None]:
            if openfigi_type_compatible(r, x):
                return True, None
            if germany_exact_isin_stock_type_compatible(r, x):
                return True, "EQUITY_LIKE"
            if germany_exact_isin_share_subtype_compatible(r, x):
                return True, "SHARE_SUBTYPE"
            if germany_exact_isin_listed_fund_compatible(r, x):
                return True, "LISTED_FUND"
            return False, None

        # Stage every regional alias that has exact ISIN + non-null share class.
        staged_by_row: dict[str, list[tuple[str, str, OpenFigiIdentity, str | None]]] = defaultdict(list)
        symbols: list[str] = []
        for r in candidate_rows:
            isin_key = (r.isin or "").upper().strip()
            for mic in GERMANY_REGIONAL_TARGET_MICS:
                identities = raw_by_key.get((isin_key, mic), ())
                for x in identities:
                    allowed, reviewed_kind = identity_allowed(r, x)
                    if not allowed or not x.share_class_figi or not x.ticker:
                        continue
                    symbol = yahoo_listing_symbol(x.ticker, mic, r.prefix, tv_type_kind(r))
                    staged_by_row[r.tv_id].append((mic, symbol, x, reviewed_kind))
                    symbols.append(symbol)
                    if reviewed_kind == "EQUITY_LIKE":
                        self.stats["openfigi_germany_final_rescue_taxonomy_candidates"] += 1
                    elif reviewed_kind == "SHARE_SUBTYPE":
                        self.stats["openfigi_germany_final_rescue_share_subtype_candidates"] += 1
                    elif reviewed_kind == "LISTED_FUND":
                        self.stats["openfigi_germany_final_rescue_listed_fund_candidates"] += 1

        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
            if symbols:
                batch_size = max(1, int(getattr(self.yahoo, "batch_size", 75)))
                self.stats["yahoo_germany_final_rescue_candidates"] += len(symbols)
                self.stats["yahoo_germany_final_rescue_batches"] += (
                    len(dict.fromkeys(symbols)) + batch_size - 1
                ) // batch_size
        except ProviderError:
            quotes = {}
            self.stats["yahoo_germany_final_rescue_unavailable"] += len(symbols)

        priority = {mic: i for i, mic in enumerate(GERMANY_REGIONAL_TARGET_MICS)}
        rescued: list[Binding] = []
        for r in candidate_rows:
            target_valid: list[tuple[str, str, OpenFigiIdentity, YahooQuote, str | None, bool]] = []
            for mic, symbol, x, reviewed_kind in staged_by_row.get(r.tv_id, ()):
                q = quotes.get(symbol)
                regular_ok = _non_us_quote_compatible(r, mic, symbol, q, False)
                yahoo_taxonomy_ok = _germany_regional_yahoo_fund_taxonomy_anomaly_compatible(
                    r, mic, symbol, q, x, "GERMANY_FINAL_EXACT_ISIN_RESCUE"
                )
                equity_like_yahoo_etf_ok = (
                    reviewed_kind == "EQUITY_LIKE"
                    and _germany_final_equity_like_yahoo_etf_taxonomy_compatible(
                        r, mic, symbol, q, x
                    )
                )
                if (reviewed_kind == "EQUITY_LIKE" and q is not None
                        and (q.quote_type or "").upper() == "ETF"):
                    self.stats["germany_final_exact_isin_rescue_yahoo_etf_taxonomy_candidates"] += 1
                # Reviewed OpenFIGI taxonomy normally requires Yahoo's ordinary
                # EQUITY contract.  The only stacked exception is the exact-ISIN
                # equity-like + explicit EUR/German-venue + Yahoo ETF anomaly
                # above; MUTUALFUND/YHD/missing metadata remain fail-closed.
                if reviewed_kind and not (regular_ok or equity_like_yahoo_etf_ok):
                    continue
                if regular_ok or yahoo_taxonomy_ok or equity_like_yahoo_etf_ok:
                    target_valid.append((
                        mic, symbol, x, q, reviewed_kind,
                        yahoo_taxonomy_ok and not regular_ok,
                        equity_like_yahoo_etf_ok and not regular_ok,
                    ))

            if not target_valid:
                self.stats["germany_final_exact_isin_rescue_no_yahoo_target"] += 1
                continue

            target_shares = {x.share_class_figi for _, _, x, _, _, _, _ in target_valid if x.share_class_figi}
            if len(target_shares) != 1:
                self.stats["germany_final_exact_isin_rescue_target_share_ambiguous"] += 1
                continue
            share = next(iter(target_shares))

            # Listed-fund rescue is intentionally limited to a pure reviewed
            # Closed-End Fund / Mutual Fund taxonomy for this exact share class.
            # If OpenFIGI also labels the same ISIN/share class as another fund
            # family (for example Pvt Eqty Fund), keep the row fail-closed.
            if any(reviewed_kind == "LISTED_FUND" for _, _, _, _, reviewed_kind, _, _ in target_valid):
                conflicting_fund_taxonomy = False
                rescue_isin = (r.isin or "").upper().strip()
                for mic in [*source_mics_by_id.get(r.tv_id, ()), *GERMANY_REGIONAL_TARGET_MICS]:
                    for x in raw_by_key.get((rescue_isin, mic), ()):
                        if x.share_class_figi != share:
                            continue
                        t2 = (x.security_type2 or "").strip().lower()
                        if t2 == "mutual fund" and not germany_exact_isin_listed_fund_compatible(r, x):
                            conflicting_fund_taxonomy = True
                            break
                    if conflicting_fund_taxonomy:
                        break
                if conflicting_fund_taxonomy:
                    self.stats["germany_final_exact_isin_rescue_listed_fund_taxonomy_conflict"] += 1
                    continue

            # If exact-ISIN source evidence exists, it must corroborate the same
            # single share class.  Absence is allowed by the existing one-sided
            # German exact-ISIN contract; conflicting evidence is not.
            isin_key = (r.isin or "").upper().strip()
            source_entries: list[tuple[str, OpenFigiIdentity, str | None]] = []
            for mic in source_mics_by_id.get(r.tv_id, ()):
                for x in raw_by_key.get((isin_key, mic), ()):
                    allowed, reviewed_kind = identity_allowed(r, x)
                    if allowed and x.share_class_figi:
                        source_entries.append((mic, x, reviewed_kind))
            source_shares = {x.share_class_figi for _, x, _ in source_entries if x.share_class_figi}
            if len(source_shares) > 1 or (source_shares and source_shares != {share}):
                self.stats["germany_final_exact_isin_rescue_source_share_conflict"] += 1
                continue

            # Different OpenFIGI ticker aliases under one exact ISIN/MIC and the
            # same shareClassFIGI are quote aliases, not distinct identities.
            # Choose deterministically only after Yahoo has validated them.
            chosen = min(
                target_valid,
                key=lambda t: (
                    priority.get(t[0], len(priority)),
                    t[1],
                    punctuation_key(t[2].ticker or ""),
                ),
            )
            target_mic, yahoo_symbol, target_of, q, reviewed_kind, yahoo_taxonomy, equity_like_yahoo_etf = chosen

            matching_source = [entry for entry in source_entries if entry[1].share_class_figi == share]
            source_mics = source_mics_by_id.get(r.tv_id, ())
            source_mic: str | None = None
            source_venue_code: str | None = None
            if len(matching_source) == 1:
                source_mic, source_of, _ = matching_source[0]
            else:
                if matching_source:
                    source_mic_set = {mic for mic, _, _ in matching_source}
                    source_mic = next(iter(source_mic_set)) if len(source_mic_set) == 1 else None
                elif len(source_mics) == 1:
                    source_mic = source_mics[0]
                if source_mic is None:
                    source_venue_code = r.prefix
                source_of = OpenFigiIdentity(
                    figi=None,
                    composite_figi=None,
                    share_class_figi=share,
                    ticker=r.symbol,
                    name=r.name or target_of.name,
                    security_type=target_of.security_type,
                    security_type2=target_of.security_type2,
                    exch_code=None,
                )

            method = "GERMANY_FINAL_EXACT_ISIN_RESCUE"
            if reviewed_kind:
                method += f"_{reviewed_kind}"
            if yahoo_taxonomy:
                method += "_YAHOO_TAXONOMY"
            if equity_like_yahoo_etf:
                method += "_YAHOO_ETF_TAXONOMY"

            binding = self._verified(
                r,
                None,
                target_of,
                q,
                target_mic,
                source_mic=source_mic,
                target_mic=target_mic,
                source_venue_code=source_venue_code,
                mapping_method=method,
                source_of=source_of,
                target_of=target_of,
            )
            rescued.append(binding)
            self.stats["germany_final_exact_isin_rescue_matches"] += 1
            self.stats[f"germany_final_exact_isin_rescue_matches_{_telemetry_token(r.prefix)}"] += 1
            self.stats[f"germany_final_exact_isin_rescue_matches_{_telemetry_token(target_mic)}"] += 1
            if reviewed_kind == "EQUITY_LIKE":
                self.stats["germany_final_exact_isin_rescue_taxonomy_matches"] += 1
            elif reviewed_kind == "SHARE_SUBTYPE":
                self.stats["germany_final_exact_isin_rescue_share_subtype_matches"] += 1
            elif reviewed_kind == "LISTED_FUND":
                self.stats["germany_final_exact_isin_rescue_listed_fund_matches"] += 1
            if yahoo_taxonomy:
                self.stats["germany_final_exact_isin_rescue_yahoo_taxonomy_matches"] += 1
            if equity_like_yahoo_etf:
                self.stats["germany_final_exact_isin_rescue_yahoo_etf_taxonomy_matches"] += 1

        return rescued


    def _exact_isin_yahoo_home_market_rescue(
        self,
        rows: list[TvRow],
        rejected: list[Binding],
    ) -> list[Binding]:
        """Resolve an eligible rejected source row to Yahoo's home-market listing.

        This path deliberately changes quote routing, not security identity.
        TradingView's exact ISIN is resolved unscoped at OpenFIGI; admission
        requires exactly one observed non-null shareClassFIGI across compatible identities; rows where OpenFIGI omits that field are non-evidence rather than contradictions.
        Yahoo is queried with that exact ISIN only.  A search candidate must be
        an EQUITY. Its route must either occur directly in the unscoped exact-ISIN
        evidence, or be independently re-proven by exact ID_ISIN + reviewed home
        MIC with the same shareClassFIGI. ID_EXCH_SYMBOL + home MIC is retained only
        as a secondary fallback when the targeted ISIN mapping is absent.
        Quote/chart metadata must explicitly report the same Yahoo exchange plus
        a currency and EQUITY type.  The source-listing currency is intentionally not compared with the home-market
        quote currency: this path changes quote routing, not security identity.

        Multiple simultaneously-valid Yahoo symbols remain fail-closed because
        choosing a preferred home listing would otherwise require a new routing
        policy beyond the identity evidence available here.
        """
        eligible_reasons = {
            "OPENFIGI_SOURCE_NO_MATCH",
            "OPENFIGI_TARGET_NO_MATCH",
            "YAHOO_NO_MATCH",
            "YAHOO_TYPE_MISMATCH:MUTUALFUND",
            "YAHOO_SUFFIX_UNKNOWN:XBRN",
            "YAHOO_CURRENCY_UNREPORTED_TARGET_ONLY",
        }
        eligible_prefixes = {
            "XETR", "FWB", "DUS", "HAM", "SWB", "MUN", "HAN",
            "GETTEX", "LS", "LSX", "TRADEGATE", "BX", "SIX",
        }
        rejected_by_id = {b.tv_id: b for b in rejected}
        candidate_rows: list[TvRow] = []
        for r in rows:
            b = rejected_by_id.get(r.tv_id)
            if b is None or b.rejection_reason not in eligible_reasons:
                continue
            kind = tv_type_kind(r)
            specs = {str(x).lower() for x in r.type_specs if x}
            if r.prefix not in eligible_prefixes or not r.isin:
                continue
            # Exact-ISIN/share-class proof is security-level evidence, so the
            # generic home-route fallback can also cover preferred shares and
            # depositary receipts.  Taxonomy still has to be compatible in
            # OpenFIGI and Yahoo must explicitly return EQUITY.
            if kind == "STOCK" and "common" not in specs:
                continue
            if kind == "PREFERRED" and "preferred" not in specs:
                continue
            if kind not in {"STOCK", "PREFERRED", "ADR"}:
                continue
            candidate_rows.append(r)
        if not candidate_rows:
            return []

        self.stats["yahoo_home_market_rescue_rows"] += len(candidate_rows)

        # v0.3.52-style security grouping: one unscoped OpenFIGI request per ISIN.
        rows_by_isin: dict[str, list[TvRow]] = defaultdict(list)
        isin_order: list[str] = []
        for r in candidate_rows:
            isin = (r.isin or "").upper().strip()
            if isin not in rows_by_isin:
                isin_order.append(isin)
            rows_by_isin[isin].append(r)
        jobs = [{"idType": "ID_ISIN", "idValue": isin} for isin in isin_order]
        try:
            mapped = self.openfigi.map_jobs(jobs) if jobs else []
            self.stats["openfigi_jobs"] += len(jobs)
            self.stats["openfigi_home_market_unscoped_jobs"] += len(jobs)
            self.stats["openfigi_home_market_grouping_saved_jobs"] += len(candidate_rows) - len(jobs)
            self.stats["openfigi_http_batches"] += (
                (len(jobs) + self.openfigi.batch_size - 1) // self.openfigi.batch_size
                if jobs else 0
            )
        except ProviderError:
            mapped = [[] for _ in jobs]
            self.stats["openfigi_home_market_unavailable"] += len(jobs)
        identities_by_isin = {isin: identities for isin, identities in zip(isin_order, mapped)}

        evidence_by_row: dict[str, tuple[str, list[OpenFigiIdentity]]] = {}
        searchable_isins: set[str] = set()
        for r in candidate_rows:
            isin = (r.isin or "").upper().strip()
            compatible = [x for x in identities_by_isin.get(isin, ()) if openfigi_type_compatible(r, x)]
            if not compatible:
                self.stats["openfigi_home_market_no_compatible_identity"] += 1
                continue
            # OpenFIGI often omits shareClassFIGI on some venue rows for the
            # same exact ISIN. Missing provider metadata is not contradictory
            # evidence: require exactly one *observed* non-null share class,
            # then later require the Yahoo ticker to match an OpenFIGI row that
            # explicitly carries that same shareClassFIGI. Rows with a missing
            # share class can therefore neither prove nor select a candidate.
            shares = {x.share_class_figi for x in compatible if x.share_class_figi}
            if not shares:
                self.stats["openfigi_home_market_share_class_missing"] += 1
                continue
            if len(shares) != 1:
                self.stats["openfigi_home_market_share_class_ambiguous"] += 1
                continue
            if any(not x.share_class_figi for x in compatible):
                self.stats["openfigi_home_market_partial_share_class_accepted"] += 1
            share = next(iter(shares))
            evidence_by_row[r.tv_id] = (share, compatible)
            searchable_isins.add(isin)

        if not searchable_isins:
            return []

        search_by_isin: dict[str, list[YahooSearchCandidate]] = {}
        search_fn = getattr(self.yahoo, "search_exact_isin", None)
        if not callable(search_fn):
            self.stats["yahoo_home_market_search_unsupported"] += len(searchable_isins)
            return []
        for isin in sorted(searchable_isins):
            try:
                search_by_isin[isin] = list(search_fn(isin))
                self.stats["yahoo_home_market_search_jobs"] += 1
                self.stats["yahoo_home_market_search_candidates"] += len(search_by_isin[isin])
            except ProviderError:
                search_by_isin[isin] = []
                self.stats["yahoo_home_market_search_unavailable"] += 1

        staged_by_row: dict[str, list[tuple[YahooSearchCandidate, OpenFigiIdentity]]] = defaultdict(list)
        symbols: list[str] = []
        # Candidates absent from the unscoped ID_ISIN ticker rows are first
        # confirmed at the *listing* layer using the strongest available
        # primitive: the same exact ISIN filtered to the reviewed Yahoo home
        # MIC.  The response must carry the independently established
        # shareClassFIGI.  This avoids requiring provider ticker syntax to be
        # identical across Yahoo and OpenFIGI.
        #
        # Only if OpenFIGI has no exact-ISIN+MIC row do we retain the v0.3.61
        # exchange-symbol confirmation as a secondary proof path.
        isin_mic_layout: list[tuple[TvRow, YahooSearchCandidate, str, str, str, int]] = []
        isin_mic_jobs: list[dict] = []
        isin_mic_job_index: dict[tuple[str, str], int] = {}
        for r in candidate_rows:
            evidence = evidence_by_row.get(r.tv_id)
            if evidence is None:
                continue
            share, compatible = evidence
            isin = (r.isin or "").upper().strip()
            for candidate in search_by_isin.get(isin, ()):
                if (candidate.quote_type or "").upper() != "EQUITY":
                    self.stats["yahoo_home_market_search_non_equity"] += 1
                    continue
                keys = _yahoo_symbol_identity_keys(candidate.symbol)
                matched = [
                    x for x in compatible
                    if x.share_class_figi == share
                    and x.ticker
                    and punctuation_key(x.ticker) in keys
                ]
                if matched:
                    staged_by_row[r.tv_id].append((candidate, matched[0]))
                    symbols.append(candidate.symbol)
                    continue

                home_mic = YAHOO_HOME_EXCHANGE_TO_MIC.get((candidate.exchange or "").upper())
                local_symbol = _home_market_local_symbol(candidate.symbol, home_mic)
                if not home_mic or not local_symbol:
                    self.stats["yahoo_home_market_search_ticker_unconfirmed"] += 1
                    continue
                key = (isin, home_mic)
                offset = isin_mic_job_index.get(key)
                if offset is None:
                    offset = len(isin_mic_jobs)
                    isin_mic_job_index[key] = offset
                    isin_mic_jobs.append({
                        "idType": "ID_ISIN",
                        "idValue": isin,
                        "micCode": home_mic,
                    })
                isin_mic_layout.append((r, candidate, share, home_mic, local_symbol, offset))

        isin_mic_mapped: list[list[OpenFigiIdentity]] = []
        if isin_mic_jobs:
            try:
                isin_mic_mapped = self.openfigi.map_jobs(isin_mic_jobs)
                self.stats["openfigi_jobs"] += len(isin_mic_jobs)
                self.stats["openfigi_home_market_isin_mic_confirmation_jobs"] += len(isin_mic_jobs)
                self.stats["openfigi_http_batches"] += (
                    len(isin_mic_jobs) + self.openfigi.batch_size - 1
                ) // self.openfigi.batch_size
            except ProviderError:
                isin_mic_mapped = [[] for _ in isin_mic_jobs]
                self.stats["openfigi_home_market_isin_mic_confirmation_unavailable"] += len(isin_mic_jobs)

        # Only candidates for which exact ISIN + home MIC did not return
        # contradictory share-class evidence are eligible for the older
        # exchange-symbol proof fallback.
        symbol_fallback_layout: list[tuple[TvRow, YahooSearchCandidate, str, str, str]] = []
        for r, candidate, share, home_mic, local_symbol, offset in isin_mic_layout:
            identities = isin_mic_mapped[offset] if offset < len(isin_mic_mapped) else []
            type_compatible = [x for x in identities if openfigi_type_compatible(r, x)]
            conflicting_shares = {
                x.share_class_figi for x in type_compatible
                if x.share_class_figi and x.share_class_figi != share
            }
            if conflicting_shares:
                self.stats["openfigi_home_market_isin_mic_confirmation_share_conflict"] += 1
                self.stats["yahoo_home_market_search_ticker_unconfirmed"] += 1
                continue
            confirmed = [
                x for x in type_compatible
                if x.share_class_figi == share
            ]
            if confirmed:
                staged_by_row[r.tv_id].append((candidate, confirmed[0]))
                symbols.append(candidate.symbol)
                self.stats["openfigi_home_market_isin_mic_confirmation_matches"] += 1
                self.stats[f"openfigi_home_market_isin_mic_confirmation_matches_{_telemetry_token(home_mic)}"] += 1
                continue
            self.stats["openfigi_home_market_isin_mic_confirmation_no_match"] += 1
            symbol_fallback_layout.append((r, candidate, share, home_mic, local_symbol))

        venue_proof_layout: list[tuple[TvRow, YahooSearchCandidate, str, str, str, int]] = []
        venue_proof_jobs: list[dict] = []
        venue_proof_job_index: dict[tuple[str, str], int] = {}
        for r, candidate, share, home_mic, local_symbol in symbol_fallback_layout:
            key = (home_mic, local_symbol)
            offset = venue_proof_job_index.get(key)
            if offset is None:
                offset = len(venue_proof_jobs)
                venue_proof_job_index[key] = offset
                venue_proof_jobs.append({
                    "idType": "ID_EXCH_SYMBOL",
                    "idValue": local_symbol,
                    "micCode": home_mic,
                })
            venue_proof_layout.append((r, candidate, share, home_mic, local_symbol, offset))

        venue_proof_mapped: list[list[OpenFigiIdentity]] = []
        if venue_proof_jobs:
            try:
                venue_proof_mapped = self.openfigi.map_jobs(venue_proof_jobs)
                self.stats["openfigi_jobs"] += len(venue_proof_jobs)
                self.stats["openfigi_home_market_symbol_confirmation_jobs"] += len(venue_proof_jobs)
                self.stats["openfigi_http_batches"] += (
                    len(venue_proof_jobs) + self.openfigi.batch_size - 1
                ) // self.openfigi.batch_size
            except ProviderError:
                venue_proof_mapped = [[] for _ in venue_proof_jobs]
                self.stats["openfigi_home_market_symbol_confirmation_unavailable"] += len(venue_proof_jobs)

        for r, candidate, share, home_mic, local_symbol, offset in venue_proof_layout:
            identities = venue_proof_mapped[offset] if offset < len(venue_proof_mapped) else []
            compatible = [
                x for x in identities
                if openfigi_type_compatible(r, x)
                and x.share_class_figi == share
                and x.ticker
                and punctuation_key(x.ticker) == punctuation_key(local_symbol)
            ]
            conflicting_shares = {
                x.share_class_figi for x in identities
                if x.share_class_figi and x.share_class_figi != share
                and x.ticker and punctuation_key(x.ticker) == punctuation_key(local_symbol)
            }
            if conflicting_shares:
                self.stats["openfigi_home_market_symbol_confirmation_share_conflict"] += 1
                self.stats["yahoo_home_market_search_ticker_unconfirmed"] += 1
                continue
            if not compatible:
                self.stats["openfigi_home_market_symbol_confirmation_no_match"] += 1
                self.stats["yahoo_home_market_search_ticker_unconfirmed"] += 1
                continue
            staged_by_row[r.tv_id].append((candidate, compatible[0]))
            symbols.append(candidate.symbol)
            self.stats["openfigi_home_market_symbol_confirmation_matches"] += 1
            self.stats[f"openfigi_home_market_symbol_confirmation_matches_{_telemetry_token(home_mic)}"] += 1

        symbols = list(dict.fromkeys(symbols))
        try:
            quotes = self.yahoo.quotes(symbols) if symbols else {}
            if symbols:
                self.stats["yahoo_home_market_quote_candidates"] += len(symbols)
                batch_size = max(1, int(getattr(self.yahoo, "batch_size", 75)))
                self.stats["yahoo_home_market_quote_batches"] += (len(symbols) + batch_size - 1) // batch_size
        except ProviderError:
            quotes = {}
            self.stats["yahoo_home_market_quote_unavailable"] += len(symbols)

        chart_needed: list[str] = []
        candidate_by_symbol: dict[str, YahooSearchCandidate] = {}
        for records in staged_by_row.values():
            for candidate, _ in records:
                candidate_by_symbol.setdefault(candidate.symbol, candidate)
                q = quotes.get(candidate.symbol)
                # Explicit type/exchange contradictions are not overridable by
                # chart metadata. Chart is only a missing/incomplete-row fallback.
                contradiction = bool(
                    q is not None and (
                        (q.quote_type is not None and (q.quote_type or "").upper() != "EQUITY")
                        or (candidate.exchange and q.exchange
                            and candidate.exchange.upper() != q.exchange.upper())
                    )
                )
                if not contradiction and not _home_market_quote_compatible(candidate, q):
                    chart_needed.append(candidate.symbol)
        chart_quotes: dict[str, YahooQuote] = {}
        if chart_needed and hasattr(self.yahoo, "chart_quotes"):
            unique_chart = list(dict.fromkeys(chart_needed))
            chart_quotes = self.yahoo.chart_quotes(unique_chart)
            self.stats["yahoo_home_market_chart_jobs"] += len(unique_chart)
            self.stats["yahoo_home_market_chart_rows"] += len(chart_quotes)

        rescued: list[Binding] = []
        for r in candidate_rows:
            evidence = evidence_by_row.get(r.tv_id)
            if evidence is None:
                continue
            share, compatible = evidence
            valid: list[tuple[YahooSearchCandidate, OpenFigiIdentity, YahooQuote]] = []
            for candidate, identity in staged_by_row.get(r.tv_id, ()):
                q = quotes.get(candidate.symbol)
                explicit_contradiction = bool(
                    q is not None and (
                        (q.quote_type is not None and (q.quote_type or "").upper() != "EQUITY")
                        or (candidate.exchange and q.exchange
                            and candidate.exchange.upper() != q.exchange.upper())
                    )
                )
                if not _home_market_quote_compatible(candidate, q) and not explicit_contradiction:
                    cq = chart_quotes.get(candidate.symbol)
                    if _home_market_quote_compatible(candidate, cq):
                        q = cq
                        self.stats["yahoo_home_market_chart_matches"] += 1
                if _home_market_quote_compatible(candidate, q):
                    valid.append((candidate, identity, q))
            # Deduplicate repeated search rows but do not choose among distinct
            # simultaneously-valid Yahoo routes without an explicit preference rule.
            by_symbol = {candidate.symbol: (candidate, identity, q) for candidate, identity, q in valid}
            if not by_symbol:
                self.stats["yahoo_home_market_no_valid_quote"] += 1
                continue
            if len(by_symbol) != 1:
                self.stats["yahoo_home_market_route_ambiguous"] += 1
                continue
            candidate, matched_identity, q = next(iter(by_symbol.values()))

            security_of = OpenFigiIdentity(
                figi=None,
                composite_figi=None,
                share_class_figi=share,
                ticker=matched_identity.ticker,
                name=matched_identity.name or r.name,
                security_type=matched_identity.security_type,
                security_type2=matched_identity.security_type2,
                exch_code=None,
            )
            binding = self._verified(
                r,
                None,
                security_of,
                q,
                None,
                source_mic=None,
                target_mic=None,
                source_venue_code=r.prefix,
                mapping_method="YAHOO_EXACT_ISIN_HOME_MARKET",
                source_of=security_of,
                target_of=security_of,
            )
            rescued.append(binding)
            self.stats["yahoo_home_market_rescue_matches"] += 1
            self.stats[f"yahoo_home_market_rescue_matches_{_telemetry_token(r.prefix)}"] += 1
            self.stats[f"yahoo_home_market_rescue_exchange_{_telemetry_token(q.exchange)}"] += 1
            self.stats[f"yahoo_home_market_rescue_currency_{_telemetry_token(q.currency)}"] += 1

        return rescued


    def refresh_cached_quotes(self, bindings: dict[str, Binding]) -> None:
        """Refresh current Yahoo quote data for cached VERIFIED bindings only.

        Identity stays persistent; price is runtime data and is never trusted from
        an old cache entry. A metadata contradiction invalidates the binding.
        Provider unavailability leaves identity VERIFIED but quote_status=UNAVAILABLE.
        """
        targets = sorted({
            b.yahoo_symbol for b in bindings.values()
            if b.status == "VERIFIED" and b.cache_hit and b.yahoo_symbol
        })
        if not targets:
            return
        try:
            quotes = self.yahoo.quotes(targets)
            self.stats["yahoo_quote_refresh_batches"] += (len(targets) + self.yahoo.batch_size - 1) // self.yahoo.batch_size
        except ProviderError:
            for b in bindings.values():
                if b.status == "VERIFIED" and b.cache_hit:
                    b.quote_status = "UNAVAILABLE"
                    b.yahoo_price = None
            return

        rows_by_id = {b.tv_id: b for b in bindings.values()}
        chart_needed: set[str] = set()
        for b in rows_by_id.values():
            if b.status != "VERIFIED" or not b.cache_hit or not b.yahoo_symbol or b.finnhub_symbol is not None:
                continue
            q0 = quotes.get(b.yahoo_symbol)
            if b.mapping_method == "YAHOO_EXACT_ISIN_HOME_MARKET":
                if not _cached_home_market_quote_compatible(b, q0):
                    # A changed explicit exchange/currency/type is a runtime
                    # contradiction, not a chart-fallback case.
                    contradiction = bool(q0 is not None and (
                        (q0.quote_type is not None and (q0.quote_type or "").upper() != "EQUITY")
                        or (q0.exchange and b.yahoo_exchange
                            and q0.exchange.upper() != b.yahoo_exchange.upper())
                        or (q0.currency and b.yahoo_currency
                            and q0.currency.upper() != b.yahoo_currency.upper())
                    ))
                    if not contradiction:
                        chart_needed.add(b.yahoo_symbol)
            elif not _cached_non_us_quote_compatible(b, q0):
                chart_needed.add(b.yahoo_symbol)
        chart_quotes: dict[str, YahooQuote] = {}
        if chart_needed and hasattr(self.yahoo, "chart_quotes"):
            chart_quotes = self.yahoo.chart_quotes(sorted(chart_needed))
            self.stats["yahoo_chart_refresh_jobs"] += len(chart_needed)
            self.stats["yahoo_chart_refresh_rows"] += len(chart_quotes)

        invalidated: list[Binding] = []
        for b in rows_by_id.values():
            if b.status != "VERIFIED" or not b.cache_hit or not b.yahoo_symbol:
                continue
            q = quotes.get(b.yahoo_symbol)
            if b.finnhub_symbol is None:
                cq = chart_quotes.get(b.yahoo_symbol)
                if b.mapping_method == "YAHOO_EXACT_ISIN_HOME_MARKET":
                    if not _cached_home_market_quote_compatible(b, q) and _cached_home_market_quote_compatible(b, cq):
                        q = cq
                        self.stats["yahoo_chart_refresh_matches"] += 1
                elif not _cached_non_us_quote_compatible(b, q) and _cached_non_us_quote_compatible(b, cq):
                    q = cq
                    self.stats["yahoo_chart_refresh_matches"] += 1
            if q is None:
                b.quote_status = "UNAVAILABLE"
                b.yahoo_price = None
                continue
            if b.mapping_method == "YAHOO_EXACT_ISIN_HOME_MARKET":
                if not _cached_home_market_quote_compatible(b, q):
                    b.status = "REJECTED"
                    b.rejection_reason = f"YAHOO_RUNTIME_HOME_MARKET_MISMATCH:{q.exchange}/{q.currency}/{q.quote_type}"
                    b.quote_status = "MISMATCH"
                    b.yahoo_price = None
                    now = int(time.time())
                    b.validated_at = now
                    b.expires_at = now + self.rejected_ttl
                    b.cache_hit = False
                    invalidated.append(b)
                    continue
                b.yahoo_exchange = q.exchange
                b.yahoo_market = q.market
                b.yahoo_quote_type = q.quote_type
                b.yahoo_currency = q.currency
                b.yahoo_price = q.price
                b.yahoo_delayed_by = q.delayed_by
                b.quote_status = "UNAVAILABLE" if q.price is None else "FRESH"
                continue
            # Cached identity has no TvRow object, so validate against the exact
            # cached currency/type/MIC contract rather than re-running discovery.
            quote_type = (q.quote_type or "").upper()
            if q.quote_type is None and b.finnhub_symbol is None:
                type_ok = True
            elif (
                b.finnhub_symbol is None
                and b.yahoo_quote_type
                and quote_type == (b.yahoo_quote_type or "").upper()
            ):
                # Preserve the exact Yahoo type admitted during full non-US
                # discovery.  This includes the bounded LSIN DR/MUTUALFUND
                # taxonomy anomaly, whose stronger OpenFIGI proof was checked
                # before the binding entered the cache.
                type_ok = True
            else:
                type_ok = ((b.tv_type or "").lower() == "fund" and quote_type in {"ETF", "MUTUALFUND"}) or \
                          ((b.tv_type or "").lower() != "fund" and quote_type == "EQUITY")
            yahoo_venue_unreported = q.exchange is None and q.full_exchange_name is None
            target_only = _strict_yahoo_mapping(b.mapping_method)
            venue_ok = yahoo_venue_compatible(b.resolved_mic, q)
            if target_only:
                type_ok = q.quote_type is not None and type_ok
                currency_ok_pre = q.currency is not None and currency_compatible(b.tv_currency, q.currency)
                venue_ok = (not yahoo_venue_unreported) and venue_ok
            else:
                currency_ok_pre = None
            if (not venue_ok and b.finnhub_symbol is None and not target_only
                    and _cached_reviewed_yahoo_mutualfund_yhd_compatible(b, q)):
                venue_ok = True
            if yahoo_venue_unreported and b.finnhub_symbol is None and not target_only:
                # Mirror cold-path admission for cached non-US identities:
                # OpenFIGI already proved the listing. Yahoo may omit all venue
                # metadata, but must still return the exact cached symbol and a
                # quote value; if market is present it must be compatible.
                venue_ok = (
                    q.symbol == b.yahoo_symbol
                    and (q.market is None or yahoo_market_compatible(b.resolved_mic, q.market))
                )
            # A cached non-US binding may have been admitted when Yahoo did
            # not publish currency, because OpenFIGI had already proven the
            # currency-constrained listing. US/Finnhub bindings still require
            # Yahoo currency to be present and equal.
            currency_ok = (
                currency_ok_pre
                if target_only
                else (currency_compatible(b.tv_currency, q.currency)
                      if q.currency is not None
                      else b.finnhub_symbol is None)
            )
            if not (type_ok and venue_ok and currency_ok):
                b.status = "REJECTED"
                b.rejection_reason = f"YAHOO_RUNTIME_MISMATCH:{q.exchange}/{q.currency}/{q.quote_type}"
                b.quote_status = "MISMATCH"
                b.yahoo_price = None
                now = int(time.time())
                b.validated_at = now
                b.expires_at = now + self.rejected_ttl
                b.cache_hit = False
                invalidated.append(b)
                continue
            b.yahoo_exchange = q.exchange
            b.yahoo_market = q.market
            b.yahoo_quote_type = q.quote_type
            b.yahoo_currency = q.currency
            b.yahoo_price = q.price
            b.yahoo_delayed_by = q.delayed_by
            missing_meta = sum((q.currency is None, q.quote_type is None, yahoo_venue_unreported))
            if q.price is None:
                b.quote_status = "UNAVAILABLE"
            elif missing_meta >= 2:
                b.quote_status = "FRESH_METADATA_UNREPORTED"
            elif q.currency is None:
                b.quote_status = "FRESH_CURRENCY_UNREPORTED"
            elif q.quote_type is None:
                b.quote_status = "FRESH_TYPE_UNREPORTED"
            elif yahoo_venue_unreported:
                b.quote_status = "FRESH_VENUE_UNREPORTED"
            else:
                b.quote_status = "FRESH"
        if invalidated:
            self.cache.put_bindings(invalidated)

    def _verified(
        self,
        r: TvRow,
        fh: FinnhubIdentity | None,
        of: OpenFigiIdentity | None,
        y: YahooQuote | None,
        mic: str | None,
        source_mic: str | None = None,
        target_mic: str | None = None,
        source_venue_code: str | None = None,
        mapping_method: str = "SAME_VENUE",
        source_of: OpenFigiIdentity | None = None,
        target_of: OpenFigiIdentity | None = None,
    ) -> Binding:
        now = int(time.time())
        if source_mic is None and source_venue_code is None:
            source_mic = mic
        target_mic = target_mic or mic
        source_of = source_of or of
        target_of = target_of or of
        payload = {
            "tv_id": r.tv_id,
            "currency": r.currency,
            "type": tv_type_kind(r),
            "mic": mic,
            "source_mic": source_mic,
            "target_mic": target_mic,
            "source_venue_code": source_venue_code,
            "mapping_method": mapping_method,
            "finnhub_symbol": fh.symbol if fh else None,
            "composite_figi": (fh.composite_figi if fh else of.composite_figi if of else None),
            "share_class_figi": (fh.share_class_figi if fh else of.share_class_figi if of else None),
            "venue_figi": source_of.figi if source_of else None,
            "source_venue_figi": source_of.figi if source_of else None,
            "target_venue_figi": target_of.figi if target_of else None,
            "yahoo_symbol": y.symbol if y else None,
            "yahoo_exchange": y.exchange if y else None,
            "yahoo_market": y.market if y else None,
            "yahoo_currency": y.currency if y else None,
            "policy": RESOLVER_VERSION,
        }
        fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return Binding(
            tv_id=r.tv_id,
            tv_symbol=r.symbol,
            tv_prefix=r.prefix,
            tv_currency=r.currency,
            tv_type=r.tv_type,
            status="VERIFIED",
            yahoo_symbol=y.symbol if y else None,
            yahoo_exchange=y.exchange if y else None,
            yahoo_market=y.market if y else None,
            yahoo_quote_type=y.quote_type if y else None,
            yahoo_currency=y.currency if y else None,
            yahoo_price=y.price if y else None,
            yahoo_delayed_by=y.delayed_by if y else None,
            quote_status="FRESH",
            resolved_mic=target_mic,
            source_mic=source_mic,
            target_mic=target_mic,
            source_venue_code=source_venue_code,
            mapping_method=mapping_method,
            source_venue_figi=source_of.figi if source_of else None,
            target_venue_figi=target_of.figi if target_of else None,
            finnhub_symbol=fh.symbol if fh else None,
            finnhub_type=fh.security_type if fh else None,
            composite_figi=fh.composite_figi if fh else of.composite_figi if of else None,
            share_class_figi=fh.share_class_figi if fh else of.share_class_figi if of else None,
            venue_figi=source_of.figi if source_of else None,
            fingerprint=fingerprint,
            resolver_version=RESOLVER_VERSION,
            validated_at=now,
            expires_at=now + self.verified_ttl,
        )

    def _reject(self, r: TvRow, reason: str) -> Binding:
        now = int(time.time())
        return Binding(
            tv_id=r.tv_id,
            tv_symbol=r.symbol,
            tv_prefix=r.prefix,
            tv_currency=r.currency,
            tv_type=r.tv_type,
            status="REJECTED",
            rejection_reason=reason,
            resolver_version=RESOLVER_VERSION,
            validated_at=now,
            expires_at=now + self.rejected_ttl,
        )
