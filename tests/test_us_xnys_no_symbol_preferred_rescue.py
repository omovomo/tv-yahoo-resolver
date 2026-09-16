from tv_market_identity.policy import RESOLVER_VERSION


def test_v048_policy_version():
    assert RESOLVER_VERSION == "0.4.26-policy426"


def test_v048_method_is_wired():
    from pathlib import Path
    text = (Path(__file__).parents[1] / "src" / "tv_market_identity" / "resolver.py").read_text(encoding="utf-8")
    assert "_us_xnys_finnhub_no_symbol_preferred_exact_isin_rescue(us, us_bindings)" in text
    assert 'mapping_method="US_XNYS_FINNHUB_NO_SYMBOL_PREFERRED_EXACT_ISIN"' in text
    assert 'b.rejection_reason != "FINNHUB_NO_SYMBOL"' in text
    assert 'r.prefix != "NYSE"' in text
    assert '"micCode": "XNYS"' in text
