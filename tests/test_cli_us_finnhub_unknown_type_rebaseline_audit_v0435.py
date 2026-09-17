from tv_market_identity.cli import parser
from tv_market_identity import __version__
from tv_market_identity.policy import RESOLVER_VERSION

def test_v0435_rebaseline_flag_and_versions():
    args = parser().parse_args(["run", "--us-finnhub-unknown-type-rebaseline-audit", "audit.jsonl"])
    assert args.us_finnhub_unknown_type_rebaseline_audit == "audit.jsonl"
    assert __version__ == "0.4.36"
    assert RESOLVER_VERSION == "0.4.34-policy434"
