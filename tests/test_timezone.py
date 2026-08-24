"""时间链：DB 存取保持 UTC 感知，API 序列化带时区，前端才能正确显示本地时间。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from easyrun.models import TestCase, TestTask, utcnow


async def test_db_roundtrip_returns_utc_aware(sf):
    now = utcnow()
    async with sf() as session:
        case = TestCase(name="时区用例")
        session.add(case)
        await session.commit()
        await session.refresh(case)
        # 出库必须带 UTC 时区
        assert case.created_at.tzinfo is not None
        assert case.created_at.utcoffset() == timedelta(0)
        assert abs((case.created_at - now).total_seconds()) < 5

        # 显式写入非 UTC 的感知时间 → 归一化到 UTC 存储
        local_time = datetime(2026, 8, 15, 20, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        task = TestTask(run_id="r", case_id=case.id, created_at=local_time)
        session.add(task)
        await session.commit()
        await session.refresh(task)
        assert task.created_at.hour == 12  # 20:00+08:00 → 12:00 UTC
        assert task.created_at.tzinfo is not None


async def test_api_serialization_includes_timezone(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        r = client.post("/api/cases", json={"name": "序列化时区", "steps": ["s"]})
        created = r.json()["created_at"]
        assert created.endswith("+00:00") or created.endswith("Z"), created
