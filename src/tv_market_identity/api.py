from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from .cache import CacheDB
from .models import Binding, TvRow
from .compat import CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
from .policy import RESOLVER_VERSION


PUBLIC_MAPPING_API_VERSION = 1


class MappingInputError(ValueError):
    """Raised when an application mapping request is structurally invalid."""


def _text(value: object | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _upper(value: object | None) -> str | None:
    text = _text(value)
    return text.upper() if text is not None else None


def _bool_or_none(value: object | None) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise MappingInputError("active_symbol must be boolean or null")


@dataclass(frozen=True)
class TvYahooMappingRequest:
    """Application-facing TradingView identity input.

    This deliberately excludes display/valuation fields and runtime Yahoo quote
    data.  The source listing is represented by exact TradingView identity and
    the identity/lifecycle fields required by the resolver/Registry contract.
    """

    request_id: str
    qualified_tv_id: str
    currency: str | None = None
    tv_type: str | None = None
    type_specs: tuple[str, ...] = ()
    isin: str | None = None
    name: str | None = None
    active_symbol: bool | None = None

    def __post_init__(self) -> None:
        request_id = _text(self.request_id)
        tv_id = _upper(self.qualified_tv_id)
        if request_id is None:
            raise MappingInputError("request_id is required")
        if tv_id is None or ":" not in tv_id:
            raise MappingInputError("qualified_tv_id must be EXCHANGE:SYMBOL")
        prefix, symbol = tv_id.split(":", 1)
        if not prefix or not symbol:
            raise MappingInputError("qualified_tv_id must be EXCHANGE:SYMBOL")
        if any(ch.isspace() for ch in tv_id):
            raise MappingInputError("qualified_tv_id must not contain whitespace")

        specs: list[str] = []
        for value in self.type_specs:
            text = _text(value)
            if text is None:
                continue
            specs.append(text)

        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "qualified_tv_id", tv_id)
        object.__setattr__(self, "currency", _upper(self.currency))
        object.__setattr__(self, "tv_type", _text(self.tv_type))
        object.__setattr__(self, "type_specs", tuple(specs))
        object.__setattr__(self, "isin", _upper(self.isin))
        object.__setattr__(self, "name", _text(self.name))
        object.__setattr__(self, "active_symbol", _bool_or_none(self.active_symbol))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TvYahooMappingRequest":
        if not isinstance(value, Mapping):
            raise MappingInputError("mapping request must be an object")
        allowed = {
            "request_id",
            "qualified_tv_id",
            "currency",
            "tv_type",
            "type_specs",
            "isin",
            "name",
            "active_symbol",
        }
        unknown = set(value) - allowed
        if unknown:
            raise MappingInputError(
                "mapping request contains unknown keys: " + ", ".join(sorted(unknown))
            )
        specs = value.get("type_specs", ())
        if specs is None:
            specs = ()
        if isinstance(specs, str) or not isinstance(specs, Sequence):
            raise MappingInputError("type_specs must be an array")
        return cls(
            request_id=value.get("request_id"),
            qualified_tv_id=value.get("qualified_tv_id"),
            currency=value.get("currency"),
            tv_type=value.get("tv_type"),
            type_specs=tuple(specs),
            isin=value.get("isin"),
            name=value.get("name"),
            active_symbol=value.get("active_symbol"),
        )

    def to_tv_row(self) -> TvRow:
        prefix, symbol = self.qualified_tv_id.split(":", 1)
        return TvRow(
            tv_id=self.qualified_tv_id,
            prefix=prefix,
            symbol=symbol,
            name=self.name,
            currency=self.currency,
            tv_type=self.tv_type,
            type_specs=self.type_specs,
            sector=None,
            market_cap=None,
            close=None,
            isin=self.isin,
            active_symbol=self.active_symbol,
        )


@dataclass(frozen=True)
class TvYahooMappingResult:
    request_id: str
    qualified_tv_id: str
    status: str
    yahoo_symbol: str | None
    source: str
    mapping_method: str | None = None
    resolver_policy: str | None = None
    identity_fingerprint: str | None = None
    rejection_reason: str | None = None
    source_mic: str | None = None
    target_mic: str | None = None
    share_class_figi: str | None = None
    cache_hit: bool = False

    @property
    def verified(self) -> bool:
        return self.status == "VERIFIED" and bool(self.yahoo_symbol)

    def as_dict(self) -> dict[str, Any]:
        return {
            "api_version": PUBLIC_MAPPING_API_VERSION,
            "request_id": self.request_id,
            "qualified_tv_id": self.qualified_tv_id,
            "status": self.status,
            "yahoo_symbol": self.yahoo_symbol,
            "source": self.source,
            "mapping_method": self.mapping_method,
            "resolver_policy": self.resolver_policy,
            "identity_fingerprint": self.identity_fingerprint,
            "rejection_reason": self.rejection_reason,
            "source_mic": self.source_mic,
            "target_mic": self.target_mic,
            "share_class_figi": self.share_class_figi,
            "cache_hit": self.cache_hit,
        }


@dataclass(frozen=True)
class TvYahooBatchResult:
    results: tuple[TvYahooMappingResult, ...]
    telemetry: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "results", tuple(self.results))
        object.__setattr__(self, "telemetry", MappingProxyType(dict(self.telemetry)))


class ResolverLike(Protocol):
    def resolve(
        self,
        rows: list[TvRow],
        refresh: bool = False,
        market: str | None = None,
        refresh_rejected: bool = False,
    ) -> dict[str, Binding]: ...


ResolverFactory = Callable[[], ResolverLike]


class TvYahooMappingService:
    """Versioned batch mapping boundary for application consumers.

    The warm path reads the normalized Identity Registry directly and does not
    construct provider clients. Only exact Registry misses/stale rows invoke the
    resolver factory. This keeps provider imports/calls out of the common
    application path while preserving the existing fail-closed resolver as the
    sole producer of new VERIFIED mappings.
    """

    def __init__(
        self,
        cache: CacheDB,
        resolver_factory: ResolverFactory,
        *,
        verified_ttl_days: int = 60,
    ) -> None:
        if not isinstance(cache, CacheDB):
            raise TypeError("cache must be CacheDB")
        if not callable(resolver_factory):
            raise TypeError("resolver_factory must be callable")
        if isinstance(verified_ttl_days, bool) or int(verified_ttl_days) <= 0:
            raise ValueError("verified_ttl_days must be positive")
        self.cache = cache
        self._resolver_factory = resolver_factory
        self.verified_ttl = int(verified_ttl_days) * 86400

    @staticmethod
    def _binding_result(
        request: TvYahooMappingRequest,
        binding: Binding | None,
        *,
        source: str,
    ) -> TvYahooMappingResult:
        if binding is None:
            return TvYahooMappingResult(
                request_id=request.request_id,
                qualified_tv_id=request.qualified_tv_id,
                status="REJECTED",
                yahoo_symbol=None,
                source=source,
                rejection_reason="NO_RESOLVER_RESULT",
            )
        return TvYahooMappingResult(
            request_id=request.request_id,
            qualified_tv_id=request.qualified_tv_id,
            status=binding.status,
            yahoo_symbol=binding.yahoo_symbol if binding.status == "VERIFIED" else None,
            source=source,
            mapping_method=binding.mapping_method,
            resolver_policy=binding.resolver_version,
            identity_fingerprint=binding.fingerprint,
            rejection_reason=binding.rejection_reason,
            source_mic=binding.source_mic,
            target_mic=binding.target_mic,
            share_class_figi=binding.share_class_figi,
            cache_hit=bool(binding.cache_hit),
        )

    def map_batch(
        self,
        requests: Iterable[TvYahooMappingRequest],
        *,
        market: str | None = None,
        refresh: bool = False,
        refresh_rejected: bool = False,
    ) -> TvYahooBatchResult:
        request_list = tuple(requests)
        if any(not isinstance(item, TvYahooMappingRequest) for item in request_list):
            raise TypeError("requests must contain TvYahooMappingRequest values")
        if not request_list:
            return TvYahooBatchResult((), {"requested": 0})

        rows_by_tv_id: dict[str, TvRow] = {}
        for request in request_list:
            row = request.to_tv_row()
            previous = rows_by_tv_id.get(row.tv_id)
            if previous is not None and previous != row:
                raise MappingInputError(
                    f"duplicate qualified_tv_id has conflicting source evidence: {row.tv_id}"
                )
            rows_by_tv_id[row.tv_id] = row
        unique_rows = list(rows_by_tv_id.values())

        registry_hits: dict[str, Binding] = {}
        registry_stats = None
        if not refresh:
            registry_hits, registry_stats = self.cache.get_registry_tv_yahoo(
                unique_rows,
                accepted_policies=(
                    RESOLVER_VERSION,
                    *CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS,
                ),
                max_age_seconds=self.verified_ttl,
            )

        # Older compatible VERIFIED bindings still reside in the TV-keyed
        # legacy cache. Read them in one indexed batch *before* constructing
        # provider clients/BatchResolver; never elevate them into Registry.
        legacy_hits: dict[str, Binding] = {}
        if not refresh:
            legacy_misses = [row for row in unique_rows if row.tv_id not in registry_hits]
            legacy_hits = self.cache.get_application_legacy_bindings(
                legacy_misses,
                current_policy=RESOLVER_VERSION,
                compatible_verified_policies=CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS,
            )
            if refresh_rejected:
                legacy_hits = {
                    tv_id: binding for tv_id, binding in legacy_hits.items()
                    if binding.status != "REJECTED"
                }

        misses = [
            row for row in unique_rows
            if row.tv_id not in registry_hits and row.tv_id not in legacy_hits
        ]
        resolved: dict[str, Binding] = {}
        resolver_invocations = 0
        if misses:
            resolver = self._resolver_factory()
            if not hasattr(resolver, "resolve") or not callable(resolver.resolve):
                raise TypeError("resolver_factory must return an object with resolve()")
            resolver_invocations = 1
            resolved = resolver.resolve(
                misses,
                refresh=refresh,
                market=market,
                refresh_rejected=refresh_rejected,
            )

        bindings = dict(registry_hits)
        bindings.update(legacy_hits)
        bindings.update(resolved)
        # Keep source="RESOLVER" for legacy hits in API v1: garp-cli's
        # strict v1 client admits only REGISTRY/RESOLVER provenance values.
        # cache_hit=true and legacy_hits telemetry identify the fast path.
        results = tuple(
            self._binding_result(
                request,
                bindings.get(request.qualified_tv_id),
                source=(
                    "REGISTRY"
                    if request.qualified_tv_id in registry_hits
                    else "RESOLVER"
                ),
            )
            for request in request_list
        )

        telemetry = {
            "requested": len(request_list),
            "legacy_hits": len(legacy_hits),
            "legacy_verified_hits": sum(
                1 for binding in legacy_hits.values() if binding.status == "VERIFIED"
            ),
            "legacy_rejected_hits": sum(
                1 for binding in legacy_hits.values() if binding.status == "REJECTED"
            ),
            "unique_tv_ids": len(unique_rows),
            "registry_hits": len(registry_hits),
            "resolver_rows": len(misses),
            "resolver_invocations": resolver_invocations,
            "verified": sum(1 for item in results if item.verified),
            "rejected": sum(1 for item in results if not item.verified),
        }
        if registry_stats is not None:
            telemetry.update(
                {
                    "registry_misses": registry_stats.misses,
                    "registry_stale_or_incompatible": registry_stats.stale_or_incompatible,
                    "registry_ambiguous": registry_stats.ambiguous,
                }
            )
        return TvYahooBatchResult(results, telemetry)


def default_resolver_factory(
    cache: CacheDB,
    *,
    yahoo_batch: int = 75,
    verified_ttl_days: int = 60,
    rejected_ttl_hours: int = 6,
    finnhub_ttl_hours: int = 24,
) -> ResolverFactory:
    """Return a lazy factory matching the standalone CLI provider contract."""

    def build() -> ResolverLike:
        from .providers import FinnhubProvider, OpenFigiProvider, ProviderError, YahooProvider
        from .resolver import BatchResolver

        try:
            finnhub = FinnhubProvider()
        except ProviderError:
            finnhub = None
        return BatchResolver(
            cache=cache,
            finnhub=finnhub,
            openfigi=OpenFigiProvider(),
            yahoo=YahooProvider(batch_size=yahoo_batch),
            verified_ttl_days=verified_ttl_days,
            rejected_ttl_hours=rejected_ttl_hours,
            finnhub_ttl_hours=finnhub_ttl_hours,
        )

    return build


def open_mapping_service(
    cache_path: str | Path,
    *,
    yahoo_batch: int = 75,
    verified_ttl_days: int = 60,
    rejected_ttl_hours: int = 6,
    finnhub_ttl_hours: int = 24,
) -> tuple[CacheDB, TvYahooMappingService]:
    """Convenience constructor for process/CLI consumers.

    The returned CacheDB is owned by the caller and must be closed.
    """

    cache = CacheDB(cache_path)
    service = TvYahooMappingService(
        cache,
        default_resolver_factory(
            cache,
            yahoo_batch=yahoo_batch,
            verified_ttl_days=verified_ttl_days,
            rejected_ttl_hours=rejected_ttl_hours,
            finnhub_ttl_hours=finnhub_ttl_hours,
        ),
        verified_ttl_days=verified_ttl_days,
    )
    return cache, service
