from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION
import tv_market_identity


def test_v088_parser_exposes_rescue_provenance_audit():
    args = parser().parse_args(["run", "--us-ootc-preferred-empty-type-rescue-audit", "audit.jsonl"])
    assert args.us_ootc_preferred_empty_type_rescue_audit == "audit.jsonl"


def test_current_versions():
    assert tv_market_identity.__version__ == "0.4.0"
    assert RESOLVER_VERSION == "0.3.99-policy99"
