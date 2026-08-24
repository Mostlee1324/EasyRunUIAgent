"""DeepSeek 官方 API 客户端（OpenAI 兼容协议）。

- deepseek-chat：高频动作决策（JSON 输出模式）
- deepseek-reasoner：低频复杂推理（拆解 / 归因 / 自愈）

协议保持 OpenAI 兼容，可无改造替换为本地开源权重服务（如 Ollama/vLLM）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

import httpx

from easyrun.config import Settings

logger = logging.getLogger("easyrun.llm")


class LLMError(Exception):
    pass


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass
class ChatResult:
    text: str
    usage: Usage
    model: str


def extract_json(text: str) -> dict:
    """从模型输出中稳健地提取 JSON 对象。

    兼容：纯 JSON、markdown 代码块包裹、前后夹杂说明文字（reasoner 常见）。
    """
    if not text:
        raise LLMError("模型返回为空")
    text = text.strip()
    # 去掉 ```json ... ``` 围栏
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    # 直接解析
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    # 平衡扫描取第一个完整对象
    start = text.find("{")
    if start == -1:
        raise LLMError(f"模型输出中找不到 JSON 对象: {text[:200]!r}")
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(text[start : i + 1])
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    pass
                break
    raise LLMError(f"模型输出 JSON 解析失败: {text[:300]!r}")


class DeepSeekClient:
    """OpenAI 兼容 chat/completions 客户端。

    transport 参数用于测试注入（httpx.AsyncBaseTransport）。
    """

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._timeout = httpx.Timeout(settings.llm_timeout)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, timeout=self._timeout)

    def _headers(self) -> dict:
        key = self._settings.resolved_api_key
        if not key:
            raise LLMError(
                "未配置 DeepSeek API Key：请设置环境变量 DEEPSEEK_API_KEY（或 EASYRUN_DEEPSEEK_API_KEY）"
            )
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    async def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        json_mode: bool = False,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        """一次补全请求，带指数退避重试（429 / 5xx / 网络错误）。"""
        model = model or self._settings.deepseek_chat_model
        body: dict = {
            "model": model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens or self._settings.llm_max_tokens,
        }
        # deepseek-reasoner 不支持 temperature / response_format
        is_reasoner = model == self._settings.deepseek_reasoner_model
        if json_mode and not is_reasoner:
            body["response_format"] = {"type": "json_object"}
        if temperature is not None and not is_reasoner:
            body["temperature"] = temperature
        elif not is_reasoner:
            body["temperature"] = self._settings.llm_temperature

        url = f"{self._settings.deepseek_base_url.rstrip('/')}/chat/completions"
        last_err: Exception | None = None
        async with self._client() as client:
            for attempt in range(4):
                try:
                    resp = await client.post(url, headers=self._headers(), json=body)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        last_err = LLMError(
                            f"DeepSeek API {resp.status_code}: {resp.text[:200]}"
                        )
                    elif resp.status_code >= 400:
                        raise LLMError(
                            f"DeepSeek API {resp.status_code}: {resp.text[:300]}"
                        )
                    else:
                        data = resp.json()
                        choice = data["choices"][0]["message"]
                        usage = data.get("usage", {})
                        return ChatResult(
                            text=choice.get("content") or "",
                            usage=Usage(
                                prompt_tokens=usage.get("prompt_tokens", 0),
                                completion_tokens=usage.get("completion_tokens", 0),
                            ),
                            model=data.get("model", model),
                        )
                except (httpx.TransportError, httpx.TimeoutException) as e:
                    last_err = e
                if attempt < 3:
                    await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
        raise LLMError(f"DeepSeek API 调用失败（已重试）: {last_err}")

    async def chat_json(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> tuple[dict, ChatResult]:
        """JSON 模式对话，返回解析后的对象与原始结果（含用量）。"""
        result = await self.chat(messages, model=model, json_mode=True, max_tokens=max_tokens)
        return extract_json(result.text), result
