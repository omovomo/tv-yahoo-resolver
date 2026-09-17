import inspect
from tv_market_identity import cli


def test_v0445_source_mic_bridge_is_strict_and_diagnostic_only():
    src = inspect.getsource(cli._write_rejection_audit)
    assert 'source_mic_proven_unique_share_class_bridge' in src
    assert 'EXACT_ISIN_OPENFIGI_MIC_SCOPED' in src
    assert 'e.get("mic") == strict_source_mic' in src
    assert 'c.get("home_mic") == strict_source_mic' in src
