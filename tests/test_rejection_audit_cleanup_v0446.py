from version_expectations import CURRENT_RESOLVER_VERSION
import inspect
from tv_market_identity import cli
from tv_market_identity.policy import RESOLVER_VERSION


def test_v0446_removes_experimental_bridge_diagnostics_without_policy_change():
    src = inspect.getsource(cli._write_rejection_audit)
    assert "us_same_ticker_unique_share_class_bridge" not in src
    assert "source_mic_proven_unique_share_class_bridge" not in src
    assert '"resolution_classification"' in src
    assert '"unscoped_openfigi"' in src
    assert '"home_market_search_candidates"' in src
    assert RESOLVER_VERSION == CURRENT_RESOLVER_VERSION
