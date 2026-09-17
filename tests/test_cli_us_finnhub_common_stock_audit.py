from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_common_stock_audit_flag_is_available_without_policy_change():
    args = parser().parse_args(["run", "--us-finnhub-common-stock-audit", "audit.jsonl"])
    assert args.us_finnhub_common_stock_audit == "audit.jsonl"
    assert RESOLVER_VERSION == "0.4.32-policy432"
