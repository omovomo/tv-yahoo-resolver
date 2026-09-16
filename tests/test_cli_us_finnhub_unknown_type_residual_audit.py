from tv_market_identity.cli import parser

def test_parser_accepts_unknown_type_residual_audit():
    args = parser().parse_args(["run", "--us-finnhub-unknown-type-residual-audit", "audit.jsonl"])
    assert args.us_finnhub_unknown_type_residual_audit == "audit.jsonl"
