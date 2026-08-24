"""确定性断言：定义校验与视觉比对。"""

from __future__ import annotations

import pytest

from easyrun.assertions import (
    _diff_images,
    normalize_assertions,
    parse_assertions_from_nl,
    run_assertion,
)
from tests.fakes import FakeBrowser


async def test_parse_assertions_from_nl_with_llm():
    """LLM 路径：结构化提取 → 确定性校验通过。"""
    from easyrun.llm import ChatResult, Usage

    class FakeLLM:
        def __init__(self):
            self.calls = 0

        async def chat_json(self, messages, **kwargs):
            self.calls += 1
            return {
                "assertions": [
                    {"type": "text_contains", "target": "订单编号", "expected": None},  # null → ""
                    {"type": "url_contains", "target": "checkout"},
                    {"type": "element_count", "target": ".product", "expected": "3"},
                ]
            }, ChatResult(text="", usage=Usage(), model="fake")

    llm = FakeLLM()
    out = await parse_assertions_from_nl("页面出现订单编号；跳转到结算页；列表有 3 个商品", llm)
    assert [a["type"] for a in out] == ["text_contains", "url_contains", "element_count"]
    assert out[0]["expected"] == ""  # null 归一为空串而非 "None"
    assert out[2]["expected"] == "3"
    assert llm.calls == 1


async def test_parse_assertions_from_nl_rejects_bad_llm_output():
    """LLM 返回非法类型 → 确定性校验兜底拒绝。"""
    from easyrun.llm import ChatResult, Usage

    class BadLLM:
        async def chat_json(self, messages, **kwargs):
            return {"assertions": [{"type": "bogus", "target": "x"}]}, ChatResult(text="", usage=Usage(), model="fake")

    with pytest.raises(ValueError, match="未知断言类型"):
        await parse_assertions_from_nl("随便", BadLLM())


async def test_parse_assertions_from_nl_rule_fallback():
    """无 LLM：关键词规则兜底。"""
    out = await parse_assertions_from_nl(
        "页面出现「订单编号」；跳转到结算页；列表有 3 个商品", None
    )
    assert any(a["type"] == "text_contains" and a["target"] == "订单编号" for a in out)
    assert any(a["type"] == "url_contains" for a in out)
    assert any(a["type"] == "element_count" and a["expected"] == "3" for a in out)


async def test_parse_assertions_from_nl_empty_input():
    with pytest.raises(ValueError, match="校验需求"):
        await parse_assertions_from_nl("   ", None)


def test_normalize_validates_types():
    ok = normalize_assertions([
        {"type": "text_contains", "target": "订单编号"},
        {"type": "element_count", "target": ".item", "expected": "3"},
    ])
    assert ok[1]["expected"] == "3"
    with pytest.raises(ValueError, match="未知断言类型"):
        normalize_assertions([{"type": "bogus"}])


async def test_text_contains():
    b = FakeBrowser(body="页面包含订单编号 ER-123")
    r = await run_assertion(b, {"type": "text_contains", "target": "订单编号"})
    assert r.ok
    r2 = await run_assertion(b, {"type": "text_contains", "target": "不存在的文本"})
    assert not r2.ok


async def test_url_contains():
    b = FakeBrowser(url="http://x/demo/checkout.html?x=1")
    assert (await run_assertion(b, {"type": "url_contains", "target": "checkout"})).ok


async def test_element_count_invalid_expected():
    b = FakeBrowser()
    r = await run_assertion(b, {"type": "element_count", "target": ".a", "expected": "abc"})
    assert not r.ok and "数字" in r.detail


async def test_text_in_view():
    b = FakeBrowser()
    b.text_positions["中性新闻（"] = [{"text": "中性新闻（12）条", "topR": 0.1, "botR": 0.2}]
    r = await run_assertion(b, {"type": "text_in_view", "target": "中性新闻（"})
    assert r.ok and r.actual == "可见命中 1 个"
    # 元素在视口外（topR > 1）不算可见
    b.text_positions["中性新闻（"][0]["topR"] = 2.0
    b.text_positions["中性新闻（"][0]["botR"] = 2.1
    r2 = await run_assertion(b, {"type": "text_in_view", "target": "中性新闻（"})
    assert not r2.ok
    r3 = await run_assertion(b, {"type": "text_in_view", "target": "不存在的文本"})
    assert not r3.ok


async def test_text_near_top():
    b = FakeBrowser()
    b.text_positions["中性新闻（"] = [
        {"text": "中性新闻（12）条", "topR": 0.05, "botR": 0.15},
        {"text": "中性新闻（99）条", "topR": 2.5, "botR": 2.6},
    ]
    r = await run_assertion(b, {"type": "text_near_top", "target": "中性新闻（"})
    assert r.ok and "窗口上方" in r.detail
    # 阈值收紧到 0.02 → 位于 5% 的元素不再算"上方"
    r2 = await run_assertion(b, {"type": "text_near_top", "target": "中性新闻（", "expected": "0.02"})
    assert not r2.ok
    # 非法阈值
    r3 = await run_assertion(b, {"type": "text_near_top", "target": "中性新闻（", "expected": "abc"})
    assert not r3.ok and "数字" in r3.detail
    # 页面滚动后：下方元素滚到窗口上方 → 通过
    b.text_positions["中性新闻（"][1]["topR"] = 0.1
    b.text_positions["中性新闻（"][1]["botR"] = 0.2
    r4 = await run_assertion(b, {"type": "text_near_top", "target": "中性新闻（"})
    assert r4.ok


async def test_value_compare():
    b = FakeBrowser()
    b.values_after["订单金额"] = {"ok": True, "value": 199.5}
    ok = await run_assertion(b, {"type": "value_compare", "target": "订单金额", "expected": ">= 100"})
    assert ok.ok and ok.actual == "199.5"
    fail = await run_assertion(b, {"type": "value_compare", "target": "订单金额", "expected": "< 100"})
    assert not fail.ok


async def test_value_compare_bad_expected_and_missing_label():
    b = FakeBrowser()
    b.values_after["订单金额"] = {"ok": True, "value": 10}
    r = await run_assertion(b, {"type": "value_compare", "target": "订单金额", "expected": "abc"})
    assert not r.ok and "运算符" in r.detail
    r2 = await run_assertion(b, {"type": "value_compare", "target": "不存在的标签", "expected": "> 1"})
    assert not r2.ok and "未找到" in r2.detail


async def test_nl_rules_value_compare():
    out = await parse_assertions_from_nl("订单金额大于100；价格不低于 50；库存小于 10", None)
    types = {a["type"] for a in out}
    assert types == {"value_compare"}
    by_target = {a["target"]: a["expected"] for a in out}
    assert by_target["订单金额"] == "> 100"
    assert by_target["价格"] == ">= 50"
    assert by_target["库存"] == "< 10"


async def test_visual_baseline_flow(tmp_path):
    from PIL import Image

    b = FakeBrowser()
    # 首次：创建基线视为通过
    r1 = await run_assertion(b, {"type": "visual", "target": "checkout"}, baseline_dir=tmp_path)
    assert r1.ok and "基线" in r1.detail
    # 修改基线后：差异超阈值 → 失败
    baseline = list(tmp_path.glob("checkout.png"))[0]
    img = Image.new("RGB", (64, 64), "white")
    img.save(baseline)
    img2 = Image.new("RGB", (64, 64), "black")
    img2.save(tmp_path / "other.png")
    # 直接测 _diff_images（actual 为字符串比率）
    ok, detail, ratio = _diff_images(baseline, tmp_path / "other.png", threshold=0.02)
    assert not ok and float(ratio) > 0.9
