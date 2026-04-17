"""
Jarvis LLM Integration
========================
Async client for Ollama API with structured JSON output.

Sends natural language to the local LLM with system context,
and receives structured action decisions.
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional

import httpx

from core import config

logger = logging.getLogger("jarvis.llm")


class LLMClient:
    """
    Async Ollama API client for the Jarvis brain.
    
    Features:
    - Structured JSON output for action routing
    - Streaming support for fast first-token
    - Conversation history tracking
    - Token usage monitoring
    - Timeout and retry handling
    """

    def __init__(self):
        cfg = config.get("llm", default={})
        self._base_url: str = cfg.get("base_url", "http://localhost:11434")
        self._model: str = cfg.get("model", "mistral:7b")
        # self._model: str = cfg.get("model", "gemma3:270m")
        self._temperature: float = cfg.get("temperature", 0.3)
        self._max_tokens: int = cfg.get("max_tokens", 512)
        self._timeout: int = cfg.get("timeout", 30)

        self._client: Optional[httpx.AsyncClient] = None
        self._total_tokens_used: int = 0
        self._request_count: int = 0

    async def _get_client(self) -> httpx.AsyncClient:
        """Lazy-initialize the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(self._timeout),
                http2=False   # FORCE HTTP/1.1
            )
        return self._client

    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        context: list[dict] | None = None,
        json_mode: bool = True,
    ) -> dict[str, Any]:
        client = await self._get_client()

        # 1. Correctly build the messages array
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if context:
            messages.extend(context)
        messages.append({"role": "user", "content": prompt})

        # 2. Update payload for the /api/chat endpoint
        payload = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self._temperature,
                "num_predict": self._max_tokens,
            },
        }

        if json_mode:
            payload["format"] = "json"

        start_time = time.monotonic()

        try:
            response = await client.post("/api/chat",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
            )
            response.raise_for_status()
            data = response.json()

            elapsed = time.monotonic() - start_time
            self._request_count += 1

            # 3. Extract content from the Chat API structure
            content = data.get("message", {}).get("content", "")

            # Track token usage (prompt_eval_count + eval_count)
            eval_count = data.get("eval_count", 0)
            self._total_tokens_used += eval_count

            logger.info(
                "LLM response in %.1fs (tokens=%d, model=%s)",
                elapsed, eval_count, self._model,
            )

            if json_mode:
                try:
                    print(content)
                    return json.loads(content)
                except json.JSONDecodeError:
                    logger.warning("LLM returned non-JSON: %s", content[:200])
                    return {"action": "none", "params": {}, "response": content}
            else:
                return {"action": "none", "params": {}, "response": content}

        except httpx.HTTPStatusError as e:
            logger.error("Ollama API error: %s", e)
            return {"action": "none", "params": {}, "response": "API Error", "error": str(e)}

        except httpx.TimeoutException:
            elapsed = time.monotonic() - start_time
            logger.warning("LLM timed out after %.1fs", elapsed)
            return {
                "action": "none",
                "params": {},
                "response": "I'm taking too long to think. Could you try again?",
                "error": "timeout",
            }

        except Exception:
            logger.exception("LLM request failed")
            return {
                "action": "none",
                "params": {},
                "response": "Something went wrong with my thinking process.",
                "error": "unknown",
            }

    async def check_health(self) -> bool:
        """Check if Ollama is running and the model is available."""
        try:
            client = await self._get_client()
            response = await client.get("/api/tags")
            if response.status_code == 200:
                models = response.json().get("models", [])
                model_names = [m.get("name", "") for m in models]
                if self._model in model_names:
                    logger.info("✅ Ollama healthy, model '%s' available", self._model)
                    return True
                else:
                    logger.warning(
                        "Ollama running but model '%s' not found. Available: %s",
                        self._model, model_names,
                    )
                    return False
            return False
        except Exception:
            logger.warning("Ollama health check failed")
            return False

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    @property
    def stats(self) -> dict:
        """Usage statistics."""
        return {
            "total_tokens": self._total_tokens_used,
            "requests": self._request_count,
            "model": self._model,
        }


# Global singleton
llm = LLMClient()