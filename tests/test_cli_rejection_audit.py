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
            if "micCode" not in job:
                out.append([
                    OpenFigiIdentity(
                        figi="BBG000HOME1", composite_figi="BBG000HOMEC",
                        share_class_figi="BBG001TESTS", ticker="HOME",
                        name="TEST AG", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="HOME",
                    ),
                    OpenFigiIdentity(
                        figi="BBG000TEST1", composite_figi="BBG000TESTC",
                        share_class_figi="BBG001TESTS", ticker="TEST",
                        name="TEST AG", security_type="Common Stock",
                        security_type2="Common Stock", exch_code="GR",
                    ),
                ])
            elif job["micCode"] == "XFRA":
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
assert record["unscoped_openfigi_status"] == "UNIQUE_SHARE_CLASS"
assert record["unscoped_share_class_figis"] == ["BBG001TESTS"]
assert {x["ticker"] for x in record["unscoped_openfigi"]} == {"HOME", "TEST"}
assert {x["exch_code"] for x in record["unscoped_openfigi"]} == {"HOME", "GR"}
'''
    code = "AUDIT_PATH = " + repr(str(audit_path)) + "\n" + code
    env = os.environ.copy()
    root = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = os.pathsep.join([str(tmp_path), str(root / "src")])
    subprocess.run([sys.executable, "-c", code], check=True, env=env, cwd=root)


def test_rejection_audit_unscoped_status_variants(tmp_path, monkeypatch):
    import json
    import sys
    import types

    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)

    from types import SimpleNamespace
    from tv_market_identity.cli import _write_rejection_audit
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow

    rows = [
        TvRow("LSX:A", "LSX", "A", "A", "EUR", "stock", ("common",), None, None, None, "DE0000000001"),
        TvRow("LSX:B", "LSX", "B", "B", "EUR", "stock", ("common",), None, None, None, "DE0000000002"),
        TvRow("LSX:C", "LSX", "C", "C", "EUR", "stock", ("common",), None, None, None, "DE0000000003"),
    ]
    bindings = {
        r.tv_id: Binding(
            r.tv_id, r.symbol, r.prefix, r.currency, r.tv_type, "REJECTED",
            rejection_reason="OPENFIGI_SOURCE_NO_MATCH",
        )
        for r in rows
    }

    class OF:
        def map_jobs(self, jobs):
            out = []
            for j in jobs:
                if "micCode" in j:
                    out.append([])
                    continue
                if j["idValue"].endswith("1"):
                    out.append([])
                elif j["idValue"].endswith("2"):
                    out.append([
                        OpenFigiIdentity(
                            "F1", "C1", None, "A", "A",
                            "Common Stock", "Common Stock", "X",
                        )
                    ])
                else:
                    out.append([
                        OpenFigiIdentity(
                            "F2", "C2", "S1", "A", "A",
                            "Common Stock", "Common Stock", "X",
                        ),
                        OpenFigiIdentity(
                            "F3", "C3", "S2", "A", "A",
                            "Common Stock", "Common Stock", "Y",
                        ),
                    ])
            return out

    class Y:
        batch_size = 75

        def quotes(self, symbols):
            return {}

    out = tmp_path / "audit.jsonl"
    _write_rejection_audit(
        out, rows, bindings, SimpleNamespace(openfigi=OF(), yahoo=Y())
    )
    recs = [json.loads(x) for x in out.read_text().splitlines()]
    assert [x["unscoped_openfigi_status"] for x in recs] == [
        "UNKNOWN", "SHARE_CLASS_MISSING", "AMBIGUOUS_SHARE_CLASS"
    ]


def test_rejection_audit_records_home_market_candidate_proof_and_quote_blocks(tmp_path, monkeypatch):
    import json
    import sys
    import types

    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)

    from types import SimpleNamespace
    from tv_market_identity.cli import _write_rejection_audit
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate

    row = TvRow(
        "LSX:TEST", "LSX", "TEST", "Test Corp", "EUR", "stock", ("common",),
        None, None, None, "US0000000001",
    )
    binding = Binding(
        row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED",
        rejection_reason="OPENFIGI_SOURCE_NO_MATCH",
    )

    class OF:
        def map_jobs(self, jobs):
            out = []
            for job in jobs:
                if "micCode" in job:
                    out.append([])
                else:
                    out.append([
                        OpenFigiIdentity(
                            "F1", "C1", "SHARE1", "HOME", "Test Corp",
                            "Common Stock", "Common Stock", "US",
                        ),
                        OpenFigiIdentity(
                            "F2", "C2", None, "HOMEEUR", "Test Corp",
                            "Common Stock", "Common Stock", "X1",
                        ),
                    ])
            return out

    class Y:
        batch_size = 75
        def search_exact_isin(self, isin):
            assert isin == "US0000000001"
            return [
                YahooSearchCandidate("HOME", "NMS", "EQUITY", "Test", "Test Corp"),
                YahooSearchCandidate("WRONG", "NYQ", "EQUITY", "Wrong", "Wrong Corp"),
            ]
        def quotes(self, symbols):
            result = {}
            if "HOME" in symbols:
                result["HOME"] = YahooQuote(
                    "HOME", "NMS", "NasdaqGS", "USD", "EQUITY", "us_market",
                    "Test", "Test Corp", 10.0, 0,
                )
            if "WRONG" in symbols:
                result["WRONG"] = YahooQuote(
                    "WRONG", "NYQ", "NYSE", "USD", "EQUITY", "us_market",
                    "Wrong", "Wrong Corp", 20.0, 0,
                )
            return result
        def chart_quotes(self, symbols):
            return {}

    out = tmp_path / "audit.jsonl"
    _write_rejection_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    assert rec["home_market_audit_status"] == "CANDIDATES_RECORDED"
    by_symbol = {x["symbol"]: x for x in rec["home_market_search_candidates"]}
    assert by_symbol["HOME"]["openfigi_ticker_confirmed"] is True
    assert by_symbol["HOME"]["quote_contract_valid"] is True
    assert by_symbol["HOME"]["admission_blocks"] == []
    assert by_symbol["WRONG"]["openfigi_ticker_confirmed"] is False
    assert "OPENFIGI_HOME_LISTING_UNCONFIRMED" in by_symbol["WRONG"]["admission_blocks"]


def test_rejection_audit_home_market_status_explains_missing_share_class(tmp_path, monkeypatch):
    import json
    import sys
    import types

    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)

    from types import SimpleNamespace
    from tv_market_identity.cli import _write_rejection_audit
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow

    row = TvRow(
        "GETTEX:A", "GETTEX", "A", "A Corp", "EUR", "stock", ("common",),
        None, None, None, "US0000000002",
    )
    binding = Binding(
        row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED",
        rejection_reason="OPENFIGI_SOURCE_NO_MATCH",
    )

    class OF:
        def map_jobs(self, jobs):
            return [
                [] if "micCode" in job else [
                    OpenFigiIdentity("F", "C", None, "A", "A Corp", "Common Stock", "Common Stock", "X")
                ]
                for job in jobs
            ]

    class Y:
        batch_size = 75
        def search_exact_isin(self, isin):
            raise AssertionError("search candidates may be prefetched diagnostically, but no candidate can become proof")
        def quotes(self, symbols):
            return {}

    out = tmp_path / "audit.jsonl"
    _write_rejection_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    assert rec["home_market_audit_status"] == "SHARE_CLASS_MISSING"
    assert rec["home_market_search_candidates"] == []
