from version_expectations import CURRENT_RESOLVER_VERSION
from tv_market_identity.cli import parser
from tv_market_identity.policy import RESOLVER_VERSION


def test_v040_cdi_audit_flag_and_policy_unchanged():
    args = parser().parse_args(["run", "--us-finnhub-cdi-audit", "audit.jsonl"])
    assert args.us_finnhub_cdi_audit == "audit.jsonl"
    assert RESOLVER_VERSION == CURRENT_RESOLVER_VERSION

