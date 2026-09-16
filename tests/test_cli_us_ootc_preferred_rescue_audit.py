from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_v088_parser_exposes_rescue_provenance_audit():
    args = parser().parse_args(["run", "--us-ootc-preferred-empty-type-rescue-audit", "audit.jsonl"])
    assert args.us_ootc_preferred_empty_type_rescue_audit == "audit.jsonl"

    assert RESOLVER_VERSION == "0.4.21-policy421"
