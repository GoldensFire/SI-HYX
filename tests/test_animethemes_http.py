"""Admission retries must close responses, wait globally and reject truncation."""
import threading

import pytest
import requests

from si_hyx_parts.animepack import theme_http as http


class Clock:
    def __init__(self):
        self.now = 0.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Response:
    def __init__(self, status=200, body=None, headers=None, error=None):
        self.status_code = status
        self.body = http.MAGIC + b"x" * 2048 if body is None else body
        self.headers = {"Content-Length": str(len(self.body)), **(headers or {})}
        self.error = error
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.closed = True

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, _):
        yield self.body
        if self.error:
            raise self.error


class Session:
    def __init__(self, responses, clock):
        self.responses = iter(responses)
        self.calls = []
        self.clock = clock

    def get(self, url, **kwargs):
        self.calls.append((self.clock.time(), kwargs))
        return next(self.responses)


@pytest.fixture
def clock_gate():
    clock = Clock()
    return clock, http.RequestGate(clock=clock.time, sleep=clock.sleep)


def transfer(tmp_path, session, gate, *, stopped=lambda: False):
    target = tmp_path / "source.webm"
    size = http.download(session, "https://v.animethemes.moe/test.webm", target,
                         stopped, lambda _: None, gate=gate)
    assert size == target.stat().st_size
    assert not target.with_suffix(".webm.part").exists()
    return target


def test_busy_retry_closes_response_and_honors_server_delay(tmp_path, clock_gate):
    clock, gate = clock_gate
    busy, good = Response(503, headers={"Retry-After": "12"}), Response()
    session = Session([busy, good], clock)
    transfer(tmp_path, session, gate)
    assert busy.closed and good.closed
    assert session.calls[1][0] >= 12
    assert all("Range" not in options["headers"] for _, options in session.calls)


def test_cooldown_is_shared_by_two_downloads(tmp_path, clock_gate):
    clock, gate = clock_gate
    one = Session([Response()], clock)
    two = Session([Response()], clock)
    transfer(tmp_path, one, gate)
    transfer(tmp_path, two, gate)
    assert two.calls[0][0] >= http.INTERVAL


@pytest.mark.parametrize("status", [403, 404, 410])
def test_permanent_http_failure_is_not_retried(tmp_path, clock_gate, status):
    clock, gate = clock_gate
    response = Response(status)
    session = Session([response], clock)
    with pytest.raises(http.SourceError, match=str(status)):
        transfer(tmp_path, session, gate)
    assert len(session.calls) == 1 and response.closed
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("broken", [
    Response(headers={"Content-Length": "5000"}),
    Response(error=requests.exceptions.ChunkedEncodingError("EOF")),
    Response(body=b"<html>busy</html>"),
    Response(206),
])
def test_bad_transfer_is_discarded_then_restarted(tmp_path, clock_gate, broken):
    clock, gate = clock_gate
    good = Response()
    session = Session([broken, good], clock)
    target = transfer(tmp_path, session, gate)
    assert target.read_bytes() == good.body
    assert broken.closed and good.closed
    assert session.calls[1][0] >= 8


def test_retry_limit_removes_partial_and_is_finite(tmp_path, clock_gate):
    clock, gate = clock_gate
    responses = [Response(503) for _ in range(http.ATTEMPTS)]
    session = Session(responses, clock)
    with pytest.raises(http.SourceError, match="исчерпаны"):
        transfer(tmp_path, session, gate)
    assert len(session.calls) == http.ATTEMPTS
    assert all(response.closed for response in responses)
    assert not list(tmp_path.iterdir())


def test_stop_during_cooldown_makes_no_second_request(tmp_path, clock_gate):
    clock, gate = clock_gate
    session = Session([Response(503)], clock)
    with pytest.raises(http.Stopped):
        transfer(tmp_path, session, gate, stopped=lambda: clock.time() >= 1)
    assert len(session.calls) == 1
    assert clock.time() < 1.2


def test_stop_while_another_generator_holds_the_slot():
    gate = http.RequestGate()
    result = []
    with gate.slot(lambda: False):
        def waiter():
            try:
                with gate.slot(lambda: True):
                    result.append("entered")
            except http.Stopped:
                result.append("stopped")
        thread = threading.Thread(target=waiter)
        thread.start()
        thread.join(timeout=1)
        assert not thread.is_alive()
    assert result == ["stopped"]


@pytest.mark.parametrize("value,expected", [
    (None, 0), ("no", 0), ("-3", 0), ("5", 5), ("nan", 0), ("inf", 0)])
def test_retry_after_invalid_and_numeric(value, expected):
    assert http.retry_after(value) == expected


def test_file_transport_does_not_inherit_api_adapter_retries():
    session = requests.Session()
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=4))
    session.headers["User-Agent"] = "SI-HYX-test"
    session.proxies["https"] = "http://proxy.invalid"
    with http.transport(session) as client:
        assert client is not session
        assert client.get_adapter("https://v.animethemes.moe").max_retries.total == 0
        assert client.headers["User-Agent"] == "SI-HYX-test"
        assert client.proxies == session.proxies
    assert session.get_adapter("https://v.animethemes.moe").max_retries.total == 4
    session.close()
