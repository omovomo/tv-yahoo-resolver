from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_cli_rejection_audit_parser_and_runtime(tmp_path):
    stub = tmp_path / "tradingview_screener.py"
    stub.write_text(
        "class Column:\n"
        "    def __init__(self, *a, **k): pass\n"
        "class Query:\n"
        "    def __init__(self, *a, **k): self.query = {}\n",
        encoding="utf-8",
    )
    audit_path = tmp_path / "audit.jsonl"
    code = r'''
import json
from types import SimpleNamespace
from tv_market_identity.cli import _write_rejection_audit, parser
from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote

args = parser().parse_args([
    "run", "--config", "config/identity_coverage_germany.ini",
    "--rejection-audit", AUDIT_PATH,
])
assert args.rejection_audit == AUDIT_PATH

class FakeOpenFigi:
    def map_jobs(self, jobs):
        out = []
        for job in jobs:
            if job["micCode"] == "XFRA":
                out.append([OpenFigiIdentity(
                    figi="BBG000TEST1", composite_figi="BBG000TESTC",
                    share_class_figi="BBG001TESTS", ticker="TEST",
                    name="TEST AG", security_type="Common Stock",
                    security_type2="Common Stock", exch_code="GR",
                )])
            else:
                out.append([])
        return out

class FakeYahoo:
    batch_size = 75
    def quotes(self, symbols):
        return {
            "TEST.F": YahooQuote(
                symbol="TEST.F", exchange="FRA", full_exchange_name="Frankfurt",
                currency="EUR", quote_type="EQUITY", market="de_market",
                short_name="Test AG", long_name="Test AG", price=10.0, delayed_by=0,
            )
        }

row = TvRow(
    tv_id="FWB:TEST", prefix="FWB", symbol="TEST", name="Test AG",
    currency="EUR", tv_type="stock", type_specs=("common",),
    sector=None, market_cap=None, close=None, isin="DE0000000001",
)
binding = Binding(
    tv_id=row.tv_id, tv_symbol=row.symbol, tv_prefix=row.prefix,
    tv_currency=row.currency, tv_type=row.tv_type, status="REJECTED",
    rejection_reason="YAHOO_NO_MATCH",
)
resolver = SimpleNamespace(openfigi=FakeOpenFigi(), yahoo=FakeYahoo())
_write_rejection_audit(__import__("pathlib").Path(AUDIT_PATH), [row], {row.tv_id: binding}, resolver)
record = json.loads(__import__("pathlib").Path(AUDIT_PATH).read_text(encoding="utf-8").strip())
assert record["tv_id"] == "FWB:TEST"
xf = next(x for x in record["evidence"] if x["mic"] == "XFRA")
assert xf["share_class_figi"] == "BBG001TESTS"
assert xf["yahoo_symbol"] == "TEST.F"
assert xf["yahoo_quote_type"] == "EQUITY"
assert xf["ordinary_contract_blocks"] == []
'''
    code = "AUDIT_PATH = " + repr(str(audit_path)) + "\n" + code
    env = os.environ.copy()
    root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(root / "src")])
    subprocess.run([sys.executable, "-c", code], check=True, env=env, cwd=root)
