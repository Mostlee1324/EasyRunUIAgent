"""Worker Agent：消费队列、驱动浏览器执行用例、产出事件流。

无状态设计：所有执行状态在数据库与队列中，Worker 可随时重建。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from easyrun.agent import AgentOutcome, AgentRunner
from easyrun.config import Settings
from easyrun.events import EV_CASE_FAILED, EventEmitter
from easyrun.execution_policy import get_execution_policy
from easyrun.llm import DeepSeekClient
from easyrun.models import (
    CASE_MODE_AGENTIC,
    TASK_FAILED,
    TASK_PASSED,
    TASK_QUEUED,
    TASK_RETRYING,
    TASK_RUNNING,
    TASK_SKIPPED,
    AgentSession,
    TestCase,
    TestRun,
    TestTask,
    new_id,
    utcnow,
)
from easyrun.queue.base import TaskQueue

logger = logging.getLogger("easyrun.worker")


class LockManager:
    """共享资源互斥锁（账号 / 设备等）。单进程内 asyncio.Lock 实现。"""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def get(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())


class Worker:
    def __init__(
        self,
        worker_id: str,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        queue: TaskQueue,
        locks: LockManager,
        llm: DeepSeekClient,
        cancel_registry: set | None = None,
    ) -> None:
        self.id = worker_id
        self._settings = settings
        self._sf = session_factory
        self._queue = queue
        self._locks = locks
        self._llm = llm
        # 注意：不能用 `cancel_registry or set()`——空集合为假值，
        # 会导致 Worker 与 API 持有两个不同的注册表对象，取消信号丢失
        self._cancel_registry = cancel_registry if cancel_registry is not None else set()
        self._stopping = False

    async def run_forever(self) -> None:
        logger.info("worker %s 启动", self.id)
        while not self._stopping:
            try:
                item = await self._queue.pop(timeout=20)
            except asyncio.CancelledError:
                raise
            except Exception:
                # 领取异常（如 Redis 连接断开）不能杀死循环：
                # 协程死亡后 task 仍被外层列表持有，异常永不回收、也无日志，
                # 表现为 worker 静默失联。这里留日志并稍后重试重连。
                logger.exception("worker %s 领取任务异常，2 秒后重试", self.id)
                await asyncio.sleep(2)
                continue
            if item is None:
                continue
            try:
                await self.process(item.task_id)
            except Exception:
                logger.exception("worker %s 处理任务 %s 异常", self.id, item.task_id)
                await self._queue.ack(item.task_id)  # 兜底：调度器按状态重试

    def stop(self) -> None:
        self._stopping = True

    async def process(self, task_id: str) -> None:
        async with self._sf() as session:
            task = await session.get(TestTask, task_id)
            if task is None:
                await self._queue.ack(task_id)
                return
            if task.status not in (TASK_QUEUED, TASK_RETRYING):
                await self._queue.ack(task_id)
                return
            run = await session.get(TestRun, task.run_id)
            case = await session.get(TestCase, task.case_id)
            if run is None or case is None:
                task.status = TASK_FAILED
                task.error = "任务关联的执行或用例不存在"
                task.finished_at = utcnow()
                await session.commit()
                await self._queue.ack(task_id)
                return
            # 执行级网址优先，其次用例级默认网址（计划批量执行时按用例各自取值）
            target_url = run.target_url or case.target_url
            lock_key = case.resource_key or task.lock_key

        # ---- 资源锁 ----
        if lock_key:
            lock = self._locks.get(lock_key)
            try:
                await asyncio.wait_for(lock.acquire(), timeout=self._settings.lock_wait_seconds)
            except asyncio.TimeoutError:
                # 单次执行策略：等不到锁直接失败，不回队列重跑（用户可从报告页手动 rerun）
                logger.warning("worker %s 任务 %s 等待资源锁 %s 超时，标记失败", self.id, task_id, lock_key)
                async with self._sf() as session:
                    t = await session.get(TestTask, task_id)
                    t.status = TASK_FAILED
                    t.error = f"等待资源锁 {lock_key} 超时（{self._settings.lock_wait_seconds}s）"
                    t.finished_at = utcnow()
                    t.updated_at = utcnow()
                    await session.commit()
                await self._queue.ack(task_id)
                return

        try:
            await self._run_task(task_id, target_url)
        finally:
            if lock_key:
                self._locks.get(lock_key).release()

    async def _run_task(self, task_id: str, target_url: str) -> None:
        async with self._sf() as session:
            task = await session.get(TestTask, task_id)
            if task.status == TASK_SKIPPED:
                # 认领后被取消（跨进程取消信号）：不执行，直接收口
                task.finished_at = utcnow()
                task.updated_at = utcnow()
                await session.commit()
                await self._queue.ack(task_id)
                return
            task.status = TASK_RUNNING
            task.agent_id = self.id
            task.started_at = utcnow()
            task.updated_at = utcnow()
            session_id = new_id()
            session.add(AgentSession(
                id=session_id, task_id=task.id, worker_id=self.id, model=self._settings.deepseek_chat_model
            ))
            await session.commit()

        emitter = EventEmitter(self._sf, task_id, session_id)
        # 运行时执行策略（DB > env 默认）：model_copy 出任务级副本，不污染进程共享单例
        policy = await get_execution_policy(self._sf, self._settings)
        runner_settings = self._settings.model_copy(update={
            "max_attempts": policy.max_attempts,
            "heal_attempts": policy.heal_attempts,
            "max_steps_per_case": policy.max_steps,
        })
        runner = AgentRunner(runner_settings, self._llm)

        async with self._sf() as session:
            task = await session.get(TestTask, task_id)
            case = await session.get(TestCase, task.case_id)
            artifact_root = self._settings.resolved_artifact_dir
        async def _should_stop() -> bool:
            # 取消信号双通道：同进程 registry（即时）+ DB skipped 状态（多机/多容器跨进程）
            if task_id in self._cancel_registry:
                return True
            async with self._sf() as session:
                status = (await session.execute(
                    select(TestTask.status).where(TestTask.id == task_id)
                )).scalar_one_or_none()
                return status == TASK_SKIPPED

        # 重试时把上次失败原因注入用例说明，帮助 LLM 换策略而不是重蹈覆辙
        previous_error = ""
        if task.attempt > 1:
            previous_error = task.error

        try:
            outcome = await runner.run(
                task_id=task_id, case=case, target_url=target_url,
                emitter=emitter, session_id=session_id, artifact_root=artifact_root,
                should_stop=_should_stop, previous_error=previous_error,
            )
        except Exception as e:
            # 兜底：任何未预期异常（LLM 不可用、浏览器崩溃等）都不能让任务卡在 running
            logger.exception("worker %s 执行任务 %s 异常", self.id, task_id)
            outcome = AgentOutcome(
                status="failed", error=f"{type(e).__name__}: {e}",
                usage={"prompt_tokens": 0, "completion_tokens": 0, "llm_calls": 0, "steps": 0, "heals": 0},
            )
            try:
                await emitter.emit(EV_CASE_FAILED, {"error": outcome.error, "usage": outcome.usage})
            except Exception:  # 事件写入失败不影响任务收口
                logger.warning("写入 case_failed 事件失败", exc_info=True)

        async with self._sf() as session:
            task = await session.get(TestTask, task_id)
            # 取消判定：registry（同进程）/ DB 已被取消方置为 skipped（跨进程）/ agent 主动上报
            canceled = (
                task.status == TASK_SKIPPED
                or task_id in self._cancel_registry
                or "任务已取消" in outcome.error
            )
            if canceled:
                # 取消的任务走 skipped（不触发重试），run 由调度器判定为 cancelled
                task.status = TASK_SKIPPED
                task.error = "用户取消"
            elif outcome.status == "passed":
                task.status = TASK_PASSED
                task.error = ""
                await self._maybe_cure(session, case, outcome)
            else:
                task.status = TASK_FAILED
                task.error = outcome.error[:1000]
            task.finished_at = utcnow()
            task.updated_at = utcnow()

            sess = await session.execute(
                select(AgentSession).where(AgentSession.id == session_id)
            )
            agent_session = sess.scalar_one_or_none()
            if agent_session is not None:
                agent_session.usage = outcome.usage
                agent_session.finished_at = utcnow()
            await session.commit()
        await self._queue.ack(task_id)
        logger.info("worker %s 任务 %s 完成: %s", self.id, task_id, outcome.status)

    async def _maybe_cure(self, session: AsyncSession, case: TestCase, outcome: AgentOutcome) -> None:
        """探索通过后自动固化：记录确定性动作，供后续回放（人工确认后启用）。

        门槛 ≥1：即使只执行了「打开页面」（如主页验证类用例），
        固化后回放同样省掉 LLM 调用。
        """
        if case.mode == CASE_MODE_AGENTIC and len(outcome.actions) >= 1:
            case = await session.get(TestCase, case.id)
            case.cured_actions = outcome.actions
            case.version += 1
            case.updated_at = utcnow()
        for loc in outcome.healed_locators:
            from easyrun.models import LocatorEntry
            session.add(LocatorEntry(
                app_url="", page=loc["page"], element_key=loc["element_key"],
                strategy=loc["strategy"], value=loc["value"], source="healed",
            ))


def worker_main() -> None:
    """独立 Worker 进程入口（easyrun worker）：多机部署时在 Worker 节点上运行。

    通过共享的 Redis 队列与数据库接入集群；API 节点设 EASYRUN_WORKERS=0。
    """
    import asyncio
    import signal

    from easyrun.config import get_settings
    from easyrun.db import create_engine_and_session, init_db
    from easyrun.llm import DeepSeekClient
    from easyrun.queue import get_queue

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    settings = get_settings()
    engine, session_factory = create_engine_and_session(settings.resolved_database_url)
    cancel_registry: set = set()

    async def run() -> None:
        await init_db(engine)
        queue = get_queue(settings)
        llm = DeepSeekClient(settings)
        locks = LockManager()
        workers = [
            Worker(f"w-{i + 1}", settings, session_factory, queue, locks, llm, cancel_registry)
            for i in range(max(settings.workers, 1))
        ]
        tasks = [asyncio.create_task(w.run_forever(), name=f"worker-{i + 1}") for i, w in enumerate(workers)]
        logger.info("独立 Worker 进程启动：%s 个 Agent，队列=%s",
                    len(workers), "memory" if settings.use_memory_queue else "redis")
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows
                pass
        await stop.wait()
        for w in workers:
            w.stop()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await queue.close()
        await engine.dispose()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
