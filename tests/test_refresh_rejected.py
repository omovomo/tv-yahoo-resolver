from tv_market_identity.cache import CacheDB
from tv_market_identity.models import OpenFigiIdentity, TvRow, YahooQuote
from tv_market_identity.resolver import BatchResolver
from pathlib import Path


class OFPreferred:
    batch_size = 100

    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job.get("idValue") == "VOW3" and job.get("micCode") == "XETR":
                out.append([
                    OpenFigiIdentity(
                        figi="FIGI_VOW3_XETR",
                        composite_figi="COMP_VOW3",
                        share_class_figi="SHARE_VOW3",
                        ticker="VOW3",
                        name="VOLKSWAGEN AG-PREF",
                        security_type="Preference",
                        security_type2="Preference",
                        exch_code="GY",
                    )
                ])
            else:
                out.append([])
        return out


class YPreferred:
    batch_size = 75

    def __init__(self, available: bool):
        self.available = available

    def quotes(self, symbols):
        if self.available and "VOW3.DE" in symbols:
            return {
                "VOW3.DE": YahooQuote(
                    "VOW3.DE", "GER", "XETRA", "EUR", "EQUITY",
                    "de_market", "VOLKSWAGEN AG", None, 90.0, 15,
                )
            }
        return {}


def test_refresh_rejected_reuses_verified_cache_policy_but_reresolves_reject(tmp_path):
    db = CacheDB(tmp_path / "refresh-rejected.sqlite")
    row = TvRow(
        "XETR:VOW3", "XETR", "VOW3", "Volkswagen AG", "EUR",
        "stock", ("preferred",), "Consumer Durables", 1e11, 90.0,
    )

    cold = BatchResolver(db, None, OFPreferred(), YPreferred(False))
    first = cold.resolve([row])[row.tv_id]
    assert first.status == "REJECTED"
    assert first.rejection_reason == "YAHOO_NO_MATCH"

    ordinary_warm = BatchResolver(db, None, OFPreferred(), YPreferred(True))
    cached = ordinary_warm.resolve([row])[row.tv_id]
    assert cached.status == "REJECTED"
    assert cached.cache_hit is True
    assert ordinary_warm.stats["cache_hits"] == 1
    assert ordinary_warm.stats["cache_misses"] == 0

    refreshed = BatchResolver(db, None, OFPreferred(), YPreferred(True))
    got = refreshed.resolve([row], refresh_rejected=True)[row.tv_id]
    assert got.status == "VERIFIED"
    assert got.cache_hit is False
    assert refreshed.stats["cache_rejected_refreshes"] == 1
    assert refreshed.stats["cache_hits"] == 0
    assert refreshed.stats["cache_misses"] == 1
    db.close()


def test_cli_source_declares_refresh_rejected_flag():
    cli_source = (Path(__file__).resolve().parents[1] / "src" / "tv_market_identity" / "cli.py").read_text(encoding="utf-8")
    assert '"--refresh-rejected"' in cli_source
    assert "refresh_rejected=args.refresh_rejected" in cli_source
