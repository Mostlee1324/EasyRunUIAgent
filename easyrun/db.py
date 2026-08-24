"""SQLAlchemy 异步引擎与会话管理。

SQLite 用于开发（零外部依赖），PostgreSQL 用于生产——两者共用同一套模型。
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

logger = logging.getLogger("easyrun.db")


class Base(DeclarativeBase):
    pass


def create_engine_and_session(database_url: str):
    kwargs: dict = {}
    if database_url.endswith(":memory:") or ":memory:" in database_url:
        # 内存库需共享单连接（测试场景）
        kwargs = {"poolclass": StaticPool, "connect_args": {"check_same_thread": False}}
    engine = create_async_engine(database_url, **kwargs)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


# 轻量迁移：create_all 不会给已存在的表加列，这里按需补列（替代引入 alembic）
_LIGHT_MIGRATIONS: list[tuple[str, str, str]] = [
    ("test_case", "target_url", "VARCHAR(500) DEFAULT ''"),
    ("test_case", "completion_checks", "JSON DEFAULT '[]'"),
    ("test_case", "case_no", "INTEGER"),
]


async def init_db(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for table, column, ddl in _LIGHT_MIGRATIONS:
            columns = await conn.run_sync(lambda c: {col["name"] for col in sa_inspect(c).get_columns(table)})
            if column not in columns:
                logger.info("轻量迁移：%s 增加列 %s", table, column)
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        await _backfill_case_no(conn)


async def _backfill_case_no(conn) -> None:
    """历史用例按创建时间回填整数编号（新用例由 API 自动分配 max+1）。"""
    rows = await conn.execute(
        text("SELECT id FROM test_case WHERE case_no IS NULL ORDER BY created_at")
    )
    ids = [r[0] for r in rows]
    if not ids:
        return
    start = (await conn.execute(text("SELECT COALESCE(MAX(case_no), 0) FROM test_case"))).scalar() or 0
    for offset, cid in enumerate(ids, 1):
        await conn.execute(
            text("UPDATE test_case SET case_no = :n WHERE id = :i"),
            {"n": start + offset, "i": cid},
        )
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_test_case_case_no ON test_case(case_no)"))
    logger.info("回填用例整数编号 %s 条（起始 #%s）", len(ids), start + 1)
