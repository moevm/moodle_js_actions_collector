"""Bound actual password CPU work, including work whose HTTP client left."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Any, TypeVar

from src.core.login_limits import LoginRateLimited


T = TypeVar("T")


class PasswordWorkers:
    def __init__(self, maximum: int = 2) -> None:
        self._slots = BoundedSemaphore(maximum)
        self._executor = ThreadPoolExecutor(max_workers=maximum, thread_name_prefix="collector-password")

    async def run(self, work: Callable[..., T], *args: Any) -> T:
        if not self._slots.acquire(blocking=False):
            raise LoginRateLimited(1)
        try:
            future = self._executor.submit(work, *args)
        except BaseException:
            self._slots.release()
            raise
        # Cancellation of the awaiting HTTP task cannot release a slot while
        # its thread is still hashing. The future owns that slot until done.
        future.add_done_callback(lambda completed: self._slots.release())
        return await asyncio.wrap_future(future)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)


password_workers = PasswordWorkers()
