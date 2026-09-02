"""strip.html — 완성된 세로 웹툰을 보면서 **말풍선을 끌어 고치는** 화면.

## 왜 필요한가

말풍선 자리는 vision 이 찾아 준다(그림에서 인물과 빈 공간을 좌표로). 실측으로
대체로 맞지만 **보장은 아니다** — 빈 자리로 고른 곳이 사실 중요한 소품 위일
수도 있고, 인물이 둘일 때 꼬리가 애매할 수도 있다.

그때 이미지를 다시 뽑으면 컷당 $0.13 이 나간다. 좌표 하나 때문에 그러는 것은
말이 안 된다. 그래서 **좌표와 글자만 고치는 자리**를 둔다 — 여기서 끌어 옮기고
내려받아 저장하면, 다시 조립할 때 API 호출이 0회다.

## 화면이 하는 일

  · 컷을 세로로, **여백까지 그대로** 보여 준다 (episode.png 와 같은 배치)
  · 말풍선을 그 위에 얹는다. 끌어 옮기고, 모서리로 크기를 바꾸고,
    더블클릭으로 글자를 고치고, 꼬리 점을 끌어 방향을 바꾼다
  · [완성본 보기] 로 편집 손잡이를 숨기면 실제로 나올 모습이 된다
  · [layout_bubbles.json 내려받기] → 같은 폴더에 저장 → 다시 조립

좌표는 **이미지 대비 퍼센트**로 다룬다. 창을 줄여도 풍선이 그 자리에 남아야
하기 때문이다. 파일에는 픽셀로 되돌려 적는다 — 그림을 그리는 쪽(PIL)이 픽셀을
쓰므로, 화면과 결과가 같은 값을 보게 하려면 한 곳에서만 환산해야 한다.

서버가 없으므로 저장은 localStorage + 내려받기다 (picks.csv · feedback.json 과
같은 길).
"""

from __future__ import annotations

import html
import json
import urllib.parse
from pathlib import Path
from typing import Any

import report
import strip
import vision

VIEW_FILE = "strip.html"

CSS = """
:root { color-scheme: light dark; --page: 520px; }
* { box-sizing: border-box; }
body { margin: 0; padding: 0 0 120px; background: #2a2d34; color: #e8eaf0;
       font: 14px/1.6 "Malgun Gothic", system-ui, sans-serif; }
header { position: sticky; top: 0; z-index: 50; background: #1b1e24ee;
         backdrop-filter: blur(6px); border-bottom: 1px solid #3a4150;
         padding: 10px 18px; }
h1 { font-size: 16px; margin: 0 0 3px; }
.meta { color: #99a1b3; font-size: 12.5px; }
.bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 9px; }
button { font: inherit; padding: 6px 13px; border-radius: 6px; border: 1px solid #4a5162;
         background: #2f343f; color: #e8eaf0; cursor: pointer; }
button.primary { background: #2f6fed; border-color: #2f6fed; font-weight: 600; }
button.on { background: #1d7a4d; border-color: #1d7a4d; }
button:hover { filter: brightness(1.12); }
.hint { color: #99a1b3; font-size: 12px; }

/* 세로 스크롤 본체 — 여백까지 episode.png 와 같은 비율로 */
.strip { width: var(--page); margin: 22px auto; }
.cut { position: relative; width: 100%; background: #fff; }
.cut img { width: 100%; display: block; }
.cutno { position: absolute; left: 0; top: 0; z-index: 5;
         background: #16181dcc; color: #fff; font-size: 11px; font-weight: 700;
         padding: 2px 8px; border-radius: 0 0 5px 0; }
body.done .cutno { display: none; }
.gap { width: 100%; background: #fff; }

/* 말풍선 — 화면에서 보이는 모양은 PIL 이 그릴 것의 근사다 */
.bb { position: absolute; display: flex; align-items: center; justify-content: center;
      text-align: center; padding: 6px 10px; cursor: move; user-select: none;
      color: #14161a; font-weight: 600; word-break: keep-all; line-height: 1.34;
      background: #fff; border: 2px solid #14161a; border-radius: 50%; }
.bb.narration { border-radius: 3px; border-width: 1px; border-color: #14161a55;
                background: #ffffffea; font-weight: 700; }
.bb.thought   { border-radius: 50%; border-style: solid; background: #fffffff2; }
.bb.shout     { border-radius: 12% 40% 14% 38% / 40% 14% 38% 12%; border-width: 3px; }
.bb.whisper   { border-radius: 40%; border-style: dashed; border-width: 1.5px; }
.bb.sel { outline: 2px solid #2f6fed; outline-offset: 3px; }
.bb .hd { position: absolute; right: -7px; bottom: -7px; width: 14px; height: 14px;
          background: #2f6fed; border: 2px solid #fff; border-radius: 3px;
          cursor: nwse-resize; }
body.done .bb { cursor: default; }
body.done .bb .hd { display: none; }
body.done .bb.sel { outline: none; }

/* 꼬리 — 풍선 중심에서 가리키는 점까지. 실제 그림은 삼각형이지만
   여기서는 방향만 확인하면 되므로 선 + 점으로 그린다. */
.tail { position: absolute; z-index: 4; pointer-events: none; overflow: visible; }
.tail line { stroke: #14161a; stroke-width: 2.5; }
.tail circle { fill: #2f6fed; stroke: #fff; stroke-width: 2; }
body.done .tail circle { display: none; }
.tailgrab { position: absolute; width: 16px; height: 16px; margin: -8px 0 0 -8px;
            border-radius: 50%; background: #2f6fed88; cursor: grab; z-index: 6; }
body.done .tailgrab { display: none; }

.editor { position: fixed; left: 50%; bottom: 22px; transform: translateX(-50%);
          z-index: 60; background: #1b1e24; border: 1px solid #4a5162;
          border-radius: 8px; padding: 10px 12px; width: min(680px, 92vw);
          display: none; box-shadow: 0 8px 30px #0008; }
.editor.open { display: block; }
.editor textarea { width: 100%; min-height: 58px; font: inherit; font-size: 13px;
                   background: #2f343f; color: #e8eaf0; border: 1px solid #4a5162;
                   border-radius: 5px; padding: 7px 9px; resize: vertical; }
.editor .row { display: flex; gap: 8px; align-items: center; margin-top: 7px; }
.editor .who { color: #99a1b3; font-size: 12px; }
"""

JS = r"""
const KEY = "webtoon-strip:" + DATA.run_id + ":ep" + DATA.episode;
let layout = {};          // {cut1: [ {kind,text,box:[x0,y0,x1,y1],tail:[x,y],auto} ]}
let sel = null;           // {cut, idx}

function load() {
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) {}
  layout = stored && typeof stored === "object" ? stored : structuredClone(DATA.layout);
  render();
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(layout)); } catch (e) {}
  const n = Object.values(layout).flat().filter(b => b && b.auto === false).length;
  document.getElementById("count").textContent = n ? `${n}개 직접 고침` : "자동 배치 그대로";
}

/* 파일은 픽셀, 화면은 %. 환산은 여기 한 곳에서만 한다. */
function pct(cut, box) {
  const s = DATA.sizes[cut];
  return { l: box[0] / s[0] * 100, t: box[1] / s[1] * 100,
           w: (box[2] - box[0]) / s[0] * 100, h: (box[3] - box[1]) / s[1] * 100 };
}
function toPx(cut, l, t, w, h) {
  const s = DATA.sizes[cut];
  return [Math.round(l / 100 * s[0]), Math.round(t / 100 * s[1]),
          Math.round((l + w) / 100 * s[0]), Math.round((t + h) / 100 * s[1])];
}

function render() {
  document.querySelectorAll(".bb,.tail,.tailgrab").forEach(e => e.remove());
  for (const [cut, list] of Object.entries(layout)) {
    const host = document.getElementById(cut);
    if (!host || !Array.isArray(list)) continue;
    list.forEach((b, i) => {
      const p = pct(cut, b.box);
      const el = document.createElement("div");
      el.className = "bb " + (b.kind || "dialogue");
      el.style.cssText = `left:${p.l}%;top:${p.t}%;width:${p.w}%;height:${p.h}%`;
      el.dataset.cut = cut; el.dataset.idx = i;
      el.textContent = b.text || "";
      // 글자가 상자에 맞게 — 폭과 글자 수로 어림한다 (PIL 도 같은 방식)
      const box = host.getBoundingClientRect();
      const wpx = p.w / 100 * box.width, hpx = p.h / 100 * box.height;
      const n = Math.max((b.text || "").length, 1);
      el.style.fontSize = Math.max(9, Math.min(hpx * 0.34, wpx * 1.5 / Math.sqrt(n))) + "px";
      const hd = document.createElement("div"); hd.className = "hd";
      el.appendChild(hd);
      host.appendChild(el);

      if (b.tail) {
        const t = pct(cut, [b.tail[0], b.tail[1], b.tail[0], b.tail[1]]);
        const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
        svg.setAttribute("class", "tail");
        svg.style.cssText = "left:0;top:0;width:100%;height:100%";
        svg.innerHTML =
          `<line x1="${p.l + p.w / 2}%" y1="${p.t + p.h / 2}%" x2="${t.l}%" y2="${t.t}%"/>` +
          `<circle cx="${t.l}%" cy="${t.t}%" r="5"/>`;
        host.appendChild(svg);
        const g = document.createElement("div");
        g.className = "tailgrab";
        g.style.cssText = `left:${t.l}%;top:${t.t}%`;
        g.dataset.cut = cut; g.dataset.idx = i;
        host.appendChild(g);
      }
    });
  }
  save();
}

/* ---- 끌기: 이동 / 크기 / 꼬리 ---- */
let drag = null;
document.addEventListener("mousedown", e => {
  if (document.body.classList.contains("done")) return;
  const grab = e.target.closest(".tailgrab");
  const hd = e.target.classList && e.target.classList.contains("hd");
  const bb = e.target.closest(".bb");
  if (grab) {
    drag = { mode: "tail", cut: grab.dataset.cut, idx: +grab.dataset.idx,
             host: grab.parentElement };
  } else if (bb) {
    pick(bb.dataset.cut, +bb.dataset.idx);
    drag = { mode: hd ? "size" : "move", cut: bb.dataset.cut, idx: +bb.dataset.idx,
             host: bb.parentElement, x: e.clientX, y: e.clientY,
             box: layout[bb.dataset.cut][+bb.dataset.idx].box.slice() };
  } else { return; }
  e.preventDefault();
});
document.addEventListener("mousemove", e => {
  if (!drag) return;
  const r = drag.host.getBoundingClientRect();
  const s = DATA.sizes[drag.cut];
  const b = layout[drag.cut][drag.idx];
  if (drag.mode === "tail") {
    b.tail = [Math.round((e.clientX - r.left) / r.width * s[0]),
              Math.round((e.clientY - r.top) / r.height * s[1])];
  } else {
    const dx = (e.clientX - drag.x) / r.width * s[0];
    const dy = (e.clientY - drag.y) / r.height * s[1];
    const o = drag.box;
    if (drag.mode === "move") {
      b.box = [o[0] + dx, o[1] + dy, o[2] + dx, o[3] + dy].map(Math.round);
    } else {
      b.box = [o[0], o[1], Math.max(o[0] + 40, o[2] + dx),
               Math.max(o[1] + 26, o[3] + dy)].map(Math.round);
    }
  }
  b.auto = false;
  render();
});
document.addEventListener("mouseup", () => { drag = null; });

/* ---- 글자 고치기 ---- */
function pick(cut, idx) {
  sel = { cut, idx };
  document.querySelectorAll(".bb").forEach(e => e.classList.toggle(
    "sel", e.dataset.cut === cut && +e.dataset.idx === idx));
  const b = layout[cut][idx];
  document.getElementById("who").textContent =
    `${cut} · ${b.kind}${b.auto === false ? " · 직접 고침" : " · 자동"}`;
  document.getElementById("txt").value = b.text || "";
  document.getElementById("ed").classList.add("open");
}
document.addEventListener("input", e => {
  if (e.target.id !== "txt" || !sel) return;
  const b = layout[sel.cut][sel.idx];
  b.text = e.target.value; b.auto = false;
  render();
  document.querySelectorAll(".bb").forEach(el => el.classList.toggle(
    "sel", el.dataset.cut === sel.cut && +el.dataset.idx === sel.idx));
});

function resetOne() {
  if (!sel) return;
  const src = DATA.layout[sel.cut];
  if (src && src[sel.idx]) layout[sel.cut][sel.idx] = structuredClone(src[sel.idx]);
  render(); pick(sel.cut, sel.idx);
}
function download() {
  const out = { "_읽는 법": DATA.note1, "_고치는 법": DATA.note2, ...layout };
  const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "layout_bubbles.json"; a.click();
  document.getElementById("count").textContent =
    "내려받았습니다 — ep 폴더에 저장하고 --sheet-only 로 다시 조립하세요";
}
function toggleDone(btn) {
  const on = document.body.classList.toggle("done");
  btn.classList.toggle("on", on);
  btn.textContent = on ? "편집으로 돌아가기" : "완성본 보기";
  if (on) document.getElementById("ed").classList.remove("open");
}
function widen(d) {
  const el = document.documentElement;
  const cur = parseInt(getComputedStyle(el).getPropertyValue("--page")) || 520;
  el.style.setProperty("--page", Math.max(280, Math.min(900, cur + d)) + "px");
  render();
}
window.addEventListener("resize", render);
load();
"""


def build(ep_dir: Path, meta: dict[str, Any], cuts: list[dict[str, Any]],
          cond: str) -> Path:
    """strip.html 생성. 컷 이미지·layout_bubbles.json 을 읽어 붙인다."""
    from PIL import Image

    layout = {k: v for k, v in vision.load_layout(ep_dir).items()
              if not str(k).startswith("_")}
    # 채택본을 따라간다. 예전에는 `_c1` 이 박혀 있었는데, 최종본을 만드는
    # write_strip 은 picks.csv 를 보므로 후보가 2장 이상이면 이 화면과
    # episode.png 가 **서로 다른 후보**를 보여주게 된다(#113). 지금은 후보가
    # 1장이라 값이 같지만, 다른 곳이 이미 채택을 따르는 이상 여기도 따라야 한다.
    picks = report.load_picks(ep_dir)
    blocks, sizes = [], {}
    for i, c in enumerate(cuts):
        n = int(c["cut_number"])
        k = picks.get((cond, n)) or 1
        rel = f"{cond}/cut{n}_c{k}.png"
        src = ep_dir / rel
        if not src.exists() and k != 1:
            rel = f"{cond}/cut{n}_c1.png"     # 채택 파일이 사라졌으면 c1 로 되돌린다
            src = ep_dir / rel
        if not src.exists():
            continue
        with Image.open(src) as im:
            sizes[f"cut{n}"] = [im.width, im.height]
        # 조건 이름에 '+' 가 들어간다(S+). URL 에서 '+' 는 공백으로 읽히므로
        # 인코딩하지 않으면 이미지가 통째로 안 뜬다 — 화면이 비어 보인다.
        url = "/".join(urllib.parse.quote(part, safe="") for part in rel.split("/"))
        blocks.append(
            f'<div class="cut" id="cut{n}">'
            f'<div class="cutno">컷 {n}</div>'
            f'<img src="{html.escape(url)}" alt="컷 {n}"></div>')
        # 컷 사이 여백 — episode.png 와 같은 비율(컷 폭 대비)로 띄운다.
        if i < len(cuts) - 1:
            ratio = strip.GAP_RATIO.get(
                max(0, min(3, int(c.get("gap_after") or 1))), 0.05)
            blocks.append(f'<div class="gap" style="height:calc(var(--page)*{ratio})"></div>')

    data = {
        "run_id": meta.get("run_id", ""), "episode": meta.get("episode", 1),
        "layout": layout, "sizes": sizes,
        "note1": "cut<번호> 마다 말풍선 목록. box 는 [x0,y0,x1,y1] 픽셀, "
                 "tail 은 꼬리가 가리킬 [x,y] (null 이면 꼬리 없음).",
        "note2": "이 파일을 ep 폴더에 저장하고 --sheet-only 로 다시 조립하면 "
                 "API 호출 없이 반영됩니다. auto:false 는 사람이 고친 것이라 "
                 "다음 실행이 덮어쓰지 않습니다.",
    }
    page = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>{html.escape(str(meta.get('title') or ''))} — 세로 웹툰 편집</title>
<style>{CSS}</style></head><body>
<header>
  <h1>{html.escape(str(meta.get('title') or ''))} · {meta.get('episode', 1)}화</h1>
  <div class="meta">컷 {len(sizes)}개 · 조건 <code>{html.escape(cond)}</code> ·
    말풍선을 끌어 옮기고, 모서리로 크기를, 파란 점으로 꼬리 방향을 바꿉니다</div>
  <div class="bar">
    <button class="primary" onclick="download()">layout_bubbles.json 내려받기</button>
    <button onclick="toggleDone(this)">완성본 보기</button>
    <button onclick="resetOne()">선택한 것 자동배치로</button>
    <button onclick="widen(-80)">좁게</button><button onclick="widen(80)">넓게</button>
    <span class="hint" id="count"></span>
  </div>
</header>
<div class="strip">{''.join(blocks)}</div>
<div class="editor" id="ed">
  <div class="who" id="who"></div>
  <textarea id="txt" placeholder="말풍선 글자"></textarea>
  <div class="row"><span class="hint">고치면 바로 반영됩니다. 저장은 위의
    [내려받기] 로.</span></div>
</div>
<script>const DATA = {json.dumps(data, ensure_ascii=False)};</script>
<script>{JS}</script>
</body></html>"""
    out = ep_dir / VIEW_FILE
    out.write_text(page, encoding="utf-8")
    return out
