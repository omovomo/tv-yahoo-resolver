from version_expectations import CURRENT_PACKAGE_VERSION, CURRENT_RESOLVER_VERSION
from pathlib import Path

import tv_market_identity
from tv_market_identity.policy import RESOLVER_VERSION


def test_current_package_version():
    assert tv_market_identity.__version__ == CURRENT_PACKAGE_VERSION
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert f'version = "{CURRENT_PACKAGE_VERSION}"' in pyproject.read_text(encoding="utf-8")


def test_current_functional_policy():
    assert RESOLVER_VERSION == CURRENT_RESOLVER_VERSION
