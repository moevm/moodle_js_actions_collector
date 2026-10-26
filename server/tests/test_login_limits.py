import asyncio
from threading import Event

import pytest

from src.core.login_limits import LoginLimiter, LoginLimits, LoginRateLimited
from src.core.password_workers import PasswordWorkers


class Clock:
    now = 0.0

    def __call__(self):
        return self.now


def test_account_budget_is_shared_across_sources_and_email_case_and_expires():
    clock = Clock()
    limiter = LoginLimiter(clock=clock)
    for index in range(5):
        email = "Admin@example.com" if index % 2 else "admin@EXAMPLE.com"
        with limiter.check(f"source-{index}", email) as check:
            check.failed = True
    with pytest.raises(LoginRateLimited) as error:
        with limiter.check("new-source", "ADMIN@example.com"):
            pytest.fail("A sixth attempt must not reach password verification")
    assert error.value.retry_after == 60
    clock.now = 59.5
    with pytest.raises(LoginRateLimited) as error:
        with limiter.check("new-source", "admin@example.com"):
            pass
    assert error.value.retry_after == 1
    clock.now = 60
    with limiter.check("new-source", "admin@example.com"):
        pass
    assert limiter.active_checks == 0
    assert not limiter._accounts


def test_successful_logins_do_not_spend_failure_budget():
    limiter = LoginLimiter()
    for _ in range(20):
        with limiter.check("same-source", "admin@example.com"):
            pass
    assert not limiter._accounts
    assert limiter.active_checks == 0


@pytest.mark.parametrize("scope", ["source", "global"])
def test_attempt_limits_apply_when_email_or_source_rotates(scope):
    limits = LoginLimits(source_attempts=2 if scope == "source" else 100,
                         global_attempts=2 if scope == "global" else 100)
    limiter = LoginLimiter(limits)
    for index in range(2):
        with limiter.check("same" if scope == "source" else f"source-{index}", f"user-{index}"):
            pass
    with pytest.raises(LoginRateLimited):
        with limiter.check("same" if scope == "source" else "another", "new-user"):
            pass


def test_active_attempts_reserve_the_remaining_account_failure_budget():
    limiter = LoginLimiter(LoginLimits(account_failures=1))
    with limiter.check("first", "account"):
        with pytest.raises(LoginRateLimited):
            with limiter.check("second", "account"):
                pass
    with limiter.check("second", "account"):
        pass


def test_concurrency_rejects_instead_of_queuing_and_releases_on_errors():
    limiter = LoginLimiter()
    with pytest.raises(RuntimeError):
        with limiter.check("source", "first"):
            with limiter.check("source", "second"):
                with pytest.raises(LoginRateLimited) as error:
                    with limiter.check("source", "third"):
                        pass
                assert error.value.retry_after == 1
                assert limiter.active_checks == 2
            raise RuntimeError("Database failed")
    assert limiter.active_checks == 0
    assert not limiter._accounts


def test_identity_cache_is_bounded_and_does_not_evict_live_failure_budgets():
    clock = Clock()
    limiter = LoginLimiter(LoginLimits(maximum_keys=2), clock=clock)
    for index in range(2):
        with limiter.check("source", f"user-{index}") as check:
            check.failed = True
    for index in range(100):
        with pytest.raises(LoginRateLimited):
            with limiter.check("source", f"rotated-user-{index}"):
                pass
    assert len(limiter._accounts) == 2
    assert all(isinstance(key, bytes) and len(key) == 32 for key in limiter._accounts)
    clock.now = 60
    with limiter.check("source", "fresh-user"):
        pass
    assert not limiter._accounts


def test_source_cache_is_bounded_and_expires():
    clock = Clock()
    limiter = LoginLimiter(LoginLimits(maximum_keys=2), clock=clock)
    for index in range(2):
        with limiter.check(f"source-{index}", "account"):
            pass
    with pytest.raises(LoginRateLimited):
        with limiter.check("third-source", "account"):
            pass
    assert len(limiter._sources) == 2
    clock.now = 60
    with limiter.check("third-source", "account"):
        pass
    assert list(limiter._sources) == ["third-source"]


@pytest.mark.asyncio
async def test_cancelled_http_waiter_cannot_release_a_running_password_thread():
    workers = PasswordWorkers(maximum=1)
    started, release, finished = Event(), Event(), Event()

    def expensive_check():
        started.set()
        try:
            assert release.wait(5)
        finally:
            finished.set()

    task = asyncio.create_task(workers.run(expensive_check))
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not finished.is_set()
        with pytest.raises(LoginRateLimited):
            await workers.run(lambda: "must not enter an executor queue")
        release.set()
        async with asyncio.timeout(2):
            while True:
                try:
                    assert await workers.run(lambda: "recovered") == "recovered"
                    break
                except LoginRateLimited:
                    await asyncio.sleep(0.005)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        workers.close()
    assert finished.is_set()


@pytest.mark.asyncio
async def test_password_worker_errors_release_the_slot():
    workers = PasswordWorkers(maximum=1)

    def broken():
        raise ValueError("bad input")

    try:
        with pytest.raises(ValueError):
            await workers.run(broken)
        assert await workers.run(lambda: 42) == 42
    finally:
        workers.close()
