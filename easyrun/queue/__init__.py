"""任务队列：统一接口，两种实现。

- MemoryQueue：进程内实现（开发零依赖）
- RedisQueue：基于 Redis List 的可靠队列（生产），
  采用 BLMOVE 的 ready→processing 两段式消费，崩溃任务由调度器超时回收。
"""

from __future__ import annotations

from easyrun.config import Settings

from .base import TaskQueue
from .memory import MemoryQueue
from .redisq import RedisQueue

__all__ = ["TaskQueue", "MemoryQueue", "RedisQueue", "get_queue"]


def get_queue(settings: Settings) -> TaskQueue:
    if settings.use_memory_queue:
        return MemoryQueue()
    return RedisQueue(settings.redis_url)
