from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_v098_closed_end_fund_audit_flag_and_policy_unchanged():
    args = parser().parse_args(["run", "--us-finnhub-closed-end-fund-audit", "audit.jsonl"])
    assert args.us_finnhub_closed_end_fund_audit == "audit.jsonl"
    assert RESOLVER_VERSION == "0.4.22-policy422"

