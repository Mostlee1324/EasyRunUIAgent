"""任务队列：内存实现全流程 + 崩溃回收。"""

from __future__ import annotations

import asyncio

import pytest

from easyrun.queue.memory import MemoryQueue


async def test_push_pop_ack():
    q = MemoryQueue()
    await q.push("t1")
    item = await q.pop(timeout=0.1)
    assert item is not None and item.task_id == "t1"
    await q.ack("t1")
    assert await q.pop(timeout=0.1) is None


async def test_requeue():
    q = MemoryQueue()
    await q.push("t1")
    item = await q.pop(timeout=0.1)
    assert item
    await q.requeue("t1")
    item2 = await q.pop(timeout=0.1)
    assert item2 and item2.task_id == "t1"


async def test_pop_timeout_returns_none():
    q = MemoryQueue()
    assert await q.pop(timeout=0.05) is None


async def test_stuck_recovery():
    q = MemoryQueue()
    await q.push("t1")
    await q.pop(timeout=0.1)  # 认领但从不 ack（模拟 Worker 崩溃）
    await asyncio.sleep(0.15)
    recovered = await q.stuck(older_than_seconds=0.1)
    assert recovered == ["t1"]
    item = await q.pop(timeout=0.1)
    assert item and item.task_id == "t1"


async def test_close_rejects_push():
    q = MemoryQueue()
    await q.close()
    with pytest.raises(Exception):
        await q.push("t1")
