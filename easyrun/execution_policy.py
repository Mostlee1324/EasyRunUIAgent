"""执行策略（运行时旋钮）：控制台配置页写入 platform_setting 表，多进程/多机共享。

优先级链：Web 配置页（DB 值）> 环境变量/命令行 > .env > 代码默认值。
无本地缓存：orchestrator 每 tick 读一次、worker 每任务读一次 → 保存即生效。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from easyrun.config import Settings
from easyrun.models import PlatformSetting

logger = logging.getLogger("easyrun.execution_policy")

# DB/API 键名 → Settings 字段名（web 侧叫 max_steps，config.py 里是 max_steps_per_case）
POLICY_FIELDS: dict[str, str] = {
    "max_attempts": "max_attempts",
    "heal_attempts": "heal_attempts",
    "max_steps": "max_steps_per_case",
}

# 失败归因开关：无对应 env 项，默认开启
FAILURE_ANALYSIS = "failure_analysis"


@dataclass(frozen=True)
class ExecutionPolicy:
    max_attempts: int
    heal_attempts: int
    max_steps: int
    failure_analysis: bool = True


async def get_execution_policy(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> ExecutionPolicy:
    """DB 有值 → DB 值；无值 → Settings（env/代码默认）。一条 IN 查询取全部键。"""
    values = {key: getattr(settings, field) for key, field in POLICY_FIELDS.items()}
    values[FAILURE_ANALYSIS] = True
    async with session_factory() as session:
        rows = await session.execute(
            select(PlatformSetting).where(
                PlatformSetting.key.in_([*POLICY_FIELDS, FAILURE_ANALYSIS])
            )
        )
        for row in rows.scalars():
            if row.key in POLICY_FIELDS:
                try:
                    values[row.key] = int(row.value)
                except (TypeError, ValueError):
                    logger.warning("执行策略键 %s 值非法: %r，忽略（回退默认）", row.key, row.value)
            elif row.key == FAILURE_ANALYSIS:
                values[FAILURE_ANALYSIS] = row.value.strip().lower() not in ("0", "false")
    return ExecutionPolicy(
        max_attempts=values["max_attempts"],
        heal_attempts=values["heal_attempts"],
        max_steps=values["max_steps"],
        failure_analysis=values[FAILURE_ANALYSIS],
    )


async def set_execution_policy(
    session_factory: async_sessionmaker[AsyncSession],
    updates: dict[str, int | bool | None],
) -> None:
    """upsert；None → 删除该键（回退 env/Settings 默认）。单事务批量提交。"""
    async with session_factory() as session:
        rows = await session.execute(
            select(PlatformSetting).where(PlatformSetting.key.in_(list(updates)))
        )
        existing = {r.key: r for r in rows.scalars()}
        for key, val in updates.items():
            row = existing.get(key)
            if val is None:
                if row is not None:
                    await session.delete(row)
            else:
                text = "1" if val is True else ("0" if val is False else str(val))
                if row is None:
                    session.add(PlatformSetting(key=key, value=text))
                else:
                    row.value = text
        await session.commit()
