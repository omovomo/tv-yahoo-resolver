from tv_market_identity.cli import parser


def test_v091_parser_accepts_unit_residual_audit():
    args = parser().parse_args(["run", "--us-finnhub-unit-residual-audit", "audit.jsonl"])
    assert args.us_finnhub_unit_residual_audit == "audit.jsonl"
