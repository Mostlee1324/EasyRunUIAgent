"""调度器：拆解、重试、watchdog、quarantine、run 收口。"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from easyrun.models import (
    RUN_PARTIAL,
    RUN_PASSED,
    TASK_FAILED,
    TASK_QUEUED,
    TASK_QUARANTINED,
    TASK_RETRYING,
    TASK_RUNNING,
    TestCase,
    TestPlan,
    TestRun,
    TestTask,
    utcnow,
)
from easyrun.orchestrator import Orchestrator
from easyrun.queue.memory import MemoryQueue


@pytest.fixture
def orch(settings, sf):
    return Orchestrator(settings, sf, MemoryQueue())


async def make_case(sf, name="用例A", **kw):
    case = TestCase(name=name, steps=["打开页面"], **kw)
    async with sf() as session:
        session.add(case)
        await session.commit()
        await session.refresh(case)
        return case


async def test_submit_case_creates_run_and_task(orch, sf):
    case = await make_case(sf, resource_key="acc-1")
    run_id = await orch.submit_case(case.id, target_url="http://x/")
    item = await orch._queue.pop(timeout=0.1)
    assert item is not None
    async with sf() as session:
        task = (await session.execute(select(TestTask))).scalars().first()
        assert task.run_id == run_id and task.case_id == case.id
        assert task.lock_key == "acc-1"
        run = await session.get(TestRun, run_id)
        assert run.status == "running"


async def test_submit_plan_creates_multiple_tasks(orch, sf):
    c1 = await make_case(sf, name="用例1")
    c2 = await make_case(sf, name="用例2")
    plan = TestPlan(name="冒烟", case_ids=[c1.id, c2.id])
    async with sf() as session:
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
    run_id = await orch.submit_plan(plan.id, target_url="http://x/")
    popped = []
    for _ in range(2):
        item = await orch._queue.pop(timeout=0.1)
        if item:
            popped.append(item.task_id)
    assert len(popped) == 2
    async with sf() as session:
        run = await session.get(TestRun, run_id)
        assert len(run.case_ids) == 2


async def test_submit_missing_case_raises(orch):
    with pytest.raises(ValueError, match="不存在"):
        await orch.submit_case("nope")


async def test_retry_failed_task(orch, sf):
    orch._settings.max_attempts = 2  # 默认只执行一次；重试机制仍可通过配置启用
    case = await make_case(sf)
    async with sf() as session:
        task = TestTask(run_id="r", case_id=case.id, status=TASK_FAILED, attempt=1, error="boom")
        session.add(task)
        await session.commit()
        tid = task.id
    await orch._retry_failed()
    item = await orch._queue.pop(timeout=0.1)
    assert item and item.task_id == tid
    async with sf() as session:
        t = await session.get(TestTask, tid)
        assert t.status == TASK_RETRYING and t.attempt == 2


async def test_quarantine_after_consecutive_failures(orch, sf):
    case = await make_case(sf)
    async with sf() as session:
        for i in range(2):  # 历史连续失败
            session.add(TestTask(run_id="r", case_id=case.id, status=TASK_FAILED, attempt=2, error="x"))
        task = TestTask(run_id="r", case_id=case.id, status=TASK_FAILED, attempt=2, error="x")
        session.add(task)
        await session.commit()
        tid = task.id
    await orch._quarantine()
    async with sf() as session:
        t = await session.get(TestTask, tid)
        assert t.status == TASK_QUARANTINED


async def test_watchdog_marks_timeout(orch, sf):
    case = await make_case(sf)
    async with sf() as session:
        task = TestTask(
            run_id="r", case_id=case.id, status=TASK_RUNNING,
            updated_at=utcnow() - timedelta(hours=1),
        )
        session.add(task)
        await session.commit()
        tid = task.id
    await orch._watchdog()
    async with sf() as session:
        t = await session.get(TestTask, tid)
        assert t.status == TASK_FAILED and "超时" in t.error


async def test_rerun_failed_creates_new_run(orch, sf):
    c1 = await make_case(sf, name="通过用例")
    c2 = await make_case(sf, name="失败用例")
    async with sf() as session:
        source = TestRun(case_ids=[c1.id, c2.id], target_url="http://x/", env="e1", status="failed")
        session.add(source)
        await session.flush()
        session.add(TestTask(run_id=source.id, case_id=c1.id, case_name="通过用例", status="passed"))
        session.add(TestTask(run_id=source.id, case_id=c2.id, case_name="失败用例", status="failed", error="boom"))
        await session.commit()
        sid = source.id

    new_id = await orch.rerun_failed(sid)
    item = await orch._queue.pop(timeout=0.1)
    assert item is not None
    async with sf() as session:
        new_run = await session.get(TestRun, new_id)
        assert new_run.target_url == "http://x/" and new_run.env == "e1"
        assert new_run.case_ids == [c2.id]  # 只有失败用例
        tasks = (await session.execute(select(TestTask).where(TestTask.run_id == new_id))).scalars().all()
        assert len(tasks) == 1 and tasks[0].case_id == c2.id


async def test_rerun_failed_rejects_when_none_failed(orch, sf):
    case = await make_case(sf)
    async with sf() as session:
        run = TestRun(case_ids=[case.id], status="passed")
        session.add(run)
        await session.flush()
        session.add(TestTask(run_id=run.id, case_id=case.id, status="passed"))
        await session.commit()
        rid = run.id
    with pytest.raises(ValueError, match="没有失败"):
        await orch.rerun_failed(rid)


async def test_cancel_run_skips_queued_and_registers_running(orch, sf):
    case = await make_case(sf)
    async with sf() as session:
        run = TestRun(case_ids=[case.id], status="running")
        session.add(run)
        await session.flush()
        t_queued = TestTask(run_id=run.id, case_id=case.id, status=TASK_QUEUED)
        t_running = TestTask(run_id=run.id, case_id=case.id, status="running")
        session.add(t_queued)
        session.add(t_running)
        await session.commit()
        run_id, qid, rid = run.id, t_queued.id, t_running.id

    registry: set = set()
    assert await orch.cancel_run(run_id, registry) is True
    assert rid in registry  # 执行中任务进入取消注册表
    async with sf() as session:
        t = await session.get(TestTask, qid)
        assert t.status == "skipped" and "取消" in t.error
    # 已终结的 run 拒绝重复取消
    async with sf() as session:
        run = await session.get(TestRun, run_id)
        run.status = "passed"
        await session.commit()
    assert await orch.cancel_run(run_id, registry) is False


async def test_complete_run_all_skipped_becomes_cancelled(orch, sf, monkeypatch):
    async def noop(*a, **k):
        return None

    monkeypatch.setattr(orch, "_trigger_analysis", noop)
    case = await make_case(sf)
    async with sf() as session:
        run = TestRun(case_ids=[case.id], status="running")
        session.add(run)
        await session.flush()
        session.add(TestTask(run_id=run.id, case_id=case.id, status="skipped", error="用户取消"))
        await session.commit()
        run_id = run.id
    await orch._complete_runs()
    async with sf() as session:
        run = await session.get(TestRun, run_id)
        assert run.status == "cancelled"


async def test_complete_run_passed_and_partial(orch, sf, monkeypatch):
    async def noop(*a, **k):
        return None

    monkeypatch.setattr(orch, "_trigger_analysis", noop)

    c1 = await make_case(sf, name="P1")
    c2 = await make_case(sf, name="F1")
    async with sf() as session:
        run1 = TestRun(case_ids=[c1.id], status="running")
        run2 = TestRun(case_ids=[c1.id, c2.id], status="running")
        session.add(run1)
        session.add(run2)
        await session.flush()
        session.add(TestTask(run_id=run1.id, case_id=c1.id, status="passed"))
        session.add(TestTask(run_id=run2.id, case_id=c1.id, status="passed"))
        session.add(TestTask(run_id=run2.id, case_id=c2.id, status="failed", error="x"))
        await session.commit()
        r1, r2 = run1.id, run2.id

    await orch._complete_runs()
    async with sf() as session:
        run1 = await session.get(TestRun, r1)
        run2 = await session.get(TestRun, r2)
        assert run1.status == RUN_PASSED and run1.stats["passed"] == 1
        assert run2.status == RUN_PARTIAL and run2.stats["failed"] == 1
