"""OpenAI (images) 이미지 생성 provider.

모델 예: gpt-image-2 (gpt-image-1 은 2026-10-23 종료)

레퍼런스 이미지가 있으면 /images/edits 로, 없으면 /images/generations 로
부른다 — 텍스트→이미지 쪽은 원본 이미지를 아예 안 받기 때문이다.

SDK(openai 패키지) 대신 requests 를 쓰는 것은 이 하네스의 방식이다
(gemini.py · textgen.py 도 같다). 의존성이 requests·PyYAML·Pillow 셋으로
유지돼서, provider 를 바꾸려고 새 패키지를 깔 필요가 없다.

**Gemini 와 다른 점** (config.yaml 의 provider.options 를 그대로 못 쓴다):

  · aspect_ratio → OpenAI 는 자유 비율이 아니라 정해진 세 크기뿐이다.
    9:16 같은 세로 비율은 1024x1536 으로, 16:9 는 1536x1024 로 맞춘다.
    정확히 그 비율이 아니라 **가장 가까운 것**이라, 세로 스크롤 웹툰의
    캔버스 모양이 Gemini 로 뽑을 때와 미묘하게 달라진다.
  · image_size(1K/2K/4K) · response_modalities → 없는 개념이라 무시한다.
    대신 quality(low|medium|high)가 그 자리다.
  · seed → **없다.** Gemini 쪽 시드 재현성(같은 프롬프트 → 같은 그림)은
    여기서 안 된다. 조용히 무시하면 "시드를 넣었는데 왜 매번 다르지" 로
    헤매므로 한 번 경고를 찍는다.
"""

from __future__ import annotations

import base64
from typing import Any

import requests

from .base import GenRequest, GenResult, ImageProvider, ProviderError, guess_mime

GENERATE_URL = "https://api.openai.com/v1/images/generations"
EDIT_URL = "https://api.openai.com/v1/images/edits"

# gpt-image 가 받는 크기. 이 셋과 "auto" 밖의 값을 주면 400 이 온다.
SQUARE = "1024x1024"
PORTRAIT = "1024x1536"
LANDSCAPE = "1536x1024"

QUALITIES = ("low", "medium", "high")
DEFAULT_QUALITY = "medium"

# 재시도해도 소용없는 상태코드 (gemini.py 와 같은 기준).
FATAL_STATUS = {400, 401, 403, 404}

# 거절(안전 필터)임을 알려주는 표식. OpenAI 는 상태코드가 400 이라 잘못된
# 인자와 구분이 안 되므로 본문의 말을 같이 본다.
REFUSAL_MARKERS = (
    "moderation_blocked", "content_policy", "safety system", "safety_violation",
    "rejected as a result of our safety system", "content_policy_violation",
)


def size_for_aspect(aspect: str) -> str:
    """"9:16" 같은 비율 문자열 → gpt-image 가 받는 크기.

    정확히 맞는 크기가 없으므로 **가장 가까운 것**을 고른다. 못 읽는 값이면
    정사각형으로 몰지 않고 auto 를 준다 — 모델이 프롬프트를 보고 고른다.
    """
    raw = str(aspect or "").strip()
    if not raw:
        return "auto"
    try:
        w_s, _, h_s = raw.partition(":")
        w, h = float(w_s), float(h_s)
        if w <= 0 or h <= 0:
            return "auto"
    except (TypeError, ValueError):
        return "auto"
    ratio = w / h
    # 경계는 정사각형(1.0)과 각 방향 사이의 중간쯤. 1024x1536 은 0.667,
    # 1536x1024 는 1.5 이므로 그 사이를 갈랐다.
    if ratio < 0.85:
        return PORTRAIT
    if ratio > 1.18:
        return LANDSCAPE
    return SQUARE


class OpenAIProvider(ImageProvider):
    name = "openai"

    def __init__(self, model: str, api_key: str | None,
                 options: dict[str, Any] | None = None):
        super().__init__(model, api_key, options)
        self._warned_seed = False

    def _quality(self) -> str:
        want = str(self.options.get("quality") or DEFAULT_QUALITY).strip().lower()
        if want not in QUALITIES:
            print(f"    ! quality='{want}' 는 모르는 값입니다 "
                  f"({'/'.join(QUALITIES)} 중 하나) — {DEFAULT_QUALITY} 로 갑니다.")
            return DEFAULT_QUALITY
        return want

    def _size(self) -> str:
        # config 가 size 를 직접 적어 뒀으면 그대로 쓴다(비율 변환보다 우선).
        explicit = str(self.options.get("size") or "").strip()
        return explicit or size_for_aspect(self.options.get("aspect_ratio"))

    def _note_unsupported(self) -> None:
        """Gemini 전용 옵션이 들어오면 한 번만 알린다 — 조용히 버리지 않는다."""
        if self.options.get("seed") is not None and not self._warned_seed:
            self._warned_seed = True
            print("    ! OpenAI 이미지 API 는 seed 를 안 받습니다 — 시드 재현은 "
                  "Gemini 로 그릴 때만 됩니다 (이 값은 무시합니다).")

    def generate(self, req: GenRequest) -> GenResult:
        self._note_unsupported()
        timeout = float(self.options.get("timeout_sec", 300))
        headers = {"Authorization": f"Bearer {self.api_key or ''}"}
        is_gpt_image = str(self.model).startswith("gpt-image")

        fields: dict[str, Any] = {
            "model": self.model,
            "prompt": req.prompt,
            "size": self._size(),
            "n": 1,
        }
        if is_gpt_image:
            fields["quality"] = self._quality()

        try:
            if req.images:
                # 레퍼런스가 있으면 편집 쪽으로 간다 — 통합 시트·직전 컷을
                # 붙여서 인물이 이어지게 하는 것이 조건 S+ 의 핵심이다.
                # multipart 라 값은 전부 문자열로 나간다.
                files = [
                    ("image[]", (p.name, p.read_bytes(), guess_mime(p)))
                    for p in req.images
                ]
                resp = requests.post(
                    EDIT_URL, headers=headers, timeout=timeout,
                    data={k: str(v) for k, v in fields.items()}, files=files)
            else:
                if not is_gpt_image:
                    # dall-e-3 는 기본이 URL 이라 base64 를 따로 요구해야 한다.
                    fields["response_format"] = "b64_json"
                resp = requests.post(
                    GENERATE_URL,
                    headers={**headers, "Content-Type": "application/json"},
                    timeout=timeout, json=fields)
        except requests.RequestException as exc:
            raise ProviderError(f"network error: {exc}", retryable=True) from exc

        if resp.status_code != 200:
            snippet = resp.text[:600].replace("\n", " ")
            low = snippet.lower()
            if any(m in low for m in REFUSAL_MARKERS):
                # 사유를 통째로 남긴다 — 사용자가 무엇을 고쳐야 할지는 이
                # 문장에만 있다 (나이·묘사 때문에 걸리는 자리가 실제로 있다).
                raise ProviderError(
                    f"이미지 모델이 거절했습니다: {snippet}",
                    retryable=False, refusal=True,
                    detail={"stage": "response", "provider": "openai",
                            "model_said": resp.text[:1000]})
            raise ProviderError(
                f"HTTP {resp.status_code}: {snippet}",
                retryable=resp.status_code not in FATAL_STATUS)

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"invalid JSON response: {resp.text[:300]}") from exc

        return self._extract_image(data)

    @staticmethod
    def _extract_image(data: dict[str, Any]) -> GenResult:
        items = data.get("data") or []
        item = items[0] if items else None
        if item is None:
            raise ProviderError(f"응답에 이미지가 없습니다: {str(data)[:400]}",
                                retryable=False)
        b64 = item.get("b64_json")
        if b64:
            return GenResult(
                image_bytes=base64.b64decode(b64),
                mime_type="image/png",
                meta={"revised_prompt": item.get("revised_prompt"),
                      "usage": data.get("usage")},
            )
        if item.get("url"):
            # URL 은 만료돼서 나중에 다시 못 읽는다. gpt-image 는 언제나 base64 다.
            raise ProviderError(
                "모델이 base64 대신 URL 을 돌려줬습니다. OPENAI_IMAGE_MODEL 을 "
                "gpt-image-2 로 두세요 (URL 은 만료됩니다).",
                retryable=False)
        raise ProviderError(f"응답에 이미지 데이터가 없습니다: {str(item)[:400]}",
                            retryable=False)
