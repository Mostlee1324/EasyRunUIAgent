"""REST API 全链路（TestClient 运行 lifespan，workers=0）。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from easyrun.models import CASE_MODE_DETERMINISTIC, StepEvent, TestRun, TestTask


@pytest_asyncio.fixture
async def client(app):
    """手动运行 lifespan：初始化库、启动调度器（无 Worker）。"""
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


def _mk_case_body(**kw):
    body = {
        "name": "演示用例", "description": "", "steps": ["打开页面", "点击按钮"],
        "assertions": [{"type": "text_contains", "target": "订单编号"}], "resource_key": "", "tags": [],
    }
    body.update(kw)
    return body


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    h = r.json()
    assert h["queue"] == "memory" and h["llm_configured"] is True and h["workers"] == 0


async def test_case_no_auto_increment(client):
    r1 = await client.post("/api/cases", json=_mk_case_body(name="编号一"))
    r2 = await client.post("/api/cases", json=_mk_case_body(name="编号二"))
    n1, n2 = r1.json()["case_no"], r2.json()["case_no"]
    assert isinstance(n1, int) and n2 == n1 + 1  # 整数递增


async def test_case_completion_checks_roundtrip(client):
    r = await client.post("/api/cases", json=_mk_case_body(
        completion_checks=[{"type": "text_in_view", "target": "中性新闻（"}],
    ))
    case = r.json()
    assert case["completion_checks"][0]["target"] == "中性新闻（"
    r = await client.put(f"/api/cases/{case['id']}", json={"completion_checks": []})
    assert r.json()["completion_checks"] == []


async def test_case_target_url_roundtrip(client):
    r = await client.post("/api/cases", json=_mk_case_body(target_url="http://my-app:9000/login"))
    case = r.json()
    assert case["target_url"] == "http://my-app:9000/login"

    # 运行时不传网址 → 回落用例默认网址
    r = await client.post(f"/api/cases/{case['id']}/run", json={"target_url": ""})
    run = r.json()
    assert run["target_url"] == "http://my-app:9000/login"

    # 运行时传网址 → 覆盖用例默认值
    r = await client.post(f"/api/cases/{case['id']}/run", json={"target_url": "http://override/"})
    assert r.json()["target_url"] == "http://override/"

    # 编辑用例改网址
    r = await client.put(f"/api/cases/{case['id']}", json={"target_url": "http://new-url/"})
    assert r.json()["target_url"] == "http://new-url/"


async def test_case_crud_and_validation(client):
    r = await client.post("/api/cases", json=_mk_case_body())
    assert r.status_code == 200
    case = r.json()
    assert case["mode"] == "agentic" and case["version"] == 1

    r = await client.get("/api/cases")
    assert len(r.json()) == 1

    r = await client.put(f"/api/cases/{case['id']}", json={"name": "改名", "steps": ["新步骤"]})
    assert r.status_code == 200 and r.json()["name"] == "改名" and r.json()["version"] == 2

    r = await client.post("/api/cases", json=_mk_case_body(assertions=[{"type": "bogus", "target": "x"}]))
    assert r.status_code == 400 and "断言" in r.json()["detail"]

    r = await client.delete(f"/api/cases/{case['id']}")
    assert r.json()["ok"] is True


async def test_submit_run_and_report_flow(client, app):
    r = await client.post("/api/cases", json=_mk_case_body())
    case_id = r.json()["id"]

    r = await client.post(f"/api/cases/{case_id}/run", json={"target_url": "http://x/", "env": "demo"})
    assert r.status_code == 200
    run_id = r.json()["id"]

    r = await client.get(f"/api/runs/{run_id}")
    detail = r.json()
    assert detail["run"]["status"] == "running"
    assert detail["tasks"][0]["status"] == "queued"

    # 模拟 Worker 完成（API 测试不启动 Worker），并手动收口
    async with app.state.sf() as session:
        task = (await session.execute(select(TestTask))).scalars().first()
        task.status = "passed"
        session.add(StepEvent(task_id=task.id, type="case_passed", payload={"usage": {}}))
        run = await session.get(TestRun, run_id)
        run.status = "passed"
        run.stats = {"total": 1, "passed": 1, "failed": 0, "quarantined": 0, "skipped": 0, "tokens": 0}
        run.finished_at = run.started_at
        await session.commit()
        task_id = task.id

    r = await client.get(f"/api/runs/{run_id}/report")
    report = r.json()
    assert report["run"]["status"] == "passed"
    assert report["tasks"][0]["task"]["id"] == task_id
    assert report["tasks"][0]["events"][0]["type"] == "case_passed"

    # 事件流轮询游标
    r = await client.get(f"/api/runs/{run_id}/events?after=0&task_id={task_id}")
    page = r.json()
    assert len(page["events"]) == 1 and page["next_after"] == page["events"][0]["seq"]
    r = await client.get(f"/api/runs/{run_id}/events?after={page['next_after']}&task_id={task_id}")
    assert r.json()["events"] == []

    # Allure 导出
    r = await client.post(f"/api/runs/{run_id}/allure")
    assert r.json()["ok"] is True

    # 趋势
    r = await client.get("/api/trends")
    assert r.json()["total_runs"] == 1 and r.json()["pass_rate"] == 1.0


async def test_cure_flow(client, app):
    r = await client.post("/api/cases", json=_mk_case_body())
    case_id = r.json()["id"]
    actions = [{"tool": "browser_navigate", "args": {"url": "http://x/"}},
               {"tool": "browser_click", "args": {"index": 1}}]
    async with app.state.sf() as session:
        from easyrun.models import TestCase
        case = await session.get(TestCase, case_id)
        case.cured_actions = actions
        await session.commit()

    r = await client.post(f"/api/cases/{case_id}/cure")
    assert r.status_code == 200
    cured = r.json()
    assert cured["mode"] == CASE_MODE_DETERMINISTIC
    assert cured["steps"] == actions


async def test_cancel_run_end_to_end(client, app):
    r = await client.post("/api/cases", json=_mk_case_body(name="待取消用例"))
    case_id = r.json()["id"]
    r = await client.post(f"/api/cases/{case_id}/run", json={"target_url": "http://x/"})
    run_id = r.json()["id"]

    r = await client.post(f"/api/runs/{run_id}/cancel")
    assert r.json()["ok"] is True

    async with app.state.sf() as session:
        from sqlalchemy import select
        task = (await session.execute(select(TestTask))).scalars().first()
        assert task.status == "skipped"

    await app.state.orchestrator._tick()  # 收口
    r = await client.get(f"/api/runs/{run_id}")
    assert r.json()["run"]["status"] == "cancelled"

    # 已终结的 run 拒绝取消
    r = await client.post(f"/api/runs/{run_id}/cancel")
    assert r.status_code == 409


async def test_rerun_failed_endpoint(client, app):
    # 造一个「1 过 1 挂」的已终结 run
    r = await client.post("/api/cases", json=_mk_case_body(name="用例A"))
    case_a = r.json()["id"]
    r = await client.post("/api/cases", json=_mk_case_body(name="用例B"))
    case_b = r.json()["id"]
    r = await client.post(f"/api/cases/{case_a}/run", json={"target_url": "http://x/"})
    run_id = r.json()["id"]
    async with app.state.sf() as session:
        from sqlalchemy import select
        from easyrun.models import TestRun
        tasks = (await session.execute(select(TestTask))).scalars().all()
        tasks[0].status = "passed"
        session.add(TestTask(run_id=run_id, case_id=case_b, case_name="用例B", status="failed", error="x"))
        run = await session.get(TestRun, run_id)
        run.status = "failed"
        run.stats = {"total": 2, "passed": 1, "failed": 1, "quarantined": 0, "skipped": 0, "tokens": 0}
        await session.commit()

    r = await client.post(f"/api/runs/{run_id}/rerun-failed")
    assert r.status_code == 200
    new_run = r.json()
    assert new_run["case_ids"] == [case_b]  # 只有失败用例
    detail = (await client.get(f"/api/runs/{new_run['id']}")).json()
    assert len(detail["tasks"]) == 1 and detail["tasks"][0]["case_id"] == case_b


async def test_runs_pagination(client, app):
    # 造 25 条执行记录（直接落库，避免真实执行）
    from datetime import timedelta
    from easyrun.models import TestRun, utcnow

    async with app.state.sf() as session:
        base = utcnow()
        for i in range(25):
            session.add(TestRun(case_ids=["x"], target_url="http://x/", status="passed",
                                started_at=base - timedelta(minutes=i)))
        await session.commit()

    r = await client.get("/api/runs?page=1&page_size=20")
    page = r.json()
    assert page["total"] == 25 and len(page["items"]) == 20 and page["page"] == 1
    r = await client.get("/api/runs?page=2&page_size=20")
    page2 = r.json()
    assert len(page2["items"]) == 5
    r = await client.get("/api/runs?page=1&page_size=100")
    assert len(r.json()["items"]) == 25
    # 越界页返回空列表而非报错
    r = await client.get("/api/runs?page=99&page_size=20")
    assert r.json()["items"] == []


async def test_settings_default_target_url(client):
    r = await client.get("/api/settings")
    assert r.json()["default_target_url"] == ""
    r = await client.put("/api/settings", json={"default_target_url": "http://www.mostoo.com"})
    assert r.json()["default_target_url"] == "http://www.mostoo.com"
    r = await client.get("/api/settings")
    assert r.json()["default_target_url"] == "http://www.mostoo.com"
    # 提交执行不填网址 → 回落平台默认
    rc = await client.post("/api/cases", json=_mk_case_body(name="默认网址用例"))
    run = await client.post(f"/api/cases/{rc.json()['id']}/run", json={"target_url": ""})
    assert run.json()["target_url"] == "http://www.mostoo.com"


async def test_delete_run_and_batch_delete(client, app):
    from sqlalchemy import select
    from easyrun.models import AgentSession, StepEvent, TestTask

    # 造两条 run，各带任务/事件/会话
    r1 = await client.post("/api/cases", json=_mk_case_body(name="待删一"))
    r2 = await client.post("/api/cases", json=_mk_case_body(name="待删二"))
    run_a = (await client.post(f"/api/cases/{r1.json()['id']}/run", json={"target_url": "http://x/"})).json()
    run_b = (await client.post(f"/api/cases/{r2.json()['id']}/run", json={"target_url": "http://y/"})).json()
    async with app.state.sf() as session:
        task_a = (await session.execute(select(TestTask).where(TestTask.run_id == run_a["id"]))).scalars().first()
        session.add(StepEvent(task_id=task_a.id, type="tool_call", payload={"ok": True}))
        session.add(AgentSession(task_id=task_a.id))
        await session.commit()

    # 单条删除：run + 任务 + 事件全部清掉
    r = await client.delete(f"/api/runs/{run_a['id']}")
    assert r.json()["ok"] is True
    r = await client.get(f"/api/runs/{run_a['id']}")
    assert r.status_code == 404
    async with app.state.sf() as session:
        assert not (await session.execute(select(TestTask).where(TestTask.run_id == run_a["id"]))).scalars().all()
        assert not (await session.execute(select(StepEvent).where(StepEvent.task_id == task_a.id))).scalars().all()

    # 批量删除
    r = await client.post("/api/runs/batch-delete", json={"run_ids": [run_b["id"], "不存在的id"]})
    assert r.json()["deleted"] == 1
    r = await client.get(f"/api/runs/{run_b['id']}")
    assert r.status_code == 404
    # 删除不存在的 → 404
    r = await client.delete("/api/runs/不存在")
    assert r.status_code == 404


async def test_plan_run_and_invalid_run_requests(client):
    r = await client.post("/api/cases", json=_mk_case_body(name="用例A"))
    case_id = r.json()["id"]
    r = await client.post("/api/plans", json={"name": "冒烟", "case_ids": [case_id]})
    plan_id = r.json()["id"]

    # 二选一校验
    r = await client.post("/api/runs", json={"case_id": case_id, "plan_id": plan_id})
    assert r.status_code == 400
    r = await client.post("/api/runs", json={})
    assert r.status_code == 400

    r = await client.post(f"/api/plans/{plan_id}/run", json={"target_url": "http://y/"})
    assert r.status_code == 200
    run_id = r.json()["id"]
    r = await client.get(f"/api/runs/{run_id}")
    assert r.json()["tasks"][0]["case_name"] == "用例A"

    r = await client.get("/api/locators")
    assert r.json() == []
