from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


class OllamaMemoryClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.chat_model = os.getenv("OLLAMA_MODEL", "qwen3:8b")
        self.embedding_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "embeddinggemma")

    def _post(self, path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "SuhasPrivateAITrader/2.0"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
        if not isinstance(data, dict):
            raise ValueError("Ollama response was not a JSON object")
        return data

    def embed(self, text: str, timeout: float = 30.0) -> list[float]:
        data = self._post("/api/embed", {"model": self.embedding_model, "input": text}, timeout)
        vectors = data.get("embeddings") or []
        if not vectors or not isinstance(vectors[0], list):
            raise ValueError("Ollama embedding response did not contain a vector")
        return [float(value) for value in vectors[0]]

    def analyze(self, *, system: str, payload: dict[str, Any], timeout: float = 120.0) -> str:
        data = self._post(
            "/api/chat",
            {
                "model": self.chat_model,
                "stream": False,
                "keep_alive": "10m",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False, default=str)},
                ],
                "options": {"temperature": 0.1, "num_ctx": 8192},
            },
            timeout,
        )
        message = data.get("message") or {}
        content = str(message.get("content") or "").strip()
        if not content:
            raise ValueError("Ollama returned an empty analysis")
        return content
