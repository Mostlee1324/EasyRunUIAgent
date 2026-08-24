"""Redis 可靠队列（生产模式）。

ready 与 processing 两条 List，认领用 BLMOVE（原子），认领时间戳存 Hash，
崩溃任务由调度器按时间戳回收。
"""

from __future__ import annotations

import time

from .base import ClaimedItem, QueueError, TaskQueue

READY = "easyrun:queue:ready"
PROCESSING = "easyrun:queue:processing"
TS = "easyrun:queue:ts"


class RedisQueue(TaskQueue):
    def __init__(self, url: str) -> None:
        try:
            from redis.asyncio import Redis  # 可选依赖：pip install -e ".[prod]"
        except ImportError as e:
            raise QueueError(
                "Redis 队列需要 redis 包：pip install -e \".[prod]\""
            ) from e
        self._redis: Redis = Redis.from_url(url, decode_responses=True)

    async def push(self, task_id: str) -> None:
        await self._redis.lpush(READY, task_id)

    async def pop(self, timeout: float) -> ClaimedItem | None:
        item = await self._redis.blmove(READY, PROCESSING, timeout=timeout)
        if item is None:
            return None
        now = time.monotonic()
        await self._redis.hset(TS, item, now)
        return ClaimedItem(task_id=item, claimed_at=now)

    async def ack(self, task_id: str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lrem(PROCESSING, 1, task_id)
            pipe.hdel(TS, task_id)
            await pipe.execute()

    async def requeue(self, task_id: str) -> None:
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lrem(PROCESSING, 1, task_id)
            pipe.lpush(READY, task_id)
            pipe.hdel(TS, task_id)
            await pipe.execute()

    async def stuck(self, older_than_seconds: float) -> list[str]:
        now = time.monotonic()
        items = await self._redis.lrange(PROCESSING, 0, -1)
        ts_map = await self._redis.hgetall(TS)
        recovered = [
            t
            for t in items
            if float(ts_map.get(t, now)) < now - older_than_seconds
        ]
        for t in recovered:
            await self.requeue(t)
        return recovered

    async def pending_count(self) -> int:
        return int(await self._redis.llen(READY) or 0)

    async def close(self) -> None:
        await self._redis.aclose()
