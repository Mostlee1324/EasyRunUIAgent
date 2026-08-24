"""平台配置 API：默认执行目标地址 + 执行策略（运行时旋钮，多机共享）。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from easyrun.execution_policy import (
    FAILURE_ANALYSIS,
    get_execution_policy,
    set_execution_policy,
)
from easyrun.platform_settings import (
    DEFAULT_TARGET_URL,
    get_default_target_url,
    set_default_target_url,
)
from easyrun.schemas import SettingsOut, SettingsUpdate

router = APIRouter(prefix="/settings", tags=["settings"])

# 键 → (最小, 最大)；越界 HTTPException 400。None = 清键回默认，不校验
_RANGES = {"max_attempts": (1, 10), "heal_attempts": (0, 5), "max_steps": (3, 100)}
_POLICY_KEYS = tuple(_RANGES)


async def _current(request: Request) -> SettingsOut:
    policy = await get_execution_policy(request.app.state.sf, request.app.state.settings)
    return SettingsOut(
        default_target_url=await get_default_target_url(request.app.state.sf),
        max_attempts=policy.max_attempts,
        heal_attempts=policy.heal_attempts,
        max_steps=policy.max_steps,
        failure_analysis=policy.failure_analysis,
    )


@router.get("", response_model=SettingsOut)
async def get_settings(request: Request):
    return await _current(request)


@router.put("", response_model=SettingsOut)
async def update_settings(body: SettingsUpdate, request: Request):
    if DEFAULT_TARGET_URL in body.model_fields_set:
        await set_default_target_url(request.app.state.sf, body.default_target_url or "")
    updates: dict[str, int | bool | None] = {
        k: getattr(body, k) for k in _POLICY_KEYS if k in body.model_fields_set
    }
    for key, val in updates.items():
        lo, hi = _RANGES[key]
        if val is not None and not (lo <= val <= hi):
            raise HTTPException(400, detail=f"{key} 取值范围 {lo}-{hi}")
    if FAILURE_ANALYSIS in body.model_fields_set:
        updates[FAILURE_ANALYSIS] = body.failure_analysis
    if updates:
        await set_execution_policy(request.app.state.sf, updates)
    return await _current(request)
