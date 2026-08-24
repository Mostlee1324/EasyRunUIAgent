"""REST API 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from easyrun.api import cases, plans, runs, settings

api_router = APIRouter(prefix="/api")
api_router.include_router(cases.router)
api_router.include_router(plans.router)
api_router.include_router(runs.router)
api_router.include_router(settings.router)
