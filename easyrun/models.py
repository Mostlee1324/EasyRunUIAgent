"""数据模型：与设计文档 §07 一一对应。

SQLite 兼容：主键为 uuid 字符串、JSON 用 SQLAlchemy JSON 类型。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from easyrun.db import Base


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UtcDateTime(TypeDecorator):
    """统一 UTC 时间存储：入库转 naive UTC（兼容 SQLite/PG），出库附加 UTC 时区。

    保证 API 层与前端拿到的 datetime 始终带时区信息，
    页面即可按本地时区正确展示（new Date / fromisoformat 直接可用）。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            value = value.replace(tzinfo=timezone.utc)
        return value


# ---- 状态常量（避免枚举迁移负担，DB 层存字符串）----

CASE_MODE_AGENTIC = "agentic"            # 探索模式：LLM 现场决策
CASE_MODE_DETERMINISTIC = "deterministic"  # 固化模式：回放已记录的确定性动作

RUN_PENDING = "pending"
RUN_RUNNING = "running"
RUN_PASSED = "passed"
RUN_FAILED = "failed"
RUN_PARTIAL = "partial"
RUN_CANCELLED = "cancelled"
RUN_TERMINAL = {RUN_PASSED, RUN_FAILED, RUN_PARTIAL, RUN_CANCELLED}

TASK_QUEUED = "queued"
TASK_RUNNING = "running"
TASK_PASSED = "passed"
TASK_FAILED = "failed"
TASK_RETRYING = "retrying"
TASK_QUARANTINED = "quarantined"
TASK_SKIPPED = "skipped"
TASK_TERMINAL = {TASK_PASSED, TASK_FAILED, TASK_QUARANTINED, TASK_SKIPPED}
TASK_ACTIVE = {TASK_QUEUED, TASK_RUNNING, TASK_RETRYING}

# 失败归因五类
FAULT_PRODUCT_BUG = "product_bug"
FAULT_ENV = "env_issue"
FAULT_CASE = "case_issue"
FAULT_LOCATOR = "locator_drift"
FAULT_AGENT = "agent_error"


class TestCase(Base):
    __tablename__ = "test_case"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # 用户可读的整数编号（对外展示；内部引用仍用 uuid 主键，保证历史数据稳定）
    case_no: Mapped[int | None] = mapped_column(Integer, nullable=True, default=None)
    name: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    mode: Mapped[str] = mapped_column(String(20), default=CASE_MODE_AGENTIC)
    # agentic: 自然语言步骤列表 ["打开登录页", "输入账号..."]
    # deterministic: 已固化的确定性动作列表 [{"tool":..., "args":...}]
    steps: Mapped[list] = mapped_column(JSON, default=list)
    # 探索模式通过后自动记录的确定性动作（人工确认后固化启用）
    cured_actions: Mapped[list] = mapped_column(JSON, default=list)
    # 断言列表 [{"type":"text_contains","target":"订单编号","expected":"","detail":""}]
    assertions: Mapped[list] = mapped_column(JSON, default=list)
    # 完成条件：满足即停止操作、进入断言阶段（如「页面右上角出现 中性新闻（xxx）标签」）
    # 在每一步动作执行前检查——条件已达成就不会再执行多余动作
    completion_checks: Mapped[list] = mapped_column(JSON, default=list)
    resource_key: Mapped[str] = mapped_column(String(100), default="")   # 共享资源锁（如账号）
    target_url: Mapped[str] = mapped_column(Text, default="")            # 默认访问网址（运行时仍可覆盖）
    tags: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class TestPlan(Base):
    __tablename__ = "test_plan"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), index=True)
    case_ids: Mapped[list] = mapped_column(JSON, default=list)   # 有序用例集
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class TestRun(Base):
    __tablename__ = "test_run"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    plan_id: Mapped[str] = mapped_column(String(32), default="")
    case_ids: Mapped[list] = mapped_column(JSON, default=list)
    target_url: Mapped[str] = mapped_column(Text, default="")
    env: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default=RUN_PENDING, index=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    # 汇总统计 {"total":n,"passed":n,"failed":n,"quarantined":n,"skipped":n,"tokens":n}
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


class TestTask(Base):
    __tablename__ = "test_task"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    case_id: Mapped[str] = mapped_column(String(32), index=True)
    case_name: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(20), default=TASK_QUEUED, index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    agent_id: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    lock_key: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class AgentSession(Base):
    __tablename__ = "agent_session"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    worker_id: Mapped[str] = mapped_column(String(64), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    # {"prompt_tokens":n,"completion_tokens":n,"llm_calls":n,"heals":n,"steps":n}
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class StepEvent(Base):
    __tablename__ = "step_event"

    # seq 为单调递增主键（SQLite/PG 均可自增），是报告轮询的游标
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(32), default=new_id, index=True)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    session_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    artifact: Mapped[str] = mapped_column(Text, default="")   # 工件相对路径（/artifacts 下）
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class LocatorEntry(Base):
    __tablename__ = "locator_entry"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    app_url: Mapped[str] = mapped_column(Text, default="")
    page: Mapped[str] = mapped_column(String(200), default="")
    element_key: Mapped[str] = mapped_column(String(200), index=True)   # 语义名（如"登录按钮"）
    strategy: Mapped[str] = mapped_column(String(20), default="text")   # text / css / role
    value: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="manual")   # manual / healed
    app_version: Mapped[str] = mapped_column(String(50), default="")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)      # 自愈定位需回归验证转正
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)


class PlatformSetting(Base):
    __tablename__ = "platform_setting"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow)


class FailureAnalysis(Base):
    __tablename__ = "failure_analysis"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(32), index=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    category: Mapped[str] = mapped_column(String(30), default=FAULT_AGENT)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    root_cause: Mapped[str] = mapped_column(Text, default="")
    defect_draft: Mapped[dict] = mapped_column(JSON, default=dict)  # {title, steps, expected, actual}
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
