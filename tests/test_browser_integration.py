"""真实浏览器集成：快照/点击流水线 + 确定性回放端到端（需要 chromium）。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

pytestmark = pytest.mark.browser

pytest.importorskip("playwright.async_api")

from easyrun.agent import AgentRunner
from easyrun.browser import BrowserSession
from easyrun.events import EventEmitter
from tests.fakes import ScriptedLLM

DEMO_DIR = Path(__file__).parent.parent / "demo"


@pytest_asyncio.fixture
async def browser(settings):
    try:
        b = await BrowserSession(settings).start()
    except Exception as e:  # 未安装 chromium 等
        pytest.skip(f"浏览器不可用: {e}")
    yield b
    await b.close()


def find(snap: dict, text: str) -> int:
    for el in snap["els"]:
        if text in (el.get("text") or ""):
            return el["i"]
    raise AssertionError(f"快照中找不到文本 {text!r}: {[e['text'] for e in snap['els']]}")


async def test_snapshot_click_pipeline(browser):
    """核心原语：快照 → 按索引点击 → 页面状态变化 → 断言。"""
    demo = (DEMO_DIR / "index.html").as_uri()
    await browser.new_page()
    assert (await browser.navigate(demo))["ok"]

    snap = await browser.snapshot()
    assert any("登" in e["text"] for e in snap["els"])

    login_idx = find(snap, "登")
    r = await browser.click(login_idx)
    assert r["ok"], r

    snap = await browser.snapshot()
    add_idx = find(snap, "加入购物车")
    await browser.click(add_idx)
    await browser.click(find(await browser.snapshot(), "去结算"))

    await browser.wait(500)
    assert "checkout" in await browser.url()
    assert "订单编号" in await browser.body_text()


async def test_type_text_js_arg_passing(browser):
    """回归：evaluate 单参约定——type_text 传入 [index, text] 数组并正确解构。"""
    demo = (DEMO_DIR / "index.html").as_uri()
    await browser.new_page()
    await browser.navigate(demo)
    snap = await browser.snapshot()
    username_idx = find(snap, "demo")  # 页面预填 value 优先于 placeholder
    r = await browser.type_text(username_idx, "demouser")
    assert r.get("ok"), r
    snap = await browser.snapshot()
    assert any("demouser" in (e.get("text") or "") for e in snap["els"])


async def test_click_link_under_sub_links_on_real_page(browser, tmp_path):
    """真实 DOM：class=sub-links 内按名称点击。"""
    page = tmp_path / "sublinks.html"
    page.write_text(
        """<html><body>
        <div id="hit-log">未点击</div>
        <div class="sub-links">
          <a href="#p" onclick="document.getElementById('hit-log').textContent='已点利好新闻'">利好新闻</a>
          <a href="#n" onclick="document.getElementById('hit-log').textContent='已点利空新闻'">利空新闻</a>
          <a href="#x" onclick="document.getElementById('hit-log').textContent='已点中性新闻'">中性新闻</a>
        </div>
        </body></html>""",
        encoding="utf-8",
    )
    await browser.new_page()
    await browser.navigate(page.as_uri())
    r = await browser.click_link("中性新闻")
    assert r.get("ok") and "中性新闻" in r.get("clicked", "")
    assert "已点中性新闻" in await browser.body_text()
    r2 = await browser.click_link("不存在的")
    assert not r2.get("ok") and "未找到" in r2["error"]


async def test_text_near_top_on_real_page(browser, tmp_path):
    """位置断言：真实滚动后，标签出现在窗口上方才通过。"""
    from easyrun.assertions import run_assertion

    page = tmp_path / "tall_page.html"
    page.write_text(
        """<html><body>
        <div style="height:300px"></div>
        <div id="section">中性新闻（12）条</div>
        <div style="height:2000px"></div>
        </body></html>""",
        encoding="utf-8",
    )
    await browser.new_page()
    await browser.navigate(page.as_uri())

    # 未滚动：标签在窗口外（300px 处仍在 900px 视口内? 视口高 900 → 300px 处是可见的！）
    # 因此改为：标签初始就在上方 → 通过；滚到页面底部 → 标签在窗口外 → 失败
    r1 = await run_assertion(browser, {"type": "text_near_top", "target": "中性新闻（"})
    assert r1.ok, r1.detail
    await browser._page.evaluate("window.scrollTo(0, 2000)")
    r2 = await run_assertion(browser, {"type": "text_near_top", "target": "中性新闻（"})
    assert not r2.ok
    # 滚回去 → 再次通过
    await browser._page.evaluate("window.scrollTo(0, 0)")
    r3 = await run_assertion(browser, {"type": "text_near_top", "target": "中性新闻（"})
    assert r3.ok


async def test_value_compare_strong_tag_and_sibling_forms(browser, tmp_path):
    """用户场景回归：<span>已分析: <strong>2363</strong> 条</span> 及兄弟元素形态。"""
    from easyrun.assertions import run_assertion

    page = tmp_path / "strong_case.html"
    page.write_text(
        """<html><body>
        <div id="same"><span>已分析: <strong>2363</strong> 条</span></div>
        <div id="siblings"><span>已处理:</span><strong>88</strong><span> 条</span></div>
        </body></html>""",
        encoding="utf-8",
    )
    await browser.new_page()
    await browser.navigate(page.as_uri())

    r = await run_assertion(browser, {"type": "value_compare", "target": "已分析", "expected": "> 0"})
    assert r.ok and float(r.actual) == 2363, r.detail
    r2 = await run_assertion(browser, {"type": "value_compare", "target": "已处理", "expected": ">= 80"})
    assert r2.ok and float(r2.actual) == 88, r2.detail
    r3 = await run_assertion(browser, {"type": "value_compare", "target": "已分析", "expected": "> 9999"})
    assert not r3.ok


async def test_value_compare_against_real_page(browser, settings, sf):
    """数值比较断言：真实 DOM 中「测试商品 A」后的价格 9.90。"""
    from easyrun.assertions import run_assertion

    demo = (DEMO_DIR / "index.html").as_uri()
    await browser.new_page()
    await browser.navigate(demo)
    r = await run_assertion(browser, {"type": "value_compare", "target": "测试商品 A", "expected": "> 5"})
    assert r.ok, r.detail
    assert float(r.actual) == 9.9
    r2 = await run_assertion(browser, {"type": "value_compare", "target": "测试商品 A", "expected": ">= 100"})
    assert not r2.ok


async def test_exported_code_runs_standalone(settings, sf, browser, tmp_path):
    """终极验证：固化动作导出的 Playwright 代码，脱离平台独立运行通过。"""
    from easyrun.codegen import export_case_code
    from easyrun.models import TestCase

    demo = (DEMO_DIR / "index.html").as_uri()
    # 发现动作（登录 → 加购 → 结算）
    await browser.new_page()
    await browser.navigate(demo)
    snap = await browser.snapshot()
    actions = [{"tool": "browser_click", "args": {"index": find(snap, "登")}}]
    await browser.click(find(snap, "登"))
    snap2 = await browser.snapshot()
    actions.append({"tool": "browser_click", "args": {"index": find(snap2, "加入购物车")}})
    await browser.click(find(snap2, "加入购物车"))
    snap3 = await browser.snapshot()
    actions.append({"tool": "browser_click", "args": {"index": find(snap3, "去结算")}})

    case = TestCase(
        name="导出独立运行验证", mode="agentic", target_url=demo,
        cured_actions=actions,
        assertions=[
            {"type": "url_contains", "target": "checkout"},
            {"type": "text_contains", "target": "订单编号"},
            {"type": "value_compare", "target": "已分析", "expected": "> 0"},
        ],
    )
    async with sf() as session:
        session.add(case)
        await session.commit()
        cid = case.id

    code, filename = await export_case_code(sf, settings, cid)
    script = tmp_path / filename
    script.write_text(code, encoding="utf-8")

    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True, text=True, timeout=120, env=os.environ.copy(),
    )
    assert proc.returncode == 0, f"生成代码运行失败:\n{proc.stdout}\n{proc.stderr}"
    assert "PASS: 导出独立运行验证" in proc.stdout


async def test_deterministic_end_to_end(settings, sf, browser):
    """Agent 循环 + 真实浏览器 + 确定性回放 + 真实断言，全链路。"""
    demo = (DEMO_DIR / "index.html").as_uri()
    await browser.new_page()
    await browser.navigate(demo)
    snap = await browser.snapshot()

    actions = [
        {"tool": "browser_click", "args": {"index": find(snap, "登")}},
    ]
    # 登录后页面变化，需要重新发现商品按钮 —— 直接在浏览器上模拟一次登录拿到索引
    await browser.click(find(snap, "登"))
    snap2 = await browser.snapshot()
    actions.append({"tool": "browser_click", "args": {"index": find(snap2, "加入购物车")}})
    await browser.click(find(snap2, "加入购物车"))
    snap3 = await browser.snapshot()
    actions.append({"tool": "browser_click", "args": {"index": find(snap3, "去结算")}})

    # 重新打开页面，交给 AgentRunner 以确定性模式回放
    await browser.new_page()
    case = SimpleNamespace(
        name="真实浏览器回放", description="", mode="deterministic", steps=actions,
        assertions=[{"type": "url_contains", "target": "checkout"},
                    {"type": "text_contains", "target": "订单编号"}],
        resource_key="", tags=[], cured_actions=[], completion_checks=[],
    )
    emitter = EventEmitter(sf, "t-real", "s-real")
    runner = AgentRunner(settings, ScriptedLLM([]), browser_factory=lambda: browser)
    outcome = await runner.run(
        task_id="t-real", case=case, target_url=demo,
        emitter=emitter, session_id="s-real", artifact_root=settings.artifact_dir,
    )
    assert outcome.status == "passed", outcome.error
    assert len(outcome.actions) == 0  # 回放不调用 LLM

    async with sf() as session:
        from sqlalchemy import select
        from easyrun.models import StepEvent
        rows = await session.execute(
            select(StepEvent).where(StepEvent.task_id == "t-real").order_by(StepEvent.seq)
        )
        evs = list(rows.scalars())
        assert any(e.type == "case_passed" for e in evs)
        assert any(e.type == "assertion" and e.payload.get("ok") for e in evs)
