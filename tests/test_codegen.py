"""用例 → 独立 Playwright 代码导出。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import easyrun.codegen as codegen
from easyrun.codegen import export_case_code, locator_line


def test_locator_line_semantic_choices():
    assert 'page.locator("a[href=\\"http://x/\\"]").first' in locator_line(
        {"tag": "a", "href": "http://x/", "text": ""}, 3, "click")
    assert 'page.get_by_text("登 录", exact=False).first' in locator_line(
        {"tag": "button", "text": "登 录", "href": ""}, 4, "click")
    assert 'page.get_by_placeholder("请输入用户名")' in locator_line(
        {"tag": "input", "text": "demo", "ph": "请输入用户名", "href": ""}, 1, "type")
    assert 'page.locator("button").nth(7)' in locator_line(
        {"tag": "button", "text": "", "href": ""}, 7, "click")


async def test_export_case_code_generates_readable_code(settings, sf, monkeypatch):
    from tests.fakes import FakeBrowser

    browser = FakeBrowser(
        url="http://shop.local/login",
        snapshot={"url": "http://shop.local/login", "title": "t", "truncated": False, "els": [
            {"i": 0, "tag": "button", "text": "登 录", "ph": "", "type": "", "href": "", "inView": True},
            {"i": 1, "tag": "input", "text": "demo", "ph": "请输入用户名", "type": "text", "href": "", "inView": True},
        ]},
    )

    class FakeBS:
        def __init__(self, settings):
            pass

        async def start(self):
            return browser

    monkeypatch.setattr(codegen, "BrowserSession", FakeBS)

    from easyrun.models import TestCase

    case = TestCase(
        name="登录冒烟", mode="agentic", target_url="http://shop.local/login",
        cured_actions=[
            {"tool": "browser_navigate", "args": {"url": "http://shop.local/login"}},
            {"tool": "browser_click", "args": {"index": 0}},
            {"tool": "browser_type", "args": {"index": 1, "text": "demo"}},
            {"tool": "browser_wait", "args": {"ms": 500}},
        ],
        assertions=[
            {"type": "text_contains", "target": "欢迎"},
            {"type": "value_compare", "target": "订单金额", "expected": "> 100"},
        ],
    )
    async with sf() as session:
        session.add(case)
        await session.commit()
        await session.refresh(case)
        cid = case.id

    code, filename = await export_case_code(sf, settings, cid)

    assert filename == "test_登录冒烟.py"
    assert 'page.get_by_text("登 录", exact=False).first.click()' in code
    assert 'page.get_by_placeholder("请输入用户名").fill("demo")' in code
    assert "page.wait_for_timeout(500)" in code
    assert 'assert "欢迎" in page.inner_text("body")' in code
    assert 'value_after(page.inner_text("body"), "订单金额") > 100' in code
    assert 'TARGET_URL = "http://shop.local/login"' in code


async def test_export_requires_cured_actions(settings, sf):
    from easyrun.models import TestCase

    case = TestCase(name="未固化", mode="agentic", cured_actions=[])
    async with sf() as session:
        session.add(case)
        await session.commit()
        cid = case.id
    with pytest.raises(ValueError, match="固化动作"):
        await export_case_code(sf, settings, cid)
