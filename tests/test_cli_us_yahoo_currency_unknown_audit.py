from tv_market_identity.cli import parser

def test_v093_currency_unknown_audit_flag():
    args = parser().parse_args(["run", "--us-yahoo-currency-unknown-audit", "audit.jsonl"])
    assert args.us_yahoo_currency_unknown_audit == "audit.jsonl"
