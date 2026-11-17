"""
Model providers.

`heuristic` is the offline baseline and needs no credentials. `anthropic` and
`openai` call their HTTP APIs with the standard library only. `auto` uses
whichever key is present, otherwise the heuristic provider — and says so.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

import build
import prompting
import sources
from config import Settings, Target


class ProviderError(RuntimeError):
    pass


@dataclass
class ProviderResult:
    envelope: dict
    provider: str
    model: str
    raw: str = ""
    usage: dict | None = None


class HeuristicProvider:
    name = "heuristic"
    model = "code-signals@1.0.0"

    def extract(self, target: Target, files, signals, settings: Settings,
                repo) -> ProviderResult:
        texts = {f.rel: f.text for f in files}
        envelope = build.build_envelope(target, signals, settings, repo, texts)
        return ProviderResult(envelope=envelope, provider=self.name, model=self.model)


def parse_json(text: str) -> dict:
    """Accept a JSON object, optionally wrapped in prose or fences."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ProviderError("model response contained no JSON object") from None
        try:
            value = json.loads(text[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ProviderError(f"model response was not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ProviderError("model response was not a JSON object")
    return value


def _post(url: str, payload: dict, headers: dict, timeout: int = 120) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "ignore")[:500]
        raise ProviderError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderError(f"cannot reach {url}: {exc.reason}") from exc


class AnthropicProvider:
    name = "anthropic"
    default_model = "claude-sonnet-4-5"
    url = "https://api.anthropic.com/v1/messages"

    def __init__(self, model: str = ""):
        self.model = model or self.default_model
        self.key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")

    def extract(self, target, files, signals, settings, repo) -> ProviderResult:
        message = prompting.user_message(target, files, signals)
        payload = {
            "model": self.model,
            "max_tokens": 8000,
            "temperature": 0,
            "system": prompting.system_prompt(),
            "messages": [{"role": "user", "content": message}],
        }
        data = _post(self.url, payload, {
            "x-api-key": self.key,
            "anthropic-version": "2023-06-01",
        })
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict))
        envelope = parse_json(text)
        return ProviderResult(envelope, self.name, self.model, text, data.get("usage"))


class OpenAIProvider:
    name = "openai"
    default_model = "gpt-4.1"
    url = "https://api.openai.com/v1/chat/completions"

    def __init__(self, model: str = ""):
        self.model = model or self.default_model
        self.key = os.environ.get("OPENAI_API_KEY", "")
        if not self.key:
            raise ProviderError("OPENAI_API_KEY is not set")

    def extract(self, target, files, signals, settings, repo) -> ProviderResult:
        payload = {
            "model": self.model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": prompting.system_prompt()},
                {"role": "user", "content": prompting.user_message(target, files, signals)},
            ],
        }
        data = _post(self.url, payload, {"Authorization": f"Bearer {self.key}"})
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError("OpenAI response had no choices")
        text = choices[0].get("message", {}).get("content", "")
        envelope = parse_json(text)
        return ProviderResult(envelope, self.name, self.model, text, data.get("usage"))


def make_provider(name: str, model: str = "") -> tuple[object, str]:
    """Return (provider, note). Raises ProviderError when a key is missing."""
    name = (name or "auto").lower()
    if name == "heuristic":
        return HeuristicProvider(), "offline baseline, no model call"
    if name == "anthropic":
        return AnthropicProvider(model), ""
    if name == "openai":
        return OpenAIProvider(model), ""
    if name == "auto":
        if os.environ.get("ANTHROPIC_API_KEY"):
            return AnthropicProvider(model), "auto-selected anthropic"
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAIProvider(model), "auto-selected openai"
        return HeuristicProvider(), "no API key found; using offline heuristic baseline"
    raise ProviderError(f"unknown provider '{name}' (expected auto, heuristic, anthropic or openai)")
