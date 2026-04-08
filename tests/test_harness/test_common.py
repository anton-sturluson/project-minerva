"""Tests for shared harness command helpers."""

from __future__ import annotations

import pytest

from harness.commands.common import retry_call, should_retry_network_error


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def test_retry_call_retries_on_429() -> None:
    attempts: list[int] = []
    sleeps: list[float] = []

    def flaky_operation() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise _StatusError(429)
        return "ok"

    result = retry_call(
        flaky_operation,
        should_retry=should_retry_network_error,
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert len(attempts) == 3
    assert sleeps == [1.0, 2.0]


def test_retry_call_gives_up_on_401() -> None:
    attempts: list[int] = []

    def unauthorized_operation() -> str:
        attempts.append(1)
        raise _StatusError(401)

    with pytest.raises(_StatusError):
        retry_call(unauthorized_operation, should_retry=should_retry_network_error, sleep=lambda _: None)

    assert len(attempts) == 1
