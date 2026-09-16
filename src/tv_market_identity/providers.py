from __future__ import annotations

import json
import os
import time
import re
from collections import defaultdict
from typing import Iterable
from urllib.parse import quote

import requests

from .models import OpenFigiIdentity, YahooQuote, YahooSearchCandidate


class ProviderError(RuntimeError):
    pass


def _nullable_text(value):
    """Normalize provider sentinels that mean metadata is unavailable.

    Yahoo sometimes serializes unavailable metadata as a string (for example
    ``"NONE"``) instead of JSON null on thin international listings. Treat
    only a small explicit sentinel set as missing; all other text is preserved.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text.upper() in {"", "NONE", "NULL", "N/A", "NA", "-"}:
        return None
    return text


class FinnhubProvider:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("FINNHUB_API_KEY")
        if not self.api_key:
            raise ProviderError("FINNHUB_API_KEY is required for US universe resolution")
        try:
            import finnhub
        except ImportError as exc:
            raise ProviderError("finnhub-python is not installed; run pip install -e .") from exc
        self.client = finnhub.Client(api_key=self.api_key)

    def us_symbols(self) -> list[dict]:
        try:
            return list(self.client.stock_symbols("US"))
        except Exception as exc:
            raise ProviderError(f"Finnhub stock_symbols('US') failed: {exc}") from exc


class OpenFigiProvider:
    URL = "https://api.openfigi.com/v3/mapping"

    def __init__(self, api_key: str | None = None, timeout: int = 25):
        self.api_key = api_key or os.getenv("OPENFIGI_API_KEY")
        self.timeout = timeout
        self.session = requests.Session()
        self._run_memo: dict[str, tuple[OpenFigiIdentity, ...]] = {}
        self.metrics = defaultdict(int)

    def reset_run_cache(self) -> None:
        """Reset request-local OpenFIGI memoization and performance counters.

        The resolver calls this once at the beginning of each resolve() run.
        Mapping responses are immutable identity evidence, so identical jobs may
        safely share one provider response within that run.  Nothing is persisted
        across resolver runs.
        """
        self._run_memo.clear()
        self.metrics.clear()

    @staticmethod
    def _job_key(job: dict) -> str:
        return json.dumps(job, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @property
    def batch_size(self) -> int:
        # Current v3 docs are inconsistent for unauthenticated max-jobs (5 vs 10).
        # Use the conservative value. Authenticated max is documented as 100.
        return 100 if self.api_key else 5

    def map_jobs(self, jobs: list[dict]) -> list[list[OpenFigiIdentity]]:
        if not jobs:
            return []

        self.metrics["requested_jobs"] += len(jobs)
        keys = [self._job_key(job) for job in jobs]

        # Preserve one output slot per requested job, but only send unique
        # uncached jobs to OpenFIGI.  Duplicate jobs can occur both within one
        # resolver stage and across bridge/probe/fallback stages.
        pending_jobs: list[dict] = []
        pending_keys: list[str] = []
        pending_seen: set[str] = set()
        for job, key in zip(jobs, keys):
            if key in self._run_memo:
                self.metrics["memo_hits"] += 1
                continue
            if key in pending_seen:
                self.metrics["intra_call_dedup_hits"] += 1
                continue
            pending_seen.add(key)
            pending_jobs.append(job)
            pending_keys.append(key)

        if pending_jobs:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["X-OPENFIGI-APIKEY"] = self.api_key

            fetched: list[list[OpenFigiIdentity]] = []
            for start in range(0, len(pending_jobs), self.batch_size):
                chunk = pending_jobs[start:start + self.batch_size]
                self.metrics["network_batches"] += 1
                self.metrics["network_jobs"] += len(chunk)
                for attempt in range(4):
                    try:
                        r = self.session.post(self.URL, headers=headers, json=chunk, timeout=self.timeout)
                        if r.status_code == 429:
                            wait = float(r.headers.get("ratelimit-reset") or 2 ** attempt)
                            time.sleep(max(0.5, min(wait, 10)))
                            continue
                        r.raise_for_status()
                        payload = r.json()
                        break
                    except Exception as exc:
                        if attempt == 3:
                            raise ProviderError(f"OpenFIGI mapping failed: {exc}") from exc
                        time.sleep(2 ** attempt)
                else:
                    raise ProviderError("OpenFIGI mapping failed after retries")

                if len(payload) != len(chunk):
                    raise ProviderError(f"OpenFIGI response length mismatch: {len(payload)} != {len(chunk)}")
                for result in payload:
                    identities: list[OpenFigiIdentity] = []
                    for row in result.get("data") or []:
                        identities.append(OpenFigiIdentity(
                            figi=row.get("figi"),
                            composite_figi=row.get("compositeFIGI"),
                            share_class_figi=row.get("shareClassFIGI"),
                            ticker=row.get("ticker"),
                            name=row.get("name"),
                            security_type=row.get("securityType"),
                            security_type2=row.get("securityType2"),
                            exch_code=row.get("exchCode"),
                        ))
                    fetched.append(identities)

            if len(fetched) != len(pending_keys):
                raise ProviderError(f"OpenFIGI memoization alignment mismatch: {len(fetched)} != {len(pending_keys)}")
            for key, identities in zip(pending_keys, fetched):
                # OpenFigiIdentity is frozen; tuples make the memo itself
                # immutable and fresh lists are returned to callers.
                self._run_memo[key] = tuple(identities)

        return [list(self._run_memo[key]) for key in keys]



class YahooProvider:
    URL = "https://query1.finance.yahoo.com/v7/finance/quote"
    SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"

    def __init__(self, batch_size: int = 75):
        self.batch_size = batch_size
        try:
            from yfinance.data import YfData
        except ImportError as exc:
            raise ProviderError("yfinance is not installed; run pip install -e .") from exc
        self.data = YfData()
        self._run_quote_memo: dict[str, YahooQuote] = {}
        self._run_search_memo: dict[str, tuple[YahooSearchCandidate, ...]] = {}
        self.metrics = defaultdict(int)

    def reset_run_cache(self) -> None:
        """Reset positive Yahoo quote evidence cached for one resolver run.

        Only successfully returned quote rows are memoized.  Missing rows are
        intentionally *not* cached because Yahoo v7 can omit thin listings from
        one bulk response and return them on the targeted retry used by the
        resolver.
        """
        self._run_quote_memo.clear()
        if hasattr(self, "_run_search_memo"):
            self._run_search_memo.clear()
        else:
            self._run_search_memo = {}
        self.metrics.clear()

    def search_exact_isin(self, isin: str, max_results: int = 10) -> list[YahooSearchCandidate]:
        """Search Yahoo using one exact ISIN query and no fuzzy/name fallback.

        Yahoo search is only a discovery mechanism here.  A returned symbol is
        never identity evidence by itself; the resolver independently binds it
        back to the same exact ISIN/shareClassFIGI through OpenFIGI and then
        validates Yahoo quote/chart metadata.
        """
        token = str(isin or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", token):
            return []
        if not hasattr(self, "_run_search_memo"):
            self._run_search_memo = {}
        if not hasattr(self, "metrics"):
            self.metrics = defaultdict(int)
        cached = self._run_search_memo.get(token)
        if cached is not None:
            self.metrics["search_memo_hits"] += 1
            return list(cached)

        self.metrics["search_queries"] += 1
        try:
            raw = self.data.get_raw_json(
                self.SEARCH_URL,
                params={
                    "q": token,
                    "quotesCount": max(1, int(max_results)),
                    "newsCount": 0,
                    "listsCount": 0,
                    "enableFuzzyQuery": "false",
                    "enableNavLinks": "false",
                    "enableCb": "false",
                },
                timeout=25,
            )
        except Exception as exc:
            raise ProviderError(f"Yahoo exact-ISIN search failed for {token}: {exc}") from exc

        out: list[YahooSearchCandidate] = []
        seen: set[str] = set()
        for row in raw.get("quotes") or []:
            symbol = _nullable_text(row.get("symbol"))
            if not symbol:
                continue
            symbol = symbol.upper()
            if symbol in seen:
                continue
            seen.add(symbol)
            out.append(YahooSearchCandidate(
                symbol=symbol,
                exchange=_nullable_text(row.get("exchange")),
                quote_type=_nullable_text(row.get("quoteType")),
                short_name=_nullable_text(row.get("shortname") or row.get("shortName")),
                long_name=_nullable_text(row.get("longname") or row.get("longName")),
            ))
        self.metrics["search_returned_candidates"] += len(out)
        self._run_search_memo[token] = tuple(out)
        return list(out)

    def quotes(self, symbols: Iterable[str]) -> dict[str, YahooQuote]:
        requested = [s for s in symbols if s]
        unique = list(dict.fromkeys(requested))

        # Some tests construct YahooProvider with __new__ to exercise parsing in
        # isolation; initialize performance state lazily for compatibility.
        if not hasattr(self, "_run_quote_memo"):
            self._run_quote_memo = {}
        if not hasattr(self, "metrics"):
            self.metrics = defaultdict(int)

        self.metrics["requested_symbols"] += len(unique)
        self.metrics["intra_call_dedup_hits"] += max(0, len(requested) - len(unique))

        out: dict[str, YahooQuote] = {}
        pending: list[str] = []
        for symbol in unique:
            cached = self._run_quote_memo.get(symbol)
            if cached is not None:
                out[symbol] = cached
                self.metrics["memo_hits"] += 1
            else:
                pending.append(symbol)

        for start in range(0, len(pending), self.batch_size):
            chunk = pending[start:start + self.batch_size]
            self.metrics["network_batches"] += 1
            self.metrics["network_symbols"] += len(chunk)
            try:
                raw = self.data.get_raw_json(
                    self.URL,
                    params={"symbols": ",".join(chunk), "formatted": "false"},
                    timeout=25,
                )
            except Exception as exc:
                raise ProviderError(f"Yahoo bulk quote failed for {len(chunk)} symbols: {exc}") from exc
            returned_in_chunk: set[str] = set()
            for row in (raw.get("quoteResponse", {}) or {}).get("result", []) or []:
                symbol = str(row.get("symbol") or "")
                if not symbol or symbol not in chunk:
                    continue
                quote = YahooQuote(
                    symbol=symbol,
                    exchange=_nullable_text(row.get("exchange")),
                    full_exchange_name=_nullable_text(row.get("fullExchangeName")),
                    currency=_nullable_text(row.get("currency")),
                    quote_type=_nullable_text(row.get("quoteType")),
                    market=_nullable_text(row.get("market")),
                    short_name=_nullable_text(row.get("shortName")),
                    long_name=_nullable_text(row.get("longName")),
                    price=row.get("regularMarketPrice"),
                    delayed_by=row.get("exchangeDataDelayedBy"),
                )
                out[symbol] = quote
                self._run_quote_memo[symbol] = quote
                returned_in_chunk.add(symbol)
            self.metrics["returned_symbols"] += len(returned_in_chunk)
            # Missing symbols remain uncached by design so a subsequent targeted
            # retry is a real network request rather than a memoized miss.
            self.metrics["missing_symbols"] += len(chunk) - len(returned_in_chunk)
        return out

    def chart_quotes(self, symbols: Iterable[str]) -> dict[str, YahooQuote]:
        """Fetch Yahoo v8 chart metadata for thin/ambiguous quote rows.

        This endpoint is deliberately a fallback, not the primary bulk source.
        Its meta block independently reports the exact Yahoo symbol, currency,
        exchange and instrumentType and is useful when v7/quote omits a row or
        misclassifies a thin international listing.
        """
        unique = list(dict.fromkeys(s for s in symbols if s))
        out: dict[str, YahooQuote] = {}
        for symbol in unique:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe='')}"
            try:
                raw = self.data.get_raw_json(
                    url,
                    params={
                        "range": "1d",
                        "interval": "1d",
                        "includePrePost": "false",
                        "events": "div,splits",
                    },
                    timeout=25,
                )
            except Exception:
                continue
            result = ((raw.get("chart") or {}).get("result") or [None])[0]
            if not result:
                continue
            meta = result.get("meta") or {}
            returned_symbol = str(meta.get("symbol") or symbol)
            if returned_symbol != symbol:
                continue
            out[symbol] = YahooQuote(
                symbol=returned_symbol,
                exchange=_nullable_text(meta.get("exchangeName")),
                full_exchange_name=_nullable_text(meta.get("fullExchangeName")),
                currency=_nullable_text(meta.get("currency")),
                quote_type=_nullable_text(meta.get("instrumentType")),
                market=_nullable_text(meta.get("market")),
                short_name=_nullable_text(meta.get("shortName")),
                long_name=_nullable_text(meta.get("longName")),
                price=meta.get("regularMarketPrice"),
                delayed_by=meta.get("exchangeDataDelayedBy"),
            )
        return out
