"""进程内队列（开发模式）。"""

from __future__ import annotations

import asyncio
import time

from .base import ClaimedItem, QueueClosed, TaskQueue


class MemoryQueue(TaskQueue):
    def __init__(self) -> None:
        self._ready: asyncio.Queue[str] = asyncio.Queue()
        self._processing: dict[str, float] = {}
        self._closed = False

    async def push(self, task_id: str) -> None:
        if self._closed:
            raise QueueClosed("queue closed")
        await self._ready.put(task_id)

    async def pop(self, timeout: float) -> ClaimedItem | None:
        try:
            task_id = await asyncio.wait_for(self._ready.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        self._processing[task_id] = time.monotonic()
        return ClaimedItem(task_id=task_id, claimed_at=self._processing[task_id])

    async def ack(self, task_id: str) -> None:
        self._processing.pop(task_id, None)

    async def requeue(self, task_id: str) -> None:
        self._processing.pop(task_id, None)
        if not self._closed:
            await self._ready.put(task_id)

    async def stuck(self, older_than_seconds: float) -> list[str]:
        now = time.monotonic()
        recovered = [
            t for t, at in self._processing.items() if now - at > older_than_seconds
        ]
        for t in recovered:
            await self.requeue(t)
        return recovered

    async def pending_count(self) -> int:
        return self._ready.qsize()

    async def close(self) -> None:
        self._closed = True
