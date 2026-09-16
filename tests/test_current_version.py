from pathlib import Path

import tv_market_identity
from tv_market_identity.policy import RESOLVER_VERSION


def test_current_package_version():
    assert tv_market_identity.__version__ == "0.4.5"
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert 'version = "0.4.5"' in pyproject.read_text(encoding="utf-8")


def test_diagnostic_release_keeps_functional_policy():
    assert RESOLVER_VERSION == "0.3.99-policy99"
