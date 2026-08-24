"""执行 / 报告 / 趋势 / Allure 导出 / 元素库 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from easyrun.models import LocatorEntry, StepEvent, TestRun, TestTask
from easyrun.reporter import build_run_report, export_allure, get_trends
from easyrun.schemas import (
    BatchDelete,
    EventsPage,
    EventOut,
    LocatorOut,
    RunCreate,
    RunDetail,
    RunOut,
    RunReport,
    RunsPage,
    TaskOut,
    TrendsOut,
)

router = APIRouter(tags=["runs"])


@router.post("/runs", response_model=RunOut)
async def create_run(body: RunCreate, request: Request):
    if bool(body.plan_id) == bool(body.case_id):
        raise HTTPException(400, "plan_id 与 case_id 必须二选一")
    orch = request.app.state.orchestrator
    try:
        if body.plan_id:
            run_id = await orch.submit_plan(body.plan_id, body.target_url, body.env)
        else:
            run_id = await orch.submit_case(body.case_id, body.target_url, body.env)
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with request.app.state.sf() as session:
        run = await session.get(TestRun, run_id)
        return RunOut.model_validate(run)


@router.get("/runs", response_model=RunsPage)
async def list_runs(request: Request, page: int = 1, page_size: int = 20):
    """执行记录分页列表（page 从 1 开始）。"""
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    async with request.app.state.sf() as session:
        total = (await session.execute(select(func.count()).select_from(TestRun))).scalar() or 0
        rows = await session.execute(
            select(TestRun)
            .order_by(TestRun.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return RunsPage(
            items=[RunOut.model_validate(r) for r in rows.scalars()],
            total=total, page=page, page_size=page_size,
        )


@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, request: Request):
    async with request.app.state.sf() as session:
        run = await session.get(TestRun, run_id)
        if run is None:
            raise HTTPException(404, "执行不存在")
        tasks = await session.execute(
            select(TestTask).where(TestTask.run_id == run_id).order_by(TestTask.created_at)
        )
        return RunDetail(
            run=RunOut.model_validate(run),
            tasks=[TaskOut.model_validate(t) for t in tasks.scalars()],
        )


@router.get("/runs/{run_id}/events", response_model=EventsPage)
async def get_events(run_id: str, request: Request, after: int = 0, task_id: str = ""):
    """事件流轮询接口：after 为游标（seq）。"""
    async with request.app.state.sf() as session:
        run = await session.get(TestRun, run_id)
        if run is None:
            raise HTTPException(404, "执行不存在")
        q = select(StepEvent).where(StepEvent.seq > after)
        if task_id:
            q = q.where(StepEvent.task_id == task_id)
        else:
            task_rows = await session.execute(select(TestTask.id).where(TestTask.run_id == run_id))
            task_ids = [r[0] for r in task_rows.all()]
            if not task_ids:
                return EventsPage(events=[], next_after=after)
            q = q.where(StepEvent.task_id.in_(task_ids))
        rows = await session.execute(q.order_by(StepEvent.seq).limit(500))
        events = [EventOut.model_validate(e) for e in rows.scalars()]
        next_after = events[-1].seq if events else after
        return EventsPage(events=events, next_after=next_after)


@router.get("/runs/{run_id}/report", response_model=RunReport)
async def get_report(run_id: str, request: Request):
    try:
        return await build_run_report(request.app.state.sf, run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


async def _delete_runs(sf, settings, run_ids: list[str]) -> int:
    """删除执行记录及其全部关联内容：任务、事件、Agent 会话、失败归因 + 截图/Allure 工件。"""
    import shutil

    from sqlalchemy import delete as sa_delete

    from easyrun.models import AgentSession, FailureAnalysis, TestTask

    async with sf() as session:
        rows = await session.execute(select(TestRun).where(TestRun.id.in_(run_ids)))
        runs = list(rows.scalars())
        if not runs:
            return 0
        task_rows = await session.execute(select(TestTask.id).where(TestTask.run_id.in_(run_ids)))
        task_ids = [r[0] for r in task_rows.all()]
        session_rows = (
            await session.execute(select(AgentSession.id).where(AgentSession.task_id.in_(task_ids)))
            if task_ids else None
        )
        session_ids = [r[0] for r in session_rows.all()] if session_rows else []
        await session.execute(sa_delete(FailureAnalysis).where(FailureAnalysis.run_id.in_(run_ids)))
        if task_ids:
            await session.execute(sa_delete(StepEvent).where(StepEvent.task_id.in_(task_ids)))
            await session.execute(sa_delete(AgentSession).where(AgentSession.task_id.in_(task_ids)))
            await session.execute(sa_delete(TestTask).where(TestTask.id.in_(task_ids)))
        await session.execute(sa_delete(TestRun).where(TestRun.id.in_(run_ids)))
        await session.commit()
    # 工件清理（尽力而为）
    artifact = settings.resolved_artifact_dir
    for sid in session_ids:
        shutil.rmtree(artifact / "sessions" / sid, ignore_errors=True)
    for rid in run_ids:
        shutil.rmtree(artifact / "allure" / rid, ignore_errors=True)
        shutil.rmtree(artifact / "allure-html" / rid, ignore_errors=True)
        shutil.rmtree(artifact / "exported" / rid, ignore_errors=True)
    return len(runs)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, request: Request):
    """删除单条执行记录（含任务、事件、截图等全部关联内容）。"""
    deleted = await _delete_runs(
        request.app.state.sf, request.app.state.settings, [run_id]
    )
    if not deleted:
        raise HTTPException(404, "执行不存在")
    return {"ok": True}


@router.post("/runs/batch-delete")
async def batch_delete_runs(body: BatchDelete, request: Request):
    """批量删除执行记录。"""
    if not body.run_ids:
        raise HTTPException(400, "run_ids 不能为空")
    deleted = await _delete_runs(
        request.app.state.sf, request.app.state.settings, body.run_ids
    )
    return {"ok": True, "deleted": deleted}


@router.post("/runs/{run_id}/rerun-failed", response_model=RunOut)
async def rerun_failed(run_id: str, request: Request):
    """重跑失败用例：把失败/隔离的用例组成新的执行。"""
    try:
        new_run_id = await request.app.state.orchestrator.rerun_failed(run_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with request.app.state.sf() as session:
        run = await session.get(TestRun, new_run_id)
        return RunOut.model_validate(run)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, request: Request):
    """取消执行：排队任务直接跳过，执行中任务在下一步停止。"""
    ok = await request.app.state.orchestrator.cancel_run(run_id, request.app.state.cancel_registry)
    if not ok:
        raise HTTPException(409, "执行已结束，无法取消")
    return {"ok": True}


@router.post("/runs/{run_id}/allure")
async def export_allure_report(run_id: str, request: Request):
    """把事件流导出为 Allure 结果格式；装有 allure CLI 时同步生成 HTML 报告。"""
    try:
        out_dir = await export_allure(request.app.state.sf, request.app.state.settings, run_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    html_url = ""
    artifact_dir = request.app.state.settings.resolved_artifact_dir
    if artifact_dir:
        from easyrun.reporter import generate_allure_html

        html_dir = artifact_dir / "allure-html" / run_id
        if await generate_allure_html(out_dir, html_dir, request.app.state.settings.resolve_allure_bin()):
            html_url = f"/allure-html/{run_id}/"
    return {"ok": True, "dir": str(out_dir), "html_url": html_url}


@router.get("/trends", response_model=TrendsOut)
async def trends(request: Request):
    return await get_trends(request.app.state.sf)


@router.get("/locators", response_model=list[LocatorOut])
async def locators(request: Request):
    async with request.app.state.sf() as session:
        rows = await session.execute(
            select(LocatorEntry).order_by(LocatorEntry.created_at.desc()).limit(200)
        )
        return [LocatorOut.model_validate(l) for l in rows.scalars()]


@router.get("/health")
async def health(request: Request):
    s = request.app.state.settings
    return {
        "ok": True,
        "name": s.app_name,
        "queue": "memory" if s.use_memory_queue else "redis",
        "llm": f"{s.deepseek_base_url} ({s.deepseek_chat_model}/{s.deepseek_reasoner_model})",
        "llm_configured": bool(s.resolved_api_key),
        "workers": s.workers,
    }
