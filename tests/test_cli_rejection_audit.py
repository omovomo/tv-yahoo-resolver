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


def test_rejection_audit_v064_resolution_classification(tmp_path, monkeypatch):
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

    class OF:
        def map_jobs(self, jobs):
            out=[]
            for j in jobs:
                if j.get("idType") == "ID_ISIN" and j.get("idValue") == "US0000000001" and "micCode" not in j:
                    out.append([OpenFigiIdentity("F","C",None,"OLD","OLD CO","Common Stock","Common Stock","X1")])
                else: out.append([])
            return out
    class Y:
        batch_size=75
        def quotes(self, symbols): return {}
        def search_exact(self, query): return []
    rows=[
        TvRow("GETTEX:NOID","GETTEX","NOID","No Id","EUR","stock",("common",),None,None,None,None,False),
        TvRow("GETTEX:OLD","GETTEX","OLD","Old Co","EUR","stock",("common",),None,None,None,"US0000000001",False),
    ]
    bindings={
        rows[0].tv_id: Binding(rows[0].tv_id,rows[0].symbol,rows[0].prefix,rows[0].currency,rows[0].tv_type,"REJECTED",rejection_reason="TV_ISIN_UNKNOWN"),
        rows[1].tv_id: Binding(rows[1].tv_id,rows[1].symbol,rows[1].prefix,rows[1].currency,rows[1].tv_type,"REJECTED",rejection_reason="OPENFIGI_SOURCE_NO_MATCH"),
    }
    p=tmp_path/"a.jsonl"
    _write_rejection_audit(p, rows, bindings, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    recs=[json.loads(x) for x in p.read_text().splitlines()]
    assert recs[0]["resolution_classification"] == "SOURCE_IDENTIFIER_MISSING"
    assert recs[1]["resolution_classification"] == "SHARE_CLASS_METADATA_MISSING"
    assert recs[1]["classification_evidence"]["active_symbol"] is False


def test_rejection_audit_v065_explicit_type_mismatch_precedes_missing_share_class(tmp_path, monkeypatch):
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

    class OF:
        def map_jobs(self, jobs):
            out = []
            for j in jobs:
                if j.get("idType") == "ID_ISIN" and j.get("idValue") == "GB0001905362" and "micCode" not in j:
                    out.append([OpenFigiIdentity("F", "C", None, "CAGP", "CAGP", "DOMESTIC", "Corp", "LN")])
                else:
                    out.append([])
            return out

    class Y:
        batch_size = 75
        def quotes(self, symbols): return {}
        def search_exact(self, query): return []

    row = TvRow("LSE:CAGP", "LSE", "CAGP", "CAGP", "GBX", "stock", ("preferred",), None, None, None, "GB0001905362", True)
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED", rejection_reason="YAHOO_TYPE_MISMATCH:BOND")
    p = tmp_path / "audit.jsonl"
    _write_rejection_audit(p, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(p.read_text(encoding="utf-8").strip())
    assert rec["unscoped_openfigi_status"] == "SHARE_CLASS_MISSING"
    assert rec["resolution_classification"] == "TAXONOMY_CONFLICT"


def test_rejection_audit_records_preferred_same_venue_exact_isin_proof(tmp_path, monkeypatch):
    import json
    import sys
    import types

    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)

    from types import SimpleNamespace
    import tv_market_identity.cli as cli
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate

    monkeypatch.setattr(cli, "probe_identifier_metadata", lambda tickers: {t: {"found": True} for t in tickers})
    row = TvRow(
        "NYSE:TEST/PB", "NYSE", "TEST/PB", "Test Preferred", "USD", "stock", ("preferred",),
        None, None, None, "US0000000001", True,
    )
    binding = Binding(
        row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED",
        rejection_reason="FINNHUB_TYPE_MISMATCH:PUBLIC",
    )

    class OF:
        def map_jobs(self, jobs):
            out = []
            for job in jobs:
                if job.get("micCode") == "XNYS":
                    out.append([OpenFigiIdentity(
                        "FIGI1", "COMP1", None, "TEST 5 PERP B", "Test Preferred",
                        "PUBLIC", "Preferred Stock", "US",
                    )])
                else:
                    out.append([OpenFigiIdentity(
                        "FIGI1", "COMP1", None, "TEST 5 PERP B", "Test Preferred",
                        "PUBLIC", "Preferred Stock", "US",
                    )])
            return out

    class Y:
        batch_size = 75
        def search_exact_isin(self, isin):
            return [YahooSearchCandidate("TEST-PB", "NYQ", "EQUITY", "Test", "Test Preferred")]
        def quotes(self, symbols):
            if "TEST-PB" not in symbols:
                return {}
            return {"TEST-PB": YahooQuote(
                "TEST-PB", "NYQ", "NYSE", "USD", "EQUITY", "us_market",
                "Test", "Test Preferred", 25.0, 0,
            )}
        def chart_quotes(self, symbols):
            return {}

    out = tmp_path / "audit.jsonl"
    cli._write_rejection_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    diag = rec["preferred_same_venue_audit"]
    assert diag["attempted"] is True
    assert diag["source_mic"] == "XNYS"
    assert diag["source_isin_mic_status"] == "UNIQUE_PREFERRED_FIGI"
    assert diag["source_figis"] == ["FIGI1"]
    assert diag["same_venue_valid_candidate_count"] == 1
    assert diag["yahoo_exact_isin_candidates"][0]["same_venue_contract_valid"] is True
    assert diag["yahoo_exact_isin_candidates"][0]["admission_blocks"] == []

def test_rejection_audit_preferred_exact_tv_symbol_fallback(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tv_market_identity import cli
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote

    import json
    row = TvRow("NYSE:SOJE", "NYSE", "SOJE", "Southern Preferred", "USD", "stock", ("preferred",), None, None, None, "US0000000001", True)
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED", rejection_reason="FINNHUB_TYPE_MISMATCH:PUBLIC")

    class OF:
        def map_jobs(self, jobs):
            return [[OpenFigiIdentity("FIGI1", "COMP1", None, "SO 4.95 PERP", "Southern", "PUBLIC", "Preferred Stock", "US")]]

    class Y:
        def search_exact_isin(self, isin):
            return []
        def quotes(self, symbols):
            symbols = list(symbols)
            if "SOJE" in symbols:
                return {"SOJE": YahooQuote("SOJE", "NYQ", "NYSE", "USD", "EQUITY", "us_market", "Southern", "Southern", 25.0, 0)}
            return {}
        def chart_quotes(self, symbols):
            return {}

    out = tmp_path / "audit.jsonl"
    cli._write_rejection_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    diag = rec["preferred_same_venue_audit"]
    assert diag["source_isin_mic_status"] == "UNIQUE_PREFERRED_FIGI"
    assert diag["yahoo_exact_isin_candidate_count"] == 0
    probe = diag["yahoo_exact_tv_symbol_probe"]
    assert probe["attempted"] is True
    assert probe["symbol"] == "SOJE"
    assert probe["same_venue_contract_valid"] is True
    assert probe["admission_blocks"] == []

def test_rejection_audit_otc_preferred_mic_discovery_is_diagnostic_only(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tv_market_identity import cli
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow
    import json

    monkeypatch.setattr(cli, "probe_identifier_metadata", lambda tickers: {t: {"found": True} for t in tickers})
    row = TvRow("OTC:TESTP", "OTC", "TESTP", "Test Preferred", "USD", "stock", ("preferred",), None, None, None, "US0000000001", True)
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED", rejection_reason="FINNHUB_TYPE_MISMATCH:?")

    class OF:
        def map_jobs(self, jobs):
            out = []
            for job in jobs:
                if job.get("micCode") == "OTCM":
                    out.append([OpenFigiIdentity("FIGI-OTCM", "COMP", None, "TESTP", "Test Preferred", "PUBLIC", "Preferred Stock", "US")])
                elif "micCode" not in job:
                    out.append([OpenFigiIdentity("FIGI-OTCM", "COMP", None, "TESTP", "Test Preferred", "PUBLIC", "Preferred Stock", "US")])
                else:
                    out.append([])
            return out

    class Y:
        batch_size = 75
        def quotes(self, symbols): return {}
        def search_exact_isin(self, isin): return []
        def chart_quotes(self, symbols): return {}

    out = tmp_path / "audit.jsonl"
    cli._write_rejection_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    diag = rec["otc_preferred_mic_discovery"]
    assert diag["attempted"] is True
    assert diag["candidate_mics"] == ["OTCM", "OTCB", "OOTC", "OTCD"]
    assert diag["status"] == "UNIQUE_MIC"
    assert diag["proven_mics"] == ["OTCM"]
    assert next(x for x in diag["mic_results"] if x["mic"] == "OTCM")["status"] == "UNIQUE_PREFERRED_FIGI"
    assert rec["rejection_reason"] == "FINNHUB_TYPE_MISMATCH:?"

def test_rejection_audit_otc_preferred_yahoo_discovery_records_raw_venue_only(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from tv_market_identity import cli
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote
    import json

    monkeypatch.setattr(cli, "probe_identifier_metadata", lambda tickers: {t: {"found": True} for t in tickers})
    row = TvRow("OTC:TESTP", "OTC", "TESTP", "Test Preferred", "USD", "stock", ("preferred",), None, None, None, "US0000000001", True)
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED", rejection_reason="FINNHUB_TYPE_MISMATCH:?")

    class OF:
        def map_jobs(self, jobs):
            out = []
            for job in jobs:
                if job.get("micCode") == "OOTC":
                    out.append([OpenFigiIdentity("FIGI-OOTC", "COMP", None, "TESTP", "Test Preferred", "PUBLIC", "Preferred Stock", "US")])
                elif "micCode" not in job:
                    out.append([OpenFigiIdentity("FIGI-OOTC", "COMP", None, "TESTP", "Test Preferred", "PUBLIC", "Preferred Stock", "US")])
                else:
                    out.append([])
            return out

    class Y:
        batch_size = 75
        def search_exact_isin(self, isin): return []
        def quotes(self, symbols):
            return {s: YahooQuote(s, "PNK", "OTC Markets", "USD", "EQUITY", "us_market", None, None, 10.0, 0) for s in symbols}
        def chart_quotes(self, symbols): return {}

    out = tmp_path / "audit.jsonl"
    cli._write_rejection_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    diag = rec["otc_preferred_yahoo_discovery"]
    assert diag["attempted"] is True
    assert diag["proven_mic"] == "OOTC"
    assert diag["venue_equivalence_assumed"] is False
    assert diag["yahoo_exact_isin_candidate_count"] == 0
    probe = diag["yahoo_exact_tv_symbol_probe"]
    assert probe["attempted"] is True
    assert probe["quote_exchange"] == "PNK"
    assert probe["non_venue_contract_valid"] is True
    assert rec["rejection_reason"] == "FINNHUB_TYPE_MISMATCH:?"


def test_rejection_audit_v075_yahoo_anomaly_matrix_is_diagnostic_only(tmp_path, monkeypatch):
    import json
    import sys
    import types
    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)

    from types import SimpleNamespace
    import tv_market_identity.cli as cli
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate

    monkeypatch.setattr(cli, "probe_identifier_metadata", lambda ids: {})
    row = TvRow("NYSE:TEST", "NYSE", "TEST", "Test Corp", "USD", "stock", ("common",), None, None, None, "US0000000001")
    binding = Binding(tv_id=row.tv_id, tv_symbol=row.symbol, tv_prefix=row.prefix,
                      tv_currency=row.currency, tv_type=row.tv_type, status="REJECTED",
                      rejection_reason="YAHOO_TYPE_MISMATCH:MUTUALFUND")

    identity = OpenFigiIdentity(figi="BBG000TEST1", composite_figi="BBG000TESTC",
        share_class_figi="BBG001TESTS", ticker="TEST", name="Test Corp",
        security_type="Common Stock", security_type2="Common Stock", exch_code="US")

    class OF:
        def map_jobs(self, jobs):
            return [[identity] for _ in jobs]

    bad = YahooQuote(symbol="TEST", exchange="NYQ", full_exchange_name="NYSE",
        currency="USD", quote_type="MUTUALFUND", market="us_market",
        short_name="Test", long_name="Test Corp", price=10.0, delayed_by=0)

    class Y:
        def quotes(self, symbols):
            return {s: bad for s in symbols if s == "TEST"}
        def chart_quotes(self, symbols):
            return {s: bad for s in symbols if s == "TEST"}
        def search_exact_isin(self, isin):
            return [YahooSearchCandidate(symbol="TEST", exchange="NYQ", quote_type="MUTUALFUND",
                                         short_name="Test", long_name="Test Corp")]

    out = tmp_path / "audit.jsonl"
    cli._write_rejection_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    diag = rec["yahoo_anomaly_audit"]
    assert diag["attempted"] is True
    assert diag["diagnostic_only"] is True
    assert diag["source_mic"] == "XNYS"
    assert diag["source_isin_mic_proven"] is True
    assert diag["exact_isin_candidate_count"] == 1
    assert diag["exact_tv_symbol_quote"]["quote_type"] == "MUTUALFUND"
    assert diag["exact_tv_symbol_chart"]["quote_type"] == "MUTUALFUND"
    assert diag["classification"] == "YAHOO_TAXONOMY_ONLY_CONFLICT"
    assert binding.status == "REJECTED"
    assert binding.rejection_reason == "YAHOO_TYPE_MISMATCH:MUTUALFUND"


def test_v076_nyse_preferred_symbol_cohort_audit_includes_verified_rows(tmp_path, monkeypatch):
    import json
    import sys
    import types
    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)
    from types import SimpleNamespace
    import tv_market_identity.cli as cli
    from tv_market_identity.models import OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate

    rows = [
        TvRow("NYSE:AAA/PA", "NYSE", "AAA/PA", "AAA", "USD", "stock", ("preferred",), None, None, None, "US0000000001"),
        TvRow("NYSE:BBB", "NYSE", "BBB", "BBB", "USD", "stock", ("common",), None, None, None, "US0000000002"),
    ]
    identity = OpenFigiIdentity("FIGI1", "COMP1", None, "AAA PR A", "AAA", "PUBLIC", "Preferred Stock", "US")
    class OF:
        def map_jobs(self, jobs):
            assert jobs == [{"idType":"ID_ISIN","idValue":"US0000000001","micCode":"XNYS"}]
            return [[identity]]
    q = YahooQuote("AAA-PA", "NYQ", "NYSE", "USD", "EQUITY", "us_market", "AAA", "AAA", 10.0, 0)
    class Y:
        def search_exact_isin(self, isin):
            return [YahooSearchCandidate("AAA-PA", "NYQ", "EQUITY", "AAA", "AAA")]
        def quotes(self, symbols):
            return {"AAA-PA": q}
    out = tmp_path / "cohort.jsonl"
    cli._write_us_nyse_preferred_symbol_audit(out, rows, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    recs = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert len(recs) == 1
    rec = recs[0]
    assert rec["tv_id"] == "NYSE:AAA/PA"
    assert rec["source_isin_mic_proven"] is True
    assert rec["exact_isin_candidate_count"] == 1
    assert rec["exact_isin_candidates"][0]["symbol"] == "AAA-PA"
    assert rec["exact_isin_candidates"][0]["punctuation_equivalent_to_tv"] is True
    assert rec["classification"] == "UNIQUE_EXACT_ISIN_SAME_VENUE_PUNCTUATION_EQUIVALENT"


def test_v078_us_finnhub_unit_audit_is_diagnostic_only(tmp_path, monkeypatch):
    import json, sys, types
    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)
    from types import SimpleNamespace
    import tv_market_identity.cli as cli
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate

    row = TvRow("NASDAQ:UONE", "NASDAQ", "UONE", "Unit One", "USD", "fund", ("unit",), None, None, None, "US0000000001")
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED",
                      finnhub_type="Unit", rejection_reason="FINNHUB_TYPE_MISMATCH:Unit")
    identity = OpenFigiIdentity("F1", "C1", "S1", "UONE", "Unit One", "Unit", "Unit", "US")
    class OF:
        def map_jobs(self, jobs):
            return [[identity] for _ in jobs]
    q = YahooQuote("UONE", "NMS", "NasdaqGS", "USD", "EQUITY", "us_market", "Unit One", "Unit One", 10.0, 0)
    class Y:
        def search_exact_isin(self, isin):
            return [YahooSearchCandidate("UONE", "NMS", "EQUITY", "Unit One", "Unit One")]
        def quotes(self, symbols): return {"UONE": q}
    out = tmp_path / "unit.jsonl"
    cli._write_us_finnhub_unit_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text().strip())
    assert rec["diagnostic_only"] is True
    assert rec["tv_type"] == "fund" and rec["tv_type_specs"] == ["unit"]
    assert rec["unscoped_openfigi_status"] == "UNIQUE_SHARE_CLASS"
    assert rec["source_openfigi_unique_figi"] is True
    assert rec["yahoo_exact_isin_candidate_count"] == 1
    assert rec["yahoo_exact_isin_candidates"][0]["source_venue_compatible"] is True
    assert binding.status == "REJECTED"
    assert binding.rejection_reason == "FINNHUB_TYPE_MISMATCH:Unit"


def test_v080_xnas_source_binding_audit_is_diagnostic_only(tmp_path):
    import json
    from types import SimpleNamespace
    from tv_market_identity import cli
    from tv_market_identity.models import Binding, OpenFigiIdentity, TvRow, YahooQuote, YahooSearchCandidate
    row = TvRow("NASDAQ:ABC", "NASDAQ", "ABC", "ABC Unit", "USD", "fund", ("unit",), None, None, None, "US0000000001")
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED", finnhub_type="Unit", rejection_reason="FINNHUB_TYPE_MISMATCH:Unit")
    identity = OpenFigiIdentity("BBG1", "BBGCOMP", "BBGSC", "ABC", "ABC Unit", "PUBLIC", "Unit", "US")
    class OF:
        def map_jobs(self, jobs): return [[identity] if "micCode" not in j else [] for j in jobs]
    class Y:
        def search_exact_isin(self, token): return [YahooSearchCandidate("ABC", "NMS", "EQUITY", "ABC Unit", "ABC Unit")]
        def quotes(self, symbols): return {"ABC": YahooQuote("ABC", "NMS", "NasdaqGS", "USD", "EQUITY", "us_market", "ABC Unit", "ABC Unit", 10.0, 0)}
    out = tmp_path / "xnas.jsonl"
    cli._write_us_xnas_source_binding_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text().strip())
    assert rec["diagnostic_only"] is True
    assert rec["source_mic"] == "XNAS"
    assert rec["unscoped_openfigi_status"] == "UNIQUE_SHARE_CLASS"
    assert rec["xnas_scoped_status"] == "NO_MATCH"
    assert rec["yahoo_strict_xnas_candidate_count"] == 1
    assert rec["classification"] == "XNAS_SCOPED_NO_MATCH_BUT_UNSCOPED_AND_YAHOO_STRICT"
    assert binding.status == "REJECTED"


def test_v080_xnas_source_binding_audit_excludes_non_xnas(tmp_path):
    from types import SimpleNamespace
    from tv_market_identity import cli
    from tv_market_identity.models import Binding, TvRow
    row = TvRow("NYSE:ABC", "NYSE", "ABC", "ABC Unit", "USD", "fund", ("unit",), None, None, None, "US0000000001")
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED", finnhub_type="Unit", rejection_reason="FINNHUB_TYPE_MISMATCH:Unit")
    class OF:
        def map_jobs(self, jobs): return []
    class Y:
        def search_exact_isin(self, token): return []
        def quotes(self, symbols): return {}
    out = tmp_path / "xnas.jsonl"
    cli._write_us_xnas_source_binding_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    assert out.read_text() == ""


def test_v0414_unit_audit_keeps_missing_isin_in_full_cohort(tmp_path, monkeypatch):
    import json, sys, types
    fake_tv = types.ModuleType("tradingview_screener")
    fake_tv.Column = type("Column", (), {"__init__": lambda self, *a, **k: None})
    fake_tv.Query = type("Query", (), {"__init__": lambda self, *a, **k: setattr(self, "query", {})})
    monkeypatch.setitem(sys.modules, "tradingview_screener", fake_tv)
    from types import SimpleNamespace
    import tv_market_identity.cli as cli
    from tv_market_identity.models import Binding, TvRow

    row = TvRow("AMEX:NOISIN", "AMEX", "NOISIN", "No Isin Unit", "USD", "fund", ("unit",), None, None, None, None)
    binding = Binding(row.tv_id, row.symbol, row.prefix, row.currency, row.tv_type, "REJECTED",
                      finnhub_type="Unit", rejection_reason="FINNHUB_TYPE_MISMATCH:Unit")
    class OF:
        def map_jobs(self, jobs):
            assert jobs == []
            return []
    class Y:
        def search_exact_isin(self, isin):
            raise AssertionError("missing ISIN must not be searched")
        def quotes(self, symbols): return {}
    out = tmp_path / "unit-missing.jsonl"
    cli._write_us_finnhub_unit_audit(out, [row], {row.tv_id: binding}, SimpleNamespace(openfigi=OF(), yahoo=Y()))
    rec = json.loads(out.read_text().strip())
    assert rec["diagnostic_release"] == "0.4.34"
    assert rec["classification"] == "MISSING_TV_ISIN"
    assert rec["tv_isin"] is None
    assert binding.status == "REJECTED"
