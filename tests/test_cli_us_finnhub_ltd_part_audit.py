from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_ltd_part_audit_flag_available_under_current_policy():
    args = parser().parse_args(["run", "--us-finnhub-ltd-part-audit", "audit.jsonl"])
    assert args.us_finnhub_ltd_part_audit == "audit.jsonl"
    assert RESOLVER_VERSION == "0.4.22-policy422"

