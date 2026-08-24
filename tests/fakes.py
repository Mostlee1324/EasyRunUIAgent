"""测试替身：脚本化 LLM 与浏览器。"""

from __future__ import annotations

from pathlib import Path

from easyrun.llm import ChatResult, Usage


class ScriptedLLM:
    """按脚本返回动作的假 LLM；脚本耗尽时调用 fail。"""

    def __init__(self, actions: list[dict]) -> None:
        self.actions = list(actions)
        self.calls: list[dict] = []

    async def chat_json(self, messages, **kwargs):
        self.calls.append(messages)
        if self.actions:
            obj = dict(self.actions.pop(0))
        else:
            obj = {"tool": "fail", "args": {"reason": "脚本耗尽"}, "reason": ""}
        return obj, ChatResult(text="", usage=Usage(prompt_tokens=10, completion_tokens=5), model="fake")


class FakeBrowser:
    """内存版 BrowserSession：可脚本化快照、点击副作用与断言数据。"""

    def __init__(
        self,
        url: str = "http://example.com/",
        body: str = "hello world",
        snapshot: dict | None = None,
        click_effects: dict[int, dict] | None = None,
    ) -> None:
        self.url_value = url
        self.body = body
        self.snap = snapshot or {"url": url, "title": "fake", "els": [], "truncated": False}
        self.click_effects = click_effects or {}
        self.navigated: list[str] = []
        self.clicks: list[int] = []
        self.typed: list[tuple[int, str]] = []
        self.shots: list[Path] = []
        self.closed = False
        self.type_fail_keys: set[str] = set()  # "index N" 恒失败的输入框
        self.values_after: dict[str, dict] = {}  # 标签 → {"ok": True, "value": N}
        self.text_positions: dict[str, list[dict]] = {}  # 标签 → [{text, topR, botR}]
        self.link_results: dict[str, dict] = {}          # 链接名 → {ok, clicked, ...}

    async def start(self):  # pragma: no cover
        return self

    async def new_page(self):
        return None

    async def close(self):
        self.closed = True

    async def snapshot(self) -> dict:
        # 每次返回新对象（真实浏览器 evaluate 语义），避免前后快照互相污染
        return {**self.snap, "url": self.url_value}

    async def navigate(self, url: str) -> dict:
        self.navigated.append(url)
        self.url_value = url
        return {"ok": True, "url": url}

    async def click(self, index: int) -> dict:
        self.clicks.append(index)
        effect = self.click_effects.get(index)
        if callable(effect):  # 支持动态副作用（模拟页面逐步变化）
            effect = effect()
        if effect:
            if effect.get("url"):
                self.url_value = effect["url"]
            if effect.get("body"):
                self.body = effect["body"]
            return {"ok": True, "clicked": effect.get("clicked", "?"), **effect}
        return {"ok": True, "clicked": "el"}

    async def type_text(self, index: int, text: str) -> dict:
        self.typed.append((index, text))
        if f"index {index}" in self.type_fail_keys:
            return {"ok": False, "error": f"index {index} 不存在（页面可能已变化，请重新观察）"}
        return {"ok": True, "typed": "el"}

    async def wait(self, ms: int) -> dict:
        return {"ok": True, "waited_ms": ms}

    async def go_back(self) -> dict:
        return {"ok": True, "url": self.url_value}

    async def get_text(self, index: int) -> dict:
        return {"ok": True, "text": "el", "tag": "div"}

    async def extract_value_after(self, label: str) -> dict:
        return self.values_after.get(label, {"ok": False, "error": f"未找到「{label}」后的数值"})

    async def find_text_positions(self, label: str) -> list[dict]:
        return self.text_positions.get(label, [])

    async def click_link(self, name: str, timeout_ms: int = 5000) -> dict:
        r = self.link_results.get(name, {"ok": False, "error": f"sub-links 中未找到「{name}」链接"})
        return {**r, "clicked": r.get("clicked", "a|" + name)}

    async def body_text(self) -> str:
        return self.body

    async def url(self) -> str:
        return self.url_value

    async def count(self, css_selector: str) -> int:
        return 1

    async def text_by_selector(self, css_selector: str) -> str:
        return ""

    async def screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\x89PNG-fake")
        self.shots.append(path)
        return path
