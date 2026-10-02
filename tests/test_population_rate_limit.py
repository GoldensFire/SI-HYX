# -*- coding: utf-8 -*-
"""Квота общая для рабочих клиентов, Retry-After и остановка без ожидания сети."""
from email.utils import formatdate
import httpx
import pytest

import animepack_api
from si_hyx_parts.animepack_api.population_rate_limit import (
    PopulationRateLimiter, request_with_backoff, retry_seconds)
from si_hyx_parts.animepack_api.ru_manga_clients import ReMangaPopulation, MangaLibPopulation


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, seconds):
        self.now += seconds

    def limiter(self, rate=10, quota=0):
        return PopulationRateLimiter(rate, quota, clock=lambda: self.now,
                                     sleep=self.sleep, wall_clock=lambda: 1_000_000 + self.now)


def test_pacing_and_minute_quota_apply_together():
    clock = Clock()
    limiter = clock.limiter(10, 4)
    sent = []
    for _ in range(5):
        limiter.acquire()
        sent.append(clock.now)
    assert sent == pytest.approx([0, .1, .2, .3, 60])


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_retry_after_is_honored_then_request_is_retried_at_slower_speed(status):
    clock = Clock()
    limiter = clock.limiter()
    sent = []

    def send():
        sent.append(clock.now)
        return httpx.Response(status if len(sent) == 1 else 200,
                              headers={"Retry-After": "12"})

    assert request_with_backoff(limiter, send).status_code == 200
    assert sent == pytest.approx([0, 12])
    assert limiter.interval == pytest.approx(.2 if status == 429 else .1)


def test_http_date_retry_after_and_malformed_values():
    headers = {"Retry-After": formatdate(1_000_012, usegmt=True)}
    assert retry_seconds(headers, 2, lambda: 1_000_000) == 12
    for value in ("", "invalid", "NaN", "Infinity"):
        assert retry_seconds({"Retry-After": value}, 2, lambda: 0) == 2


def test_an_inflight_success_cannot_remove_the_pause_for_all_workers():
    clock = Clock()
    limiter = clock.limiter()
    limiter.observe(httpx.Response(429, headers={"Retry-After": "10"}))
    limiter.observe(httpx.Response(200))
    limiter.acquire()
    assert clock.now == pytest.approx(10)
    assert limiter.interval == pytest.approx(.2)


def test_quota_and_retry_after_waits_can_be_cancelled_promptly():
    clock = Clock()
    limiter = clock.limiter(10, 1)
    limiter.acquire()
    with pytest.raises(InterruptedError):
        limiter.acquire(lambda: clock.now >= .5)
    assert clock.now == pytest.approx(.5)
    limiter.observe(httpx.Response(429, headers={"Retry-After": "3600"}))
    with pytest.raises(InterruptedError):
        limiter.acquire(lambda: clock.now >= 1)
    assert clock.now == pytest.approx(1)


def test_retries_are_bounded_and_return_the_final_server_error():
    clock = Clock()
    attempts = []

    def send():
        attempts.append(clock.now)
        return httpx.Response(429, headers={"Retry-After": "1"})

    response = request_with_backoff(clock.limiter(), send)
    assert response.status_code == 429 and len(attempts) == 4


def test_gateway_failure_retries_the_same_catalog_page_and_closes_failed_response():
    clock = Clock()
    calls = []
    failed = httpx.Response(502)

    def send():
        calls.append("/api/manga?page=29")
        return failed if len(calls) == 1 else httpx.Response(200)

    assert request_with_backoff(clock.limiter(), send).status_code == 200
    assert calls == ["/api/manga?page=29"] * 2
    assert failed.is_closed and clock.now == pytest.approx(2)


def test_client_errors_are_not_retried():
    calls = []

    def send():
        calls.append(True)
        return httpx.Response(422)

    assert request_with_backoff(Clock().limiter(), send).status_code == 422
    assert len(calls) == 1


def test_connection_failure_retries_without_skipping_the_request():
    clock = Clock()
    calls = []

    def send():
        calls.append(clock.now)
        if len(calls) < 3:
            raise httpx.ReadError("connection closed")
        return httpx.Response(200)

    assert request_with_backoff(clock.limiter(), send).status_code == 200
    assert calls == pytest.approx([0, 2, 6])


def test_transport_retry_limit_preserves_the_final_error():
    calls = []

    def send():
        calls.append(True)
        raise httpx.ReadTimeout("timeout")

    with pytest.raises(httpx.ReadTimeout):
        request_with_backoff(Clock().limiter(), send)
    assert len(calls) == 4


def test_repeated_gateway_failures_pause_without_reducing_the_allowed_rate():
    clock = Clock()
    limiter = clock.limiter(1.6, 100)
    limiter.observe(httpx.Response(502))
    limiter.observe(httpx.Response(502))
    limiter.acquire()
    assert clock.now == pytest.approx(4)
    assert limiter.interval == pytest.approx(1 / 1.6)


@pytest.mark.parametrize("status", [500, 502, 504])
def test_single_busy_response_after_another_gateway_failure_does_not_reduce_rate(status):
    clock = Clock()
    limiter = clock.limiter(1.6, 100)
    limiter.observe(httpx.Response(status))
    limiter.observe(httpx.Response(503))
    limiter.acquire()
    assert clock.now == pytest.approx(4)
    assert limiter.interval == pytest.approx(1 / 1.6)


@pytest.mark.parametrize("status", [200, 404, 502])
def test_only_consecutive_busy_responses_reduce_the_rate(status):
    limiter = Clock().limiter(1.6, 100)
    limiter.observe(httpx.Response(503))
    limiter.observe(httpx.Response(status))
    limiter.observe(httpx.Response(503))
    assert limiter.interval == pytest.approx(1 / 1.6)
    limiter.observe(httpx.Response(503))
    assert limiter.interval == pytest.approx(2 / 1.6)


def test_smaller_server_quota_reduces_both_frequency_and_minute_budget():
    limiter = Clock().limiter(100 / 60, 100)
    limiter.observe(httpx.Response(200, headers={"X-RateLimit-Limit": "50"}))
    assert limiter.per_minute == 50 and limiter.interval == pytest.approx(1.2)


def test_known_minute_quota_waits_without_permanently_reducing_the_working_rate():
    clock = Clock()
    limiter = clock.limiter(1.6, 100)
    limiter.observe(httpx.Response(429, headers={"Retry-After": "20",
                    "X-RateLimit-Limit": "100", "X-RateLimit-Remaining": "0"}))
    limiter.acquire()
    assert clock.now == pytest.approx(20) and limiter.interval == pytest.approx(1 / 1.6)


@pytest.mark.parametrize("cls", [ReMangaPopulation, MangaLibPopulation])
def test_detail_clients_have_separate_sessions_and_share_the_same_limiter(cls):
    client = cls()
    worker = client.detail_client()
    try:
        assert worker.limiter is client.limiter
        assert worker.stopped is client.stopped
        if client.session is not None:
            assert worker.session is not client.session
    finally:
        for item in (client, worker):
            if item.session is not None:
                item.session.close()
