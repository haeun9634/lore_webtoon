#!/usr/bin/env python3
"""이미지 한 장을 그린다. 시트도 페이지도 여기를 지난다.

실제 호출은 story-harness 의 make_sheet_painter 를 그대로 쓴다 — 컷을 그리는
코드와 같은 경로다. 여기서 다시 구현하면 재시도·응답 파싱·참조 이미지 첨부가
조금씩 달라지고, 그 차이가 그림 차이로 나타난다.

story.py 는 한 글자도 안 고친다(harness-is-final). 대신 그 쪽 크기표에
**페이지용 칸을 하나 더 단다** — make_sheet_painter 가 kind 로 그 표를 찾기
때문에, 표에 없는 이름을 넘기면 KeyError 다. 기존 칸은 안 건드리므로 시트는
예전과 똑같이 나온다.
"""

from __future__ import annotations

from pathlib import Path

import cost
import llm
from llm import story

SHEET_KIND = "sheet"        # 가로로 넓은 자료 시트 (story.py 가 이미 아는 칸)
PAGE_KIND = "page"          # 세로로 읽는 웹툰 페이지 — 여기서 더한다

# 세로 스크롤 웹툰이라 페이지는 세로로 길어야 한다.
#
# ★ 두 프로바이더의 캔버스 **모양이 다르다.** 같은 프롬프트를 줘도 한 페이지에
#   들어가는 세로 길이가 달라진다:
#
#       Gemini  9:16       = 세로/가로 1.78
#       OpenAI  1024x1536  = 세로/가로 1.50   (약 16% 짧다)
#
#   OpenAI 는 gpt-image 가 받는 크기가 1024x1024 · 1024x1536 · 1536x1024
#   셋뿐이라 더 긴 값을 줄 수가 없다. Gemini 도 9:16 이 천장이다 —
#   webtoon-harness 가 실측해 뒀다(config.yaml: 1:2 · 9:21 · 1:3 은 전부 400,
#   image_size 를 올려도 픽셀만 늘고 캔버스 모양은 같다).
#
#   그래서 한 페이지에 컷을 많이 모을수록 각 컷이 납작해지고, 그 정도가
#   프로바이더마다 다르다. 페이지에 컷을 몇 개까지 모을지(pages.max_ratio)는
#   그래서 이 표에서 뽑는다 — 손으로 맞추게 두면 프로바이더를 바꿀 때마다
#   같이 바꿔야 하는 것을 잊는다.
# 프로바이더별 페이지 캔버스. **값은 .env 로 바꾼다** — 모델을 갈아 끼울 때마다
# 코드를 뜯어고치게 두지 않는다.
#
#     PAGE_CANVAS_OPENAI=1024x1536      OpenAI 는 픽셀 (받는 값이 셋뿐이다)
#     PAGE_CANVAS_GEMINI=9:16           Gemini 는 비율
#
# 세로/가로는 이 값에서 뽑는다. 따로 적어 두면 두 곳이 갈라진다.
PAGE_CANVAS = {"openai": "1024x1536", "gemini": "9:16"}
DEFAULT_ASPECT = 16 / 9


def canvas_for(provider: str) -> str:
    name = (provider or "").strip().lower()
    return (llm.env(f"PAGE_CANVAS_{name.upper()}")
            or PAGE_CANVAS.get(name) or "9:16")


def page_aspect(provider: str) -> float:
    """캔버스 문자열 -> 세로/가로. `1024x1536` 도 `9:16` 도 읽는다."""
    text = canvas_for(provider)
    for sep in ("x", "X", ":"):
        if sep in text:
            a, _, b = text.partition(sep)
            try:
                w, h = float(a), float(b)
            except ValueError:
                break
            if w > 0:
                return h / w
    story.warn(f"캔버스 '{text}' 를 읽지 못했습니다. {DEFAULT_ASPECT:.2f} 로 봅니다.")
    return DEFAULT_ASPECT


# story.py 의 시트 크기표에 페이지 칸을 단다. 프로바이더마다 다른 값이라
# 둘 다 넣는다 — make_sheet_painter 는 provider 에 맞는 쪽만 읽는다.
story.CHARSHEET_SIZES.setdefault(PAGE_KIND, canvas_for("openai"))
story.CHARSHEET_RATIOS.setdefault(PAGE_KIND, canvas_for("gemini"))


def backend_for(stage: str) -> tuple[str, str, str]:
    """(provider, model, quality). 못 쓰면 왜 못 쓰는지를 달고 멈춘다."""
    provider = llm.provider_for(stage).strip().lower()
    ok, default_model, why = story.image_backend_ready(provider)
    if not ok:
        raise SystemExit(why)
    model = llm.model_for(stage, provider) or default_model
    quality = (llm.env("OPENAI_IMAGE_QUALITY") or "high").strip().lower()
    return provider, model, quality


def paint(stage: str, prompt: str, out_path: Path, refs=None,
          kind: str = SHEET_KIND) -> dict:
    """한 장 그려서 저장한다. refs 는 같이 붙일 참조 이미지 경로.

    refs 순서가 곧 모델이 보는 순서다. 부르는 쪽이 정한다 — 시트를 먼저,
    직전 페이지를 마지막에 두는 것이 webtoon-harness 가 쓰는 순서와 같다.
    """
    provider, model, quality = backend_for(stage)
    refs = [Path(r) for r in (refs or []) if Path(r).exists()]

    painter, label = story.make_sheet_painter(provider, model, quality, refs)
    data, meta = painter(prompt, kind)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    cost_info = cost.cost_fields(provider, model, quality, (meta or {}).get("usage_dict"))
    return {"stage": stage, "provider": provider, "model": model, "backend": label,
            "quality": quality, "bytes": len(data),
            "refs": [r.name for r in refs], "meta": meta or {}, "cost": cost_info,
            "output_path": str(out_path)}
