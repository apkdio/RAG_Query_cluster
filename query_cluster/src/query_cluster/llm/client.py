"""OpenAI 兼容接口的极简 LLM 客户端。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: int = 90):
        if not base_url or not model:
            raise LLMError("需要提供 --base-url 和 --model（或 LLM_BASE_URL / LLM_MODEL）")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    def chat(self, messages: list[dict]) -> str:
        url = self.base_url
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"
        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise LLMError(f"LLM 请求失败: {exc}") from exc

        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"LLM 响应格式异常: {str(data)[:300]}") from exc


def client_from_env(base_url: str | None = None, model: str | None = None,
                    api_key_env: str = "LLM_API_KEY", timeout: int = 90) -> LLMClient:
    return LLMClient(
        base_url=base_url or os.environ.get("LLM_BASE_URL", ""),
        model=model or os.environ.get("LLM_MODEL", ""),
        api_key=os.environ.get(api_key_env),
        timeout=timeout,
    )
