"""报告中心：事件聚合、AI 失败归因、趋势统计、Allure 兼容导出（设计文档 §05）。"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from easyrun.config import Settings
from easyrun.events import (
    EV_ASSERTION,
    EV_CASE_FAILED,
    EV_HEAL_REQUEST,
    EV_HEAL_RESULT,
    EV_LLM_DECISION,
    EV_TOOL_CALL,
)
from easyrun.llm import DeepSeekClient, LLMError
from easyrun.models import (
    FAULT_AGENT,
    FAULT_CASE,
    FAULT_ENV,
    FAULT_LOCATOR,
    FAULT_PRODUCT_BUG,
    AgentSession,
    FailureAnalysis,
    StepEvent,
    TestCase,
    TestRun,
    TestTask,
)
from easyrun.schemas import (
    EventOut,
    FailureAnalysisOut,
    RunOut,
    RunReport,
    TaskOut,
    TaskReport,
    TrendsOut,
)

logger = logging.getLogger("easyrun.reporter")

FAILURE_CATEGORIES = {
    FAULT_PRODUCT_BUG: "产品缺陷（被测应用的真实 bug）",
    FAULT_ENV: "环境问题（网络 / 服务 / 测试数据不可用）",
    FAULT_CASE: "用例设计问题（步骤或断言本身不合理）",
    FAULT_LOCATOR: "locator 漂移（页面改版导致元素定位失效）",
    FAULT_AGENT: "Agent 误判（操作错误或过早放弃）",
}

ANALYSIS_PROMPT = """你是测试失败分析专家。根据给定的用例信息与执行事件流，判断失败原因并输出 JSON：

{{"category": "<五选一>", "confidence": <0~1>, "root_cause": "<一句话根因>", "defect_draft": {{"title": "<缺陷标题>", "steps": "<复现步骤>", "expected": "<期望结果>", "actual": "<实际结果>"}}}}

类别定义：
- {product}: 被测应用的真实缺陷
- {env}: 网络、服务或测试数据等环境问题
- {case}: 用例步骤或断言本身设计不合理
- {locator}: 页面改版导致元素定位失效
- {agent}: Agent 操作错误或过早放弃

只输出 JSON，不要输出其他内容。"""


# ---- 失败归因（deepseek-reasoner）----

async def analyze_task_failure(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    task_id: str,
    run_id: str,
) -> FailureAnalysis:
    async with session_factory() as session:
        task = await session.get(TestTask, task_id)
        if task is None:
            raise ValueError(f"任务不存在: {task_id}")
        case = await session.get(TestCase, task.case_id)
        events = await session.execute(
            select(StepEvent).where(StepEvent.task_id == task_id).order_by(StepEvent.seq)
        )
        event_list = list(events.scalars())
        case_name = case.name if case else task.case_name
        case_steps = case.steps if case else []
        case_assertions = case.assertions if case else []
        event_text = _summarize_events(event_list)

    llm = DeepSeekClient(settings)
    prompt = ANALYSIS_PROMPT.format(
        product=FAULT_PRODUCT_BUG, env=FAULT_ENV, case=FAULT_CASE,
        locator=FAULT_LOCATOR, agent=FAULT_AGENT,
    )
    context = (
        f"用例：{case_name}\n"
        f"用例步骤：{json.dumps(case_steps, ensure_ascii=False)}\n"
        f"断言：{json.dumps(case_assertions, ensure_ascii=False)}\n"
        f"执行事件流摘要：\n{event_text}\n"
        f"最终错误：{task.error}"
    )
    try:
        obj, _ = await llm.chat_json(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": context[:6000]},
            ],
            model=settings.deepseek_reasoner_model,
            max_tokens=2048,
        )
    except LLMError as e:
        logger.warning("失败归因跳过（LLM 不可用）: %s", e)
        obj = {
            "category": FAULT_AGENT, "confidence": 0.0,
            "root_cause": f"归因未执行（LLM 不可用）: {e}",
            "defect_draft": {"title": case_name, "steps": "", "expected": "", "actual": task.error},
        }

    category = obj.get("category") if obj.get("category") in FAILURE_CATEGORIES else FAULT_AGENT
    try:
        confidence = float(obj.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    draft = obj.get("defect_draft") or {}
    if not isinstance(draft, dict):
        draft = {"title": str(draft)}

    async with session_factory() as session:
        analysis = FailureAnalysis(
            task_id=task_id, run_id=run_id, category=category,
            confidence=min(max(confidence, 0.0), 1.0),
            root_cause=str(obj.get("root_cause", ""))[:2000],
            defect_draft={
                "title": str(draft.get("title") or case_name)[:300],
                "steps": str(draft.get("steps", ""))[:2000],
                "expected": str(draft.get("expected", ""))[:1000],
                "actual": str(draft.get("actual", task.error))[:1000],
            },
        )
        session.add(analysis)
        await session.commit()
        await session.refresh(analysis)
    return analysis


def _summarize_events(events: list[StepEvent], limit: int = 4000) -> str:
    lines: list[str] = []
    for ev in events:
        p = ev.payload or {}
        if ev.type == EV_LLM_DECISION:
            lines.append(f"[决策] {p.get('tool')} {json.dumps(p.get('args'), ensure_ascii=False)[:120]} 理由:{p.get('reason', '')[:100]}")
        elif ev.type == EV_TOOL_CALL:
            status = "成功" if p.get("ok") else f"失败: {p.get('error', '')[:120]}"
            lines.append(f"[动作] {p.get('tool')} → {status}")
        elif ev.type == EV_ASSERTION:
            status = "通过" if p.get("ok") else f"失败: {p.get('detail', '')[:160]}"
            lines.append(f"[断言] {p.get('type')}:{p.get('target')} → {status}")
        elif ev.type == EV_HEAL_REQUEST:
            lines.append(f"[自愈] 第 {p.get('attempt')} 轮: {json.dumps(p.get('failures'), ensure_ascii=False)[:200]}")
        elif ev.type == EV_HEAL_RESULT:
            lines.append(f"[自愈结果] {'成功' if p.get('ok') else '失败'}")
        elif ev.type == EV_CASE_FAILED:
            lines.append(f"[失败] {str(p.get('error', ''))[:300]}")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n...(摘要截断)"


# ---- 报告视图 ----

async def build_run_report(
    session_factory: async_sessionmaker[AsyncSession], run_id: str
) -> RunReport:
    async with session_factory() as session:
        run = await session.get(TestRun, run_id)
        if run is None:
            raise ValueError(f"执行不存在: {run_id}")
        tasks = await session.execute(
            select(TestTask).where(TestTask.run_id == run_id).order_by(TestTask.created_at)
        )
        task_list = list(tasks.scalars())
        reports: list[TaskReport] = []
        for task in task_list:
            events = await session.execute(
                select(StepEvent).where(StepEvent.task_id == task.id).order_by(StepEvent.seq)
            )
            analysis = await session.execute(
                select(FailureAnalysis)
                .where(FailureAnalysis.task_id == task.id)
                .order_by(FailureAnalysis.created_at.desc())
            )
            analysis_row = analysis.scalars().first()
            reports.append(TaskReport(
                task=TaskOut.model_validate(task),
                events=[EventOut.model_validate(e) for e in events.scalars()],
                analysis=FailureAnalysisOut.model_validate(analysis_row) if analysis_row else None,
            ))
        return RunReport(run=RunOut.model_validate(run), tasks=reports)


async def get_trends(session_factory: async_sessionmaker[AsyncSession]) -> TrendsOut:
    async with session_factory() as session:
        runs = await session.execute(select(TestRun).order_by(TestRun.started_at.desc()))
        run_list = list(runs.scalars())
        total_runs = len(run_list)
        passed_runs = sum(1 for r in run_list if r.status == "passed")
        tasks = await session.execute(select(TestTask))
        task_list = list(tasks.scalars())
        total_tasks = len(task_list)
        flaky = sum(1 for t in task_list if t.attempt > 1)
        durations = [
            (r.finished_at - r.started_at).total_seconds()
            for r in run_list
            if r.finished_at is not None
        ]
        sessions = await session.execute(select(AgentSession.usage))
        tokens = 0
        for (usage,) in sessions.all():
            u = usage or {}
            tokens += int(u.get("prompt_tokens", 0) or 0) + int(u.get("completion_tokens", 0) or 0)
        return TrendsOut(
            total_runs=total_runs,
            passed_runs=passed_runs,
            pass_rate=round(passed_runs / total_runs, 4) if total_runs else 0.0,
            total_tasks=total_tasks,
            flaky_tasks=flaky,
            flakiness=round(flaky / total_tasks, 4) if total_tasks else 0.0,
            avg_duration_seconds=round(sum(durations) / len(durations), 1) if durations else 0.0,
            total_tokens=tokens,
            recent_runs=[RunOut.model_validate(r) for r in run_list[:10]],
        )


# ---- Allure 兼容导出 ----

_STATUS_MAP = {
    "passed": "passed", "failed": "failed",
    "quarantined": "broken", "skipped": "skipped", "retrying": "failed",
}


async def generate_allure_html(results_dir: Path, out_dir: Path, allure_bin: str | None) -> bool:
    """调用 allure CLI 生成静态 HTML 报告（未安装 CLI 时返回 False）。"""
    import asyncio

    if not allure_bin:
        return False
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        allure_bin, "generate", str(results_dir), "-o", str(out_dir), "-c",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        logger.warning("allure generate 失败: %s", stderr.decode(errors="replace")[:300])
        return False
    return (out_dir / "index.html").exists()


async def export_allure(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    run_id: str,
) -> Path:
    """把事件流转换为 Allure 结果格式（allure-results 目录结构）。"""
    report = await build_run_report(session_factory, run_id)
    out_dir = settings.resolved_artifact_dir / "allure" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact_root = settings.resolved_artifact_dir

    for task_report in report.tasks:
        task = task_report.task
        result_uuid = uuid.uuid4().hex
        steps = []
        attachments = []
        attach_index = 0
        last_start = int(task.created_at.timestamp() * 1000)
        for ev in task_report.events:
            ts = int(ev.created_at.timestamp() * 1000)
            if ev.type == EV_TOOL_CALL:
                steps.append({
                    "name": f"{ev.payload.get('tool', '')} {json.dumps(ev.payload.get('args', {}), ensure_ascii=False)[:80]}",
                    "status": "passed" if ev.payload.get("ok") else "failed",
                    "start": last_start, "stop": ts,
                    "statusDetails": {} if ev.payload.get("ok") else {"message": ev.payload.get("error", "")[:500]},
                })
                last_start = ts
            elif ev.type == EV_ASSERTION:
                steps.append({
                    "name": f"断言 {ev.payload.get('type')}:{ev.payload.get('target')}",
                    "status": "passed" if ev.payload.get("ok") else "failed",
                    "start": last_start, "stop": ts,
                    "statusDetails": {} if ev.payload.get("ok") else {"message": ev.payload.get("detail", "")[:500]},
                })
                last_start = ts
            elif ev.type == "screenshot" and ev.artifact:
                src = artifact_root / ev.artifact
                if src.exists():
                    attach_index += 1
                    name = f"{result_uuid[:8]}-s{attach_index}.png"
                    (out_dir / name).write_bytes(src.read_bytes())
                    attachments.append({"name": f"步骤截图 {attach_index}", "source": name, "type": "image/png"})
        result = {
            "uuid": result_uuid,
            "historyId": task.case_id,
            "name": task.case_name,
            "fullName": f"{task.case_name}#{task.id[:8]}",
            "status": _STATUS_MAP.get(task.status, "broken"),
            "statusDetails": {"message": task.error[:1000]} if task.error else {},
            "start": int(task.created_at.timestamp() * 1000),
            "stop": int((task.finished_at or task.created_at).timestamp() * 1000),
            "steps": steps,
            "attachments": attachments,
        }
        (out_dir / f"{result_uuid}-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return out_dir
