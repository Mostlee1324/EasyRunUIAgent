"""API 契约（pydantic DTO）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


# ---- 用例 ----

class AssertionIn(BaseModel):
    """确定性断言：type 见 easyrun.assertions.ASSERTION_TYPES。"""
    type: str = "text_contains"
    target: str = ""        # 文本内容 / URL 片段 / CSS 选择器 / 元素语义名
    expected: str = ""      # 期望值（text_contains 等场景可为空）
    min_steps: int | None = None  # 仅完成条件使用：执行满 N 个动作后条件才生效
    after_step: int | None = Field(default=None, ge=1, le=99)  # 绑定步骤序号：该步骤完成后立即校验

class AssertionParseRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

class AssertionParseResponse(BaseModel):
    assertions: list[AssertionIn]

class CaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    steps: list[str] = Field(default_factory=list)          # 自然语言步骤
    assertions: list[AssertionIn] = Field(default_factory=list)
    completion_checks: list[AssertionIn] = Field(default_factory=list)  # 完成条件：满足即停止操作
    resource_key: str = ""
    target_url: str = ""                                    # 默认访问网址（运行时仍可覆盖）
    tags: list[str] = Field(default_factory=list)
    mode: str = "agentic"

class CaseUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[str] | None = None
    assertions: list[AssertionIn] | None = None
    completion_checks: list[AssertionIn] | None = None
    resource_key: str | None = None
    target_url: str | None = None
    tags: list[str] | None = None
    mode: str | None = None

class CaseOut(BaseModel):
    id: str
    case_no: int | None = None   # 用户可读的整数编号（内部引用仍用 id）
    name: str
    description: str
    mode: str
    steps: list
    cured_actions: list
    assertions: list
    completion_checks: list
    resource_key: str
    target_url: str
    tags: list
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---- 计划 ----

class PlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    case_ids: list[str] = Field(default_factory=list)

class PlanOut(BaseModel):
    id: str
    name: str
    case_ids: list
    created_at: datetime

    model_config = {"from_attributes": True}


# ---- 执行 ----

class RunRequest(BaseModel):
    target_url: str = ""
    env: str = ""

class RunCreate(BaseModel):
    """提交执行：plan_id 与 case_id 二选一。"""
    plan_id: str | None = None
    case_id: str | None = None
    target_url: str = ""
    env: str = ""

class BatchDelete(BaseModel):
    run_ids: list[str] = Field(default_factory=list)

class RunOut(BaseModel):
    id: str
    plan_id: str
    case_ids: list
    target_url: str
    env: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    stats: dict

    model_config = {"from_attributes": True}

class TaskOut(BaseModel):
    id: str
    run_id: str
    case_id: str
    case_name: str
    status: str
    attempt: int
    agent_id: str
    error: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

    model_config = {"from_attributes": True}

class SettingsUpdate(BaseModel):
    default_target_url: str = ""
    max_attempts: int | None = None
    heal_attempts: int | None = None
    max_steps: int | None = None
    failure_analysis: bool | None = None

class SettingsOut(BaseModel):
    default_target_url: str = ""
    max_attempts: int = 1
    heal_attempts: int = 0
    max_steps: int = 30
    failure_analysis: bool = True

class RunsPage(BaseModel):
    items: list[RunOut]
    total: int
    page: int
    page_size: int

class RunDetail(BaseModel):
    run: RunOut
    tasks: list[TaskOut]

class EventsPage(BaseModel):
    events: list[EventOut]
    next_after: int

class EventOut(BaseModel):
    seq: int
    task_id: str
    session_id: str
    type: str
    payload: dict
    artifact: str
    created_at: datetime

    model_config = {"from_attributes": True}

class FailureAnalysisOut(BaseModel):
    id: str
    task_id: str
    category: str
    confidence: float
    root_cause: str
    defect_draft: dict
    created_at: datetime

    model_config = {"from_attributes": True}

class LocatorOut(BaseModel):
    id: str
    app_url: str
    page: str
    element_key: str
    strategy: str
    value: str
    source: str
    app_version: str
    verified: bool
    created_at: datetime

    model_config = {"from_attributes": True}

class TaskReport(BaseModel):
    task: TaskOut
    events: list[EventOut]
    analysis: FailureAnalysisOut | None = None

class RunReport(BaseModel):
    run: RunOut
    tasks: list[TaskReport]

class TrendsOut(BaseModel):
    total_runs: int
    passed_runs: int
    pass_rate: float
    total_tasks: int
    flaky_tasks: int            # 经历过重试的任务数
    flakiness: float
    avg_duration_seconds: float
    total_tokens: int
    recent_runs: list[RunOut]
