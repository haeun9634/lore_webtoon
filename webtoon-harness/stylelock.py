"""style_lock.html — Scene 과 Scene 사이에서 그림체가 유지되는가를 확인하는 도구.

기존 스타일 실험은 "캐릭터 1명 x 장면 1개 x 6회" 로 style_suffix 문구를 골랐다.
그건 **한 장 안에서** 그 문구가 먹히는지를 본 것이다. 화 전체를 이어 읽을 때
Scene 1 과 Scene 4 의 그림체가 같은 사람 손에서 나온 것으로 보이는가는 아직
확인한 적이 없다. 이 파일이 그것만 본다.

이미지는 다시 만들지 않는다. 이미 뽑아 둔 scene_<조건>/ 의 채택본만 읽는다
(API 호출 0회, 0원). 화면은 두 가지 보기를 오간다:

  세로 보기   : Scene 을 위에서 아래로 나란히 놓는다. 읽는 순서 그대로 본다.
  얼굴만 크롭 : 각 Scene 에서 인물 얼굴만 잘라 **가로로** 붙여 놓는다.
                그림체 차이는 얼굴에서 제일 먼저 드러나기 때문이다 — 세로로
                떨어져 있으면 눈이 기억으로 비교하지만, 옆에 붙여 놓으면
                눈매 각도나 코 생략 정도가 바로 보인다.

얼굴이 이미지 어디에 있는지는 코드가 알 수 없다(얼굴 검출을 넣으면 의존성이
늘고, 이 하네스는 그걸 감당할 물건이 아니다). 그래서 사람이 지정한다 —
picks.csv / layout.json / bubbles.json 과 완전히 같은 방식이다:

  1) [크롭 편집] 을 켜고 Scene 이미지 위에 얼굴 자리를 끌어 그린다
  2) localStorage 에 즉시 저장 (새로고침해도, 다시 만들어도 남는다)
  3) [style_faces.json 내려받기] -> 같은 폴더에 저장
  4) 다음에 다시 만들 때 그 파일이 HTML 에 박혀 들어와 기준선이 된다
     (file:// 에서는 JSON 을 fetch 할 수 없기 때문)

처음 열면 자리를 모르므로 어림잡은 상자가 놓인다. 그건 정답이 아니라 출발점이다.

채점은 점수가 아니라 Y/N 이다. "7점"은 다음에 뭘 고칠지 알려주지 않지만
"배경밀도 N"은 알려준다. 열은 style_score.csv 와 정확히 같다.
"""

from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from viewer import _esc, image_size

CROP_FILE = "style_faces.json"
SCORE_FILE = "style_score.csv"
PAGE_FILE = "style_lock.html"

SCENE_KEY_RE = re.compile(r"^(?:scene)?\s*(\d+)$", re.IGNORECASE)

# 체크 항목 — (csv 열 이름, 화면 표시, 무엇을 보라는 말)
# 열 이름은 style_score.csv 와 1:1 이다. 바꾸면 이미 채운 채점표와 어긋난다.
ITEMS: list[tuple[str, str, str]] = [
    ("선굵기", "선 굵기",
     "윤곽선이 다른 Scene 보다 굵거나 얇지 않은가. 머리카락 끝과 옷 주름에서 제일 잘 보인다."),
    ("채도톤", "채도·명도 톤",
     "같은 빨강이 더 쨍하거나 탁하지 않은가. 그림자 밝기가 튀지 않는가."),
    ("얼굴양식화", "얼굴 양식화 정도",
     "눈·코·입을 얼마나 생략했는가. 한 Scene 만 사실적이거나 한 Scene 만 단순하면 N."),
    ("배경밀도", "배경 디테일 밀도",
     "배경을 어디까지 그렸는가. 한 Scene 만 텅 비거나 한 Scene 만 빽빽하면 N."),
]
TOTAL_KEY = "종합"
SCORE_HEADER = ["scene_no"] + [k for k, _, _ in ITEMS] + [TOTAL_KEY]

# 처음 열었을 때 놓이는 얼굴 상자 (이미지 대비 %). 정답이 아니라 출발점이다.
# 패널이 위에서 아래로 쌓이므로 첫 패널의 가운데 위쪽을 잡아 둔다.
DEFAULT_CROP = {"x": 28.0, "y": 6.0, "w": 44.0, "h": 26.0}
MIN_SIDE = 4.0

FACE_H = 260          # 얼굴 크롭 타일 높이(px). 확대를 켜면 두 배가 된다.
MIN_ZOOM, MAX_ZOOM = 1.5, 4.0


class StyleLockError(RuntimeError):
    """style_faces.json 을 읽을 수 없음. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


def crops_path(ep_dir: Path) -> Path:
    return ep_dir / CROP_FILE


def score_path(ep_dir: Path) -> Path:
    return ep_dir / SCORE_FILE


def page_path(ep_dir: Path) -> Path:
    return ep_dir / PAGE_FILE


def _clamp(value: Any, lo: float, hi: float, fallback: float) -> float:
    try:
        return min(hi, max(lo, float(value)))
    except (TypeError, ValueError):
        return fallback


# --------------------------------------------------------------------------- #
# style_faces.json
# --------------------------------------------------------------------------- #
def load_crops(ep_dir: Path, cond_dir: str,
               numbers: list[int]) -> tuple[dict[int, dict[str, float]], list[str], bool]:
    """style_faces.json -> {scene_number: {x,y,w,h}}. 없으면 빈 dict.

    조건마다 그림이 다르므로 얼굴 자리도 다르다. 그래서 조건 폴더 이름
    (scene_C 처럼)으로 한 겹 감싼다:

        {"scene_C": {"scene1": {"x": 30, "y": 8, "w": 40, "h": 24}, ...}}

    감싸지 않은 예전/손으로 쓴 형태({"scene1": {...}})도 받아서 이 조건 것으로 본다.
    돌려주는 경고는 run.py 가 화면에 찍는다 — 조용히 기본값으로 떨어지면
    파일을 고쳐도 왜 안 먹는지 알 수 없다.
    """
    path = crops_path(ep_dir)
    if not path.exists():
        return {}, [], False
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise StyleLockError(f"{CROP_FILE} 을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(raw, dict):
        raise StyleLockError(f"{CROP_FILE} 의 최상위는 객체여야 합니다: "
                             f'{{"{cond_dir}": {{"scene1": {{"x": 30, "y": 8, '
                             f'"w": 40, "h": 24}}}}}}')

    warnings: list[str] = []
    block = raw.get(cond_dir)
    if block is None:
        others = [k for k in raw if not str(k).startswith("_")
                  and isinstance(raw[k], dict) and not SCENE_KEY_RE.match(str(k).strip())]
        if others:
            warnings.append(f"{CROP_FILE}: 이 조건({cond_dir})의 얼굴 자리가 없습니다 "
                            f"(파일에 있는 것: {', '.join(others)}). 기본 상자로 시작합니다.")
            return {}, warnings, True
        block = raw     # 감싸지 않은 형태 — 이 조건 것으로 본다
    if not isinstance(block, dict):
        raise StyleLockError(f"{CROP_FILE} 의 {cond_dir} 값은 객체여야 합니다.")

    crops: dict[int, dict[str, float]] = {}
    for key, item in block.items():
        if str(key).startswith("_"):
            continue
        m = SCENE_KEY_RE.match(str(key).strip())
        if not m:
            warnings.append(f'{CROP_FILE}: Scene 키를 알 수 없습니다 -> "{key}" '
                            f'(예: "scene1" 또는 "1")')
            continue
        n = int(m.group(1))
        if n not in numbers:
            warnings.append(f"{CROP_FILE}: Scene {n} 은 이 화에 없습니다 "
                            f"(Scene {min(numbers)}~{max(numbers)}).")
            continue
        if not isinstance(item, dict):
            warnings.append(f"{CROP_FILE}: scene{n} 의 값은 객체여야 합니다 "
                            f'({{"x": 30, "y": 8, "w": 40, "h": 24}}).')
            continue
        w = _clamp(item.get("w"), MIN_SIDE, 100.0, DEFAULT_CROP["w"])
        h = _clamp(item.get("h"), MIN_SIDE, 100.0, DEFAULT_CROP["h"])
        crops[n] = {"x": _clamp(item.get("x"), 0.0, 100.0 - w, DEFAULT_CROP["x"]),
                    "y": _clamp(item.get("y"), 0.0, 100.0 - h, DEFAULT_CROP["y"]),
                    "w": w, "h": h}
    return crops, warnings, True


def other_blocks(ep_dir: Path, cond_dir: str) -> dict[str, Any]:
    """style_faces.json 에서 이 조건이 아닌 부분. 내려받기가 그대로 들고 나간다.

    한 파일에 여러 이름표가 산다 (scene_C / verify/scene_C ...). 어느 화면에서
    내려받든 자기 것만 쓰고 나머지를 빼먹으면, 저장하는 순간 다른 화면의 얼굴
    자리가 조용히 사라진다 — picks.csv 가 다른 모드의 행을 옮겨 담는 것과 같은 이유다.
    """
    path = crops_path(ep_dir)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(raw, dict):
        return {}
    # 감싸지 않은 예전 형태({"scene1": ...})는 통째로 이 조건 것이므로 남길 게 없다.
    if any(SCENE_KEY_RE.match(str(k).strip()) for k in raw):
        return {}
    return {k: v for k, v in raw.items() if k != cond_dir}


# --------------------------------------------------------------------------- #
# style_score.csv
# --------------------------------------------------------------------------- #
def write_score(ep_dir: Path, numbers: list[int], header: list[str] | None = None,
                filename: str = SCORE_FILE) -> tuple[Path, bool]:
    """빈 채점표를 만든다. (경로, 새로 만들었는가).

    이미 있으면 절대 덮어쓰지 않는다 — 사람이 채운 Y/N 이 그 안에 있다.
    verify_score.csv 도 열만 다를 뿐 같은 규약이라 이 함수를 같이 쓴다.
    """
    cols = header or SCORE_HEADER
    path = ep_dir / filename
    if path.exists():
        return path, False
    ep_dir.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for n in numbers:
            w.writerow([n] + [""] * (len(cols) - 1))
    return path, True


def read_score(ep_dir: Path, header: list[str] | None = None,
               filename: str = SCORE_FILE) -> dict[int, dict[str, str]]:
    """채운 채점표를 읽어 HTML 에 박아 넣는다 (file:// 에서 fetch 불가).

    Y/N 만 인정한다. 그 밖의 값(점수를 적었다든지)은 버리고 빈칸으로 본다 —
    이 표는 "고칠 것이 있는가" 만 묻는다.
    """
    cols = (header or SCORE_HEADER)[1:]      # scene_no 는 값이 아니라 행 이름이다
    path = ep_dir / filename
    if not path.exists():
        return {}
    out: dict[int, dict[str, str]] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    n = int(str(row.get("scene_no") or "").strip())
                except (TypeError, ValueError):
                    continue
                marks = {}
                for key in cols:
                    v = str(row.get(key) or "").strip().upper()
                    if v in ("Y", "N"):
                        marks[key] = v
                if marks:
                    out[n] = marks
    except (OSError, csv.Error):
        return {}
    return out


# --------------------------------------------------------------------------- #
CSS = """
:root { --w: 690px; --fh: 260px; --z: 2.6; --bg: #ffffff; --fg: #16181d;
        --line: rgba(0,0,0,.12); --soft: rgba(0,0,0,.05); --dim: rgba(0,0,0,.45); }
* { box-sizing: border-box; }
html { scrollbar-gutter: stable; }
body { margin: 0; padding-top: var(--bar, 40px); background: var(--bg); color: var(--fg);
       font: 14px/1.65 "Malgun Gothic", system-ui, sans-serif;
       -webkit-font-smoothing: antialiased; }

/* --- 상단 바 --------------------------------------------------------------- */
.bar { position: fixed; top: 0; left: 0; right: 0; z-index: 10; display: flex;
       align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 14px;
       font-size: 12.5px; line-height: 1.4; color: #e6e8ee;
       background: rgba(18,20,26,.90); backdrop-filter: blur(6px); }
.bar .cond { color: #9aa2b4; }
.bar .sp { flex: 1 1 auto; }
.bar label { display: flex; align-items: center; gap: 5px; cursor: pointer;
             user-select: none; white-space: nowrap; }
.bar a { color: #9dc0ff; text-decoration: none; }
.bar a:hover { text-decoration: underline; }
.bar button { font: inherit; color: #e6e8ee; background: #2b313d; cursor: pointer;
              border: 1px solid #3f4756; border-radius: 5px; padding: 4px 9px; }
.bar button:hover { background: #39414f; }
.bar button.primary { background: #2f6fed; border-color: #2f6fed; color: #fff;
                      font-weight: 600; }
.edit-only { display: none; align-items: center; gap: 8px; }
/* 편집 모드는 body.cedit 이다. body 에 .crop 을 붙이면 얼굴 상자의 `.crop img` 가
   페이지의 모든 이미지에 걸린다 (body 의 자손이 아닌 이미지는 없다). */
body.cedit .edit-only { display: flex; }
.dirty { color: #ffc75a; }
.tally { color: #9aa2b4; font-variant-numeric: tabular-nums; }

/* --- 얼굴만 크롭: 가로로 나란히 ---------------------------------------------- */
.faces { display: none; gap: 14px; padding: 16px 14px 4px; overflow-x: auto;
         align-items: flex-start; }
body.face .faces { display: flex; }
.tile { margin: 0; flex: 0 0 auto; }
/* 상자의 가로세로비는 잘라낸 픽셀 비율(--ar)이다. 높이를 고정하고 폭을 거기서
   끌어내야 얼굴이 눌리거나 늘어나지 않는다. */
.crop { position: relative; overflow: hidden; height: var(--fh); aspect-ratio: var(--ar);
        background: rgba(127,127,127,.10); border: 1px solid var(--line); }
body.zoom .crop { height: calc(var(--fh) * 2); }
/* 잘라내기는 이미지를 상자보다 크게 키워 밀어 넣는 것으로 한다. 좌표가 전부
   퍼센트라 창 크기가 바뀌어도 같은 자리가 남는다. */
.crop img { position: absolute; display: block;
            width: calc(10000% / var(--cw)); height: calc(10000% / var(--ch));
            left: calc(-100% * var(--cx) / var(--cw));
            top: calc(-100% * var(--cy) / var(--ch));
            max-width: none; image-rendering: auto; }
.tile figcaption { padding: 6px 2px 4px; font-size: 12px; color: var(--dim);
                   font-variant-numeric: tabular-nums; }
.tile figcaption b { color: var(--fg); font-size: 12.5px; }
.tile .miss { display: flex; align-items: center; justify-content: center; width: 190px;
              height: var(--fh); padding: 14px; text-align: center; font-size: 12px;
              color: var(--dim); border: 2px dashed var(--line); background: var(--soft); }

/* --- 세로 보기: Scene 을 읽는 순서대로 ---------------------------------------- */
.stack { padding: 16px 14px 0; }
body.face .stack { display: none; }
body.face.cedit .stack { display: block; }    /* 크롭을 고치려면 원본이 보여야 한다 */
.row { display: flex; gap: 18px; align-items: flex-start; justify-content: center;
       margin-bottom: 34px; }
.shot { flex: 0 1 var(--w); min-width: 0; overflow-x: auto; }
.sframe { position: relative; width: 100%; }
body.zoom .sframe { width: calc(var(--w) * var(--z)); }
.sframe img { display: block; vertical-align: bottom; width: 100%; height: auto;
              background: rgba(127,127,127,.10); }
.no { position: absolute; top: 8px; left: 8px; z-index: 2; pointer-events: none;
      font: 700 11px/1 ui-monospace, "Consolas", monospace; letter-spacing: .03em;
      padding: 4px 7px; border-radius: 4px; background: rgba(18,20,26,.62); color: #fff; }
.no i { font-style: normal; opacity: .72; font-weight: 400; }
.shot .miss { display: flex; align-items: center; justify-content: center; aspect-ratio: 3/4;
              padding: 24px; text-align: center; font-size: 13px; color: var(--dim);
              border: 2px dashed var(--line); background: var(--soft); }
.shot .miss .d { display: block; margin-top: 8px; font-size: 12px; opacity: .85; }

/* --- 얼굴 자리 상자 (크롭 편집) ----------------------------------------------- */
.box { position: absolute; left: var(--cx0); top: var(--cy0);
       width: var(--cw0); height: var(--ch0); z-index: 3; display: none; }
body.cedit .box { display: block; outline: 2px solid #2f6fed;
                  background: rgba(47,111,237,.10); cursor: grab; }
body.cedit .box.drag { cursor: grabbing; background: rgba(47,111,237,.18); }
body.cedit .sframe { cursor: crosshair; }
.box b { position: absolute; left: 0; top: -18px; white-space: nowrap;
         font: 700 10px/1 ui-monospace, "Consolas", monospace; color: #fff;
         background: #2f6fed; padding: 3px 5px; border-radius: 3px; }
.box i.grip { position: absolute; right: -7px; bottom: -7px; width: 14px; height: 14px;
              border: 2px solid #2f6fed; border-radius: 3px; background: #fff;
              cursor: nwse-resize; }
.rubber { position: absolute; z-index: 4; border: 2px dashed #2f6fed;
          background: rgba(47,111,237,.12); pointer-events: none; }

/* --- 체크 항목 ---------------------------------------------------------------- */
.chk { flex: 0 0 268px; position: sticky; top: calc(var(--bar, 40px) + 12px);
       border: 1px solid var(--line); border-radius: 8px; background: var(--soft);
       padding: 12px 13px; font-size: 12.5px; }
.chk > b { display: block; margin-bottom: 8px; font-size: 13px; }
.chk .hint { color: var(--dim); font-size: 11.5px; margin: -4px 0 10px; }
.it { display: flex; align-items: center; gap: 6px; padding: 5px 0;
      border-top: 1px solid var(--line); }
.it:first-of-type { border-top: 0; }
.it.sum { margin-top: 4px; border-top: 2px solid var(--line); font-weight: 700; }
.it > span { flex: 1 1 auto; min-width: 0; }
.it > span em { display: block; font-style: normal; font-weight: 400; font-size: 11px;
                color: var(--dim); line-height: 1.45; }
.it i { flex: 0 0 auto; width: 26px; text-align: center; cursor: pointer; user-select: none;
        font: 700 11px/20px ui-monospace, "Consolas", monospace; border-radius: 4px;
        border: 1px solid var(--line); background: #fff; color: var(--dim); }
.it i:hover { border-color: #2f6fed; color: #2f6fed; }
.it i.on[data-v="Y"] { background: #1f9d55; border-color: #1f9d55; color: #fff; }
.it i.on[data-v="N"] { background: #d33; border-color: #d33; color: #fff; }

/* 얼굴 타일 아래에도 같은 체크가 붙는다. 옆에 붙여 놓고 바로 표시하려고. */
.tile .chk { position: static; flex: none; width: 100%; margin-top: 6px; padding: 8px 9px;
             font-size: 11.5px; }
.tile .chk > b, .tile .chk .hint, .tile .it > span em { display: none; }
.tile .it { padding: 3px 0; }

footer { max-width: 1080px; margin: 0 auto; padding: 20px 16px 56px;
         font-size: 12.5px; color: var(--dim); }
footer p { margin: 0 0 8px; }
footer b { color: var(--fg); }
footer code { background: var(--soft); padding: 1px 5px; border-radius: 4px; }
footer ol { margin: 4px 0 10px; padding-left: 20px; }
footer li { margin-bottom: 3px; }
"""


JS = """
const root = document.documentElement, body = document.body;
const bar = document.querySelector(".bar");
// 얼굴 자리는 조건마다 다르다 (그림이 다르므로). 채점도 마찬가지다.
const CKEY = "webtoon-stylecrop:" + META.run_id + ":ep" + META.episode + ":" + META.cond;
const SKEY = "webtoon-stylescore:" + META.run_id + ":ep" + META.episode + ":" + META.cond;
const VKEY = "webtoon-stylelock:" + META.run_id + ":ep" + META.episode;

const face = document.getElementById("face"), zoom = document.getElementById("zoom"),
      crop = document.getElementById("crop"), dirty = document.getElementById("dirty"),
      tally = document.getElementById("tally");

let crops = {};   // {scene: {x,y,w,h}} — 사람이 지정한 얼굴 자리
let score = {};   // {scene: {열이름: "Y"|"N"}}

function fitBar() {
  const h = bar.offsetHeight + "px";
  if (root.style.getPropertyValue("--bar") !== h) root.style.setProperty("--bar", h);
}

function cropOf(n) {
  return crops[n] || META.saved_crops[n] || META.def_crop;
}

/* --- 보기 토글 --------------------------------------------------------------- */
function apply() {
  body.classList.toggle("face", !!(face && face.checked));
  body.classList.toggle("zoom", !!(zoom && zoom.checked));
  body.classList.toggle("cedit", !!(crop && crop.checked));
  fitBar();
  try {
    localStorage.setItem(VKEY, JSON.stringify(
      {face: face && face.checked, zoom: zoom && zoom.checked,
       crop: crop && crop.checked}));
  } catch (e) {}
}

[face, zoom, crop].filter(Boolean).forEach(el => el.addEventListener("input", apply));

/* --- 얼굴 자리 --------------------------------------------------------------- */
// 타일과 원본 위 상자는 같은 값을 본다. 하나를 고치면 둘 다 그 자리에서 다시 그려진다.
function paintCrop(n) {
  const c = cropOf(n), sc = META.scenes.filter(s => s.n === +n)[0];
  const tile = document.querySelector('.tile[data-scene="' + n + '"] .crop');
  if (tile && sc) {
    tile.style.setProperty("--cx", c.x);
    tile.style.setProperty("--cy", c.y);
    tile.style.setProperty("--cw", c.w);
    tile.style.setProperty("--ch", c.h);
    // 잘라낸 조각의 실제 픽셀 비율. 이게 틀리면 얼굴이 눌린 채로 비교된다.
    tile.style.setProperty("--ar", (c.w * sc.iw) / (c.h * sc.ih));
  }
  const box = document.querySelector('.box[data-scene="' + n + '"]');
  if (box) {
    box.style.setProperty("--cx0", c.x + "%");
    box.style.setProperty("--cy0", c.y + "%");
    box.style.setProperty("--cw0", c.w + "%");
    box.style.setProperty("--ch0", c.h + "%");
    const tag = box.querySelector("b");
    if (tag) tag.textContent = "얼굴 " + Math.round(c.w) + "x" + Math.round(c.h) + "%";
  }
}

function same(a, b) {
  return a && b && Math.abs(a.x - b.x) < 0.05 && Math.abs(a.y - b.y) < 0.05 &&
         Math.abs(a.w - b.w) < 0.05 && Math.abs(a.h - b.h) < 0.05;
}

function countCrop() {
  if (!dirty) return;
  let n = 0;
  META.scenes.forEach(s => {
    const base = META.saved_crops[s.n];
    if (!base) { if (crops[s.n]) n++; }        // 파일에 없던 자리를 새로 잡았다
    else if (!same(cropOf(s.n), base)) n++;
  });
  dirty.textContent = n ? "저장 안 된 얼굴 자리 " + n + "개"
                        : (META.had_crop_file ? "저장된 " + META.crop_file + " 과 같음"
                                              : "얼굴 자리 저장 전 (기본 상자)");
  dirty.style.color = n ? "" : "#7f8798";
}

function setCrop(n, c) {
  const w = Math.min(100, Math.max(META.min_side, c.w));
  const h = Math.min(100, Math.max(META.min_side, c.h));
  crops[n] = {x: Math.min(100 - w, Math.max(0, c.x)),
              y: Math.min(100 - h, Math.max(0, c.y)), w: w, h: h};
  try { localStorage.setItem(CKEY, JSON.stringify(crops)); } catch (e) {}
  paintCrop(n);
  countCrop();
}

/* 빈 곳을 끌면 새 상자, 상자 안을 끌면 이동, 모서리를 끌면 크기 조절 */
let drag = null, rubber = null;

document.addEventListener("pointerdown", e => {
  if (!crop || !crop.checked) return;
  const frameEl = e.target.closest(".sframe");
  if (!frameEl) return;
  const frame = frameEl.getBoundingClientRect();
  if (!frame.width || !frame.height) return;
  const n = frameEl.closest(".row").dataset.scene;

  const box = e.target.closest(".box");
  if (box) {
    drag = {mode: e.target.closest(".grip") ? "size" : "move", n: n, frame: frame,
            start: Object.assign({}, cropOf(n)), sx: e.clientX, sy: e.clientY};
    box.classList.add("drag");
  } else {
    rubber = {n: n, frame: frame, sx: e.clientX, sy: e.clientY,
              box: document.createElement("div")};
    rubber.box.className = "rubber";
    frameEl.appendChild(rubber.box);
  }
  try { e.target.setPointerCapture(e.pointerId); } catch (err) {}
  e.preventDefault();
});

document.addEventListener("pointermove", e => {
  if (drag) {
    const f = drag.frame;
    const dx = (e.clientX - drag.sx) / f.width * 100;
    const dy = (e.clientY - drag.sy) / f.height * 100;
    const s = Object.assign({}, drag.start);
    if (drag.mode === "size") { s.w = drag.start.w + dx; s.h = drag.start.h + dy; }
    else { s.x = drag.start.x + dx; s.y = drag.start.y + dy; }
    setCrop(drag.n, s);
  } else if (rubber) {
    const f = rubber.frame;
    rubber.box.style.cssText =
      "left:" + (Math.min(rubber.sx, e.clientX) - f.left) + "px;" +
      "top:" + (Math.min(rubber.sy, e.clientY) - f.top) + "px;" +
      "width:" + Math.abs(e.clientX - rubber.sx) + "px;" +
      "height:" + Math.abs(e.clientY - rubber.sy) + "px";
  }
});

document.addEventListener("pointerup", e => {
  if (drag) {
    const box = document.querySelector('.box[data-scene="' + drag.n + '"]');
    if (box) box.classList.remove("drag");
    drag = null;
  } else if (rubber) {
    const f = rubber.frame;
    const w = Math.abs(e.clientX - rubber.sx) / f.width * 100;
    const h = Math.abs(e.clientY - rubber.sy) / f.height * 100;
    rubber.box.remove();
    // 손이 미끄러진 정도의 작은 사각형은 상자를 갈아엎지 않는다.
    if (w >= META.min_side && h >= META.min_side) {
      setCrop(rubber.n, {x: (Math.min(rubber.sx, e.clientX) - f.left) / f.width * 100,
                         y: (Math.min(rubber.sy, e.clientY) - f.top) / f.height * 100,
                         w: w, h: h});
    }
    rubber = null;
  }
});

/* --- 채점 (점수 아님 — Y/N) --------------------------------------------------- */
function paintScore(n) {
  const marks = score[n] || {};
  document.querySelectorAll('.it[data-scene="' + n + '"] i').forEach(el => {
    el.classList.toggle("on", marks[el.parentNode.dataset.key] === el.dataset.v);
  });
}

function countScore() {
  if (!tally) return;
  let done = 0;
  const need = META.scenes.length * (META.keys.length);
  META.scenes.forEach(s => {
    const m = score[s.n] || {};
    META.keys.forEach(k => { if (m[k]) done++; });
  });
  tally.textContent = "채점 " + done + "/" + need;
}

document.addEventListener("click", e => {
  const btn = e.target.closest(".it i");
  if (!btn) return;
  const it = btn.parentNode, n = it.dataset.scene, k = it.dataset.key;
  score[n] = score[n] || {};
  if (score[n][k] === btn.dataset.v) delete score[n][k];   // 한 번 더 누르면 해제
  else score[n][k] = btn.dataset.v;
  try { localStorage.setItem(SKEY, JSON.stringify(score)); } catch (e) {}
  paintScore(n);
  countScore();
});

/* --- 내려받기 (서버가 없으므로 picks.csv 와 같은 방식) ------------------------ */
function cropText() {
  const mine = {};
  META.scenes.forEach(s => {
    const c = cropOf(s.n);
    mine["scene" + s.n] = {x: +c.x.toFixed(1), y: +c.y.toFixed(1),
                           w: +c.w.toFixed(1), h: +c.h.toFixed(1)};
  });
  // 다른 이름표(다른 조건 / verify 한 벌)는 읽은 그대로 다시 실어 보낸다.
  const out = Object.assign({}, META.other_crops);
  out[META.cond] = mine;
  // 상자 하나가 네 줄로 늘어지면 사람이 열어 고치기 나쁘다. 한 줄로 붙인다.
  return JSON.stringify(out, null, 2).replace(
    /\\{\\s*"x": ([-\\d.]+),\\s*"y": ([-\\d.]+),\\s*"w": ([-\\d.]+),\\s*"h": ([-\\d.]+)\\s*\\}/g,
    '{"x": $1, "y": $2, "w": $3, "h": $4}') + "\\n";
}

function scoreText() {
  const rows = [META.header.join(",")];
  META.scenes.forEach(s => {
    const m = score[s.n] || {};
    rows.push([s.n].concat(META.keys.map(k => m[k] || "")).join(","));
  });
  return rows.join("\\r\\n") + "\\r\\n";
}

function save(name, text, type) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], {type: type}));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

// 이 스크립트는 verify.html 에도 그대로 실린다. 거기 없는 버튼이 있어도 죽지 않는다.
function on(id, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener("click", fn);
}

on("dlcrop", () => save(META.crop_file, cropText(), "application/json"));
on("dlscore", () => save(META.score_file, "\\ufeff" + scoreText(), "text/csv;charset=utf-8"));
on("resetcrop", () => {
  if (!confirm("얼굴 자리를 저장된 " + META.crop_file + " 상태로 되돌립니다. 계속할까요?")) return;
  crops = {};
  try { localStorage.removeItem(CKEY); } catch (e) {}
  META.scenes.forEach(s => paintCrop(s.n));
  countCrop();
});

/* --- 시작 --------------------------------------------------------------------- */
try {
  const c = JSON.parse(localStorage.getItem(CKEY) || "null");
  if (c && typeof c === "object") crops = c;
} catch (e) { crops = {}; }
try {
  const s = JSON.parse(localStorage.getItem(SKEY) || "null");
  if (s && typeof s === "object") score = s;
} catch (e) { score = {}; }
// 파일에 채워 둔 Y/N 은 브라우저에 아직 아무것도 없을 때만 기준선이 된다.
if (!Object.keys(score).length) score = JSON.parse(JSON.stringify(META.saved_score));
try {
  const v = JSON.parse(localStorage.getItem(VKEY) || "null");
  if (v && typeof v === "object") {
    face.checked = !!v.face; zoom.checked = !!v.zoom; crop.checked = !!v.crop;
  }
} catch (e) {}

apply();
META.scenes.forEach(s => { paintCrop(s.n); paintScore(s.n); });
countCrop();
countScore();
window.addEventListener("resize", fitBar);
window.addEventListener("load", fitBar);
fitBar();
"""


# --------------------------------------------------------------------------- #
def check_rows(n: int, items: list[tuple[str, str, str]], sum_key: str = "",
               sum_hint: str = "") -> str:
    """Scene n 의 Y/N 줄들. data-scene/data-key 로 JS 가 상태를 칠한다.

    같은 항목이 화면 여러 곳(세로 보기 옆 / 얼굴 타일 아래 / 채점 탭)에 나올 수
    있다. 값은 한 군데(META.keys 기준의 score)에 모이므로 어디를 눌러도 같이 켜진다.
    """
    rows = [f'<div class="it" data-scene="{n}" data-key="{_esc(key)}">'
            f'<span>{_esc(label)}<em>{_esc(hint)}</em></span>'
            f'<i data-v="Y">Y</i><i data-v="N">N</i></div>'
            for key, label, hint in items]
    if sum_key:
        rows.append(
            f'<div class="it sum" data-scene="{n}" data-key="{_esc(sum_key)}">'
            f'<span>{_esc(sum_key)}<em>{_esc(sum_hint)}</em></span>'
            f'<i data-v="Y">Y</i><i data-v="N">N</i></div>')
    return "".join(rows)


def _check_html(n: int, compact: bool = False) -> str:
    """Scene 하나의 체크 항목. 세로 보기 옆과 얼굴 타일 아래에 같은 것이 붙는다."""
    head = ("" if compact else
            f'<b>Scene {n} 체크</b>'
            f'<p class="hint">앞 Scene 과 견줘서 같으면 Y, 튀면 N.</p>')
    body = check_rows(n, ITEMS, TOTAL_KEY, "넷 중 하나라도 N 이면 이 Scene 은 N 이다.")
    return f'<div class="chk">{head}{body}</div>'


def build_page(
    ep_dir: Path,
    episode_meta: dict[str, Any],
    condition: str,
    cond_dir: str,
    label: str,
    scenes: list[dict[str, Any]],
    picks: dict[int, int],
    crops: dict[int, dict[str, float]],
    had_crop_file: bool,
    saved_score: dict[int, dict[str, str]],
    opts: dict[str, Any],
) -> tuple[Path, list[int]]:
    """style_lock.html 을 쓰고 (경로, 이미지 없는 Scene) 반환.

    scenes : [{"scene_number", "label", "description"}, ...]
    picks  : {scene_number: candidate} — 이 조건의 채택 기록만
    crops  : style_faces.json 에서 읽은 얼굴 자리 (없는 Scene 은 기본 상자)
    """
    width = int(opts.get("width_px") or 690)
    tiles: list[str] = []
    rows: list[str] = []
    missing: list[int] = []
    meta_scenes: list[dict[str, Any]] = []

    for sc in scenes:
        n = int(sc["scene_number"])
        cand = picks.get(n)
        src = f"{cond_dir}/scene{n}_c{cand}.png" if cand else None
        path = ep_dir / src if src else None
        size = image_size(path) if path is not None and path.exists() else None

        if size is None:
            missing.append(n)
            # 이미지가 없어도 채점 행은 남긴다 — 빈 style_score.csv 에는 이 Scene 도
            # 있는데 내려받은 CSV 에서만 빠지면 두 파일의 행이 어긋난다.
            meta_scenes.append({"n": n, "iw": None, "ih": None})
            why = ("picks.csv 에 채택 기록이 없습니다" if not cand
                   else f"채택 파일이 없습니다 — {src}")
            tiles.append(f'<figure class="tile" data-scene="{n}">'
                         f'<div class="miss">Scene {n}<br>{_esc(why)}</div>'
                         f'<figcaption><b>Scene {n}</b></figcaption></figure>')
            rows.append(
                f'<div class="row" data-scene="{n}"><div class="shot">'
                f'<div class="miss"><div>Scene {n} · {_esc(why)}'
                f'<span class="d">{_esc(sc.get("description"))}</span></div></div>'
                f'</div>{_check_html(n)}</div>')
            continue

        iw, ih = size
        c = crops.get(n, DEFAULT_CROP)
        ar = (c["w"] * iw) / (c["h"] * ih)
        meta_scenes.append({"n": n, "iw": iw, "ih": ih})

        tiles.append(
            f'<figure class="tile" data-scene="{n}">'
            f'<div class="crop" style="--cx: {c["x"]:.1f}; --cy: {c["y"]:.1f}; '
            f'--cw: {c["w"]:.1f}; --ch: {c["h"]:.1f}; --ar: {ar:.4f}">'
            f'<img src="{_esc(src)}" alt="Scene {n} 얼굴" decoding="async"></div>'
            f'<figcaption><b>Scene {n}</b> {_esc(sc.get("label"))} · c{cand}</figcaption>'
            f'{_check_html(n, compact=True)}</figure>')

        rows.append(
            f'<div class="row" data-scene="{n}"><div class="shot"><div class="sframe">'
            f'<img src="{_esc(src)}" alt="Scene {n}" width="{iw}" height="{ih}" '
            f'loading="lazy" decoding="async">'
            f'<div class="no">Scene {n} <i>{_esc(sc.get("label"))} · c{cand}</i></div>'
            f'<div class="box" data-scene="{n}" style="--cx0: {c["x"]:.1f}%; '
            f'--cy0: {c["y"]:.1f}%; --cw0: {c["w"]:.1f}%; --ch0: {c["h"]:.1f}%">'
            f'<b>얼굴</b><i class="grip"></i></div>'
            f'</div></div>{_check_html(n)}</div>')

    widest = max((s["iw"] for s in meta_scenes if s["iw"]), default=width)
    zoom = min(MAX_ZOOM, max(MIN_ZOOM, widest / width))

    meta = json.dumps({
        "run_id": episode_meta.get("run_id"),
        "episode": episode_meta.get("episode"),
        "cond": cond_dir,
        "scenes": meta_scenes,
        "keys": [k for k, _, _ in ITEMS] + [TOTAL_KEY],
        "header": SCORE_HEADER,
        "def_crop": DEFAULT_CROP,
        "min_side": MIN_SIDE,
        "saved_crops": {str(n): crops[n] for n in crops},
        "had_crop_file": had_crop_file,
        "other_crops": other_blocks(ep_dir, cond_dir),
        "saved_score": {str(n): saved_score[n] for n in saved_score},
        "crop_file": CROP_FILE,
        "score_file": SCORE_FILE,
    }, ensure_ascii=False).replace("</", "<\\/")

    shown = len(scenes) - len(missing)
    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>그림체 일관성 {_esc(condition)} — {_esc(episode_meta.get('run_id'))} ep{episode_meta.get('episode')}</title>
<style>{CSS}
:root {{ --w: {width}px; --fh: {FACE_H}px; --z: {zoom:.2f}; }}
</style></head>
<body>
<div class="bar">
  <b>{_esc(episode_meta.get('run_id'))} · {episode_meta.get('episode')}화 「{_esc(episode_meta.get('title'))}」 그림체 일관성</b>
  <span class="cond">조건 {_esc(condition)}{(' — ' + _esc(label)) if label else ''} · Scene {shown}/{len(scenes)}</span>
  <span class="cond"><a href="viewer_scene_{_esc(condition)}.html">Scene 뷰어</a>
    <a href="contact_sheet_scene.html">Scene 시트</a></span>
  <span class="sp"></span>
  <label><input type="checkbox" id="face"> 얼굴만 크롭</label>
  <label><input type="checkbox" id="zoom"> 확대</label>
  <label><input type="checkbox" id="crop"> 크롭 편집</label>
  <span class="edit-only">
    <button class="primary" id="dlcrop">{CROP_FILE} 내려받기</button>
    <button id="resetcrop">되돌리기</button>
    <span class="dirty" id="dirty"></span>
  </span>
  <button id="dlscore">{SCORE_FILE} 내려받기</button>
  <span class="tally" id="tally"></span>
</div>

<section class="faces" id="faces">{"".join(tiles)}</section>
<section class="stack" id="stack">{"".join(rows)}</section>

<footer>
  <p><b>이 화면은 이미지를 만들지 않습니다.</b> 이미 뽑아 둔
     <code>{_esc(cond_dir)}/</code> 의 채택본만 읽습니다 — API 호출 0회, 0원.
     고칠 것이 보이면 그때 다시 뽑으세요.</p>
  <p><b>보는 순서</b></p>
  <ol>
    <li>먼저 세로로 훑습니다. Scene {shown}개가 한 사람 손에서 나온 것으로 보이는지.</li>
    <li><b>얼굴만 크롭</b> 을 켜서 얼굴을 가로로 붙여 놓고 봅니다. 그림체 차이는
        얼굴에서 제일 먼저 드러납니다 — 세로로 떨어져 있으면 눈이 기억으로 비교하지만,
        옆에 두면 눈매 각도와 코 생략 정도가 바로 보입니다.</li>
    <li><b>확대</b> 를 켜서 선 굵기와 채색 질감을 봅니다
        (원본 {widest:,}px 폭 기준 약 {zoom:.1f}배 — 거의 원본 픽셀입니다).</li>
    <li>Scene 옆 체크 항목을 <b>앞 Scene 과 견줘</b> Y/N 으로 표시합니다.
        점수는 매기지 않습니다 — "7점"은 다음에 뭘 고칠지 알려주지 않지만
        "배경밀도 N"은 알려주기 때문입니다.</li>
  </ol>
  <p><b>얼굴 자리는 코드가 모릅니다.</b> 처음 열면 어림잡은 상자가 놓여 있습니다.
     <b>크롭 편집</b> 을 켜고 Scene 이미지 위에 얼굴을 끌어 그리세요 (상자 안을 끌면 이동,
     오른쪽 아래 모서리로 크기 조절). 바꾼 값은 브라우저에 바로 저장되고,
     <b>{CROP_FILE} 내려받기</b> → 이 폴더(<code>{_esc(str(ep_dir))}</code>)에
     <code>{CROP_FILE}</code> 로 저장해야 다음에 다시 만들 때도 남습니다.</p>
  <p><b>채점표</b> · <code>{SCORE_FILE}</code> 는 빈 표로 이미 이 폴더에 있습니다.
     엑셀에서 직접 채워도 되고, 위에서 Y/N 을 누른 뒤
     <b>{SCORE_FILE} 내려받기</b> 로 같은 자리에 덮어써도 됩니다.
     열은 <code>{', '.join(SCORE_HEADER)}</code> 이고 값은 <b>Y 또는 N</b> 입니다.</p>
  <p>{('채택 기록이 없는 Scene: ' + ', '.join(str(n) for n in missing)) if missing
      else 'Scene ' + str(len(scenes)) + '개 모두 picks.csv 에 채택되어 있습니다.'}</p>
  <p>생성 {datetime.now().isoformat(timespec='seconds')}</p>
</footer>
<script>const META = {meta};{JS}</script>
</body></html>
"""
    out = page_path(ep_dir)
    out.write_text(doc, encoding="utf-8")
    return out, missing
