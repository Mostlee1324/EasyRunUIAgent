"""用例 → 独立 Playwright 自动化代码（回答「把用例变成自动化代码」）。

固化动作里的索引只在平台快照体系内有效，直接生成代码没有意义。
导出流程：用真实浏览器回放一遍固化动作，每一步从快照中解析出该索引
元素的语义定位器（文本 / href / placeholder），据此生成
`get_by_text / get_by_role / get_by_placeholder` 风格的可读代码。
全程不调用 LLM（0 token）。
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from easyrun.browser import BrowserSession
from easyrun.config import Settings
from easyrun.models import CASE_MODE_DETERMINISTIC, TestCase

logger = logging.getLogger("easyrun.codegen")

_HEADER = '''# -*- coding: utf-8 -*-
"""由 EasyRun UI Agent 自动生成：用例「{name}」（固化动作导出，全程无 LLM）。

生成时间：{now}  用例版本：v{version}
运行：pip install playwright && playwright install chromium
"""
import os
import re
from pathlib import Path

# 在 EasyRun 项目内运行时，自动使用项目自带的浏览器内核（data/browsers）；
# 其他环境保持 Playwright 默认行为（自行 playwright install chromium）
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH") and (Path.cwd() / "data" / "browsers").is_dir():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(Path.cwd() / "data" / "browsers")

from playwright.sync_api import sync_playwright

TARGET_URL = "{target}"


def value_after(body: str, label: str) -> float:
    """取标签文本之后的第一个数值（与平台 value_compare 断言同语义）。"""
    i = body.find(label)
    if i < 0:
        raise AssertionError(f"页面中未找到标签「{{label}}」")
    m = re.search(r"-?\\d[\\d,]*\\.?\\d*", body[i + len(label):])
    if not m:
        raise AssertionError(f"标签「{{label}}」之后没有数值")
    return float(m.group(0).replace(",", ""))


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(TARGET_URL)
{steps}

{asserts}
        print("PASS: {name}")
        browser.close()


if __name__ == "__main__":
    run()
'''


def _q(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def locator_line(el: dict, index: int, kind: str) -> str:
    """按快照元素信息生成语义定位器（带兜底）。"""
    tag, text, href, ph = el.get("tag", ""), el.get("text", ""), el.get("href", ""), el.get("ph", "")
    if kind == "click":
        if tag == "a" and href:
            return f'page.locator("a[href=\\"{_q(href)}\\"]").first'
        if text:
            return f'page.get_by_text("{_q(text)}", exact=False).first'
    if kind == "type":
        if ph:
            return f'page.get_by_placeholder("{_q(ph)}")'
        if text:
            return f'page.locator("input[value=\\"{_q(text)}\\"]").first'
    # 纯定位器，注释由调用方放在行尾（不能放前面，否则吞掉 .click()/.fill()）
    return f'page.locator("{tag or "button"}").nth({index})'


def _assert_code_line(a: dict) -> str:
    """断言 dict → Playwright assert 代码行（8 空格缩进）；visual 返回注释行；不支持返回空串。"""
    t, target, expected = a.get("type", ""), a.get("target", ""), a.get("expected", "")
    if t == "text_contains":
        return f'        assert "{_q(target)}" in page.inner_text("body"), "页面未出现：{_q(target)}"'
    if t == "url_contains":
        return f'        assert "{_q(target)}" in page.url, "URL 未包含：{_q(target)}"'
    if t == "element_exists":
        return f'        assert page.locator("{_q(target)}").count() > 0, "元素不存在：{_q(target)}"'
    if t == "element_count":
        return f'        assert page.locator("{_q(target)}").count() == {expected}, "元素数量不匹配"'
    if t == "element_text":
        return f'        assert page.get_by_text("{_q(target)}", exact=False).count() > 0, "文本不存在：{_q(target)}"'
    if t == "value_compare":
        m = re.match(r"^(>=|<=|==|=|>|<)\s*(-?[\d.,]+)$", expected or "")
        if m:
            op, num = m.group(1), m.group(2).replace(",", "")
            return (
                f'        assert value_after(page.inner_text("body"), "{_q(target)}") {op} {num}, '
                f'"数值比较失败：{_q(target)} {op} {num}"'
            )
    if t == "visual":
        return "        # visual 断言依赖平台基线机制，导出后需自行接入视觉比对"
    return ""


async def export_case_code(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    case_id: str,
) -> tuple[str, str]:
    """回放固化动作并生成代码。返回 (code, filename)。"""
    async with session_factory() as session:
        case = await session.get(TestCase, case_id)
        if case is None:
            raise ValueError("用例不存在")
        actions = case.cured_actions or (case.steps if case.mode == CASE_MODE_DETERMINISTIC else [])
        if not actions:
            raise ValueError("用例还没有固化动作：需要先以探索模式成功执行一次（通过后自动记录）")
        assertions = case.assertions or []
        name, version = case.name, case.version

    # 断言拆分：绑定步骤的随标记点就地生成（在动作序列内），无绑定的收尾生成
    step_map: dict[int, list[dict]] = {}
    unbound_assertions: list[dict] = []
    for a in assertions:
        n = a.get("after_step")
        if n is not None:
            step_map.setdefault(int(n), []).append(a)
        else:
            unbound_assertions.append(a)

    browser = await BrowserSession(settings).start()
    steps_lines: list[str] = []
    target_url = ""
    try:
        await browser.new_page()
        # 动作列表不以导航开头时（探索阶段已在目标页开始记录），回放需先导航
        if not actions or actions[0].get("tool") != "browser_navigate":
            first_url = case.target_url
            if first_url:
                await browser.navigate(first_url)
        for action in actions:
            tool = action.get("tool")
            args = dict(action.get("args") or {})
            if tool == "browser_navigate":
                if not target_url:
                    target_url = str(args.get("url", ""))
                await browser.navigate(str(args.get("url", "")))
                continue
            if tool == "browser_click":
                idx = int(args.get("index", -1))
                snap = await browser.snapshot()
                els = snap.get("els", [])
                el = els[idx] if 0 <= idx < len(els) else {}
                steps_lines.append(f"        {locator_line(el, idx, 'click')}.click()")
                await browser.click(idx)
            elif tool == "browser_type":
                idx = int(args.get("index", -1))
                snap = await browser.snapshot()
                els = snap.get("els", [])
                el = els[idx] if 0 <= idx < len(els) else {}
                steps_lines.append(
                    f'        {locator_line(el, idx, "type")}.fill("{_q(str(args.get("text", "")))}")'
                )
                await browser.type_text(idx, str(args.get("text", "")))
            elif tool == "browser_wait":
                steps_lines.append(f"        page.wait_for_timeout({int(args.get('ms', 1000))})")
                await browser.wait(int(args.get("ms", 1000)))
            elif tool == "browser_go_back":
                steps_lines.append("        page.go_back()")
                await browser.go_back()
            elif tool == "case_step_done":
                # 步骤完成标记：就地生成该步骤绑定的断言代码行（真实时序），标记本身不生成代码
                n = int(args.get("step", 0))
                for a in step_map.get(n, []):
                    line = _assert_code_line(a)
                    if line:
                        steps_lines.append(line)
            # browser_get_text 等观察类动作不进代码
    finally:
        try:
            await browser.close()
        except Exception:
            pass

    target_url = target_url or case.target_url or "http://example.com/"

    assert_lines: list[str] = [_assert_code_line(a) for a in unbound_assertions]
    assert_lines = [ln for ln in assert_lines if ln]

    if not assert_lines and not step_map:
        assert_lines.append("        # 该用例没有断言，请补充业务校验")

    code = _HEADER.format(
        name=name,
        version=version,
        now=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        target=_q(target_url),
        steps="\n".join(steps_lines) if steps_lines else "        pass",
        asserts="\n".join(assert_lines),
    )
    filename = re.sub(r"[^\w一-鿿]+", "_", name).strip("_") or "case"
    return code, f"test_{filename}.py"
