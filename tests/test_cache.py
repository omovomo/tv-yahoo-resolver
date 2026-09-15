from tv_market_identity.cache import CacheDB
from tv_market_identity.models import Binding
from tv_market_identity.policy import RESOLVER_VERSION
import time


def test_binding_cache_roundtrip(tmp_path):
    db = CacheDB(tmp_path / "cache.sqlite")
    now = int(time.time())
    b = Binding(
        tv_id="NYSE:BRK.B", tv_symbol="BRK.B", tv_prefix="NYSE", tv_currency="USD", tv_type="stock",
        status="VERIFIED", yahoo_symbol="BRK-B", resolver_version=RESOLVER_VERSION,
        validated_at=now, expires_at=now + 1000,
    )
    db.put_bindings([b])
    got = db.get_bindings([b.tv_id], RESOLVER_VERSION, {b.tv_id: ("USD", "stock")})
    assert got[b.tv_id].yahoo_symbol == "BRK-B"
    assert got[b.tv_id].cache_hit is True
    assert got[b.tv_id].quote_status == "STALE_CACHED"
    assert got[b.tv_id].yahoo_price is None
    db.close()
