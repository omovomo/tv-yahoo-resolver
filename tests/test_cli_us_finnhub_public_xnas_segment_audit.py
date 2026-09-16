from tv_market_identity.cli import parser

def test_public_xnas_segment_audit_parser():
    args = parser().parse_args(["run", "--us-finnhub-public-xnas-segment-audit", "out.jsonl"])
    assert args.us_finnhub_public_xnas_segment_audit == "out.jsonl"
