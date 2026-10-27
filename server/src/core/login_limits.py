"""Bounded login admission for the application's single API process."""

from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class LoginLimits:
    window_seconds: float = 60
    account_failures: int = 5
    source_attempts: int = 60
    global_attempts: int = 120
    concurrent_checks: int = 2
    maximum_keys: int = 4096

    def __post_init__(self) -> None:
        if min(self.window_seconds, self.account_failures, self.source_attempts,
               self.global_attempts, self.concurrent_checks, self.maximum_keys) <= 0:
            raise ValueError("Login limits must be positive")


class LoginRateLimited(Exception):
    def __init__(self, retry_after: float) -> None:
        super().__init__("Too many sign-in attempts; retry later")
        self.retry_after = max(1, math.ceil(retry_after))


@dataclass(slots=True)
class LoginCheck:
    failed: bool = False


@dataclass(slots=True)
class _Account:
    failures: deque[float] = field(default_factory=deque)
    active: int = 0


class LoginLimiter:
    def __init__(
        self, limits: LoginLimits | None = None, *, clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.limits = limits or LoginLimits()
        self.clock = clock
        self.active_checks = 0
        self._global: deque[float] = deque()
        self._sources: dict[str, deque[float]] = {}
        self._accounts: dict[bytes, _Account] = {}
        self._key = secrets.token_bytes(32)

    def _expire(self, values: deque[float], now: float) -> None:
        while values and values[0] <= now - self.limits.window_seconds:
            values.popleft()

    def _prune(self, now: float) -> None:
        self._expire(self._global, now)
        for source, attempts in list(self._sources.items()):
            self._expire(attempts, now)
            if not attempts:
                del self._sources[source]
        for key, account in list(self._accounts.items()):
            self._expire(account.failures, now)
            if not account.failures and not account.active:
                del self._accounts[key]

    def _wait(self, values: deque[float], now: float) -> float:
        return values[0] + self.limits.window_seconds - now if values else 1

    @contextmanager
    def check(self, source: str, email: str) -> Iterator[LoginCheck]:
        # Admission has no await: counters are atomic within this event loop.
        # Do not trust client-supplied forwarding headers to choose `source`.
        now = self.clock()
        self._prune(now)
        key = hmac.digest(self._key, email.casefold().encode("utf-8"), hashlib.sha256)
        attempts = self._sources.get(source)
        account = self._accounts.get(key)
        if len(self._global) >= self.limits.global_attempts:
            raise LoginRateLimited(self._wait(self._global, now))
        if attempts is not None and len(attempts) >= self.limits.source_attempts:
            raise LoginRateLimited(self._wait(attempts, now))
        if account is not None and len(account.failures) + account.active >= self.limits.account_failures:
            raise LoginRateLimited(self._wait(account.failures, now))
        if self.active_checks >= self.limits.concurrent_checks:
            raise LoginRateLimited(1)
        if ((account is None and len(self._accounts) >= self.limits.maximum_keys)
                or (attempts is None and len(self._sources) >= self.limits.maximum_keys)):
            # Never evict a live failure budget to make room for rotating names.
            raise LoginRateLimited(self.limits.window_seconds)

        if attempts is None:
            attempts = self._sources[source] = deque()
        if account is None:
            account = self._accounts[key] = _Account()
        self._global.append(now)
        attempts.append(now)
        account.active += 1
        self.active_checks += 1
        check = LoginCheck()
        try:
            yield check
        finally:
            self.active_checks -= 1
            account.active -= 1
            if check.failed:
                account.failures.append(self.clock())
            if not account.failures and not account.active:
                del self._accounts[key]
