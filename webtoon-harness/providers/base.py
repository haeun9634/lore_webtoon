"""이미지 생성 provider 공통 인터페이스.

새 provider 를 붙이려면:
  1) 이 파일의 ImageProvider 를 상속해 generate() 를 구현
  2) providers/__init__.py 의 REGISTRY 에 이름을 등록
  3) config.yaml 의 provider.name 을 그 이름으로 변경
run.py 는 이 인터페이스 밖의 것을 알지 못한다.
"""

from __future__ import annotations

import mimetypes
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ProviderError(RuntimeError):
    """생성 실패. 재시도 가능한 실패는 retryable=True.

    refusal 은 **거절**이다 — 모델이 "못 만들겠다"고 답한 경우 (안전 필터).
    네트워크 오류나 5xx 와 성격이 완전히 다르다:

      · 다시 시도해도 같은 답이 온다 (retryable=False)
      · 고칠 사람은 우리가 아니라 **입력을 쓴 사용자**다
      · 그래서 사용자에게 원문 그대로 보여줘야 한다

    실제로 문제가 되는 자리: 나이를 13세로 적으면 미성년 묘사로 판단해 이미지
    모델이 거절할 수 있다. 그때 "생성 실패"라고만 뜨면 사용자는 무엇을 고쳐야
    할지 알 수 없다. detail 에 모델이 돌려준 사유를 통째로 담아 두고, 위쪽
    (run.py → landing)에서 파일로 남기고 화면에 띄운다.
    """

    def __init__(self, message: str, retryable: bool = True,
                 refusal: bool = False, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.refusal = refusal
        self.detail = detail or {}


@dataclass
class GenRequest:
    prompt: str
    images: list[Path] = field(default_factory=list)  # 첨부 레퍼런스 (순서 유지)


@dataclass
class GenResult:
    image_bytes: bytes
    mime_type: str = "image/png"
    meta: dict[str, Any] = field(default_factory=dict)  # 로그에 남길 부가 정보


def guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "image/png"


class ImageProvider(ABC):
    """이미지 생성 API 어댑터."""

    name: str = "base"

    def __init__(self, model: str, api_key: str | None, options: dict[str, Any] | None = None):
        self.model = model
        self.api_key = api_key
        self.options = options or {}

    @abstractmethod
    def generate(self, req: GenRequest) -> GenResult:
        """이미지 1장 생성. 실패 시 ProviderError."""

    def requires_api_key(self) -> bool:
        return True

    def describe(self) -> str:
        return f"{self.name}:{self.model}"
