"""Agent 执行循环：探索 / 失败 / 自愈 / 固化回放。"""

from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy import select

from easyrun.agent import AgentRunner, CaseFailed
from easyrun.config import Settings
from easyrun.events import EV_ASSERTION, EV_CASE_FAILED, EV_CASE_PASSED, EV_HEAL_REQUEST, EV_HEAL_RESULT, EV_LLM_DECISION, EV_TOOL_CALL, EventEmitter
from easyrun.models import StepEvent
from tests.fakes import FakeBrowser, ScriptedLLM


def make_case(**kw):
    defaults = dict(
        name="演示用例", description="", mode="agentic",
        steps=["打开页面", "点击按钮"], assertions=[{"type": "text_contains", "target": "订单编号"}],
        resource_key="", tags=[], cured_actions=[], completion_checks=[],
    )
    defaults.update(kw)
    return SimpleNamespace(**defaults)


def make_runner(settings, llm, browser):
    return AgentRunner(settings, llm, browser_factory=lambda: browser)


async def run_case(settings, sf, llm, browser, case, task_id="t-1", session_id="s-1", should_stop=None, previous_error=""):
    emitter = EventEmitter(sf, task_id, session_id)
    runner = make_runner(settings, llm, browser)
    outcome = await runner.run(
        task_id=task_id, case=case, target_url="http://example.com/app",
        emitter=emitter, session_id=session_id, artifact_root=settings.resolved_artifact_dir,
        should_stop=should_stop, previous_error=previous_error,
    )
    return outcome, emitter


async def events(sf, task_id):
    async with sf() as session:
        rows = await session.execute(
            select(StepEvent).where(StepEvent.task_id == task_id).order_by(StepEvent.seq)
        )
        return list(rows.scalars())


async def test_click_link_by_name_under_sub_links(settings, sf):
    """按名称点击 sub-links 分组链接（用户场景：利好/利空/中性新闻，避免索引漂移）。"""
    llm = ScriptedLLM([
        {"tool": "browser_click_link", "args": {"name": "中性新闻"}, "reason": "点中性新闻链接"},
        {"tool": "finish", "args": {}, "reason": ""},
    ])
    browser = FakeBrowser(body="订单编号 X 中性新闻 (12)")
    browser.link_results["中性新闻"] = {"ok": True}
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "passed"
    assert outcome.actions == [{"tool": "browser_click_link", "args": {"name": "中性新闻"}}]


async def test_click_link_not_found_fails_immediately(settings, sf):
    """sub-links 中没有该链接 → 明确报错（失败即终止策略）。"""
    llm = ScriptedLLM([
        {"tool": "browser_click_link", "args": {"name": "不存在的链接"}, "reason": ""},
    ])
    browser = FakeBrowser(body="订单编号 X")
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "failed"
    assert "未找到" in outcome.error


async def test_wait_actions_recorded_for_cure(settings, sf):
    """回归：browser_wait 必须进入固化记录——动态渲染页面依赖等待时机。"""
    llm = ScriptedLLM([
        {"tool": "browser_navigate", "args": {"url": "http://example.com/app"}, "reason": ""},
        {"tool": "browser_wait", "args": {"ms": 2000}, "reason": "等待链接渲染"},
        {"tool": "finish", "args": {}, "reason": ""},
    ])
    browser = FakeBrowser(body="订单编号 X")
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "passed"
    assert [a["tool"] for a in outcome.actions] == ["browser_navigate", "browser_wait"]


async def test_agentic_happy_path(settings, sf):
    browser = FakeBrowser(body="订单编号 ER-1")
    llm = ScriptedLLM([
        {"tool": "browser_navigate", "args": {"url": "http://example.com/app"}, "reason": "打开"},
        {"tool": "browser_click", "args": {"index": 1}, "reason": "点登录"},
        {"tool": "browser_type", "args": {"index": 2, "text": "demo"}, "reason": "输入"},
        {"tool": "finish", "args": {"summary": "完成"}, "reason": ""},
    ])
    case = make_case()
    outcome, _ = await run_case(settings, sf, llm, browser, case)

    assert outcome.status == "passed"
    assert [a["tool"] for a in outcome.actions] == ["browser_navigate", "browser_click", "browser_type"]
    assert outcome.usage["llm_calls"] == 4
    evs = await events(sf, "t-1")
    types = [e.type for e in evs]
    assert types[0] == "session_start"
    assert types.count(EV_LLM_DECISION) == 4
    assert types.count(EV_TOOL_CALL) == 3
    assert types.count(EV_ASSERTION) == 1
    assert EV_CASE_PASSED in types
    assert browser.closed


async def test_agent_fail_tool(settings, sf):
    llm = ScriptedLLM([{"tool": "fail", "args": {"reason": "找不到登录入口"}, "reason": ""}])
    browser = FakeBrowser()
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())

    assert outcome.status == "failed"
    assert "找不到登录入口" in outcome.error
    evs = await events(sf, "t-1")
    assert evs[-1].type == EV_CASE_FAILED


async def test_unknown_tool_recovery(settings, sf):
    llm = ScriptedLLM([
        {"tool": "magic_do", "args": {}, "reason": ""},
        {"tool": "finish", "args": {}, "reason": ""},
    ])
    browser = FakeBrowser(body="订单编号 X")
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "passed"
    assert len(llm.calls) == 2  # 未知工具后重新决策


async def test_max_steps_exceeded(settings, sf):
    # 参数各异 → 不触发重复动作护栏，走步数上限
    llm = ScriptedLLM([{"tool": "browser_wait", "args": {"ms": i}, "reason": ""} for i in range(20)])
    browser = FakeBrowser()
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "failed"
    assert "最大步数" in outcome.error


async def test_repeated_identical_success_fails_fast(settings, sf):
    """行为环回归：同一动作只执行一次；重复请求先跳过，超过上限（2 次跳过）才终止。"""
    llm = ScriptedLLM([{"tool": "browser_click", "args": {"index": 5}, "reason": ""}] * 12)
    browser = FakeBrowser(body="订单编号 X")
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "failed"
    assert "反复请求" in outcome.error
    assert len(llm.calls) == 4  # 执行 1 次 + 跳过 2 次 + 第 3 次跳过请求时终止
    assert len(browser.clicks) == 1  # 重复请求的动作从未执行


async def test_single_click_then_finish_passes(settings, sf):
    """同一动作只执行一次（含聚焦等无变化场景）不终止，反馈提示勿重复。"""
    llm = ScriptedLLM([
        {"tool": "browser_click", "args": {"index": 5}, "reason": ""},
        {"tool": "finish", "args": {}, "reason": ""},
    ])
    browser = FakeBrowser(body="订单编号 X")
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "passed"
    last_messages = llm.calls[1]  # finish 决策的上下文含无变化提示
    assert any("请勿重复同一动作" in m.get("content", "") for m in last_messages)


async def test_repeated_clicks_skipped_even_with_page_progress(settings, sf):
    """单次执行策略：页面有进展时重复请求同样跳过（不重新执行），超过跳过上限终止。"""
    n = {"i": 0}

    def effect():
        n["i"] += 1
        return {"url": f"http://example.com/page/{n['i']}", "body": f"第{n['i']}页内容"}

    browser = FakeBrowser(body="订单编号 X")
    browser.click_effects = {5: effect}
    llm = ScriptedLLM(
        [{"tool": "browser_click", "args": {"index": 5}, "reason": ""}] * 5
        + [{"tool": "finish", "args": {}, "reason": ""}]
    )
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "failed"
    assert "反复请求" in outcome.error
    assert len(browser.clicks) == 1  # 页面有进展也不重复执行


async def test_skip_repeat_then_continue(settings, sf):
    """用户场景：点击「中性新闻」链接一次后，再被请求就跳过并继续下一步，而不是失败。"""
    llm = ScriptedLLM([
        {"tool": "browser_click", "args": {"index": 5}, "reason": "点击中性新闻链接"},
        {"tool": "browser_click", "args": {"index": 5}, "reason": "再点一次"},
        {"tool": "finish", "args": {}, "reason": "已跳过重复点击，继续后续步骤"},
    ])
    browser = FakeBrowser(body="订单编号 X")
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())

    assert outcome.status == "passed"  # 跳过而非失败
    assert len(browser.clicks) == 1    # 链接只真实点击了一次
    evs = await events(sf, "t-1")
    skipped = [e for e in evs if e.type == "tool_call" and e.payload.get("skipped")]
    assert len(skipped) == 1 and "跳过" in skipped[0].payload["reason"]
    last_messages = llm.calls[2]  # finish 决策的上下文包含跳过提示
    assert any("已跳过" in m.get("content", "") for m in last_messages)


async def test_no_change_detection_ignores_scroll(settings, sf):
    """回归：scrollIntoView 只改变可见性，不算页面变化——护栏必须能拦住这种重复。"""
    snap = {"url": "http://x/", "title": "t", "truncated": False, "els": [
        {"i": 0, "tag": "a", "text": "新闻链接", "ph": "", "type": "", "href": "", "inView": True},
        {"i": 1, "tag": "a", "text": "底部链接", "ph": "", "type": "", "href": "", "inView": False},
    ]}
    browser = FakeBrowser(body="订单编号 X", snapshot=snap)

    def effect():  # 模拟 scrollIntoView 副作用：文本不变，仅可见性翻转
        snap["els"][0]["inView"] = False
        snap["els"][1]["inView"] = True
        return {"ok": True}

    browser.click_effects = {0: effect}
    llm = ScriptedLLM([{"tool": "browser_click", "args": {"index": 0}, "reason": ""}] * 4)
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "failed"
    assert "反复请求" in outcome.error
    assert len(llm.calls) == 4  # 执行 1 次 + 跳过 2 次 + 第 3 次跳过请求时终止


def test_page_changed_text_fingerprint_only():
    """页面变化判断只比文本指纹（信息性提示用），URL/可见性不参与。"""
    from easyrun.agent import AgentRunner

    base = {"url": "http://x/", "els": [{"i": 0, "text": "已分析: # 条", "inView": True}]}
    assert not AgentRunner._page_changed(base, base)
    # 纯数字变化（行情/时间）不算变化
    a = {"url": "http://x/", "els": [{"i": 0, "text": "价格 123 元", "inView": True}]}
    b = {"url": "http://x/", "els": [{"i": 0, "text": "价格 456 元", "inView": False}]}
    assert not AgentRunner._page_changed(a, b)
    # 文本内容变化算变化
    c = {"url": "http://x/", "els": [{"i": 0, "text": "价格 123 元", "inView": True}]}
    d = {"url": "http://x/", "els": [{"i": 0, "text": "价格已更新", "inView": True}]}
    assert AgentRunner._page_changed(c, d)
    # URL 变化不参与判断（点击可能只是滚动，URL 不变；导航类变化由文本指纹体现）
    e = {"url": "http://x/page2", "els": [{"i": 0, "text": "已分析: # 条", "inView": True}]}
    assert not AgentRunner._page_changed(base, e)


async def test_completion_check_stops_before_repeated_click(settings, sf):
    """完成条件：目标已达成就不再做多余动作（用户场景：右上角出现标签后不再点链接）。"""
    llm = ScriptedLLM([
        {"tool": "browser_click", "args": {"index": 5}, "reason": "点击中性新闻链接"},
        {"tool": "browser_click", "args": {"index": 5}, "reason": "再点一次"},
        {"tool": "browser_click", "args": {"index": 5}, "reason": "再点一次"},
    ])
    browser = FakeBrowser(body="订单编号 X")
    browser.click_effects = {5: {"body": "订单编号 X 中性新闻（12）条"}}  # 点击后出现标签
    case = make_case(completion_checks=[{"type": "text_contains", "target": "中性新闻（"}])
    outcome, _ = await run_case(settings, sf, llm, browser, case)

    assert outcome.status == "passed"
    assert len(browser.clicks) == 1  # 第一次点击后条件满足，后续点击全部不发生
    assert len(llm.calls) == 1
    evs = await events(sf, "t-1")
    assert any(e.type == "goal_reached" for e in evs)


async def test_completion_check_satisfied_at_start_skips_all_actions(settings, sf):
    """开局就满足完成条件：不调用 LLM、不执行任何动作。"""
    llm = ScriptedLLM([{"tool": "browser_click", "args": {"index": 5}, "reason": ""}])
    browser = FakeBrowser(body="订单编号 X 中性新闻（12）条")
    case = make_case(completion_checks=[{"type": "text_contains", "target": "中性新闻（"}])
    outcome, _ = await run_case(settings, sf, llm, browser, case)

    assert outcome.status == "passed"
    assert len(llm.calls) == 0
    assert len(browser.clicks) == 0


async def test_completion_check_min_steps_gate(settings, sf):
    """min_steps：条件在动作数达标前不生效（目标状态=初始状态的场景）。"""
    llm = ScriptedLLM([
        {"tool": "browser_click", "args": {"index": 0}, "reason": "点日期"},
        {"tool": "browser_click", "args": {"index": 3}, "reason": "点利好新闻"},
        {"tool": "browser_wait", "args": {"ms": 500}, "reason": "等待滚动"},
        {"tool": "finish", "args": {}, "reason": ""},
    ])
    browser = FakeBrowser(body="订单编号 X 利好新闻 (6)")  # 目标文本一开始就存在
    case = make_case(completion_checks=[
        {"type": "text_contains", "target": "利好新闻 (", "min_steps": 3},
    ])
    outcome, _ = await run_case(settings, sf, llm, browser, case)
    # 必须执行完 3 个动作后条件才生效 → 两个点击都真实执行，然后 finish
    assert outcome.status == "passed"
    assert len(browser.clicks) == 2  # 两个点击都执行了（没有被提前终止）
    evs = await events(sf, "t-1")
    assert any(e.type == "goal_reached" for e in evs)


async def test_completion_check_in_deterministic_replay(settings, sf):
    """固化回放同样支持完成条件：条件满足后跳过剩余动作。"""
    llm = ScriptedLLM([])
    browser = FakeBrowser(body="订单编号 X")
    browser.click_effects = {5: {"body": "订单编号 X 中性新闻（1）"}}
    case = make_case(
        mode="deterministic",
        steps=[{"tool": "browser_click", "args": {"index": 5}}] * 3,
        completion_checks=[{"type": "text_contains", "target": "中性新闻（"}],
    )
    outcome, _ = await run_case(settings, sf, llm, browser, case)
    assert outcome.status == "passed"
    assert len(browser.clicks) == 1  # 第一次点击后满足，剩余 2 个动作跳过


async def test_previous_error_injected_into_brief(settings, sf):
    """重试时上次失败原因注入用例说明，帮助 LLM 换策略。"""
    llm = ScriptedLLM([{"tool": "finish", "args": {}, "reason": ""}])
    browser = FakeBrowser(body="订单编号 X")
    outcome, _ = await run_case(
        settings, sf, llm, browser, make_case(),
        previous_error="同一动作连续失败 5 次（browser_click）",
    )
    assert outcome.status == "passed"
    first = llm.calls[0]
    assert any("上一次执行失败" in m.get("content", "") and "连续失败" in m.get("content", "") for m in first)


def test_trim_keeps_history_summary():
    """裁剪历史时必须保留动作摘要，防止 LLM 遗忘已做动作。"""
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "brief"},
        {"role": "user", "content": "snap1"},
        {"role": "assistant", "content": json.dumps({"tool": "browser_click", "args": {"index": 5}, "reason": "x"})},
        {"role": "user", "content": "ok1"},
        {"role": "user", "content": "snap2"},
        {"role": "assistant", "content": json.dumps({"tool": "browser_type", "args": {"index": 1, "text": "a"}, "reason": "x"})},
        {"role": "user", "content": "ok2"},
        {"role": "user", "content": "snap3"},
        {"role": "assistant", "content": json.dumps({"tool": "browser_wait", "args": {"ms": 1}, "reason": "x"})},
        {"role": "user", "content": "ok3"},
    ]
    from easyrun.agent import AgentRunner

    AgentRunner._trim(messages, keep_tail=4)
    assert messages[0]["role"] == "system" and messages[1]["role"] == "user"
    summary = next(m["content"] for m in messages if "历史动作摘要" in m["content"])
    assert "browser_click" in summary and "browser_type" in summary


async def test_should_stop_aborts_loop(settings, sf):
    """取消钩子：执行中每步检查，命中即停止，不再调用 LLM。"""
    llm = ScriptedLLM([{"tool": "browser_wait", "args": {"ms": 1}, "reason": ""}] * 10)
    browser = FakeBrowser(body="订单编号 X")
    calls = {"n": 0}

    async def should_stop():
        calls["n"] += 1
        return calls["n"] >= 2  # 第 2 步起停止

    outcome, _ = await run_case(settings, sf, llm, browser, make_case(), should_stop=should_stop)
    assert outcome.status == "failed"
    assert outcome.error == "任务已取消"
    assert len(llm.calls) == 1  # 只执行了 1 步就被取消


async def test_action_failure_terminates_immediately(settings, sf):
    """失败即终止：同一动作失败不重试、不换方式，立即结束（用户要求）。"""
    llm = ScriptedLLM([{"tool": "browser_type", "args": {"index": 1, "text": "demo"}, "reason": ""}] * 10)
    browser = FakeBrowser()
    browser.type_fail_keys.add("index 1")  # type_text 恒失败
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "failed"
    assert "执行失败" in outcome.error
    assert len(llm.calls) == 1  # 第一次失败立即终止，不重试不换策略


async def test_healing_disabled_by_default_fails_immediately(settings, sf):
    """默认 heal_attempts=0：断言失败直接判失败，不自愈重试（单次执行策略）。"""
    s = Settings(
        database_url="sqlite+aiosqlite:///:memory:", workers=0,
        artifact_dir=settings.resolved_artifact_dir, heal_attempts=0,
        max_steps_per_case=10,
    )
    llm = ScriptedLLM([
        {"tool": "browser_navigate", "args": {"url": "http://example.com/app"}, "reason": ""},
        {"tool": "finish", "args": {}, "reason": ""},
    ])
    browser = FakeBrowser(body="页面没有订单")  # 断言必失败
    outcome, _ = await run_case(s, sf, llm, browser, make_case())
    assert outcome.status == "failed"
    assert "断言失败" in outcome.error
    assert outcome.usage["heals"] == 0
    assert len(llm.calls) == 2  # 导航 + finish，没有自愈轮


async def test_healing_success(settings, sf):
    # 主循环：导航 → finish；断言失败 → 自愈：点击修复 → 断言通过
    llm = ScriptedLLM([
        {"tool": "browser_navigate", "args": {"url": "http://example.com/app"}, "reason": ""},
        {"tool": "finish", "args": {}, "reason": ""},
        # 自愈轮
        {"tool": "browser_click", "args": {"index": 4}, "reason": "重新提交订单"},
        {"tool": "finish", "args": {}, "reason": ""},
    ])
    browser = FakeBrowser(body="页面无订单信息")
    browser.click_effects = {4: {"body": "订单编号 ER-99 已生成"}}
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())

    assert outcome.status == "passed"
    assert outcome.usage["heals"] == 1
    assert outcome.healed_locators == [{
        "page": "http://example.com/app", "element_key": "订单编号",
        "strategy": "text", "value": "订单编号",
    }]
    evs = await events(sf, "t-1")
    types = [e.type for e in evs]
    assert EV_HEAL_REQUEST in types
    assert any(e.type == EV_HEAL_RESULT and e.payload.get("ok") for e in evs)


async def test_healing_fails(settings, sf):
    llm = ScriptedLLM([
        {"tool": "browser_navigate", "args": {"url": "http://example.com/app"}, "reason": ""},
        {"tool": "finish", "args": {}, "reason": ""},
        {"tool": "fail", "args": {"reason": "页面本身坏了"}, "reason": ""},
        {"tool": "fail", "args": {"reason": "页面本身坏了"}, "reason": ""},
    ])
    browser = FakeBrowser(body="没有订单")
    outcome, _ = await run_case(settings, sf, llm, browser, make_case())
    assert outcome.status == "failed"
    assert "断言失败" in outcome.error


async def test_deterministic_replay(settings, sf):
    llm = ScriptedLLM([])  # 回放模式不应调用 LLM
    browser = FakeBrowser(body="订单编号 R-1")
    case = make_case(
        mode="deterministic",
        steps=[
            {"tool": "browser_navigate", "args": {"url": "http://old-url/"}},
            {"tool": "browser_click", "args": {"index": 2}},
        ],
    )
    outcome, _ = await run_case(settings, sf, llm, browser, case, task_id="t-2", session_id="s-2")
    assert outcome.status == "passed"
    assert browser.navigated == ["http://example.com/app"]  # 回放替换目标地址
    assert len(llm.calls) == 0
    assert outcome.usage["steps"] == 3  # 2 个动作 + 1 条断言


async def test_deterministic_replay_failure(settings, sf):
    llm = ScriptedLLM([])
    browser = FakeBrowser(body="")
    browser.click_effects = {2: {"ok": False, "error": "index 2 不存在"}}
    case = make_case(mode="deterministic", steps=[{"tool": "browser_click", "args": {"index": 2}}])
    outcome, _ = await run_case(settings, sf, llm, browser, case)
    assert outcome.status == "failed"
    assert "固化动作" in outcome.error
