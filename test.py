import json
import os
import sys

import finnhub
import requests
import yfinance as yf


TV_ID = "TSX:SHOP"

LOCAL_SYMBOL = "SHOP"
EXPECTED_MIC = "XTSE"
EXPECTED_CURRENCY = "CAD"
EXPECTED_TYPE = "Common Stock"

YAHOO_CANDIDATE = "SHOP.TO"


def dump(title, value):
    print()
    print("=" * 80)
    print(title)
    print("=" * 80)
    print(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True))


# ----------------------------------------------------------------------
# 1. OpenFIGI
# ----------------------------------------------------------------------

def check_openfigi():
    headers = {
        "Content-Type": "application/json",
    }

    api_key = os.getenv("OPENFIGI_API_KEY")
    if api_key:
        headers["X-OPENFIGI-APIKEY"] = api_key

    payload = [
        {
            "idType": "ID_EXCH_SYMBOL",
            "idValue": LOCAL_SYMBOL,
            "micCode": EXPECTED_MIC,
            "currency": EXPECTED_CURRENCY,
            "securityType2": EXPECTED_TYPE,
        }
    ]

    response = requests.post(
        "https://api.openfigi.com/v3/mapping",
        headers=headers,
        json=payload,
        timeout=20,
    )

    print(f"OpenFIGI HTTP: {response.status_code}")

    response.raise_for_status()

    raw = response.json()
    dump("OPENFIGI RAW", raw)

    if not raw:
        raise RuntimeError("OpenFIGI returned empty response")

    job = raw[0]

    if "error" in job:
        raise RuntimeError(f"OpenFIGI error: {job['error']}")

    rows = job.get("data") or []

    # Defensive filtering even though filters were supplied to API.
    rows = [
        r
        for r in rows
        if (r.get("securityType2") or "").lower() == EXPECTED_TYPE.lower()
    ]

    dump("OPENFIGI FILTERED", rows)

    if not rows:
        raise RuntimeError(
            "OpenFIGI found no Common Stock for SHOP + XTSE + CAD"
        )

    if len(rows) != 1:
        raise RuntimeError(
            f"OpenFIGI identity is ambiguous: {len(rows)} candidates"
        )

    row = rows[0]

    return {
        "venue_figi": row.get("figi"),
        "composite_figi": row.get("compositeFIGI"),
        "share_class_figi": row.get("shareClassFIGI"),
        "ticker": row.get("ticker"),
        "name": row.get("name"),
        "exchange_code": row.get("exchCode"),
        "security_type": row.get("securityType"),
        "security_type2": row.get("securityType2"),
    }


# ----------------------------------------------------------------------
# 2. Finnhub
#
# IMPORTANT:
# /search is only candidate corroboration for non-US.
# It does NOT prove MIC/currency/listing identity.
# ----------------------------------------------------------------------

def check_finnhub():
    api_key = os.environ["FINNHUB_API_KEY"]
    client = finnhub.Client(api_key=api_key)

    raw = client.symbol_lookup(YAHOO_CANDIDATE)

    dump("FINNHUB LOOKUP RAW", raw)

    rows = raw.get("result") or []

    exact = [
        row
        for row in rows
        if row.get("symbol") == YAHOO_CANDIDATE
    ]

    dump("FINNHUB EXACT CANDIDATES", exact)

    if len(exact) != 1:
        raise RuntimeError(
            f"Finnhub exact {YAHOO_CANDIDATE!r}: "
            f"expected 1 result, got {len(exact)}"
        )

    row = exact[0]

    if row.get("type") != EXPECTED_TYPE:
        raise RuntimeError(
            f"Finnhub type mismatch: "
            f"{row.get('type')!r} != {EXPECTED_TYPE!r}"
        )

    return {
        "symbol": row.get("symbol"),
        "display_symbol": row.get("displaySymbol"),
        "description": row.get("description"),
        "type": row.get("type"),
    }


# ----------------------------------------------------------------------
# 3. Yahoo RAW quote
#
# Deliberately do NOT use:
#
#     yf.Ticker(...).info["symbol"]
#
# yfinance's Quote code overwrites quote_result[0]["symbol"] with the
# requested symbol during info processing.
#
# Instead use its HTTP transport directly and inspect Yahoo's RAW
# quoteResponse.
# ----------------------------------------------------------------------

def check_yahoo():
    ticker = yf.Ticker(YAHOO_CANDIDATE)

    raw = ticker._data.get_raw_json(
        "https://query1.finance.yahoo.com/v7/finance/quote",
        params={
            "symbols": YAHOO_CANDIDATE,
            "formatted": "false",
        },
        timeout=20,
    )

    dump("YAHOO RAW", raw)

    rows = (
        raw.get("quoteResponse", {})
        .get("result", [])
    )

    if len(rows) != 1:
        raise RuntimeError(
            f"Yahoo expected exactly 1 quote, got {len(rows)}"
        )

    row = rows[0]

    # These are strict target-provider checks.
    if row.get("symbol") != YAHOO_CANDIDATE:
        raise RuntimeError(
            f"Yahoo symbol mismatch: "
            f"{row.get('symbol')!r} != {YAHOO_CANDIDATE!r}"
        )

    if row.get("currency") != EXPECTED_CURRENCY:
        raise RuntimeError(
            f"Yahoo currency mismatch: "
            f"{row.get('currency')!r} != {EXPECTED_CURRENCY!r}"
        )

    if row.get("quoteType") != "EQUITY":
        raise RuntimeError(
            f"Yahoo quoteType mismatch: "
            f"{row.get('quoteType')!r} != 'EQUITY'"
        )

    return {
        "symbol": row.get("symbol"),
        "exchange": row.get("exchange"),
        "full_exchange_name": row.get("fullExchangeName"),
        "currency": row.get("currency"),
        "quote_type": row.get("quoteType"),
        "market": row.get("market"),
        "short_name": row.get("shortName"),
        "long_name": row.get("longName"),
        "price": row.get("regularMarketPrice"),
        "exchange_delay": row.get("exchangeDataDelayedBy"),
    }


def main():
    print(f"TV identity      : {TV_ID}")
    print(f"Expected MIC     : {EXPECTED_MIC}")
    print(f"Expected currency: {EXPECTED_CURRENCY}")
    print(f"Yahoo candidate  : {YAHOO_CANDIDATE}")

    try:
        openfigi = check_openfigi()
        finnhub_data = check_finnhub()
        yahoo = check_yahoo()

        result = {
            "tv": {
                "ticker_id": TV_ID,
                "local_symbol": LOCAL_SYMBOL,
                "expected_mic": EXPECTED_MIC,
                "currency": EXPECTED_CURRENCY,
                "type": EXPECTED_TYPE,
            },
            "openfigi": openfigi,
            "finnhub": finnhub_data,
            "yahoo": yahoo,
        }

        dump("FINAL EVIDENCE", result)

        print()
        print("VERIFIED")
        print(
            f"{TV_ID} -> {YAHOO_CANDIDATE}"
        )

        return 0

    except Exception as exc:
        print()
        print("REJECTED")
        print(f"{type(exc).__name__}: {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())