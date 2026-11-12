"""LLM 客户端：OpenAI 兼容协议封装。

通过 .env 中的 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY 即可切换
DeepSeek / 通义千问 / GLM / OpenAI 等任意兼容厂商。
"""

import json
from collections.abc import AsyncGenerator

import httpx

from app.core.config import settings


class LLMClient:
    def __init__(self) -> None:
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "sk-xxxxxx"

    async def chat(
        self,
        messages: list[dict],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        """非流式调用，返回完整回复文本。"""
        body: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]

    async def chat_stream(
        self, messages: list[dict], temperature: float = 0.7
    ) -> AsyncGenerator[str, None]:
        """流式调用，逐段 yield 增量文本。"""
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        async with (
            httpx.AsyncClient(timeout=180) as client,
            client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            ) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    delta = json.loads(payload)["choices"][0]["delta"]
                    content = delta.get("content")
                    if content:
                        yield content
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue


llm_client = LLMClient()
