"""用例与元素库 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from easyrun.assertions import normalize_assertions
from easyrun.models import CASE_MODE_AGENTIC, CASE_MODE_DETERMINISTIC, TestCase, utcnow
from easyrun.schemas import (
    AssertionIn,
    AssertionParseRequest,
    AssertionParseResponse,
    CaseCreate,
    CaseOut,
    CaseUpdate,
    RunRequest,
    RunOut,
)

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("", response_model=list[CaseOut])
async def list_cases(request: Request):
    async with request.app.state.sf() as session:
        rows = await session.execute(select(TestCase).order_by(TestCase.created_at.desc()))
        return [CaseOut.model_validate(c) for c in rows.scalars()]


@router.post("/assertions/parse", response_model=AssertionParseResponse)
async def parse_assertions(body: AssertionParseRequest, request: Request):
    """自然语言 → 断言：LLM 结构化提取 + 确定性校验，LLM 不可用时规则兜底。"""
    from easyrun.assertions import parse_assertions_from_nl
    from easyrun.llm import LLMError

    try:
        assertions = await parse_assertions_from_nl(body.text, request.app.state.llm)
    except LLMError:
        # LLM 不可用 → 规则兜底；规则也提不出 → 明确报错
        assertions = await parse_assertions_from_nl(body.text, None)
        if not assertions:
            raise HTTPException(400, "LLM 不可用且规则未匹配，请改用下方表单手动添加断言")
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not assertions:
        raise HTTPException(400, "未能从描述中提取出断言，请补充明确的校验点（如「页面出现××」）")
    return AssertionParseResponse(assertions=[AssertionIn(**a) for a in assertions])


@router.post("", response_model=CaseOut)
async def create_case(body: CaseCreate, request: Request):
    if body.mode not in (CASE_MODE_AGENTIC, CASE_MODE_DETERMINISTIC):
        raise HTTPException(400, f"mode 只能是 {CASE_MODE_AGENTIC} 或 {CASE_MODE_DETERMINISTIC}")
    try:
        assertions = normalize_assertions([a.model_dump() for a in body.assertions])
        completion_checks = normalize_assertions([a.model_dump() for a in body.completion_checks])
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with request.app.state.sf() as session:
        from sqlalchemy import func

        next_no = (
            await session.execute(select(func.coalesce(func.max(TestCase.case_no), 0) + 1))
        ).scalar()
        case = TestCase(
            case_no=next_no,
            name=body.name, description=body.description, mode=body.mode,
            steps=body.steps, assertions=assertions, completion_checks=completion_checks,
            resource_key=body.resource_key, target_url=body.target_url, tags=body.tags,
        )
        session.add(case)
        await session.commit()
        await session.refresh(case)
        return CaseOut.model_validate(case)


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(case_id: str, request: Request):
    async with request.app.state.sf() as session:
        case = await session.get(TestCase, case_id)
        if case is None:
            raise HTTPException(404, "用例不存在")
        return CaseOut.model_validate(case)


@router.put("/{case_id}", response_model=CaseOut)
async def update_case(case_id: str, body: CaseUpdate, request: Request):
    async with request.app.state.sf() as session:
        case = await session.get(TestCase, case_id)
        if case is None:
            raise HTTPException(404, "用例不存在")
        data = body.model_dump(exclude_unset=True)
        if "assertions" in data:
            try:
                data["assertions"] = normalize_assertions(data["assertions"])
            except ValueError as e:
                raise HTTPException(400, str(e))
        if "completion_checks" in data:
            try:
                data["completion_checks"] = normalize_assertions(data["completion_checks"])
            except ValueError as e:
                raise HTTPException(400, str(e))
        if "mode" in data and data["mode"] not in (CASE_MODE_AGENTIC, CASE_MODE_DETERMINISTIC):
            raise HTTPException(400, "mode 只能是 agentic 或 deterministic")
        for k, v in data.items():
            setattr(case, k, v)
        case.version += 1
        case.updated_at = utcnow()
        await session.commit()
        await session.refresh(case)
        return CaseOut.model_validate(case)


@router.delete("/{case_id}")
async def delete_case(case_id: str, request: Request):
    async with request.app.state.sf() as session:
        case = await session.get(TestCase, case_id)
        if case is None:
            raise HTTPException(404, "用例不存在")
        await session.delete(case)
        await session.commit()
        return {"ok": True}


@router.post("/{case_id}/run", response_model=RunOut)
async def run_case(case_id: str, body: RunRequest, request: Request):
    try:
        run_id = await request.app.state.orchestrator.submit_case(case_id, body.target_url, body.env)
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with request.app.state.sf() as session:
        from easyrun.models import TestRun
        run = await session.get(TestRun, run_id)
        return RunOut.model_validate(run)


@router.post("/{case_id}/export-code")
async def export_case_code(case_id: str, request: Request):
    """把固化动作导出为独立 Playwright 自动化代码（回放解析定位器，0 token）。"""
    from easyrun.codegen import export_case_code as do_export

    try:
        code, filename = await do_export(
            request.app.state.sf, request.app.state.settings, case_id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    out_dir = request.app.state.settings.resolved_artifact_dir / "exported" / case_id
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / filename).write_text(code, encoding="utf-8")
    return {"ok": True, "code": code, "filename": filename, "path": str(out_dir / filename)}


@router.post("/{case_id}/cure", response_model=CaseOut)
async def cure_case(case_id: str, request: Request):
    """固化：把最近一次探索通过记录的确定性动作启用为回放模式。"""
    async with request.app.state.sf() as session:
        case = await session.get(TestCase, case_id)
        if case is None:
            raise HTTPException(404, "用例不存在")
        if not case.cured_actions:
            raise HTTPException(400, "该用例还没有固化动作（需要先以探索模式成功执行一次）")
        case.steps = case.cured_actions
        case.mode = CASE_MODE_DETERMINISTIC
        case.version += 1
        case.updated_at = utcnow()
        await session.commit()
        await session.refresh(case)
        return CaseOut.model_validate(case)
