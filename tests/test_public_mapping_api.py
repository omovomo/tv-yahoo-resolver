import time

import pytest

from tv_market_identity.api import (
    MappingInputError,
    PUBLIC_MAPPING_API_VERSION,
    TvYahooMappingRequest,
    TvYahooMappingService,
)
from tv_market_identity.cache import CacheDB
from tv_market_identity.models import Binding
from tv_market_identity.policy import RESOLVER_VERSION
from tv_market_identity.resolver import BatchResolver


def _request(*, request_id="row-1", tv_id="NASDAQ:MSFT", isin="US5949181045"):
    return TvYahooMappingRequest(
        request_id=request_id,
        qualified_tv_id=tv_id,
        currency="USD",
        tv_type="stock",
        type_specs=("common",),
        isin=isin,
        name="Microsoft Corp",
        active_symbol=True,
    )


def _binding(request, *, yahoo_symbol="MSFT"):
    row = request.to_tv_row()
    now = int(time.time())
    return Binding(
        tv_id=row.tv_id,
        tv_symbol=row.symbol,
        tv_prefix=row.prefix,
        tv_currency=row.currency,
        tv_type=row.tv_type,
        status="VERIFIED",
        yahoo_symbol=yahoo_symbol,
        yahoo_exchange="NMS",
        yahoo_market="us_market",
        yahoo_quote_type="EQUITY",
        yahoo_currency="USD",
        yahoo_price=400.0,
        yahoo_delayed_by=0,
        quote_status="FRESH",
        resolved_mic="XNAS",
        source_mic="XNAS",
        target_mic="XNAS",
        source_venue_code="NASDAQ",
        mapping_method="SAME_VENUE",
        composite_figi="BBG000BPH459",
        share_class_figi="BBG001S5TD05",
        venue_figi="BBG000BPH459",
        source_venue_figi="BBG000BPH459",
        target_venue_figi="BBG000BPH459",
        fingerprint="identity-fingerprint",
        resolver_version=RESOLVER_VERSION,
        validated_at=now,
        expires_at=now + 3600,
    )


class _StubResolver(BatchResolver):
    def __init__(self, bindings):
        self._bindings = bindings
        self.calls = []

    def resolve(self, rows, refresh=False, market=None, refresh_rejected=False):
        self.calls.append((tuple(rows), refresh, market, refresh_rejected))
        return {row.tv_id: self._bindings[row.tv_id] for row in rows}


def test_mapping_request_is_narrow_and_strict():
    request = TvYahooMappingRequest.from_mapping(
        {
            "request_id": "screen:42",
            "qualified_tv_id": "nasdaq:msft",
            "currency": "usd",
            "tv_type": "stock",
            "type_specs": ["common"],
            "isin": "us5949181045",
            "active_symbol": True,
        }
    )
    row = request.to_tv_row()
    assert request.qualified_tv_id == "NASDAQ:MSFT"
    assert row.tv_id == "NASDAQ:MSFT"
    assert row.currency == "USD"
    assert row.isin == "US5949181045"
    assert row.sector is None
    assert row.market_cap is None
    assert row.close is None

    with pytest.raises(MappingInputError):
        TvYahooMappingRequest.from_mapping(
            {"request_id": "x", "qualified_tv_id": "MSFT", "display_price": 100}
        )


def test_warm_registry_hit_does_not_construct_resolver(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        request = _request()
        row = request.to_tv_row()
        binding = _binding(request)
        metrics = cache.put_registry_tv_yahoo({row.tv_id: row}, [binding])
        assert metrics["written"] == 1

        def forbidden_factory():
            raise AssertionError("warm Registry hit must not construct providers/resolver")

        service = TvYahooMappingService(cache, forbidden_factory)
        batch = service.map_batch([request], market="america")
        assert batch.telemetry["registry_hits"] == 1
        assert batch.telemetry["resolver_rows"] == 0
        assert batch.telemetry["resolver_invocations"] == 0
        result = batch.results[0]
        assert result.verified is True
        assert result.source == "REGISTRY"
        assert result.yahoo_symbol == "MSFT"
        assert result.cache_hit is True
        assert result.as_dict()["api_version"] == PUBLIC_MAPPING_API_VERSION
        assert "yahoo_price" not in result.as_dict()
    finally:
        cache.close()


def test_registry_miss_invokes_resolver_only_for_miss_tail(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        warm = _request(request_id="warm", tv_id="NASDAQ:MSFT", isin="US5949181045")
        cold = _request(request_id="cold", tv_id="NASDAQ:AAPL", isin="US0378331005")
        warm_binding = _binding(warm, yahoo_symbol="MSFT")
        cold_binding = _binding(cold, yahoo_symbol="AAPL")
        cold_binding.tv_id = "NASDAQ:AAPL"
        cold_binding.tv_symbol = "AAPL"
        cold_binding.fingerprint = "aapl-fingerprint"
        cache.put_registry_tv_yahoo({warm.qualified_tv_id: warm.to_tv_row()}, [warm_binding])

        resolver = _StubResolver({cold.qualified_tv_id: cold_binding})
        service = TvYahooMappingService(cache, lambda: resolver)
        batch = service.map_batch([warm, cold], market="america")

        assert batch.telemetry["registry_hits"] == 1
        assert batch.telemetry["resolver_rows"] == 1
        assert batch.telemetry["resolver_invocations"] == 1
        assert len(resolver.calls) == 1
        rows, refresh, market, refresh_rejected = resolver.calls[0]
        assert [row.tv_id for row in rows] == ["NASDAQ:AAPL"]
        assert refresh is False
        assert market == "america"
        assert refresh_rejected is False
        assert [(item.request_id, item.source, item.yahoo_symbol) for item in batch.results] == [
            ("warm", "REGISTRY", "MSFT"),
            ("cold", "RESOLVER", "AAPL"),
        ]
    finally:
        cache.close()


def test_duplicate_tv_id_requires_identical_source_evidence(tmp_path):
    cache = CacheDB(tmp_path / "identity.sqlite3")
    try:
        service = TvYahooMappingService(cache, lambda: _StubResolver({}))
        first = _request(request_id="a")
        second = TvYahooMappingRequest(
            request_id="b",
            qualified_tv_id=first.qualified_tv_id,
            currency="EUR",
            tv_type=first.tv_type,
            type_specs=first.type_specs,
            isin=first.isin,
            active_symbol=True,
        )
        with pytest.raises(MappingInputError, match="conflicting source evidence"):
            service.map_batch([first, second])
    finally:
        cache.close()


def test_lightweight_mapping_cli_warm_path_avoids_main_cli_dependencies(tmp_path, monkeypatch, capsys):
    from tv_market_identity.mapping_cli import parser as mapping_parser, run

    cache_path = tmp_path / "identity.sqlite3"
    cache = CacheDB(cache_path)
    try:
        request = _request()
        row = request.to_tv_row()
        cache.put_registry_tv_yahoo({row.tv_id: row}, [_binding(request)])
    finally:
        cache.close()

    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        '{"request_id":"row-1","qualified_tv_id":"NASDAQ:MSFT","currency":"USD","tv_type":"stock","type_specs":["common"],"isin":"US5949181045","name":"Microsoft Corp","active_symbol":true}\n',
        encoding="utf-8",
    )
    args = mapping_parser().parse_args(
        ["--cache", str(cache_path), "--input", str(input_path), "--telemetry"]
    )
    assert run(args) == 0
    captured = capsys.readouterr()
    result = __import__("json").loads(captured.out)
    telemetry = __import__("json").loads(captured.err)
    assert result["status"] == "VERIFIED"
    assert result["source"] == "REGISTRY"
    assert result["yahoo_symbol"] == "MSFT"
    assert telemetry["registry_hits"] == 1
    assert telemetry["resolver_invocations"] == 0
