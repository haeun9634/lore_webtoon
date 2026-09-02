"""verify.html — 한 번의 생성으로 그림체·말풍선·효과음·통독을 동시에 재는 화면.

셋을 따로 검증하면 생성 비용이 세 번 나간다. 그런데 이 셋은 **같은 이미지**로
동시에 잴 수 있다:

  말풍선/효과음 : 새 scene_gen.txt 규칙으로 뽑은 이미지에서 바로 확인한다
  그림체         : 그 Scene 들은 서로 다른 장면이므로 그대로 편차 측정이 된다
  통독           : 그 Scene 들을 세로로 이어 붙이면 그게 곧 읽는 화면이다

그래서 --verify-all 은 Scene 전체를 후보 2장씩만 뽑고(채택용 3장이 아니다 —
여기서 고를 것이 아니라 잴 것이다), 그 한 벌을 네 가지로 나눠 본다.

기존 scene_C/ 는 건드리지 않는다. 전부 verify/ 아래에 따로 쌓인다 — scenes.json
도 verify/scenes_verify.json 으로 따로 남아, 이미 만들어 둔 이미지와 기록이
어긋나지 않는다.

탭 3(통독)은 이 파일이 다시 그리지 않는다. 실제 Scene 뷰어(viewer.py)를 verify/
이미지로 한 벌 만들어 iframe 으로 그대로 띄운다. "viewer 와 동일 렌더" 를
흉내 내는 대신 진짜 그것을 쓴다 — 말풍선 편집·자동 핏·넘침 경고·bubbles.json
내려받기가 전부 살아 있어야 하기 때문이다.

채점은 점수가 아니라 Y/N 이다 (verify_score.csv). 네 탭의 체크가 모두 한
채점표의 열이므로, 어느 탭에서 눌러도 같은 행에 모인다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import stylelock
from stylelock import DEFAULT_CROP, MIN_SIDE, check_rows
from viewer import _esc, image_size

VERIFY_DIR = "verify"
PAGE_FILE = "verify.html"
SCORE_FILE = "verify_score.csv"
SCENES_FILE = "scenes_verify.json"

# ① 말풍선/효과음 — 새 프롬프트 규칙이 실제로 먹었는지 묻는 다섯 가지.
BUBBLE_ITEMS: list[tuple[str, str, str]] = [
    ("말풍선존재", "빈 말풍선이 그려졌는가",
     "대사가 있는 패널에만 있는가. 개수가 그 Scene 의 대사 줄 수와 맞는가."),
    ("말풍선빈칸", "말풍선 안이 정말 비어 있는가",
     "뭉개진 글자나 낙서로 채워지지 않았는가. 글자는 뷰어가 얹는다."),
    ("말풍선크기", "말풍선 크기가 대사 길이에 맞는가",
     "짧은 대사에 거대한 말풍선, 긴 대사에 좁쌀만 한 말풍선이 아닌가."),
    ("얼굴가림", "말풍선이 인물 얼굴을 가리지 않는가",
     "얼굴 위에 얹혀 표정을 덮고 있지 않은가."),
    ("효과음한글", "효과음이 한글로, 그림에 녹아들게 그려졌는가",
     "로마자나 깨진 글자가 아닌가. 패널당 최대 1개를 지켰는가."),
]
# ② 그림체 — style-lock 과 같은 항목을 쓴다. 같은 것을 두 번 정의하지 않는다.
STYLE_ITEMS = stylelock.ITEMS
READ_KEY = "통독종합"

SCORE_HEADER = (["scene_no"]
                + [k for k, _, _ in BUBBLE_ITEMS]
                + [k for k, _, _ in STYLE_ITEMS]
                + [READ_KEY])
ALL_KEYS = SCORE_HEADER[1:]

FACE_H = stylelock.FACE_H
MIN_ZOOM, MAX_ZOOM = stylelock.MIN_ZOOM, stylelock.MAX_ZOOM


def verify_dir(ep_dir: Path) -> Path:
    return ep_dir / VERIFY_DIR


def page_path(ep_dir: Path) -> Path:
    return ep_dir / PAGE_FILE


def scenes_path(ep_dir: Path) -> Path:
    return verify_dir(ep_dir) / SCENES_FILE


# --------------------------------------------------------------------------- #
CSS = """
/* --- 탭 ---------------------------------------------------------------------- */
.tabs { position: sticky; top: var(--bar, 40px); z-index: 9; display: flex; gap: 6px;
        padding: 8px 14px 0; background: var(--bg);
        border-bottom: 1px solid var(--line); }
.tabs button { font: inherit; font-size: 13px; padding: 8px 14px; cursor: pointer;
               color: var(--dim); background: transparent; border: 1px solid transparent;
               border-bottom: 0; border-radius: 7px 7px 0 0; margin-bottom: -1px; }
.tabs button:hover { color: var(--fg); background: var(--soft); }
.tabs button.on { color: var(--fg); font-weight: 700; background: var(--bg);
                  border-color: var(--line); }
.tab { display: none; }
.tab.on { display: block; }

/* 탭마다 쓸모 있는 도구가 다르다. 안 쓰는 토글을 켜 두면 뭘 보고 있는지 흐려진다.
   `.bar label` 이 이미 display:flex 라, 숨기는 쪽도 클래스를 두 개 겹쳐 이긴다. */
.bar .only-style, .bar .only-zoom { display: none; }
body[data-tab="style"] .bar .only-style { display: flex; }
body[data-tab="style"] .bar .only-zoom,
body[data-tab="bub"] .bar .only-zoom { display: flex; }
body:not([data-tab="style"]) .bar .edit-only { display: none; }

.lead { max-width: 1080px; margin: 0 auto; padding: 14px 16px 0;
        font-size: 12.5px; color: var(--dim); }
.lead b { color: var(--fg); }
.lead code { background: var(--soft); padding: 1px 5px; border-radius: 4px; }

/* --- ① 말풍선/효과음 ---------------------------------------------------------- */
.bsec { padding: 16px 14px 8px; border-bottom: 1px solid var(--line); }
.bsec h2 { margin: 0 0 4px; font-size: 15px; }
.bsec .lines { margin: 0 0 12px; font-size: 12.5px; color: var(--dim);
               white-space: pre-wrap; }
.bwrap { display: flex; gap: 18px; align-items: flex-start; }
.bshots { display: flex; gap: 14px; align-items: flex-start; min-width: 0;
          overflow-x: auto; flex: 1 1 auto; }
.bshot { margin: 0; flex: 0 0 auto; }
.bframe { position: relative; width: var(--w); }
body.zoom .bframe { width: calc(var(--w) * var(--z)); }
.bframe img { display: block; width: 100%; height: auto;
              background: rgba(127,127,127,.10); border: 1px solid var(--line); }
.bshot figcaption { padding: 6px 2px; font-size: 12px; color: var(--dim); }
.bshot .miss { display: flex; align-items: center; justify-content: center; width: 320px;
               aspect-ratio: 3/4; padding: 20px; text-align: center; font-size: 12.5px;
               color: var(--dim); border: 2px dashed var(--line); background: var(--soft); }

/* --- ③ 통독 (진짜 Scene 뷰어를 그대로 띄운다) ---------------------------------- */
.readwrap { padding: 12px 14px 0; }
.readwrap iframe { width: 100%; height: calc(100vh - var(--bar, 40px) - 200px);
                   min-height: 460px; border: 1px solid var(--line); border-radius: 8px;
                   background: #fff; }

/* --- ④ 채점 ------------------------------------------------------------------- */
.scorewrap { padding: 16px 14px; overflow-x: auto; }
table.score { border-collapse: collapse; font-size: 12px; }
table.score th, table.score td { border: 1px solid var(--line); padding: 6px 8px;
                                 text-align: center; white-space: nowrap; }
table.score th { background: var(--soft); font-weight: 700; }
table.score th.grp { background: rgba(47,111,237,.10); }
table.score td.sc { font-weight: 700; font-variant-numeric: tabular-nums; }
.it.mini { border-top: 0; padding: 0; gap: 3px; justify-content: center; }
.it.mini > span { display: none; }
"""


JS = """
/* --- 탭 (열어 둔 탭은 기억한다. 채점하다 새로고침하면 처음으로 돌아가면 곤란) --- */
const TKEY = "webtoon-verifytab:" + META.run_id + ":ep" + META.episode;
const tabs = Array.prototype.slice.call(document.querySelectorAll(".tabs button"));

function showTab(name) {
  const found = tabs.some(b => b.dataset.tab === name) ? name : tabs[0].dataset.tab;
  tabs.forEach(b => b.classList.toggle("on", b.dataset.tab === found));
  document.querySelectorAll(".tab").forEach(s =>
    s.classList.toggle("on", s.id === "tab-" + found));
  document.body.dataset.tab = found;
  try { localStorage.setItem(TKEY, found); } catch (e) {}
  fitBar();
}

tabs.forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

let start = null;
try { start = localStorage.getItem(TKEY); } catch (e) {}
showTab(start || tabs[0].dataset.tab);
"""


# --------------------------------------------------------------------------- #
def _lines_text(sc: dict[str, Any]) -> str:
    lines = sc.get("lines") or []
    if not lines:
        return "대사 없음 — 이 Scene 에는 말풍선이 하나도 없어야 한다."
    return "대사 " + str(len(lines)) + "줄 · " + " / ".join(
        f"[컷 {l['cut']}] {l['text']}" for l in lines)


def _bubble_tab(ep_dir: Path, cond_dir: str, scenes: list[dict[str, Any]],
                candidates: int) -> str:
    """① 말풍선/효과음 — 후보를 나란히 크게 놓고 다섯 가지를 묻는다."""
    out: list[str] = []
    for sc in scenes:
        n = int(sc["scene_number"])
        shots: list[str] = []
        for k in range(1, candidates + 1):
            src = f"{cond_dir}/scene{n}_c{k}.png"
            path = ep_dir / src
            if path.exists():
                size = image_size(path)
                dim = f' width="{size[0]}" height="{size[1]}"' if size else ""
                inner = (f'<div class="bframe"><img src="{_esc(src)}" '
                         f'alt="Scene {n} 후보 {k}"{dim} loading="lazy" '
                         f'decoding="async"></div>')
            else:
                inner = f'<div class="miss">후보 {k} 이미지가 없습니다<br>{_esc(src)}</div>'
            shots.append(f'<figure class="bshot">{inner}'
                         f'<figcaption>후보 {k}</figcaption></figure>')
        out.append(
            f'<section class="bsec" data-scene="{n}">'
            f'<h2>Scene {n} · {_esc(sc.get("label"))} · 패널 '
            f'{len(sc.get("cut_numbers") or [])}개</h2>'
            f'<p class="lines">{_esc(_lines_text(sc))}</p>'
            f'<div class="bwrap"><div class="bshots">{"".join(shots)}</div>'
            f'<div class="chk"><b>Scene {n} 확인</b>'
            f'<p class="hint">대사 줄 수와 그려진 말풍선 수를 먼저 세세요.</p>'
            f'{check_rows(n, BUBBLE_ITEMS)}</div></div></section>')
    return "".join(out)


def _style_tab(ep_dir: Path, cond_dir: str, scenes: list[dict[str, Any]],
               picks: dict[int, int], crops: dict[int, dict[str, float]],
               width: int) -> tuple[str, list[dict[str, Any]], list[int]]:
    """② 그림체 — style-lock 과 같은 화면. 대상만 verify/ 이미지다."""
    tiles: list[str] = []
    rows: list[str] = []
    meta_scenes: list[dict[str, Any]] = []
    missing: list[int] = []

    for sc in scenes:
        n = int(sc["scene_number"])
        cand = picks.get(n, 1)
        src = f"{cond_dir}/scene{n}_c{cand}.png"
        path = ep_dir / src
        size = image_size(path) if path.exists() else None

        if size is None:
            missing.append(n)
            meta_scenes.append({"n": n, "iw": None, "ih": None})
            why = f"이미지가 없습니다 — {src}"
            tiles.append(f'<figure class="tile" data-scene="{n}">'
                         f'<div class="miss">Scene {n}<br>{_esc(why)}</div>'
                         f'<figcaption><b>Scene {n}</b></figcaption></figure>')
            rows.append(f'<div class="row" data-scene="{n}"><div class="shot">'
                        f'<div class="miss"><div>Scene {n} · {_esc(why)}</div></div></div>'
                        f'<div class="chk"><b>Scene {n} 체크</b>'
                        f'<p class="hint">앞 Scene 과 견줘서 같으면 Y, 튀면 N.</p>'
                        f'{check_rows(n, STYLE_ITEMS)}</div></div>')
            continue

        iw, ih = size
        c = crops.get(n, DEFAULT_CROP)
        meta_scenes.append({"n": n, "iw": iw, "ih": ih})
        tiles.append(
            f'<figure class="tile" data-scene="{n}">'
            f'<div class="crop" style="--cx: {c["x"]:.1f}; --cy: {c["y"]:.1f}; '
            f'--cw: {c["w"]:.1f}; --ch: {c["h"]:.1f}; '
            f'--ar: {(c["w"] * iw) / (c["h"] * ih):.4f}">'
            f'<img src="{_esc(src)}" alt="Scene {n} 얼굴" decoding="async"></div>'
            f'<figcaption><b>Scene {n}</b> {_esc(sc.get("label"))} · c{cand}</figcaption>'
            f'<div class="chk">{check_rows(n, STYLE_ITEMS)}</div></figure>')
        rows.append(
            f'<div class="row" data-scene="{n}"><div class="shot"><div class="sframe">'
            f'<img src="{_esc(src)}" alt="Scene {n}" width="{iw}" height="{ih}" '
            f'loading="lazy" decoding="async">'
            f'<div class="no">Scene {n} <i>{_esc(sc.get("label"))} · c{cand}</i></div>'
            f'<div class="box" data-scene="{n}" style="--cx0: {c["x"]:.1f}%; '
            f'--cy0: {c["y"]:.1f}%; --cw0: {c["w"]:.1f}%; --ch0: {c["h"]:.1f}%">'
            f'<b>얼굴</b><i class="grip"></i></div></div></div>'
            f'<div class="chk"><b>Scene {n} 체크</b>'
            f'<p class="hint">앞 Scene 과 견줘서 같으면 Y, 튀면 N.</p>'
            f'{check_rows(n, STYLE_ITEMS)}</div></div>')

    html = (f'<section class="faces">{"".join(tiles)}</section>'
            f'<section class="stack">{"".join(rows)}</section>')
    return html, meta_scenes, missing


def _score_tab(scenes: list[dict[str, Any]]) -> str:
    """④ 채점 — 네 탭에서 누른 것이 여기 한 표에 모인다."""
    groups = [("말풍선/효과음", BUBBLE_ITEMS), ("그림체", STYLE_ITEMS)]
    top = "".join(f'<th class="grp" colspan="{len(items)}">{_esc(name)}</th>'
                  for name, items in groups)
    head = "".join(f'<th title="{_esc(hint)}">{_esc(key)}</th>'
                   for _, items in groups for key, _, hint in items)
    body: list[str] = []
    for sc in scenes:
        n = int(sc["scene_number"])
        cells = "".join(
            f'<td><div class="it mini" data-scene="{n}" data-key="{_esc(key)}">'
            f'<span></span><i data-v="Y">Y</i><i data-v="N">N</i></div></td>'
            for _, items in groups for key, _, _ in items)
        cells += (f'<td><div class="it mini" data-scene="{n}" data-key="{_esc(READ_KEY)}">'
                  f'<span></span><i data-v="Y">Y</i><i data-v="N">N</i></div></td>')
        body.append(f'<tr><td class="sc">Scene {n}</td>'
                    f'<td>{_esc(sc.get("label"))}</td>{cells}</tr>')
    return (f'<div class="scorewrap"><table class="score">'
            f'<thead><tr><th rowspan="2">Scene</th><th rowspan="2">컷</th>{top}'
            f'<th rowspan="2" title="이어 읽었을 때 한 편으로 읽히는가">'
            f'{_esc(READ_KEY)}</th></tr><tr>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def build_page(
    ep_dir: Path,
    episode_meta: dict[str, Any],
    condition: str,
    cond_dir: str,
    label: str,
    scenes: list[dict[str, Any]],
    picks: dict[int, int],
    candidates: int,
    crops: dict[int, dict[str, float]],
    had_crop_file: bool,
    saved_score: dict[int, dict[str, str]],
    viewer_href: str,
    opts: dict[str, Any],
) -> tuple[Path, list[int]]:
    """verify.html 을 쓰고 (경로, 그림체 탭에서 이미지가 없던 Scene) 반환.

    scenes : [{"scene_number", "label", "cut_numbers", "lines": [{"cut","text"}]}, ...]
    picks  : {scene_number: candidate} — 그림체/통독 탭이 쓸 후보. 없으면 1번.
    """
    width = int(opts.get("width_px") or 690)
    bub = _bubble_tab(ep_dir, cond_dir, scenes, candidates)
    style, meta_scenes, missing = _style_tab(ep_dir, cond_dir, scenes, picks, crops, width)
    score = _score_tab(scenes)

    widest = max((s["iw"] for s in meta_scenes if s["iw"]), default=width)
    zoom = min(MAX_ZOOM, max(MIN_ZOOM, widest / width))

    meta = json.dumps({
        "run_id": episode_meta.get("run_id"),
        "episode": episode_meta.get("episode"),
        # localStorage 이름표. style_lock.html 과 섞이면 안 된다 — 열도 이미지도 다르다.
        "cond": cond_dir,
        "scenes": meta_scenes,
        "keys": ALL_KEYS,
        "header": SCORE_HEADER,
        "def_crop": DEFAULT_CROP,
        "min_side": MIN_SIDE,
        "saved_crops": {str(n): crops[n] for n in crops},
        "had_crop_file": had_crop_file,
        "other_crops": stylelock.other_blocks(ep_dir, cond_dir),
        "saved_score": {str(n): saved_score[n] for n in saved_score},
        "crop_file": stylelock.CROP_FILE,
        "score_file": SCORE_FILE,
    }, ensure_ascii=False).replace("</", "<\\/")

    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>통합 검증 {_esc(condition)} — {_esc(episode_meta.get('run_id'))} ep{episode_meta.get('episode')}</title>
<style>{stylelock.CSS}{CSS}
:root {{ --w: {width}px; --fh: {FACE_H}px; --z: {zoom:.2f}; }}
</style></head>
<body>
<div class="bar">
  <b>{_esc(episode_meta.get('run_id'))} · {episode_meta.get('episode')}화 「{_esc(episode_meta.get('title'))}」 통합 검증</b>
  <span class="cond">조건 {_esc(condition)}{(' — ' + _esc(label)) if label else ''} ·
    Scene {len(scenes)} x 후보 {candidates} · <code>{_esc(cond_dir)}/</code></span>
  <span class="sp"></span>
  <label class="only-style"><input type="checkbox" id="face"> 얼굴만 크롭</label>
  <label class="only-zoom"><input type="checkbox" id="zoom"> 확대</label>
  <label class="only-style"><input type="checkbox" id="crop"> 크롭 편집</label>
  <span class="edit-only">
    <button class="primary" id="dlcrop">{stylelock.CROP_FILE} 내려받기</button>
    <button id="resetcrop">되돌리기</button>
    <span class="dirty" id="dirty"></span>
  </span>
  <button id="dlscore">{SCORE_FILE} 내려받기</button>
  <span class="tally" id="tally"></span>
</div>

<nav class="tabs">
  <button data-tab="bub">① 말풍선/효과음</button>
  <button data-tab="style">② 그림체</button>
  <button data-tab="read">③ 통독</button>
  <button data-tab="score">④ 채점</button>
</nav>

<section class="tab" id="tab-bub">
  <p class="lead">새 <code>scene_gen.txt</code> 규칙(빈 말풍선 + 효과음 레터링)이
     실제로 먹었는지 봅니다. <b>확대</b> 를 켜면 원본 픽셀에 가깝게 커집니다 —
     말풍선 안의 뭉개진 글자는 작게 보면 그냥 얼룩으로 지나갑니다.
     대사 줄 수와 그려진 말풍선 개수를 <b>세어서</b> 비교하세요.</p>
  {bub}
</section>

<section class="tab" id="tab-style">
  <p class="lead"><b>한 장 안이 아니라 Scene 과 Scene 사이를 봅니다.</b>
     한 이미지 안의 패널끼리는 같은 호출에서 같이 그려졌으니 일관된 게 당연합니다.
     진짜 문제는 서로 다른 호출로 나온 Scene {len(scenes)}장이 한 사람 손에서
     나온 것으로 보이는가입니다. <b>얼굴만 크롭</b> 으로 얼굴을 가로로 붙여 보세요 —
     차이는 얼굴에서 제일 먼저 드러납니다.
     상자가 얼굴을 못 잡았으면 <b>크롭 편집</b> 을 켜고 이미지 위에 끌어 그리세요.</p>
  {style}
</section>

<section class="tab" id="tab-read">
  <p class="lead">아래는 <code>{_esc(viewer_href)}</code> 를 그대로 띄운 것입니다 —
     흉내가 아니라 실제 Scene 뷰어입니다. <b>말풍선 편집</b> 을 켜고 그려진 말풍선
     위에 사각형을 끌어 그리면 대사가 순서대로 들어갑니다. 글자 크기는 영역에 맞춰
     자동으로 잡히고(최소 11px), 그래도 안 들어가면 영역이 빨갛게 표시됩니다.
     <b>bubbles.json 내려받기</b> 로 저장하면 <code>{VERIFY_DIR}/bubbles.json</code>
     자리에 넣으세요 — 본 파이프라인의 <code>bubbles.json</code> 과 섞이지 않습니다.
     프레임이 답답하면 <a href="{_esc(viewer_href)}" target="_blank">새 창으로</a>.</p>
  <div class="readwrap"><iframe src="{_esc(viewer_href)}" title="통독 (Scene 뷰어)"
    loading="lazy"></iframe></div>
</section>

<section class="tab" id="tab-score">
  <p class="lead">네 탭에서 누른 Y/N 이 여기 모입니다 (어느 쪽에서 눌러도 같은 칸입니다).
     <b>{SCORE_FILE} 내려받기</b> → 내려받은 파일을 <code>{_esc(str(ep_dir))}</code> 에
     <code>{SCORE_FILE}</code> 로 저장하세요. 열은
     <code>{', '.join(SCORE_HEADER)}</code> 이고 값은 <b>Y 또는 N</b> 입니다.
     점수를 적으면 다시 읽을 때 버려집니다 — "7점"은 다음에 뭘 고칠지 알려주지
     않지만 "말풍선빈칸 N"은 알려주기 때문입니다.</p>
  {score}
</section>

<footer>
  <p><b>이 한 벌로 넷을 동시에 잽니다.</b> Scene {len(scenes)}장 x 후보 {candidates}장을
     한 번 뽑아, 말풍선·효과음(①) / 그림체(②) / 통독(③) 을 같은 이미지로 봅니다.
     따로 검증했다면 생성 비용이 세 번 나갔을 것입니다.</p>
  <p>이미지는 <code>{_esc(cond_dir)}/</code> 에 있습니다. 기존
     <code>scene_{_esc(condition)}/</code> 는 건드리지 않았습니다 —
     둘을 나란히 두고 새 프롬프트 규칙의 전/후를 비교할 수 있습니다.</p>
  <p>{('그림체 탭에서 이미지를 찾지 못한 Scene: ' + ', '.join(str(n) for n in missing))
      if missing else
      '그림체·통독 탭은 후보 ' + ('picks.csv 기준' if picks else '1번') + '을 씁니다.'}
     후보를 바꾸려면 <code>{VERIFY_DIR}/contact_sheet_scene.html</code> 에서 고르고
     <code>picks.csv</code> 를 <code>{VERIFY_DIR}/</code> 에 저장한 뒤 같은 명령을
     다시 실행하세요 (이미 뽑아 둔 이미지를 다시 읽기만 하므로 0원입니다).</p>
  <p>생성 {datetime.now().isoformat(timespec='seconds')}</p>
</footer>
<script>const META = {meta};{stylelock.JS}{JS}</script>
</body></html>
"""
    out = page_path(ep_dir)
    out.write_text(doc, encoding="utf-8")
    return out, missing
