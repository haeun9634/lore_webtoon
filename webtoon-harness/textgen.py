"""텍스트 LLM 클라이언트 — prompt_gen / scene_gen / cut_split 전용.

이미지 provider(providers/)와 **완전히 분리되어 있다.** 그림은 Gemini 로 뽑으면서
글(한국어 콘티 -> 영어 패널 서술)은 다른 모델에 맡길 수 있고, 그러는 편이 나은
경우가 있다 — 이 단계는 창작이 아니라 번역에 가깝고, 번역 품질과 그림 품질은
같은 모델이 잘한다는 보장이 없다.

어느 것을 쓸지는 config.yaml 의 text.provider 가 정한다 (gemini | openai).
키와 모델 이름은 .env 에서 온다 — config 에는 **어느 환경변수를 읽을지**만 적는다.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
FATAL_STATUS = {400, 401, 403, 404}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class TextError(RuntimeError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class GeminiText:
    def __init__(self, model: str, api_key: str | None, options: dict[str, Any] | None = None):
        self.model = model
        self.api_key = api_key
        self.options = options or {}

    def describe(self) -> str:
        return f"gemini-text:{self.model}"

    def complete(self, prompt: str, json_mode: bool = True) -> tuple[str, dict[str, Any]]:
        cfg: dict[str, Any] = {}
        if self.options.get("temperature") is not None:
            cfg["temperature"] = float(self.options["temperature"])
        if self.options.get("max_output_tokens"):
            cfg["maxOutputTokens"] = int(self.options["max_output_tokens"])
        if json_mode:
            cfg["responseMimeType"] = "application/json"

        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        if cfg:
            body["generationConfig"] = cfg

        try:
            resp = requests.post(
                ENDPOINT.format(model=self.model),
                headers={"x-goog-api-key": self.api_key or "", "Content-Type": "application/json"},
                json=body,
                timeout=float(self.options.get("timeout_sec", 180)),
            )
        except requests.RequestException as exc:
            raise TextError(f"network error: {exc}", retryable=True) from exc

        if resp.status_code != 200:
            snippet = resp.text[:600].replace("\n", " ")
            raise TextError(f"HTTP {resp.status_code}: {snippet}",
                            retryable=resp.status_code not in FATAL_STATUS)
        try:
            data = resp.json()
        except ValueError as exc:
            raise TextError(f"invalid JSON response: {resp.text[:300]}") from exc

        candidates = data.get("candidates") or []
        if not candidates:
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise TextError(f"응답에 후보가 없습니다 ({reason})", retryable=False)

        cand = candidates[0]
        texts = [p["text"] for p in (cand.get("content") or {}).get("parts") or [] if p.get("text")]
        if not texts:
            raise TextError(f"응답에 텍스트가 없습니다 (finishReason={cand.get('finishReason')})")
        return "\n".join(texts), {
            "finish_reason": cand.get("finishReason"),
            "usage": data.get("usageMetadata"),
        }


class OpenAIText:
    """ChatGPT(OpenAI) 텍스트 클라이언트. GeminiText 와 같은 인터페이스다.

    호출부(call_json)는 어느 쪽인지 몰라야 한다 — describe() 와 complete() 만
    쓴다. 그래서 두 클래스의 반환 모양(본문, meta)을 똑같이 맞춘다.
    """

    def __init__(self, model: str, api_key: str | None, options: dict[str, Any] | None = None):
        self.model = model
        self.api_key = api_key
        self.options = options or {}

    def describe(self) -> str:
        return f"openai-text:{self.model}"

    def complete(self, prompt: str, json_mode: bool = True) -> tuple[str, dict[str, Any]]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.options.get("temperature") is not None:
            body["temperature"] = float(self.options["temperature"])
        if self.options.get("max_output_tokens"):
            body["max_tokens"] = int(self.options["max_output_tokens"])
        if json_mode:
            # JSON 모드를 켜면 모델이 반드시 JSON 하나만 낸다. 프롬프트에
            # "JSON only" 라고 적어 두었어도 켜는 편이 낫다 — 말로 부탁하는 것과
            # 형식으로 막는 것은 다르다.
            body["response_format"] = {"type": "json_object"}

        try:
            resp = requests.post(
                OPENAI_ENDPOINT,
                headers={"Authorization": f"Bearer {self.api_key or ''}",
                         "Content-Type": "application/json"},
                json=body,
                timeout=float(self.options.get("timeout_sec", 180)),
            )
        except requests.RequestException as exc:
            raise TextError(f"network error: {exc}", retryable=True) from exc

        if resp.status_code != 200:
            snippet = resp.text[:600].replace(chr(10), " ")
            raise TextError(f"HTTP {resp.status_code}: {snippet}",
                            retryable=resp.status_code not in FATAL_STATUS)
        try:
            data = resp.json()
        except ValueError as exc:
            raise TextError(f"invalid JSON response: {resp.text[:300]}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise TextError("응답에 choices 가 없습니다", retryable=False)
        msg = (choices[0].get("message") or {})
        text = str(msg.get("content") or "")
        if not text.strip():
            raise TextError(
                f"응답에 텍스트가 없습니다 (finish_reason={choices[0].get('finish_reason')})")
        usage = data.get("usage") or {}
        return text, {
            "finish_reason": choices[0].get("finish_reason"),
            # 사용량 키 이름을 Gemini 쪽에 맞춰 둔다. 원장을 읽는 코드가 두
            # 프로바이더를 구분하지 않아도 되게 하려는 것이다.
            "usage": {"promptTokenCount": usage.get("prompt_tokens"),
                      "candidatesTokenCount": usage.get("completion_tokens"),
                      "totalTokenCount": usage.get("total_tokens")},
        }


PROVIDERS = {"gemini": GeminiText, "openai": OpenAIText}


def build(provider: str, model: str, api_key: str | None,
          options: dict[str, Any] | None = None):
    """config 의 text.provider 로 클라이언트를 고른다."""
    name = str(provider or "gemini").strip().lower()
    cls = PROVIDERS.get(name)
    if cls is None:
        raise TextError(
            f"config.yaml 의 text.provider 를 모릅니다: {provider}"
            f" — 쓸 수 있는 값: {' | '.join(sorted(PROVIDERS))}", retryable=False)
    return cls(model=model, api_key=api_key, options=options)


def extract_json(raw: str) -> Any:
    """```json 펜스 / 앞뒤 잡소리를 걷어내고 첫 JSON 값을 파싱한다."""
    text = raw.strip()
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (text.find("["), text.find("{")) if i >= 0]
    if starts:
        start = min(starts)
        closer = "]" if text[start] == "[" else "}"
        end = text.rfind(closer)
        if end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError as exc:
                raise TextError(f"JSON 파싱 실패: {exc}\n원문 앞부분: {raw[:300]}", retryable=True) from exc
    raise TextError(f"JSON 을 찾지 못했습니다. 원문 앞부분: {raw[:300]}", retryable=True)


def call_json(client, prompt: str, max_retries: int, backoff_sec: float,
              on_retry=None) -> tuple[Any, dict[str, Any], float]:
    """JSON 응답 1건. (파싱된 값, meta, 소요초) — 파싱 실패도 재시도 대상."""
    started = time.time()
    last: Exception | None = None
    for attempt in range(1, max_retries + 2):
        try:
            raw, meta = client.complete(prompt)
            return extract_json(raw), meta, round(time.time() - started, 2)
        except TextError as exc:
            last = exc
            if not exc.retryable or attempt > max_retries:
                break
            if on_retry:
                on_retry(attempt, str(exc))
            time.sleep(backoff_sec * (2 ** (attempt - 1)))
    raise TextError(str(last), retryable=False)
