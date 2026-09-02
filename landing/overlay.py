"""편집실에서 그림 위에 얹은 것을 **진짜 그림에 굽는다.**

## 왜 생겼나

편집실은 말풍선·스티커·효과음을 얹을 수 있었지만, 얹은 것이 브라우저에만
남았다. `editor.js` 머리말이 그렇게 적고 있었다 — *"서버로 보내지 않고 그림에도
굽지 않습니다 — 다른 기기에서 열면 없습니다."* 그래서 공들여 배치해 놓고도
가져갈 수 있는 것은 말풍선 없는 원본뿐이었다.

여기서 두 가지를 한다:

  1. 얹은 것을 **작품 폴더에 저장한다** (`overlay.json`). 브라우저를 비워도,
     다른 기기에서 열어도 그대로 있다.
  2. 그것을 **그림에 구워 낸다** — 장마다 `baked/scene{n}.png`, 그리고 전부
     이어 붙인 `episode_baked.png`.

원본은 건드리지 않는다. 굽기는 언제든 다시 할 수 있어야 하고, 말풍선을 옮긴
뒤 다시 구우려면 밑그림이 깨끗해야 한다.

## 좌표

편집실은 화면에 보이는 상자를 기준으로 **퍼센트**로 자리를 잡는다(x·y·w).
퍼센트는 해상도와 무관하므로 그대로 쓰면 된다. 문제는 글자 크기다 — `size` 는
CSS 픽셀이라 "화면에서 몇 px" 이지 "그림에서 몇 px" 이 아니다.

그래서 편집실이 보낼 때 `ref_w`(그때 화면에서 그 상자가 몇 px 였는지)를 같이
보낸다. 굽는 쪽은 `그림폭 / ref_w` 로 배율을 잡는다. 그러면 화면에서 본 것과
같은 비율로 구워진다 — 창 크기를 바꿔 가며 편집했더라도, 마지막에 보낸 값이
기준이 되므로 "지금 보이는 그대로"가 나온다.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
WEBTOON = HERE.parent / "webtoon-harness"
if str(WEBTOON) not in sys.path:
    sys.path.insert(0, str(WEBTOON))

import episode as _episode          # noqa: E402  (경로를 넣은 뒤에야 보인다)
import strip as _strip              # noqa: E402

OVERLAY_FILE = "overlay.json"
BAKED_DIR = "baked"
BAKED_EPISODE = "episode_baked.png"

# 편집실이 아는 것과 같은 목록. 한쪽이 늘면 여기도 늘어야 한다.
BUBBLE_VARIANTS = ("normal", "shout", "whisper", "thought", "narration", "flash")
TAILED = {"normal", "shout", "whisper", "thought"}
ITEM_TYPES = ("bubble", "sticker", "sfx")

INK = (17, 17, 17, 255)
PAPER = (255, 255, 255, 255)

# 이모지는 **비트맵 폰트**라 아무 크기나 안 된다 (애플 이모지는 20·26·32·40·
# 48·52·64·96·160 뿐이다). 되는 크기로 그린 뒤 줄이는 이유가 그것이다.
EMOJI_FONTS = (
    "/System/Library/Fonts/Apple Color Emoji.ttc",
    r"C:\Windows\Fonts\seguiemj.ttf",
    "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
    "/usr/share/fonts/truetype/ancient-scripts/Symbola_hint.ttf",
)


class OverlayError(RuntimeError):
    """굽기 실패. serve.py 가 사람이 읽을 메시지로 바꿔 내보낸다."""


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:      # pragma: no cover - 환경 문제
        raise OverlayError("Pillow 가 없어 그림에 구울 수 없습니다. "
                           "pip install Pillow") from exc
    return Image, ImageDraw, ImageFont


# --------------------------------------------------------------------------- #
# 저장 — 얹은 것은 작품 폴더에 남는다
# --------------------------------------------------------------------------- #

def _clamp(v: Any, lo: float, hi: float, fallback: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(f) or math.isinf(f):
        return fallback
    return max(lo, min(hi, f))


def clean_item(raw: Any) -> dict[str, Any] | None:
    """편집실이 보낸 항목 하나를 믿을 수 있는 값으로 깎는다.

    모르는 값은 조용히 기본값으로 떨어뜨린다 — 여기서 세우면 항목 하나가
    이상할 때 화 전체를 못 굽는다. 브라우저에서 온 값이라 무엇이든 올 수 있다.
    """
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "").strip().lower()
    if kind not in ITEM_TYPES:
        return None
    text = str(raw.get("text") or "")
    if not text.strip():
        return None
    variant = str(raw.get("variant") or "").strip().lower()
    if kind == "bubble" and variant not in BUBBLE_VARIANTS:
        variant = "normal"
    tail = str(raw.get("tail") or "").strip().lower()
    return {
        "type": kind,
        "variant": variant,
        "text": text[:400],           # 말풍선 하나가 화 전체를 덮는 것을 막는다
        "x": _clamp(raw.get("x"), -20, 110, 20.0),
        "y": _clamp(raw.get("y"), -20, 110, 30.0),
        "w": _clamp(raw.get("w"), 3, 100, 40.0),
        "size": _clamp(raw.get("size"), 4, 200, 15.0),
        "rot": _clamp(raw.get("rot"), -180, 180, 0.0),
        "tail": tail if tail in ("left", "right", "none") else "left",
    }


def clean_payload(raw: Any) -> dict[str, Any]:
    """편집실이 보낸 것 전체 → 저장할 모양.

    {"scenes": {"1": {...}}, "gaps": {"1": 2}}

    `gaps` 는 **사람이 편집실에서 고친 여백**이다 (장 뒤의 쉼, 0~3). 콘티가
    정한 gap_after 를 덮어쓴다 — 없는 장은 콘티 값 그대로다. 옛 파일에는 이
    칸이 없고, 없으면 아무것도 안 덮어쓰므로 예전과 같이 읽힌다.
    """
    scenes: dict[str, Any] = {}
    for key, val in ((raw or {}).get("scenes") or {}).items():
        try:
            no = int(key)
        except (TypeError, ValueError):
            continue
        if no < 1 or not isinstance(val, dict):
            continue
        items = [c for c in (clean_item(i) for i in (val.get("items") or [])) if c]
        ref_w = _clamp(val.get("ref_w"), 80, 8000, 720.0)
        # 빈 장도 남긴다 — "여기 있던 말풍선을 지웠다"와 "한 번도 안 열었다"가
        # 구분돼야 다시 구울 때 옛 말풍선이 되살아나지 않는다.
        scenes[str(no)] = {"ref_w": ref_w, "items": items}

    gaps: dict[str, int] = {}
    for key, val in ((raw or {}).get("gaps") or {}).items():
        try:
            no, g = int(key), int(val)
        except (TypeError, ValueError):
            continue
        if no >= 1 and 0 <= g <= 3:
            gaps[str(no)] = g
    return {"scenes": scenes, "gaps": gaps}


def gap_overrides(data: dict[str, Any]) -> dict[int, int]:
    """저장된 여백 고침. {장 번호: 0~3}"""
    out: dict[int, int] = {}
    for key, val in (data.get("gaps") or {}).items():
        try:
            out[int(key)] = int(val)
        except (TypeError, ValueError):
            continue
    return out


def overlay_path(ep_dir: Path) -> Path:
    return ep_dir / OVERLAY_FILE


def load_overlay(ep_dir: Path) -> dict[str, Any]:
    p = overlay_path(ep_dir)
    if not p.exists():
        return {"scenes": {}, "gaps": {}}
    try:
        return clean_payload(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        # 파일이 깨졌으면 빈 것으로 본다. 여기서 세우면 편집실이 안 열린다.
        return {"scenes": {}, "gaps": {}}


def save_overlay(ep_dir: Path, raw: Any) -> dict[str, Any]:
    data = clean_payload(raw)
    ep_dir.mkdir(parents=True, exist_ok=True)
    overlay_path(ep_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data


def count_items(data: dict[str, Any]) -> int:
    return sum(len(v.get("items") or []) for v in (data.get("scenes") or {}).values())


# --------------------------------------------------------------------------- #
# 글꼴
# --------------------------------------------------------------------------- #

_EMOJI_CACHE: dict[int, Any] = {}
_EMOJI_PATH: str | None = None
_EMOJI_SIZES: list[int] | None = None


def _emoji_font(size: int):
    """이모지 글꼴. 없으면 None — 스티커만 빠지고 나머지는 그대로 구워진다."""
    global _EMOJI_PATH, _EMOJI_SIZES
    _, _, ImageFont = _pil()
    if _EMOJI_SIZES is None:
        _EMOJI_SIZES = []
        for cand in EMOJI_FONTS:
            if not Path(cand).exists():
                continue
            got = []
            for s in (20, 26, 32, 40, 48, 52, 64, 96, 109, 128, 160):
                try:
                    ImageFont.truetype(cand, s)
                    got.append(s)
                except OSError:
                    pass
            if got:
                _EMOJI_PATH, _EMOJI_SIZES = cand, got
                break
    if not _EMOJI_SIZES or not _EMOJI_PATH:
        return None, 0
    # 목표보다 크거나 같은 것 중 가장 작은 것. 없으면 가장 큰 것.
    pick = next((s for s in _EMOJI_SIZES if s >= size), _EMOJI_SIZES[-1])
    if pick not in _EMOJI_CACHE:
        try:
            _EMOJI_CACHE[pick] = ImageFont.truetype(_EMOJI_PATH, pick)
        except OSError:
            return None, 0
    return _EMOJI_CACHE[pick], pick


# --------------------------------------------------------------------------- #
# 그리기 — 편집실의 CSS 를 픽셀로 옮긴다
# --------------------------------------------------------------------------- #

def _lines_and_box(draw, text: str, font, inner_w: int) -> tuple[list[str], int, int]:
    """줄바꿈한 결과와 글자 덩어리의 (폭, 높이). 한국어는 어절에서 끊는다."""
    lines = _strip.wrap(draw, text, font, max(8, inner_w))
    lh = max(1, int(font.size * 1.35))          # CSS 의 line-height: normal 근사
    w = max((int(draw.textlength(x, font=font)) for x in lines), default=0)
    return lines, w, lh * len(lines)


def _dashed_ellipse(draw, box, ink, width, on=14, off=10):
    """점선 타원. Pillow 에 점선이 없어서 짧은 호를 번갈아 그린다."""
    x0, y0, x1, y1 = box
    per = max(40, int((abs(x1 - x0) + abs(y1 - y0)) * 1.6))
    step = 360 * (on + off) / max(1, per)
    a = 0.0
    while a < 360:
        draw.arc(box, a, min(360.0, a + 360 * on / max(1, per)), fill=ink, width=width)
        a += step


def _bubble_tile(item: dict[str, Any], box_w: int, scale: float):
    """말풍선 하나를 투명 타일에 그린다. (타일, 높이) 를 돌려준다.

    편집실 CSS 를 그대로 옮긴다: padding .55em/.85em, 글자는 가운데(나레이션만
    왼쪽), 테두리 2.5px. em 은 글자 크기이므로 배율이 저절로 따라간다.
    """
    Image, ImageDraw, _ = _pil()
    variant = item["variant"]
    fs = max(7, int(item["size"] * scale))
    bold = variant in ("shout",)
    font = _strip._font(fs, bold=bold)
    pad_x, pad_y = int(fs * 0.85), int(fs * 0.55)
    stroke = max(2, int(2.5 * scale))

    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    inner_w = max(10, box_w - pad_x * 2)
    lines, _tw, th = _lines_and_box(probe, item["text"], font, inner_w)
    box_h = th + pad_y * 2
    # 외침은 삐죽삐죽한 만큼 안쪽이 좁아진다 — CSS 도 padding 을 두 배로 준다.
    if variant == "shout":
        box_h += int(fs * 1.1)
        box_w_draw = box_w
    else:
        box_w_draw = box_w

    tail_h = int(fs * 0.95) if (variant in TAILED and item["tail"] != "none") else 0
    tile = Image.new("RGBA", (box_w_draw, box_h + tail_h + stroke * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    b = (stroke, stroke, box_w_draw - stroke, box_h - stroke)

    if variant == "narration":
        d.rounded_rectangle(b, radius=max(2, int(3 * scale)), fill=PAPER,
                            outline=INK, width=max(2, int(2 * scale)))
    elif variant == "shout":
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        rw, rh = (b[2] - b[0]) / 2, (b[3] - b[1]) / 2
        pts, spikes = [], 12
        for i in range(spikes * 2):
            ang = math.pi * i / spikes - math.pi / 2
            f = 1.0 if i % 2 == 0 else 0.80
            pts.append((cx + math.cos(ang) * rw * f, cy + math.sin(ang) * rh * f))
        d.polygon(pts, fill=PAPER, outline=INK)
    elif variant == "whisper":
        d.ellipse(b, fill=PAPER)
        _dashed_ellipse(d, b, INK, max(2, int(2 * scale)), on=5, off=7)
    elif variant == "flash":
        d.ellipse(b, fill=(255, 255, 255, 210))
        _dashed_ellipse(d, b, (17, 17, 17, 210), max(2, int(2 * scale)), on=16, off=11)
    elif variant == "thought":
        d.ellipse(b, fill=PAPER, outline=INK, width=stroke)
    else:                                        # normal
        d.ellipse(b, fill=PAPER, outline=INK, width=stroke)

    # 꼬리 — 누가 말했는가를 가리키는 유일한 표시. 왼쪽 22% 또는 오른쪽 22%.
    if tail_h:
        at = box_w_draw * (0.22 if item["tail"] == "left" else 0.78)
        if variant == "thought":
            # 속마음은 삼각형이 아니라 점점 작아지는 동그라미 둘이다.
            r1 = max(4, int(fs * 0.30))
            r2 = max(3, int(fs * 0.19))
            cy1 = box_h + r1 * 0.4
            d.ellipse((at - r1, cy1 - r1, at + r1, cy1 + r1),
                      fill=PAPER, outline=INK, width=max(1, stroke - 1))
            cy2 = cy1 + r1 + r2 * 1.2
            d.ellipse((at - r2, cy2 - r2, at + r2, cy2 + r2),
                      fill=PAPER, outline=INK, width=max(1, stroke - 1))
        else:
            half = max(3, int(fs * 0.36))
            d.polygon([(at - half, box_h - stroke * 2), (at + half, box_h - stroke * 2),
                       (at - half * 0.2, box_h + tail_h)], fill=PAPER, outline=INK)

    # 글자 — 나레이션만 왼쪽 정렬이다 (CSS 의 text-align: left).
    lh = max(1, int(font.size * 1.35))
    top = (box_h - lh * len(lines)) / 2
    if variant == "shout":
        top = (box_h - lh * len(lines)) / 2
    for i, line in enumerate(lines):
        lw = d.textlength(line, font=font)
        x = pad_x if variant == "narration" else (box_w_draw - lw) / 2
        d.text((x, top + i * lh), line, font=font, fill=INK)
    return tile


def _sticker_tile(item: dict[str, Any], scale: float):
    """이모지 스티커. 글꼴이 없으면 None — 나머지는 그대로 구워진다."""
    Image, ImageDraw, _ = _pil()
    target = max(8, int(item["size"] * 2.2 * scale))
    font, drawn = _emoji_font(target)
    if font is None:
        return None
    pad = max(4, drawn // 6)
    tile = Image.new("RGBA", (drawn * 2 + pad * 2, drawn * 2 + pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    try:
        d.text((pad, pad), item["text"], font=font, embedded_color=True)
    except (OSError, ValueError):
        return None
    box = tile.getbbox()
    if not box:
        return None
    tile = tile.crop(box)
    # 되는 크기로 그린 뒤 목표 크기로 줄인다 (비트맵 이모지라 크기가 띄엄띄엄하다).
    if tile.height and tile.height != target:
        w = max(1, round(tile.width * target / tile.height))
        tile = tile.resize((w, max(1, target)), Image.LANCZOS)
    return tile


def _sfx_tile(item: dict[str, Any], scale: float):
    """효과음 — 흰 글자에 검은 테두리. 레터링이라 굵게 그린다."""
    Image, ImageDraw, _ = _pil()
    fs = max(8, int(item["size"] * 2 * scale))
    font = _strip._font(fs, bold=True)
    sw = max(2, int(3 * scale))
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    tw = int(probe.textlength(item["text"], font=font))
    tile = Image.new("RGBA", (tw + sw * 4, int(fs * 1.5) + sw * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    d.text((sw * 2, sw * 2), item["text"], font=font, fill=PAPER,
           stroke_width=sw, stroke_fill=INK)
    return tile.crop(tile.getbbox() or (0, 0, 1, 1))


def render_scene(base, spec: dict[str, Any]):
    """밑그림 한 장 + 얹은 것 → 구운 그림 한 장 (RGB).

    base 는 건드리지 않는다 — 복사본에 얹는다.
    """
    Image, _, _ = _pil()
    img = base.convert("RGBA")
    items = spec.get("items") or []
    if not items:
        return img.convert("RGB"), []
    ref_w = float(spec.get("ref_w") or 720.0)
    scale = img.width / max(1.0, ref_w)
    skipped: list[str] = []

    for it in items:
        box_w = max(8, int(img.width * it["w"] / 100.0))
        try:
            if it["type"] == "bubble":
                tile = _bubble_tile(it, box_w, scale)
            elif it["type"] == "sticker":
                tile = _sticker_tile(it, scale)
            else:
                tile = _sfx_tile(it, scale)
        except (OSError, ValueError) as exc:
            skipped.append(f"{it['type']}({it['text'][:8]}): {exc}")
            continue
        if tile is None:
            skipped.append(f"{it['type']}({it['text'][:8]})")
            continue
        # 자리 — 편집실은 왼쪽 위를 x%·y% 에 두고 가운데를 기준으로 돌린다.
        left = img.width * it["x"] / 100.0
        top = img.height * it["y"] / 100.0
        cx, cy = left + tile.width / 2, top + tile.height / 2
        if abs(it["rot"]) > 0.01:
            tile = tile.rotate(-it["rot"], expand=True, resample=Image.BICUBIC)
        img.alpha_composite(tile, (int(cx - tile.width / 2), int(cy - tile.height / 2)))
    return img.convert("RGB"), skipped


# --------------------------------------------------------------------------- #
# 굽기 — 장마다 한 장, 그리고 한 편
# --------------------------------------------------------------------------- #

def baked_dir(ep_dir: Path) -> Path:
    return ep_dir / BAKED_DIR


def baked_scene_path(ep_dir: Path, no: int) -> Path:
    return baked_dir(ep_dir) / f"scene{int(no)}.png"


def baked_episode_path(ep_dir: Path) -> Path:
    return ep_dir / BAKED_EPISODE


def scene_spec(data: dict[str, Any], no: int) -> dict[str, Any]:
    """그 장에 얹은 것. 없으면 빈 dict."""
    return (data.get("scenes") or {}).get(str(int(no))) or {}


def has_items(data: dict[str, Any], no: int) -> bool:
    """그 장에 얹은 것이 하나라도 있는가."""
    return bool(scene_spec(data, no).get("items"))


def bake_one(ep_dir: Path, no: int, src: Path,
             data: dict[str, Any] | None = None) -> Path:
    """장 **하나만** 굽는다. 화면이 최종본을 보여줄 때 그때그때 쓴다.

    bake() 는 한 편을 통째로 굽고 이어 붙인다 — 말풍선 하나 옮길 때마다 그걸
    다 할 수는 없다. 그래서 필요한 장 하나만 굽는 길을 따로 둔다. 결과는 같은
    자리(baked/scene{n}.png)에 떨어지므로 나중에 bake() 가 덮어써도 어긋나지
    않는다.
    """
    Image, _, _ = _pil()
    data = data if data is not None else load_overlay(ep_dir)
    base = Image.open(src)
    base.load()
    img, _gone = render_scene(base, scene_spec(data, no))
    out = baked_scene_path(ep_dir, no)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    return out


def bake(ep_dir: Path, numbers: list[int], base_of, data: dict[str, Any] | None = None,
         layout: dict[int, tuple[int, str]] | None = None,
         gap_table: dict[int, float] | None = None) -> dict[str, Any]:
    """얹은 것을 그림에 굽는다.

    numbers : 이 화의 장 번호들 (순서대로)
    base_of : 장 번호 -> 밑그림 경로. 없으면 None 을 돌려준다.
    layout  : {장 번호: (gap_after, weight)}. 없으면(None) 전부 여백 없이 꽉
              채워 잇는다(예전 동작 그대로). 있으면 원래 생성 때와 같은
              여백·폭으로 다시 잇는다 — 편집실에서 다시 구웠다고 세로 스크롤의
              리듬(#110)이 사라지면 안 된다.
    gap_table : 여백 눈금(gap_after -> 폭의 몇 배). 없으면 하네스 기본값.
              **원래 생성 때 쓴 config 의 눈금을 넘겨야 한다** — 기본값으로
              다시 이으면 같은 gap_after=1 이 0.07 배(기본)와 0.16 배(제품)로
              갈려서, 구운 한 편이 원본 episode.png 와 높이가 달라진다.

    **얹은 것이 없는 장도 굽는다.** 안 그러면 한 편으로 이을 때 어떤 장은
    구운 것, 어떤 장은 원본이 되어 두 폴더를 섞어 읽어야 한다.
    """
    Image, _, _ = _pil()
    data = data if data is not None else load_overlay(ep_dir)
    scenes = data.get("scenes") or {}
    out_dir = baked_dir(ep_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    made: list[int] = []
    missing: list[int] = []
    skipped: list[str] = []
    for no in numbers:
        src = base_of(no)
        if not src or not Path(src).exists():
            missing.append(no)
            continue
        try:
            base = Image.open(src)
            base.load()
        except OSError as exc:
            raise OverlayError(f"{no}번째 장의 그림을 읽지 못했습니다: {exc}") from exc
        img, gone = render_scene(base, scenes.get(str(no)) or {})
        img.save(baked_scene_path(ep_dir, no))
        made.append(no)
        skipped.extend(f"{no}장 {g}" for g in gone)

    if not made:
        raise OverlayError("구울 그림이 하나도 없습니다. 먼저 웹툰을 만들어 주세요.")

    out = baked_episode_path(ep_dir)
    layout = layout or {}
    # 모르는 장은 **여백 0** 이다. 1 로 두면 layout 을 안 넘긴 옛 호출부까지
    # 갑자기 여백이 생겨서, 예전에 구운 화를 다시 구우면 높이가 달라진다
    # (config 의 scene.stitch_gaps 가 기본 꺼짐인 것과 같은 이유다).
    gaps = [layout.get(n, (0, "normal"))[0] for n in made]
    weights = [layout.get(n, (1, "normal"))[1] for n in made]
    ratios = [_strip.width_ratio({"weight": w}) for w in weights]
    try:
        w, h = _episode.stitch([baked_scene_path(ep_dir, n) for n in made], out,
                               gaps, ratios,
                               gap_table or _strip.gap_ratio_table())
    except _episode.StitchError as exc:
        raise OverlayError(f"한 편으로 잇지 못했습니다: {exc}") from exc

    return {"scenes": made, "missing": missing, "skipped": skipped,
            "width": w, "height": h, "episode": str(out)}
