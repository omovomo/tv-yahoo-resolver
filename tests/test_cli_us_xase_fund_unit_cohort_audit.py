from tv_market_identity.cli import parser


def test_v092_parser_accepts_xase_fund_unit_cohort_audit():
    args = parser().parse_args(["run", "--us-xase-fund-unit-cohort-audit", "audit.jsonl"])
    assert args.us_xase_fund_unit_cohort_audit == "audit.jsonl"
