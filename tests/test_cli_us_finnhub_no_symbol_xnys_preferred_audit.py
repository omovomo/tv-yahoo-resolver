from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION

def test_no_symbol_xnys_preferred_audit_flag_without_policy_change():
    args = parser().parse_args(["run", "--us-finnhub-no-symbol-xnys-preferred-audit", "audit.jsonl"])
    assert args.us_finnhub_no_symbol_xnys_preferred_audit == "audit.jsonl"
    assert RESOLVER_VERSION == "0.4.23-policy423"
