from tv_market_identity import __version__
from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_ltd_part_audit_flag_available_under_current_policy():
    args = parser().parse_args(["run", "--us-finnhub-ltd-part-audit", "audit.jsonl"])
    assert args.us_finnhub_ltd_part_audit == "audit.jsonl"
    assert RESOLVER_VERSION == "0.3.99-policy99"


def test_current_package_version_after_ltd_part_audit_release():
    assert __version__ == "0.4.0"
