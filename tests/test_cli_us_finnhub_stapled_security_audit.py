from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_v041_stapled_security_audit_flag_and_policy_unchanged():
    args = parser().parse_args(["run", "--us-finnhub-stapled-security-audit", "audit.jsonl"])
    assert args.us_finnhub_stapled_security_audit == "audit.jsonl"
    assert RESOLVER_VERSION == "0.4.34-policy434"

