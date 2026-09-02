# -*- coding: utf-8 -*-
"""완성본에 LORE 표시를 붙인다 — **내보낼 때만.**

만든 사람은 결과물을 SNS·커뮤니티에 올린다. 그때 그림만 돌아다니고 어디서
만들었는지가 안 남으면 퍼질수록 서비스는 아무것도 못 얻는다. 반대로 표시가
있으면 그림 한 장이 그대로 유입 경로가 된다.

**저장물은 안 건드린다.** `episode.png` 도 `baked/` 도 그대로 두고, 내려받는
순간에만 표시를 얹은 사본을 만들어 내보낸다. 이유가 셋이다 —

1. 만드는 동안 보는 화면과 편집실이 깨끗해야 한다. 작업 중에 계속 보이면
   방해가 되고, 편집기에서 얹은 말풍선과 겹쳐 보인다.
2. 표시는 "서비스 밖으로 나가는 파일"의 성질이지 저장물의 성질이 아니다.
   다시 구우면 두 번 찍히는 사고도 구조적으로 안 난다.
3. 나중에 "크레딧을 쓰면 표시를 뗀다"(#60)로 갈 때, 저장물에 박혀 있으면
   이미 만든 작품은 영영 못 뗀다.

붙는 것은 둘이다.

- **아래 브랜드 띠** — 그림 밑에 덧대는 자리. 어디서 만들었는지와 작품·회차를
  적는다. 그림을 안 가린다.
- **반투명 코너 마크** — 그림 오른쪽 아래. 띠만 잘라내도 남는다.

`for_download()` 는 결과를 캐시한다. 한 편은 세로로 아주 긴 그림이라(수만 px)
받을 때마다 다시 그리면 눈에 띄게 느리다.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEBTOON = HERE.parent / "webtoon-harness"
if str(WEBTOON) not in sys.path:
    sys.path.insert(0, str(WEBTOON))

import strip as _strip              # noqa: E402  (경로를 넣은 뒤에야 보인다)

# 꺼야 할 때 여기만 False 로. serve.py 는 이 값을 보고 원본을 그대로 내보낸다.
ENABLED = True

CACHE_DIR = "download"              # 표시를 얹은 사본이 쌓이는 곳 (작품 폴더 안)

# 브랜드 색 — web/style.css 의 --sea-* 와 같은 값이다. 한쪽을 바꾸면 같이.
SEA_DEEP = (63, 111, 102)
SEA_MINT = (161, 198, 187)
SAND = (245, 231, 211)
PAPER = (255, 253, 247)

# 띠 크기는 그림 폭에 비례한다 — 800px 짜리와 2000px 짜리에 같은 픽셀을 쓰면
# 한쪽은 안 보이고 한쪽은 뒤덮는다.
BAND_RATIO = 0.085                  # 띠 높이 / 그림 폭
BAND_MIN, BAND_MAX = 64, 190
MARK_RATIO = 0.05                   # 코너 마크 글자 크기 / 그림 폭
MARK_MIN, MARK_MAX = 22, 64
MARK_ALPHA = 150                    # 0~255. 그림을 읽는 데 방해가 안 될 만큼만

WORDMARK = "LORE"
TAGLINE = "루와 함께 만든 웹툰"

# 띠 왼쪽에 앉는 루. 없으면 글자만 나간다 — 그림 하나 때문에 내려받기가 막히면 안 된다.
LOU_MARK = HERE / "web" / "lou" / "react" / "idle" / "01.webp"


class WatermarkError(RuntimeError):
    """표시를 못 붙였다. serve.py 가 원본을 그대로 내보내는 근거가 된다."""


def _pil():
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:      # pragma: no cover
        raise WatermarkError("Pillow 가 없습니다.  pip install Pillow") from exc
    return Image, ImageDraw


def _fit(value: float, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(value))))


def _paste_lou(canvas, x: int, top: int, band_h: int) -> int:
    """띠 왼쪽에 루를 앉힌다. 글자가 시작할 x 오프셋을 돌려준다 (없으면 0)."""
    Image, _ = _pil()
    if not LOU_MARK.exists():
        return 0
    try:
        lou = Image.open(LOU_MARK).convert("RGBA")
        lou.load()
    except OSError:
        return 0
    size = max(16, int(band_h * 0.86))
    lou = lou.resize((size, size), Image.LANCZOS)
    canvas.paste(lou, (x, top + (band_h - size) // 2), lou)
    return size + max(6, size // 8)


def _draw_band(img, caption: str):
    """그림 아래에 덧대는 브랜드 띠. 새 이미지를 돌려준다 (원본은 안 건드림)."""
    Image, ImageDraw = _pil()
    w, h = img.size
    band = _fit(w * BAND_RATIO, BAND_MIN, BAND_MAX)

    out = Image.new("RGB", (w, h + band), PAPER)
    out.paste(img.convert("RGB"), (0, 0))
    d = ImageDraw.Draw(out)

    # 그림과 띠 사이 가는 선 — 띠가 작품의 일부로 안 읽히게 경계를 준다
    d.rectangle([0, h, w, h + 2], fill=SEA_MINT)

    pad = max(12, band // 5)
    logo = _strip._font(_fit(band * 0.42, 14, 64), bold=True)
    small = _strip._font(_fit(band * 0.24, 10, 34))

    # 왼쪽 — 루 + LORE + 한 줄
    ty = h + 2 + (band - 2) // 2
    left = pad + _paste_lou(out, pad, h + 2, band - 2)
    lb = d.textbbox((0, 0), WORDMARK, font=logo)
    lh = lb[3] - lb[1]
    d.text((left, ty - lh // 2 - lb[1] - _fit(band * 0.10, 2, 12)),
           WORDMARK, font=logo, fill=SEA_DEEP)
    d.text((left, ty + _fit(band * 0.06, 2, 10)), TAGLINE, font=small, fill=SEA_DEEP)

    # 오른쪽 — 작품·회차. 길면 왼쪽 글자와 겹치므로 폭을 보고 줄인다.
    if caption:
        cb = d.textbbox((0, 0), caption, font=small)
        cw, ch = cb[2] - cb[0], cb[3] - cb[1]
        if cw < w - pad - cb[0] - left - (lb[2] - lb[0]) - pad:
            d.text((w - pad - cw, ty - ch // 2 - cb[1]), caption, font=small,
                   fill=(120, 120, 120))
    return out


def cut_layout(paths: list[Path], gaps: list[int], ratios: list[float],
                gap_table: dict[int, float] | None = None
                ) -> list[tuple[int, int, int, int]] | None:
    """최종본 안에서 각 컷이 차지하는 자리 — (x, y, 폭, 높이) 목록.

    webtoon-harness/episode.py 의 stitch() 와 **같은 규칙**(가장 좁은 꽉채움
    컷이 지면 폭을 정하고, 그보다 넓은 컷은 줄이되 늘리지 않는다, 가운데 정렬)
    으로 다시 계산한다. 실제 이어붙이기는 그대로 하네스가 하고, 여기서는
    컷마다 표시를 찍을 자리만 구한다 — 소스 그림의 크기만 읽으면 되므로
    stitch() 처럼 무겁게 로드하지 않는다.

    소스 그림을 못 읽으면 None — 호출부가 예전처럼 한 장짜리 마크로 돌아간다.
    """
    Image, _ = _pil()
    if not paths or len(paths) != len(gaps) or len(paths) != len(ratios):
        return None
    sizes = []
    try:
        for p in paths:
            with Image.open(p) as im:
                sizes.append(im.size)
    except OSError:
        return None
    full = [w for (w, _h), r in zip(sizes, ratios) if r >= 0.999]
    if not full:
        full = [sizes[0][0]] if sizes else []
    if not full:
        return None
    width = min(full)
    table = gap_table or _strip.gap_ratio_table()

    bounds = []
    y = 0
    for (iw, ih), gap, ratio in zip(sizes, gaps, ratios):
        target = width if ratio >= 0.999 else max(1, round(width * ratio))
        w = min(iw, target)                                # 늘리지 않는다
        h = ih if w == iw else max(1, round(ih * w / iw))
        x = (width - w) // 2
        bounds.append((x, y, w, h))
        y += h + _strip.gap_px(width, gap, table)
    return bounds


def _mark_layer(canvas_size: tuple[int, int],
                 boxes: list[tuple[int, int, int, int]]):
    """`boxes` 마다 그 자리 오른쪽 아래에 반투명 워드마크를 찍은 레이어."""
    Image, ImageDraw = _pil()
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for x0, y0, bw, bh in boxes:
        size = _fit(bw * MARK_RATIO, MARK_MIN, MARK_MAX)
        font = _strip._font(size, bold=True)
        box = d.textbbox((0, 0), WORDMARK, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        pad = max(10, size // 2)
        x, y = x0 + bw - pad - tw - box[0], y0 + bh - pad - th - box[1]

        # 밝은 그림에서도 어두운 그림에서도 읽히게 옅은 그림자를 깐다
        off = max(1, size // 20)
        d.text((x + off, y + off), WORDMARK, font=font, fill=(0, 0, 0, MARK_ALPHA // 3))
        d.text((x, y), WORDMARK, font=font, fill=(*PAPER, MARK_ALPHA))
    return layer


def _draw_mark(img):
    """그림 오른쪽 아래 반투명 워드마크 하나. 컷 경계를 모를 때 쓰는 예전 동작."""
    Image, _ = _pil()
    w, h = img.size
    layer = _mark_layer((w, h), [(0, 0, w, h)])
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def _draw_percut_marks(img, bounds: list[tuple[int, int, int, int]]):
    """컷마다 **자기 자리**의 오른쪽 아래에 표시를 찍는다.

    한 장 전체에 하나만 찍으면, 그 컷 하나만 잘라(스크린샷·크롭) 퍼뜨렸을 때
    표시가 안 딸려 간다. `bounds` 는 cut_layout() 의 결과.
    """
    Image, _ = _pil()
    w, h = img.size
    safe = [(x, y, bw, bh) for x, y, bw, bh in bounds
            if bw > 0 and bh > 0 and 0 <= x and 0 <= y and x + bw <= w and y + bh <= h]
    if not safe:
        return _draw_mark(img)
    layer = _mark_layer((w, h), safe)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def stamp(src: Path, out: Path, caption: str = "",
          cut_bounds: list[tuple[int, int, int, int]] | None = None) -> Path:
    """`src` 에 표시를 얹어 `out` 으로 쓴다. 원본은 안 건드린다.

    `cut_bounds` 를 주면 컷마다(cut_layout() 참고) 찍고, 없으면 예전처럼
    그림 전체에 하나만 찍는다.
    """
    Image, _ = _pil()
    try:
        img = Image.open(src)
        img.load()
    except OSError as exc:
        raise WatermarkError(f"그림을 읽지 못했습니다: {exc}") from exc

    marked_img = _draw_percut_marks(img, cut_bounds) if cut_bounds else _draw_mark(img)
    marked = _draw_band(marked_img, caption)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")     # 반쯤 쓰다 만 파일을 안 남긴다
    try:
        # 형식을 못 박으면 PIL 이 ".part" 를 보고 무슨 그림인지 몰라 죽는다
        marked.save(tmp, format="PNG")
        tmp.replace(out)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise WatermarkError(f"표시한 그림을 저장하지 못했습니다: {exc}") from exc
    return out


def for_download(src: Path, cache_root: Path, caption: str = "",
                  cut_bounds: list[tuple[int, int, int, int]] | None = None) -> Path:
    """내려받기용 경로. 캐시가 원본보다 새것이면 그대로 쓴다.

    표시를 못 붙이면 **원본 경로를 그대로 돌려준다** — 워터마크 때문에
    내려받기 자체가 막히는 것이 제일 나쁘다. 표시는 있으면 좋은 것이지
    없으면 파일을 못 주는 것이 아니다.

    `cut_bounds` 가 있으면 컷마다 찍은 판을 캐시한다 — 파일 이름을 다르게
    둬서(`_wmc`), 컷 경계를 몰라 한 장짜리로 찍었던 예전 캐시와 안 섞인다.
    """
    src = Path(src)
    if not ENABLED or not src.exists():
        return src
    suffix = "_wmc" if cut_bounds else "_wm"
    out = Path(cache_root) / CACHE_DIR / f"{src.stem}{suffix}.png"
    try:
        if out.exists() and out.stat().st_mtime >= src.stat().st_mtime:
            return out
        return stamp(src, out, caption, cut_bounds=cut_bounds)
    except (WatermarkError, OSError, ValueError):
        return src
