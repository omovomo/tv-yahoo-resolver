from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_gdr_audit_flag_is_available_without_policy_change():
    args = parser().parse_args(["run", "--us-finnhub-gdr-audit", "audit.jsonl"])
    assert args.us_finnhub_gdr_audit == "audit.jsonl"
    assert RESOLVER_VERSION == "0.4.23-policy423"
