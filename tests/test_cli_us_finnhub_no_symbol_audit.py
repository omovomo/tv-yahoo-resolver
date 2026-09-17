from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_no_symbol_audit_flag_is_available_without_policy_change():
    args = parser().parse_args([
        "run",
        "--us-finnhub-no-symbol-audit", "no-symbol.jsonl",
    ])
    assert args.us_finnhub_no_symbol_audit == "no-symbol.jsonl"
    assert RESOLVER_VERSION == "0.4.32-policy432"
