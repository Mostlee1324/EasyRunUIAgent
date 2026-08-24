"""Playwright 浏览器会话与页面操作工具。

快照策略（对应设计文档 §04 的「文本化快照」）：执行 JS 收集页面上所有
可交互元素（链接 / 按钮 / 输入框等），以 DOM 顺序编号；Agent 基于索引操作。
操作前重新收集一次，天然容忍两次快照之间页面状态的轻微变化。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from easyrun.config import Settings

try:
    from playwright.async_api import Browser, Page, async_playwright
except ImportError:  # pragma: no cover - 未安装 playwright 时给出清晰报错
    async_playwright = None  # type: ignore[assignment]

# 收集函数在页面内共享：快照与点击/输入使用同一份逻辑，保证索引一致
_COLLECT = """
function __er_collect(limit) {
  const selectors = 'a,button,input,select,textarea,[role="button"],[role="link"],[role="menuitem"],[onclick],label,summary';
  const seen = new Set();
  const nodes = [];
  const els = [];
  for (const el of document.querySelectorAll(selectors)) {
    if (seen.has(el)) continue;
    seen.add(el);
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (r.width === 0 || cs.visibility === 'hidden' || cs.display === 'none') continue;
    let text = (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || el.title || '').trim();
    if (!text && el.tagName === 'A') text = (el.getAttribute('href') || '').trim();
    els.push({
      i: els.length,
      tag: el.tagName.toLowerCase(),
      text: text.slice(0, 100),
      ph: (el.getAttribute('placeholder') || '').slice(0, 60),
      type: el.getAttribute('type') || '',
      href: (el.getAttribute('href') || '').slice(0, 120),
      inView: r.top >= 0 && r.top < window.innerHeight,
      topR: r.top / window.innerHeight,      // 元素上边缘的视口相对位置（0=窗口顶部，1=窗口底部）
      botR: r.bottom / window.innerHeight,   // 元素下边缘的视口相对位置
    });
    nodes.push(el);
    if (els.length >= limit) break;
  }
  window.__er_nodes = nodes;
  return { els, truncated: els.length >= limit };
}
"""

SNAPSHOT_JS = f"""() => {{
  const r = {_COLLECT}(150);
  return {{ url: location.href, title: document.title.slice(0, 120), els: r.els, truncated: r.truncated }};
}}"""

CLICK_JS = f"""(i) => {{
  const r = {_COLLECT}(150);
  const el = r.els[i];
  if (!el) return {{ ok: false, error: 'index ' + i + ' 不存在（页面可能已变化，请重新观察）' }};
  window.__er_nodes[i].scrollIntoView({{ block: 'center' }});
  window.__er_nodes[i].click();
  return {{ ok: true, clicked: el.tag + '|' + el.text }};
}}"""

# 注意：Playwright evaluate(fn, arg) 只接受单个参数，用数组传参并在函数内解构
TYPE_JS = f"""([i, text]) => {{
  const r = {_COLLECT}(150);
  const el = r.els[i];
  if (!el) return {{ ok: false, error: 'index ' + i + ' 不存在（页面可能已变化，请重新观察）' }};
  const node = window.__er_nodes[i];
  node.scrollIntoView({{ block: 'center' }});
  const proto = node.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
  setter.call(node, text);
  node.dispatchEvent(new Event('input', {{ bubbles: true }}));
  node.dispatchEvent(new Event('change', {{ bubbles: true }}));
  return {{ ok: true, typed: el.tag + '|' + el.text }};
}}"""

GET_TEXT_JS = f"""(i) => {{
  const r = {_COLLECT}(150);
  const el = r.els[i];
  if (!el) return {{ ok: false, error: 'index ' + i + ' 不存在' }};
  return {{ ok: true, text: el.text, tag: el.tag }};
}}"""

# 查找包含目标文本的「最内层」元素及其视口位置。
# 关键：快照只收集可交互元素，而业务标签（如「中性新闻（xxx）」）往往是
# 普通 div/span——位置与可见性断言需要独立的全 DOM 文本查找。
TEXT_POSITION_JS = """(label) => {
  const out = [];
  for (const el of document.querySelectorAll('body *')) {
    const t = el.textContent || '';
    if (!t.includes(label)) continue;
    const childMatch = Array.from(el.children).some(c => (c.textContent || '').includes(label));
    if (childMatch) continue;  // 只保留最内层命中，避免重复
    const r = el.getBoundingClientRect();
    out.push({
      text: t.trim().slice(0, 100),
      topR: r.top / window.innerHeight,
      botR: r.bottom / window.innerHeight,
    });
  }
  return out;
}"""

# 按名称点击 class=sub-links 分组内的链接（如 利好新闻/利空新闻/中性新闻）。
# 语义定位替代索引猜测：页面动态渲染时索引会漂移，名称不会。
CLICK_LINK_JS = """(name) => {
  const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();
  const containers = Array.from(document.querySelectorAll('[class*="sub-links"]'));
  if (!containers.length) return {ok: false, error: '页面没有 class 含 sub-links 的容器（可能日期尚未加载完成）'};
  const allNames = [];
  for (const c of containers) {
    for (const a of c.querySelectorAll('a')) {
      const t = clean(a.textContent);
      if (t) allNames.push(t);
      if (t === name || t.includes(name)) {
        a.scrollIntoView({block: 'center'});
        a.click();
        return {ok: true, clicked: 'a|' + t, href: a.getAttribute('href') || ''};
      }
    }
  }
  return {ok: false, error: 'sub-links 中未找到「' + name + '」链接（当前: ' + allNames.join(' / ') + '）'};
}"""

# 提取「标签文本之后的数值」，支持两种 DOM 形态：
# 1) 标签与数值在同一元素内：<span>已分析: <strong>2363</strong> 条</span>
# 2) 标签与数值在相邻兄弟元素：<span>已分析:</span><strong>2363</strong>
# 选文本最短的候选（最精确），支持 ¥ 1,234.5 等格式
VALUE_AFTER_JS = """(label) => {
  const num = (t) => {
    const m = t.match(/-?\\d[\\d,]*\\.?\\d*/);
    return m ? parseFloat(m[0].replace(/,/g, '')) : null;
  };
  const candidates = [];
  const push = (len, value) => { if (value !== null && !isNaN(value)) candidates.push({len, value}); };

  // 1) 同一元素内：标签之后的第一个数值
  for (const el of document.querySelectorAll('body *')) {
    const t = (el.textContent || '').replace(/\\s+/g, ' ').trim();
    if (!t.includes(label)) continue;
    const rest = t.slice(t.indexOf(label) + label.length);
    push(t.length, num(rest));
  }
  // 2) 相邻兄弟元素：标签在直接文本节点，数值在其后的兄弟元素里
  if (!candidates.length) {
    for (const el of document.querySelectorAll('body *')) {
      const direct = Array.from(el.childNodes)
        .filter(n => n.nodeType === 3).map(n => n.textContent).join('');
      if (!direct.includes(label)) continue;
      let sib = el.nextElementSibling, rest = '';
      while (sib && rest.length < 300) { rest += (sib.textContent || '') + ' '; sib = sib.nextElementSibling; }
      push(rest.length, num(rest.replace(/\\s+/g, ' ').trim()));
    }
  }
  if (!candidates.length) return {ok: false, error: `未找到「${label}」后的数值`};
  candidates.sort((a, b) => a.len - b.len);
  return {ok: true, value: candidates[0].value};
}"""


class BrowserError(Exception):
    pass


class BrowserSession:
    """一个 Worker 持有一个浏览器进程，每个任务一个独立 context。"""

    def __init__(self, settings: Settings) -> None:
        if async_playwright is None:
            raise BrowserError(
                "playwright 未安装：pip install playwright && playwright install chromium"
            )
        self._settings = settings
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def start(self) -> "BrowserSession":
        p = await async_playwright().start()  # type: ignore[union-attr]
        self._browser = await p.chromium.launch(headless=self._settings.browser_headless)
        return self

    async def new_page(self) -> Page:
        assert self._browser is not None, "browser not started"
        context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900}, locale="zh-CN"
        )
        self._page = await context.new_page()
        return self._page

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        self._page = None

    # ---- 观察 ----

    async def snapshot(self) -> dict:
        return await self._page.evaluate(SNAPSHOT_JS)

    # ---- 行动 ----

    async def navigate(self, url: str) -> dict:
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        return {"ok": True, "url": self._page.url}

    async def click(self, index: int) -> dict:
        return await self._page.evaluate(CLICK_JS, index)

    async def type_text(self, index: int, text: str) -> dict:
        return await self._page.evaluate(TYPE_JS, [index, text])

    async def wait(self, ms: int) -> dict:
        ms = max(0, min(int(ms), 30_000))
        await asyncio.sleep(ms / 1000)
        return {"ok": True, "waited_ms": ms}

    async def go_back(self) -> dict:
        await self._page.go_back(wait_until="domcontentloaded")
        return {"ok": True, "url": self._page.url}

    async def get_text(self, index: int) -> dict:
        return await self._page.evaluate(GET_TEXT_JS, index)

    async def extract_value_after(self, label: str) -> dict:
        """标签文本之后的数值（数值比较断言用）。"""
        return await self._page.evaluate(VALUE_AFTER_JS, label)

    async def find_text_positions(self, label: str) -> list[dict]:
        """包含目标文本的最内层元素及其视口位置（位置/可见性断言用）。"""
        return await self._page.evaluate(TEXT_POSITION_JS, label)

    async def click_link(self, name: str, timeout_ms: int = 5000) -> dict:
        """按名称点击 sub-links 分组内的链接。

        内置轮询：日期选项卡点击后链接是异步渲染的，
        在 timeout 内每隔 0.5s 重试，渲染完成即点击（匹配「点日期后等 3~5 秒」的节奏）。
        """
        import time

        deadline = time.monotonic() + timeout_ms / 1000
        last: dict = {"ok": False, "error": "未尝试"}
        while True:
            last = await self._page.evaluate(CLICK_LINK_JS, name)
            if last.get("ok") or time.monotonic() >= deadline:
                return last
            await asyncio.sleep(0.5)

    async def body_text(self) -> str:
        return await self._page.inner_text("body")

    async def url(self) -> str:
        return self._page.url

    async def count(self, css_selector: str) -> int:
        return await self._page.locator(css_selector).count()

    async def text_by_selector(self, css_selector: str) -> str:
        return await self._page.locator(css_selector).first.inner_text()

    async def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(path))
        return path


def format_snapshot(snap: dict, limit_chars: int = 6000) -> str:
    """快照 → LLM 文本。"""
    lines = [f"URL: {snap.get('url', '')}", f"标题: {snap.get('title', '')}"]
    for el in snap.get("els", []):
        view = "可见" if el.get("inView") else "屏外"
        lines.append(f"[{el['i']}|{el['tag']}|{el['text']}|{el['type']}|{el['href']}|{view}]")
    text = "\n".join(lines)
    if len(text) > limit_chars:
        text = text[:limit_chars] + "\n...(快照过长已截断)"
    return text
