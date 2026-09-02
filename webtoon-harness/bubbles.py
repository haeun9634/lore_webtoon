"""말풍선 텍스트 얹기 — 말풍선 그림은 이미지 안에 있고, 글자만 위에 올린다.

CSS 로 말풍선을 그려 봤더니 그림과 따로 놀았다. 선 굵기도, 질감도, 원근도
맞지 않는다. 그래서 방식을 바꿨다:

  이미지 모델   : 빈 말풍선(과 캡션 박스)까지 그린다. 안은 비운다.
  이 코드       : 그 빈 자리에 대사 글자만 얹는다. 배경도 테두리도 꼬리도 없다.

빈 말풍선이 이미지 어디에 그려졌는지는 코드가 알 수 없다. 그래서 사람이
영역을 지정한다 — picks.csv / layout.json 과 같은 방식이다:

  1) 뷰어에서 [말풍선 편집] 을 켜고, 그려진 말풍선 위에 사각형을 끌어 그린다
  2) 그 영역에 해당 컷의 대사가 자동으로 들어간다 (영역에 맞춰 글자 크기 조절)
  3) 더블클릭으로 문구를 고치고, 끌어서 옮기고, 모서리로 크기를 바꾼다
  4) localStorage 에 즉시 저장 → [bubbles.json 내려받기] → 같은 폴더에 저장

좌표는 전부 이미지 대비 퍼센트다. 뷰어 폭이 바뀌어도 창을 줄여도 글자가
그려진 말풍선 안에 그대로 남아야 하기 때문이다.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BUBBLE_FILE = "bubbles.json"
SCENE_KEY_RE = re.compile(r"^(?:scene)?\s*(\d+)$", re.IGNORECASE)

MIN_W, MAX_W = 4.0, 96.0
MIN_H, MAX_H = 3.0, 96.0
DEFAULT_W = 34.0
# 글자 크기는 영역에 맞춰 자동으로 잡되, 이 아래로는 내려가지 않는다.
# 11px 보다 작아져야 들어간다면 그건 영역이 좁거나 대사가 긴 것이므로 사람에게 알린다.
MIN_FONT_PX, MAX_FONT_PX = 11.0, 64.0


class BubbleError(RuntimeError):
    """bubbles.json 을 읽을 수 없음. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


@dataclass
class Region:
    """이미지 위 사각형 하나. 그 안에 컷 하나의 대사가 들어간다."""
    cut: int
    text: str            # 화면에 얹을 문구 (사람이 고쳤으면 고친 것)
    source: str          # 원본 대사. 고쳤는지 판별하는 데만 쓴다
    x: float
    y: float
    w: float
    h: float
    fs: float | None = None   # 글자 크기 수동 지정(px). None 이면 영역에 맞춰 자동
    # 글자의 종류. 대사/나레이션/속마음은 표시 규약(대괄호·소괄호)으로도
    # 알아낼 수 있지만 screen_text 는 겉껍질이 없어서 구분이 안 된다 —
    # 화면 UI 는 말풍선이 아니라 다르게 그려져야 하므로 값을 들고 다닌다.
    kind: str = ""

    @property
    def edited(self) -> bool:
        return self.text.strip() != self.source.strip()


def bubbles_path(ep_dir: Path) -> Path:
    return ep_dir / BUBBLE_FILE


def is_narration(text: str) -> bool:
    """[대괄호]로 시작하면 무전·내레이션. 이미지 쪽은 캡션 박스로 그려진다."""
    return str(text or "").strip().startswith("[")


def is_thought(text: str) -> bool:
    """(소괄호)로 시작하면 속마음. 이미지 쪽은 구름 모양 풍선으로 그려진다."""
    return str(text or "").strip().startswith("(")


def kind_of(text: str) -> str:
    """얹을 글자의 종류. 뷰어가 모양을 다르게 줄 때 쓴다."""
    if is_narration(text):
        return "narration"
    if is_thought(text):
        return "thought"
    return "dialogue"


def _est_height(text: str, w: float) -> float:
    """폭 w(%)일 때 글자가 차지할 높이(%) 어림. 예전 형식 파일을 옮길 때만 쓴다."""
    per_line = max(6.0, w * 0.42)
    lines = max(1, math.ceil(len(str(text or "")) / per_line))
    return min(MAX_H, 3.0 + lines * 3.4)


def _clamp(value: Any, lo: float, hi: float, fallback: float) -> float:
    try:
        return min(hi, max(lo, float(value)))
    except (TypeError, ValueError):
        return fallback


# --------------------------------------------------------------------------- #
# 자동 배치 — 콘티가 정해 둔 자리(bubble_zone)가 있을 때만
#
# 오랫동안 자동 배치를 하지 않았다. 이유는 정당했다: 빈 말풍선이 그림 어디에
# 있는지 모르는 채로 아무 데나 글자를 얹으면 말풍선 밖에 떨어져서 손이 더 간다.
#
# 그런데 그건 **자리를 아무도 모를 때**의 이야기다. 지금은 콘티가 컷마다
# bubble_zone 을 정하고, 그 자리를 비우라는 지시가 생성 프롬프트에도 들어간다
# (scenegen.bubble_zone_clause). 즉 그림과 배치가 같은 값을 보고 있다.
#
# 그래도 이건 **초안**이다. 모델이 지시를 무시할 수 있으므로 사람이 뷰어에서
# 고칠 수 있어야 하고, 사람이 그린 사각형은 언제나 이것을 이긴다.
# --------------------------------------------------------------------------- #

# 한 컷 안에서 zone 이 가리키는 직사각형 (x, y, w) — 세로는 글자 길이로 정한다.
ZONE_BOX = {
    "top":    (8.0, 6.0, 84.0),
    "bottom": (8.0, 74.0, 84.0),
    "left":   (5.0, 20.0, 42.0),
    "right":  (53.0, 20.0, 42.0),
    "center": (18.0, 40.0, 64.0),
}
STACK_GAP = 1.5      # 한 컷에 글자가 여럿일 때 세로 간격(%)


def auto_regions(scenes: list[dict[str, Any]],
                 cut_order: dict[int, list[int]] | None = None) -> dict[int, list[Region]]:
    """bubble_zone 으로 만든 배치 초안. zone 이 none/없음이면 만들지 않는다.

    scenes    : [{"scene_number", "lines": [{"cut", "text", "zone"}]}, ...]
    cut_order : {scene_number: [컷 번호 순서]} — 한 장에 컷이 여럿일 때 필요하다.

    ★ bubble_zone 은 **컷(패널) 안에서의 자리**이고 Region 좌표는 **장 전체**
      기준이다. 그래서 컷이 여럿인 장에서는 그 컷이 장의 어느 높이에 있는지를
      먼저 알아야 한다. cut_order 로 장을 컷 수만큼 세로로 나누고, 그 구간
      안에서 zone 이 가리키는 자리에 놓는다. 이걸 안 하면 한 장의 글자가
      전부 맨 위에 겹쳐 쌓인다.

    ⚠️ 이건 **어림**이다. 장의 실제 구성은 큰 컷 하나가 바탕을 덮고 나머지가
      그 위에 겹치는 형태라(scene.composition) 컷이 세로로 고르게 나뉘어 있지
      않고, 코드는 그 배치를 알 수 없다. 그래서 초안이고, 사람이 뷰어에서 끌어
      고친 것이 언제나 이것을 이긴다.
    """
    out: dict[int, list[Region]] = {}
    for sc in scenes:
        n = int(sc["scene_number"])
        order = list((cut_order or {}).get(n) or [])
        by_cut: dict[int, list[dict[str, Any]]] = {}
        for line in sc.get("lines") or []:
            text = str(line.get("text") or "").strip()
            zone = str(line.get("zone") or "none").strip().lower()
            if not text:
                continue
            # 화면 글자는 말풍선이 아니라 bubble_zone 을 갖지 않는다. 그래도
            # 읽는 사람에게는 보여야 하므로(단톡방이 안 보이던 것이 원래
            # 피드백이다) 그 컷 구간의 가운데에 놓는다. 실제 화면이 어디 있는지는
            # 그림을 봐야 알므로 이건 특히 거친 어림이다.
            if zone not in ZONE_BOX:
                if str(line.get("kind") or "") != "screen_text":
                    continue
                line = dict(line, zone="center")
            by_cut.setdefault(int(line["cut"]), []).append(line)

        for cut, lines in by_cut.items():
            # 이 컷이 장의 어느 세로 구간인가.
            if len(order) > 1 and cut in order:
                i, total = order.index(cut), len(order)
                band_top, band_h = 100.0 * i / total, 100.0 / total
            else:
                band_top, band_h = 0.0, 100.0

            x, y, w = ZONE_BOX[str(lines[0].get("zone")).strip().lower()]
            top = band_top + y * band_h / 100.0     # zone 의 y 를 구간 크기로 환산
            for line in lines:
                text = str(line["text"]).strip()
                h = min(_est_height(text, w), band_h)
                if top + h > 100.0:
                    break            # 칸을 벗어난다 — 나머지는 사람이 놓는다
                out.setdefault(n, []).append(Region(
                    cut=cut, text=text, source=text,
                    x=x, y=top, w=w, h=h, fs=None,
                    kind=str(line.get("kind") or "")))
                top += h + STACK_GAP
    for n in out:
        out[n].sort(key=lambda r: r.cut)
    return out


def load(ep_dir: Path, scenes: list[dict[str, Any]]) -> tuple[dict[int, list[Region]],
                                                              list[str], bool]:
    """bubbles.json → {scene_number: [Region]}.

    scenes : [{"scene_number", "cut_numbers", "lines": [{"cut","text","zone"}]}, ...]
    반환    : (영역, 경고, 파일이 있었는가)

    **사람이 그린 사각형이 언제나 이긴다.** 콘티의 bubble_zone 으로 만든 초안은
    그 위에 없는 컷만 채운다 — 자동 배치는 그림이 지시를 따랐다고 가정하는
    것이고, 그 가정이 틀렸을 때 고치는 것은 사람이기 때문이다.

    bubble_zone 이 없는 옛 run 은 초안이 비어 있고, 예전처럼 영역 없는 대사가
    뷰어의 "배치 대기" 목록에 남는다.
    """
    by_scene = {int(sc["scene_number"]): {
        int(l["cut"]): str(l.get("text") or "").strip()
        for l in (sc.get("lines") or []) if str(l.get("text") or "").strip()
    } for sc in scenes}

    drafted = auto_regions(scenes, {int(sc["scene_number"]): list(sc.get("cut_numbers") or [])
                                    for sc in scenes})
    path = bubbles_path(ep_dir)
    if not path.exists():
        return drafted, [], False

    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise BubbleError(f"{BUBBLE_FILE} 을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(raw, dict):
        raise BubbleError(f"{BUBBLE_FILE} 의 최상위는 객체여야 합니다: "
                          f'{{"scene1": [{{"cut": 2, "x": 12, "y": 38, "w": 40, "h": 9}}]}}')

    warnings: list[str] = []
    placed: dict[int, list[Region]] = {}
    old_format = False

    for key, items in raw.items():
        if str(key).startswith("_"):
            continue
        m = SCENE_KEY_RE.match(str(key).strip())
        if not m:
            warnings.append(f'{BUBBLE_FILE}: Scene 키를 알 수 없습니다 → "{key}" '
                            f'(예: "scene1" 또는 "1")')
            continue
        n = int(m.group(1))
        if n not in by_scene:
            warnings.append(f"{BUBBLE_FILE}: Scene {n} 은 이 화에 없습니다.")
            continue
        if not isinstance(items, list):
            warnings.append(f"{BUBBLE_FILE}: scene{n} 의 값은 배열이어야 합니다.")
            continue

        texts, seen = by_scene[n], []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                cut = int(item["cut"])
            except (KeyError, TypeError, ValueError):
                warnings.append(f"{BUBBLE_FILE}: scene{n} 에 cut 번호가 없는 항목이 있습니다.")
                continue
            if cut not in texts:
                warnings.append(f"{BUBBLE_FILE}: scene{n} 의 컷 {cut} 은 이 Scene 에 "
                                f"없거나 대사가 없습니다 → 건너뜁니다.")
                continue
            if cut in seen:
                warnings.append(f"{BUBBLE_FILE}: scene{n} 에 컷 {cut} 이 여러 번 "
                                f"있습니다 → 첫 번째만 씁니다.")
                continue
            seen.append(cut)

            source = texts[cut]
            text = str(item.get("text") or "").strip() or source
            w = _clamp(item.get("w"), MIN_W, MAX_W, DEFAULT_W)
            if item.get("h") is None:
                # 예전 형식(CSS 말풍선)에는 높이가 없었다. 글자 길이로 어림해 옮긴다.
                old_format = True
                h = _est_height(text, w)
            else:
                h = _clamp(item.get("h"), MIN_H, MAX_H, _est_height(text, w))
            fs = None
            if item.get("fs") is not None:
                fs = _clamp(item.get("fs"), MIN_FONT_PX, MAX_FONT_PX, MIN_FONT_PX)
            placed.setdefault(n, []).append(Region(
                cut=cut, text=text, source=source,
                x=_clamp(item.get("x"), 0.0, 100.0 - w, 5.0),
                y=_clamp(item.get("y"), 0.0, 100.0 - h, 5.0),
                w=w, h=h, fs=fs))

    if old_format:
        warnings.append(
            f"{BUBBLE_FILE}: 높이(h)가 없는 예전 형식입니다 — 글자 길이로 어림해 "
            f"옮겼습니다. 뷰어에서 위치를 다시 잡고 내려받아 덮어써 주세요.")

    # 사람이 놓지 않은 컷만 초안으로 채운다.
    for n, regions in drafted.items():
        have = {r.cut for r in placed.get(n, ())}
        for r in regions:
            if r.cut not in have:
                placed.setdefault(n, []).append(r)

    for n in placed:
        placed[n].sort(key=lambda r: r.cut)
    return placed, warnings, True


def to_file_json(by_scene: dict[int, list[Region]]) -> str:
    """내려받기/저장용 bubbles.json 본문. text 는 원본과 다를 때만 적는다."""
    out: dict[str, Any] = {}
    for n in sorted(by_scene):
        items = []
        for r in by_scene[n]:
            item: dict[str, Any] = {"cut": r.cut, "x": round(r.x, 1), "y": round(r.y, 1),
                                    "w": round(r.w, 1), "h": round(r.h, 1)}
            if r.edited:
                item["text"] = r.text
            if r.fs is not None:
                item["fs"] = round(r.fs, 1)
            items.append(item)
        out[f"scene{n}"] = items
    return json.dumps(out, ensure_ascii=False, indent=2) + "\n"
