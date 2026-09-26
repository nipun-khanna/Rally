"""Optional Meta Muse Spark conversation extractor.

This adapter exposes only extraction. Grok remains Rally's decision agent.
"""

import json
from collections.abc import Callable

import httpx

from app.agent import GrokClient
from app.models import ChatMessage, PlanFacts


META_CHAT_URL = "https://api.meta.ai/v1/chat/completions"
STANDARD_MODELS = frozenset({"muse-spark-1.1", "muse-spark-1.2", "muse-spark-1.3"})


class MuseExtractor:
    def __init__(self, api_key: str, model: str = "muse-spark-1.3",
                 transport: Callable[[dict], dict] | None = None,
                 default_city: str = "", time_zone: str = "America/New_York"):
        if model not in STANDARD_MODELS:
            raise ValueError("Muse extraction requires a standard tier model")
        self.api_key = api_key
        self.model = model
        self.transport = transport
        # Share Rally's prompt, output contract, and evidence/date validation.
        self._extractor = GrokClient("", transport=self._call,
                                     default_city=default_city, time_zone=time_zone)

    def _call(self, payload: dict) -> dict:
        request = dict(payload)
        request["model"] = self.model
        request["response_format"] = {
            **payload["response_format"],
            "json_schema": {
                **payload["response_format"]["json_schema"],
                # PlanFacts.evidence is a map with dynamic keys. Meta strict mode
                # rejects that schema, while non-strict mode still constrains JSON.
                "strict": False,
            },
        }
        if self.transport is not None:
            return self.transport(request)
        if not self.api_key:
            raise RuntimeError("Meta Model API key is missing")
        try:
            response = httpx.post(
                META_CHAT_URL, json=request,
                headers={"Authorization": f"Bearer {self.api_key}"}, timeout=25)
            response.raise_for_status()
            return json.loads(response.json()["choices"][0]["message"]["content"])
        except (httpx.HTTPError, KeyError, IndexError, ValueError, TypeError):
            raise RuntimeError("Meta Model API request failed") from None

    def extract(self, messages: list[ChatMessage], previous: PlanFacts | None) -> PlanFacts:
        return self._extractor.extract(messages, previous)
