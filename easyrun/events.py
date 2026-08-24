"""步骤事件流：报告中心与审计的事实源（设计文档 §05）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from easyrun.models import StepEvent

# 事件类型
EV_SESSION_START = "session_start"
EV_LLM_DECISION = "llm_decision"      # LLM 选择的动作与理由
EV_TOOL_CALL = "tool_call"            # 动作执行结果
EV_SCREENSHOT = "screenshot"          # 步骤截图（工件引用）
EV_ASSERTION = "assertion"            # 确定性断言结果
EV_HEAL_REQUEST = "heal_request"      # 自愈开始
EV_HEAL_RESULT = "heal_result"        # 自愈结果
EV_GOAL_REACHED = "goal_reached"      # 完成条件已满足，提前停止操作
EV_CASE_PASSED = "case_passed"
EV_CASE_FAILED = "case_failed"


class EventEmitter:
    """写入 step_event 表。每事件独立提交，保证报告轮询可见。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        task_id: str,
        session_id: str,
    ) -> None:
        self._sf = session_factory
        self.task_id = task_id
        self.session_id = session_id

    async def emit(self, type_: str, payload: dict, artifact: str = "") -> StepEvent:
        async with self._sf() as session:
            ev = StepEvent(
                task_id=self.task_id,
                session_id=self.session_id,
                type=type_,
                payload=payload,
                artifact=artifact,
            )
            session.add(ev)
            await session.commit()
            await session.refresh(ev)
            return ev
