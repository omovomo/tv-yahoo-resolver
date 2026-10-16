"""Read-only IBKR/Flex security reconciliation against independently proven Registry evidence.

A matching ISIN establishes a *security candidate*, not a broker listing or a
Yahoo/TV price-routing permission.  This module deliberately has no symbol
fallback, broker network dependency, Registry writes, or provider imports.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .compat import CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS
from .policy import RESOLVER_VERSION
from .models import TvRow
from .registry import tv_source_fingerprint

BROKER_SECURITY_API_VERSION = 1
_ISIN = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_ASSET_CLASSES = frozenset({"STK", "ETF", "ADR"})


class BrokerInputError(ValueError):
    """An IBKR batch request violates the strict wire contract."""


def _string(value: object | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BrokerInputError(f"{field} must be a string or null")
    value = value.strip()
    return value or None


@dataclass(frozen=True)
class IbkrSecurityRequest:
    request_id: str
    conid: str | None = None
    symbol: str | None = None
    isin: str | None = None
    currency: str | None = None
    asset_class: str | None = None

    def __post_init__(self) -> None:
        request_id = _string(self.request_id, "request_id")
        conid = _string(self.conid, "conid")
        symbol = _string(self.symbol, "symbol")
        isin = _string(self.isin, "isin")
        currency = _string(self.currency, "currency")
        asset_class = _string(self.asset_class, "asset_class")
        if not request_id:
            raise BrokerInputError("request_id is required")
        if conid and (not conid.isascii() or not conid.isdecimal() or int(conid) <= 0):
            raise BrokerInputError("conid must be a positive decimal identifier")
        if conid:
            conid = str(int(conid))
        if not conid and not isin:
            raise BrokerInputError("at least conid or isin is required")
        if isin:
            isin = isin.upper()
            if not _ISIN.fullmatch(isin):
                raise BrokerInputError("isin must be a 12-character ISIN identifier")
        if asset_class:
            asset_class = asset_class.upper()
            if asset_class not in _ASSET_CLASSES:
                raise BrokerInputError("asset_class must be STK, ETF or ADR")
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "conid", conid)
        object.__setattr__(self, "symbol", symbol.upper() if symbol else None)
        object.__setattr__(self, "isin", isin)
        object.__setattr__(self, "currency", currency.upper() if currency else None)
        object.__setattr__(self, "asset_class", asset_class)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "IbkrSecurityRequest":
        if not isinstance(payload, Mapping):
            raise BrokerInputError("request must be an object")
        allowed = {"request_id", "conid", "symbol", "isin", "currency", "asset_class"}
        unknown = set(payload) - allowed
        if unknown:
            raise BrokerInputError("unknown fields: " + ", ".join(sorted(unknown)))
        return cls(**{field: payload.get(field) for field in allowed})


@dataclass(frozen=True)
class IbkrSecurityResult:
    request_id: str
    conid: str | None
    isin: str | None
    status: str
    reason: str | None
    registry_security_id: int | None = None
    tv_candidates: tuple[str, ...] = ()
    yahoo_candidates: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "api_version": BROKER_SECURITY_API_VERSION,
            "request_id": self.request_id,
            "conid": self.conid,
            "isin": self.isin,
            "status": self.status,
            "reason": self.reason,
            "match_method": "EXACT_ISIN_REGISTRY" if self.status == "SECURITY_MATCH" else None,
            "conid_verified": False,
            "registry_security_id": self.registry_security_id,
            "tv_candidates": list(self.tv_candidates),
            "yahoo_candidates": list(self.yahoo_candidates),
            "listing_verified": False,
            "yahoo_symbol": None,
            "tv_id": None,
        }


@dataclass(frozen=True)
class IbkrSecurityBatch:
    results: tuple[IbkrSecurityResult, ...]
    telemetry: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "telemetry", MappingProxyType(dict(self.telemetry)))


def _chunks(items: list[int | str], size: int = 400):
    for start in range(0, len(items), size):
        yield items[start:start + size]


def _indexed_rows(conn: sqlite3.Connection, table: str, key: str, ids: list[int]):
    out = {}
    for part in _chunks(ids):
        marks = ",".join("?" for _ in part)
        for row in conn.execute(f"SELECT * FROM {table} WHERE {key} IN ({marks})", part):
            out[int(row[key])] = row
    return out


def _active_security_matches(
    conn: sqlite3.Connection, isins: set[str], *, max_age_seconds: int
) -> dict[str, tuple[int, tuple[str, ...], tuple[str, ...]]]:
    """Indexed ISIN -> security -> current TV/Yahoo evidence (no legacy promotion)."""
    if not isins:
        return {}
    security_by_isin: dict[str, set[int]] = {isin: set() for isin in isins}
    for part in _chunks(sorted(isins)):
        marks = ",".join("?" for _ in part)
        for row in conn.execute(
            f"""SELECT i.identifier_value,i.security_id
                FROM registry_security_identifiers i
                JOIN registry_securities s ON s.security_id=i.security_id
                WHERE i.namespace='ISIN' AND i.lifecycle_state='ACTIVE'
                  AND s.lifecycle_state='ACTIVE' AND i.identifier_value IN ({marks})""",
            part,
        ):
            security_by_isin[row["identifier_value"]].add(int(row["security_id"]))
    unique_by_isin = {isin: next(iter(ids)) for isin, ids in security_by_isin.items() if len(ids) == 1}
    if not unique_by_isin:
        return {}
    security_ids = sorted(set(unique_by_isin.values()))
    tv_sources: dict[int, sqlite3.Row] = {}
    for part in _chunks(security_ids):
        marks = ",".join("?" for _ in part)
        for row in conn.execute(
            f"""SELECT * FROM registry_provider_identifiers
                WHERE provider='TRADINGVIEW' AND identifier_type='QUALIFIED_ID'
                  AND lifecycle_state='ACTIVE' AND security_id IN ({marks})""", part
        ):
            tv_sources[int(row["provider_identifier_id"])] = row
    if not tv_sources:
        return {}
    policy_set = frozenset((RESOLVER_VERSION, *CACHE_COMPATIBLE_VERIFIED_RESOLVER_VERSIONS))
    deadline = int(time.time()) - max_age_seconds
    mappings: list[sqlite3.Row] = []
    for part in _chunks(sorted(tv_sources)):
        marks = ",".join("?" for _ in part)
        mappings.extend(conn.execute(
            f"""SELECT * FROM registry_mappings INDEXED BY idx_registry_mappings_source
                WHERE source_provider_identifier_id IN ({marks})
                  AND status='VERIFIED' AND lifecycle_state='ACTIVE'
                  AND last_verified_at>=?""", [*part, deadline]
        ).fetchall())
    if not mappings:
        return {}
    targets = _indexed_rows(conn, "registry_provider_identifiers", "provider_identifier_id",
                            sorted({int(m["target_provider_identifier_id"]) for m in mappings}))
    listing_ids = sorted({int(s["listing_id"]) for s in tv_sources.values() if s["listing_id"] is not None} |
                         {int(t["listing_id"]) for t in targets.values() if t["listing_id"] is not None})
    listings = _indexed_rows(conn, "registry_listings", "listing_id", listing_ids)
    by_security: dict[int, set[tuple[str, str]]] = {}
    isin_by_security = {security_id: isin for isin, security_id in unique_by_isin.items()}
    for m in mappings:
        if m["resolver_policy"] not in policy_set or not m["source_fingerprint"]:
            continue
        s = tv_sources.get(int(m["source_provider_identifier_id"]))
        t = targets.get(int(m["target_provider_identifier_id"]))
        if s is None or t is None or t["provider"] != "YAHOO" or t["identifier_type"] != "SYMBOL":
            continue
        security_id = int(s["security_id"])
        if t["security_id"] is None or int(t["security_id"]) != security_id:
            continue
        sl = listings.get(int(s["listing_id"])) if s["listing_id"] is not None else None
        tl = listings.get(int(t["listing_id"])) if t["listing_id"] is not None else None
        if sl is None or tl is None or any(x["lifecycle_state"] != "ACTIVE" for x in (sl, tl, t)):
            continue
        if any(int(x["security_id"]) != security_id for x in (sl, tl)):
            continue
        try:
            metadata = json.loads(s["metadata_json"] or "{}")
        except (TypeError, ValueError):
            continue
        try:
            tv_id = str(s["identifier_value"])
            prefix, symbol = tv_id.split(":", 1)
            source_row = TvRow(
                tv_id=tv_id, prefix=prefix, symbol=symbol, name=None,
                currency=metadata.get("currency"), tv_type=metadata.get("tv_type"),
                type_specs=tuple(metadata.get("type_specs") or ()), sector=None,
                market_cap=None, close=None, isin=metadata.get("isin"),
                active_symbol=metadata.get("active_symbol"),
            )
            reconstructed = tv_source_fingerprint(source_row)
        except (TypeError, ValueError, AttributeError):
            continue
        if (metadata.get("isin") != isin_by_security.get(security_id) or
                metadata.get("source_fingerprint") != reconstructed or
                m["source_fingerprint"] != reconstructed):
            continue
        by_security.setdefault(security_id, set()).add((s["identifier_value"], t["identifier_value"]))
    return {
        isin: (sec, tuple(sorted({tv for tv, _ in by_security[sec]})),
               tuple(sorted({y for _, y in by_security[sec]})))
        for isin, sec in unique_by_isin.items() if sec in by_security
    }


def reconcile_ibkr_security_batch(
    conn: sqlite3.Connection,
    requests: Iterable[IbkrSecurityRequest],
    *,
    verified_ttl_days: int = 60,
) -> IbkrSecurityBatch:
    """Reconcile exact broker ISIN against active Registry evidence, read-only.

    SECURITY_MATCH never authorizes choosing a Yahoo symbol or TradingView listing.
    A broker venue/listing contract is required before introducing VERIFIED routes.
    """
    batch = tuple(requests)
    if any(not isinstance(r, IbkrSecurityRequest) for r in batch):
        raise TypeError("requests must contain IbkrSecurityRequest")
    if verified_ttl_days <= 0:
        raise ValueError("verified_ttl_days must be positive")
    if not batch:
        return IbkrSecurityBatch((), {"requested": 0})
    # Same conid may appear in multiple imported lots, but it may not claim
    # incompatible ISINs. Refuse the entire conflicting group.
    claimed: dict[str, set[str]] = {}
    for r in batch:
        if r.conid and r.isin:
            claimed.setdefault(r.conid, set()).add(r.isin)
    conflicted = {conid for conid, ids in claimed.items() if len(ids) > 1}
    isins = {r.isin for r in batch if r.isin and r.conid not in conflicted}
    matches = _active_security_matches(conn, isins, max_age_seconds=verified_ttl_days * 86400)
    results: list[IbkrSecurityResult] = []
    for r in batch:
        if r.conid in conflicted:
            status, reason, match = "CONFLICT", "CONID_ISIN_CONFLICT", None
        elif not r.isin:
            status, reason, match = "UNRESOLVED", "ISIN_REQUIRED_FOR_SECURITY_MATCH", None
        else:
            match = matches.get(r.isin)
            status, reason = ("SECURITY_MATCH", None) if match else ("UNRESOLVED", "NO_CURRENT_REGISTRY_PROOF")
        results.append(IbkrSecurityResult(
            r.request_id, r.conid, r.isin, status, reason,
            registry_security_id=match[0] if match else None,
            tv_candidates=match[1] if match else (),
            yahoo_candidates=match[2] if match else (),
        ))
    return IbkrSecurityBatch(tuple(results), {
        "requested": len(batch),
        "security_matches": sum(r.status == "SECURITY_MATCH" for r in results),
        "unresolved": sum(r.status == "UNRESOLVED" for r in results),
        "conflicts": sum(r.status == "CONFLICT" for r in results),
        "listing_verified": 0,
    })
