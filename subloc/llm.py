"""LM Studio (OpenAI-compatible) client: model listing, selection, chat."""

from dataclasses import dataclass

import httpx

from .errors import ContextTooLong, ModelNotAvailable, SublocError, TranslatorUnavailable

DEFAULT_URL = "http://localhost:1234"

# Suggestions only — the user always picks. Matched by substring of the model id.
HINTS: list[tuple[str, str]] = [
    ("bonsai", "Not recommended: 1-bit, low quality"),
    ("mistral", "Not recommended: old, English-focused"),
    ("uncensored", "Use if another model refuses or softens mature dialogue"),
    ("gemma-4-26b-a4b", "Recommended: fast, strong Arabic"),
    ("gemma-4-31b", "Best quality, slower"),
    ("qwen3.8-27b", "Strong for Japanese / Korean / Chinese sources"),
    ("gemma-4-e4b", "Light: for weaker PCs"),
    ("gemma-4-e2b", "Lightest: for weak PCs, lower quality"),
]


@dataclass
class ModelInfo:
    id: str
    vision: bool
    loaded: bool
    quantization: str | None

    @property
    def hint(self) -> str:
        return next((h for key, h in HINTS if key in self.id.lower()), "")


class LMStudio:
    def __init__(self, base_url: str = DEFAULT_URL, timeout: float = 600):
        self.base_url = base_url.rstrip("/")
        # Fail fast when nothing is listening; allow long answers (first request may load the model).
        self.http = httpx.Client(timeout=httpx.Timeout(timeout, connect=5.0))

    def list_models(self) -> list[ModelInfo]:
        """Chat-capable models (LLM/VLM), loaded ones first. Uses LM Studio's richer endpoint when
        available, else the standard OpenAI one (llama-server, Ollama: every listed model counts as loaded)."""
        r = self._request("GET", "/api/v0/models")
        if r.status_code == 404:
            r = self._request("GET", "/v1/models")
            r.raise_for_status()
            return [
                ModelInfo(m["id"], False, True, None)
                for m in r.json().get("data", [])
                if "embed" not in m["id"].lower()
            ]
        r.raise_for_status()
        models = [
            ModelInfo(m["id"], m["type"] == "vlm", m.get("state") == "loaded", m.get("quantization"))
            for m in r.json()["data"]
            if m.get("type") in ("llm", "vlm")
        ]
        return sorted(models, key=lambda m: not m.loaded)

    def _request(self, method: str, path: str, **kw) -> httpx.Response:
        try:
            return self.http.request(method, f"{self.base_url}{path}", **kw)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise TranslatorUnavailable(
                "Can't reach LM Studio. Open LM Studio, load a model and start its local server "
                "(Developer tab → Start Server), then press Start again — progress is kept.",
                str(e),
            ) from e
        except httpx.ReadTimeout as e:
            raise SublocError("LM Studio took too long to answer.", str(e)) from e
        except httpx.RemoteProtocolError as e:  # server closed mid-answer (stopped / crashed)
            raise TranslatorUnavailable(
                "LM Studio stopped answering. Check that it's still running, then press Start again — "
                "progress is kept.",
                str(e),
            ) from e

    def default_model(self, need_vision: bool = False) -> ModelInfo | None:
        """Default = whatever is currently loaded in LM Studio."""
        return next(
            (m for m in self.list_models() if m.loaded and (m.vision or not need_vision)),
            None,
        )

    def chat(
        self,
        model: str,
        messages: list[dict],
        json_schema: dict | None = None,
        temperature: float = 0.2,
        reasoning: str | None = "none",
    ) -> str:
        """`reasoning="none"` turns off thinking (much faster; same quality for these tasks)."""
        body: dict = {"model": model, "messages": messages, "temperature": temperature}
        if reasoning:
            body["reasoning_effort"] = reasoning
        if json_schema:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "strict": True, "schema": json_schema},
            }
        r = self._request("POST", "/v1/chat/completions", json=body)
        if r.status_code >= 400:
            text = r.text[:500]
            low = text.lower()
            if "context" in low and ("length" in low or "exceed" in low or "overflow" in low or "too long" in low):
                raise ContextTooLong("Too much text for the model's context window.", text)
            if r.status_code == 404 or (
                "model" in low
                and ("not found" in low or "no model" in low or "not loaded" in low or "failed to load" in low)
            ):
                raise ModelNotAvailable(
                    f"The model “{model}” isn't available in LM Studio. Load it there, or pick another one.", text
                )
            raise SublocError(f"LM Studio returned an error ({r.status_code}).", text)
        try:
            return r.json()["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError) as e:
            raise SublocError("LM Studio sent an answer Subloc couldn't read.", r.text[:500]) from e
