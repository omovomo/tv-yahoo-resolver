from collections import defaultdict
from types import MethodType, SimpleNamespace

import pytest

from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
from tv_market_identity.resolver import BatchResolver


def row(prefix="OTC", tv_type="stock", specs=("common",), isin="US0000000001", symbol="ROYTL", currency="USD"):
    return TvRow(f"{prefix}:{symbol}", prefix, symbol, symbol, currency, tv_type, specs, None, None, None, isin)


def binding(r):
    return Binding(r.tv_id, r.symbol, r.prefix, r.currency, r.tv_type, "REJECTED",
                   finnhub_type="Royalty Trst", rejection_reason="FINNHUB_TYPE_MISMATCH:Royalty Trst")


def identity(figi="F1", share="SC1", st="Royalty Trst", st2="Common Stock"):
    return OpenFigiIdentity(figi, "C1", share, "IGNORED", "Trust", st, st2, "US")


def candidate(symbol="ROYTL", qt="EQUITY"):
    return YahooSearchCandidate(symbol, "PNK", qt, symbol, symbol)


def quote(symbol="ROYTL", exchange="PNK", currency="USD", qt="EQUITY"):
    return YahooQuote(symbol, exchange, "OTC Markets Pink", currency, qt, "us_market", symbol, symbol, 1.0, 0)


def resolver(ids=None, candidates=None, q=None):
    ids = [identity()] if ids is None else ids
    candidates = [candidate()] if candidates is None else candidates
    q = quote() if q is None else q
    class OF:
        def map_jobs(self, jobs):
            assert all(j.get("micCode") == "OOTC" for j in jobs)
            return [ids for _ in jobs]
    class Y:
        def search_exact_isin(self, isin): return candidates
        def quotes(self, symbols): return {q.symbol: q} if q else {}
    ns = SimpleNamespace(openfigi=OF(), yahoo=Y(), stats=defaultdict(int), verified_ttl=86400)
    ns._verified = MethodType(BatchResolver._verified, ns)
    return ns


def run(r=None, res=None):
    r = r or row(); res = res or resolver()
    return BatchResolver._us_ootc_stock_common_royalty_trust_rescue(res, [r], [binding(r)]), res


def test_ootc_stock_common_royalty_trust_exact_isin_rescues_audited_contract():
    out, res = run()
    assert out[0].status == "VERIFIED"
    assert out[0].mapping_method == "US_OOTC_STOCK_COMMON_FINNHUB_ROYALTY_TRST_EXACT_ISIN"
    assert out[0].source_mic == out[0].target_mic == "OOTC"
    assert res.stats["us_ootc_stock_common_royalty_trust_rescue_matches"] == 1


@pytest.mark.parametrize("r", [
    row(prefix="NYSE"), row(tv_type="fund"), row(specs=("preferred",)), row(isin=None),
])
def test_ootc_royalty_trust_rejects_wrong_venue_taxonomy_or_missing_isin(r):
    out, _ = run(r=r)
    assert out[0].status == "REJECTED"


@pytest.mark.parametrize("ids", [
    [],
    [identity("F1"), identity("F2")],
    [identity(st="PUBLIC")],
    [identity(st2="Preference")],
    [identity(share=None)],
])
def test_ootc_royalty_trust_requires_unique_scoped_taxonomy_and_shareclass(ids):
    out, _ = run(res=resolver(ids=ids))
    assert out[0].status == "REJECTED"


@pytest.mark.parametrize("candidates,q", [
    ([], quote()),
    ([candidate(), candidate("OTHER")], quote()),
    ([candidate("OTHER")], quote("OTHER")),
    ([candidate(qt="MUTUALFUND")], quote()),
    ([candidate()], quote(exchange="NYQ")),
    ([candidate()], quote(currency="EUR")),
    ([candidate()], quote(currency=None)),
    ([candidate()], quote(qt="MUTUALFUND")),
])
def test_ootc_royalty_trust_requires_unique_exact_yahoo_ootc_usd_equity(candidates, q):
    out, _ = run(res=resolver(candidates=candidates, q=q))
    assert out[0].status == "REJECTED"


def test_policy419_reuses_policy415_verified_cache_only():
    from tv_market_identity.resolver import CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
    assert "0.4.15-policy415" in CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
