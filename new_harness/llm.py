#!/usr/bin/env python3
"""단계마다 다른 모델을 부를 수 있는 텍스트 호출 계층.

프로바이더 구현(OpenAI·Gemini·Anthropic)은 story-harness/story.py 것을 그대로
빌려 쓴다. 여기서 다시 짜면 재시도·이미지 첨부·토큰 집계가 조금씩 달라지고,
그 차이가 결과 차이로 나타난다.

모델은 .env 만 고치면 바뀐다. 우선순위:

    <STAGE>_PROVIDER / <STAGE>_MODEL   (단계별)
      -> NH_PROVIDER / NH_MODEL        (이 하네스 전체 기본)
      -> PROVIDER                      (story-harness 와 같은 기본)

단계 이름은 STORY · BOARD · SHEET 다. 예를 들어 이야기만 GPT 로 뽑고 콘티는
Gemini 로 두려면 .env 에 이렇게 적는다:

    NH_PROVIDER=gemini
    STORY_PROVIDER=openai
    STORY_MODEL=gpt-5.1
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORY_HARNESS = HERE.parent / "story-harness"


def load_dotenv(path: Path) -> None:
    """.env 를 os.environ 에 넣는다. 이미 있는 값은 덮어쓰지 않는다."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = (p.strip() for p in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if value:
            os.environ.setdefault(key, value)


# new_harness/.env 를 story-harness/.env 보다 **먼저** 읽는다. 둘 다
# setdefault 라 먼저 읽힌 쪽이 이긴다 — 모델 선택은 여기서 하고, API 키는
# 이미 있는 story-harness/.env 것을 그대로 물려받는다.
load_dotenv(HERE / ".env")

if str(STORY_HARNESS) not in sys.path:
    sys.path.insert(0, str(STORY_HARNESS))

import story  # noqa: E402  (sys.path 를 세운 뒤에야 import 할 수 있다)


PROVIDERS = tuple(story.PROVIDERS)          # gemini / openai / anthropic
IMAGE_PROVIDERS = tuple(story.IMAGE_PROVIDERS)      # gemini / openai

# 글을 쓰는 단계 / 그림을 그리는 단계. 이름이 곧 .env 의 앞자리다
# (STORY_PROVIDER · SHEET_IMAGE_MODEL …).
TEXT_STAGES = ("STORY", "DETAIL", "CUTSCRIPT", "CUTSCRIPT_FIX",
               "REVIEW", "FIX", "BOARD", "SHEET")
IMAGE_STAGES = ("SHEET_IMAGE", "PAGE_IMAGE")
STAGES = TEXT_STAGES + IMAGE_STAGES

DEFAULT_MAX_TOKENS = story.env_int("NH_MAX_TOKENS", 16000)
DEFAULT_TEMPERATURE = story.env_float("NH_TEMPERATURE", 0.9)


def env(key: str, default=None):
    return story.env(key, default)


def _pick(stage: str, suffix: str, fallbacks: tuple) -> tuple[str, str]:
    """(값, 어디서 왔는지). 어디서 왔는지는 --plan 이 보여 준다.

    ".env 를 고쳤는데 왜 그대로지" 를 혼자 알아내게 두지 않으려는 것이다 —
    단계별 값이 있으면 전체 기본은 안 쓰이는데, 화면에 이름만 찍히면 어느
    줄이 이겼는지 알 수 없다.
    """
    key = f"{stage.upper()}_{suffix}"
    value = env(key)
    if value:
        return value.strip(), key
    for other in fallbacks:
        value = env(other)
        if value:
            return value.strip(), other
    return "", ""


def provider_for(stage: str) -> str:
    """이 단계가 쓸 프로바이더. 모르는 이름이면 거기서 멈춘다."""
    name, where = _pick(stage, "PROVIDER", ("NH_PROVIDER", "PROVIDER"))
    name = (name or "gemini").lower()
    allowed = IMAGE_PROVIDERS if stage.upper() in IMAGE_STAGES else PROVIDERS
    if name not in allowed:
        raise SystemExit(
            f"{where or stage.upper() + '_PROVIDER'}='{name}' 를 모릅니다. "
            f"{' / '.join(sorted(allowed))} 중 하나여야 합니다.")
    return name


def image_default(provider: str) -> str:
    """provider 가 쓸 이미지 모델 이름. 키가 없어도 이름은 알려준다.

    image_backend_ready 는 (쓸 수 있는가, 모델, 사유) 를 돌려주는데, 여기서는
    모델 이름만 본다 — --plan 은 키가 없어도 돌아야 하기 때문이다.
    """
    return story.image_backend_ready(provider)[1]


def model_for(stage: str, provider: str) -> str:
    """이 단계가 쓸 모델 이름."""
    if stage.upper() in IMAGE_STAGES:
        model, _ = _pick(stage, "MODEL", ("NH_IMAGE_MODEL",))
        return model or image_default(provider)
    model, _ = _pick(stage, "MODEL", ("NH_MODEL",))
    return model or story.default_model_for(provider)


def load_images(paths) -> list:
    """사진 경로 목록 -> story.load_image 결과 목록."""
    return [story.load_image(p) for p in (paths or [])]


class Call:
    """한 단계의 호출 한 번. 어느 모델이 무엇을 얼마나 썼는지 같이 돌려준다."""

    def __init__(self, stage: str, provider: str = None, model: str = None,
                 max_retries: int = 3):
        self.stage = stage.upper()
        self.provider = (provider or provider_for(self.stage)).strip().lower()
        if self.provider not in PROVIDERS:
            raise SystemExit(f"알 수 없는 provider: {self.provider}")
        self.model = model or model_for(self.stage, self.provider)
        self.backend = story.make_backend(self.provider, max_retries=max_retries)
        self.temp_ok = self.backend.supports_temperature(self.model)

    def describe(self) -> str:
        return f"{self.provider}:{self.model}"

    def __call__(self, prompt: str, images=None, temperature: float = None,
                 max_tokens: int = None) -> tuple[str, dict]:
        temp = DEFAULT_TEMPERATURE if temperature is None else temperature
        text, usage, stop = self.backend.complete(
            self.model,
            prompt,
            temp if self.temp_ok else None,
            max_tokens or DEFAULT_MAX_TOKENS,
            images=images or None,
        )
        meta = {
            "stage": self.stage,
            "provider": self.provider,
            "model": self.model,
            "usage": usage,
            "stop": stop,
            "cost": story.cost_of(self.model, usage),
        }
        if stop == "max_tokens":
            story.warn(f"[{self.stage}] 응답이 길이 제한에서 끊겼습니다 "
                       f"(NH_MAX_TOKENS={max_tokens or DEFAULT_MAX_TOKENS}).")
        return text, meta


STAGE_LABEL = {
    "STORY": "이야기 후보",
    "DETAIL": "스토리 구체화",
    "CUTSCRIPT": "컷 대본",
    "REVIEW": "스토리 검수",
    "FIX": "지적 반영",
    "CUTSCRIPT_FIX": "컷 대본 픽스 (독자 검수·자기수정)",
    "BOARD": "콘티",
    "SHEET": "시트 사양",
    "SHEET_IMAGE": "시트 그림",
    "PAGE_IMAGE": "페이지 그림",
}


def plan() -> list[dict]:
    """지금 .env 로 각 단계가 어느 모델을 쓰는지. 실행 전에 보여 준다."""
    out = []
    for stage in STAGES:
        provider = provider_for(stage)
        _, pfrom = _pick(stage, "PROVIDER", ("NH_PROVIDER", "PROVIDER"))
        _, mfrom = _pick(stage, "MODEL",
                         ("NH_IMAGE_MODEL",) if stage in IMAGE_STAGES else ("NH_MODEL",))
        out.append({
            "stage": stage,
            "label": STAGE_LABEL.get(stage, stage),
            "image": stage in IMAGE_STAGES,
            "provider": provider,
            "model": model_for(stage, provider),
            "from": mfrom or pfrom or "기본값",
        })
    return out
