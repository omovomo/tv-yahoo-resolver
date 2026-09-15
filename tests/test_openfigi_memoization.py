from tv_market_identity.providers import OpenFigiProvider


class FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def post(self, url, headers, json, timeout):
        self.calls.append(list(json))
        payload = []
        for job in json:
            value = job["idValue"]
            if value == "EMPTY":
                payload.append({})
            else:
                payload.append({"data": [{
                    "figi": f"FIGI-{value}",
                    "compositeFIGI": f"COMP-{value}",
                    "shareClassFIGI": f"SHARE-{value}",
                    "ticker": value,
                    "name": value,
                    "securityType": "Common Stock",
                    "securityType2": "Common Stock",
                    "exchCode": "GF",
                }]})
        return FakeResponse(payload)


def job(value, mic="XFRA"):
    return {"idType": "ID_ISIN", "idValue": value, "micCode": mic}


def test_openfigi_deduplicates_within_call_and_preserves_output_order():
    provider = OpenFigiProvider(api_key="x")
    provider.session = FakeSession()

    result = provider.map_jobs([job("A"), job("B"), job("A")])

    assert [rows[0].ticker for rows in result] == ["A", "B", "A"]
    assert provider.session.calls == [[job("A"), job("B")]]
    assert provider.metrics["requested_jobs"] == 3
    assert provider.metrics["network_jobs"] == 2
    assert provider.metrics["network_batches"] == 1
    assert provider.metrics["intra_call_dedup_hits"] == 1


def test_openfigi_memoizes_across_calls_including_empty_results():
    provider = OpenFigiProvider(api_key="x")
    provider.session = FakeSession()

    first = provider.map_jobs([job("A"), job("EMPTY")])
    second = provider.map_jobs([job("EMPTY"), job("A"), job("C")])

    assert first[1] == []
    assert second[0] == []
    assert second[1][0].ticker == "A"
    assert second[2][0].ticker == "C"
    assert provider.session.calls == [
        [job("A"), job("EMPTY")],
        [job("C")],
    ]
    assert provider.metrics["requested_jobs"] == 5
    assert provider.metrics["memo_hits"] == 2
    assert provider.metrics["network_jobs"] == 3
    assert provider.metrics["network_batches"] == 2


def test_openfigi_reset_run_cache_forces_new_network_lookup():
    provider = OpenFigiProvider(api_key="x")
    provider.session = FakeSession()

    provider.map_jobs([job("A")])
    provider.reset_run_cache()
    provider.map_jobs([job("A")])

    assert provider.session.calls == [[job("A")], [job("A")]]
    assert provider.metrics["requested_jobs"] == 1
    assert provider.metrics["network_jobs"] == 1
    assert provider.metrics["memo_hits"] == 0
