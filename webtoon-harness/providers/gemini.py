"""Google Gemini (generateContent) 이미지 생성 provider.

레퍼런스 이미지는 inline_data 파트로 여러 장 동시 첨부한다 (조건 B/C/D).
모델 예: gemini-3-pro-image-preview, gemini-2.5-flash-image
"""

from __future__ import annotations

import base64
from typing import Any

import requests

from .base import GenRequest, GenResult, ImageProvider, ProviderError, guess_mime

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# 재시도해도 소용없는 상태코드
FATAL_STATUS = {400, 401, 403, 404}


class GeminiProvider(ImageProvider):
    name = "gemini"

    def _generation_config(self) -> dict[str, Any]:
        opt = self.options
        cfg: dict[str, Any] = {}
        if opt.get("response_modalities"):
            cfg["responseModalities"] = list(opt["response_modalities"])
        image_cfg: dict[str, Any] = {}
        if opt.get("aspect_ratio"):
            image_cfg["aspectRatio"] = opt["aspect_ratio"]
        if opt.get("image_size"):
            image_cfg["imageSize"] = opt["image_size"]
        if image_cfg:
            cfg["imageConfig"] = image_cfg
        # 시드 — "같은 프롬프트, 같은 모델인데 그림체가 다르게 나온다"는 실사용자
        # 지적(2026-08) 때문에 넣었다. 시드를 고정하면 같은 프롬프트가 같은 그림
        # 근처로 돌아온다. **기본값은 없다** — options 에 seed 를 안 적으면 이
        # 키 자체가 안 붙어서 예전 run 과 요청 본문이 한 글자도 안 달라진다.
        # 다만 컷마다 같은 시드를 쓰면 모든 컷이 서로 닮아버리므로, 컷별로 다른
        # 값을 넣는 일은 부르는 쪽(run.py)이 한다 — 여기는 받은 값을 실을 뿐이다.
        if opt.get("seed") is not None:
            try:
                cfg["seed"] = int(opt["seed"])
            except (TypeError, ValueError):
                pass
        return cfg

    def generate(self, req: GenRequest) -> GenResult:
        parts: list[dict[str, Any]] = [{"text": req.prompt}]
        for path in req.images:
            parts.append(
                {
                    "inline_data": {
                        "mime_type": guess_mime(path),
                        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
                    }
                }
            )

        body: dict[str, Any] = {"contents": [{"role": "user", "parts": parts}]}
        gen_cfg = self._generation_config()
        if gen_cfg:
            body["generationConfig"] = gen_cfg

        url = ENDPOINT.format(model=self.model)
        timeout = float(self.options.get("timeout_sec", 300))

        try:
            resp = requests.post(
                url,
                headers={
                    "x-goog-api-key": self.api_key or "",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"network error: {exc}", retryable=True) from exc

        if resp.status_code != 200:
            snippet = resp.text[:600].replace("\n", " ")
            raise ProviderError(
                f"HTTP {resp.status_code}: {snippet}",
                retryable=resp.status_code not in FATAL_STATUS,
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise ProviderError(f"invalid JSON response: {resp.text[:300]}") from exc

        return self._extract_image(data)

    # 모델이 "안 만들겠다"고 답할 때 오는 사유들. 재시도해도 같은 답이 온다.
    REFUSAL_FINISH = {"PROHIBITED_CONTENT", "SAFETY", "IMAGE_SAFETY", "BLOCKLIST",
                      "SPII", "RECITATION"}

    @staticmethod
    def _extract_image(data: dict[str, Any]) -> GenResult:
        candidates = data.get("candidates") or []
        if not candidates:
            feedback = data.get("promptFeedback") or {}
            reason = feedback.get("blockReason", "no candidates")
            # 후보가 아예 안 온 것은 프롬프트 단계에서 걸린 것이다 — 거의 항상
            # 안전 필터다. 사유·등급을 통째로 넘겨서 사용자에게 그대로 보여준다.
            raise ProviderError(
                f"no image returned ({reason})", retryable=False,
                refusal=True,
                detail={
                    "stage": "prompt",
                    "block_reason": feedback.get("blockReason"),
                    "block_reason_message": feedback.get("blockReasonMessage"),
                    "safety_ratings": feedback.get("safetyRatings"),
                })

        cand = candidates[0]
        finish = cand.get("finishReason")
        texts: list[str] = []
        for part in (cand.get("content") or {}).get("parts") or []:
            # 요청은 snake_case, 응답은 camelCase 로 오는 경우가 섞여 있어 둘 다 본다.
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return GenResult(
                    image_bytes=base64.b64decode(inline["data"]),
                    mime_type=inline.get("mimeType") or inline.get("mime_type") or "image/png",
                    meta={
                        "finish_reason": finish,
                        "usage": data.get("usageMetadata"),
                        "text": " ".join(texts)[:500] or None,
                    },
                )
            if part.get("text"):
                texts.append(part["text"])

        said = " ".join(texts).strip()
        detail = said[:300] or "(no text)"
        refused = finish in GeminiProvider.REFUSAL_FINISH
        raise ProviderError(
            f"response had no image part (finishReason={finish}): {detail}",
            retryable=not refused,
            refusal=refused,
            # 이미지 대신 글로 답한 경우, 그 글이 곧 거절 사유다 ("I can't
            # generate images of minors in ..." 같은 문장). 잘라내지 말고
            # 그대로 남긴다 — 사용자가 무엇을 고쳐야 할지는 이 문장에만 있다.
            detail={
                "stage": "response",
                "finish_reason": finish,
                "model_said": said or None,
                "safety_ratings": cand.get("safetyRatings"),
            },
        )
