"""viewer_<조건>.html 생성 — 채택된 컷을 세로로 이어 붙인 웹툰 뷰어 + 배치 편집기.

contact_sheet 가 "후보를 나란히 놓고 고르는 표"라면, 이쪽은 "독자가 실제로
보는 화면"이다. picks.csv 의 채택 기록을 컷 번호 순으로 읽어 모바일 폭
(기본 690px)으로 세로 배치한다. 스크롤 리듬 — 컷 길이, 이어짐, 끊김 —
을 눈으로 확인하는 게 목적이다.

이미지는 다시 만들지 않는다. 컷마다 표시 크기(wide/normal/tall/impact)를
layout.json 에서 읽어 그 틀에 object-fit: cover 로 맞춘다. 즉 틀에 안 맞는
부분은 잘린다 — 크기 리듬이 읽히는지만 보는 용도다.

크기는 뷰어 안에서 바로 바꾼다. 서버가 없으므로 picks.csv 와 같은 방식으로 돈다:
  1) 컷 위 [wide|normal|tall|impact] 를 누르면 그 자리에서 다시 배치된다
     (스크롤하다 눈에 걸리는 컷을 바로 고치라고 만든 것이다)
  2) localStorage 에 즉시 저장 — 새로고침하거나 다른 조건 뷰어로 넘어가도 유지
  3) [layout.json 내려받기] → 같은 폴더에 저장
  4) 다시 만들 때 그 layout.json 이 HTML 에 박혀 들어와 기준선이 된다
     (file:// 에서는 JSON 을 fetch 할 수 없기 때문)

말풍선 합성은 아직 없다. 대사는 이미지 아래 캡션으로만 붙는다.
"""

from __future__ import annotations

import html
import json
import re
import struct
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import bubbles

LAYOUT_FILE = "layout.json"
DEFAULT_SIZE = "normal"
SCREEN = "screen"  # 비율 대신 화면 높이를 쓰는 특수값
# 총 높이 어림에 쓸 값. impact 는 뷰포트에 따라 달라지므로 9:16 로 어림잡는다.
SCREEN_RATIO = 9 / 16
# 이보다 납작한 틀은 세로가 많이 잘리므로 위쪽(얼굴)을 남기고 자른다.
FLAT_RATIO = 0.7
# 가벼운 컷(weight: light)이 쓰는 지면 폭. strip.LIGHT_WIDTH 와 같은 값이다 —
# 뷰어와 PNG 가 다른 폭으로 그리면 같은 화가 두 가지로 보인다.
LIGHT_WIDTH = 0.55

CUT_KEY_RE = re.compile(r"^(?:cut)?\s*(\d+)$", re.IGNORECASE)


class LayoutError(RuntimeError):
    """layout.json 이 읽히지 않음. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


def layout_path(ep_dir: Path) -> Path:
    return ep_dir / LAYOUT_FILE


def load_layout(ep_dir: Path, allowed: Iterable[str]) -> tuple[dict[int, str], list[str]]:
    """layout.json → {cut_number: size}. 파일이 없으면 빈 dict (= 전부 normal).

    ("cut3" | "3" | 3) 키를 모두 받아준다. 모르는 크기 이름은 버리고 경고만 남긴다.
    돌려주는 경고는 run.py 가 화면에 찍는다 — 조용히 normal 로 떨어지면
    layout.json 을 고쳐도 왜 안 먹는지 알 수 없다.
    """
    path = layout_path(ep_dir)
    if not path.exists():
        return {}, []
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise LayoutError(f"{LAYOUT_FILE} 을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(raw, dict):
        raise LayoutError(f"{LAYOUT_FILE} 의 최상위는 객체여야 합니다: "
                          f'{{"cut1": "wide", "cut2": "normal", ...}}')

    names = list(allowed)
    layout: dict[int, str] = {}
    warnings: list[str] = []
    for key, value in raw.items():
        if str(key).startswith("_"):  # 주석용 키는 무시한다
            continue
        m = CUT_KEY_RE.match(str(key).strip())
        if not m:
            warnings.append(f'{LAYOUT_FILE}: 컷 키를 알 수 없습니다 → "{key}" '
                            f'(예: "cut3" 또는 "3")')
            continue
        size = str(value or "").strip().lower()
        if size not in names:
            warnings.append(f'{LAYOUT_FILE}: 컷 {m.group(1)} 의 크기 "{value}" 를 모릅니다 '
                            f'→ {DEFAULT_SIZE} 으로 봅니다 (가능: {", ".join(names)})')
            continue
        layout[int(m.group(1))] = size
    return layout, warnings


def parse_sizes(raw: Any) -> dict[str, tuple[str, float]]:
    """config 의 sizes 테이블 → {이름: (CSS aspect-ratio | "screen", 높이 배율)}.

    "16:9" -> ("16/9", 9/16)   # 폭 1 일 때의 높이
    "screen" -> ("screen", SCREEN_RATIO)
    """
    table = raw if isinstance(raw, dict) else {}
    out: dict[str, tuple[str, float]] = {}
    for name, spec in table.items():
        text = str(spec or "").strip().lower()
        if text == SCREEN:
            out[str(name)] = (SCREEN, SCREEN_RATIO)
            continue
        m = re.match(r"^(\d+(?:\.\d+)?)\s*[:/]\s*(\d+(?:\.\d+)?)$", text)
        if not m:
            raise LayoutError(
                f'config.yaml 의 viewer.sizes.{name} 값 "{spec}" 을 알 수 없습니다. '
                f'"16:9" 같은 비율이나 "screen" 이어야 합니다.')
        w, h = float(m.group(1)), float(m.group(2))
        if w <= 0 or h <= 0:
            raise LayoutError(f"config.yaml 의 viewer.sizes.{name} 비율이 0 입니다.")
        out[str(name)] = (f"{m.group(1)}/{m.group(2)}", h / w)
    if DEFAULT_SIZE not in out:
        raise LayoutError(f'config.yaml 의 viewer.sizes 에 "{DEFAULT_SIZE}" 이 없습니다. '
                          f"크기를 지정하지 않은 컷이 쓸 기본값입니다.")
    return out


def image_size(path: Path) -> tuple[int, int] | None:
    """이미지 헤더에서 (폭, 높이). 의존성 없이 PNG/JPEG 만 읽는다. 실패하면 None.

    확장자는 믿지 않는다. 이미지 모델이 JPEG 를 돌려줘도 하네스는 .png 로 저장하기
    때문이다(provider 가 준 바이트를 그대로 쓴다). 매직 넘버로 판별한다.

    Scene 이미지는 틀에 맞춰 자르지 않고 원본 비율 그대로 쌓는다. 크기를 미리
    박아 두지 않으면 이미지가 로드되기 전까지 높이가 0이라, 그 위에 %로 얹은
    말풍선이 전부 맨 위로 뭉치고 스크롤도 튄다.
    """
    try:
        with path.open("rb") as fh:
            head = fh.read(24)
            if head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR":
                w, h = struct.unpack(">II", head[16:24])
                return (w, h) if w and h else None
            if head[:2] != b"\xff\xd8":       # JPEG SOI
                return None
            fh.seek(2)
            while True:
                byte = fh.read(1)
                while byte == b"\xff":        # 세그먼트 사이 채움 바이트
                    byte = fh.read(1)
                if not byte:
                    return None
                marker = byte[0]
                size = fh.read(2)
                if len(size) < 2:
                    return None
                length = struct.unpack(">H", size)[0]
                # SOF0~SOF15 중 DHT(C4)/JPG(C8)/DAC(CC) 은 프레임 헤더가 아니다.
                if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                    body = fh.read(5)
                    if len(body) < 5:
                        return None
                    h, w = struct.unpack(">HH", body[1:5])
                    return (w, h) if w and h else None
                if length < 2:
                    return None
                fh.seek(length - 2, 1)
                if fh.read(1) != b"\xff":     # 다음 마커가 아니면 포기
                    return None
                fh.seek(-1, 1)
    except (OSError, struct.error):
        return None


def _esc(text: Any) -> str:
    return html.escape(str(text or ""))


def _dark(bg: str) -> bool:
    """배경색이 어두운가. 글자색을 뒤집는 데만 쓴다. 이상하면 밝다고 본다."""
    s = str(bg or "").strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) != 6:
        return False
    try:
        r, g, b = (int(s[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return False
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 0.5


CSS = """
:root { --w: 690px; --gap: 0px; --bg: #ffffff; --fg: #16181d;
        --cap-bg: rgba(0,0,0,.05); --cap-line: rgba(0,0,0,.10); --dim: rgba(0,0,0,.45); }
* { box-sizing: border-box; }
/* 세로 스크롤바 자리를 항상 비워 둔다. impact 컷 높이가 100vh 에 걸려 있어서,
   스크롤바가 생겼다 사라졌다 하면 폭 -> 높이 -> 스크롤바로 되먹임이 돌아
   (특히 --mode both 의 두 칸 배치에서) 레이아웃이 무한히 요동친다. */
html { scrollbar-gutter: stable; }
/* --bar 는 JS 가 상단 바 실제 높이로 채운다. 바가 좁은 창에서 두 줄로 접히면
   높이가 달라지므로 고정값을 쓰면 첫 컷 위쪽을 가린다. */
body { margin: 0; padding-top: var(--bar, 40px); background: var(--bg); color: var(--fg);
       font: 14px/1.65 "Malgun Gothic", system-ui, sans-serif;
       -webkit-font-smoothing: antialiased; }

/* --- 상단 바 (읽는 화면을 최대한 덜 가리도록 얇게) ------------------------- */
.bar { position: fixed; top: 0; left: 0; right: 0; z-index: 10; display: flex;
       align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 14px;
       font-size: 12.5px; line-height: 1.4; color: #e6e8ee;
       background: rgba(18,20,26,.90); backdrop-filter: blur(6px); }
.bar .cond { color: #9aa2b4; }
.bar .sp { flex: 1 1 auto; }
.bar label { display: flex; align-items: center; gap: 5px; cursor: pointer;
             user-select: none; white-space: nowrap; }
.bar input[type=range] { width: 100px; }
.bar a { color: #9dc0ff; text-decoration: none; }
.bar a:hover { text-decoration: underline; }
.bar button { font: inherit; color: #e6e8ee; background: #2b313d; cursor: pointer;
              border: 1px solid #3f4756; border-radius: 5px; padding: 4px 9px; }
.bar button:hover { background: #39414f; }
.bar button.primary { background: #2f6fed; border-color: #2f6fed; color: #fff;
                      font-weight: 600; }
.edit-only { display: none; align-items: center; gap: 8px; }
body.edit .edit-only { display: flex; }
.dirty { color: #ffc75a; }
.pos { font-variant-numeric: tabular-nums; color: #9aa2b4; min-width: 112px;
       text-align: right; }
.progress { position: absolute; left: 0; bottom: 0; height: 2px; width: 0;
            background: #2f6fed; transition: width .08s linear; }

/* --- 컷 띠 ------------------------------------------------------------------ */
.strip { width: var(--w); max-width: 100%; margin: 0 auto; }
.cut { position: relative; margin-bottom: var(--gap); }
.cut:last-child { margin-bottom: 0; }

/* 틀이 크기를 정하고 이미지는 그 안에서 잘린다. 이미지는 재생성하지 않는다. */
.frame { position: relative; width: 100%; aspect-ratio: var(--ar); overflow: hidden; }
/* impact: 상단 바를 뺀 '실제로 보이는' 화면 높이를 가득 채운다. */
.frame.screen { aspect-ratio: auto; height: calc(100vh - var(--bar, 40px)); }
@supports (height: 100dvh) {
  .frame.screen { height: calc(100dvh - var(--bar, 40px)); }
}
/* display:block + vertical-align 로 인라인 여백 제거. 간격 0px 이 진짜 0px 이어야 한다. */
.frame img { display: block; vertical-align: bottom; width: 100%; height: 100%;
             object-fit: cover; object-position: var(--pos, center);
             background: rgba(127,127,127,.10); }
body.fit-contain .frame img { object-fit: contain; background: rgba(127,127,127,.16); }

.no { position: absolute; top: 8px; left: 8px; z-index: 2; pointer-events: none;
      font: 700 11px/1 ui-monospace, "Consolas", monospace; letter-spacing: .03em;
      padding: 4px 7px; border-radius: 4px; background: rgba(18,20,26,.62); color: #fff; }
.no i { font-style: normal; opacity: .72; font-weight: 400; }

/* --- 컷 크기 편집 ----------------------------------------------------------- */
.pick { position: absolute; top: 8px; right: 8px; z-index: 3; display: none; gap: 3px; }
body.edit .pick { display: flex; }
.pick button { font: 600 11px/1 ui-monospace, "Consolas", monospace; padding: 6px 7px;
               color: #dfe3ec; background: rgba(18,20,26,.66); cursor: pointer;
               border: 1px solid rgba(255,255,255,.20); border-radius: 4px; }
.pick button:hover { background: rgba(18,20,26,.92); }
.pick button.on { background: #2f6fed; border-color: #2f6fed; color: #fff; }
.cut.flash::after { content: ""; position: absolute; inset: 0; z-index: 4;
                    pointer-events: none; outline: 3px solid #2f6fed; outline-offset: -3px;
                    animation: fade .5s ease-out forwards; }
@keyframes fade { to { opacity: 0; } }

.cap { padding: 10px 16px; font-size: 13.5px; white-space: pre-wrap;
       background: var(--cap-bg); border-top: 1px solid var(--cap-line); }
.cap .rtag { display: inline-block; font-size: 10.5px; font-weight: 700; padding: 1px 6px;
             border-radius: 999px; background: #ffe9b8; color: #6b4b00; margin-right: 6px;
             vertical-align: 1px; }
.cap.reader { color: var(--dim); font-style: italic; }
body.hide-cap .cap { display: none; }
body.hide-no .no { display: none; }

.frame.miss { display: flex; align-items: center; justify-content: center; text-align: center;
              padding: 24px; color: var(--dim); font-size: 13px;
              border: 2px dashed var(--cap-line); background: var(--cap-bg); }
.frame.miss .d { display: block; margin-top: 8px; font-size: 12px; opacity: .85; }

/* --- Scene 모드: 한 장이 곧 한 페이지다. 자르지 않고 원본 비율로 쌓는다. ---- */
.scene { position: relative; margin-bottom: var(--gap); }
.scene:last-child { margin-bottom: 0; }
.sframe { position: relative; }
.scene img { display: block; vertical-align: bottom; width: 100%; height: auto;
             background: rgba(127,127,127,.10); }

/* --- 말풍선 글자: 말풍선 그림은 이미지 안에 있고 여기서는 글자만 얹는다 ----- */
/* 좌표는 전부 이미지 대비 %. 창 크기가 바뀌어도 그려진 말풍선 안에 남는다. */
.sframe { container-type: inline-size; }
/* 말풍선은 대개 타원이다. 좌우 여백을 위아래보다 크게 잡아야 글자 모서리가
   타원 선을 넘지 않는다 (padding 의 % 는 가로세로 모두 폭 기준이라 값이 곧 비율). */
.tx { position: absolute; left: var(--x); top: var(--y); width: var(--w); height: var(--h);
      z-index: 3; display: flex; align-items: center; justify-content: center;
      padding: 2.5% 11%; overflow: hidden; color: #111; text-align: center; }
.tx .t { display: block; width: 100%;
         font-family: "Nanum Gothic", "Malgun Gothic", "Apple SD Gothic Neo",
                      system-ui, sans-serif;
         font-size: 2.1cqw;  /* JS 가 영역에 맞춰 다시 잡는다. 이건 최초값일 뿐 */
         font-weight: 700; line-height: 1.3; letter-spacing: -.02em;
         /* 한국어는 어절 단위로 끊는다. break-word 를 주면 어절 중간에서 잘린다. */
         word-break: keep-all; overflow-wrap: normal; white-space: pre-wrap; }
body.hide-bub .tx { display: none; }
/* 최소 크기로도 안 들어가면 영역을 키우거나 대사를 줄이라는 신호를 준다. */
.tx.over { outline: 2px solid #d33; background: rgba(221,51,51,.10); }
body.bedit .tx.over { outline: 2px solid #d33; }

/* 편집할 때만 영역이 보인다. 읽을 때는 글자만 떠 있다. */
.tx { cursor: default; }
body.bedit .tx { cursor: grab; outline: 1px dashed rgba(47,111,237,.85); outline-offset: 0;
                 background: rgba(47,111,237,.06); }
body.bedit .tx.drag { cursor: grabbing; outline: 2px solid #2f6fed; }
body.bedit .tx .t[contenteditable="true"] { outline: none; cursor: text; }
.grip { display: none; position: absolute; right: -6px; bottom: -6px; width: 13px;
        height: 13px; border: 2px solid #2f6fed; border-radius: 3px; background: #fff;
        cursor: nwse-resize; }
.del { display: none; position: absolute; right: -8px; top: -9px; width: 17px; height: 17px;
       border-radius: 50%; background: #d33; color: #fff; cursor: pointer;
       font: 700 12px/16px ui-monospace, monospace; text-align: center; }
/* 글자 크기 수동 조정. auto 는 자동 핏으로 되돌린다. */
.fs { display: none; position: absolute; left: 0; bottom: -19px; gap: 2px; }
body.bedit .fs { display: flex; }
.fs b { font: 700 10px/15px ui-monospace, "Consolas", monospace; min-width: 16px;
        height: 16px; text-align: center; color: #fff; background: rgba(18,20,26,.72);
        border-radius: 3px; cursor: pointer; padding: 0 3px; user-select: none; }
.fs b:hover { background: #2f6fed; }
.fs b.now { background: transparent; color: #2f6fed; cursor: default; }
.tx[data-fs] .fs b.now { color: #ffc75a; }
.cutno { display: none; position: absolute; left: 0; top: -17px;
         font: 700 10px/1 ui-monospace, "Consolas", monospace; color: #fff;
         background: rgba(18,20,26,.72); padding: 3px 5px; border-radius: 3px;
         white-space: nowrap; }
body.bedit .grip, body.bedit .del, body.bedit .cutno { display: block; }

/* 새 영역을 끌어 그릴 때의 고무줄 */
.rubber { position: absolute; z-index: 4; border: 2px dashed #2f6fed;
          background: rgba(47,111,237,.12); pointer-events: none; }
body.bedit .sframe { cursor: crosshair; }
.queue { color: #ffc75a; max-width: 42ch; overflow: hidden; text-overflow: ellipsis;
         white-space: nowrap; }
.scene .miss { display: flex; align-items: center; justify-content: center; text-align: center;
               aspect-ratio: 3/4; padding: 24px; color: var(--dim); font-size: 13px;
               border: 2px dashed var(--cap-line); background: var(--cap-bg); }
.scene .miss .d { display: block; margin-top: 8px; font-size: 12px; opacity: .85; }

/* --- 두 모드 나란히 비교 (--mode both) -------------------------------------- */
.cols { display: flex; gap: 18px; justify-content: center; align-items: flex-start;
        padding: 0 12px; }
.col { flex: 0 1 var(--w); min-width: 0; }
.colhead { position: sticky; top: var(--bar, 40px); z-index: 6; padding: 7px 10px;
           text-align: center; font-size: 12.5px; font-weight: 700;
           background: var(--cap-bg); border-bottom: 1px solid var(--cap-line); }
.colhead span { font-weight: 400; color: var(--dim); }
.mark { padding: 5px 10px; font: 700 11px/1.4 ui-monospace, "Consolas", monospace;
        color: var(--dim); background: var(--cap-bg);
        border-top: 1px dashed var(--cap-line); border-bottom: 1px dashed var(--cap-line); }
body.hide-no .mark { display: none; }

/* --- 연출 여백 (W7.5 의 gap_after) ------------------------------------------
   컷 사이의 빈 곳이다. 여기서 독자는 잠깐 혼자가 되고, 다음 컷을 스스로 예상한다.
   [연출 여백] 을 끄면 전부 사라진다 — 같은 그림으로 있고/없고를 바로 비교하려고
   따로 두었다. 여백이 진짜 여백이려면 배경 말고 아무것도 없어야 한다. */
.gapx { width: 100%; position: relative; }
body.no-dgap .gapx { display: none; }
.gapx b { position: absolute; left: 0; top: 50%; transform: translateY(-50%);
          font: 700 10px/1 ui-monospace, "Consolas", monospace; letter-spacing: .04em;
          color: var(--dim); opacity: .55; padding: 3px 6px; border-radius: 3px;
          background: var(--cap-bg); }
body.hide-no .gapx b { display: none; }
.gapx.lv0 b { display: none; }

/* --- 스크롤 폴드 눈금 -------------------------------------------------------
   폴드는 독자의 화면이 끝나는 자리다. 엄지가 멈추는 곳이 늘 거기라서, 그 선
   바로 아래에 무엇이 오는지가 "다음도 볼까"를 정한다. 웹툰 작법이 말하는 것도
   그것이다 — 폴드에서 평평한 대사 컷을 만나면 독자가 빠져나가고, 리빌이나
   임팩트를 만나면 계속 내려간다.
   눈금은 **그림 위에 겹쳐 그리는 자**일 뿐이라 화의 내용을 바꾸지 않는다.
   기본은 꺼짐이다 — 켜야 보인다. */
.strip { position: relative; }
.fold { position: absolute; left: 0; right: 0; height: 0; pointer-events: none;
        border-top: 1px dashed color-mix(in srgb, var(--fg, #111) 45%, transparent);
        z-index: 4; display: none; }
body.show-fold .fold { display: block; }
.fold b { position: absolute; right: 4px; top: 3px; font: 700 10px/1 ui-monospace,
          "Consolas", monospace; letter-spacing: .04em; padding: 3px 6px;
          border-radius: 3px; background: var(--cap-bg); color: var(--dim); }

/* 무게 — 가벼운 컷(float)은 지면을 덜 먹는다. 배경이 없어서 좁혀도 잘릴 것이
   없고, 좁다는 것 자체가 "이 컷은 스쳐 가는 컷"이라는 신호다.
   weight 가 없는 옛 화는 전부 normal 로 읽혀 예전처럼 꽉 찬다. */
.cut.w-light { width: 55%; margin-left: auto; margin-right: auto; }
.cut.w-light .frame { background: var(--cap-bg); }
.cut .wt { display: none; }
.cut.w-light .wt, .cut.w-full .wt { display: inline-block; margin-left: 6px; opacity: .7; }
body.hide-no .cut .wt { display: none; }

/* 앞 컷에서 배경이 이어지는 컷. 두 컷이 한 공간의 위/아래라는 표시다. */
.cut .link { display: none; }
.cut.linked .link { display: inline-block; margin-left: 6px; opacity: .75; }
body.hide-no .cut .link { display: none; }

footer { width: var(--w); max-width: 100%; margin: 0 auto; padding: 28px 16px 56px;
         font-size: 12.5px; color: var(--dim); }
body.compare footer { width: auto; max-width: 1420px; }
footer ol { margin: 4px 0 0; padding-left: 20px; }
footer li { margin-bottom: 3px; }
footer p { margin: 0 0 6px; }
footer code { background: var(--cap-bg); padding: 1px 5px; border-radius: 4px; }
footer kbd { font: 600 11px/1.4 ui-monospace, "Consolas", monospace; padding: 2px 5px;
             border: 1px solid var(--cap-line); border-radius: 4px; background: var(--cap-bg); }
"""

JS = """
const root = document.documentElement, body = document.body;
const KEY = "webtoon-viewer:" + META.run_id + ":ep" + META.episode;
// 배치는 화 단위다(조건별이 아니다). 조건 뷰어 사이를 오가도 같은 배치를 본다.
const LKEY = "webtoon-layout:" + META.run_id + ":ep" + META.episode;

const cap = document.getElementById("cap"), num = document.getElementById("num"),
      fit = document.getElementById("fit"), edit = document.getElementById("edit"),
      gap = document.getElementById("gap"), gapv = document.getElementById("gapv"),
      prog = document.getElementById("prog"), pos = document.getElementById("pos"),
      dirty = document.getElementById("dirty"), bar = document.querySelector(".bar");
// 연출 여백 토글. 연출본이 아닌 뷰어에는 없다 — 그때는 null 로 두고 전부 건너뛴다.
const dgap = document.getElementById("dgap");
const foldbox = document.getElementById("fold");

/* --- 스크롤 폴드 눈금 -------------------------------------------------------
   화면 하나 높이마다 띠 위에 선을 하나 긋고 번호를 붙인다. 독자의 엄지가 멈추는
   자리가 늘 그 선이라, "몇 번째 화면에서 무엇을 보게 되는가"를 눈으로 확인하려는
   것이다. 화면 높이는 창 크기에서 오므로 창을 줄이면 눈금도 따라 움직인다 —
   폰과 데스크톱에서 폴드가 다른 자리에 떨어지는 것을 그대로 보여 준다.
   선은 겹쳐 그리는 자일 뿐이라 컷의 배치를 건드리지 않는다. */
const stripEl = document.querySelector(".strip");
function drawFolds() {
  if (!stripEl || !foldbox) return;
  stripEl.querySelectorAll(".fold").forEach(el => el.remove());
  if (!foldbox.checked) return;
  const screen = Math.max(200, window.innerHeight - (bar ? bar.offsetHeight : 0));
  const total = stripEl.scrollHeight;
  const frag = document.createDocumentFragment();
  // 화면 하나를 넘기지 못하는 짧은 화에는 그을 선이 없다.
  for (let y = screen, i = 2; y < total && i < 400; y += screen, i++) {
    const line = document.createElement("div");
    line.className = "fold";
    line.style.top = y + "px";
    line.innerHTML = "<b>화면 " + i + "</b>";
    frag.appendChild(line);
  }
  stripEl.appendChild(frag);
}
const cuts = Array.prototype.slice.call(document.querySelectorAll(".cut"));
const names = META.order;

let layout = {};    // {컷번호(문자열): 크기}

// 화면 한가운데에 걸린 컷. 숫자키 편집이 "지금 보고 있는 컷"을 바로 잡아야 하므로
// 스크롤 표시용 값을 재활용하지 않고 그때그때 계산한다.
function centerCut() {
  const mid = window.innerHeight / 2;
  let cur = cuts[0] || null;
  for (const el of cuts) { if (el.getBoundingClientRect().top <= mid) cur = el; }
  return cur;
}

// 고정 바가 첫 컷을 가리지 않도록 실제 높이를 --bar 로 넘긴다. impact 컷 높이도 여기 걸린다.
// 값이 그대로면 쓰지 않는다 — resize 마다 다시 쓰면 레이아웃이 무효화되어 되먹임이 돈다.
function fitBar() {
  const h = bar.offsetHeight + "px";
  if (root.style.getPropertyValue("--bar") !== h) root.style.setProperty("--bar", h);
}

function sizeOf(n) { return layout[n] || META.saved[n] || META.def; }

/* --- 보기 설정 (대사/컷번호/잘라채우기/간격/편집) --------------------------- */
function apply() {
  body.classList.toggle("hide-cap", !cap.checked);
  body.classList.toggle("hide-no", !num.checked);
  body.classList.toggle("fit-contain", !fit.checked);
  body.classList.toggle("edit", edit.checked);
  if (dgap) body.classList.toggle("no-dgap", !dgap.checked);
  if (foldbox) { body.classList.toggle("show-fold", foldbox.checked); drawFolds(); }
  root.style.setProperty("--gap", gap.value + "px");
  gapv.textContent = gap.value + "px";
  fitBar();
}

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify({cap: cap.checked, num: num.checked,
      fit: fit.checked, edit: edit.checked, gap: gap.value,
      dgap: dgap ? dgap.checked : null,
      fold: foldbox ? foldbox.checked : null}));
  } catch (e) {}
}

function load() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { s = null; }
  if (s && typeof s === "object") {
    cap.checked = s.cap !== false;
    num.checked = s.num !== false;
    fit.checked = s.fit !== false;
    edit.checked = s.edit !== false;
    if (s.gap != null) gap.value = s.gap;
    if (dgap && s.dgap != null) dgap.checked = s.dgap !== false;
    // 폴드 눈금은 기본이 꺼짐이다 — 켜 둔 적이 있을 때만 켜진 채로 돌아온다.
    if (foldbox && s.fold != null) foldbox.checked = s.fold === true;
  }
  apply();
}

[cap, num, fit, edit, gap, dgap, foldbox].filter(Boolean).forEach(el =>
  el.addEventListener("input", () => { apply(); save(); }));

/* --- 배치 ------------------------------------------------------------------- */
function paint(el) {
  const n = el.dataset.cut, size = sizeOf(n), spec = META.sizes[size] || {};
  const frame = el.querySelector(".frame");
  el.dataset.size = size;
  frame.classList.toggle("screen", !!spec.screen);
  frame.style.setProperty("--ar", spec.ar || "");
  frame.style.setProperty("--pos", spec.flat ? "center 38%" : "");
  const tag = el.querySelector(".no i");
  if (tag) tag.textContent = size;
  el.querySelectorAll(".pick button").forEach(b =>
    b.classList.toggle("on", b.dataset.size === size));
}

function countChanged() {
  return cuts.filter(el => sizeOf(el.dataset.cut) !==
                           (META.saved[el.dataset.cut] || META.def)).length;
}

function paintAll() {
  cuts.forEach(paint);
  const n = countChanged();
  dirty.textContent = n ? "저장 안 된 변경 " + n + "컷" : "저장된 layout.json 과 같음";
  dirty.style.color = n ? "" : "#7f8798";
  onScroll();
}

function setSize(el, size) {
  if (!META.sizes[size]) return;
  layout[el.dataset.cut] = size;
  try { localStorage.setItem(LKEY, JSON.stringify(layout)); } catch (e) {}
  const before = el.getBoundingClientRect().top;
  paintAll();
  // 크기가 바뀌면 그 컷이 화면에서 밀린다. 보던 위치를 그대로 유지한다.
  window.scrollBy(0, el.getBoundingClientRect().top - before);
  el.classList.remove("flash");
  void el.offsetWidth;
  el.classList.add("flash");
}

document.addEventListener("click", e => {
  const btn = e.target.closest(".pick button");
  if (btn) setSize(btn.closest(".cut"), btn.dataset.size);
});

// 스크롤하다 눈에 걸리는 컷을 숫자키로 바로 고친다 (편집 모드에서만).
document.addEventListener("keydown", e => {
  if (!edit.checked || e.metaKey || e.ctrlKey || e.altKey) return;
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName)) return;
  const i = parseInt(e.key, 10) - 1;
  const cur = centerCut();
  if (i >= 0 && i < names.length && cur) { setSize(cur, names[i]); e.preventDefault(); }
});

/* --- layout.json 저장 규약 (서버가 없으므로 picks.csv 와 같은 방식) --------- */
function layoutText() {
  const lines = cuts.map(el => '  "cut' + el.dataset.cut + '": "' + sizeOf(el.dataset.cut) + '"');
  return "{\\n" + lines.join(",\\n") + "\\n}\\n";
}

document.getElementById("download").addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([layoutText()], {type: "application/json"}));
  a.download = "layout.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
});

document.getElementById("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(layoutText());
        alert("layout.json 내용을 클립보드에 복사했습니다."); }
  catch (e) { window.prompt("복사해서 layout.json 으로 저장하세요:", layoutText()); }
});

document.getElementById("revert").addEventListener("click", () => {
  if (!confirm("저장된 layout.json 상태로 되돌립니다. 계속할까요?")) return;
  layout = {};
  try { localStorage.removeItem(LKEY); } catch (e) {}
  paintAll();
});

/* --- 스크롤 위치 표시 ------------------------------------------------------- */
let ticking = false;
function onScroll() {
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(() => {
    ticking = false;
    const max = root.scrollHeight - window.innerHeight;
    prog.style.width = (max > 0 ? Math.min(1, window.scrollY / max) * 100 : 0) + "%";
    const cur = centerCut();
    if (!cur) return;
    pos.textContent = "컷 " + cur.dataset.cut + " " + cur.dataset.size +
                      " (" + (cuts.indexOf(cur) + 1) + "/" + cuts.length + ")";
  });
}
window.addEventListener("scroll", onScroll, {passive: true});
window.addEventListener("resize", () => { fitBar(); onScroll(); drawFolds(); });
// 그림이 lazy 로 들어오면서 띠 높이가 늘어난다 — 다 들어온 뒤에 눈금을 다시 긋는다.
window.addEventListener("load", () => { fitBar(); onScroll(); drawFolds(); });

try {
  const stored = JSON.parse(localStorage.getItem(LKEY) || "null");
  if (stored && typeof stored === "object") layout = stored;
} catch (e) { layout = {}; }

load();
paintAll();
fitBar();
"""


SCENE_JS = """
const root = document.documentElement, body = document.body;
const KEY = "webtoon-viewer-scene:" + META.run_id + ":ep" + META.episode;
// 말풍선 위치는 화 단위다(조건별이 아니다). 조건 뷰어를 오가도 같은 배치를 본다.
const BKEY = "webtoon-bubbles:" + META.run_id + ":ep" + META.episode;
const cap = document.getElementById("cap"), num = document.getElementById("num"),
      show = document.getElementById("bub"), bedit = document.getElementById("bedit"),
      gap = document.getElementById("gap"), gapv = document.getElementById("gapv"),
      prog = document.getElementById("prog"), pos = document.getElementById("pos"),
      dirty = document.getElementById("dirty"), queue = document.getElementById("queue"),
      over = document.getElementById("over"), bar = document.querySelector(".bar");
// 연출 여백 토글. 연출본이 아닌 뷰어에는 없다 — 그때는 null 로 두고 전부 건너뛴다.
const dgap = document.getElementById("dgap");
const scenes = Array.prototype.slice.call(document.querySelectorAll(".scene"));

function fitBar() {
  const h = bar.offsetHeight + "px";
  if (root.style.getPropertyValue("--bar") !== h) root.style.setProperty("--bar", h);
}

function apply() {
  body.classList.toggle("hide-cap", !cap.checked);
  body.classList.toggle("hide-no", !num.checked);
  body.classList.toggle("hide-bub", !show.checked);
  body.classList.toggle("bedit", bedit.checked && show.checked);
  if (dgap) body.classList.toggle("no-dgap", !dgap.checked);
  root.style.setProperty("--gap", gap.value + "px");
  gapv.textContent = gap.value + "px";
  fitBar();
}

function save() {
  try { localStorage.setItem(KEY, JSON.stringify(
    {cap: cap.checked, num: num.checked, bub: show.checked,
     bedit: bedit.checked, gap: gap.value,
     dgap: dgap ? dgap.checked : null})); } catch (e) {}
}

function load() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { s = null; }
  if (s && typeof s === "object") {
    cap.checked = s.cap !== false;
    num.checked = s.num !== false;
    show.checked = s.bub !== false;
    bedit.checked = s.bedit === true;
    if (s.gap != null) gap.value = s.gap;
    if (dgap && s.dgap != null) dgap.checked = s.dgap !== false;
  }
  apply();
}

[cap, num, show, bedit, gap, dgap].filter(Boolean).forEach(el =>
  el.addEventListener("input", () => { apply(); save(); }));

/* --- 말풍선 글자 얹기 ------------------------------------------------------- */
// 말풍선 그림은 이미지 안에 있다. 여기서 다루는 것은 "글자를 놓을 사각형" 뿐이다.
function key(el) { return el.closest(".scene").dataset.scene + "|" + el.dataset.cut; }
function all() { return Array.prototype.slice.call(document.querySelectorAll(".tx")); }

function state(el) {
  return {x: parseFloat(el.style.getPropertyValue("--x")),
          y: parseFloat(el.style.getPropertyValue("--y")),
          w: parseFloat(el.style.getPropertyValue("--w")),
          h: parseFloat(el.style.getPropertyValue("--h")),
          fs: el.dataset.fs ? parseFloat(el.dataset.fs) : null,
          text: el.querySelector(".t").textContent};
}

function put(el, s) {
  el.style.setProperty("--x", s.x.toFixed(1) + "%");
  el.style.setProperty("--y", s.y.toFixed(1) + "%");
  el.style.setProperty("--w", s.w.toFixed(1) + "%");
  el.style.setProperty("--h", s.h.toFixed(1) + "%");
  if (s.text != null) el.querySelector(".t").textContent = s.text;
  if (s.fs === null || s.fs === undefined) delete el.dataset.fs;
  else el.dataset.fs = s.fs;
  refit(el);
}

// 영역 안쪽(패딩 제외)의 실제 여유 공간.
function box(el) {
  const cs = getComputedStyle(el);
  return {w: el.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight),
          h: el.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)};
}

function fits(t, b) {
  return t.scrollWidth <= b.w + 1 && t.scrollHeight <= b.h + 1;
}

/* 영역에 맞는 가장 큰 글자 크기를 이분 탐색으로 찾는다. 말풍선마다 크기가
   다르므로 한 값으로 고정할 수 없다. MIN 아래로는 내려가지 않고, 그래도 넘치면
   영역을 빨갛게 칠해 사람에게 넘긴다 (영역을 키우든 대사를 줄이든 사람 판단). */
function refit(el) {
  const t = el.querySelector(".t");
  const b = box(el);
  if (b.h <= 0 || b.w <= 0) return;                 // 아직 그림 크기가 안 잡혔다
  let size;
  if (el.dataset.fs) {
    size = Math.min(META.max_fs, Math.max(META.min_fs, parseFloat(el.dataset.fs)));
  } else {
    let lo = META.min_fs, hi = META.max_fs, best = META.min_fs;
    t.style.fontSize = lo + "px";
    if (fits(t, b)) {
      for (let i = 0; i < 8; i++) {
        const mid = (lo + hi) / 2;
        t.style.fontSize = mid + "px";
        if (fits(t, b)) { best = mid; lo = mid; } else { hi = mid; }
      }
    }
    size = best;
  }
  t.style.fontSize = size.toFixed(1) + "px";
  el.classList.toggle("over", !fits(t, b));
  const now = el.querySelector(".fs .now");
  if (now) now.textContent = Math.round(size);
}

function refitAll() { all().forEach(refit); overLabel(); }

function overLabel() {
  if (!over) return;
  const n = all().filter(el => el.classList.contains("over")).length;
  over.textContent = n ? "넘침 " + n + "개" : "";
}

function source(sceneNum, cut) {
  const line = (META.lines[sceneNum] || []).filter(l => l.cut === +cut)[0];
  return line ? line.text : "";
}

function make(scene, cut, text, s) {
  const el = document.createElement("div");
  el.className = "tx";
  el.dataset.cut = cut;
  el.dataset.source = source(scene.dataset.scene, cut);   // 고쳤는지 비교할 원본
  el.innerHTML = '<span class="cutno"></span><span class="t"></span>' +
                 '<span class="fs"><b data-d="-1">\\u2212</b><b class="now"></b>' +
                 '<b data-d="1">+</b><b data-d="0">auto</b></span>' +
                 '<i class="grip"></i><i class="del">\\u00d7</i>';
  el.querySelector(".cutno").textContent = "컷 " + cut;
  el.querySelector(".t").textContent = text;
  scene.querySelector(".sframe").appendChild(el);
  put(el, s);
  return el;
}

function pending(sceneEl) {
  const n = sceneEl.dataset.scene;
  const have = {};
  sceneEl.querySelectorAll(".tx").forEach(el => { have[el.dataset.cut] = 1; });
  return (META.lines[n] || []).filter(l => !have[l.cut]);
}

function queueLabel() {
  if (!queue) return;
  const left = scenes.reduce((a, sc) => a + pending(sc).length, 0);
  if (!left) { queue.textContent = "모든 대사 배치됨"; queue.style.color = "#7f8798"; return; }
  let next = null, scn = null;
  for (const sc of scenes) {
    const p = pending(sc);
    if (p.length) { next = p[0]; scn = sc.dataset.scene; break; }
  }
  queue.textContent = "배치 대기 " + left + "개 · 다음 Scene " + scn + " 컷 " +
                      next.cut + ": " + next.text;
  queue.style.color = "";
}

function store() {
  const out = {};
  all().forEach(el => { out[key(el)] = state(el); });
  try { localStorage.setItem(BKEY, JSON.stringify(out)); } catch (e) {}
  countDirty();
  queueLabel();
  overLabel();
}

function countDirty() {
  if (!dirty) return;
  const now = all();
  let n = 0;
  now.forEach(el => {
    const s = state(el), b = META.saved[key(el)];
    if (!b) { n++; return; }                                  // 새로 그린 영역
    if (Math.abs(s.x - b.x) > 0.05 || Math.abs(s.y - b.y) > 0.05 ||
        Math.abs(s.w - b.w) > 0.05 || Math.abs(s.h - b.h) > 0.05 ||
        s.text.trim() !== b.text.trim() ||
        (s.fs || 0) !== (b.fs || 0)) n++;
  });
  n += Object.keys(META.saved).filter(k =>                    // 지운 영역
    !now.some(el => key(el) === k)).length;
  dirty.textContent = n ? "저장 안 된 변경 " + n + "개"
                        : (META.had_file ? "저장된 bubbles.json 과 같음" : "저장 전");
  dirty.style.color = n ? "" : "#7f8798";
}

function restore() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(BKEY) || "null"); } catch (e) { s = null; }
  if (s && typeof s === "object" && Object.keys(s).length) {
    all().forEach(el => el.remove());
    Object.keys(s).forEach(k => {
      const v = s[k], parts = k.split("|");
      const sc = document.getElementById("scene" + parts[0]);
      if (!sc || !v || !isFinite(v.x) || !isFinite(v.y) || !isFinite(v.w) || !isFinite(v.h)) return;
      make(sc, +parts[1], String(v.text == null ? "" : v.text),
           {x: +v.x, y: +v.y, w: +v.w, h: +v.h, fs: isFinite(v.fs) ? +v.fs : null});
    });
  }
  refitAll();
  countDirty();
  queueLabel();
}

/* 빈 곳을 끌면 새 영역, 영역 안을 끌면 이동, 모서리를 끌면 크기 조절 */
let drag = null, rubber = null;

document.addEventListener("pointerdown", e => {
  if (!body.classList.contains("bedit")) return;
  if (e.target.closest(".t[contenteditable='true']")) return;
  const frameEl = e.target.closest(".sframe");
  if (!frameEl) return;
  const frame = frameEl.getBoundingClientRect();
  if (!frame.width || !frame.height) return;

  if (e.target.closest(".del")) {                    // 지우기
    const el = e.target.closest(".tx");
    el.remove();
    store();
    e.preventDefault();
    return;
  }

  const fsBtn = e.target.closest(".fs b[data-d]");   // 글자 크기 수동 조정
  if (fsBtn) {
    const el = fsBtn.closest(".tx"), d = +fsBtn.dataset.d;
    const t = el.querySelector(".t");
    if (d === 0) delete el.dataset.fs;               // auto = 자동 핏으로 복귀
    else el.dataset.fs = Math.min(META.max_fs, Math.max(META.min_fs,
           (parseFloat(el.dataset.fs) || parseFloat(t.style.fontSize) || META.min_fs) + d));
    refit(el);
    store();
    e.preventDefault();
    return;
  }

  const el = e.target.closest(".tx");
  if (el) {
    drag = {mode: e.target.closest(".grip") ? "size" : "move", el: el, frame: frame,
            start: state(el), sx: e.clientX, sy: e.clientY};
    el.classList.add("drag");
  } else {                                            // 새 영역 그리기
    const sceneEl = frameEl.closest(".scene");
    if (!pending(sceneEl).length) { queueLabel(); return; }
    rubber = {frame: frame, scene: sceneEl, sx: e.clientX, sy: e.clientY,
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
    if (drag.mode === "size") {
      s.w = Math.min(META.max_w, Math.max(META.min_w, drag.start.w + dx));
      s.h = Math.min(META.max_h, Math.max(META.min_h, drag.start.h + dy));
      s.w = Math.min(s.w, 100 - s.x);
      s.h = Math.min(s.h, 100 - s.y);
    } else {
      s.x = Math.min(100 - s.w, Math.max(0, drag.start.x + dx));
      s.y = Math.min(100 - s.h, Math.max(0, drag.start.y + dy));
    }
    put(drag.el, s);
  } else if (rubber) {
    const f = rubber.frame;
    const x = Math.min(rubber.sx, e.clientX) - f.left, y = Math.min(rubber.sy, e.clientY) - f.top;
    rubber.box.style.cssText = "left:" + x + "px; top:" + y + "px; width:" +
      Math.abs(e.clientX - rubber.sx) + "px; height:" + Math.abs(e.clientY - rubber.sy) + "px";
  }
});

document.addEventListener("pointerup", e => {
  if (drag) {
    drag.el.classList.remove("drag");
    drag = null;
    store();
  } else if (rubber) {
    const f = rubber.frame;
    const x = (Math.min(rubber.sx, e.clientX) - f.left) / f.width * 100;
    const y = (Math.min(rubber.sy, e.clientY) - f.top) / f.height * 100;
    const w = Math.abs(e.clientX - rubber.sx) / f.width * 100;
    const h = Math.abs(e.clientY - rubber.sy) / f.height * 100;
    const sceneEl = rubber.scene;
    rubber.box.remove();
    rubber = null;
    if (w >= META.min_w && h >= META.min_h) {
      const next = pending(sceneEl)[0];
      if (next) make(sceneEl, next.cut, next.text, {x: x, y: y, w: w, h: h});
    }
    store();
  }
});

// 더블클릭으로 문구 수정. Enter 로 확정, Esc 로 취소.
document.addEventListener("dblclick", e => {
  if (!body.classList.contains("bedit")) return;
  const el = e.target.closest(".tx");
  if (!el) return;
  const t = el.querySelector(".t"), before = t.textContent;
  t.contentEditable = "true";
  t.dataset.before = before;
  t.focus();
  const range = document.createRange();
  range.selectNodeContents(t);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
});

document.addEventListener("keydown", e => {
  const t = document.activeElement;
  if (!t || !t.classList || !t.classList.contains("t")) return;
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); t.blur(); }
  else if (e.key === "Escape") { t.textContent = t.dataset.before || ""; t.blur(); }
});

// 고치는 즉시 다시 핏 — 길어지면 작아지고, 최소 크기로도 안 되면 빨개진다.
document.addEventListener("input", e => {
  const t = e.target;
  if (t.classList && t.classList.contains("t") && t.contentEditable === "true") {
    refit(t.closest(".tx"));
    overLabel();
  }
});

document.addEventListener("blur", e => {
  const t = e.target;
  if (!t.classList || !t.classList.contains("t") || t.contentEditable !== "true") return;
  t.contentEditable = "false";
  t.textContent = t.textContent.replace(/\\s+$/, "");
  refit(t.closest(".tx"));
  store();
}, true);

function bubbleText() {
  const out = {};
  scenes.forEach(sc => {
    const items = Array.prototype.slice.call(sc.querySelectorAll(".tx")).map(el => {
      const s = state(el);
      const item = {cut: +el.dataset.cut, x: +s.x.toFixed(1), y: +s.y.toFixed(1),
                    w: +s.w.toFixed(1), h: +s.h.toFixed(1)};
      if (s.text.trim() !== (el.dataset.source || "").trim()) item.text = s.text;
      if (s.fs) item.fs = +s.fs.toFixed(1);
      return item;
    });
    if (items.length) out["scene" + sc.dataset.scene] = items;
  });
  return JSON.stringify(out, null, 2) + "\\n";
}

const dl = document.getElementById("download");
if (dl) dl.addEventListener("click", () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([bubbleText()], {type: "application/json"}));
  a.download = "bubbles.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
});

const cp = document.getElementById("copy");
if (cp) cp.addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(bubbleText());
        alert("bubbles.json 내용을 클립보드에 복사했습니다."); }
  catch (e) { window.prompt("복사해서 bubbles.json 으로 저장하세요:", bubbleText()); }
});

const rv = document.getElementById("revert");
if (rv) rv.addEventListener("click", () => {
  if (!confirm("저장된 bubbles.json 상태로 되돌립니다 (없으면 전부 지웁니다). 계속할까요?")) return;
  try { localStorage.removeItem(BKEY); } catch (e) {}
  all().forEach(el => el.remove());
  Object.keys(META.saved).forEach(k => {
    const v = META.saved[k], parts = k.split("|");
    const sc = document.getElementById("scene" + parts[0]);
    if (sc) make(sc, +parts[1], v.text, {x: v.x, y: v.y, w: v.w, h: v.h});
  });
  countDirty();
  queueLabel();
});

let ticking = false;
function onScroll() {
  if (ticking) return;
  ticking = true;
  requestAnimationFrame(() => {
    ticking = false;
    const max = root.scrollHeight - window.innerHeight;
    prog.style.width = (max > 0 ? Math.min(1, window.scrollY / max) * 100 : 0) + "%";
    if (!scenes.length) return;
    const mid = window.innerHeight / 2;
    let cur = scenes[0];
    for (const el of scenes) { if (el.getBoundingClientRect().top <= mid) cur = el; }
    pos.textContent = "Scene " + cur.dataset.scene +
                      " (" + (scenes.indexOf(cur) + 1) + "/" + scenes.length + ")";
  });
}
window.addEventListener("scroll", onScroll, {passive: true});
window.addEventListener("resize", () => { fitBar(); onScroll(); });
window.addEventListener("load", () => { fitBar(); onScroll(); });

load();
restore();
fitBar();
onScroll();
"""


def viewer_path(ep_dir: Path, condition: str, directed: bool = False) -> Path:
    """연출본은 파일을 따로 쓴다 — 나란히 열어 놓고 비교하는 것이 목적이다."""
    return ep_dir / f"viewer_{condition}{'_directed' if directed else ''}.html"


def scene_viewer_path(ep_dir: Path, condition: str, directed: bool = False) -> Path:
    return ep_dir / f"viewer_scene_{condition}{'_directed' if directed else ''}.html"


def compare_viewer_path(ep_dir: Path, condition: str) -> Path:
    return ep_dir / f"viewer_both_{condition}.html"


def _ink(bg: str) -> str:
    return ("--fg: #e9ebf1; --cap-bg: rgba(255,255,255,.07); "
            "--cap-line: rgba(255,255,255,.14); --dim: rgba(233,235,241,.62);"
            if _dark(bg) else
            "--fg: #16181d; --cap-bg: rgba(0,0,0,.05); "
            "--cap-line: rgba(0,0,0,.10); --dim: rgba(0,0,0,.45);")


def _caption(text: str, reader: bool = False) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    tag = '<span class="rtag">reader_only</span>' if reader else ""
    return f'<div class="cap{" reader" if reader else ""}">{tag}{_esc(text)}</div>'


def _cut_items(
    ep_dir: Path,
    condition: str,
    cuts: list[dict[str, Any]],
    picks: dict[int, int],
    layout: dict[int, str],
    sizes: dict[str, tuple[str, float]],
    width: int,
    marks: dict[int, int] | None = None,
    gaps: dict[int, int] | None = None,
    gap_map: dict[int, str] | None = None,
) -> tuple[str, list[int], dict[str, int], int]:
    """컷 모드 띠의 HTML. (html, 이미지 없는 컷, 크기별 개수, 총 높이 어림).

    gaps 가 있으면 컷 사이에 연출 여백(W7.5 의 gap_after)을 한 칸씩 끼운다.
    """
    items: list[str] = []
    missing: list[int] = []
    tally: dict[str, int] = {name: 0 for name in sizes}
    strip_h = 0
    buttons = "".join(f'<button data-size="{_esc(name)}">{_esc(name)}</button>'
                      for name in sizes)

    for cut in cuts:
        n = int(cut["cut_number"])
        size = layout.get(n, DEFAULT_SIZE)
        ratio, h_mult = sizes[size]
        tally[size] += 1
        # 가벼운 컷은 폭이 55% 라 높이도 그만큼 준다. 총 높이 어림이 이걸
        # 안 보면 화가 실제보다 길게 찍힌다.
        wt_now = str(cut.get("weight") or "normal").strip().lower()
        strip_h += round(width * h_mult * (LIGHT_WIDTH if wt_now == "light" else 1.0))

        # JS 없이도 맞게 보이도록 초기 크기는 파이썬이 박아 둔다. 이후는 JS 가 다시 칠한다.
        frame_cls = "frame screen" if ratio == SCREEN else "frame"
        vars_: list[str] = []
        if ratio != SCREEN:
            vars_.append(f"--ar: {ratio}")
        if h_mult < FLAT_RATIO:
            # 납작한 틀은 세로가 많이 잘린다. 얼굴이 남도록 위쪽을 기준으로 자른다.
            vars_.append("--pos: center 38%")
        style = f' style="{"; ".join(vars_)}"' if vars_ else ""

        cand = picks.get(n)
        src = f"{condition}/cut{n}_c{cand}.png" if cand else None
        if src and (ep_dir / src).exists():
            inner = f'<img src="{_esc(src)}" alt="컷 {n}" loading="lazy" decoding="async">'
        else:
            missing.append(n)
            why = ("picks.csv 에 채택 기록이 없습니다" if not cand
                   else f"채택 파일이 없습니다 — {src}")
            frame_cls += " miss"
            inner = (f'<div>컷 {n} · {_esc(why)}'
                     f'<span class="d">{_esc(cut.get("description"))}</span></div>')

        # 앞 컷에서 배경이 이어지는 컷 — 콘티(W7.5)의 vertical_link.
        # 옛 run 에는 이 칸이 없다. 없으면 표시가 안 붙을 뿐 나머지는 그대로다.
        linked = bool(cut.get("vertical_link"))
        link_mark = '<span class="link">↕ 이어짐</span>' if linked else ""
        # 무게 — 콘티(W7.5)의 weight. 없으면 normal 이라 예전과 같이 꽉 찬다.
        wt = str(cut.get("weight") or "normal").strip().lower()
        wt = wt if wt in ("full", "normal", "light") else "normal"
        wt_cls = f" w-{wt}" if wt != "normal" else ""
        wt_mark = ('<span class="wt">· 가벼운 컷</span>' if wt == "light"
                   else '<span class="wt">· 통째로</span>' if wt == "full" else "")
        items.append(
            f'<section class="cut{" linked" if linked else ""}{wt_cls}" id="cut{n}" '
            f'data-cut="{n}" data-size="{_esc(size)}" data-weight="{wt}">'
            f'<div class="{frame_cls}"{style}>{inner}</div>'
            f'<div class="no">컷 {n} <i>{_esc(size)}</i>{wt_mark}{link_mark}</div>'
            f'<div class="pick">{buttons}</div>'
            f'{_caption(cut.get("dialogue"), bool(cut.get("reader_only")))}</section>'
        )
        if marks and n in marks:
            items.append(f'<div class="mark">— Scene {marks[n]} 끝 —</div>')
        if gaps and n != int(cuts[-1]["cut_number"]):
            items.append(_gap_html(gaps.get(n, 1), gap_map or DEFAULT_GAP_MAP))

    return "".join(items), missing, tally, strip_h


DEFAULT_GAP_MAP = {0: "0", 1: "60px", 2: "240px", 3: "80vh"}
GAP_LABELS = {0: "붙임", 1: "보통", 2: "길게", 3: "낙차"}


def parse_gap_map(raw: Any) -> dict[int, str]:
    """config 의 viewer.gap_map → {0~3: CSS 길이}. 없으면 기본표.

    숫자는 px 로, 문자열은 그대로 쓴다("80vh"). 0 이 0 이 아니면 "붙인다"가
    거짓말이 되므로 거기서 멈춘다.
    """
    if raw in (None, "", {}):
        return dict(DEFAULT_GAP_MAP)
    if not isinstance(raw, dict):
        raise LayoutError(f"config.yaml 의 viewer.gap_map 이 표가 아닙니다: {raw!r}")

    out: dict[int, str] = {}
    for key, value in raw.items():
        try:
            level = int(key)
        except (TypeError, ValueError):
            raise LayoutError(
                f"viewer.gap_map 의 칸 이름 {key!r} 을 모릅니다. 0~3 이어야 합니다.")
        if not 0 <= level <= 3:
            raise LayoutError(
                f"viewer.gap_map 에 {level} 칸이 있습니다. gap_after 는 0~3 입니다.")
        if isinstance(value, bool):
            raise LayoutError(f"viewer.gap_map 의 {level} 칸이 참/거짓입니다: {value!r}")
        if isinstance(value, (int, float)):
            if value < 0:
                raise LayoutError(f"viewer.gap_map 의 {level} 칸이 음수입니다: {value!r}")
            out[level] = f"{value:g}px"
        elif isinstance(value, str) and value.strip():
            out[level] = value.strip()
        else:
            raise LayoutError(
                f"viewer.gap_map 의 {level} 칸 {value!r} 을 길이로 읽을 수 없습니다. "
                f"숫자(픽셀) 또는 \"80vh\" 같은 문자열이어야 합니다.")

    missing = [lv for lv in (0, 1, 2, 3) if lv not in out]
    if missing:
        raise LayoutError(
            f"viewer.gap_map 에 {missing} 칸이 없습니다. gap_after 는 0~3 이므로 "
            f"네 칸이 다 있어야 합니다.")
    if out[0] not in ("0", "0px", "0em", "0rem"):
        raise LayoutError(
            f"viewer.gap_map 의 0 칸이 {out[0]} 입니다. 0 은 '붙인다'는 뜻이므로 "
            f"0 이어야 합니다 — 웹툰에서 붙은 두 컷은 한 동작입니다.")
    return out


def _gap_html(level: int, gap_map: dict[int, str]) -> str:
    """컷/Scene 사이의 빈 자리 한 칸."""
    level = level if isinstance(level, int) and 0 <= level <= 3 else 1
    height = gap_map.get(level, DEFAULT_GAP_MAP[level])
    if height in ("0", "0px"):
        return ""
    return (f'<div class="gapx lv{level}" data-lv="{level}" '
            f'style="height: {_esc(height)}">'
            f'<b>여백 {level} · {GAP_LABELS[level]}</b></div>')


def _region_html(r: Any) -> str:
    """글자 얹을 영역 하나. 좌표는 인라인 style 로 박는다 — JS 없이도 제자리에 놓인다.

    말풍선 그림(테두리·꼬리)은 이미지 안에 이미 있다. 여기서는 글자만 얹는다.
    """
    fs = f' data-fs="{r.fs:.1f}"' if r.fs is not None else ""
    return (
        f'<div class="tx" data-cut="{r.cut}" data-source="{_esc(r.source)}"{fs} '
        f'style="--x: {r.x:.1f}%; --y: {r.y:.1f}%; --w: {r.w:.1f}%; --h: {r.h:.1f}%">'
        f'<span class="cutno">컷 {r.cut}</span>'
        f'<span class="t">{_esc(r.text)}</span>'
        f'<span class="fs"><b data-d="-1">&minus;</b><b class="now"></b>'
        f'<b data-d="1">+</b><b data-d="0">auto</b></span>'
        f'<i class="grip"></i><i class="del">&times;</i></div>'
    )


def _scene_items(
    ep_dir: Path,
    cond_dir: str,
    scenes: list[dict[str, Any]],
    picks: dict[int, int],
    width: int,
    bubbles_by_scene: dict[int, list[Any]] | None = None,
    gaps: dict[int, int] | None = None,
    gap_map: dict[int, str] | None = None,
) -> tuple[str, list[int], int]:
    """Scene 모드 띠의 HTML. (html, 이미지 없는 Scene, 총 높이 어림).

    scenes : [{"scene_number", "label", "dialogue", "description", "reader_only"}, ...]
    말풍선은 이미지 위에 얹으므로 .sframe 안에 들어간다 (캡션은 그 바깥).
    """
    items: list[str] = []
    missing: list[int] = []
    strip_h = 0

    for sc in scenes:
        n = int(sc["scene_number"])
        cand = picks.get(n)
        src = f"{cond_dir}/scene{n}_c{cand}.png" if cand else None
        path = ep_dir / src if src else None
        if path is not None and path.exists():
            size = image_size(path)
            dim = f' width="{size[0]}" height="{size[1]}"' if size else ""
            strip_h += round(size[1] * width / size[0]) if size else round(width * 4 / 3)
            inner = (f'<img src="{_esc(src)}" alt="Scene {n}"{dim} '
                     f'loading="lazy" decoding="async">')
        else:
            missing.append(n)
            why = ("picks.csv 에 채택 기록이 없습니다" if not cand
                   else f"채택 파일이 없습니다 — {src}")
            inner = (f'<div class="miss"><div>Scene {n} · {_esc(why)}'
                     f'<span class="d">{_esc(sc.get("description"))}</span></div></div>')
            strip_h += round(width * 4 / 3)

        bubs = "".join(_region_html(r) for r in (bubbles_by_scene or {}).get(n, []))
        items.append(
            f'<section class="scene" id="scene{n}" data-scene="{n}">'
            f'<div class="sframe">{inner}{bubs}</div>'
            f'<div class="no">Scene {n} <i>{_esc(sc.get("label"))}</i></div>'
            f'{_caption(sc.get("dialogue"), bool(sc.get("reader_only")))}</section>'
        )
        if gaps and n != int(scenes[-1]["scene_number"]):
            items.append(_gap_html(gaps.get(n, 1), gap_map or DEFAULT_GAP_MAP))

    return "".join(items), missing, strip_h


def build_viewer(
    ep_dir: Path,
    episode_meta: dict[str, Any],
    condition: str,
    label: str,
    cuts: list[dict[str, Any]],
    picks: dict[int, int],
    layout: dict[int, str],
    sizes: dict[str, tuple[str, float]],
    opts: dict[str, Any],
    siblings: Iterable[str] = (),
    direction: dict[str, Any] | None = None,
) -> tuple[Path, list[int], dict[str, int]]:
    """viewer_<condition>.html 을 쓰고 (경로, 이미지 없는 컷들, 크기별 개수) 반환.

    cuts    : prompts.json 의 cuts (cut_number/description/dialogue/reader_only)
    picks   : {cut_number: candidate} — 이 조건의 채택 기록만
    layout  : {cut_number: size} — layout.json (없는 컷은 normal)
    sizes   : parse_sizes() 결과
    opts    : {"width_px", "gap_px", "show_captions", "background"}
    siblings: 같이 만들어진 다른 조건들 (상단 바 링크용)
    direction: {"gaps", "breaks", "gap_map"} — 있으면 연출 여백을 끼운 별도 파일
               (viewer_<condition>_directed.html)로 나간다. 이미지는 그대로다.

    반환하는 크기별 개수는 layout.json 기준이다. 뷰어에서 바꾼 뒤 내려받지 않은
    변경은 브라우저 안에만 있다.
    """
    width = int(opts.get("width_px") or 690)
    gap = max(0, int(opts.get("gap_px") or 0))
    bg = str(opts.get("background") or "#ffffff")
    show_cap = bool(opts.get("show_captions", True))

    if direction:
        gap = 0     # 연출이 여백을 정한다. 슬라이더 기본 간격까지 겹치면 두 번 띄운다.
    strip, missing, tally, strip_h = _cut_items(
        ep_dir, condition, cuts, picks, layout, sizes, width,
        marks=(direction or {}).get("breaks"),
        gaps=(direction or {}).get("gaps"),
        gap_map=(direction or {}).get("gap_map"))

    links = "".join(f' <a href="viewer_{_esc(s)}.html">{_esc(s)}</a>'
                    for s in siblings if s != condition)
    other = f'<span class="cond">다른 조건:{links}</span>' if links else ""
    ink = _ink(bg)
    dtoggle = ('  <label><input type="checkbox" id="dgap" checked> 연출 여백</label>\n'
               if direction else "")
    dnote = ""
    if direction:
        counts = direction.get("counts") or {}
        dnote = (
            f'<p><b>연출 여백 켜짐</b> · 이 파일은 <code>ep{episode_meta.get("episode"):02d}'
            f'_direction.json</code> 의 gap_after 를 컷 사이 빈 자리로 옮긴 것입니다. '
            f'그림은 <code>viewer_{_esc(condition)}.html</code> 과 글자 하나까지 같습니다 — '
            f'다른 것은 사이의 빈 곳뿐입니다. '
            f'여백 {" / ".join(f"{lv}:{counts.get(lv, 0)}회" for lv in (0, 1, 2, 3))}. '
            f'<b>연출 여백</b> 을 끄면 여백 없이 붙은 상태가 되어 같은 창에서 바로 비교됩니다. '
            f'Scene 경계는 <b>컷 번호</b> 를 켜면 점선으로 보입니다.</p>')

    numbers = [int(c["cut_number"]) for c in cuts]
    meta = json.dumps({
        "run_id": episode_meta.get("run_id"),
        "episode": episode_meta.get("episode"),
        "def": DEFAULT_SIZE,
        "order": list(sizes),
        "sizes": {name: {"ar": None if ratio == SCREEN else ratio,
                         "screen": ratio == SCREEN,
                         "flat": h_mult < FLAT_RATIO}
                  for name, (ratio, h_mult) in sizes.items()},
        # 파일에 저장된 배치. 뷰어에서 바꾼 것과 비교해 "저장 안 된 변경"을 센다.
        "saved": {str(n): layout[n] for n in numbers if n in layout},
    }, ensure_ascii=False).replace("</", "<\\/")

    n_light = sum(1 for c in cuts
                  if str(c.get("weight") or "").strip().lower() == "light")
    n_full = sum(1 for c in cuts
                 if str(c.get("weight") or "").strip().lower() == "full")
    weight_note = (
        f'<b>컷 무게</b> · 가벼운 컷 {n_light}개(지면 폭 {int(LIGHT_WIDTH * 100)}%), '
        f'통째로 쓰는 컷 {n_full}개. 한 화의 모든 컷이 같은 무게일 필요는 없습니다 — '
        f'스쳐 가는 리액션과 판이 뒤집히는 컷이 같은 지면을 먹으면 정작 큰 컷이 '
        f'안 커 보입니다. 무게는 콘티가 render_style·size 에서 계산합니다.'
        if (n_light or n_full) else
        '<b>컷 무게</b> · 이 화는 모든 컷이 같은 무게입니다 (가벼운 컷도 통컷도 '
        '없습니다). 콘티가 render_style 을 float 이나 bleed 로 두면 여기가 갈립니다.')

    n_link = sum(1 for c in cuts if c.get("vertical_link"))
    link_note = (
        f'<b>↕ 이어짐</b> 표시가 붙은 컷 {n_link}개는 앞 컷과 배경이 위에서 아래로 '
        f'이어지는 자리입니다 (콘티가 계산한 vertical_link — 여백 0 · 같은 존). '
        f'무대는 그대로 두고 카메라만 아래로 내려간 자리라, 두 컷이 한 공간의 위와 '
        f'아래로 읽혀야 맞습니다. 실제로 이어 그리려면 config 의 '
        f'<code>vertical_link: true</code> 를 켜세요 (기본 꺼짐).'
        if n_link else
        '이 화에는 배경이 이어지는 자리(<b>↕ 이어짐</b>)가 없습니다 — 여백 0 으로 '
        '붙은 컷이 없거나, 붙은 두 컷의 존이 서로 다릅니다.')

    mix = " · ".join(f"{name} {tally[name]}" for name in sizes if tally[name])
    has_screen = any(sizes[layout.get(n, DEFAULT_SIZE)][0] == SCREEN for n in numbers)
    keys = ", ".join(f"<kbd>{i}</kbd> {_esc(name)}"
                     for i, name in enumerate(sizes, 1) if i <= 9)
    shown = len(cuts) - len(missing)

    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>뷰어 {_esc(condition)} — {_esc(episode_meta.get('run_id'))} ep{episode_meta.get('episode')}</title>
<style>{CSS}
:root {{ --w: {width}px; --gap: {gap}px; --bg: {_esc(bg)}; {ink} }}
</style></head>
<body class="{'' if show_cap else 'hide-cap'}">
<div class="bar">
  <b>{_esc(episode_meta.get('run_id'))} · {episode_meta.get('episode')}화 「{_esc(episode_meta.get('title'))}」</b>
  <span class="cond">조건 {_esc(condition)}{(' — ' + _esc(label)) if label else ''}</span>
  {other}
  <span class="cond"><a href="contact_sheet.html">컷 시트</a></span>
  <span class="sp"></span>
  <label><input type="checkbox" id="cap"{' checked' if show_cap else ''}> 대사</label>
  <label><input type="checkbox" id="num" checked> 컷 번호</label>
  <label><input type="checkbox" id="fit" checked> 잘라 채우기</label>
  <label>간격 <input type="range" id="gap" min="0" max="64" step="2" value="{gap}">
    <span id="gapv">{gap}px</span></label>
{dtoggle}  <label><input type="checkbox" id="fold"> 스크롤 폴드</label>
  <label><input type="checkbox" id="edit" checked> 크기 편집</label>
  <span class="edit-only">
    <button class="primary" id="download">layout.json 내려받기</button>
    <button id="copy">복사</button>
    <button id="revert">되돌리기</button>
    <span class="dirty" id="dirty"></span>
  </span>
  <span class="pos" id="pos">컷 -</span>
  <div class="progress" id="prog"></div>
</div>

<div class="strip">{strip}</div>

<footer>
  <p>컷 {shown}/{len(cuts)}장 · 폭 {width}px · 기본 간격 {gap}px ·
     {LAYOUT_FILE} 기준 크기 {_esc(mix)}</p>
  <p>총 높이 약 {strip_h:,}px (캡션 제외{', impact 는 9:16 로 어림' if has_screen else ''})</p>
  <p>{('채택 기록이 없는 컷: ' + ', '.join(str(n) for n in missing)) if missing
      else '모든 컷이 picks.csv 에 채택되어 있습니다.'}</p>
  {dnote}
  <p><b>크기 바꾸기</b> · 컷 오른쪽 위 버튼을 누르거나, 보고 있는 컷에 숫자키 {keys}.
     바꾼 값은 브라우저에 바로 저장되고 다른 조건 뷰어에서도 그대로 보입니다.
     확정하려면 <b>layout.json 내려받기</b> → 내려받은 파일을 이 폴더
     (<code>{_esc(str(ep_dir))}</code>)에 <code>{LAYOUT_FILE}</code> 로 저장하세요.
     그래야 다음에 다시 만들 때도 남습니다.</p>
  <p>이미지는 다시 만들지 않고 틀에 맞춰 잘라 넣은 것이라,
     <b>잘라 채우기</b> 를 끄면 원본 전체가 보입니다.
     말풍선 합성은 아직 없습니다 — 대사는 이미지 아래 캡션입니다.</p>
  <p>{weight_note}</p>
  <p><b>스크롤 폴드</b> · 켜면 화면 하나 높이마다 띠 위에 점선이 그어집니다.
     독자의 엄지가 멈추는 자리가 늘 그 선이라, 선 <b>바로 아래</b>에 무엇이 오는지가
     다음 화면까지 내려갈지를 정합니다 — 리빌·임팩트·반전이면 계속 내려가고,
     평평한 대사 컷이면 거기서 빠져나갑니다. 창을 좁히면 눈금이 따라 움직이므로
     폰에서 폴드가 어디 떨어지는지도 같은 창에서 볼 수 있습니다.
     {link_note}</p>
  <p>생성 {datetime.now().isoformat(timespec='seconds')}</p>
</footer>
<script>const META = {meta};{JS}</script>
</body></html>
"""
    out = viewer_path(ep_dir, condition, directed=bool(direction))
    out.write_text(doc, encoding="utf-8")
    return out, missing, tally


def build_scene_viewer(
    ep_dir: Path,
    episode_meta: dict[str, Any],
    condition: str,
    label: str,
    scenes: list[dict[str, Any]],
    picks: dict[int, int],
    opts: dict[str, Any],
    siblings: Iterable[str] = (),
    bubbles_by_scene: dict[int, list[Any]] | None = None,
    had_bubble_file: bool = False,
    direction: dict[str, Any] | None = None,
) -> tuple[Path, list[int]]:
    """viewer_scene_<condition>.html 을 쓰고 (경로, 이미지 없는 Scene) 반환.

    Scene 이미지는 한 장이 곧 웹툰 페이지 한 장이다. 틀에 맞춰 자르지 않고
    원본 비율 그대로 쌓는다 (layout.json 은 컷 모드 전용).
    대사는 이미지에 그리지 않고 말풍선으로 얹는다 (bubbles.json).
    """
    width = int(opts.get("width_px") or 690)
    gap = max(0, int(opts.get("gap_px") or 0))
    bg = str(opts.get("background") or "#ffffff")
    show_cap = bool(opts.get("show_captions", True))
    by_scene = bubbles_by_scene or {}

    if direction:
        gap = 0     # 연출이 여백을 정한다. 슬라이더 기본 간격까지 겹치면 두 번 띄운다.
    cond_dir = f"scene_{condition}"
    strip, missing, strip_h = _scene_items(
        ep_dir, cond_dir, scenes, picks, width, by_scene,
        gaps=(direction or {}).get("gaps"),
        gap_map=(direction or {}).get("gap_map"))
    links = "".join(f' <a href="viewer_scene_{_esc(s)}.html">{_esc(s)}</a>'
                    for s in siblings if s != condition)
    other = f'<span class="cond">다른 조건:{links}</span>' if links else ""
    dtoggle = ('  <label><input type="checkbox" id="dgap" checked> 연출 여백</label>\n'
               if direction else "")
    dnote = ""
    if direction:
        counts = direction.get("counts") or {}
        regroup = direction.get("regroup_note") or ""
        dnote = (
            f'<p><b>연출 여백 켜짐</b> · Scene 사이의 빈 자리는 '
            f'<code>ep{episode_meta.get("episode"):02d}_direction.json</code> 의 '
            f'gap_after 에서 왔습니다 (그 Scene 마지막 컷의 값). 그림은 '
            f'<code>viewer_scene_{_esc(condition)}.html</code> 과 같습니다 — 다른 것은 '
            f'사이의 빈 곳뿐입니다. '
            f'여백 {" / ".join(f"{lv}:{counts.get(lv, 0)}회" for lv in (0, 1, 2, 3))}. '
            f'<b>연출 여백</b> 을 끄면 지금 버전과 같은 배치가 됩니다.</p>'
            + (f'<p><b>주의</b> · {_esc(regroup)}</p>' if regroup else ""))
    meta = json.dumps({
        "run_id": episode_meta.get("run_id"),
        "episode": episode_meta.get("episode"),
        "min_w": bubbles.MIN_W, "max_w": bubbles.MAX_W,
        "min_h": bubbles.MIN_H, "max_h": bubbles.MAX_H,
        "min_fs": bubbles.MIN_FONT_PX, "max_fs": bubbles.MAX_FONT_PX,
        "had_file": bool(had_bubble_file),
        # 이 Scene 에 들어가야 할 대사 전부. 아직 영역이 없는 것이 "배치 대기" 다.
        "lines": {str(sc["scene_number"]): [{"cut": int(l["cut"]), "text": str(l["text"])}
                                            for l in (sc.get("lines") or [])]
                  for sc in scenes},
        # 파일 기준선. 뷰어에서 바꾼 것과 비교해 변경 수를 센다.
        "saved": {f"{n}|{r.cut}": {"x": round(r.x, 1), "y": round(r.y, 1),
                                   "w": round(r.w, 1), "h": round(r.h, 1),
                                   "text": r.text, "fs": r.fs}
                  for n, items in by_scene.items() for r in items},
    }, ensure_ascii=False).replace("</", "<\\/")
    shown = len(scenes) - len(missing)
    panels = sum(len(sc.get("cut_numbers") or []) for sc in scenes)
    n_bub = sum(len(v) for v in by_scene.values())
    n_lines = sum(len(sc.get("lines") or []) for sc in scenes)

    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scene 뷰어 {_esc(condition)} — {_esc(episode_meta.get('run_id'))} ep{episode_meta.get('episode')}</title>
<style>{CSS}
:root {{ --w: {width}px; --gap: {gap}px; --bg: {_esc(bg)}; {_ink(bg)} }}
</style></head>
<body class="{'' if show_cap else 'hide-cap'}">
<div class="bar">
  <b>{_esc(episode_meta.get('run_id'))} · {episode_meta.get('episode')}화 「{_esc(episode_meta.get('title'))}」</b>
  <span class="cond">Scene 모드 · 조건 {_esc(condition)}{(' — ' + _esc(label)) if label else ''}</span>
  {other}
  <span class="cond"><a href="viewer_both_{_esc(condition)}.html">컷 모드와 비교</a>
    · <a href="contact_sheet_scene.html">Scene 시트</a></span>
  <span class="sp"></span>
  <label><input type="checkbox" id="bub" checked> 대사 얹기</label>
  <label><input type="checkbox" id="bedit"> 말풍선 편집</label>
  <span class="edit-only">
    <button class="primary" id="download">bubbles.json 내려받기</button>
    <button id="copy">복사</button>
    <button id="revert">되돌리기</button>
    <span class="dirty" id="dirty"></span>
    <span class="queue" id="queue"></span>
  </span>
  <span class="dirty" id="over"></span>
  <label><input type="checkbox" id="cap"{' checked' if show_cap else ''}> 캡션</label>
  <label><input type="checkbox" id="num" checked> Scene 번호</label>
  <label>간격 <input type="range" id="gap" min="0" max="64" step="2" value="{gap}">
    <span id="gapv">{gap}px</span></label>
{dtoggle}  <span class="pos" id="pos">Scene -</span>
  <div class="progress" id="prog"></div>
</div>

<div class="strip">{strip}</div>

<footer>
  <p>Scene {shown}/{len(scenes)}장 (컷 {panels}개분) · 대사 {n_lines}줄 중 {n_bub}줄 배치됨 ·
     폭 {width}px · 기본 간격 {gap}px · 총 높이 약 {strip_h:,}px</p>
  <p>{('채택 기록이 없는 Scene: ' + ', '.join(str(n) for n in missing)) if missing
      else '모든 Scene 이 picks.csv 에 채택되어 있습니다.'}</p>
  {dnote}
  <p><b>말풍선</b> · 빈 말풍선은 이미지에 그려져 있습니다. 여기서는 그 안에 <b>글자만</b>
     얹습니다 (배경도 테두리도 꼬리도 없습니다).
     {'영역은 <code>' + bubbles.BUBBLE_FILE + '</code> 에서 왔습니다.'
      if had_bubble_file else
      '<code>' + bubbles.BUBBLE_FILE + '</code> 이 없어 아직 지정된 영역이 없습니다.'}</p>
  <p><b>말풍선 편집</b> 을 켜고 · 그려진 말풍선 위에 <b>사각형을 끌어 그리면</b> 대기 중인
     대사가 순서대로 들어갑니다 · 영역 안을 끌면 이동, 오른쪽 아래 모서리를 끌면 크기 ·
     <b>더블클릭</b> 으로 문구 수정(Enter 확정, Esc 취소) · <b>&times;</b> 로 삭제 ·
     글자 크기는 영역에 맞춰 자동이고 <b>&minus; + auto</b> 로 직접 잡을 수 있습니다.
     최소 {bubbles.MIN_FONT_PX:.0f}px 로도 안 들어가면 영역이 <span style="color:#d33">빨갛게</span>
     표시됩니다 — 영역을 키우거나 대사를 줄이라는 신호입니다.
     확정하려면 <b>bubbles.json 내려받기</b> → 이 폴더
     (<code>{_esc(str(ep_dir))}</code>)에 <code>{bubbles.BUBBLE_FILE}</code> 로 저장하세요.</p>
  <p>Scene 한 장 = 컷 여러 개를 한 번에 그린 웹툰 페이지 한 장입니다. 이미지 안의
     패널 나눔은 이미지 모델이 그린 것이라 컷 경계와 정확히 맞지 않을 수 있습니다 —
     그게 이 모드에서 볼 것입니다. <b>대사 얹기</b> 를 끄면 원본 그림만 봅니다.</p>
  <p>생성 {datetime.now().isoformat(timespec='seconds')}</p>
</footer>
<script>const META = {meta};{SCENE_JS}</script>
</body></html>
"""
    out = scene_viewer_path(ep_dir, condition, directed=bool(direction))
    out.write_text(doc, encoding="utf-8")
    return out, missing


def build_compare_viewer(
    ep_dir: Path,
    episode_meta: dict[str, Any],
    condition: str,
    label: str,
    cuts: list[dict[str, Any]],
    cut_picks: dict[int, int],
    layout: dict[int, str],
    sizes: dict[str, tuple[str, float]],
    scenes: list[dict[str, Any]],
    scene_picks: dict[int, int],
    opts: dict[str, Any],
    calls: dict[str, Any] | None = None,
    bubbles_by_scene: dict[int, list[Any]] | None = None,
) -> tuple[Path, list[int], list[int]]:
    """viewer_both_<condition>.html — 컷 모드와 Scene 모드를 나란히 놓는다.

    두 띠는 한 페이지를 같이 스크롤한다. 길이가 서로 다르므로 컷 쪽에는
    Scene 경계선을 그어 어디까지가 같은 Scene 인지 보이게 한다.
    """
    width = int(opts.get("width_px") or 690)
    gap = max(0, int(opts.get("gap_px") or 0))
    bg = str(opts.get("background") or "#ffffff")
    show_cap = bool(opts.get("show_captions", True))

    marks = {int(sc["cut_numbers"][-1]): int(sc["scene_number"])
             for sc in scenes if sc.get("cut_numbers")}
    left, cut_missing, tally, left_h = _cut_items(
        ep_dir, condition, cuts, cut_picks, layout, sizes, width, marks=marks)
    # 비교 화면의 말풍선은 보여주기만 한다. 편집은 Scene 뷰어에서 한다.
    right, scene_missing, right_h = _scene_items(
        ep_dir, f"scene_{condition}", scenes, scene_picks, width, bubbles_by_scene or {})

    numbers = [int(c["cut_number"]) for c in cuts]
    meta = json.dumps({
        "run_id": episode_meta.get("run_id"),
        "episode": episode_meta.get("episode"),
        "def": DEFAULT_SIZE,
        "order": list(sizes),
        "sizes": {name: {"ar": None if ratio == SCREEN else ratio,
                         "screen": ratio == SCREEN,
                         "flat": h_mult < FLAT_RATIO}
                  for name, (ratio, h_mult) in sizes.items()},
        "saved": {str(n): layout[n] for n in numbers if n in layout},
    }, ensure_ascii=False).replace("</", "<\\/")

    calls = calls or {}
    cost = ""
    if calls:
        cost = (f"<p>호출 수 · 컷 모드 {calls.get('cut_calls')}회 "
                f"({calls.get('cut_units')}컷 x 후보 {calls.get('cut_candidates')}) "
                f"vs Scene 모드 {calls.get('scene_calls')}회 "
                f"({calls.get('scene_units')}Scene x 후보 {calls.get('scene_candidates')}) · "
                f"예상 비용 {calls.get('cut_krw'):,}원 vs {calls.get('scene_krw'):,}원</p>")

    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>컷 vs Scene {_esc(condition)} — {_esc(episode_meta.get('run_id'))} ep{episode_meta.get('episode')}</title>
<style>{CSS}
:root {{ --w: {width}px; --gap: {gap}px; --bg: {_esc(bg)}; {_ink(bg)} }}
</style></head>
<body class="compare {'' if show_cap else 'hide-cap'}">
<div class="bar">
  <b>{_esc(episode_meta.get('run_id'))} · {episode_meta.get('episode')}화 「{_esc(episode_meta.get('title'))}」</b>
  <span class="cond">컷 모드 vs Scene 모드 · 조건 {_esc(condition)}{(' — ' + _esc(label)) if label else ''}</span>
  <span class="cond"><a href="viewer_{_esc(condition)}.html">컷만</a>
    · <a href="viewer_scene_{_esc(condition)}.html">Scene 만</a></span>
  <span class="sp"></span>
  <label><input type="checkbox" id="cap"{' checked' if show_cap else ''}> 대사</label>
  <label><input type="checkbox" id="num" checked> 번호·경계</label>
  <label><input type="checkbox" id="fit" checked> 잘라 채우기</label>
  <label>간격 <input type="range" id="gap" min="0" max="64" step="2" value="{gap}">
    <span id="gapv">{gap}px</span></label>
  <label><input type="checkbox" id="edit"> 크기 편집</label>
  <span class="edit-only">
    <button class="primary" id="download">layout.json 내려받기</button>
    <button id="copy">복사</button>
    <button id="revert">되돌리기</button>
    <span class="dirty" id="dirty"></span>
  </span>
  <span class="pos" id="pos">컷 -</span>
  <div class="progress" id="prog"></div>
</div>

<div class="cols">
  <div class="col">
    <div class="colhead">컷 모드 <span>컷 1개 = 이미지 1장 · {len(cuts)}장</span></div>
    {left}
  </div>
  <div class="col">
    <div class="colhead">Scene 모드 <span>컷 여러 개 = 이미지 1장 · {len(scenes)}장</span></div>
    {right}
  </div>
</div>

<footer>
  <p>컷 {len(cuts) - len(cut_missing)}/{len(cuts)}장 · Scene
     {len(scenes) - len(scene_missing)}/{len(scenes)}장 ·
     총 높이 컷 약 {left_h:,}px vs Scene 약 {right_h:,}px</p>
  {cost}
  <p>두 칸은 같은 페이지를 같이 스크롤합니다. 길이가 다르므로 컷 쪽에 Scene 경계선을
     그어 두었습니다 — 같은 이야기 구간을 찾을 때 쓰세요. 창이 좁으면 두 칸이
     같이 줄어듭니다(690px 기준 비율은 유지).</p>
  <p><b>이 화면에서 볼 것</b></p>
  <ol>
    <li>Scene 한 장 <b>안에서</b> 인물이 같은 사람으로 보이는가 (패널 사이 얼굴·복장)</li>
    <li>Scene 과 Scene <b>사이</b> 연결은 어떤가 — 컷 모드보다 나은가 나쁜가</li>
    <li>같은 구간을 읽었을 때 컷 모드와 Scene 모드 중 어느 쪽이 읽히는가</li>
  </ol>
  <p>생성 {datetime.now().isoformat(timespec='seconds')}</p>
</footer>
<script>const META = {meta};{JS}</script>
</body></html>
"""
    out = compare_viewer_path(ep_dir, condition)
    out.write_text(doc, encoding="utf-8")
    return out, cut_missing, scene_missing
