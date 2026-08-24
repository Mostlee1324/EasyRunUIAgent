"""轻量迁移：已存在的旧表缺列时，init_db 自动补列。"""

from __future__ import annotations

from sqlalchemy import text

from easyrun.db import create_engine_and_session, init_db


async def test_init_db_adds_missing_target_url_column(tmp_path):
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'old.db'}"
    engine, _ = create_engine_and_session(db_url)

    # 模拟旧版 schema：test_case 没有 target_url 列
    async with engine.begin() as conn:
        await conn.execute(text(
            "CREATE TABLE test_case ("
            "id VARCHAR(32) PRIMARY KEY, name VARCHAR(200), description TEXT,"
            "mode VARCHAR(20), steps JSON, cured_actions JSON, assertions JSON,"
            "resource_key VARCHAR(100), tags JSON, version INTEGER,"
            "created_at DATETIME, updated_at DATETIME)"
        ))

    await init_db(engine)  # create_all + 轻量迁移（列补全 + case_no 回填）

    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO test_case (id, name, target_url) VALUES ('c1', '旧用例', 'http://x/')"
        ))
        row = (await conn.execute(text("SELECT target_url FROM test_case"))).scalar()
        assert row == "http://x/"

    # 历史用例回填整数编号
    await init_db(engine)
    async with engine.begin() as conn:
        no = (await conn.execute(text("SELECT case_no FROM test_case WHERE id = 'c1'"))).scalar()
        assert no == 1

    # 幂等：再次 init_db 不报错、不重复回填
    await init_db(engine)
    await engine.dispose()
