from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_nvdr_and_sdr_audit_flags_are_available_without_policy_change():
    args = parser().parse_args([
        "run",
        "--us-finnhub-nvdr-audit", "nvdr.jsonl",
        "--us-finnhub-sdr-audit", "sdr.jsonl",
    ])
    assert args.us_finnhub_nvdr_audit == "nvdr.jsonl"
    assert args.us_finnhub_sdr_audit == "sdr.jsonl"
    assert RESOLVER_VERSION == "0.4.22-policy422"
