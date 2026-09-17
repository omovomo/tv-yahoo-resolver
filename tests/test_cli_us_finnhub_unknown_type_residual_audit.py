from tv_market_identity.cli import parser

def test_parser_accepts_unknown_type_residual_audit():
    args = parser().parse_args(["run", "--us-finnhub-unknown-type-residual-audit", "audit.jsonl"])
    assert args.us_finnhub_unknown_type_residual_audit == "audit.jsonl"


def test_v428_unknown_type_audit_metadata_and_policy():
    from tv_market_identity import __version__
    from tv_market_identity.policy import RESOLVER_VERSION
    from pathlib import Path
    text = Path("src/tv_market_identity/cli.py").read_text(encoding="utf-8")
    assert __version__ == "0.4.34"
    assert RESOLVER_VERSION == "0.4.34-policy434"
    assert '"diagnostic_only": True, "diagnostic_release": "0.4.28"' in text
    assert '"v428_cohort_key"' in text
