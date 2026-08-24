"""平台级配置（键值对，入库持久化）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from easyrun.models import PlatformSetting

# 默认执行目标地址：运行用例/计划未填网址时的兜底
DEFAULT_TARGET_URL = "default_target_url"


async def get_default_target_url(session_factory: async_sessionmaker[AsyncSession]) -> str:
    async with session_factory() as session:
        row = await session.get(PlatformSetting, DEFAULT_TARGET_URL)
        return (row.value if row else "") or ""


async def set_default_target_url(session_factory: async_sessionmaker[AsyncSession], url: str) -> str:
    url = (url or "").strip()
    async with session_factory() as session:
        row = await session.get(PlatformSetting, DEFAULT_TARGET_URL)
        if row is None:
            row = PlatformSetting(key=DEFAULT_TARGET_URL, value=url)
            session.add(row)
        else:
            row.value = url
        await session.commit()
    return url
