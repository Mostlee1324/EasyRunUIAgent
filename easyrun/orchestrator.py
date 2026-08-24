"""调度器（Master）：计划拆解、重试、watchdog、quarantine、run 完成判定。

纯确定性代码，不含 LLM（设计文档 §03 决策）。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from easyrun.config import Settings
from easyrun.models import (
    RUN_CANCELLED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_PASSED,
    RUN_RUNNING,
    RUN_TERMINAL,
    TASK_ACTIVE,
    TASK_FAILED,
    TASK_PASSED,
    TASK_QUARANTINED,
    TASK_QUEUED,
    TASK_RETRYING,
    TASK_SKIPPED,
    TASK_TERMINAL,
    AgentSession,
    StepEvent,
    TestCase,
    TestPlan,
    TestRun,
    TestTask,
    utcnow,
)
from easyrun.queue.base import TaskQueue

logger = logging.getLogger("easyrun.orchestrator")


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        queue: TaskQueue,
    ) -> None:
        self._settings = settings
        self._sf = session_factory
        self._queue = queue
        self._stopping = False
        # task_id -> 失败分析协程（避免重复触发）
        self._analyzed: set[str] = set()
        # 执行策略快照（每 tick 刷新一次；None = 未刷新，使用时兜底现查）
        self._policy = None

    # ---- 提交 ----

    async def submit_case(self, case_id: str, target_url: str = "", env: str = "") -> str:
        async with self._sf() as session:
            case = await session.get(TestCase, case_id)
            if case is None:
                raise ValueError(f"用例不存在: {case_id}")
            # 优先级：运行时填写 > 用例默认网址 > 平台默认目标地址
            if not target_url:
                target_url = case.target_url or await self._platform_default_url()
            run = TestRun(case_ids=[case_id], target_url=target_url, env=env, status=RUN_RUNNING)
            session.add(run)
            await session.flush()
            task = TestTask(
                run_id=run.id, case_id=case_id, case_name=case.name,
                status=TASK_QUEUED, lock_key=case.resource_key,
            )
            session.add(task)
            await session.commit()
            task_id = task.id
            run_id = run.id
        await self._queue.push(task_id)
        return run_id

    async def _platform_default_url(self) -> str:
        from easyrun.platform_settings import get_default_target_url

        return await get_default_target_url(self._sf)

    async def _execution_policy(self):
        from easyrun.execution_policy import get_execution_policy

        return await get_execution_policy(self._sf, self._settings)

    async def submit_plan(self, plan_id: str, target_url: str = "", env: str = "") -> str:
        async with self._sf() as session:
            plan = await session.get(TestPlan, plan_id)
            if plan is None:
                raise ValueError(f"计划不存在: {plan_id}")
            if not plan.case_ids:
                raise ValueError("计划中没有用例")
            # 运行时未填写 → 回落平台默认目标地址（单用例级回落在 Worker 按用例再兜底）
            run = TestRun(
                plan_id=plan_id, case_ids=list(plan.case_ids),
                target_url=target_url or await self._platform_default_url(),
                env=env, status=RUN_RUNNING,
            )
            session.add(run)
            await session.flush()
            task_ids: list[str] = []
            for cid in plan.case_ids:
                case = await session.get(TestCase, cid)
                if case is None:
                    logger.warning("计划 %s 中的用例 %s 不存在，跳过", plan_id, cid)
                    continue
                task = TestTask(
                    run_id=run.id, case_id=cid, case_name=case.name,
                    status=TASK_QUEUED, lock_key=case.resource_key,
                )
                session.add(task)
                await session.flush()
                task_ids.append(task.id)
            await session.commit()
        for tid in task_ids:
            await self._queue.push(tid)
        return run.id

    # ---- 重跑失败用例 ----

    async def rerun_failed(self, run_id: str) -> str:
        """把源 run 中失败/隔离的用例组成新的 run（手动重跑入口）。"""
        async with self._sf() as session:
            source = await session.get(TestRun, run_id)
            if source is None:
                raise ValueError(f"执行不存在: {run_id}")
            rows = await session.execute(
                select(TestTask).where(
                    TestTask.run_id == run_id,
                    TestTask.status.in_([TASK_FAILED, TASK_QUARANTINED]),
                ).order_by(TestTask.created_at)
            )
            failed_tasks = list(rows.scalars())
            if not failed_tasks:
                raise ValueError("该执行没有失败的用例")
            new_run = TestRun(
                plan_id=source.plan_id,
                case_ids=[t.case_id for t in failed_tasks],
                target_url=source.target_url,
                env=source.env,
                status=RUN_RUNNING,
            )
            session.add(new_run)
            await session.flush()
            task_ids: list[str] = []
            for t in failed_tasks:
                task = TestTask(
                    run_id=new_run.id, case_id=t.case_id, case_name=t.case_name,
                    status=TASK_QUEUED, lock_key=t.lock_key,
                )
                session.add(task)
                await session.flush()
                task_ids.append(task.id)
            await session.commit()
        for tid in task_ids:
            await self._queue.push(tid)
        logger.info("重跑失败用例：run %s → 新 run %s（%s 个用例）", run_id, new_run.id, len(task_ids))
        return new_run.id

    # ---- 取消 ----

    async def cancel_run(self, run_id: str, cancel_registry: set) -> bool:
        """取消一次执行：排队中的任务直接跳过，执行中的任务在下一步停止。

        执行中任务同时写入两条取消信号：
        1. cancel_registry（同进程 Worker 下一步立即停止，进程内共享集合）；
        2. DB 状态置为 skipped（跨进程信号：多机/多容器部署下 Worker 每步查库感知，
           收口时据此保持 skipped 而不是覆盖成 failed）。
        """
        async with self._sf() as session:
            run = await session.get(TestRun, run_id)
            if run is None or run.status in RUN_TERMINAL:
                return False
            rows = await session.execute(
                select(TestTask).where(TestTask.run_id == run_id)
            )
            task_list = list(rows.scalars())
            for t in task_list:
                if t.status in (TASK_QUEUED, TASK_RETRYING):
                    t.status = TASK_SKIPPED
                    t.error = "用户取消"
                    t.updated_at = utcnow()
                elif t.status == "running":
                    cancel_registry.add(t.id)
                    t.status = TASK_SKIPPED  # 跨进程取消信号：Worker 每步查库感知
                    t.error = "用户取消"
                    t.updated_at = utcnow()
            await session.commit()
        logger.info("run %s 已请求取消（排队 %s 个直接跳过，执行中 %s 个逐步停止）",
                    run_id,
                    sum(1 for t in task_list if t.status == TASK_SKIPPED),
                    sum(1 for t in task_list if t.status == "running"))
        return True

    # ---- 调度循环 ----

    async def run_forever(self) -> None:
        logger.info("调度器启动（间隔 2s）")
        while not self._stopping:
            try:
                await self._tick()
            except Exception:
                logger.exception("调度器 tick 异常")
            await asyncio.sleep(2)

    def stop(self) -> None:
        self._stopping = True

    async def _tick(self) -> None:
        self._policy = await self._execution_policy()  # 每 tick 重读执行策略（DB > env 默认）
        await self._recover_stuck_queue_items()
        await self._watchdog()
        await self._retry_failed()
        await self._quarantine()
        await self._complete_runs()

    async def _recover_stuck_queue_items(self) -> None:
        """队列中认领超时的任务（Worker 崩溃）放回就绪。"""
        recovered = await self._queue.stuck(
            older_than_seconds=self._settings.task_timeout_seconds
        )
        if recovered:
            async with self._sf() as session:
                await session.execute(
                    update(TestTask)
                    .where(TestTask.id.in_(recovered))
                    .values(status=TASK_QUEUED, updated_at=utcnow())
                )
                await session.commit()
            logger.info("回收崩溃任务 %s 个", len(recovered))

    async def _watchdog(self) -> None:
        """执行中的任务超过 2 倍时限 → 判定超时失败。"""
        limit = utcnow() - timedelta(seconds=self._settings.task_timeout_seconds * 2)
        async with self._sf() as session:
            rows = await session.execute(
                select(TestTask).where(TestTask.status == "running", TestTask.updated_at < limit)
            )
            for task in rows.scalars():
                task.status = TASK_FAILED
                task.error = f"执行超时（>{self._settings.task_timeout_seconds * 2}s，可能 Agent 卡死）"
                task.finished_at = utcnow()
                task.updated_at = utcnow()
                await self._queue.ack(task.id)
            await session.commit()

    async def _retry_failed(self) -> None:
        """失败且未达重试上限的任务 → retrying 并重新入队。"""
        policy = self._policy or await self._execution_policy()
        async with self._sf() as session:
            rows = await session.execute(
                select(TestTask).where(
                    TestTask.status == TASK_FAILED,
                    TestTask.attempt < policy.max_attempts,
                )
            )
            retry: list[str] = []
            for task in rows.scalars():
                task.status = TASK_RETRYING
                task.attempt += 1
                task.updated_at = utcnow()
                retry.append(task.id)
            await session.commit()
        for tid in retry:
            await self._queue.push(tid)
        if retry:
            logger.info("重试任务 %s 个", len(retry))

    async def _quarantine(self) -> None:
        """达重试上限的失败任务：按该用例连续失败次数决定隔离。"""
        policy = self._policy or await self._execution_policy()
        async with self._sf() as session:
            rows = await session.execute(
                select(TestTask).where(
                    TestTask.status == TASK_FAILED,
                    TestTask.attempt >= policy.max_attempts,
                )
            )
            for task in rows.scalars():
                history = await session.execute(
                    select(TestTask.status)
                    .where(TestTask.case_id == task.case_id, TestTask.id != task.id)
                    .order_by(TestTask.created_at.desc())
                    .limit(10)
                )
                recent = [h for h in history.scalars()]
                consecutive = 1
                for status in recent:
                    if status in (TASK_FAILED, TASK_QUARANTINED):
                        consecutive += 1
                    else:
                        break
                if consecutive >= self._settings.quarantine_threshold:
                    task.status = TASK_QUARANTINED
                    task.error = f"连续失败 {consecutive} 次，已隔离（quarantine）"
                    task.updated_at = utcnow()
            await session.commit()

    async def _complete_runs(self) -> None:
        """所有任务终结 → run 收口 + 统计 + 触发失败归因。"""
        async with self._sf() as session:
            runs = await session.execute(
                select(TestRun).where(TestRun.status == RUN_RUNNING)
            )
            for run in runs.scalars():
                tasks = await session.execute(
                    select(TestTask).where(TestTask.run_id == run.id)
                )
                task_list = list(tasks.scalars())
                if not task_list or any(t.status in TASK_ACTIVE for t in task_list):
                    continue
                passed = sum(1 for t in task_list if t.status == TASK_PASSED)
                failed = sum(1 for t in task_list if t.status == TASK_FAILED)
                quarantined = sum(1 for t in task_list if t.status == TASK_QUARANTINED)
                skipped = sum(1 for t in task_list if t.status == TASK_SKIPPED)
                tokens = await self._run_tokens(session, run.id)
                if failed == 0 and quarantined == 0 and passed == 0 and skipped > 0:
                    run.status = RUN_CANCELLED  # 全部被跳过 = 用户取消
                elif failed == 0 and quarantined == 0:
                    run.status = RUN_PASSED
                elif passed > 0:
                    run.status = RUN_PARTIAL
                else:
                    run.status = RUN_FAILED
                run.stats = {
                    "total": len(task_list), "passed": passed, "failed": failed,
                    "quarantined": quarantined, "skipped": skipped, "tokens": tokens,
                }
                run.finished_at = utcnow()
                await session.commit()
                logger.info("run %s 收口: %s %s", run.id, run.status, run.stats)
                for t in task_list:
                    if t.status in (TASK_FAILED, TASK_QUARANTINED) and t.id not in self._analyzed:
                        self._analyzed.add(t.id)
                        # 失败归因在报告层执行（异步触发，不阻塞调度循环）
                        asyncio.create_task(self._trigger_analysis(run.id, t.id))

    async def _run_tokens(self, session: AsyncSession, run_id: str) -> int:
        """汇总 run 内所有 Agent 会话的 token 用量（联查，兼容 SQLite 的 JSON 列）。"""
        rows = await session.execute(
            select(AgentSession.usage).join(
                TestTask, TestTask.id == AgentSession.task_id
            ).where(TestTask.run_id == run_id)
        )
        total = 0
        for (usage,) in rows.all():
            u = usage or {}
            total += int(u.get("prompt_tokens", 0) or 0) + int(u.get("completion_tokens", 0) or 0)
        return total

    async def _trigger_analysis(self, run_id: str, task_id: str) -> None:
        # 配置页关闭失败归因时跳过（省 reasoner token）
        policy = self._policy or await self._execution_policy()
        if not policy.failure_analysis:
            return
        from easyrun.reporter import analyze_task_failure
        try:
            await analyze_task_failure(self._sf, self._settings, task_id, run_id)
        except Exception:
            logger.exception("任务 %s 失败归因异常", task_id)
