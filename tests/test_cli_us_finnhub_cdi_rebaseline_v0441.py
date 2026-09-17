from version_expectations import CURRENT_PACKAGE_VERSION, CURRENT_RESOLVER_VERSION
from tv_market_identity.cli import parser
from tv_market_identity import __version__
from tv_market_identity.policy import RESOLVER_VERSION


def test_v0441_cdi_rebaseline_flag_and_policy_unchanged():
    args = parser().parse_args(["run", "--us-finnhub-cdi-audit", "audit.jsonl"])
    assert args.us_finnhub_cdi_audit == "audit.jsonl"
    assert __version__ == CURRENT_PACKAGE_VERSION
    assert RESOLVER_VERSION == CURRENT_RESOLVER_VERSION
