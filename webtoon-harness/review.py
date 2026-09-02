"""review.html — 완성된 1화를 읽으면서 컷마다 피드백을 남기는 화면.

컨택트 시트는 **후보를 고르는** 표다. 조건 x Scene 격자에 후보가 늘어서 있고,
완성본을 통독하기에는 맞지 않는다. 그런데 실제로 고칠 것이 보이는 순간은
"1화를 처음부터 끝까지 읽어 내려갈 때"다 — 옷이 바뀌었다, 이 컷은 얼굴이 작다,
여기서 흐름이 끊긴다 같은 것은 순서대로 봐야 보인다.

그래서 이 화면은 컨택트 시트와 반대로 만든다:

  - 조건 하나만. 채택본만. 후보를 나란히 놓지 않는다.
  - 읽는 순서 그대로 세로로 흐른다 (episode.png 와 같은 순서).
  - 그림 옆에 **그 장에 무엇을 담으려 했는지**를 붙인다 — 컷 서술·대사·
    나레이션·효과음·beat·size·작화. 의도와 결과를 나란히 놓아야 "왜 이렇게
    나왔지" 가 아니라 "무엇을 고쳐야지" 가 나온다.
  - 컷마다 / 장마다 / 화 전체에 각각 적을 칸.

저장은 이 저장소의 다른 화면과 같은 길이다: 입력 즉시 localStorage, 버튼으로
feedback.json 내려받기, 다음에 다시 만들면 박혀 들어와 복원. 서버가 없으므로
사람의 판단은 전부 파일로 돈다.

feedback.json 은 컨택트 시트와 **같이 쓴다.** 그쪽은 units 에, 여기는 scenes 와
cuts 에 적어서 서로 덮지 않는다.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import report
import bubbles
import scenegen

REVIEW_FILE = "review.html"

CSS = """
:root { color-scheme: light dark; --w: 560px; }
* { box-sizing: border-box; }
body { margin: 0; padding: 0 0 80px; background: #f6f6f7; color: #16181d;
       font: 14px/1.65 "Malgun Gothic", system-ui, sans-serif; }
header { position: sticky; top: 0; z-index: 9; background: #f6f6f7;
         border-bottom: 1px solid #d8dbe2; padding: 12px 20px; }
h1 { font-size: 18px; margin: 0 0 4px; }
.meta { color: #5a6070; font-size: 12.5px; }
.meta code { background: #e7e9ee; padding: 1px 5px; border-radius: 4px; }
.bar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 10px; }
button { font: inherit; padding: 6px 13px; border-radius: 6px; border: 1px solid #b9bec9;
         background: #fff; cursor: pointer; }
button.primary { background: #2f6fed; border-color: #2f6fed; color: #fff; font-weight: 600; }
button:hover { filter: brightness(0.97); }
.count { color: #5a6070; font-size: 12.5px; }
.wrap { max-width: 1180px; margin: 0 auto; padding: 20px; }
.general { background: #fff; border: 1px solid #d8dbe2; border-radius: 8px;
           padding: 14px 16px; margin-bottom: 22px; }
.scene { display: grid; grid-template-columns: var(--w) 1fr; gap: 22px;
         align-items: start; margin-bottom: 30px; }
.art { position: relative; }
/* 장과 장이 실제로 붙었을 때를 보려는 화면이라 그림 사이에 틈을 두지 않는다. */
.art img { width: 100%; display: block; border-radius: 0; background: #e7e9ee; }
.art.miss { height: 300px; border: 1px dashed #b9bec9; display: flex;
            align-items: center; justify-content: center; color: #8b91a0; }
.sceneno { position: absolute; left: 0; top: 0; background: #16181dcc; color: #fff;
           font-size: 12px; font-weight: 700; padding: 3px 9px; border-radius: 0 0 6px 0; }

/* 말풍선 글자 — 그림에는 빈 말풍선만 있고(scene.lettering: overlay) 한글은
   여기서 얹는다. 자리는 콘티의 bubble_zone 으로 만든 **초안**이라 그려진
   말풍선과 어긋날 수 있다. 그래서 옅은 테두리를 둬서 "여기가 글자 자리"임을
   보이게 하고, 뷰어(--view)에서 끌어 고칠 수 있게 해 둔다. */
.tx { position: absolute; box-sizing: border-box; display: flex;
      align-items: center; justify-content: center; text-align: center;
      padding: 2px 6px; line-height: 1.35; word-break: keep-all;
      font-weight: 600; color: #14161a; pointer-events: none;
      background: #ffffffe0; border: 1px solid #00000022; border-radius: 12px;
      text-shadow: 0 1px 0 #fff; }
.tx.narration { border-radius: 3px; background: #fffdf2ee; font-weight: 700;
                border-color: #0000001f; }
.tx.thought   { border-radius: 999px; background: #fbfaffe6; font-style: italic; }
.tx.screen    { border-radius: 4px; background: #101318e8; color: #eef1f6;
                font-weight: 500; text-shadow: none; border-color: #ffffff2a;
                white-space: pre-line; }
/* 글자를 끄고 그림만 보는 스위치 */
body.notext .tx { display: none; }
.txbar { display: flex; gap: 12px; align-items: center; margin: 0 0 10px;
         font-size: 13px; color: #4a505c; }
.txbar label { display: flex; gap: 5px; align-items: center; cursor: pointer; }
.side { min-width: 0; }
.cut { background: #fff; border: 1px solid #d8dbe2; border-radius: 8px;
       padding: 12px 14px; margin-bottom: 12px; }
.cuthead { display: flex; gap: 7px; align-items: center; flex-wrap: wrap;
           font-weight: 700; margin-bottom: 7px; }
.tag { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 999px;
       background: #e7e9ee; color: #45506a; }
.tag.sd { background: #ffe9b8; color: #6b4b00; }
.tag.emphasis { background: #ffd9d9; color: #8a1d1d; }
.kr { white-space: pre-wrap; margin-bottom: 7px; }
.line { font-size: 13px; margin: 2px 0; }
.line b { color: #5a6070; font-weight: 600; font-size: 11.5px; margin-right: 5px; }
.d { color: #8a4b00; } .n { color: #1d5c8a; } .t { color: #6b3fa0; } .s { color: #8a1d5c; }
.en { font-size: 12px; color: #364; background: #f2f7f2; border-left: 3px solid #9ec39e;
      padding: 7px 9px; white-space: pre-wrap; margin: 8px 0; }
label { display: block; font-size: 11.5px; color: #5a6070; margin: 8px 0 3px; }
textarea { font: inherit; font-size: 13px; width: 100%; min-height: 52px; padding: 7px 9px;
           border: 1px solid #b9bec9; border-radius: 6px; background: #fffdf5;
           resize: vertical; color: inherit; }
textarea:focus { outline: 2px solid #2f6fed; outline-offset: -1px; }
textarea.filled { border-color: #d8a200; background: #fff8e2; }
.scenefb { background: #fff; border: 1px solid #d8dbe2; border-radius: 8px;
           padding: 12px 14px; }
.help { color: #5a6070; font-size: 12.5px; margin-top: 26px; }
.ghead { margin-bottom: 10px; }
.three { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 12px; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.where { font-weight: 400; opacity: .7; font-size: 10.5px; }
@media (max-width: 980px) {
  .scene { grid-template-columns: 1fr; }
  .three, .two { grid-template-columns: 1fr; }
}
@media (prefers-color-scheme: dark) {
  body { background: #16181d; color: #e6e8ee; }
  header { background: #16181d; border-color: #2c313c; }
  .cut, .general, .scenefb { background: #1d2027; border-color: #2c313c; }
  button { background: #232833; color: #e6e8ee; border-color: #3a4150; }
  button.primary { background: #2f6fed; border-color: #2f6fed; color: #fff; }
  textarea { background: #1f2229; border-color: #3a4150; }
  textarea.filled { background: #2b2718; border-color: #7a6320; }
  .en { background: #1b241b; border-color: #3f5f3f; color: #cfe0cf; }
  .meta, .count, .help, label { color: #9aa2b4; }
  .meta code { background: #232833; } .tag { background: #232833; color: #b9c2d6; }
}
"""

JS = """
const KEY = "webtoon-feedback:" + DATA.run_id + ":ep" + DATA.episode;
const LAYERS = ["units", "scenes", "cuts", "cuts_art", "cuts_story"];
const GENERAL = ["general", "general_art", "general_story"];
// 그림 쪽으로 갈 것과 스토리 쪽으로 갈 것. 세는 데만 쓴다.
const ART = ["scenes", "cuts_art"], STORY = ["cuts_story"];
let fb = {};

function load() {
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) {}
  const base = stored && typeof stored === "object" ? stored : DATA.saved;
  fb = {};
  GENERAL.forEach(k => fb[k] = String((base && base[k]) || ""));
  LAYERS.forEach(k => fb[k] = Object.assign({}, (base && base[k]) || {}));
  document.querySelectorAll("textarea[data-layer]").forEach(t => {
    t.value = (fb[t.dataset.layer] || {})[t.dataset.key] || "";
    t.classList.toggle("filled", !!t.value.trim());
  });
  document.querySelectorAll("textarea[data-general]").forEach(t => {
    t.value = fb[t.dataset.general] || "";
    t.classList.toggle("filled", !!t.value.trim());
  });
  count();
}
function save() { try { localStorage.setItem(KEY, JSON.stringify(fb)); } catch (e) {} }
function tally(keys, generals) {
  let n = 0;
  keys.forEach(L => Object.values(fb[L] || {}).forEach(v => { if (v && v.trim()) n++; }));
  generals.forEach(g => { if ((fb[g] || "").trim()) n++; });
  return n;
}
function count() {
  const art = tally(ART, ["general_art"]);
  const story = tally(STORY, ["general_story"]);
  const etc = tally(["cuts", "units"], ["general"]);
  const bits = [];
  if (art) bits.push("🎨 그림 " + art);
  if (story) bits.push("📖 스토리 " + story);
  if (etc) bits.push("🧩 종합 " + etc);
  document.getElementById("count").textContent = bits.length ? bits.join(" · ") : "아직 없음";
}
function json() {
  const trim = o => {
    const out = {};
    Object.keys(o || {}).forEach(k => { if (o[k] && o[k].trim()) out[k] = o[k]; });
    return out;
  };
  const payload = {run_id: DATA.run_id, episode: DATA.episode,
                   saved_at: new Date().toISOString().slice(0, 19)};
  GENERAL.forEach(k => payload[k] = fb[k] || "");
  LAYERS.forEach(k => payload[k] = trim(fb[k]));
  return JSON.stringify(payload, null, 2);
}
function download() {
  const blob = new Blob([json()], {type: "application/json;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "feedback.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
async function copy() {
  try { await navigator.clipboard.writeText(json()); alert("feedback.json 내용을 복사했습니다."); }
  catch (e) { window.prompt("복사해서 feedback.json 으로 저장하세요:", json()); }
}
function jump(d) {
  const boxes = [...document.querySelectorAll("textarea")];
  const i = boxes.indexOf(document.activeElement);
  const next = boxes[(i < 0 ? 0 : i + d + boxes.length) % boxes.length];
  if (next) { next.focus(); next.scrollIntoView({block: "center", behavior: "smooth"}); }
}
document.addEventListener("input", e => {
  const t = e.target;
  if (t.matches("textarea[data-layer]")) {
    fb[t.dataset.layer][t.dataset.key] = t.value;
  } else if (t.matches("textarea[data-general]")) {
    fb[t.dataset.general] = t.value;
  } else { return; }
  t.classList.toggle("filled", !!t.value.trim());
  save(); count();
});
// 적을 것이 많을 때 마우스로 옮겨 다니면 흐름이 끊긴다.
document.addEventListener("keydown", e => {
  if (e.ctrlKey && e.key === "Enter") { e.preventDefault(); jump(1); }
});
load();
"""


def _esc(text: Any) -> str:
    return html.escape(str(text or ""))


def _lines(cut: dict[str, Any]) -> str:
    rows = []
    for key, label, cls in (("dialogue", "대사", "d"), ("narration", "나레이션", "n"),
                            ("thought", "속마음", "t"), ("sfx", "효과음", "s")):
        text = str(cut.get(key) or "").strip()
        if text:
            rows.append(f'<div class="line {cls}"><b>{label}</b>{_esc(text)}</div>')
    return "".join(rows)


def _overlay(regions: list[Any]) -> str:
    """말풍선 자리에 얹을 글자. 좌표는 전부 이미지 대비 퍼센트다.

    글자 크기는 영역 폭과 글자 수로 어림한다 — 뷰어처럼 실측해 맞추지는
    않는다. 이 화면은 "대사가 어디에 어떻게 놓이는가"를 읽는 자리이고,
    한 글자까지 맞추는 것은 뷰어(--view)의 일이다.
    """
    out = []
    for r in regions:
        raw = str(getattr(r, "kind", "") or "")
        kind = "screen" if raw == "screen_text" else bubbles.kind_of(r.text)
        body = str(r.text or "").strip()
        # 표시 규약의 겉껍질은 벗긴다 — [나레이션] · (속마음)
        if kind == "narration" and body.startswith("[") and body.endswith("]"):
            body = body[1:-1]
        elif kind == "thought" and body.startswith("(") and body.endswith(")"):
            body = body[1:-1]
        n = max(len(body), 1)
        # 폭(%) 대비 글자 수로 대충. 길면 작게, 짧으면 크게.
        size = max(9.0, min(19.0, r.w * 0.62 / max(1.0, n ** 0.5) * 2.2))
        out.append(
            f'<div class="tx {kind}" style="left:{r.x:.2f}%;top:{r.y:.2f}%;'
            f'width:{r.w:.2f}%;min-height:{r.h:.2f}%;font-size:{size:.1f}px">'
            f'{_esc(body)}</div>')
    return "".join(out)


def build(ep_dir: Path, episode_meta: dict[str, Any], scenes: list[Any],
          cond: str, info: dict[str, str],
          file_pattern: str = "{cond}/scene{n}_c{k}.png",
          picks: dict[tuple[str, int], int] | None = None) -> Path:
    """review.html 생성. scenes 는 scenegen.Scene 목록."""
    saved = report.read_feedback(ep_dir)
    picks = picks or {}

    # 말풍선 글자. 사람이 뷰어에서 놓은 것(bubbles.json)이 있으면 그것을,
    # 없으면 콘티의 bubble_zone 으로 만든 초안을 쓴다.
    rows = [{"scene_number": sc.scene_number,
             "cut_numbers": list(sc.cut_numbers),
             "lines": scenegen.overlay_lines(sc.cuts)} for sc in scenes]
    try:
        placed, _warn, _had = bubbles.load(ep_dir, rows)
    except bubbles.BubbleError:
        placed = bubbles.auto_regions(
            rows, {r["scene_number"]: r["cut_numbers"] for r in rows})

    blocks = []
    for sc in scenes:
        n = sc.scene_number
        k = picks.get((cond, n)) or 1
        rel = file_pattern.replace("{cond}", cond).replace("{n}", str(n)).replace("{k}", str(k))
        if not (ep_dir / rel).exists() and k != 1:
            rel = file_pattern.replace("{cond}", cond).replace("{n}", str(n)).replace("{k}", "1")
        art = (f'<img src="{_esc(rel)}" alt="Scene {n}" loading="lazy">'
               f'{_overlay(placed.get(n) or [])}'
               if (ep_dir / rel).exists() else
               '<div class="art miss">이미지 없음</div>')

        cuts = []
        for i, cut in enumerate(sc.cuts):
            num = cut.get("cut_number")
            style = str(cut.get("render_style") or "normal")
            tags = "".join(
                f'<span class="tag {t if t in ("sd", "emphasis") else ""}">{_esc(v)}</span>'
                for t, v in (("beat", cut.get("beat")), ("size", cut.get("size")),
                             (style, style)) if v)
            panel = sc.panels[i] if i < len(sc.panels) else ""
            cuts.append(
                f'<div class="cut">'
                f'<div class="cuthead">컷 {num}{tags}</div>'
                f'<div class="kr">{_esc(cut.get("description"))}</div>'
                f'{_lines(cut)}'
                f'<div class="en">{_esc(panel) or "(패널 서술 없음)"}</div>'
                f'<div class="two">'
                f'<div><label for="a{num}">🎨 그림</label>'
                f'<textarea id="a{num}" data-layer="cuts_art" data-key="{num}" '
                f'placeholder="옷이 다름, 얼굴이 작음, 서술과 다르게 그려짐 …">'
                f'</textarea></div>'
                f'<div><label for="t{num}">📖 스토리</label>'
                f'<textarea id="t{num}" data-layer="cuts_story" data-key="{num}" '
                f'placeholder="이 대사 어색함, 이 컷 필요 없음, 흐름이 끊김 …">'
                f'</textarea></div>'
                f'</div></div>')

        blocks.append(
            f'<section class="scene">'
            f'<div class="art"><span class="sceneno">Scene {n} · 컷 '
            f'{_esc(", ".join(str(c.get("cut_number")) for c in sc.cuts))}</span>{art}</div>'
            f'<div class="side">{"".join(cuts)}'
            f'<div class="scenefb"><label for="s{n}">이 장 전체 피드백 '
            f'(구도·이음매·분위기)</label>'
            f'<textarea id="s{n}" data-layer="scenes" data-key="{n}" '
            f'placeholder="위 장과 이어지는가, 배치가 읽히는가, 톤이 맞는가 …">'
            f'</textarea></div></div></section>')

    data = json.dumps({
        "run_id": episode_meta["run_id"], "episode": episode_meta["episode"],
        "saved": saved,
    }, ensure_ascii=False).replace("</", "<\\/")

    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>1화 검토 — {_esc(episode_meta['run_id'])} ep{episode_meta['episode']}</title>
<style>{CSS}</style></head><body>
<header>
<h1>{_esc(episode_meta['run_id'])} · {episode_meta['episode']}화 —
  {_esc(episode_meta.get('title'))}</h1>
<div class="meta">Scene {len(scenes)}개 · 조건 <code>{_esc(cond)}</code> ·
  그림체 <code>{_esc(info.get('style_name'))}</code> ·
  이미지 모델 <code>{_esc(info.get('image_model'))}</code></div>
<div class="bar">
  <button class="primary" onclick="download()">feedback.json 내려받기</button>
  <button onclick="copy()">복사</button>
  <span class="count" id="count"></span>
  <span class="count">· Ctrl+Enter 로 다음 칸</span>
  <label class="txbar" style="margin:0"><input type="checkbox" id="txoff"
    onchange="document.body.classList.toggle('notext', this.checked)"> 대사 숨기기</label>
</div>
</header>
<div class="wrap">
<div class="general">
  <div class="ghead"><b>1화 전체 피드백</b> — 컷 하나가 아니라 전반에 걸친 것.
    <span class="count">고칠 곳이 다르니 나눠 적으세요.</span></div>
  <div class="three">
    <div><label for="fb-general_art">🎨 그림 전체 <span class="where">webtoon-harness</span></label>
      <textarea id="fb-general_art" data-general="general_art"
        placeholder="예) 장과 장 사이가 끊긴다 / 그림체가 시트에 끌려간다 / 효과음이 부족하다"></textarea></div>
    <div><label for="fb-general_story">📖 스토리 전체 <span class="where">story-harness</span></label>
      <textarea id="fb-general_story" data-general="general_story"
        placeholder="예) 1화만 보고는 안 궁금하다 / 나레이션이 그림을 반복한다 / 훅이 약하다"></textarea></div>
    <div><label for="fb-general">🧩 종합 <span class="where">둘 다 / 구조</span></label>
      <textarea id="fb-general" data-general="general"
        placeholder="예) 컷을 더 묶어야 한다 / 화당 비용이 비싸다 / 순서를 바꾸고 싶다"></textarea></div>
  </div>
</div>
{''.join(blocks)}
<p class="help">
  적는 즉시 브라우저에 저장됩니다(새로고침해도 남습니다).
  <b>feedback.json 내려받기</b> → 이 폴더(<code>{_esc(str(ep_dir))}</code>)에
  <code>feedback.json</code> 으로 저장하면 다음에 다시 만들 때 복원됩니다.<br>
  피드백은 <u>사람이 보는 기록</u>입니다 — 코드가 읽어서 프롬프트에 자동으로 넣지
  않습니다. 무엇을 바꿔서 좋아졌는지 알 수 없게 되기 때문입니다.
  컨택트 시트의 피드백과 같은 파일을 쓰되 서로 덮지 않습니다.
</p>
</div>
<script>const DATA = {data};{JS}</script>
</body></html>
"""
    out = ep_dir / REVIEW_FILE
    out.write_text(doc, encoding="utf-8")
    return out
