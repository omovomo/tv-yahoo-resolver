from version_expectations import CURRENT_RESOLVER_VERSION
from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_v042_preference_audit_flag_and_policy_unchanged():
    args = parser().parse_args(["run", "--us-finnhub-preference-audit", "audit.jsonl"])
    assert args.us_finnhub_preference_audit == "audit.jsonl"
    assert RESOLVER_VERSION == CURRENT_RESOLVER_VERSION
