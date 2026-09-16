from tv_market_identity.cli import parser


def test_parser_accepts_v087_slmnp_admission_audit():
    args = parser().parse_args(["run", "--us-v087-slmnp-admission-audit", "audit.jsonl"])
    assert args.us_v087_slmnp_admission_audit == "audit.jsonl"
