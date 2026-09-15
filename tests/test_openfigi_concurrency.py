import threading
import time

from tv_market_identity.providers import OpenFigiProvider


class NoopRateLimiter:
    def acquire(self):
        return None

    def defer(self, seconds):
        return None


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def job(n):
    return {"idType": "ID_ISIN", "idValue": f"ISIN{n:04d}", "micCode": "XFRA"}


def payload_for(chunk):
    return [
        {"data": [{
            "figi": f"FIGI-{j['idValue']}",
            "compositeFIGI": f"COMP-{j['idValue']}",
            "shareClassFIGI": f"SHARE-{j['idValue']}",
            "ticker": j["idValue"],
            "name": j["idValue"],
            "securityType": "Common Stock",
            "securityType2": "Common Stock",
            "exchCode": "GF",
        }]}
        for j in chunk
    ]


class ConcurrentFakeSession:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []

    def post(self, url, headers, json, timeout):
        first = int(json[0]["idValue"][-4:])
        # Force later chunks to finish first; map_jobs must still restore the
        # original chunk/job order before populating the memo and output.
        delay = {0: 0.06, 100: 0.03, 200: 0.005}.get(first, 0.005)
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append(first)
        try:
            time.sleep(delay)
            return FakeResponse(
                payload_for(json),
                headers={"ratelimit-remaining": "20", "ratelimit-reset": "1.5"},
            )
        finally:
            with self.lock:
                self.active -= 1


class Retry429Session:
    def __init__(self):
        self.calls = 0

    def post(self, url, headers, json, timeout):
        self.calls += 1
        if self.calls == 1:
            return FakeResponse(
                [],
                status_code=429,
                headers={"ratelimit-remaining": "0", "ratelimit-reset": "0"},
            )
        return FakeResponse(
            payload_for(json),
            headers={"ratelimit-remaining": "24", "ratelimit-reset": "5.5"},
        )


def test_openfigi_runs_batches_concurrently_but_preserves_job_order():
    provider = OpenFigiProvider(api_key="x", max_workers=3)
    provider.session = ConcurrentFakeSession()
    provider._rate_limiter = NoopRateLimiter()

    jobs = [job(i) for i in range(250)]
    result = provider.map_jobs(jobs)

    assert [rows[0].ticker for rows in result] == [j["idValue"] for j in jobs]
    assert provider.session.max_active >= 2
    assert provider.metrics["network_batches"] == 3
    assert provider.metrics["network_jobs"] == 250
    assert provider.metrics["concurrent_batches_submitted"] == 3
    assert provider.metrics["concurrent_batches_completed"] == 3
    assert provider.metrics["transport_max_workers"] == 3
    assert provider.metrics["rate_limit_remaining_min"] == 20.0
    assert provider.metrics["rate_limit_reset_max_seconds"] == 1.5


def test_openfigi_429_uses_retry_path_and_preserves_result():
    provider = OpenFigiProvider(api_key="x", max_workers=1)
    provider.session = Retry429Session()
    provider._rate_limiter = NoopRateLimiter()

    result = provider.map_jobs([job(1)])

    assert result[0][0].ticker == "ISIN0001"
    assert provider.session.calls == 2
    assert provider.metrics["rate_limit_429s"] == 1
    assert provider.metrics["transport_attempts"] == 2
    assert provider.metrics["transport_retries"] == 1
    assert provider.metrics["network_batches"] == 1
    assert provider.metrics["network_jobs"] == 1


def test_openfigi_worker_count_is_bounded():
    provider = OpenFigiProvider(api_key="x", max_workers=999)
    assert provider.max_workers == 16

    provider = OpenFigiProvider(api_key="x", max_workers=0)
    assert provider.max_workers == 1
