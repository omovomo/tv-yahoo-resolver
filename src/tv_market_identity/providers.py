from __future__ import annotations

import os
import time
from typing import Iterable
from urllib.parse import quote

import requests

from .models import OpenFigiIdentity, YahooQuote


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

    @property
    def batch_size(self) -> int:
        # Current v3 docs are inconsistent for unauthenticated max-jobs (5 vs 10).
        # Use the conservative value. Authenticated max is documented as 100.
        return 100 if self.api_key else 5

    def map_jobs(self, jobs: list[dict]) -> list[list[OpenFigiIdentity]]:
        if not jobs:
            return []
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key
        all_results: list[list[OpenFigiIdentity]] = []
        for start in range(0, len(jobs), self.batch_size):
            chunk = jobs[start:start + self.batch_size]
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
                all_results.append(identities)
        return all_results


class YahooProvider:
    URL = "https://query1.finance.yahoo.com/v7/finance/quote"

    def __init__(self, batch_size: int = 75):
        self.batch_size = batch_size
        try:
            from yfinance.data import YfData
        except ImportError as exc:
            raise ProviderError("yfinance is not installed; run pip install -e .") from exc
        self.data = YfData()

    def quotes(self, symbols: Iterable[str]) -> dict[str, YahooQuote]:
        unique = list(dict.fromkeys(s for s in symbols if s))
        out: dict[str, YahooQuote] = {}
        for start in range(0, len(unique), self.batch_size):
            chunk = unique[start:start + self.batch_size]
            try:
                raw = self.data.get_raw_json(
                    self.URL,
                    params={"symbols": ",".join(chunk), "formatted": "false"},
                    timeout=25,
                )
            except Exception as exc:
                raise ProviderError(f"Yahoo bulk quote failed for {len(chunk)} symbols: {exc}") from exc
            for row in (raw.get("quoteResponse", {}) or {}).get("result", []) or []:
                symbol = str(row.get("symbol") or "")
                if not symbol:
                    continue
                out[symbol] = YahooQuote(
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
