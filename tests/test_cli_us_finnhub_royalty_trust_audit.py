from tv_market_identity.cli import parser

def test_v094_royalty_trust_audit_flag():
    args = parser().parse_args(["run", "--us-finnhub-royalty-trust-audit", "audit.jsonl"])
    assert args.us_finnhub_royalty_trust_audit == "audit.jsonl"
