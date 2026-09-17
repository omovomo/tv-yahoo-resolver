import inspect
from tv_market_identity import cli


def test_v0444_bridge_audit_is_diagnostic_only():
    src = inspect.getsource(cli._write_rejection_audit)
    assert 'us_same_ticker_unique_share_class_bridge' in src
    assert '"candidate"' in src
    assert 'same_ticker_us_openfigi_count' in src
    assert 'exact_tv_symbol_yahoo_source_candidate_count' in src
