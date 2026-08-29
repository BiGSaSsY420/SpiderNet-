"""Backoff behaviour, with the clock stubbed out."""

import asyncio

import pytest

from app.utils.retry import (
    RetryableAPIClient,
    retry_with_backoff,
    retry_with_backoff_async,
)


@pytest.fixture
def clock(monkeypatch):
    slept = []
    monkeypatch.setattr("app.utils.retry.time.sleep", slept.append)
    return slept


@pytest.fixture
def async_clock(monkeypatch):
    """`retry_with_backoff_async` awaits asyncio.sleep; record the delays instead."""
    slept = []

    async def fake_sleep(delay):
        slept.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return slept


def test_succeeds_without_sleeping(clock):
    @retry_with_backoff(max_retries=3)
    def ok():
        return "fine"

    assert ok() == "fine"
    assert clock == []


def test_retries_then_succeeds(clock):
    calls = []

    @retry_with_backoff(max_retries=3, initial_delay=1.0)
    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("boom")
        return "recovered"

    assert flaky() == "recovered"
    assert len(calls) == 3
    assert len(clock) == 2


def test_raises_the_last_error_after_exhausting_retries(clock):
    @retry_with_backoff(max_retries=2, initial_delay=1.0)
    def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        always_fails()
    assert len(clock) == 2


def test_only_listed_exceptions_are_retried(clock):
    @retry_with_backoff(max_retries=3, exceptions=(KeyError,))
    def wrong_error():
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        wrong_error()
    assert clock == []


def test_on_retry_callback_receives_attempt_numbers(clock):
    seen = []

    @retry_with_backoff(max_retries=2, on_retry=lambda e, n: seen.append(n))
    def fails():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        fails()
    assert seen == [1, 2]


def test_delay_never_exceeds_max_delay(clock):
    """Jitter used to be applied after the clamp, so delays ran to 1.5x max."""
    @retry_with_backoff(max_retries=8, initial_delay=1.0, max_delay=5.0,
                        backoff_factor=3.0, jitter=True)
    def always_fails():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        always_fails()

    assert clock, "expected some sleeps"
    assert max(clock) <= 5.0, f"slept {max(clock)}s, above the 5s ceiling"


def test_client_delay_never_exceeds_max_delay(clock):
    client = RetryableAPIClient(max_retries=8, initial_delay=1.0,
                                max_delay=4.0, backoff_factor=3.0)

    def always_fails():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        client.call_with_retry(always_fails)

    assert max(clock) <= 4.0


def test_batch_stops_at_the_first_failure_when_asked(clock):
    client = RetryableAPIClient(max_retries=0)

    def process(item):
        raise ValueError("rejected")

    with pytest.raises(ValueError):
        client.call_batch_with_retry(["a", "b"], process, continue_on_failure=False)


def test_batch_over_an_empty_list_does_nothing(clock):
    client = RetryableAPIClient(max_retries=0)

    assert client.call_batch_with_retry([], lambda item: item) == ([], [])


def test_client_returns_the_value_once_the_call_recovers(clock):
    client = RetryableAPIClient(max_retries=3, initial_delay=1.0)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise RuntimeError("boom")
        return "recovered"

    assert client.call_with_retry(flaky) == "recovered"
    assert len(clock) == 1


def test_client_passes_arguments_through(clock):
    client = RetryableAPIClient(max_retries=0)

    assert client.call_with_retry(lambda a, b=0: a + b, 1, b=2) == 3


def test_batch_collects_failures_and_continues(clock):
    client = RetryableAPIClient(max_retries=0)

    def process(item):
        if item == "bad":
            raise ValueError("rejected")
        return item.upper()

    results, failures = client.call_batch_with_retry(
        ["a", "bad", "c"], process, continue_on_failure=True
    )
    assert results == ["A", "C"]
    assert len(failures) == 1
    assert failures[0]["index"] == 1
    assert failures[0]["item"] == "bad"


# --- the async decorator, used by the OASIS simulation coroutines ---------

@pytest.mark.asyncio
async def test_async_succeeds_without_sleeping(async_clock):
    @retry_with_backoff_async(max_retries=3)
    async def ok():
        return "fine"

    assert await ok() == "fine"
    assert async_clock == []


@pytest.mark.asyncio
async def test_async_retries_then_succeeds(async_clock):
    calls = []

    @retry_with_backoff_async(max_retries=3, initial_delay=1.0)
    async def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("boom")
        return "recovered"

    assert await flaky() == "recovered"
    assert len(calls) == 3
    assert len(async_clock) == 2


@pytest.mark.asyncio
async def test_async_raises_the_last_error_after_exhausting_retries(async_clock):
    @retry_with_backoff_async(max_retries=2, initial_delay=1.0)
    async def always_fails():
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await always_fails()
    assert len(async_clock) == 2


@pytest.mark.asyncio
async def test_async_only_retries_listed_exceptions(async_clock):
    @retry_with_backoff_async(max_retries=3, exceptions=(KeyError,))
    async def wrong_error():
        raise ValueError("not retryable")

    with pytest.raises(ValueError):
        await wrong_error()
    assert async_clock == []


@pytest.mark.asyncio
async def test_async_on_retry_callback_receives_attempt_numbers(async_clock):
    seen = []

    @retry_with_backoff_async(max_retries=2, on_retry=lambda e, n: seen.append(n))
    async def fails():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await fails()
    assert seen == [1, 2]


@pytest.mark.asyncio
async def test_async_delay_never_exceeds_max_delay(async_clock):
    @retry_with_backoff_async(max_retries=8, initial_delay=1.0, max_delay=5.0,
                              backoff_factor=3.0, jitter=True)
    async def always_fails():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        await always_fails()

    assert async_clock, "expected some sleeps"
    assert max(async_clock) <= 5.0, f"slept {max(async_clock)}s, above the 5s ceiling"


@pytest.mark.asyncio
async def test_async_decorator_preserves_the_wrapped_name():
    @retry_with_backoff_async(max_retries=0)
    async def named_coroutine():
        return None

    assert named_coroutine.__name__ == "named_coroutine"
