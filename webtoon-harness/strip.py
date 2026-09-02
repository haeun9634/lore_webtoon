"""컷 한 장 = 이미지 한 장. 말풍선·글자·여백은 **코드가** 얹고 이어 붙인다.

## 왜 이렇게 바꿨나

전에는 컷 여러 개를 한 이미지에 묶어 구웠다(Scene 모드). 이음매를 없애려던
것인데, 그 구조가 네 가지 문제를 한꺼번에 만들었다:

  · **만화 페이지가 나온다.** 모델에게 "한 캔버스에 컷 3개를 배치하라"고 하면
    격자 말고 다른 답이 없다. "no borders" 를 열 번 말해도 안 된다.
  · **여백이 없다.** 컷 사이 호흡을 이미지 모델이 정하게 된다. 그런데 여백은
    그림이 아니라 **레이아웃**이다.
  · **말풍선 자리를 모른다.** 모델이 그림 안에 말풍선을 그리고, 코드는 그것이
    어디 그려졌는지 모른 채 글자를 얹는다. 어긋날 수밖에 없다.
  · **비용이 한 컷에 쏠린다.** 캔버스를 컷들이 나눠 갖는 비율도 모델이 정한다.

컷 하나가 캔버스 하나를 통째로 쓰면 넷이 동시에 사라진다. 이음매는 애초에
문제가 아니었다 — **컷 사이에 여백을 두는 것이 웹툰의 원래 모습**이라,
붙일 이음매 자체가 없다.

## 코드가 그리는 것

  말풍선 · 나레이션 상자 · 속마음 구름   모양과 글자 전부. 자리를 코드가
                                        정하므로 어긋날 일이 없다.
  단톡방/휴대폰 화면 컷                  이미지 모델은 한글 UI 를 못 그린다.
                                        코드가 그리면 정확하고 0원이다.
  컷 사이 여백                           gap_after(콘티가 계산해 둔 값)로.

효과음은 **그림 안에** 남긴다. 레터링은 그림의 일부라 코드로 얹으면 붙여 놓은
스티커가 된다 — 여기서만은 이미지 모델이 낫다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import scenegen

EPISODE_FILE = "episode.png"
MAX_HEIGHT = 60000        # PNG 한계(65,535)보다 앞에서 실용 한계가 온다

# 한글이 반드시 나와야 하므로 폰트를 못 찾으면 세운다 — 조용히 네모(□)로
# 그리면 다 뽑고 나서야 알게 된다.
FONT_CANDIDATES = (
    r"C:\Windows\Fonts\malgun.ttf",
    r"C:\Windows\Fonts\malgunbd.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
)


class StripError(RuntimeError):
    """조립 실패. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


def _pil():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:      # pragma: no cover
        raise StripError("Pillow 가 없습니다.  pip install Pillow") from exc
    return Image, ImageDraw, ImageFont


_FONT_PATH: str | None = None


def font_path() -> str:
    global _FONT_PATH
    if _FONT_PATH:
        return _FONT_PATH
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            _FONT_PATH = p
            return p
    raise StripError(
        "한글 폰트를 찾지 못했습니다. 말풍선 글자를 그릴 수 없습니다.\n"
        "        찾아본 곳: " + " / ".join(FONT_CANDIDATES))


def _font(size: int, bold: bool = False):
    _, _, ImageFont = _pil()
    p = font_path()
    if bold:
        cand = p.replace("malgun.ttf", "malgunbd.ttf")
        if Path(cand).exists():
            p = cand
    return ImageFont.truetype(p, max(8, int(size)))


# --------------------------------------------------------------------------- #
# 글자 줄바꿈 — 한국어는 단어 사이가 아니라 **어절** 사이에서 끊는다
# --------------------------------------------------------------------------- #
def wrap(draw, text: str, font, max_w: int) -> list[str]:
    """폭에 맞춰 줄을 나눈다. 어절이 통째로 안 들어가면 글자 단위로 자른다."""
    out: list[str] = []
    for para in str(text or "").split("\n"):
        if not para.strip():
            out.append("")
            continue
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= max_w or not line:
                line = trial
                # 한 어절이 폭을 넘으면 글자 단위로 쪼갠다
                while draw.textlength(line, font=font) > max_w and len(line) > 1:
                    cut = len(line) - 1
                    while cut > 1 and draw.textlength(line[:cut], font=font) > max_w:
                        cut -= 1
                    out.append(line[:cut])
                    line = line[cut:]
            else:
                out.append(line)
                line = word
        out.append(line)
    return out


def fit_font(draw, text: str, max_w: int, max_h: int, start: int, bold=False):
    """상자에 들어가는 가장 큰 글자 크기. 최소 크기까지 줄여도 안 되면 그대로 준다."""
    size = int(start)
    while size > 10:
        f = _font(size, bold)
        lines = wrap(draw, text, f, max_w)
        h = len(lines) * int(size * 1.42)
        if h <= max_h:
            return f, lines
        size -= 1
    f = _font(11, bold)
    return f, wrap(draw, text, f, max_w)


# --------------------------------------------------------------------------- #
# 말풍선 — 모양과 글자를 코드가 그린다
#
# 이미지 모델이 빈 말풍선을 그리게 하고 그 위에 글자만 얹던 방식을 버렸다.
# 모델이 어디에 그렸는지 코드가 알 수 없어서 글자가 늘 어긋났기 때문이다.
# 코드가 모양까지 그리면 자리는 정의상 맞는다.
# --------------------------------------------------------------------------- #
BUBBLE_KINDS = ("dialogue", "shout", "whisper", "thought", "narration")


def bubble_kind(cut: dict[str, Any], field: str, text: str | None = None) -> str:
    """풍선 모양. text 를 주면 그것으로 판정한다 — 한 컷에 대사가 여러 줄이면
    cut[field] 하나만 보고는 어느 줄인지 알 수 없다."""
    if field == "narration":
        return "narration"
    if field == "thought":
        return "thought"
    line = str(cut.get(field) or "") if text is None else str(text)
    if "!" in line:
        return "shout"
    if line.strip().startswith("(") or "…" in line:
        return "whisper"
    return "dialogue"


def _rounded(draw, box, radius, fill, outline, width=3):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def draw_bubble(img, box: tuple[int, int, int, int], kind: str, text: str,
                tail_to: tuple[int, int] | None = None) -> None:
    """말풍선 하나를 그리고 그 안에 글자를 넣는다. box 는 (x0,y0,x1,y1) 픽셀."""
    Image, ImageDraw, _ = _pil()
    draw = ImageDraw.Draw(img, "RGBA")
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    pad = max(10, int(min(w, h) * 0.11))
    ink = (20, 22, 26, 255)

    if kind == "narration":
        # 나레이션은 상자다. 살짝 각지고 반투명한 흰 판.
        draw.rectangle(box, fill=(255, 255, 255, 232), outline=(20, 22, 26, 90), width=2)
    elif kind == "thought":
        # 속마음은 구름. 큰 타원 + 가장자리 원들.
        draw.ellipse(box, fill=(255, 255, 255, 240), outline=ink, width=3)
        r = max(6, int(min(w, h) * 0.10))
        for i, (cx, cy) in enumerate((
                (x0 + w * 0.18, y0 + h * 0.06), (x0 + w * 0.52, y0 - h * 0.01),
                (x0 + w * 0.84, y0 + h * 0.08), (x0 - w * 0.01, y0 + h * 0.45),
                (x1 + w * 0.01 - 2 * r, y0 + h * 0.5),
                (x0 + w * 0.3, y1 - h * 0.05), (x0 + w * 0.7, y1 - h * 0.04))):
            rr = r if i % 2 else int(r * 0.72)
            draw.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                         fill=(255, 255, 255, 240), outline=ink, width=2)
    elif kind == "shout":
        # 외침은 삐죽삐죽한 폭발형.
        import math
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        pts, spikes = [], 16
        for i in range(spikes * 2):
            ang = math.pi * i / spikes
            f = 1.0 if i % 2 == 0 else 0.80
            pts.append((cx + math.cos(ang) * w / 2 * f,
                        cy + math.sin(ang) * h / 2 * f))
        draw.polygon(pts, fill=(255, 255, 255, 242), outline=ink)
    elif kind == "whisper":
        _rounded(draw, box, radius=int(min(w, h) * 0.45),
                 fill=(255, 255, 255, 225), outline=(20, 22, 26, 130), width=2)
    else:
        draw.ellipse(box, fill=(255, 255, 255, 242), outline=ink, width=3)

    # 꼬리 — 말하는 사람 쪽으로 **짧게**. 풍선 가장자리에서 조금만 뻗는다.
    # 길게 뻗으면 화면을 가로지르는 선이 되어 그림을 망친다.
    if tail_to and kind in ("dialogue", "shout", "whisper"):
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        tx, ty = tail_to
        dx, dy = tx - cx, ty - cy
        n = max(1.0, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / n, dy / n
        # 풍선 가장자리까지 간 뒤 그 길이의 30% 만 더 나간다.
        edge = min(w, h) / 2
        tip = (cx + ux * (edge + min(n - edge, edge * 0.55)),
               cy + uy * (edge + min(n - edge, edge * 0.55)))
        px, py = -uy, ux
        base = max(6, int(min(w, h) * 0.13))
        draw.polygon([(cx + ux * edge * 0.55 + px * base,
                       cy + uy * edge * 0.55 + py * base),
                      (cx + ux * edge * 0.55 - px * base,
                       cy + uy * edge * 0.55 - py * base), tip],
                     fill=(255, 255, 255, 242), outline=ink)

    body = str(text or "").strip()
    if not body:
        return
    inner_w, inner_h = max(20, w - pad * 2), max(16, h - pad * 2)
    f, lines = fit_font(draw, body, inner_w, inner_h,
                        start=int(h * 0.34), bold=(kind == "shout"))
    lh = int(f.size * 1.42)
    ty0 = (y0 + y1) / 2 - len(lines) * lh / 2
    for i, line in enumerate(lines):
        lw = draw.textlength(line, font=f)
        draw.text(((x0 + x1) / 2 - lw / 2, ty0 + i * lh), line, font=f, fill=ink)


# 말풍선이 놓일 자리 — bubble_zone 이 가리키는 컷 안의 상대 좌표 (x, y, w, h)
ZONE_BOX = {
    "top":    (0.06, 0.05, 0.88, 0.22),
    "bottom": (0.06, 0.73, 0.88, 0.22),
    "left":   (0.04, 0.16, 0.44, 0.26),
    "right":  (0.52, 0.16, 0.44, 0.26),
    "center": (0.16, 0.38, 0.68, 0.24),
}
BUBBLE_FIELDS = ("narration", "dialogue", "thought")


def measure(draw, text: str, max_w: int, size: int) -> tuple[Any, list[str], int, int]:
    """이 폭에서 글자가 실제로 차지하는 크기. (폰트, 줄들, 폭, 높이)"""
    f = _font(size)
    lines = wrap(draw, text, f, max_w)
    tw = int(max([draw.textlength(l, font=f) for l in lines] or [0]))
    th = int(len(lines) * f.size * 1.42)
    return f, lines, tw, th


# 말하는 사람이 화면 어느 쪽에 있는가 → 꼬리가 향할 지점 (컷 폭·높이 대비)
SIDE_POINT = {"left": (0.22, 0.62), "right": (0.78, 0.62), "center": (0.5, 0.66)}


def tail_point(cut: dict[str, Any], kind: str, w: int, h: int, y: float,
               side_override: str = ""):
    """말풍선 꼬리가 가리킬 자리. 모르면 None — 꼬리를 아예 안 그린다.

    **짐작하지 않는다.** 예전에는 화면 아래 가운데를 무조건 가리켰는데, 두
    사람이 있는 컷에서 윤재가 하는 말의 꼬리가 시하를 가리켰다. 틀린 꼬리는
    없는 꼬리보다 나쁘다 — 대사가 통째로 다른 사람 것이 된다.

    speaker_side 는 콘티(W7)가 적는다. 그쪽은 이미 "A는 화면 왼쪽, B는 오른쪽"
    을 고정하고 있으므로 새로 판단할 것이 없다.
    """
    if kind == "narration":
        return None                      # 나레이션은 화자가 없다
    side = str(side_override or cut.get("speaker_side") or "").strip().lower()
    if side == "offscreen":
        return None                      # 화면 밖의 목소리 — 가리킬 사람이 없다
    pt = SIDE_POINT.get(side)
    if not pt:
        return None                      # 옛 run: 모르면 안 그린다
    fx, fy = pt
    # 풍선이 아래쪽에 있으면 인물은 그 위에 있을 가능성이 크다.
    if y > h * 0.5:
        fy = 1.0 - fy
    return int(w * fx), int(h * fy)


def compose_cut(img, cut: dict[str, Any]):
    """컷 이미지 한 장 위에 말풍선과 글자를 얹는다. 새 이미지를 돌려준다.

    **풍선을 글자에 맞춘다.** 칸을 꽉 채우면 짧은 대사도 화면을 가로지르는
    거대한 타원이 되어 그림을 덮는다. bubble_zone 은 "어느 쪽에 둘까"를
    정할 뿐이고, 크기는 글자가 정한다.
    """
    Image, ImageDraw, _ = _pil()
    out = img.convert("RGBA")
    w, h = out.size
    # 한 컷에 말이 여러 줄일 수 있다 (두 사람이 주고받는 칸). 옛 run 은
    # speech_rows 가 옛 세 칸에서 같은 모양을 만들어 주므로 여기는 한 길이다.
    rows = scenegen.speech_rows(cut)
    if not rows:
        return out.convert("RGB")

    zone = str(cut.get("bubble_zone") or "none").strip().lower()
    slot = ZONE_BOX.get(zone) or ZONE_BOX["top"]
    sx, sy, sw, _sh = slot
    probe = ImageDraw.Draw(out)

    # 글자 크기는 컷 폭에 비례시킨다 — 컷마다 해상도가 달라도 같은 크기로 읽힌다.
    base_size = max(14, int(w * 0.030))
    pad_x, pad_y = int(w * 0.030), int(w * 0.018)
    avail = int(sw * w) - pad_x * 2

    boxes = []
    for row in rows:
        fld, text = row["kind"], row["text"]
        f, lines, tw, th = measure(probe, text, avail, base_size)
        bw = min(int(sw * w), tw + pad_x * 2)
        bh = th + pad_y * 2
        if bubble_kind(cut, fld, text) in ("dialogue", "shout", "thought"):
            bw = int(bw * 1.18)          # 타원·구름은 모서리가 남으므로 여유를 준다
            bh = int(bh * 1.45)
        boxes.append((fld, text, min(bw, int(w * 0.94)), bh, row["side"]))

    total = sum(b[3] for b in boxes) + int(w * 0.012) * (len(boxes) - 1)
    y = sy * h
    # 아래쪽 자리면 쌓은 높이만큼 위로 올려 컷 밖으로 나가지 않게 한다.
    if sy > 0.5:
        y = min(y, h - total - int(h * 0.03))
    y = max(int(h * 0.02), y)

    multi = len([b for b in boxes if b[0] != "narration"]) > 1
    for fld, text, bw, bh, side in boxes:
        # 풍선이 둘 이상이면 **말한 사람 쪽으로** 좌우를 가른다. 겹쳐 쌓으면
        # 누가 먼저 말했는지, 어느 것이 누구 것인지 사라진다.
        if multi and fld != "narration" and side in ("left", "right"):
            x = int(w * 0.04) if side == "left" else int(w - bw - w * 0.04)
        elif sx + sw > 0.99:
            x = int(w - bw - w * 0.04)
        elif sx < 0.06:
            x = int(w * 0.04)
        else:
            x = int((sx + sw / 2) * w - bw / 2)
        x = max(0, min(x, w - bw))
        box = (x, int(y), x + bw, int(y + bh))
        kind = bubble_kind(cut, fld, text)
        draw_bubble(out, box, kind, text,
                    tail_point(cut, kind, w, h, y, side_override=side))
        y += bh + int(w * 0.012)
    return out.convert("RGB")


# --------------------------------------------------------------------------- #
# 단톡방 컷 — 이미지 모델을 부르지 않는다
#
# 이미지 모델은 한글 UI 를 못 그린다. 단톡방 문구를 서술로 넘겼더니 글자가
# 아예 안 나오거나 뭉개진 획이 나왔고, 그 컷을 살리려고 "휴대폰 제품 사진"
# 같은 인서트가 생겼다. 코드가 그리면 글자가 정확하고, 진짜 대화창처럼 보이고,
# 0원이다.
# --------------------------------------------------------------------------- #
BG      = (206, 216, 227)
BUBBLE  = (255, 255, 255)
MINE    = (254, 229,   0)
INK     = ( 26,  28,  33)
SUBINK  = (108, 118, 132)


def chat_cut(width: int, height: int, lines: list[str], title: str = "과 단톡방"):
    """단톡방 화면 한 컷. lines 는 말풍선 하나에 한 줄씩."""
    Image, ImageDraw, _ = _pil()
    img = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(img)

    pad = int(width * 0.06)
    bar_h = int(height * 0.09)
    draw.rectangle((0, 0, width, bar_h), fill=(168, 194, 212))
    tf = _font(int(bar_h * 0.42), bold=True)
    draw.text((pad, (bar_h - tf.size) / 2), title, font=tf, fill=INK)

    y = bar_h + int(height * 0.05)
    body = _font(int(height * 0.042))
    name_f = _font(int(height * 0.030))
    max_w = int(width * 0.62)
    for i, raw in enumerate(lines):
        text = str(raw or "").strip()
        if not text:
            continue
        mine = text.startswith(">")          # "> " 로 시작하면 내가 보낸 말
        text = text.lstrip("> ").strip()
        wrapped = wrap(draw, text, body, max_w - int(width * 0.06))
        tw = max(draw.textlength(l, font=body) for l in wrapped)
        bw = int(tw + width * 0.07)
        bh = int(len(wrapped) * body.size * 1.45 + height * 0.022)
        if not mine:
            draw.text((pad, y), f"익명{i % 3 + 1}", font=name_f, fill=SUBINK)
            y += int(name_f.size * 1.4)
            x0 = pad
        else:
            x0 = width - pad - bw
        draw.rounded_rectangle((x0, y, x0 + bw, y + bh), radius=int(height * 0.018),
                               fill=MINE if mine else BUBBLE)
        ty = y + int(height * 0.011)
        for l in wrapped:
            draw.text((x0 + int(width * 0.035), ty), l, font=body, fill=INK)
            ty += int(body.size * 1.45)
        y += bh + int(height * 0.028)
        if y > height - bh:
            break
    return img


def is_screen_cut(cut: dict[str, Any]) -> bool:
    """이 컷은 코드가 그리는 화면 컷인가 — 사람이 없고 화면 글자만 있는 컷."""
    if not str(cut.get("screen_text") or "").strip():
        return False
    return not [x for x in (cut.get("characters_in_frame") or []) if str(x).strip()]


# --------------------------------------------------------------------------- #
# 세로 조립 — 컷 사이에 여백을 둔다
#
# 여백은 시간이다. 붙인 두 컷은 한 호흡이고(몰아침), 띄운 두 컷 사이에서 독자는
# 잠깐 혼자가 된다(뜸들이기). 콘티가 컷마다 gap_after(0~3)를 이미 계산해 두었고
# (webtoon.derive_layout), 지금까지 그 값이 그림에 닿은 적이 없었다.
# --------------------------------------------------------------------------- #
# 컷 폭 대비 여백 높이. 처음엔 0.05/0.13/0.28 로 촘촘했는데, 화면에서 보면
# 셋이 다 "조금 뜬 것"으로 읽혀 여백을 안 쓴 것과 같았다. 웹툰의 여백은
# **시간**이라 차이가 눈에 보여야 뜻이 생긴다 — 3(낙차용)은 스크롤을 한 번
# 굴려야 다음 컷이 나올 만큼 비운다.
GAP_RATIO = {0: 0.0, 1: 0.07, 2: 0.26, 3: 0.62}

# 위 값은 **지면 폭 대비**라, 폭을 800px 로 두면 0 / 56 / 208 / 496px 이 된다.
# 세로 스크롤 작법이 실제로 쓰는 눈금은 이보다 넓다 (컷 폭 800px 기준):
#
#     빠른 동작·추격   100–150px    엄지가 안 멈춘다
#     감정 리액션      200–300px    한 박자 쉬고 다음 컷이 들어온다
#     장면 전환        400–600px    낮에서 밤으로, 다른 장소로
#     낙차·클리프행어  600–800px    화면이 통째로 비고 다음 컷이 나온다
#
# 특히 양 끝이 어긋난다 — 1(56px)은 "붙인 것"과 구분이 안 갈 만큼 좁고,
# 3(496px)은 폰 화면 하나를 채우지 못해서 "낙차"가 아니라 "조금 넓은 여백"이
# 된다. 뷰어는 3 을 이미 80vh(≈ 화면 하나)로 그리고 있어서, 같은 화를 뷰어로
# 볼 때와 PNG 한 장으로 볼 때 호흡이 서로 달랐다.
#
# 기본값은 그대로 둔다 — 이미 뽑아 둔 화의 PNG 가 다시 뽑을 때마다 달라지면
# 무엇이 바뀐 것인지 구분할 수 없다. 위 눈금으로 벌리려면 config 에 적는다:
#
#     scene:
#       gap_ratio: {0: 0.0, 1: 0.16, 2: 0.32, 3: 0.90}
#
# (0.16 · 0.32 · 0.90 = 800px 폭에서 128 / 256 / 720px — 위 표의 각 구간 안이다.)
#
# ⚠️ 위 눈금은 **작법서가 적어 둔 픽셀 값 그대로**이고, 그 값들은 화면이 지금보다
#    짧던 시절에 잡힌 것이다. 요즘 폰(19.5:9)에서 폭 800px 캔버스의 한 화면은
#    캔버스 좌표로 1700px 쯤이라, 720px 여백은 화면 하나가 아니라 **화면의 약 40%**
#    다. 뷰어는 같은 자리를 80vh(=화면 하나)로 그리므로, 같은 화를 뷰어로 볼 때가
#    PNG 로 볼 때보다 여전히 더 크게 뜸을 들인다.
#    낙차를 폰 화면 하나로 맞추고 싶으면 3 을 1.8 쯤으로 올린다 — 다만 그러면 화
#    전체 길이가 눈에 띄게 늘어난다(낙차 두 자리에 화면 두 개가 통째로 빈다).
WEBTOON_GAP_RATIO = {0: 0.0, 1: 0.16, 2: 0.32, 3: 0.90}


# 컷이 가로를 얼마나 쓸까 — **기본은 꽉 채운다.**
#
# "가로를 다 채우지 마라"를 size 별 고정표로 넣었다가 뺐다. 그건 "무조건
# 채워라"를 "무조건 조금 비워라"로 바꾼 것일 뿐 똑같이 기계적이다. 모든 normal
# 컷이 정확히 같은 폭이면 그것도 띠가 쌓인 것이다.
#
# **폭의 변화는 이미 비율에서 나온다.** 컷마다 캔버스가 16:9 / 4:3 / 3:4 / 9:16
# 로 갈리므로(run.cut_aspect), 같은 지면 폭에 놓아도 모양과 높이가 전부 다르다.
# 거기에 인셋을 또 얹으면 규칙 두 개가 겹친다.
#
# 특정 size 만 좁히고 싶으면 config 의 scene.width_ratio 에 그것만 적는다.
# 비워 두면(기본) 전부 1.0 이다.
#
# **무게(weight)는 예외다.** 위에서 size 별 고정표를 뺀 이유는 "모든 normal 컷을
# 똑같이 조금 비워라"가 "모든 컷을 꽉 채워라"만큼이나 기계적이기 때문이었다.
# 무게는 그 얘기가 아니다 — 좁아지는 것은 **콘티가 가볍다고 정한 컷뿐**이고,
# 그 컷은 배경도 없다. 지면을 덜 먹는 것이 곧 그 컷이 가볍다는 뜻이라, 폭이
# 내용에서 나온다.
#
# weight 가 없는 옛 컷은 전부 "normal" 로 읽히므로 예전처럼 1.0 이다.
LIGHT_WIDTH = 0.55        # 떠 있는 컷이 쓰는 지면 폭
# "wide" 는 사람이 결과보기에서 특정 장을 눈에 띄게 키우고 싶을 때 쓰는
# 수동 표시다 — 콘티(W7~W9)가 정하는 값이 아니라 실측 원가/작화 데이터도
# 없다. weight 가 없거나 "wide" 가 아닌 옛 컷은 이 경로를 안 타므로 결과가
# 안 바뀐다.
WIDE_WIDTH = 1.15         # 눈에 띄게 키운 장이 쓰는 지면 폭


def width_ratio(cut: dict[str, Any], table: dict[str, Any] | None = None,
                light: float = LIGHT_WIDTH, wide: float = WIDE_WIDTH) -> float:
    """이 컷이 지면 폭을 얼마나 쓸까 (0~1, wide 는 1 초과). 기본 1.0 = 꽉 채움."""
    weight = str(cut.get("weight") or "normal").strip().lower()
    if weight == "light":
        try:
            return max(0.3, min(1.0, float(light)))
        except (TypeError, ValueError):
            return LIGHT_WIDTH
    if weight == "wide":
        try:
            return max(1.0, min(1.6, float(wide)))
        except (TypeError, ValueError):
            return WIDE_WIDTH
    if not table:
        return 1.0
    try:
        return max(0.3, min(1.0, float(
            table.get(str(cut.get("size") or "").strip().lower(), 1.0))))
    except (TypeError, ValueError):
        return 1.0


def gap_ratio_table(cfg: dict[str, Any] | None = None) -> dict[int, float]:
    """config 의 scene.gap_ratio → {0..3: 폭 대비 비율}. 없으면 기본값 그대로.

    적어 놓은 칸만 갈아 끼운다 — {3: 0.9} 라고만 적으면 나머지 셋은 기본값이다.
    읽을 수 없는 값은 조용히 건너뛴다. 여기서 세우면 config 오타 하나에 이미 뽑아
    둔 화의 조립이 통째로 막힌다.
    """
    out = dict(GAP_RATIO)
    raw = ((cfg or {}).get("scene") or {}).get("gap_ratio") or {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            lv = int(k)
            val = float(v)
        except (TypeError, ValueError):
            continue
        if 0 <= lv <= 3 and 0.0 <= val <= 3.0:
            out[lv] = val
    return out


def gap_px(width: int, gap_after: Any, table: dict[int, float] | None = None) -> int:
    try:
        g = int(gap_after)
    except (TypeError, ValueError):
        g = 1
    tab = table or GAP_RATIO
    return int(width * tab.get(max(0, min(3, g)), 0.05))


def stitch_strip(items: list[tuple[Any, int, float]], out: Path,
                 bg=(255, 255, 255)) -> tuple[int, int]:
    """[(이미지, 뒤 여백 px, 가로 비율)] → 세로 한 장. (가로, 세로) 를 돌려준다.

    **지면 폭**은 가장 넓은 컷이 정한다. 컷마다 그 폭의 일부만 쓰고 가운데
    정렬되므로 좌우에 여백이 생기고 폭이 컷마다 달라진다 — 웹툰의 모양이다.
    전부 꽉 채우면 같은 폭의 띠가 쌓인 것처럼 보인다.

    컷을 **늘리지는 않는다.** 늘리면 그 컷만 흐려져서, 원인이 생성인지 조립인지
    구분할 수 없게 된다.
    """
    Image, _, _ = _pil()
    if not items:
        raise StripError("이어 붙일 컷이 하나도 없습니다.")

    # 지면 폭은 **가장 좁은 컷**이 정하고, 모든 컷이 그 폭을 꽉 채운다.
    # 좌우 여백은 두지 않는다 — 컷마다 폭이 다르면 띠가 들쭉날쭉해 보이고,
    # 세로로 쭉 내려오는 흐름이 끊긴다.
    #
    # 폭의 변화는 이미 **비율**에서 나온다: 같은 폭이어도 16:9 컷은 납작하고
    # 3:4 컷은 길다. 거기에 좌우 여백까지 얹으면 규칙이 겹친다.
    #
    # 가장 좁은 폭에 맞추는 이유는 **줄이기만 하기 위해서**다. 늘리면 그 컷만
    # 흐려져서, 원인이 생성인지 조립인지 구분할 수 없게 된다.
    # 지면 폭은 **ratio == 1.0(꽉 채우는 컷)** 중 가장 좁은 것이 정한다. ratio 가
    # 작은(가벼운) 컷은 원래부터 폭을 덜 쓰기로 되어 있으므로 지면 폭을 정하는
    # 데서 빼야 한다 — 안 그러면 가벼운 컷 하나가 화면 전체를 좁혀 버린다.
    # 전부 ratio < 1.0 인 (있을 수 없지만) 경우에는 예전처럼 가장 좁은 원본으로
    # 되돌아간다.
    full = [im.width for im, _g, r in items if r >= 0.999]
    page = min(full) if full else min(im.width for im, _g, _r in items)

    placed = []
    for im, gap, ratio in items:
        # ratio 를 실제 픽셀에 적용한다. 그동안 이 값이 계산만 되고 여기서
        # 버려지고 있었다 — width_ratio() 가 뭘 돌려주든 전부 꽉 채워 그려졌다.
        target = page if ratio >= 0.999 else max(1, round(page * ratio))
        # 늘리지는 않는다 — 늘리면 그 컷만 흐려져서, 원인이 생성인지 조립인지
        # 구분할 수 없게 된다. target 이 원본보다 크면 원본 폭 그대로 둔다.
        w = min(im.width, target)
        if w != im.width:
            im = im.resize((w, max(1, round(im.height * w / im.width))),
                           Image.LANCZOS)
        placed.append((im.convert("RGB"), max(0, int(gap)), w))

    total = sum(im.height + gap for im, gap, _w in placed)
    total -= placed[-1][1]              # 마지막 뒤 여백은 버린다
    if total > MAX_HEIGHT:
        raise StripError(
            f"이어 붙이면 세로 {total:,}px 입니다 (상한 {MAX_HEIGHT:,}px).\n"
            f"        provider.options.image_size 를 낮추세요.")

    sheet = Image.new("RGB", (page, total), bg)
    y = 0
    for i, (im, gap, w) in enumerate(placed):
        # 지면보다 좁은 컷(ratio < 1.0)은 가운데 정렬한다 — 좌우에 남는 자리가
        # 배경색으로 비어, "이 컷은 가볍다"는 것이 폭으로도 읽힌다.
        x = (page - w) // 2
        sheet.paste(im, (x, y))
        y += im.height + (gap if i < len(placed) - 1 else 0)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return page, total


# --------------------------------------------------------------------------- #
# 글자를 **이미지 모델이 그리게** 시키는 문구
#
# 이 파일 위쪽에는 코드가 풍선을 그리는 길(draw_bubble · compose_cut)이 있고,
# 여기는 그 반대 길이다. 둘 다 남겨 둔 이유는 서로 다른 것을 포기하기 때문이다:
#
#   코드가 그림 : 한글이 절대 안 깨지고 자리를 정확히 안다. 대신 얹은 티가 나고,
#                 그림 어디가 비었는지 몰라 vision 을 한 번 더 불러야 한다.
#   모델이 그림 : 풍선이 그림에 녹아들고 크기·꼬리를 장면에 맞춰 정한다.
#                 대신 한글이 깨질 수 있고, 대사를 고치려면 컷을 다시 뽑아야 한다.
#
# 지금은 모델이 그린다. 되돌리려면 run.build_jobs 에서 draw_text_clause 를
# NO_BUBBLE_CLAUSE 로 바꾸고 write_strip 의 vision 블록 주석을 푼다.
DRAW_BUBBLE_HEAD = (
    "SPEECH BALLOONS — draw them into the artwork, with the Korean text inside, "
    "spelled exactly as given. Clean legible Hangul at a size that reads on a "
    "phone. Place each balloon where it does not cover a face, and point its "
    "tail at the character who is speaking.")

# 모양을 말로 정해 준다. 나레이션이 말풍선으로 그려지던 것은 이 구분을 안 줘서
# 생긴 일이다 — 모델에게는 둘 다 그냥 "글자 담는 것"이다.
BUBBLE_SHAPE = {
    "narration": "a caption box with a straight rectangular edge and no tail "
                 "(this is narration, not speech — it must NOT look like a "
                 "speech balloon)",
    "dialogue": "a rounded oval speech balloon with a short tail",
    "shout": "a jagged explosive speech burst with spiky edges",
    "whisper": "a small balloon with a fine dotted outline",
    "thought": "a soft cloud-shaped thought bubble with small round bubbles "
               "trailing toward the character (no pointed tail)",
}


def draw_text_clause(cut: dict[str, Any]) -> str:
    """이 컷의 글자를 그림 안에 그리라고 시키는 문구.

    speaker_side 가 여기서 쓰인다 — "꼬리를 하윤재(화면 오른쪽)에게" 처럼
    **어느 쪽 인물인지**까지 말해 줘야 두 사람이 있는 컷에서 안 헷갈린다.
    """
    items = []
    rows = scenegen.speech_rows(cut)
    multi = len([r for r in rows if r["kind"] != "narration"]) > 1
    for row in rows:
        field, text = row["kind"], row["text"]
        kind = ("narration" if field == "narration" else
                "thought" if field == "thought" else
                "shout" if "!" in text else
                "whisper" if text.startswith("(") or "…" in text else "dialogue")
        who = row["speaker"] or str(cut.get("speaker") or "").strip()
        side = row["side"] or str(cut.get("speaker_side") or "").strip().lower()
        at = ""
        if kind not in ("narration", "thought") and who:
            where = {"left": " (on the left of the frame)",
                     "right": " (on the right of the frame)"}.get(side, "")
            at = f" Its tail points at {who}{where}."
        elif kind == "thought" and who:
            at = f" It belongs to {who}."
        # 풍선이 둘 이상이면 좌우를 못박는다. 안 그러면 두 꼬리가 같은 쪽을
        # 가리켜 누가 먼저 말했는지 사라진다.
        if multi and side in ("left", "right", "center") and kind != "narration":
            at += (" It sits in the middle of the panel." if side == "center"
                   else f" It sits on the {side} side of the panel.")
        items.append(f'{BUBBLE_SHAPE[kind]} carrying the Korean text "{text}".{at}')
    if len(items) > 1:
        items.append(f"There are {len(items)} separate balloons in this panel; "
                     "read them top to bottom in the order given, and do not let "
                     "them overlap each other or cover a face.")
    if not items:
        return ("No speech balloons and no lettering in this panel — it is a "
                "silent panel.")
    return DRAW_BUBBLE_HEAD + " " + " ".join(items)


# 반대 길에서 쓰는 문구 — 모델이 글자를 아예 안 그리게 한다.
NO_BUBBLE_CLAUSE = (
    "NO TEXT AND NO BALLOONS. Draw no speech balloons, no thought bubbles, no "
    "caption boxes, no lettering and no writing of any kind anywhere in this "
    "panel — they are composited on afterwards. Sound-effect lettering is the "
    "only exception and is described separately if this panel has one.")

# lettering: none 전용. 효과음 예외까지 없앤다 — 액션 컷에서는 큼직한 효과음
# 레터링이 화면을 가로질러서, 독자가 먼저 읽는 것이 동작이 아니라 글자가 된다.
NO_TEXT_AT_ALL_CLAUSE = (
    "NO TEXT ANYWHERE. Draw no speech balloons, no thought bubbles, no caption "
    "boxes, no sound-effect lettering and no writing of any kind in this panel — "
    "not in Korean, not in English, not as decoration. This panel is artwork "
    "only; every balloon and every word is composited on afterwards.")

# lettering: sfx_only 전용. 효과음은 그림의 일부라 남기고 풍선만 없앤다.
SFX_ONLY_CLAUSE = (
    "NO BALLOONS. Draw no speech balloons, no thought bubbles, no caption boxes "
    "and no dialogue text — those are composited on afterwards. The only "
    "lettering in this panel is the Korean sound effect described above, drawn "
    "as part of the artwork.")


def text_clause(cut: dict[str, Any], mode: str = "in_image") -> str:
    """lettering 모드에 맞는 글자 지시 한 줄.

    예전에는 build_jobs 가 draw_text_clause() 를 **무조건** 불렀다. config 의
    scene.lettering 을 컷 모드가 아예 안 보고 있었다는 뜻이라, overlay 로 두어도
    none 으로 두어도 컷에는 한글 말풍선이 그대로 구워졌다.
    """
    if mode == "in_image":
        return draw_text_clause(cut)
    if mode == "sfx_only":
        return SFX_ONLY_CLAUSE
    return NO_TEXT_AT_ALL_CLAUSE if mode == "none" else NO_BUBBLE_CLAUSE
