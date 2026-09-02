"""contact_sheet.html 생성 + picks.csv / feedback.json 읽기·쓰기 규약.

서버가 없으므로 채택 기록은 이렇게 돈다:
  1) 브라우저에서 후보를 클릭 → localStorage 에 즉시 저장 (새로고침해도 유지)
  2) [picks.csv 내려받기] 버튼 → 같은 폴더에 picks.csv 로 저장
  3) run.py 가 COND_D 실행 때 그 picks.csv 를 읽어 직전 컷 채택 이미지를 첨부
  4) contact_sheet 를 다시 만들면 저장된 picks.csv 가 HTML 에 박혀 들어와
     체크 상태가 복원된다 (file:// 에서는 CSV 를 fetch 할 수 없기 때문)

피드백도 같은 길로 돈다 (feedback.json). 채택은 "어느 장이 나은가"만 남기는데,
정작 고쳐야 할 것은 "왜 별로인가"다 — 옷이 바뀐다, 조연이 매번 다른 사람이다,
연출이 만화 페이지 같다. 그건 채택 체크로는 적을 자리가 없어서 지금까지 채팅
같은 하네스 밖으로 흘렀다. 컷 옆에 칸을 두면 보면서 바로 적을 수 있고, 다음에
시트를 다시 만들 때 그대로 박혀 들어와 무엇을 고치려 했는지가 남는다.

피드백은 코드가 읽어서 프롬프트에 넣지 않는다. 사람이 보는 기록이다 — 자동으로
프롬프트에 밀어 넣으면 "무엇을 바꿔서 좋아졌는지"를 알 수 없게 된다.
"""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path
from typing import Any

PICKS_HEADER = ["run_id", "episode", "condition", "cut_number", "candidate", "file", "picked_at"]
FEEDBACK_FILE = "feedback.json"


# --------------------------------------------------------------------------- #
# picks.csv
# --------------------------------------------------------------------------- #
def picks_path(ep_dir: Path) -> Path:
    return ep_dir / "picks.csv"


def read_rows(ep_dir: Path) -> list[dict[str, str]]:
    """picks.csv 를 행 그대로 읽는다. 파일이 없으면 빈 리스트."""
    path = picks_path(ep_dir)
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def load_picks(ep_dir: Path) -> dict[tuple[str, int], int]:
    """{(condition, cut_number): candidate}. 파일이 없으면 빈 dict."""
    path = picks_path(ep_dir)
    if not path.exists():
        return {}
    picks: dict[tuple[str, int], int] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                cond = str(row["condition"]).strip()
                cut = int(row["cut_number"])
                cand = int(row["candidate"])
            except (KeyError, TypeError, ValueError):
                continue
            if cond and cand > 0:
                picks[(cond, cut)] = cand
    return picks


# --------------------------------------------------------------------------- #
# feedback.json
# --------------------------------------------------------------------------- #
def feedback_path(ep_dir: Path) -> Path:
    return ep_dir / FEEDBACK_FILE


# 피드백은 **어디로 가야 하는지**로 나뉜다. "옷이 컷마다 바뀐다" 는 이 저장소가
# 고칠 일이고, "이 장면이 재미없다" 는 story-harness 가 고칠 일이다. 한 칸에
# 섞어 적으면 나중에 무엇을 어디서 고쳐야 하는지 다시 분류해야 한다.
#
#   cuts_art     컷 하나의 그림   — 옷이 다르다, 얼굴이 작다, 서술과 다르다
#   cuts_story   컷 하나의 내용   — 이 대사는 어색하다, 이 컷은 필요 없다
#   scenes       장 단위          — 구도, 이음매, 분위기
#   units        컨택트 시트가 쓰는 자리 (후보 고르는 단위)
#
# 한 파일에 같이 살되 서로 덮지 않는다 — 두 화면에서 번갈아 적어도 잃는 것이
# 없어야 한다.
FEEDBACK_LAYERS = ("units", "scenes", "cuts", "cuts_art", "cuts_story")

# 화 전체 피드백도 같은 이유로 셋이다.
FEEDBACK_GENERAL = ("general", "general_art", "general_story")


def _blank_feedback() -> dict[str, Any]:
    return {**{k: "" for k in FEEDBACK_GENERAL},
            **{k: {} for k in FEEDBACK_LAYERS}}


def read_feedback(ep_dir: Path) -> dict[str, Any]:
    """feedback.json. 없거나 깨졌으면 빈 모양 그대로 — 여기서 세우지 않는다."""
    path = feedback_path(ep_dir)
    if not path.exists():
        return _blank_feedback()
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return _blank_feedback()
    if not isinstance(data, dict):
        return _blank_feedback()
    out = _blank_feedback()
    for key in FEEDBACK_GENERAL:
        out[key] = str(data.get(key) or "")
    for layer in FEEDBACK_LAYERS:
        rows = data.get(layer)
        if isinstance(rows, dict):
            out[layer] = {str(k): str(v or "") for k, v in rows.items()}
    return out


def feedback_summary(ep_dir: Path) -> str:
    """화면에 한 줄로 찍을 요약. 무엇이 어디로 갈 것인지가 보여야 한다."""
    fb = read_feedback(ep_dir)
    art = (sum(1 for v in fb["cuts_art"].values() if v.strip())
           + sum(1 for v in fb["scenes"].values() if v.strip())
           + (1 if fb["general_art"].strip() else 0))
    story = (sum(1 for v in fb["cuts_story"].values() if v.strip())
             + (1 if fb["general_story"].strip() else 0))
    etc = (sum(1 for v in fb["cuts"].values() if v.strip())
           + sum(1 for v in fb["units"].values() if v.strip())
           + (1 if fb["general"].strip() else 0))
    bits = []
    if art:
        bits.append(f"그림 {art}건")
    if story:
        bits.append(f"스토리 {story}건")
    if etc:
        bits.append(f"기타 {etc}건")
    return " · ".join(bits)


# --------------------------------------------------------------------------- #
# contact sheet
# --------------------------------------------------------------------------- #
CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; font: 14px/1.6 "Malgun Gothic", system-ui, sans-serif;
       background: #f6f6f7; color: #16181d; }
h1 { font-size: 20px; margin: 0 0 4px; }
.meta { color: #5a6070; font-size: 13px; margin-bottom: 4px; }
.meta code { background: #e7e9ee; padding: 1px 5px; border-radius: 4px; }
.bar { position: sticky; top: 0; z-index: 5; background: #f6f6f7; padding: 12px 0 10px;
       border-bottom: 1px solid #d8dbe2; margin-bottom: 16px; display: flex;
       gap: 10px; align-items: center; flex-wrap: wrap; }
button { font: inherit; padding: 7px 14px; border-radius: 6px; border: 1px solid #b9bec9;
         background: #fff; cursor: pointer; }
button.primary { background: #2f6fed; border-color: #2f6fed; color: #fff; font-weight: 600; }
button:hover { filter: brightness(0.97); }
.count { color: #5a6070; font-size: 13px; }
table { border-collapse: collapse; width: 100%; background: #fff; }
th, td { border: 1px solid #d8dbe2; vertical-align: top; padding: 10px; }
th { background: #eceef3; font-size: 13px; position: sticky; top: 58px; z-index: 4; }
th.cutcol, td.cutcol { width: 26%; min-width: 320px; }
.cutno { font-weight: 700; font-size: 15px; margin-bottom: 6px; }
.tag { display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 999px;
       background: #ffe9b8; color: #6b4b00; margin-left: 6px; vertical-align: middle; }
.kr { white-space: pre-wrap; margin-bottom: 8px; }
.dlg { color: #8a4b00; white-space: pre-wrap; margin-bottom: 8px; }
.en { font-size: 12.5px; color: #364; background: #f2f7f2; border-left: 3px solid #9ec39e;
      padding: 8px 10px; white-space: pre-wrap; }
.warn { font-size: 12px; color: #a13; margin-top: 6px; }
.cands { display: flex; gap: 8px; flex-wrap: wrap; }
figure { margin: 0; width: 168px; }
figure img { width: 168px; height: 224px; object-fit: cover; display: block;
             border: 3px solid transparent; border-radius: 4px; cursor: pointer;
             background: #e7e9ee; }
figure.picked img { border-color: #2f6fed; }
figcaption { font-size: 11.5px; color: #5a6070; text-align: center; margin-top: 3px; }
figure.picked figcaption { color: #2f6fed; font-weight: 700; }
.missing { width: 168px; height: 224px; border: 1px dashed #b9bec9; border-radius: 4px;
           display: flex; align-items: center; justify-content: center; color: #8b91a0;
           font-size: 12px; }
.help { margin: 18px 0 0; font-size: 12.5px; color: #5a6070; }
.fb { margin-top: 10px; }
.fb label { display: block; font-size: 12px; color: #5a6070; margin-bottom: 3px; }
textarea { font: inherit; font-size: 13px; width: 100%; min-height: 60px; padding: 7px 9px;
           border: 1px solid #b9bec9; border-radius: 6px; background: #fffdf5;
           resize: vertical; color: inherit; }
textarea:focus { outline: 2px solid #2f6fed; outline-offset: -1px; }
textarea.filled { border-color: #d8a200; background: #fff8e2; }
.general { background: #fff; border: 1px solid #d8dbe2; border-radius: 8px;
           padding: 12px 14px; margin-bottom: 16px; }
.general textarea { min-height: 74px; }
@media (prefers-color-scheme: dark) {
  textarea { background: #1f2229; border-color: #3a4150; }
  textarea.filled { background: #2b2718; border-color: #7a6320; }
  .general { background: #1d2027; border-color: #2c313c; }
  body { background: #16181d; color: #e6e8ee; }
  .bar { background: #16181d; border-color: #2c313c; }
  table { background: #1d2027; }
  th, td { border-color: #2c313c; } th { background: #232833; }
  button { background: #232833; color: #e6e8ee; border-color: #3a4150; }
  button.primary { background: #2f6fed; border-color: #2f6fed; color: #fff; }
  .en { background: #1b241b; border-color: #3f5f3f; color: #cfe0cf; }
  .meta, .count, figcaption, .help { color: #9aa2b4; }
  .meta code { background: #232833; }
}
"""

JS = """
const KEY = "webtoon-picks:" + DATA.run_id + ":ep" + DATA.episode;
let picks = {};

function load() {
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { stored = null; }
  picks = stored && typeof stored === "object" ? stored : Object.assign({}, DATA.saved_picks);
  render();
}
function save() { try { localStorage.setItem(KEY, JSON.stringify(picks)); } catch (e) {} }

function render() {
  document.querySelectorAll("figure[data-key]").forEach(fig => {
    const on = picks[fig.dataset.key] === Number(fig.dataset.cand);
    fig.classList.toggle("picked", on);
  });
  const n = Object.keys(picks).length;
  const total = DATA.conditions.length * DATA.cuts.length;
  document.getElementById("count").textContent =
    "채택 " + n + " / " + total + " (조건 " + DATA.conditions.length + " x 컷 " + DATA.cuts.length + ")";
}

function toggle(fig) {
  const key = fig.dataset.key, cand = Number(fig.dataset.cand);
  if (picks[key] === cand) { delete picks[key]; } else { picks[key] = cand; }
  save(); render();
}

function file(cond, n, cand) {
  return DATA.file_pattern.replace("{cond}", cond).replace("{n}", n).replace("{k}", cand);
}

function csv() {
  const stamp = new Date().toISOString().slice(0, 19);
  const rows = [DATA.header.join(",")];
  DATA.conditions.forEach(c => DATA.cuts.forEach(cut => {
    const key = c.name + "|" + cut.cut_number;
    const cand = picks[key];
    if (!cand) return;
    rows.push([DATA.run_id, DATA.episode, c.name, cut.cut_number, cand,
               file(c.name, cut.cut_number, cand), stamp].join(","));
  }));
  // 이 시트가 다루지 않는 행(다른 모드의 채택)은 저장된 picks.csv 에서 그대로 옮긴다.
  // 그러지 않으면 컷 시트에서 받은 파일이 Scene 시트에서 받은 파일에 덮여 사라진다.
  DATA.extra_rows.forEach(r => rows.push(r.join(",")));
  return rows.join("\\n") + "\\n";
}

function download() {
  const blob = new Blob(["\\ufeff" + csv()], {type: "text/csv;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "picks.csv";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

async function copyCsv() {
  try { await navigator.clipboard.writeText(csv()); alert("picks.csv 내용을 클립보드에 복사했습니다."); }
  catch (e) { window.prompt("복사해서 picks.csv 로 저장하세요:", csv()); }
}

function reset() {
  if (!confirm("체크를 저장된 picks.csv 상태로 되돌립니다. 계속할까요?")) return;
  picks = Object.assign({}, DATA.saved_picks);
  save(); render();
}

// --- 피드백 -------------------------------------------------------------- //
// 채택과 같은 길로 돈다: 입력 즉시 localStorage, 버튼으로 feedback.json 내려받기,
// 다음에 시트를 다시 만들면 저장된 파일이 박혀 들어와 복원된다.
const FKEY = "webtoon-feedback:" + DATA.run_id + ":ep" + DATA.episode;
let fb = {general: "", units: {}};

function fbLoad() {
  let stored = null;
  try { stored = JSON.parse(localStorage.getItem(FKEY) || "null"); } catch (e) { stored = null; }
  const base = stored && typeof stored === "object" ? stored : DATA.saved_feedback;
  fb = {general: String((base && base.general) || ""),
        units: Object.assign({}, (base && base.units) || {})};
  document.querySelectorAll("textarea[data-unit]").forEach(t => {
    t.value = fb.units[t.dataset.unit] || "";
    t.classList.toggle("filled", !!t.value.trim());
  });
  const g = document.getElementById("fb-general");
  if (g) g.value = fb.general;
  fbCount();
}
function fbSave() { try { localStorage.setItem(FKEY, JSON.stringify(fb)); } catch (e) {} }
function fbCount() {
  const n = Object.values(fb.units).filter(v => v && v.trim()).length
          + (fb.general.trim() ? 1 : 0);
  const el = document.getElementById("fbcount");
  if (el) el.textContent = n ? "피드백 " + n + "건" : "피드백 없음";
}
function fbJson() {
  const units = {};
  Object.keys(fb.units).forEach(k => { if (fb.units[k] && fb.units[k].trim()) units[k] = fb.units[k]; });
  return JSON.stringify({
    run_id: DATA.run_id, episode: DATA.episode,
    saved_at: new Date().toISOString().slice(0, 19),
    general: fb.general, units: units,
  }, null, 2);
}
function downloadFeedback() {
  const blob = new Blob([fbJson()], {type: "application/json;charset=utf-8"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "feedback.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
async function copyFeedback() {
  try { await navigator.clipboard.writeText(fbJson()); alert("feedback.json 내용을 클립보드에 복사했습니다."); }
  catch (e) { window.prompt("복사해서 feedback.json 으로 저장하세요:", fbJson()); }
}

document.addEventListener("input", e => {
  const t = e.target;
  if (t.matches("textarea[data-unit]")) {
    fb.units[t.dataset.unit] = t.value;
    t.classList.toggle("filled", !!t.value.trim());
  } else if (t.id === "fb-general") {
    fb.general = t.value;
  } else { return; }
  fbSave(); fbCount();
});

document.addEventListener("click", e => {
  const fig = e.target.closest("figure[data-key]");
  if (fig) toggle(fig);
});
load();
fbLoad();
"""


def _esc(text: Any) -> str:
    return html.escape(str(text or ""))


def build_contact_sheet(
    ep_dir: Path,
    episode_meta: dict[str, Any],
    conditions: list[dict[str, str]],
    cuts: list[dict[str, Any]],
    candidates: int,
    info: dict[str, str],
    filename: str = "contact_sheet.html",
    unit: str = "컷",
    file_pattern: str = "{cond}/cut{n}_c{k}.png",
) -> Path:
    """contact_sheet.html 생성.

    conditions   : [{"name": "A", "label": "텍스트만"}, ...]
    cuts         : [{"cut_number", "description", "dialogue", "reader_only", "scene",
                     "prompt_preview", "warnings"}, ...]
    unit         : 행 이름. Scene 모드에서는 "Scene" 이 들어온다.
    file_pattern : 후보 이미지 경로. Scene 모드는 "{cond}/scene{n}_c{k}.png".
                   picks.csv 의 file 열도 이 규칙으로 쓰인다.
    """
    saved = {f"{c}|{n}": k for (c, n), k in load_picks(ep_dir).items()}
    mine = {c["name"] for c in conditions}
    extra = [[str(row.get(col) or "") for col in PICKS_HEADER]
             for row in read_rows(ep_dir)
             if str(row.get("condition") or "").strip() not in mine]
    data = {
        "run_id": episode_meta["run_id"],
        "episode": episode_meta["episode"],
        "conditions": conditions,
        "cuts": [{"cut_number": c["cut_number"]} for c in cuts],
        "saved_picks": saved,
        "header": PICKS_HEADER,
        "file_pattern": file_pattern,
        "extra_rows": extra,
        # 피드백은 컷/Scene 번호로만 묶는다. 조건별로 나누면 같은 말을 조건 수만큼
        # 적어야 하고, 실제로 적히는 말은 대개 조건과 무관하다 (옷이 바뀐다 등).
        "saved_feedback": read_feedback(ep_dir),
    }

    rows: list[str] = []
    for cut in cuts:
        n = cut["cut_number"]
        tag = '<span class="tag">reader_only</span>' if cut.get("reader_only") else ""
        warn = ""
        if cut.get("warnings"):
            warn = f'<div class="warn">⚠ 금지어 감지: {_esc(", ".join(cut["warnings"]))}</div>'
        dlg = f'<div class="dlg">대사: {_esc(cut.get("dialogue"))}</div>' if cut.get("dialogue") else ""
        note = f'<div class="meta">{_esc(cut.get("note"))}</div>' if cut.get("note") else ""
        cells = [
            f'<td class="cutcol"><div class="cutno">{_esc(unit)} {n}{tag}</div>{note}'
            f'<div class="kr">{_esc(cut.get("description"))}</div>{dlg}'
            f'<div class="en">{_esc(cut.get("scene") or "(프롬프트 없음)")}</div>{warn}'
            f'<div class="fb"><label for="fb-{n}">이 {_esc(unit)} 피드백</label>'
            f'<textarea id="fb-{n}" data-unit="{n}" '
            f'placeholder="무엇이 잘못됐는지 — 옷이 바뀜, 조연이 다른 사람, 얼굴이 작음 …">'
            f'</textarea></div></td>'
        ]
        for cond in conditions:
            figs: list[str] = []
            for k in range(1, candidates + 1):
                rel = (file_pattern.replace("{cond}", cond["name"])
                       .replace("{n}", str(n)).replace("{k}", str(k)))
                if (ep_dir / rel).exists():
                    figs.append(
                        f'<figure data-key="{_esc(cond["name"])}|{n}" data-cand="{k}">'
                        f'<img src="{_esc(rel)}" alt="cut{n} c{k}" loading="lazy">'
                        f'<figcaption>c{k}</figcaption></figure>'
                    )
                else:
                    figs.append(f'<div class="missing">c{k} 미생성</div>')
            cells.append(f'<td><div class="cands">{"".join(figs)}</div></td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")

    head = "".join(
        f'<th>{_esc(c["name"])}<br><span style="font-weight:400">{_esc(c["label"])}</span></th>'
        for c in conditions
    )
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    doc = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>{_esc(unit)} 시트 — {_esc(episode_meta['run_id'])} ep{episode_meta['episode']}</title>
<style>{CSS}</style></head><body>
<h1>{_esc(episode_meta['run_id'])} · {episode_meta['episode']}화 — {_esc(episode_meta.get('title'))}</h1>
<div class="meta">{_esc(unit)} {len(cuts)}개 · {_esc(unit)}당 후보 {candidates}장 · 컷 출처 <code>{_esc(episode_meta.get('source'))}</code></div>
<div class="meta">이미지 모델 <code>{_esc(info.get('image_model'))}</code> · 텍스트 모델 <code>{_esc(info.get('text_model'))}</code></div>
<div class="meta">스타일(고정) <code>{_esc(info.get('style'))}</code></div>
<div class="meta">외형(고정) <code>{_esc(info.get('appearance'))}</code></div>
<div class="bar">
  <button class="primary" onclick="download()">picks.csv 내려받기</button>
  <button onclick="copyCsv()">CSV 복사</button>
  <button onclick="reset()">저장된 picks.csv 로 되돌리기</button>
  <span class="count" id="count"></span>
  <button onclick="downloadFeedback()">feedback.json 내려받기</button>
  <button onclick="copyFeedback()">피드백 복사</button>
  <span class="count" id="fbcount"></span>
</div>
<div class="general">
  <label for="fb-general"><b>이 화 전체에 대한 피드백</b> — 컷 하나가 아니라 전반에 걸친 것</label>
  <textarea id="fb-general"
    placeholder="예) 연출이 세로 스크롤이 아니라 만화 페이지에 가깝다 / 주인공 옷이 컷마다 바뀐다 / 조연 성별이 매번 달라진다"></textarea>
</div>
<table><thead><tr><th class="cutcol">{_esc(unit)} / 원문 서술 / 영어 프롬프트</th>{head}</tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="help">
  후보 이미지를 클릭하면 채택으로 기록됩니다(다시 클릭하면 해제). 조건 x {_esc(unit)} 당 1장.<br>
  다 고른 뒤 <b>picks.csv 내려받기</b> → 내려받은 파일을 이 폴더
  (<code>{_esc(str(ep_dir))}</code>)에 <code>picks.csv</code> 로 저장하세요.<br>
  COND_D 는 실행할 때 이 파일에서 직전 {_esc(unit)} 의 채택 이미지를 찾아 첨부합니다.
  기록이 없으면 후보 1번(c1)을 씁니다.<br>
  컷 모드와 Scene 모드는 <code>picks.csv</code> 를 함께 씁니다(Scene 행의 condition 은
  <code>scene_&lt;조건&gt;</code>). 내려받을 때 <b>이 시트가 다루지 않는 행은 저장된
  picks.csv 에서 그대로 옮겨 담습니다</b> — 다만 옮겨지는 것은 <u>파일에 저장된</u>
  기록뿐이니, 다른 시트에서 고르고 아직 내려받지 않은 것이 있으면 그쪽을 먼저
  저장하세요.
</p>
<p class="help">
  <b>피드백</b>은 컷 옆 칸과 맨 위 전체 칸에 적습니다. 적는 즉시 브라우저에
  저장되고(새로고침해도 남습니다), <b>feedback.json 내려받기</b> → 이 폴더에
  <code>feedback.json</code> 으로 저장하면 다음에 시트를 다시 만들 때 그대로
  복원됩니다.<br>
  피드백은 <u>사람이 보는 기록</u>입니다 — 코드가 읽어서 프롬프트에 자동으로 넣지
  않습니다. 자동으로 밀어 넣으면 무엇을 바꿔서 좋아졌는지 알 수 없게 되기
  때문입니다. 고칠 것이 정해지면 <code>config.yaml</code>(<code>outfit_lock</code>,
  <code>supporting_cast</code>, <code>aspect_ratio</code> …)을 고쳐서 다시 뽑으세요.
</p>
<script>const DATA = {payload};{JS}</script>
</body></html>
"""
    out = ep_dir / filename
    out.write_text(doc, encoding="utf-8")
    return out
