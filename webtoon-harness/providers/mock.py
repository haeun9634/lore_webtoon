"""API 호출 없이 더미 PNG 를 만드는 provider.

키 없이 전체 파이프라인(로그 / compare.html / score_sheet.csv)을 끝까지
돌려보고 싶을 때 config.yaml 의 provider.name 을 mock 으로 바꾼다.
프롬프트 해시로 색을 정하므로 같은 프롬프트면 같은 색, 다르면 다른 색이 나온다.
외부 의존성(PIL 등) 없이 PNG 를 직접 인코딩한다.
"""

from __future__ import annotations

import hashlib
import struct
import time
import zlib

from .base import GenRequest, GenResult, ImageProvider

SIZE = 512


def _png(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    row = b"\x00" + bytes(rgb) * width  # 필터 바이트 0 + RGB 픽셀
    raw = row * height

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit truecolor
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 6))
        + chunk(b"IEND", b"")
    )


class MockProvider(ImageProvider):
    name = "mock"

    def requires_api_key(self) -> bool:
        return False

    def generate(self, req: GenRequest) -> GenResult:
        time.sleep(float(self.options.get("fake_latency_sec", 0.1)))
        seed = hashlib.sha256(req.prompt.encode("utf-8")).digest()
        # 너무 어둡지 않게 128~255 범위로
        rgb = (128 + seed[0] // 2, 128 + seed[1] // 2, 128 + seed[2] // 2)
        return GenResult(
            image_bytes=_png(SIZE, SIZE, rgb),
            mime_type="image/png",
            meta={"mock": True, "rgb": rgb, "attached": len(req.images)},
        )
