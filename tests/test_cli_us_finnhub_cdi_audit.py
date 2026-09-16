from tv_market_identity import __version__
from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_v040_cdi_audit_flag_and_policy_unchanged():
    args = parser().parse_args(["run", "--us-finnhub-cdi-audit", "audit.jsonl"])
    assert args.us_finnhub_cdi_audit == "audit.jsonl"
    assert RESOLVER_VERSION == "0.3.99-policy99"


def test_v040_package_version_is_diagnostic_release():
    assert __version__ == "0.4.0"
