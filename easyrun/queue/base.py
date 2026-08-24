"""队列接口与通用异常。"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field


class QueueError(Exception):
    pass


class QueueClosed(QueueError):
    pass


@dataclass
class ClaimedItem:
    task_id: str
    claimed_at: float = field(default_factory=time.monotonic)


class TaskQueue(abc.ABC):
    """任务队列：元素为 task_id 字符串。

    pop() 返回即视为已认领（进入 processing 状态），ack() 确认完成，
    requeue() 放回就绪队列（用于重试）。未被 ack 的认领项由调度器
    通过 stuck() 回收。
    """

    @abc.abstractmethod
    async def push(self, task_id: str) -> None: ...

    @abc.abstractmethod
    async def pop(self, timeout: float) -> ClaimedItem | None: ...

    @abc.abstractmethod
    async def ack(self, task_id: str) -> None: ...

    @abc.abstractmethod
    async def requeue(self, task_id: str) -> None:
        """processing → ready（重试 / 锁冲突放回）。"""

    @abc.abstractmethod
    async def stuck(self, older_than_seconds: float) -> list[str]:
        """回收认领超过阈值的任务，返回被回收的 task_id 列表（已放回就绪队列）。"""

    @abc.abstractmethod
    async def pending_count(self) -> int: ...

    @abc.abstractmethod
    async def close(self) -> None: ...
