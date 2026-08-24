"""确定性断言：校验由代码执行，LLM 不参与下结论（设计文档 §04）。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

from easyrun.browser import BrowserSession


@dataclass
class AssertionResult:
    type: str
    target: str
    expected: str
    ok: bool
    actual: str = ""
    detail: str = ""


ASSERTION_TYPES: dict[str, str] = {
    "text_contains": "页面正文包含指定文本（target 为期望出现的文本）",
    "url_contains": "当前 URL 包含指定片段（target 为 URL 片段）",
    "element_exists": "CSS 选择器匹配的元素存在（target 为 CSS 选择器）",
    "element_count": "CSS 选择器匹配的元素数量等于期望值（target 为 CSS 选择器，expected 为数字）",
    "element_text": "页面存在指定文本的元素（target 为文本）",
    "text_in_view": "屏幕可见元素中包含指定文本（target 为文本，如「中性新闻（」）",
    "text_near_top": "包含指定文本的元素出现在窗口上方区域（target 为文本；expected 可选，上方比例阈值，默认 0.4）",
    "value_compare": "标签后的数值与期望值比较（target 为标签文本，expected 为 运算符+数字，如 \">= 100\"）",
    "visual": "页面截图与基线一致（target 为基线名，如 checkout）",
}


def normalize_assertions(raw: list[dict]) -> list[dict]:
    """校验断言定义，非法类型直接报错（API 层 400）。"""
    out = []
    for a in raw:
        t = a.get("type", "text_contains")
        if t not in ASSERTION_TYPES:
            raise ValueError(f"未知断言类型: {t}（可选: {', '.join(ASSERTION_TYPES)}）")
        # 注意：LLM 可能返回 null，必须归一为空串而不是 "None"
        entry = {
            "type": t,
            "target": str(a.get("target") or ""),
            "expected": str(a.get("expected") or ""),
        }
        ms = a.get("min_steps")
        if ms is not None:
            try:
                entry["min_steps"] = int(ms)
            except (TypeError, ValueError):
                pass
        # 步骤后断言绑定：非法值直接报错（与 min_steps 的静默丢弃刻意不同——
        # 绑定错误会让断言被静默跳过，宁可录入时 400）
        as_ = a.get("after_step")
        if as_ is not None:
            try:
                as_i = int(as_)
            except (TypeError, ValueError):
                raise ValueError(f"after_step 必须为 1-99 的整数，收到 {as_!r}")
            if not 1 <= as_i <= 99:
                raise ValueError(f"after_step 必须为 1-99 的整数，收到 {as_i}")
            entry["after_step"] = as_i
        out.append(entry)
    return out


# 自然语言 → 断言：规则兜底模式（无 LLM 时仍可用）
_NL_RULES: list[tuple[str, str]] = [
    (r"(?:存在|共|有)\s*(\d+)\s*个|数量.{0,6}(\d+)", "element_count"),   # 数量类放最前（含「存在 N 个」）
    (r"URL|跳转|链接.*包含|进入.*页", "url_contains"),
    (r"元素.*存在|存在.*元素|选择器", "element_exists"),
    (r"出现|包含|显示|提示|文案|文本", "text_contains"),
]

# 数值比较：标签 + 比较词 + 数值（如「订单金额大于 100」「价格不低于 50」）
# 注意顺序：「不低于」必须在「低于」之前匹配
_NL_VALUE_PATTERNS: list[tuple[str, str]] = [
    (r"(.{1,12}?)(不低于|至少)\s*(-?[\d.,]+)", ">="),
    (r"(.{1,12}?)(大于|超过)\s*(-?[\d.,]+)", ">"),
    (r"(.{1,12}?)(等于|是)\s*(-?[\d.,]+)", "=="),
    (r"(.{1,12}?)(不超过|不高于)\s*(-?[\d.,]+)", "<="),
    (r"(.{1,12}?)(小于|低于)\s*(-?[\d.,]+)", "<"),
]

_ASSERTION_PROMPT = """你是测试断言提取器。把用户的中文校验需求转换为结构化断言列表，输出 JSON：
{"assertions": [{"type": "<类型>", "target": "<目标>", "expected": "<期望值，数量类必填>"}]}

类型定义（type 只能取这 6 个）：
- text_contains: 页面正文包含某文本。target=期望出现的文本（如"订单编号"）
- url_contains: 当前 URL 包含某片段。target=URL 片段（如"checkout"）
- element_exists: CSS 选择器匹配的元素存在。target=CSS 选择器（如".order-list"）
- element_count: CSS 选择器匹配的元素数量等于期望值。target=CSS 选择器，expected=数字
- element_text: 页面存在某文本的元素。target=文本
- text_near_top: 包含指定文本的元素出现在窗口上方区域。target=文本（如"中性新闻（"），expected 可选=上方比例阈值（默认 0.4）
- value_compare: 标签后的数值与期望值比较。target=标签文本（如"订单金额"），expected=运算符+数字（如">= 100"、"< 50"）
- visual: 页面截图与基线一致（视觉回归）。target=基线名（如"checkout"）

常见说法对照：
- "页面出现/包含「订单编号」" → text_contains
- "跳转到结算页 / URL 包含 checkout" → url_contains
- "购物车按钮存在" → element_exists（需给 CSS 选择器，没有则用 element_text）
- "列表有 3 个商品" → element_count
- "订单金额大于 100" → value_compare（target=订单金额，expected="> 100"）
- "价格不低于 50" → value_compare（target=价格，expected=">= 50"）
- "「已分析」后的数值大于 0" → value_compare（target=已分析，expected="> 0"；支持标签与数值同元素或相邻兄弟元素，如 <span>已分析: <strong>2363</strong> 条</span>）
- "结算页和上次一致" → visual

只输出 JSON，不要输出其他内容。"""


async def parse_assertions_from_nl(text: str, llm=None) -> list[dict]:
    """自然语言 → 断言列表。

    技巧：
    1. LLM 只做翻译（受严格 schema 约束），合法性由 normalize_assertions 确定性兜底；
    2. 输出回填表单，人工仍可修改——AI 是建议不是结论；
    3. LLM 不可用时降级为关键词规则，保证功能可用。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("请先输入校验需求描述")
    sentences = [s.strip() for s in __import__("re").split(r"[。；;，,\n]", text) if s.strip()]

    # 无 LLM：关键词规则兜底
    if llm is None:
        import re as _re

        out = []
        for s in sentences:
            # 数值比较优先匹配（标签 + 比较词 + 数值）
            matched = False
            for pattern, op in _NL_VALUE_PATTERNS:
                m = _re.search(pattern, s)
                if m:
                    out.append({"type": "value_compare", "target": m.group(1).strip(), "expected": f"{op} {m.group(3)}"})
                    matched = True
                    break
            if matched:
                continue
            for pattern, atype in _NL_RULES:
                m = _re.search(pattern, s)
                if not m:
                    continue
                if atype == "element_count":
                    n = m.group(1) or m.group(2)
                    out.append({"type": atype, "target": s, "expected": n})
                elif atype == "url_contains":
                    frag = _re.search(r"[\w\-/.]{2,}", s)
                    out.append({"type": atype, "target": frag.group(0) if frag else s})
                else:
                    quoted = _re.findall(r"[「『\"']([^」』\"']+)[」』\"']", s)
                    out.append({"type": atype, "target": quoted[0] if quoted else s})
                break
        return normalize_assertions(out) if out else []

    # LLM 结构化提取
    obj, _ = await llm.chat_json(
        [
            {"role": "system", "content": _ASSERTION_PROMPT},
            {"role": "user", "content": "\n".join(sentences)},
        ]
    )
    raw = obj.get("assertions") if isinstance(obj, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError("未能从描述中提取出断言，请补充明确的校验点（如「页面出现××」）")
    try:
        return normalize_assertions(raw)  # 确定性兜底：非法类型直接拒绝
    except ValueError:
        raise


async def run_assertion(
    browser: BrowserSession,
    assertion: dict,
    baseline_dir: Path | None = None,
) -> AssertionResult:
    t = assertion.get("type", "text_contains")
    target = assertion.get("target", "")
    expected = assertion.get("expected", "")
    base = AssertionResult(type=t, target=target, expected=expected, ok=False)

    if t == "text_contains":
        text = await browser.body_text()
        base.ok = target in text
        base.actual = text[:300]
        base.detail = f"正文包含「{target}」" if base.ok else f"正文未找到「{target}」"

    elif t == "url_contains":
        url = await browser.url()
        base.ok = target in url
        base.actual = url
        base.detail = f"URL 包含「{target}」" if base.ok else f"URL 不含「{target}」"

    elif t == "element_exists":
        n = await browser.count(target)
        base.ok = n > 0
        base.actual = f"匹配 {n} 个"
        base.detail = f"选择器 {target} 匹配 {n} 个元素"

    elif t == "element_count":
        n = await browser.count(target)
        try:
            want = int(expected)
        except ValueError:
            base.detail = f"expected 必须是数字，收到 {expected!r}"
            return base
        base.ok = n == want
        base.actual = f"匹配 {n} 个"
        base.detail = f"期望 {want} 个，实际 {n} 个"

    elif t == "element_text":
        text = await browser.body_text()
        base.ok = target in text
        base.actual = text[:300]
        base.detail = f"页面存在文本「{target}」" if base.ok else f"页面无文本「{target}」"

    elif t == "text_in_view":
        # 全 DOM 文本查找（不只可交互元素）：业务标签常为普通 div/span
        positions = await browser.find_text_positions(target)
        hits = [p for p in positions if p.get("topR", 1) < 1 and p.get("botR", 0) > 0]
        base.ok = bool(hits)
        base.actual = f"可见命中 {len(hits)} 个"
        base.detail = f"屏幕可见元素含「{target}」" if base.ok else f"屏幕可见元素不含「{target}」"

    elif t == "text_near_top":
        # 位置断言：元素上边缘位于窗口上方区域（默认 40% 以内），且仍可见
        try:
            thr = float(expected) if expected else 0.4
        except ValueError:
            base.detail = f"expected 应为数字比例（如 0.4），收到 {expected!r}"
            return base
        positions = await browser.find_text_positions(target)
        hits = [
            p for p in positions
            if p.get("topR", 1) <= thr and p.get("botR", 0) >= 0
        ]
        base.ok = bool(hits)
        if hits:
            best = min(hits, key=lambda e: abs((e.get("topR") or 1) - 0))
            base.actual = f"元素上边缘位于窗口 {best.get('topR', 0):.0%} 处"
            base.detail = f"「{target}」出现在窗口上方（{best.get('topR', 0):.0%}，阈值 {thr:.0%}）"
        else:
            loc = ", ".join(f"{p.get('topR', 0):.0%}" for p in positions)
            base.actual = f"命中元素位置: {loc or '无'}"
            base.detail = f"「{target}」不在窗口上方（阈值 {thr:.0%}）"

    elif t == "value_compare":
        res = await browser.extract_value_after(target)
        if not res.get("ok"):
            base.detail = str(res.get("error", "数值提取失败"))
            return base
        import re as _re

        value = float(res["value"])
        m = _re.match(r"^(>=|<=|==|=|>|<)\s*(-?[\d.,]+)$", expected)
        if not m:
            base.detail = f"expected 格式应为 运算符+数字（如 \">= 100\"），收到 {expected!r}"
            return base
        op, num = m.group(1), float(m.group(2).replace(",", ""))
        ops = {
            ">": value > num, ">=": value >= num, "<": value < num,
            "<=": value <= num, "==": value == num, "=": value == num,
        }
        base.ok = ops[op]
        base.actual = str(value)
        base.detail = f"{target} 数值 {value} {op} {num}，{'通过' if base.ok else '不满足'}"

    elif t == "visual":
        assert baseline_dir is not None, "visual 断言需要 baseline_dir"
        key = hashlib.md5(f"{await browser.url()}:{target}".encode()).hexdigest()[:12]
        baseline = baseline_dir / f"{target or key}.png"
        shot = baseline_dir / f"{key}.current.png"
        await browser.screenshot(shot)
        if not baseline.exists():
            shot.replace(baseline)
            base.ok = True
            base.detail = "基线不存在，已创建基线（本次视为通过）"
            return base
        base.ok, base.detail, base.actual = _diff_images(baseline, shot, threshold=0.02)
        shot.unlink(missing_ok=True)

    return base


def _diff_images(baseline: Path, current: Path, threshold: float) -> tuple[bool, str, str]:
    """灰度缩放下采样比较，返回 (ok, detail, ratio)。"""
    size = (320, 320)
    a = ImageOps.grayscale(Image.open(baseline)).resize(size)
    b = ImageOps.grayscale(Image.open(current)).resize(size)
    diff = ImageChops.difference(a, b)
    # 归一化到 [0,1] 的平均差异
    data = list(diff.getdata())
    ratio = sum(data) / (len(data) * 255)
    ok = ratio <= threshold
    return ok, f"截图差异 {ratio:.3%}（阈值 {threshold:.1%}）", f"{ratio:.4f}"
