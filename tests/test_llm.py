"""DeepSeek 客户端：请求构造、重试、JSON 提取。"""

from __future__ import annotations

import httpx
import pytest

from easyrun.config import Settings
from easyrun.llm import DeepSeekClient, LLMError, extract_json


def _settings() -> Settings:
    return Settings(deepseek_api_key="sk-test", deepseek_base_url="https://api.deepseek.com")


async def test_chat_json_mode_and_auth():
    captured = {}

    def handler(request: httpx.Request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"tool":"finish","args":{},"reason":"ok"}'}}],
                  "usage": {"prompt_tokens": 11, "completion_tokens": 3},
                  "model": "deepseek-chat"},
        )

    client = DeepSeekClient(_settings(), transport=httpx.MockTransport(handler))
    obj, result = await client.chat_json([{"role": "user", "content": "hi"}])

    assert obj == {"tool": "finish", "args": {}, "reason": "ok"}
    assert result.usage.prompt_tokens == 11
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer sk-test"
    import json as _json

    body = _json.loads(captured["body"])
    assert body["response_format"] == {"type": "json_object"}
    assert body["temperature"] == 0.2


async def test_reasoner_skips_temperature_and_json_mode():
    captured = {}

    def handler(request: httpx.Request):
        captured["body"] = request.content.decode()
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"a":1}'}}], "usage": {}, "model": "deepseek-reasoner"},
        )

    s = _settings()
    client = DeepSeekClient(s, transport=httpx.MockTransport(handler))
    await client.chat_json([{"role": "user", "content": "x"}], model=s.deepseek_reasoner_model)

    import json as _json

    body = _json.loads(captured["body"])
    assert body["model"] == "deepseek-reasoner"
    assert "temperature" not in body
    assert "response_format" not in body


async def test_retry_on_429_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"x":1}'}}], "usage": {}, "model": "m"},
        )

    client = DeepSeekClient(_settings(), transport=httpx.MockTransport(handler))
    obj, _ = await client.chat_json([{"role": "user", "content": "hi"}])
    assert obj == {"x": 1}
    assert calls["n"] == 3


async def test_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("EASYRUN_DEEPSEEK_API_KEY", raising=False)
    s = Settings(deepseek_api_key="")
    client = DeepSeekClient(s)
    with pytest.raises(LLMError, match="DEEPSEEK_API_KEY"):
        await client.chat([{"role": "user", "content": "hi"}])


def test_extract_json_variants():
    assert extract_json('{"tool":"finish","args":{},"reason":""}') == {
        "tool": "finish", "args": {}, "reason": ""}
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('好的，下一步执行：\n{"tool": "browser_click", "args": {"index": 3}, "reason": "r"}\n完成。') == {
        "tool": "browser_click", "args": {"index": 3}, "reason": "r"}
    with pytest.raises(LLMError):
        extract_json("没有任何 JSON")
