"""Provider 레지스트리. 새 provider 는 여기 한 줄만 추가하면 config 로 교체 가능."""

from __future__ import annotations

from typing import Any

from .base import GenRequest, GenResult, ImageProvider, ProviderError
from .gemini import GeminiProvider
from .mock import MockProvider
# 파일 이름이 openai.py 가 아니라 openai_images.py 인 이유: 그 안에서 SDK 를
# `import openai` 로 부르는데, 같은 이름이면 자기 자신을 가리킬 위험이 있다.
from .openai_images import OpenAIProvider

REGISTRY: dict[str, type[ImageProvider]] = {
    "gemini": GeminiProvider,
    "openai": OpenAIProvider,
    "mock": MockProvider,
}

__all__ = [
    "GenRequest",
    "GenResult",
    "ImageProvider",
    "ProviderError",
    "REGISTRY",
    "build_provider",
]


def build_provider(name: str, model: str, api_key: str | None, options: dict[str, Any] | None = None) -> ImageProvider:
    try:
        cls = REGISTRY[name]
    except KeyError:
        known = ", ".join(sorted(REGISTRY))
        raise SystemExit(f"[config] 알 수 없는 provider '{name}'. 사용 가능: {known}") from None
    return cls(model=model, api_key=api_key, options=options)
