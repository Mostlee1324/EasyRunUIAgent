"""测试计划 API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from easyrun.models import TestPlan, TestRun
from easyrun.schemas import PlanCreate, PlanOut, RunOut, RunRequest

router = APIRouter(prefix="/plans", tags=["plans"])


@router.get("", response_model=list[PlanOut])
async def list_plans(request: Request):
    async with request.app.state.sf() as session:
        rows = await session.execute(select(TestPlan).order_by(TestPlan.created_at.desc()))
        return [PlanOut.model_validate(p) for p in rows.scalars()]


@router.post("", response_model=PlanOut)
async def create_plan(body: PlanCreate, request: Request):
    plan = TestPlan(name=body.name, case_ids=body.case_ids)
    async with request.app.state.sf() as session:
        session.add(plan)
        await session.commit()
        await session.refresh(plan)
        return PlanOut.model_validate(plan)


@router.get("/{plan_id}", response_model=PlanOut)
async def get_plan(plan_id: str, request: Request):
    async with request.app.state.sf() as session:
        plan = await session.get(TestPlan, plan_id)
        if plan is None:
            raise HTTPException(404, "计划不存在")
        return PlanOut.model_validate(plan)


@router.delete("/{plan_id}")
async def delete_plan(plan_id: str, request: Request):
    async with request.app.state.sf() as session:
        plan = await session.get(TestPlan, plan_id)
        if plan is None:
            raise HTTPException(404, "计划不存在")
        await session.delete(plan)
        await session.commit()
        return {"ok": True}


@router.post("/{plan_id}/run", response_model=RunOut)
async def run_plan(plan_id: str, body: RunRequest, request: Request):
    try:
        run_id = await request.app.state.orchestrator.submit_plan(plan_id, body.target_url, body.env)
    except ValueError as e:
        raise HTTPException(400, str(e))
    async with request.app.state.sf() as session:
        run = await session.get(TestRun, run_id)
        return RunOut.model_validate(run)
