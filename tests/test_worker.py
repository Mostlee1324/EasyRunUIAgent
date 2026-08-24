"""Worker 兜底：LLM 异常不能让任务卡在 running。"""

from __future__ import annotations

from easyrun.llm import LLMError
from easyrun.models import TASK_FAILED, TestCase, TestRun, TestTask
from easyrun.queue.memory import MemoryQueue
from easyrun.worker import LockManager, Worker


class BoomLLM:
    async def chat_json(self, messages, **kwargs):
        raise LLMError("未配置 DeepSeek API Key")


async def test_maybe_cure_records_single_action(settings, sf):
    """回归：只执行了 1 个动作（如仅打开页面）的通过用例也应记录固化动作。"""
    from easyrun.agent import AgentOutcome
    from easyrun.models import TestCase

    case = TestCase(name="主页验证", mode="agentic", steps=["打开页面"])
    async with sf() as session:
        session.add(case)
        await session.commit()
        await session.refresh(case)

    worker = Worker("w-cure", settings, sf, MemoryQueue(), LockManager(), BoomLLM())
    outcome = AgentOutcome(status="passed", actions=[
        {"tool": "browser_navigate", "args": {"url": "http://x/"}},
    ])
    async with sf() as session:
        await worker._maybe_cure(session, case, outcome)
        await session.commit()  # _maybe_cure 由调用方统一提交（worker 收口时）
    async with sf() as session:
        c = await session.get(TestCase, case.id)
        assert len(c.cured_actions) == 1
        assert c.cured_actions[0]["tool"] == "browser_navigate"


def test_worker_shares_cancel_registry_identity(settings, sf):
    """回归：注册表必须是同一对象（空 set 的 or 陷阱曾导致取消信号丢失）。"""
    registry: set = set()
    w = Worker("w", settings, sf, MemoryQueue(), LockManager(), BoomLLM(), cancel_registry=registry)
    assert w._cancel_registry is registry
    registry.add("t-x")
    assert "t-x" in w._cancel_registry


async def test_worker_lock_timeout_fails_instead_of_requeue(settings, sf):
    """单次执行策略：等不到资源锁直接失败，不回队列重跑。"""
    case = TestCase(name="锁冲突用例", resource_key="shared-account")
    async with sf() as session:
        session.add(case)
        await session.flush()
        run = TestRun(case_ids=[case.id], status="running")
        session.add(run)
        await session.flush()
        task = TestTask(run_id=run.id, case_id=case.id, status="queued", lock_key="shared-account")
        session.add(task)
        await session.commit()
        tid = task.id

    settings.lock_wait_seconds = 1  # 快速触发超时
    queue = MemoryQueue()
    await queue.push(tid)
    item = await queue.pop(timeout=0.1)
    worker = Worker("w-lock", settings, sf, queue, LockManager(), BoomLLM())

    # 占用锁
    lock = worker._locks.get("shared-account")
    await lock.acquire()
    await worker.process(item.task_id)
    lock.release()

    async with sf() as session:
        t = await session.get(TestTask, tid)
        assert t.status == "failed"
        assert "资源锁" in t.error
    assert await queue.pop(timeout=0.1) is None  # 未放回队列，不会重跑


async def test_worker_marks_failed_on_llm_error(settings, sf):
    case = TestCase(name="用例X", steps=["打开页面"])
    async with sf() as session:
        session.add(case)
        await session.flush()
        run = TestRun(case_ids=[case.id], status="running")
        session.add(run)
        await session.flush()
        task = TestTask(run_id=run.id, case_id=case.id, status="queued")
        session.add(task)
        await session.commit()
        tid = task.id

    queue = MemoryQueue()
    await queue.push(tid)
    item = await queue.pop(timeout=0.1)  # 模拟 run_forever 的认领
    assert item is not None and item.task_id == tid
    worker = Worker("w-test", settings, sf, queue, LockManager(), BoomLLM())
    await worker.process(item.task_id)

    async with sf() as session:
        t = await session.get(TestTask, tid)
        assert t.status == TASK_FAILED
        assert "DeepSeek" in t.error or "LLMError" in t.error
    # 队列项已被 ack，不会残留 processing
    assert await queue.pop(timeout=0.1) is None
