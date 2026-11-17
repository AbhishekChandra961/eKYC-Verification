"""Retries with exponential backoff, and the decision to give up (-> dead-letter queue).

A transient error (S3 or Kafka briefly unreachable, an object not visible yet) may succeed on a second try, so
the work is repeated up to max_attempts times, waiting base_delay, base_delay * factor, ... in between. A
PermanentError (e.g. an event that does not match its schema) is not retried. When the attempts are used up, or
the error is permanent, the caller publishes the original event to kyc.dlq with the error.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")
log = logging.getLogger(__name__)


class PermanentError(Exception):
    """An error that retrying cannot fix: the event goes to the dead-letter queue at once."""


class RetriesExhausted(Exception):
    def __init__(self, last_error: BaseException, attempts: int):
        super().__init__(f"{type(last_error).__name__}: {last_error}")
        self.last_error, self.attempts = last_error, attempts


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5  # seconds before the 2nd attempt
    factor: float = 2.0  # each further wait is this many times longer (0.5 s, 1 s, ...)

    def delay(self, attempt: int) -> float:
        """Wait after the `attempt`-th failed attempt (1-based)."""
        return self.base_delay * self.factor ** (attempt - 1)


def run_with_retry(work: Callable[[], T], policy: RetryPolicy = RetryPolicy(),
                   sleep: Callable[[float], None] = time.sleep) -> tuple[T, int]:
    """Run `work` until it succeeds; return (its result, attempts used). Raises RetriesExhausted after
    policy.max_attempts failures, or at once for a PermanentError (attempts = 1)."""
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return work(), attempt
        except PermanentError as exc:
            raise RetriesExhausted(exc, attempt) from exc
        except Exception as exc:  # noqa: BLE001 - any other error counts as transient
            if attempt == policy.max_attempts:
                raise RetriesExhausted(exc, attempt) from exc
            wait = policy.delay(attempt)
            log.warning("attempt %d/%d failed (%s: %s); retrying in %.1f s", attempt, policy.max_attempts,
                        type(exc).__name__, exc, wait)
            sleep(wait)
    raise AssertionError("unreachable")
