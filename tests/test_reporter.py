"""报告中心：归因、聚合、趋势、Allure 导出。"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from easyrun.llm import LLMError
from easyrun.models import (
    FAULT_PRODUCT_BUG,
    AgentSession,
    FailureAnalysis,
    StepEvent,
    TestCase,
    TestRun,
    TestTask,
)
from easyrun.reporter import analyze_task_failure, build_run_report, export_allure, get_trends


class FakeAnalysisLLM:
    def __init__(self, obj=None, error=None):
        self.obj = obj or {
            "category": FAULT_PRODUCT_BUG, "confidence": 0.9,
            "root_cause": "结算接口 500", "defect_draft": {
                "title": "结算失败", "steps": "登录→结算", "expected": "订单出现", "actual": "页面报错",
            },
        }
        self.error = error

    async def chat_json(self, messages, **kwargs):
        if self.error:
            raise self.error
        return self.obj, None


async def seed_task(sf, status="failed", error="boom"):
    case = TestCase(name="用例X", steps=["s1"], assertions=[{"type": "text_contains", "target": "t"}])
    async with sf() as session:
        session.add(case)
        await session.flush()
        run = TestRun(case_ids=[case.id], status="running")
        session.add(run)
        await session.flush()
        task = TestTask(run_id=run.id, case_id=case.id, status=status, error=error)
        session.add(task)
        await session.flush()
        session.add(StepEvent(task_id=task.id, type="tool_call", payload={"tool": "browser_click", "ok": False, "error": "x"}))
        session.add(StepEvent(task_id=task.id, type="assertion", payload={"type": "text_contains", "ok": False, "detail": "缺少"}))
        await session.commit()
        return run.id, task.id


async def test_analyze_task_failure(settings, sf, monkeypatch):
    import easyrun.reporter as reporter

    monkeypatch.setattr(reporter, "DeepSeekClient", lambda s: FakeAnalysisLLM())
    run_id, task_id = await seed_task(sf)
    row = await analyze_task_failure(sf, settings, task_id, run_id)
    assert row.category == FAULT_PRODUCT_BUG
    assert row.confidence == 0.9
    assert row.defect_draft["title"] == "结算失败"


async def test_analyze_fallback_when_llm_down(settings, sf, monkeypatch):
    import easyrun.reporter as reporter

    monkeypatch.setattr(reporter, "DeepSeekClient", lambda s: FakeAnalysisLLM(error=LLMError("网络挂了")))
    run_id, task_id = await seed_task(sf)
    row = await analyze_task_failure(sf, settings, task_id, run_id)
    assert row.category == "agent_error"
    assert "LLM 不可用" in row.root_cause


async def test_analyze_invalid_category_falls_back(settings, sf, monkeypatch):
    import easyrun.reporter as reporter

    monkeypatch.setattr(reporter, "DeepSeekClient", lambda s: FakeAnalysisLLM(obj={"category": "bogus", "confidence": 0.5, "root_cause": "r", "defect_draft": {}}))
    run_id, task_id = await seed_task(sf)
    row = await analyze_task_failure(sf, settings, task_id, run_id)
    assert row.category == "agent_error"


async def test_build_run_report_and_trends(settings, sf, monkeypatch):
    import easyrun.reporter as reporter

    monkeypatch.setattr(reporter, "DeepSeekClient", lambda s: FakeAnalysisLLM())
    run_id, task_id = await seed_task(sf, status="passed", error="")
    async with sf() as session:
        session.add(AgentSession(task_id=task_id, usage={"prompt_tokens": 100, "completion_tokens": 50}))
        await session.commit()
    report = await build_run_report(sf, run_id)
    assert report.run.id == run_id
    assert len(report.tasks) == 1 and len(report.tasks[0].events) == 2
    trends = await get_trends(sf)
    assert trends.total_tasks == 1 and trends.total_tokens == 150


async def test_export_allure(settings, sf):
    run_id, task_id = await seed_task(sf, status="failed", error="boom")
    # 放一张截图工件
    png = settings.artifact_dir / "sessions" / "s-1" / "s_0000.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG")
    async with sf() as session:
        session.add(StepEvent(task_id=task_id, type="screenshot", artifact="sessions/s-1/s_0000.png"))
        await session.commit()

    out = await export_allure(sf, settings, run_id)
    results = list(out.glob("*-result.json"))
    assert len(results) == 1
    data = json.loads(results[0].read_text())
    assert data["status"] == "failed"
    assert data["steps"][0]["status"] == "failed"  # tool_call 失败
    assert any(a["name"].startswith("步骤截图") for a in data["attachments"])
