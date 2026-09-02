/* LORE 랜딩 — 폼 → 진행 → 결과.
 *
 * 상태는 서버에서 통째로 받아 화면을 다시 그린다(0.8초마다). 브라우저가 진행
 * 상황을 따로 들고 있지 않으므로, 새로고침해도 창을 닫았다 열어도 같은 화면이
 * 나온다 — 10분 걸리는 일에서 이건 편의가 아니라 필수다. */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const FIELD_KEYS = ["나이", "성별", "직업", "성격", "말투", "과거", "관계", "약점"];

const STYLE_INFO = [
  ["webtoon",   "일반 웹툰",      "깔끔한 선과 셀 채색. 매주 연재하는 그 그림 — 읽히는 속도가 기준입니다."],
  ["romance",   "로맨스 판타지",  "표지 일러스트급 밀도. 보석 같은 눈, 장미와 금박, 레이스까지 하나하나."],
  ["shoujo",    "순정 · BL",      "얼굴과 둘 사이의 거리. 길고 날카로운 눈, 스크린톤, 여백에 뜬 꽃."],
  ["frost",     "세미리얼 · 성인향","사실적인 인체에 선은 얇고 듬성듬성, 진한 디테일은 얼굴·손에만. 넓은 면은 비워 두고 저채도로 차분하게."],
  ["pastel",    "일상툰 감성",    "일부러 덜 완성한 그림. 흔들리는 연필선, 종이 결, 바랜 파스텔 몇 색."],
  ["noir",      "다크 느와르",    "어둠이 주인공입니다. 화면 대부분이 먹으로 덮이고 빛은 얇게 남습니다."],
  ["cinematic", "시네마틱 반실사","빛으로 화려해집니다. 역광·공기·얕은 심도·필름 색보정. 얼굴은 웹툰 그대로."],
  ["game",      "게임 원화",      "고급 모바일 게임 캐릭터 CG. 섬세한 선화에 은은하게 빛나는 채색과 정제된 조명까지."],
];

// 장르 단추로 먼저 꺼내 두는 것들. index.html 의 datalist 에는 더 많이 있고,
// 여기 없는 장르도 칸에 직접 쓰면 그대로 간다.
// story-harness 가 **전용 샘플을 가진** 장르만 올린다(samples.py GENRES).
// 전용 샘플이 없는 장르를 고르면 엉뚱한 장르의 카드를 보고 쓰게 된다 —
// "일상"을 골랐는데 각성·던전이 나오던 것이 그 사정이다. 여기 없는 장르도
// 칸에 직접 쓰면 그대로 가고, 하네스가 낱말을 보고 알아서 맞춘다.
/* 그림체 썸네일. loading="lazy" 는 **안 쓴다** — 걸음이 숨어 있는 동안에는
   브라우저가 "화면 밖"으로 보고 안 받아 오다가, 걸음이 열려도 한동안 빈
   칸으로 남는다(실제로 7장 중 2장만 뜨는 것을 봤다).
   여덟 그림체 모두 **실제로 그 그림체로 뽑아 둔 샘플**을 쓴다. 파스텔·
   느와르·순정은 예시가 없던 동안 루 그림으로 자리만 채웠는데, 그러면 카드를
   봐도 어떤 그림이 나오는지 알 수가 없었다. 원본은 design-reference/picture
   에 있고, 여기에는 기존 샘플과 같은 규격(가로 1080 안, JPEG)으로 줄여
   넣는다 — 원본 PNG 는 장당 2~3MB 라 썸네일로 그대로 쓰면 안 된다. */
const STYLE_THUMB = {
  cinematic: "/static/samples/ex-cinematic-1.jpg",
  romance:   "/static/samples/ex-romance-1.jpg",
  webtoon:   "/static/samples/ex-webtoon-1.jpg",
  frost:     "/static/samples/ex-frost-1.jpg",
  pastel:    "/static/samples/ex-pastel-1.jpg",
  noir:      "/static/samples/ex-noir-1.jpg",
  shoujo:    "/static/samples/ex-shoujo-1.jpg",
  game:      "/static/samples/ex-game-1.jpg",
};

const GENRE_QUICK = [
  "로맨스 판타지", "무협", "판타지", "헌터·게이트",
  "마법학교", "게임 판타지", "센티넬", "오메가버스",
  "아이돌", "스릴러", "액션", "개그", "일상",
  "히어로",
];

/* 장르 카드 아래에 늘 떠 있는 한 줄. 안 고른 상태에서 아무것도 안 보이면
   "여기 뭔가 떠야 하는데 안 떴다"로 읽혀서 고장 같아 보인다 — 안 고른 것도
   **고른 것 중 하나**라는 걸 말해 주는 자리다. 문구는 하네스가 그 장르로
   무엇을 하는지를 적는다(분위기 형용사 말고). */
const GENRE_NOTE = {
  "로맨스 판타지": "드레스와 무도회, 계약 결혼과 회귀. 감정이 사건을 끕니다.",
  "무협":         "강호와 문파, 내공과 검. 은원이 이야기를 끕니다.",
  "판타지":       "검과 마법, 다른 세계. 종족과 왕국이 배경이 됩니다.",
  "헌터·게이트":  "현대 한국에 열린 게이트. 각성자와 길드, 등급이 규칙입니다.",
  "마법학교":     "입학과 기숙사, 수업과 시험. 학교가 세계의 크기입니다.",
  "게임 판타지":  "상태창과 레벨, 퀘스트와 스킬. 규칙이 눈에 보입니다.",
  "센티넬":       "가이드와 센티넬, 감각 폭주와 결합. 관계가 곧 설정입니다.",
  "오메가버스":   "알파·베타·오메가, 페로몬과 각인. 관계의 규칙이 세계입니다.",
  "아이돌":       "연습생과 데뷔, 무대와 팬. 성장과 경쟁이 축입니다.",
  "스릴러":       "쫓고 쫓기는 것. 정보를 언제 주는지가 연출이 됩니다.",
  "액션":         "몸으로 부딪히는 것. 합과 속도로 컷을 나눕니다.",
  "개그":         "박자와 배신. 컷의 크기 차이로 웃깁니다.",
  "일상":         "큰 사건 없이 하루하루. 인물의 결이 곧 이야기입니다.",
  "히어로":       "능력과 빌런, 등록과 자경단. 누가 구할 자격을 갖느냐가 규칙입니다.",
};
const GENRE_NOTE_EMPTY =
  "비워두면 루가 골라요 — 앞에서 적은 캐릭터 설명을 보고 이야기에 맞는 장르를 정합니다.";

/* ---- 일반 모드 · 전문 모드 ------------------------------------------- *
 *
 * 계정이 없으므로 고른 모드는 브라우저(localStorage)에 남는다. sessionStorage
 * 가 아닌 이유: 창을 닫았다 열 때마다 "어떻게 만들까요?" 를 다시 묻는 것은
 * 한 번 정한 사람에게는 그냥 방해다.
 *
 * 모드가 정하는 것은 두 가지뿐이다 —
 *   1. 폼에서 [data-expert-only] 를 보여줄 것인가 (안 보여줘도 기본값은 간다)
 *   2. 시트 검수 화면에서 외형 사양 편집 폼을 열 것인가
 * 어느 단계에서 멈출지는 **서버가** 정한다(pipeline.checkpoints). 화면이 그
 * 규칙을 베껴 두면 둘이 갈라져서, 고른 사람이 속은 것이 된다. */

const MODES = {
  simple: { label: "일반 모드", desc: "세부 설정 없이 자동으로 만듭니다 — 캐릭터 시트만 확인합니다." },
  expert: { label: "전문 모드", desc: "이야기 · 시트 · 콘티 · 그림 검수, 네 곳에서 멈추고 보여드립니다." },
};

function currentMode() {
  const m = localStorage.getItem("lore_mode");
  return m === "expert" ? "expert" : m === "simple" ? "simple" : null;
}

function isExpert() { return currentMode() === "expert"; }

/* 폼의 전문 전용 칸을 열고 닫는다. 숨긴 칸의 값은 **안 지운다** — 전문 모드로
   골라 놓고 일반으로 바꿔도 라디오의 기본값(연출 fast · 등신 기본 · 검수 2번)이
   그대로 남아서, collect() 가 보내는 값이 일반 모드가 약속한 것과 같다. */
function applyMode() {
  const mode = currentMode() || "simple";
  const expert = mode === "expert";
  document.body.dataset.mode = mode;
  $$("[data-expert-only]").forEach(el => { el.hidden = !expert; });
  const badge = $("#modeBadge");
  if (badge) badge.textContent = MODES[mode].label;
  const desc = $("#modeBarDesc");
  if (desc) desc.textContent = MODES[mode].desc;
  paintCost();
}

function setMode(mode) {
  localStorage.setItem("lore_mode", mode === "expert" ? "expert" : "simple");
  applyMode();
}

let jobId    = sessionStorage.getItem("lore_job") || null;
let poll     = null;
/* 사진은 여러 장 받는다 — 한 사람을 여러 각도로 찍은 것이다.
   한 장으로는 늘 안 보이는 칸(하의·신발·뒤통수)이 남고, 다른 각도가 그 칸을 채운다. */
const MAX_PHOTOS = 4;
let photos = [];          // data URL 목록. 순서가 LOOK 에 붙는 순서다.
let shownCuts = new Set();
let lastStatus = null;

/* ------------------------------------------------------------------ 초기화 */

function buildForm() {
  // 항목 표는 화면에서 뺐다(1걸음은 사진·이름·이야기뿐). 칸이 있으면 채우고
  // 없으면 지나간다 — collect() 의 fields 는 그때 그냥 빈 채로 간다.
  const grid = $("#fieldsGrid");
  if (grid) grid.innerHTML = FIELD_KEYS.map(k => `
    <label><span>${k}</span><input type="text" data-field="${k}" placeholder=""></label>
  `).join("");

  // 기본은 아무 것도 안 고른 상태다("건너뛰기" = 루가 정합니다). 라디오는
  // 한 번 고르면 같은 것을 다시 눌러도 브라우저가 저절로 풀어주지 않으므로,
  // 이미 고른 것을 또 누르면 비우는 동작만 직접 얹는다(장르 빠른 고르개와
  // 같은 "다시 누르면 비운다" 패턴). click 에서 preventDefault 를 쓰면 라디오는
  // "취소된 활성화 단계"가 클릭 이전 상태로 되돌려 버려서 — 우리가 스크립트로
  // 정한 checked 값이 이벤트가 끝나자마자 그대로 지워진다(직접 겪음). 그래서
  // 기본 동작은 그대로 두고, 클릭이 checked 를 바꾸기 **전** 상태만
  // (mousedown/keydown 시점에) 따로 기억해 뒀다가, 그게 "이미 켜져 있었다"일
  // 때만 클릭이 끝난 뒤 스크립트로 끈다.
  $("#styles").innerHTML = STYLE_INFO.map(([key, label, desc]) => `
    <label class="style-opt">
      <input type="radio" name="style" value="${key}">
      <span class="style-box">
        <img class="style-thumb" src="${STYLE_THUMB[key]}" alt="">
        <b>${label}</b><small>${desc}</small>
      </span>
    </label>
  `).join("");
  $$('#styles .style-opt').forEach(opt => {
    const inp = opt.querySelector('input[name="style"]');
    const rememberBeforeState = () => { inp.dataset.wasChecked = String(inp.checked); };
    opt.addEventListener("pointerdown", rememberBeforeState);   // 마우스·터치
    inp.addEventListener("keydown", e => {                      // 키보드(Space)
      if (e.key === " " || e.key === "Spacebar") rememberBeforeState();
    });
    inp.addEventListener("click", () => {
      if (inp.dataset.wasChecked === "true") inp.checked = false;
    });
  });


  // 장르 빠른 고르개. datalist 는 폰에서 안 열리는 브라우저가 있어서, 자주
  // 쓰는 것만 단추로 먼저 꺼내 둔다. 목록에 없는 장르는 그대로 칸에 쓰면 된다.
  const quick = $("#genreQuick");
  if (quick) {
    quick.innerHTML = GENRE_QUICK
      .map(g => `<button type="button" aria-pressed="false">${g}</button>`).join("");
    const input = $("#form").genre;
    const hint = $("#genreNote");
    const sync = () => {
      const now = input.value.trim();
      $$("button", quick).forEach(b =>
        b.setAttribute("aria-pressed", String(b.textContent === now)));
      if (!hint) return;
      // 세 가지 상태 모두 한 줄이 뜬다 — 빈 자리를 남기지 않는다.
      hint.dataset.state = now ? (GENRE_NOTE[now] ? "known" : "custom") : "empty";
      hint.textContent = now
        ? (GENRE_NOTE[now] || `「${now}」 그대로 갑니다 — 목록에 없는 장르도 루가 낱말을 보고 맞춥니다.`)
        : GENRE_NOTE_EMPTY;
    };
    $$("button", quick).forEach(btn => btn.addEventListener("click", () => {
      // 눌린 것을 다시 누르면 비운다 — 비우면 루가 고른다
      input.value = (input.value.trim() === btn.textContent) ? "" : btn.textContent;
      sync();
    }));
    input.addEventListener("input", sync);
    sync();
  }
}

/* ---- 사용자 피드백 ---------------------------------------------------- *
 *
 * 자유 입력만 두면 대부분 아무것도 안 적고 넘어간다 — 그러면 왜 다시 만들라고
 * 했는지가 남지 않는다. 그래서 자주 나온 불만을 버튼으로 먼저 보여 주고, 그
 * 밖의 말은 그대로 적게 한다. 둘 다 선택이라 아무것도 안 하고 눌러도 된다.
 *
 * 항목 목록은 서버(/api/config)가 준다. 화면에 베껴 두면 pipeline.py 의
 * FEEDBACK_TAGS 와 갈라지고, 화면에만 있는 id 를 보내면 서버가 버린다. */

let fbTagsByStage = {};
let fbTextMax = 500;

/* "기타"는 다른 태그와 달리 골랐을 때 적는 칸(.fb-etc-note)을 열어 준다 —
   "더 하고 싶은 말"을 늘 펼쳐 두지 않고 기타 선택지 하나로 합친 것.
   태그를 못 받아 "기타" 버튼 자체가 없으면(아래 loadFeedbackTags 참고) 적는
   칸은 마크업 기본값(안 숨김)대로 계속 열려 있다 — 그래야 자유 입력만이라도
   남는다. */
function fbChips(stage, box) {
  const wrap = $(".fb-tags", box);
  const text = $(".fb-text", box);
  const note = $(".fb-etc-note", box);
  const tags = fbTagsByStage[stage] || [];
  const hasEtc = tags.some(t => t.id === "etc");
  wrap.replaceChildren(...tags.map(t => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "fb-tag";
    b.dataset.tagId = t.id;
    b.textContent = t.label;
    b.setAttribute("aria-pressed", "false");
    b.addEventListener("click", () => {
      const nowPressed = b.getAttribute("aria-pressed") !== "true";
      b.setAttribute("aria-pressed", nowPressed ? "true" : "false");
      if (t.id === "etc" && note) {
        note.hidden = !nowPressed;
        if (nowPressed) $(".fb-text", note)?.focus();
      }
    });
    return b;
  }));
  if (text) text.maxLength = fbTextMax;
  if (note) note.hidden = hasEtc;
}

async function loadFeedbackTags() {
  try {
    const cfg = await getConfig();
    fbTagsByStage = cfg.feedback_tags || {};
    fbTextMax = cfg.feedback_text_max || fbTextMax;
  } catch { return; }      // 못 받으면 자유 입력만 남는다 — 승인 자체는 안 막는다
  document.querySelectorAll(".fb-box").forEach(box => fbChips(box.dataset.fbStage, box));
}

/* 그 단계에서 고른 항목과 적은 말. 상자가 없거나 아무것도 안 했으면 빈 값이다. */
function fbRead(box) {
  if (!box) return { tags: [], feedback: "" };
  return {
    tags: [...box.querySelectorAll('.fb-tag[aria-pressed="true"]')]
      .map(b => b.dataset.tagId),
    feedback: ($(".fb-text", box)?.value || "").trim(),
  };
}

/* 보낸 뒤에는 비운다. 다음 판에도 지난번에 고른 것이 눌린 채로 남아 있으면
   사람이 다시 고른 것처럼 보여서 같은 말이 두 번 프롬프트에 실린다. */
function fbClear(box) {
  if (!box) return;
  box.querySelectorAll(".fb-tag").forEach(b => b.setAttribute("aria-pressed", "false"));
  const text = $(".fb-text", box);
  if (text) text.value = "";
  // "기타" 버튼이 실제로 있을 때만 다시 접는다 — 없으면(태그를 못 받은 경우)
  // 적는 칸이 유일한 입력 수단이라 계속 열어 둬야 한다.
  const note = $(".fb-etc-note", box);
  if (note && box.querySelector('.fb-tag[data-tag-id="etc"]')) note.hidden = true;
}

/* ---- 작품 규칙 (user memory) ------------------------------------------ *
 *
 * 작가가 작품마다 선언하는 규칙. 피드백이 "지난 결과에 대한 말" 이라면 이것은
 * "앞으로 모든 생성이 지킬 것" 이다 — 스토리·콘티·그림 전 단계 프롬프트에
 * 실리고, 다른 설정과 충돌하면 이긴다 (서버 쪽 pipeline.read/write_memory).
 *
 * 저장 형식은 구조(JSON)지만 화면은 줄 단위 텍스트로 편집한다:
 *   항상 적용   한 줄 = 규칙 하나
 *   키워드      「태그1, 태그2 :: 내용」 — :: 앞이 발동 키워드다 */

let memLimits = { always: 500, keyword: 1500 };

function memParse(box) {
  const always = $(".mem-always", box).value.split("\n")
    .map(t => t.trim()).filter(Boolean).map(text => ({ text }));
  const keyword = [];
  for (const line of $(".mem-keyword", box).value.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const i = t.indexOf("::");
    if (i < 0) return { error: `키워드 줄에 :: 가 없습니다 — "${t.slice(0, 24)}"` };
    const tags = t.slice(0, i).split(",").map(x => x.trim()).filter(Boolean);
    const text = t.slice(i + 2).trim();
    if (!tags.length || !text)
      return { error: `키워드 줄이 비었습니다 — "${t.slice(0, 24)}"` };
    keyword.push({ tags, text });
  }
  return { always, keyword };
}

function memFill(box, data) {
  $(".mem-always", box).value =
    (data.always || []).map(e => e.text).join("\n");
  $(".mem-keyword", box).value =
    (data.keyword || []).map(e => `${e.tags.join(", ")} :: ${e.text}`).join("\n");
  memCount(box);
}

function memCount(box) {
  const a = (memParse(box).always || []).reduce((n, e) => n + e.text.length, 0);
  const k = (memParse(box).keyword || []).reduce((n, e) => n + e.text.length, 0);
  const ca = $('.mem-count[data-kind="always"]', box);
  const ck = $('.mem-count[data-kind="keyword"]', box);
  if (ca) { ca.textContent = `${a}/${memLimits.always}`;
            ca.style.color = a > memLimits.always ? "var(--accent)" : ""; }
  if (ck) { ck.textContent = `${k}/${memLimits.keyword}`;
            ck.style.color = k > memLimits.keyword ? "var(--accent)" : ""; }
}

/* runId 의 규칙을 모든 .mem-box 에 채우고 저장 버튼을 잇는다. 화면에 상자가
 * 여럿(승인·결과)이라 마지막으로 연 것이 저장하는 것이 자연스럽다 — 저장하면
 * 다른 상자도 다시 채운다. */
async function wireMemory(runId) {
  if (!runId) return;
  let data = { always: [], keyword: [] };
  try {
    const cfg = await getConfig();
    memLimits = { always: cfg.memory_always_max || 500,
                  keyword: cfg.memory_keyword_max || 1500 };
    data = await (await fetch(`/api/runs/${encodeURIComponent(runId)}/memory`)).json();
  } catch { /* 서버가 없으면 빈 칸 — 편집 자체는 된다 */ }
  $$(".mem-box").forEach(box => {
    memFill(box, data);
    if (box.dataset.memWired) return;          // 리스너는 한 번만
    box.dataset.memWired = "1";
    box.addEventListener("input", () => memCount(box));
    $(".mem-save", box).addEventListener("click", async () => {
      const status = $(".mem-status", box);
      const parsed = memParse(box);
      if (parsed.error) { status.textContent = parsed.error; return; }
      status.textContent = "저장하는 중…";
      try {
        const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/memory`, {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(parsed) });
        const out = await res.json();
        if (!res.ok) throw new Error(out.error || "저장하지 못했습니다");
        status.textContent = "저장됨 — 다음 생성(다시 만들기·다음 화·다시 그리기)부터 적용됩니다";
        $$(".mem-box").forEach(b => { if (b !== box) memFill(b, out); });
      } catch (err) { status.textContent = err.message; }
    });
  });
}

function fbStageBox(stage) {
  return document.querySelector(`.fb-box[data-fb-stage="${stage}"]`);
}

/* 세계관 프리셋 — 목록은 서버(story-harness/worlds.json)에서 받는다.
   여기에 베껴 두면 두 곳이 갈라지고, 화면에만 있는 키를 고르면 story.py 가
   worlds.json 에서 그 키를 못 찾아 실행이 통째로 멈춘다. */
let configOnce = null;
function getConfig() {
  if (!configOnce) configOnce = fetch("/api/config").then(r => r.json());
  return configOnce;
}

async function loadWorlds() {
  const sel = $("#worldPreset"), hint = $("#worldHint");
  if (!sel) return;
  let worlds = [];
  try {
    worlds = (await getConfig()).worlds || [];
  } catch { return; }               // 못 받아도 자유 입력은 그대로 된다
  if (!worlds.length) return;

  sel.append(...worlds.map(w => {
    const o = document.createElement("option");
    o.value = w.key; o.textContent = w.label; o.dataset.text = w.text || "";
    return o;
  }));

  sel.addEventListener("change", () => {
    const text = sel.selectedOptions[0]?.dataset.text || "";
    hint.textContent = text;
    hint.hidden = !text;
    // 고르면 본문을 입력칸에 채워 준다 — 그대로 써도 되고 고쳐 써도 된다.
    // 이미 직접 쓴 글이 있으면 덮지 않는다. 골랐다고 남의 글을 지우면 안 된다.
    const box = $("#form").world;
    if (text && !box.value.trim()) box.value = text;
  });
}

function setupPhoto() {
  const drop = $("#photoDrop"), input = $("#photo");

  const paint = () => {
    // 올린 사진 옆에 빈 칸(+)을 하나 남겨 둔다. 빈 칸이 안 보이면 더 올릴 수
    // 있다는 것을 모른다. 한동안 화면에서 한 장만 받게 막아 뒀었는데, 여러
    // 각도를 보여줄수록 닮게 그려지므로 다시 연다 — photos 배열과 서버는
    // 그동안에도 여러 장을 그대로 받고 있었다(하네스 계약).
    const shots = photos.map((src, i) => `
      <figure class="shot">
        <img src="${src}" alt="${i + 1}번째 사진">
        <button type="button" class="shot-x" data-i="${i}" aria-label="지우기">✕</button>
      </figure>`);
    // 칸을 여러 개 미리 깔지 않는다 — 다음 한 칸만 보이면 충분하고, 빈 칸이
    // 줄줄이 있으면 다 채워야 하는 것처럼 읽힌다.
    const slots = photos.length < MAX_PHOTOS
      ? [`<span class="photo-slot" aria-hidden="true">+</span>`] : [];
    $("#photoStrip").innerHTML = shots.concat(slots).join("");
    $$("#photoStrip .shot-x").forEach(b => b.addEventListener("click", e => {
      e.preventDefault(); e.stopPropagation();
      photos.splice(Number(b.dataset.i), 1); paint();
    }));
    drop.classList.toggle("has-photo", photos.length > 0);
    // 각도 이야기는 딱 한 번, 한 장 올렸을 때만 한다 — 그때가 "더 올릴까" 를
    // 정하는 순간이다. 그 뒤로도 계속 붙어 있으면 잔소리로 읽힌다.
    $("#photoCount").textContent =
      photos.length === 0 ? "눌러서 사진을 올려주세요"
      : photos.length === 1 ? `1 / ${MAX_PHOTOS}장 · 각도를 바꿔 더 올리면 더 닮게 그립니다`
      : `${photos.length} / ${MAX_PHOTOS}장`;
    input.value = "";
  };

  const load = files => {
    const list = [...(files || [])];
    if (!list.length) return;
    const room = MAX_PHOTOS - photos.length;
    if (room <= 0) return toast(`사진은 ${MAX_PHOTOS}장까지 올릴 수 있습니다`);
    if (list.length > room) toast(`${room}장만 추가합니다 (최대 ${MAX_PHOTOS}장)`);
    list.slice(0, room).forEach(file => {
      if (!file.type.startsWith("image/")) return;
      if (file.size > 6 * 1024 * 1024) return toast("사진이 너무 큽니다 (6MB 까지)");
      const fr = new FileReader();
      fr.onload = () => { photos.push(fr.result); paint(); };
      fr.readAsDataURL(file);
    });
  };

  input.addEventListener("change", e => load(e.target.files));
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => {
    e.preventDefault(); drop.classList.remove("drag");
  }));
  drop.addEventListener("drop", e => load(e.dataTransfer.files));
  paint();
}


/* ------------------------------------------------------------------ 크레딧
 *
 * 실제로 소진되는 잔액이다(credits.py). 계정이 없으므로 브라우저가 만든
 * uid(localStorage)로 사람을 구분한다 — lore_mode 와 같은 방식이다.
 * 비용 값 자체는 여기서 안 정한다 — /api/config 가 credits.py 를 그대로
 * 내려주므로, 화면의 "−N 크레딧" 표시가 실제로 빠지는 값과 늘 같다. */

function getUid() {
  let uid = localStorage.getItem("lore_uid");
  if (!uid) {
    uid = "u" + Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
    localStorage.setItem("lore_uid", uid);
  }
  return uid;
}
const UID = getUid();

let creditCost = { full: 0, preview: 0, webtoon_mult: 1 };   // /api/config 도착 전 임시값
let creditPackages = [];
let dailyFreeCredits = 20;
let creditBalance = null;

async function loadCreditConfig() {
  try {
    const cfg = await getConfig();
    creditCost = cfg.credit_cost || creditCost;
    creditPackages = cfg.credit_packages || [];
    dailyFreeCredits = cfg.daily_free_credits || dailyFreeCredits;
  } catch { /* 못 받아도 화면은 뜬다 — 비용 칩만 0으로 보인다 */ }
  paintCost();
  paintMyCreditHint();
}

async function refreshCreditBalance() {
  try {
    const res = await fetch(`/api/credits?uid=${encodeURIComponent(UID)}`);
    creditBalance = (await res.json()).balance;
  } catch { creditBalance = null; }
  paintCreditPill();
}

function paintCreditPill() {
  const shown = creditBalance == null ? "…" : creditBalance.toLocaleString("ko-KR");
  const el = $("#creditPillNum");
  if (el) el.textContent = shown;
  const cur = $("#chargeCurBalance");
  if (cur) cur.textContent = shown;
  // 마이페이지에도 같은 숫자를 쓴다 — 두 군데가 다른 값을 보이면 어느 쪽이
  // 참인지 알 수 없다. 잔액을 바꾸는 곳이 여기 하나뿐이라 저절로 맞는다.
  // 목업(/demo/mypage)만 예외다: 거기 숫자는 화면을 보여주려고 넣은 것이라,
  // 늦게 도착한 진짜 잔액이 덮어쓰면 목업이 반쯤 진짜가 된다.
  if (mockAccountPill) return;
  const my = $("#myCreditNum");
  if (my) my.textContent = shown;
  paintMyCreditHint();
}

/* "1,240" 만 있으면 많은 건지 적은 건지 알 수 없다 — 한 편에 얼마인지를 같이
   적어서, 몇 편 더 만들 수 있는지가 바로 보이게 한다. */
function paintMyCreditHint() {
  const el = $("#myCreditHint");
  if (!el || mockAccountPill) return;
  const one = creditCost.full;
  if (!one) { el.textContent = ""; return; }
  const left = creditBalance == null ? null : Math.floor(creditBalance / one);
  el.textContent = left == null
    ? `한 편 만드는 데 ${one.toLocaleString("ko-KR")} C`
    : `한 편에 ${one.toLocaleString("ko-KR")} C — 지금 ${left}편 더 만들 수 있어요`;
}

function layoutMode() {
  const el = document.querySelector('input[name="layout_mode"]:checked');
  return el ? el.value : "fast";
}

function creationCost() {
  // 한 편 전액 — 만들 때 12C 를 한 번에 받고, 나머지 생성(1화 전체 보기)은
  // 추가 결제가 없다. 연출 모드로도 값이 안 바뀐다.
  return creditCost.full || 0;
}

function paintCost() {
  const preview = true;              // 지금은 미리보기만 만든다 — collect() 도 항상 preview:true
  $("#costChip").textContent = `−${creationCost()}크레딧`;
  // 단추에는 지금 나가는 값만 적고, 무슨 일이 일어나는지는 바로 밑 한 줄이
  // 말한다 — 이야기는 한 편 전체가 만들어지고 그림은 첫 장면(3컷)만 나온다는
  // 것을 모르고 누르면, 결과 화면에서 "이게 다야?" 가 된다.
  const noteEl = $("#submitNote");
  if (noteEl && !noteEl.dataset.costNote) {
    noteEl.dataset.costNote = "1";
    const per = creationCost();
    const full = (creditCost.full || 0)
      * (layoutMode() === "webtoon" ? (creditCost.webtoon_mult || 1) : 1);
    noteEl.textContent = noteEl.textContent.replace(/\s*$/, "") +
      ` 먼저 일부 장면을 보여드려요.` +
      ` 마음에 들면 추가 결제 없이 전체를 이어서 볼 수 있어요.`;
  }
  // 홈의 첫 단추에도 값을 적는다 — 다섯 걸음을 다 밟고 마지막에야 얼마인지
  // 아는 것은 늦다. /api/config 가 오기 전에는 값이 0 이라, 그동안은 숨긴다
  // (0 크레딧이라고 적어 두면 공짜인 줄 안다).
  const startChip = $("#startCostChip");
  if (startChip) {
    // 홈에서 궁금한 것은 "한 편에 얼마" 다. "첫 장 2C부터" 는 우리끼리 말이라
    // (장이 뭔지, C 가 뭔지, 부터가 뭔지) 아무것도 전달이 안 됐다.
    // 전체 가격 하나만 말하고, 나눠 내는 방식은 만들기 단추 밑에서 설명한다.
    const full = (creditCost.full || 0)
      * (layoutMode() === "webtoon" ? (creditCost.webtoon_mult || 1) : 1);
    startChip.hidden = !full;
    startChip.textContent = `−${full}크레딧`;
  }
  $("#submitBtn").firstChild.textContent =
    preview ? "미리보기 만들기 " : "웹툰 만들기 ";
}

/* ---- 충전 모달 — 프리토타이핑 결제 ------------------------------------- *
 *
 * 걸음: 상품 고르기 → 카드사 고르기 → 완료. 실제 PG 연동이 없고, 카드번호를
 * 넣는 화면도 아예 없다 — "지불 의사가 있는가" 를 보는 게 목적이라, 카드
 * 고르기 딱 한 걸음 앞에서 멈추고 그 자리에서 바로 지급한다. */

const CARD_ISSUERS = ["신한카드", "국민카드", "삼성카드", "현대카드", "카카오페이", "토스페이"];
let chargeSelectedPkg = null;
let chargeSelectedCard = "";
let chargeSelectedMethod = "";

const CHARGE_METHOD_LABELS = { app: "앱 결제", web: "웹 결제", simple: "간편 결제" };

function showChargeConfirm() {
  const pkg = chargeSelectedPkg;
  if (!pkg) return;
  $("#chargeConfirmBox").innerHTML = `
    <div class="charge-confirm-row"><span>상품</span><b>${pkg.emoji || ""} ${pkg.label} · ${pkg.credits.toLocaleString("ko-KR")}크레딧</b></div>
    <div class="charge-confirm-row"><span>결제 수단</span><b>${chargeSelectedCard} · ${CHARGE_METHOD_LABELS[chargeSelectedMethod] || ""}</b></div>
    <div class="charge-confirm-row charge-confirm-total"><span>결제 금액</span><b>${pkg.price.toLocaleString("ko-KR")}원</b></div>`;
  chargeStep("confirm");
}

function chargeStep(name) {
  $$(".charge-step").forEach(el => { el.hidden = el.dataset.chargeStep !== name; });
}

/* 승선 — 하루 1회 무료 카드. 예전엔 이 자리가 유료 상품("물결")이었다.
   이름은 뒤의 출항 → 항해 → 탐험 앞에 놓이는 첫 걸음이다(배에 오르는 것).
   오늘 이미 받았는지는 서버(credits.json 의 날짜)만 알므로, 열 때마다
   물어보고 그린다 — 잘못 안내해서 "받았다고 나왔는데 안 받아짐" 이 되면
   안 되니, 상태를 모르면(요청 실패) 아예 카드를 숨긴다. */
async function renderFreeClaimCard(box) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "charge-pkg charge-pkg-free";
  b.disabled = true;
  b.innerHTML = `
    <span class="charge-pkg-badge">하루 1회 무료</span>
    <span class="charge-pkg-emoji">⛵</span>
    <span class="charge-pkg-label">승선</span>
    <span class="charge-pkg-tag">확인하는 중…</span>
    <span class="charge-pkg-value">${dailyFreeCredits.toLocaleString("ko-KR")}C</span>`;
  box.appendChild(b);
  try {
    const res = await fetch(`/api/credits/daily?uid=${encodeURIComponent(UID)}`);
    const st = await res.json();
    if (!res.ok) throw new Error();
    if (st.claimed) {
      b.querySelector(".charge-pkg-tag").textContent = "오늘은 이미 받았어요 — 내일 또!";
    } else {
      b.disabled = false;
      b.querySelector(".charge-pkg-tag").textContent = "눌러서 바로 받기";
      b.addEventListener("click", () => claimDailyFree(b));
    }
  } catch {
    b.remove();
  }
}

async function claimDailyFree(btn) {
  btn.disabled = true;
  try {
    const res = await fetch("/api/credits/daily", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uid: UID }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "지급에 실패했습니다");
    if (data.granted) {
      creditBalance = data.balance;
      paintCreditPill();
      toast(`오늘의 무료 크레딧 ${data.credits_added}개가 들어왔어요! ✨`);
      btn.querySelector(".charge-pkg-tag").textContent = "오늘은 이미 받았어요 — 내일 또!";
    } else {
      btn.querySelector(".charge-pkg-tag").textContent = "오늘은 이미 받았어요 — 내일 또!";
      toast("오늘은 이미 받았어요 — 내일 다시 와 주세요!");
    }
  } catch (err) {
    btn.disabled = false;
    toast(err.message || "지급에 실패했습니다");
  }
}

function renderChargePackages() {
  const box = $("#chargePackages");
  box.innerHTML = "";
  renderFreeClaimCard(box);
  creditPackages.forEach((pkg, ti) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "charge-pkg";
    // 단계 — 출항(1)에서 탐험(3)으로 멀어질수록 카드의 물빛이 짙어진다.
    b.dataset.tier = String(ti + 1);
    // 크레딧보다 "몇 편"이 먼저다. 크레딧은 이 서비스가 만든 단위라 60이
    // 많은지 적은지 알 수 없지만, "웹툰 7편"은 바로 읽힌다. 편당 가격이
    // 깊이 들어갈수록 싸지는 것도 여기서 저절로 보인다.
    const full = creditCost.full || 8;
    const eps = Math.floor(pkg.credits / full);
    const perEp = Math.round(pkg.price / (pkg.credits / full));
    b.innerHTML = `${pkg.badge ? `<span class="charge-pkg-badge">${pkg.badge}</span>` : ""}
      <span class="charge-pkg-emoji">${pkg.emoji || ""}</span>
      <span class="charge-pkg-label">${pkg.label}</span>
      <span class="charge-pkg-tag">${pkg.tagline || ""}</span>
      <span class="charge-pkg-value">웹툰 <b>${eps}편</b> · ${pkg.credits.toLocaleString("ko-KR")}C</span>
      <span class="charge-pkg-price">${pkg.price.toLocaleString("ko-KR")}원</span>
      <span class="charge-pkg-per">한 편에 ${perEp.toLocaleString("ko-KR")}원</span>`;
    b.addEventListener("click", () => {
      chargeSelectedPkg = pkg;
      $("#chargePkgSummary").textContent =
        `${pkg.label} · ${pkg.credits.toLocaleString("ko-KR")}크레딧 · ${pkg.price.toLocaleString("ko-KR")}원`;
      chargeStep("card");
      renderChargeCards();
    });
    box.appendChild(b);
  });
}

function renderChargeCards() {
  const box = $("#chargeCards");
  box.innerHTML = "";
  CARD_ISSUERS.forEach(name => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "charge-card";
    b.textContent = name;
    // 실제 PG 처럼 카드사 → 결제 방식(앱/웹/간편) → 최종 확인 순서다.
    // 프리토타이핑: 마지막 확인까지 간 사람 수가 진짜 지불 의사다.
    b.addEventListener("click", () => {
      chargeSelectedCard = name;
      $("#chargeMethodTitle").textContent = `${name} 결제 방식`;
      $("#chargeMethodSummary").textContent = $("#chargePkgSummary").textContent;
      chargeStep("method");
    });
    box.appendChild(b);
  });
}

async function finishCharge() {
  if (!chargeSelectedPkg) return;
  chargeStep("done");
  $("#chargeDoneEmoji").textContent = "⏳";
  $("#chargeDoneTitle").textContent = "결제 처리 중";
  $("#chargeDoneBody").textContent = "카드사와 통신하고 있어요…";
  try {
    const res = await fetch("/api/credits/charge", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ uid: UID, package_id: chargeSelectedPkg.id }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "결제에 실패했습니다");
    creditBalance = data.balance;
    paintCreditPill();
    // 반전 — 끝까지 결제할 마음이었던 사람에게만 보인다. 여기 도달 수가
    // 프리토타이핑이 재는 진짜 지불 의사이고, 돈은 실제로 안 빠져나간다.
    $("#chargeDoneEmoji").textContent = "🎁";
    $("#chargeDoneTitle").textContent = "짜잔 — 이벤트에 당첨되셨어요!";
    $("#chargeDoneBody").innerHTML =
      `지금은 오픈 준비 기간이라, <b>이번 충전은 저희가 선물로 드려요.</b><br>`
      + `${chargeSelectedPkg.emoji || ""} ${chargeSelectedPkg.label} `
      + `${data.credits_added.toLocaleString("ko-KR")}크레딧이 방금 들어왔고, `
      + `카드에서 빠져나간 돈은 없습니다.`;
  } catch (err) {
    $("#chargeDoneBody").textContent = err.message;
  }
}

function openChargeModal() {
  chargeSelectedPkg = null;
  $("#chargeModal").hidden = false;
  chargeStep("package");
  paintCreditPill();
  renderChargePackages();
  // "충전하기" 를 누른 시점을 기록한다 — 카드사까지 고른 시점(charge_success)과
  // 비교하면 클릭률(지불 의사)이 나온다. 실패해도 화면은 그대로 쓸 수 있어야
  // 한다.
  fetch("/api/credits/charge-click", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uid: UID }),
  }).catch(() => {});
}

function closeChargeModal() { $("#chargeModal").hidden = true; }

/* ------------------------------------------------------------------ 계정
 *
 * 닉네임+비밀번호만 있는 가벼운 계정 — 이메일 인증·비밀번호 찾기 없음.
 * 로그인 안 해도 웹툰은 그대로 만든다. 계정은 결과 화면의 "계정에
 * 담아두기" 를 통해서만 필요해지는 선택 기능이다. 세션은 서버가 쿠키
 * (lore_session, HttpOnly) 로 들고 있어서 여기서는 로그인 응답을 상태에
 * 반영하는 것만 신경 쓰면 된다. */

let accountState = { logged_in: false };
let signupPhoto = { kind: "preset", id: "" };   // 회원가입 폼에서 고른 사진
let pendingClaimRunId = "";                     // 담아두기 → 로그인/가입하면 이걸 담는다

/* 계정 상태를 처음 받아 오는 일은 화면 그리기와 **경주한다.** 주소로 바로
   /mypage 에 들어오면 이 요청이 끝나기 전에 마이페이지가 그려지고, 그때는
   아직 로그인 안 한 것으로 보여서 로그인 창이 떴다(로그인해 둔 사람인데도).
   그래서 이 약속을 들고 있다가, 계정이 필요한 화면이 먼저 기다리게 한다. */
let accountReady = null;

async function refreshAccount() {
  try {
    accountState = await (await fetch("/api/account/me")).json();
  } catch { accountState = { logged_in: false }; }
  paintAccountPill();
  paintClaimBanner();
  return accountState;
}

const GUEST_PILL_PHOTO = "/static/lou/react/idle/01.webp";   // 로그인 전 자리 채움 — accounts.DEFAULT_PHOTO_ID 와 같은 그림

/* 상단 바 배지. 로그인 전에는 「로그인」(누르면 계정 창), 로그인 뒤에는
   프로필 사진 + 「마이페이지」(누르면 마이페이지로 간다).
   닉네임 대신 「마이페이지」라고 적는 이유: 닉네임만 적혀 있으면 그것이
   **눌러서 갈 수 있는 자리**라는 것을 아무도 모른다. 닉네임은 마이페이지
   안에서 크게 보여 준다. */
let mockAccountPill = false;   // 목업에서만 켠다 — 로그인 뒤 모습을 보여주려고

function paintAccountPill() {
  const img = $("#accountAvatarImg"), label = $("#accountPillLabel");
  const btn = $("#accountBtn");
  if (mockAccountPill) {
    // /api/account/me 응답이 늦게 와서 배지를 다시 「로그인」으로 되돌리는 것을 막는다
    img.src = GUEST_PILL_PHOTO;
    label.textContent = "마이페이지";
    return;
  }
  if (accountState.logged_in) {
    img.src = accountState.photo_url;
    label.textContent = "마이페이지";
    if (btn) btn.title = `${accountState.nickname} · 내 작품 보기`;
  } else {
    img.src = GUEST_PILL_PHOTO;
    label.textContent = "로그인";
    if (btn) btn.title = "로그인 · 내 계정";
  }
}

/* ---- 이 브라우저가 만든 작품 ------------------------------------------- *
 *
 * "담아두기" 는 **내가 만든 것**에만 권해야 한다. 공유 링크를 받고 들어온
 * 사람에게도 뜨면, 남의 작품을 자기 계정에 담으라고 권하는 꼴이다.
 *
 * 그런데 결과 화면은 둘을 구분할 수가 없었다 — 내 목록에서 고른 것도, 남이
 * 보낸 링크도 똑같이 /works?run=… 으로 열리고 showRunResult() 하나가 받는다.
 * 서버도 못 가른다: 작품에 만든 사람이 안 적혀 있다(계정 기능이 소유자 개념을
 * 일부러 안 넣었다). 그래서 브라우저가 자기가 만든 것을 적어 둔다.
 *
 * localStorage 인 이유: 창을 닫아도 남아야 한다. sessionStorage 는 탭을 닫으면
 * 사라져서, 어제 만든 내 작품을 오늘 열면 남의 것처럼 보인다. */

const MY_RUNS_KEY = "lore_my_runs";
const MY_RUNS_MAX = 200;

function myRuns() {
  try {
    const v = JSON.parse(localStorage.getItem(MY_RUNS_KEY) || "[]");
    return Array.isArray(v) ? v.filter(x => typeof x === "string") : [];
  } catch { return []; }              // 비공개 창이거나 값이 깨졌을 때
}

function rememberMyRun(runId) {
  if (!runId) return;
  const list = myRuns().filter(x => x !== runId);
  list.push(runId);
  try {
    localStorage.setItem(MY_RUNS_KEY,
                         JSON.stringify(list.slice(-MY_RUNS_MAX)));
  } catch { /* 저장을 못 해도 만드는 것 자체는 막지 않는다 */ }
}

/* 내가 만든 것인가. 담아 둔 적이 있으면 그것도 내 것이다 — 폰에서 만들어
   담아 두고 PC 에서 열면 이 브라우저의 기록에는 없기 때문이다. */
function isMyRun(runId) {
  if (!runId) return false;
  return myRuns().includes(runId)
      || (accountState.claimed_runs || []).includes(runId);
}

/* 결과 화면의 "서버에 저장하기".
 *
 * 로그인 여부와 상관없이 **늘 보인다.** 로그인 전에 누르면 회원가입 창이 열리고,
 * 가입이 끝나면 보고 있던 작품이 그대로 담긴다 — 계정을 만들 이유가 처음
 * 생기는 자리가 여기다. 로그인한 사람에게도 보이는 이유는, 저장을 사용자가
 * 시켜야 하는 일로 두었기 때문이다(저절로 담으면 안 누른 사람은 자기 작품이
 * 어디 있는지 알 수 없다).
 *
 * 이미 담은 작품이면 감추는 대신 **눌리지 않는 「저장됨」** 으로 바꾼다.
 * 감춰 버리면 단추가 셋에서 둘로 줄어 자리가 흔들리고, 저장이 됐는지 안 됐는지도
 * 알 수 없다.
 *
 * 담을 작품이 없을 때(목업)와, **남이 보낸 링크로 들어온 작품**일 때는 안
 * 보인다 — 남의 작품을 자기 계정에 담으라고 권하는 꼴이 되기 때문이다
 * (위 isMyRun 참고). 목업은 흐름을 보여줘야 해서 showMockResult() 가 따로 켠다. */
function paintClaimBanner() {
  const mine = !!resultRunId && isMyRun(resultRunId);

  /* 남의 작품을 보고 있으면 **내 작품에만 있을 수 있는 단추**를 전부 감춘다.
     내려받기 · 편집실로 가기 · 공유하기 · 서버에 저장하기가 그렇다 — 남이
     그린 것을 내려받거나 고치러 들어가거나 내 것처럼 퍼뜨릴 자리가 아니다.
     읽는 것만 남는다. */
  ["#downloadBtn", "#editorLink", "#claimBtn"].forEach(sel => {
    const el = $(sel); if (el) el.hidden = !mine;
  });
  const share = $("#shareBtn");
  if (share && share.closest(".share-wrap")) share.closest(".share-wrap").hidden = !mine;
  // 감출 때는 열려 있던 공유 목록도 같이 닫는다 — 안 그러면 떠 있던 메뉴만
  // 남아서 어디에 붙은 것인지 모를 자리에 뜬다.
  if (!mine) { const menu = $("#shareMenu"); if (menu) menu.hidden = true; }
  // 단추 밑 한 줄 설명도 그 단추가 있을 때만 뜻이 있다.
  const note = $("#claimNote"); if (note) note.hidden = !mine;
  // 「내려받는 파일에는 LORE 표시가 붙습니다」는 내려받기가 있을 때만 뜻이 있다.
  const wm = $(".wm-note"); if (wm) wm.hidden = !mine;

  const btn = $("#claimBtn");
  if (!btn) return;
  const done = accountState.logged_in
    && (accountState.claimed_runs || []).includes(resultRunId);
  btn.disabled = done;
  btn.textContent = done ? "저장됨" : "서버에 저장하기";
}

async function claimCurrentRun() {
  if (!accountState.logged_in) {
    // 로그인 전이면 먼저 계정부터 만들게 하고, 되는 대로 이 작품을 담는다.
    pendingClaimRunId = resultRunId;
    openAccountModal("signup");
    return;
  }
  if (!resultRunId) return toast("화면 구경용 목업이라 담을 작품이 없습니다.");
  try {
    // uid 를 같이 보낸다 — 서버가 "이 작품을 만든 브라우저인가" 를 이것으로 본다.
    const res = await fetch("/api/account/claim", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: resultRunId, uid: getUid() }),
    });
    if (!res.ok) {
      // 서버가 이유를 준다(남의 작품이거나 이미 다른 계정에 담긴 작품).
      // 그 이유를 그대로 보여야 무엇이 잘못됐는지 안다.
      const why = (await res.json().catch(() => ({}))).error;
      throw new Error(why || "저장하지 못했습니다 — 다시 시도해 주세요");
    }
    accountState.claimed_runs = [...(accountState.claimed_runs || []), resultRunId];
    paintClaimBanner();
    toast("계정에 저장했어요 — 「마이페이지」에서 다시 열 수 있습니다");
  } catch (err) { toast(err.message || "저장하지 못했습니다 — 다시 시도해 주세요"); }
}

/* ---- 계정 모달 — 로그인/회원가입 탭, 로그인 후엔 프로필로 바뀐다 ------- */

function openAccountModal(tab) {
  $("#accountModal").hidden = false;
  if (accountState.logged_in) {
    showAccountProfile();
  } else {
    switchAccountTab(tab || "login");
    if (!$("#photoGrid").children.length) renderPhotoGrid();
  }
}
function closeAccountModal() { $("#accountModal").hidden = true; }

function switchAccountTab(tab) {
  $("#accountAuth").hidden = false;
  $("#accountProfile").hidden = true;
  $("#tabLogin").classList.toggle("is-active", tab === "login");
  $("#tabSignup").classList.toggle("is-active", tab === "signup");
  $("#loginForm").hidden = tab !== "login";
  $("#signupForm").hidden = tab !== "signup";
}

async function renderPhotoGrid() {
  let presets = [];
  try { presets = (await getConfig()).account_photo_presets || []; }
  catch { /* 프리셋을 못 받아도 직접 올리기는 된다 */ }
  const grid = $("#photoGrid");
  grid.innerHTML = presets.map(p => `
    <button type="button" class="photo-opt" data-preset="${p.id}">
      <img src="${p.url}" alt="">
    </button>`).join("");
  if (presets[0]) selectPresetPhoto(presets[0].id);
  $$(".photo-opt", grid).forEach(b =>
    b.addEventListener("click", () => selectPresetPhoto(b.dataset.preset)));
}

function selectPresetPhoto(id) {
  signupPhoto = { kind: "preset", id };
  $$(".photo-opt", $("#photoGrid")).forEach(b =>
    b.classList.toggle("is-selected", b.dataset.preset === id));
  $(".photo-upload-btn").classList.remove("is-selected");
}

async function onSignup(e) {
  e.preventDefault();
  const form = e.target;
  const err = $("#signupError");
  err.hidden = true;
  const body = {
    nickname: form.nickname.value.trim(),
    password: form.password.value,
    photo: signupPhoto,
    agree_terms: form.agree_terms.checked,
  };
  try {
    const res = await fetch("/api/account/signup", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "회원가입에 실패했습니다");
    await afterLogin(data);
  } catch (ex) { err.textContent = ex.message; err.hidden = false; }
}

async function onLogin(e) {
  e.preventDefault();
  const form = e.target;
  const err = $("#loginError");
  err.hidden = true;
  try {
    const res = await fetch("/api/account/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nickname: form.nickname.value.trim(), password: form.password.value }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "로그인에 실패했습니다");
    await afterLogin(data);
  } catch (ex) { err.textContent = ex.message; err.hidden = false; }
}

async function afterLogin(data) {
  accountState = data;
  paintAccountPill();
  if (pendingClaimRunId) {
    const runId = pendingClaimRunId;
    pendingClaimRunId = "";
    try {
      await fetch("/api/account/claim", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: runId }),
      });
      accountState.claimed_runs = [...(accountState.claimed_runs || []), runId];
    } catch { /* 로그인 자체는 됐다 — 결과 화면에서 배너를 다시 누르면 된다 */ }
  }
  paintClaimBanner();
  closeAccountModal();
  toast(`${accountState.nickname}님, 반가워요`);
}

async function showAccountProfile() {
  $("#accountAuth").hidden = true;
  $("#accountProfile").hidden = false;
  $("#profileAvatarImg").src = accountState.photo_url;
  $("#profileNickname").textContent = accountState.nickname;
  const list = $("#accountWorksList");
  list.innerHTML = `<p class="works-empty">불러오는 중…</p>`;
  try {
    const runs = (await (await fetch("/api/account/works")).json()).runs || [];
    list.innerHTML = runs.length
      ? runs.map(workCard).join("")
      : `<p class="works-empty">아직 담아둔 작품이 없습니다 — 결과 화면에서 ` +
        `"계정에 담아두기" 를 눌러 보세요.</p>`;
    $$("[data-open]", list).forEach(b => b.addEventListener("click", () => {
      closeAccountModal();
      showRunResult(b.dataset.open, Number(b.dataset.ep));
    }));
  } catch {
    list.innerHTML = `<p class="works-empty">목록을 불러오지 못했습니다.</p>`;
  }
}

async function logout() {
  try { await fetch("/api/account/logout", { method: "POST" }); }
  catch { /* 실패해도 화면은 로그아웃으로 바꾼다 */ }
  accountState = { logged_in: false };
  paintAccountPill();
  paintClaimBanner();
  switchAccountTab("login");
}

/* ------------------------------------------------------------- 위저드

   흐름은 사람이 겪는 순서다.

     1걸음  무엇을 만들 건지 — 사진 · 캐릭터 설명 · 이야기 한 줄
     2걸음  **어떻게** 만들지 — 스토리 모드 / 전문가 모드 (갈림길)
     3~5걸음  전문가를 고른 사람에게만 이어진다 (세계 · 그림 · 확인)

   그래서 걸음 수가 고정이 아니다 — 스토리 모드는 2걸음에서 끝나고 바로
   출발하고, 전문가 모드는 5걸음까지 간다. 수심계도 그에 맞춰 늘어난다.
   늘어나는 것 자체가 "더 물어보는 길을 골랐다"는 신호라서 숨기지 않는다.

   칸은 여전히 하나도 안 지웠다 — 전부 같은 <form> 안에 있고 보이는 걸음만
   바뀐다. 그래서 collect() 는 어느 걸음에 서 있든 전부 걷는다. */

const WIZ_FORK = 5;                       // 갈림길 = 마지막 걸음
const WIZ_SIMPLE_LAST = 5;
// 전문가도 더 안 묻는다 — 다른 것은 도중에 몇 번 멈추느냐뿐이고,
// 그건 서버(checkpoints)가 정한다. 그래서 두 길의 걸음 수가 같다.
const WIZ_EXPERT_LAST = 5;
const WIZ_NAMES = ["수면", "항해", "깊은 바다", "심해", "바닥"];
let wizStep = 1;
/* 이번 실행에서 고른 길. localStorage 의 모드와 **일부러 따로 둔다** —
   지난번에 전문가로 만들었다고 이번에도 말없이 전문가 길로 끌고 가면, 갈림길
   화면이 있으나 마나가 된다. 고르는 것은 매번 다시 한다. (고른 값은 그때
   setMode 로 localStorage 에도 남아서 시트 편집 폼 같은 다른 자리에 쓰인다.) */
let wizChoice = null;

// 지금 길의 마지막 걸음. 아직 안 골랐으면 갈림길까지만 보여준다.
function wizLast() { return WIZ_SIMPLE_LAST; }   // 두 길의 걸음 수가 같다

function wizPaintGauge() {
  const gauge = $("#wizGauge");
  if (!gauge) return;
  const last = wizLast();
  gauge.innerHTML = WIZ_NAMES.slice(0, last).map((name, i) => {
    const n = i + 1;
    const state = n < wizStep ? "done" : (n === wizStep ? "on" : "");
    return `<li class="wiz-tick ${state}" title="${n}. ${name}"
                ${n === wizStep ? 'aria-current="step"' : ""}></li>`;
  }).join("");
}

// 요약 — 비운 칸은 "루가 정합니다"로 적는다. 안 적었다는 사실 자체가 결과로
// 보여야, 마지막 걸음에서 되돌아갈지 말지를 판단할 수 있다.
function wizPaintSummary() {
  const box = $("#wizSummary");
  if (!box) return;
  const form = $("#form");
  const auto = `<i class="wiz-auto">루가 정합니다</i>`;
  const val = v => (v && v.trim()) ? esc(v.trim()) : auto;
  const cut = (v, n) => {
    const t = (v || "").trim();
    return t ? esc(t.slice(0, n)) + (t.length > n ? "…" : "") : auto;
  };

  const styleEl = form.style;
  const styleLabel = styleEl
    ? (document.querySelector(`.style-opt input[value="${styleEl.value}"]`)
        ?.closest(".style-opt")?.querySelector("b")?.textContent || styleEl.value)
    : "";

  // 화면에 있는 것만 적는다. 설명·항목·세계관은 이제 안 묻는 칸이라 뺐다 —
  // 요약에 "루가 정합니다" 가 줄줄이 뜨면 안 물어본 것을 물어본 것처럼 보인다.
  const rows = [
    ["캐릭터", val(form.name.value)],
    ["사진", photos.length ? `${photos.length}장` : `<i class="wiz-auto">없음</i>`],
    ["설명", cut(form.character.value, 34)],
    ["이야기", cut(form.story.value, 34)],
    ["장르", val(form.genre.value)],
    ["그림체", styleLabel ? esc(styleLabel) : auto],
    ["보는 방식", wizChoice === "expert" ? "3번만 확인하며" : "빠르게 결과부터"],
  ];
  box.innerHTML = rows.map(([k, v]) =>
    `<div class="wiz-row"><span>${k}</span><b>${v}</b></div>`).join("");
}

function wizGo(n, scroll = true) {
  const last = wizLast();
  // 갈림길을 벗어나면 고른 것을 지운다 — 다시 들어오면 기본값(빠르게)부터다.
  if (n !== WIZ_FORK) wizChoice = null;
  wizStep = Math.min(last, Math.max(1, n));
  $$(".wiz-step").forEach(p => { p.hidden = Number(p.dataset.step) !== wizStep; });

  document.body.dataset.step = String(wizStep);
  pickWizLou();

  // 갈림길에서는 늘 고르게 한다 — 지난번 모드가 기억돼 있어도 마찬가지다.
  // 갈림길에 들어서면 **빠르게**가 이미 골라져 있다. 아무것도 안 고른 채로
  // 요약과 만들기 단추가 안 보이면 화면이 멈춘 것처럼 읽혀서, 기본값을 두고
  // 바꾸고 싶은 사람만 다른 카드를 누르게 한다.
  if (wizStep === WIZ_FORK && !wizChoice) {
    wizChoice = "simple";
    setMode("simple");
  }
  const atFork = false;
  const atEnd  = wizStep === last;

  // 갈림길에서는 아래 단추를 안 쓴다 — 고르는 것이 곧 넘어가는 것이다.
  $("#wizNext").hidden = atFork || atEnd;
  $("#submitBtn").hidden = !(atEnd && !atFork);
  $("#ipAgreeLine").hidden = !(atEnd && !atFork);
  $("#wizSkip").hidden = atFork || atEnd;
  // 「이전」은 1걸음에서 갈 곳이 없으니 아예 안 보인다.
  // 예전에는 이 자리를 「홈으로」로 바꿔 놨었다. 아무도 시키지 않은 단추였고,
  // 홈으로 가는 문은 이미 헤더의 LORE 하나로 충분하다 — 같은 일을 하는 문이
  // 화면에 둘이면 어느 쪽이 무엇인지 고민하게 만든다.
  $("#wizPrev").hidden = wizStep === 1;
  $("#wizPrev").textContent = "이전";
  $("#submitNote").hidden = !(atEnd && !atFork);
  $(".wiz-foot").hidden = atFork;

  if (wizStep === WIZ_FORK) {
    $$(".fork-card").forEach(c =>
      c.setAttribute("aria-pressed", String(c.dataset.mode === wizChoice)));
  }
  if (atEnd && !atFork) wizPaintSummary();
  wizPaintGauge();

  if (!scroll) return;
  window.scrollTo({ top: 0, behavior: "smooth" });   // 걸음마다 화면 맨 위부터
}

function setupWizard() {
  if (!$("#wizGauge")) return;
  const move = n => wizGo(n);
  // 홈의 시작하기 — 아래로 스크롤이 아니라 **화면 전환**이다. 캔버스에서
  // 홈과 만들기는 다른 아트보드다.
  const openCreate = () => {
    view("create");
    wizGo(1, false);
    window.scrollTo(0, 0);
  };
  const closeCreate = () => {
    view("landing"); pickHero();
    window.scrollTo(0, 0);
  };
  pickHero();
  const start = $("#startBtn");
  if (start) start.addEventListener("click", openCreate);
  // 헤더의 LORE 는 어느 화면에서든 홈으로 돌아가는 문이다. 새로고침 없이
  // 되돌리되(입력이 날아가지 않게), 만드는 중일 때는 붙잡는다 — 여기서 나가면
  // 돌고 있는 작업을 놓치기 때문.
  const brand = $("#brandHome");
  if (brand) brand.addEventListener("click", e => {
    e.preventDefault();
    if (document.body.dataset.view === "running") {
      toast("루가 만드는 중이에요 — 끝나면 보여드릴게요");
      return;
    }
    forget();
  });
  // 1걸음의 약속: 사진과 이름은 필수다. 없이 넘어가려 하면 그 자리에서 말한다.
  const step1ok = () => {
    const form = $("#form");
    if (!photos.length) { toast("캐릭터 사진을 올려주세요"); return false; }
    if (!form.name.value.trim()) { toast("이름을 적어주세요"); form.name.focus(); return false; }
    return true;
  };
  $("#wizNext").addEventListener("click", () => {
    if (wizStep === 1 && !step1ok()) return;
    move(wizStep + 1);
  });
  $("#wizSkip").addEventListener("click", () => {
    if (wizStep === 1 && !step1ok()) return;
    move(wizStep + 1);
  });
  const back = () => {
    if (wizStep === 1) { closeCreate(); return; }   // 1걸음의 뒤 = 홈
    move(wizStep - 1);
  };
  $("#wizPrev").addEventListener("click", back);
  $("#wizBack").addEventListener("click", back);

  // 갈림길 — 고르는 것이 곧 다음 동작이다.
  //   스토리 모드: 여기서 바로 출발한다(더 물어볼 것이 없다).
  //   전문가 모드: 길이 3걸음 늘어나고 그 첫 걸음으로 넘어간다.
  $$(".fork-card").forEach(card => card.addEventListener("click", () => {
    const mode = card.dataset.mode;
    wizChoice = mode;
    setMode(mode);
    $$(".fork-card").forEach(c =>
      c.setAttribute("aria-pressed", String(c === card)));
    // 고른 즉시 출발하지 않는다 — 무엇으로 만드는지 한 번은 보고 눌러야
    // "이럴 줄 몰랐다"가 안 나온다. 요약만 새로 그린다.
    wizPaintSummary();
  }));

  wizGo(1, false);
}

/* ------------------------------------------------------------------ 제출 */

function collect() {
  const form = $("#form");
  const fields = {};
  $$("[data-field]", form).forEach(el => {
    if (el.value.trim()) fields[el.dataset.field] = el.value.trim();
  });
  return {
    uid:        UID,
    name:       form.name.value.trim(),
    character:  form.character.value.trim(),
    photo_note: form.photo_note.value.trim(),
    fields,
    genre:      form.genre.value.trim(),
    world:      form.world.value.trim(),
    world_preset: form.world_preset ? form.world_preset.value : "",
    story:      form.story.value.trim(),
    style:      form.style.value,
    // "" | sd | md | ld. 빈 값이면 그림체가 정한 등신 그대로 간다.
    head_ratio: form.head_ratio ? form.head_ratio.value : "",
    // fast(한 장에 3컷) | webtoon(컷마다 한 장). 비우면 fast — 지금까지의 방식이다.
    layout_mode: form.layout_mode ? form.layout_mode.value : "webtoon",
    // 지금은 **항상 미리보기**다. 한 화를 통째로 굽기 전에 앞 3컷을 먼저
    // 보여주고, 마음에 들면 이어서 그린다(/api/runs/<id>/continue).
    preview:    true,
    // 전문 모드인가. 서버는 이 한 값으로 어디서 멈출지(checkpoints)와 무엇을
    // 고를 수 있는지를 정한다. 이번 실행에 박히므로, 도는 도중에 모드를
    // 바꿔도 이 작업의 검수 지점은 안 바뀐다.
    expert:     isExpert(),
    // 전문 모드에서만 읽힌다 — 일반 모드는 서버가 기본값(2)으로 되돌린다.
    art_qa_regen_max: form.art_qa_regen_max
      ? Number(form.art_qa_regen_max.value) : 2,
    photos_data: photos,
    // 만들 때마다 짧게 받는 저작권 확인 — 서버도 이 값을 다시 확인한다.
    agree_ip: $("#ipAgreeCheck").checked,
  };
}

/* 실제로 출발시킨다. 갈림길에서 "스토리 모드"를 고른 것과 마지막 걸음에서
   "웹툰 만들기"를 누른 것이 같은 일을 하므로, 단추 핸들러가 아니라 이 함수를
   양쪽이 함께 부른다. 실패하면 그 자리에 남아서 이유를 보여준다 — 여기서
   진행 화면으로 넘어가 버리면 무엇이 잘못됐는지 볼 자리가 없다. */
async function startRun() {
  const btn = $("#submitBtn"), note = $("#submitNote");
  const fork = $$(".fork-card");
  note.hidden = false;
  note.classList.remove("error");
  // 저작권 확인 체크는 여기서 먼저 막는다 — 서버도 다시 확인하지만, 여기서
  // 잡아야 사람이 왜 안 되는지 바로 안다(서버 오류로 보이면 안 된다).
  if (!$("#ipAgreeCheck").checked) {
    note.textContent = "저작권 확인에 동의해야 만들 수 있습니다";
    note.classList.add("error");
    return;
  }
  note.textContent = "루가 바다로 나가는 중…";
  btn.disabled = true;
  fork.forEach(c => { c.disabled = true; });
  try {
    const res = await fetch("/api/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collect()),
    });
    const data = await res.json();
    if (!res.ok) {
      if (res.status === 402) {
        // 크레딧이 모자란다 — 그 자리에서 충전 모달로 보낸다.
        note.textContent = "";
        note.append(document.createTextNode((data.error || "크레딧이 모자랍니다") + " "));
        const chargeLink = document.createElement("button");
        chargeLink.type = "button";
        chargeLink.className = "inline-link";
        chargeLink.textContent = "충전하기";
        chargeLink.addEventListener("click", openChargeModal);
        note.appendChild(chargeLink);
        note.classList.add("error");
        return;
      }
      throw new Error(data.error || "시작하지 못했습니다");
    }
    jobId = data.id;
    sessionStorage.setItem("lore_job", jobId);
    if (data.credit_balance != null) { creditBalance = data.credit_balance; paintCreditPill(); }
    shownCuts = new Set();
    startPolling();
  } catch (err) {
    note.textContent = err.message;
    note.classList.add("error");
  } finally {
    btn.disabled = false;
    fork.forEach(c => { c.disabled = false; });
    paintCost();
  }
}

function submit(e) { e.preventDefault(); startRun(); }

/* ------------------------------------------------------------------ 진행 */

/* 만드는 일은 **서버에서** 돈다. 그래서 화면이 진행 화면일 필요가 없다 —
   둘러보기나 마이페이지를 보는 동안에도 폴링은 그대로 돌고, 지금 어디까지
   왔는지는 떠 있는 표시(#miniProg)가 들고 다닌다.

   `background: true` 면 화면을 진행 화면으로 옮기지 않는다 (둘러보다 새로고침한
   경우, 또는 진행 화면에서 「둘러보기」로 빠져나간 경우). */
function startPolling(opts = {}) {
  if (!opts.background) view("running");
  lastStatus = null;
  tick();
  clearInterval(poll);
  poll = setInterval(tick, 800);
}

async function tick() {
  if (!jobId) return;
  let state;
  try {
    const res = await fetch(`/api/jobs/${jobId}`);
    if (res.status === 404) { forget(); return; }
    state = await res.json();
  } catch { return; }             // 잠깐 끊긴 것뿐이면 다음 번에 다시 받는다

  // **어느 화면에 있든** 그린다. 확인 팝업(#approvalModal)이 여기서 뜨는데,
  // 그 팝업이 떠 있는 동안은 서버에서도 아무것도 안 돌아간다 — 둘러보러 나가
  // 있다고 안 알리면 사람은 만들어지는 줄 알고 기다리고, 실제로는 자기 차례에서
  // 멈춰 있다. 그래서 이것만은 보던 화면을 가로채는 쪽이 맞다.
  // (팝업은 #progress 바깥에 있다 — 안에 두면 그 화면이 숨을 때 같이 숨는다.)
  renderProgress(state);
  paintMini(state);

  if (state.status === "done") {
    clearInterval(poll); poll = null;
    // 다 됐으면 어디에 있든 완성본으로 데려간다. 기다리다 나간 사람이 바라던
    // 것이 이것이라, 표시만 바꿔 두고 알아서 누르기를 기다릴 이유가 없다.
    showResult();
  } else if (state.status === "error" || state.status === "cancelled") {
    clearInterval(poll); poll = null;
    // 실패도 마찬가지로 알린다 — 나가 있는 동안 조용히 멈춰 있으면, 사람은
    // 계속 만들어지는 줄 알고 기다린다.
    renderFailure(state);
  }
  lastStatus = state.status;
}

function mmss(sec) {
  const s = Math.max(0, Math.round(sec));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/* ---- 확인 화면이 보여줄 본문 ------------------------------------------- *
 *
 * "이대로 진행할까요?" 를 물으려면 무엇을 진행할지가 보여야 한다. 스토리는
 * 장면 셋, 콘티는 컷과 대사를 그대로 편다. 값이 없으면(파일이 덜 씌었거나
 * 옛 run) 자리를 통째로 비운다 — :empty 로 상자까지 사라진다. */

function renderStoryPreview(sp) {
  const host = $("#storyPreview");
  if (!host) return;
  if (!sp || !(sp.scenes || []).length) { host.innerHTML = ""; return; }
  const head = [
    sp.title ? `<p class="ap-title">${esc(sp.title)}</p>` : "",
    sp.logline ? `<p class="ap-logline">${esc(sp.logline)}</p>` : "",
    sp.hook ? `<p class="ap-hook">${esc(sp.hook)}</p>` : "",
  ].join("");
  host.innerHTML = head + sp.scenes.map(s => `
    <div class="ap-scene">
      <div class="ap-no">${esc(s.no)}번째 장면</div>
      ${s.one_line ? `<p class="ap-one">${esc(s.one_line)}</p>` : ""}
      ${s.text ? `<p class="ap-text">${esc(s.text)}</p>` : ""}
      ${s.changed ? `<p class="ap-changed">→ ${esc(s.changed)}</p>` : ""}
    </div>`).join("");
}

function renderBoardPreview(bp) {
  const host = $("#boardPreview");
  if (!host) return;
  if (!bp || !(bp.cuts || []).length) {
    // 컷이 하나도 안 나온 게이트 소진 — 보여줄 콘티가 없다는 것 자체가
    // 정보다. 빈 칸으로 두면 "왜 아무것도 안 보이지" 로 헷갈린다.
    host.innerHTML = `<p class="ap-hook">이번 시도는 컷이 하나도 안 나왔습니다 — 보여드릴 콘티가 없어요.</p>`;
    return;
  }
  const head = (bp.title ? `<p class="ap-title">${esc(bp.title)}</p>` : "")
    + (bp.draft ? `<p class="ap-hook">게이트에 걸린 마지막 시도입니다 — 아직 통과한 콘티가 아닙니다.</p>` : "");
  host.innerHTML = head + bp.cuts.map(c => {
    const lines = [];
    if (c.narration) lines.push(`<p class="ap-line narration">${esc(c.narration)}</p>`);
    if (c.dialogue) lines.push(`<p class="ap-line"><span class="who">${esc(c.speaker || "?")}</span> ${esc(c.dialogue)}</p>`);
    if (c.thought) lines.push(`<p class="ap-line narration">(${esc(c.thought)})</p>`);
    if (c.sfx) lines.push(`<p class="ap-line sfx">${esc(c.sfx)}</p>`);
    return `<div class="ap-scene">
      <div class="ap-no">CUT ${String(c.no).padStart(2, "0")}${c.shot ? " · " + esc(c.shot) : ""}</div>
      ${lines.join("")}
      ${c.description ? `<p class="ap-text">${esc(c.description)}</p>` : ""}
    </div>`;
  }).join("");
}

function renderProgress(s) {
  $("#clock").textContent = mmss(s.elapsed);

  // 검수 화면은 **그 작업이 시작될 때의 모드**를 따른다 (localStorage 가 아니라
  // 서버가 준 s.expert). 도는 중에 모드를 바꾼 사람에게, 시작할 때 약속한 것과
  // 다른 화면이 뜨면 안 된다.
  const jobExpert = !!s.expert;
  const sheetEdit = $(".sheet-approval-edit");
  if (sheetEdit) sheetEdit.hidden = !jobExpert;
  // 일반 모드에는 외형 편집 폼이 없으니 "수정 반영해서" 라고 하면 안 맞는다 —
  // 그 모드의 다시 만들기는 시트를 한 번 더 뽑는 것이다.
  $("#sheetRetryBtn").textContent =
    jobExpert ? "수정 반영해서 다시 만들기" : "다시 만들기";

  const approvalBox = $("#sheetApproval");
  if (s.status === "awaiting_sheet_approval") {
    approvalBox.hidden = false;
    // 매번 새로 그리지 않는다 — '다시 만들기'로 두 번째 시트가 나왔을 때만
    // 이미지 src 를 바꾼다. no-store 라 캐시는 안 걸리지만, 같은 문자열로
    // src 를 다시 대입하면 브라우저가 재요청하지 않는 경우가 있어 캐시
    // 버스터를 붙인다.
    if (lastStatus !== "awaiting_sheet_approval") {
      const v = Date.now();
      $("#approvalSheet").src = `/api/jobs/${jobId}/sheet?v=${v}`;
      const photoBox = $("#approvalPhotoBox");
      if (s.has_photo) {
        photoBox.hidden = false;
        $("#approvalPhoto").src = `/api/jobs/${jobId}/photo?v=${v}`;
      } else {
        photoBox.hidden = true;
      }
      setSheetButtonsBusy(false);
      loadSheetFields();
    }
  } else {
    approvalBox.hidden = true;
  }

  // 사람 확인이 필요한 이유 — 그 단계가 남긴 note 를 그대로 보여준다.
  // "멈췄습니다"만 뜨고 왜 멈췄는지 안 보이면 사용자가 판단할 근거가 없다.
  const currentStage = s.stages && s.stages[s.stage_index];
  const stageReason = (currentStage && currentStage.note) || "";

  const storyApprovalBox = $("#storyApproval");
  if (s.status === "awaiting_story_approval") {
    storyApprovalBox.hidden = false;
    $("#storyApprovalReason").textContent = stageReason;
    if (lastStatus !== "awaiting_story_approval") {
      setStoryButtonsBusy(false);
      wireMemory(s.run_id);
      renderStoryPreview(s.story_preview);
    }
  } else {
    storyApprovalBox.hidden = true;
  }

  const boardApprovalBox = $("#boardApproval");
  if (s.status === "awaiting_board_approval") {
    boardApprovalBox.hidden = false;
    $("#boardApprovalReason").textContent = stageReason;
    // 컷이 하나도 안 나온 판이면 "이대로 진행" 은 고를 것이 없는데도 버튼은
    // 늘 떠 있었다 — 눌러도 그 자리에서 실패로 끝났다(2026-08-26 실사용
    // 확인). 진행할 콘티가 있을 때만 그 버튼을 보여준다.
    const hasCuts = !!(s.board_preview && (s.board_preview.cuts || []).length);
    $("#boardApproveBtn").hidden = !hasCuts;
    $("#boardApprovalExplain").innerHTML = hasCuts
      ? `자동으로 다시 쓰는 시도(게이트 재시도)를 다 써서 더 못 고쳤습니다.
         <b>이대로 진행</b>하면 지금 이 콘티 그대로 그림 단계로 넘어갑니다 —
         <b>다시 만들기</b>를 누르면 콘티를 처음부터 다시 짭니다(새 시도이니
         다른 결과가 나올 수 있습니다).`
      : `자동으로 다시 쓰는 시도(게이트 재시도)를 다 썼는데 컷이 하나도 안
         나왔습니다 — 넘어갈 콘티 자체가 없어서 <b>다시 만들기</b>만
         가능합니다. 무엇이 빠졌는지 아래에 적어 주시면 다음 시도에
         반영됩니다.`;
    if (lastStatus !== "awaiting_board_approval") {
      setBoardButtonsBusy(false);
      wireMemory(s.run_id);
      renderBoardPreview(s.board_preview);
    }
  } else {
    boardApprovalBox.hidden = true;
  }

  const artqaBox = $("#artqaApproval");
  if (s.status === "awaiting_artqa_approval") {
    artqaBox.hidden = false;
    if (lastStatus !== "awaiting_artqa_approval") {
      renderArtQa(s.art_qa || {});
      $("#artqaApproveBtn").disabled = false;
    }
    // 이 자리에서는 중단할 것이 없다 — 그림은 이미 다 나왔다. 버튼을 남겨 두면
    // "다 만든 것을 버리는 버튼" 으로 읽힌다(서버는 어느 쪽이든 완성으로
    // 끝내지만, 누르는 사람은 그걸 모른다).
    $("#cancelBtn").hidden = true;
  } else {
    artqaBox.hidden = true;
    $("#cancelBtn").hidden = false;
  }

  // 확인이 필요한 자리는 팝업으로 띄운다 — 진행 화면 아래에 붙어 있으면
  // 기다리는 사람이 자기 차례가 온 것을 모른다.
  const waiting = ["awaiting_sheet_approval", "awaiting_story_approval",
                   "awaiting_board_approval", "awaiting_artqa_approval"]
                  .includes(s.status);
  $("#approvalModal").hidden = !waiting;
  // 팝업이 떠 있는 동안에는 뒤가 안 굴러가게 — 확인 창 뒤로 웹툰이 스크롤되면
  // 어디를 보고 있는지 헷갈린다.
  document.body.classList.toggle("modal-open", waiting);

  if (s.status === "queued") {
    $("#progEyebrow").textContent = "대기 중";
    $("#progTitle").textContent = "앞에 만들고 있는 작품이 있습니다";
    $("#progSub").textContent =
      `한 번에 한 편씩 만듭니다 — 앞에 ${s.queue_position}편이 있습니다.`;
  } else if (s.status === "running") {
    $("#progEyebrow").textContent = `${s.style_label}${s.preview ? " · 미리보기" : ""}`;
    $("#progTitle").textContent = "웹툰을 만들고 있습니다";
    const art = s.art;
    $("#progSub").textContent = art && art.eta_sec
      ? `그림 단계입니다 — 남은 시간 약 ${mmss(art.eta_sec)}.`
      : "지금 무엇을 하고 있는지 아래에 그대로 보여드립니다.";
  } else if (s.status && s.status.startsWith("awaiting_")) {
    // 멈춰서 기다리는 중인데 "만들고 있습니다" 가 그대로 떠 있으면, 사용자는
    // 자기 차례인 줄 모르고 계속 기다린다 — 실제로 아무것도 안 돌아간다.
    $("#progEyebrow").textContent = "확인이 필요합니다";
    $("#progTitle").textContent = "잠깐 봐 주세요";
    $("#progSub").textContent = s.status === "awaiting_artqa_approval"
      ? "그림은 다 나왔습니다. 검수 결과만 확인하면 끝납니다."
      : "아래에서 확인하고 넘어가 주세요 — 그동안은 아무것도 안 돌아갑니다.";
  }

  paintMascot(s, currentStage);
  paintRefusals(s.refusals);

  $("#rail").innerHTML = s.stages.map((st, i) => {
    const num = String(i + 1).padStart(2, "0");
    const mark = st.state === "done" ? "✓" : st.state === "error" ? "!" : num;
    const steps = st.steps.filter(x => x.state !== "skip").map(x => `
      <li data-state="${x.state}">
        <span class="tick">${x.state === "done" ? "✓" : ""}</span>${x.label}
      </li>`).join("");
    const showSteps = st.state === "active" || st.state === "error";
    const bar = (st.key === "art" && s.art && s.art.total)
      ? `<div class="bar"><i style="width:${Math.round(s.art.done / s.art.total * 100)}%"></i></div>`
      : "";
    const time = st.seconds != null ? `${mmss(st.seconds)}` : "";
    return `
      <li class="stage" data-state="${st.state}">
        <span class="stage-dot">${mark}</span>
        <div class="stage-main">
          <h3>${st.title}</h3>
          <p class="stage-desc">${st.desc}</p>
          ${st.note && showSteps ? `<p class="stage-note">${esc(st.note)}</p>` : ""}
          ${showSteps ? `<ul class="steps">${steps}</ul>${bar}` : ""}
        </div>
        <span class="stage-time">${time}</span>
      </li>`;
  }).join("");

  // 그려진 장은 나오는 대로 보여준다 — 10분을 빈 화면으로 기다리게 하지 않는다.
  if (s.ready_cuts.length) {
    $("#cutstrip").hidden = false;
    $("#cutCount").textContent = s.art
      ? `${s.art.done} / ${s.art.total}장` : `${s.ready_cuts.length}장`;
    for (const n of s.ready_cuts) {
      if (shownCuts.has(n)) continue;
      shownCuts.add(n);
      const fig = document.createElement("figure");
      fig.innerHTML = `<img src="/api/jobs/${jobId}/page/${n}?w=260" alt="${n}번째 장" loading="lazy">
                       <figcaption>${n}</figcaption>`;
      $("#cutGrid").append(fig);
    }
  }

  $("#logBox").textContent = s.log.join("\n");
}

// ------------------------------------------------------------------ 거절
// 이미지 모델이 "못 그리겠다"고 답한 장을 사용자에게 그대로 보여준다. 사유를
// 숨기고 "생성 실패"라고만 쓰면 사용자는 무엇을 고쳐야 할지 알 수 없다.
function paintRefusals(list) {
  const box = $("#refusals");
  if (!box) return;
  if (!list || !list.length) { box.hidden = true; return; }
  box.hidden = false;
  $("#refusalList").innerHTML = list.map(r => `
    <li class="refusal">
      <div class="refusal-top">
        <span class="refusal-code">${esc(r.reason)}</span>
        <span class="refusal-where">${r.cut_number != null
          ? `${esc(String(r.cut_number))}번째 ${esc(r.unit || "장")}` : ""}</span>
      </div>
      <p class="refusal-hint">${esc(r.hint)}</p>
      ${r.model_said ? `<p class="refusal-said">모델이 한 말 — ${esc(r.model_said)}</p>` : ""}
      ${r.description ? `<p class="refusal-desc">해당 장면 — ${esc(r.description)}</p>` : ""}
    </li>`).join("");
}

// ---------------------------------------------------------------- 마스코트
// 단계 key → 표정 + 한 줄. 사용자는 10분 가까이 이 화면을 본다. rail 은 무엇을
// 하는지 기계적으로 적고, 마스코트는 그걸 사람 말로 한 번 더 말한다.
/* 단계 문구는 **지금 실제로 무엇을 하는지**만 말한다. 여기에 "루가 춤추고
   있어요" 같은 걸 섞으면 진행 표시가 아니라 잡담이 된다 — 노는 것은 아래
   상호작용 자리에서 따로 한다. 문구는 레퍼런스(design-reference/loading/*)의
   말을 그대로 따른다. */
const MASCOT_MOODS = {
  story: ["write", "루가 이야기를 만들고 있어요"],
  sheet: ["draw", "루가 캐릭터를 디자인하고 있어요"],
  board: ["read", "루가 콘티를 짜고 있어요"],
  art:   ["draw", "루가 그림을 그리고 있어요"],
  bind:  ["read", "루가 완성도를 확인하고 있어요"],
};
const MASCOT_WAITING = "루가 확인을 기다리고 있어요";

/* 전체 진행률. 다섯 단계를 같은 무게로 치고, 그림 단계 안에서는 그린 장
   수(s.art.done/total)로 더 잘게 나눈다. 정확한 예측이 아니라 "움직이고
   있다"를 보여주는 숫자다 — 그래서 단계가 뒤로 돌아가도 숫자는 안 줄인다. */
let louPctShown = 0;
function louPercent(s) {
  const stages = (s.stages || []).filter(st => st.state !== "skip");
  if (!stages.length) return 0;
  let done = 0, frac = 0;
  stages.forEach((st, i) => {
    if (st.state === "done") done += 1;
    else if (i === s.stage_index) {
      if (st.key === "art" && s.art && s.art.total) frac = s.art.done / s.art.total;
      else frac = 0.35;              // 단계 중간쯤이라고 친다
    }
  });
  let pct = Math.round((done + frac) / stages.length * 100);
  if (s.status === "done") pct = 100;
  louPctShown = Math.max(louPctShown, Math.min(100, pct));
  return louPctShown;
}

function paintLouProgress(s) {
  const fill = $("#louBarFill"), label = $("#louPct");
  if (!fill) return;
  const pct = louPercent(s);
  fill.style.width = pct + "%";
  label.textContent = pct + "%";
  const box = $("#louProgress");
  if (box) box.setAttribute("aria-valuenow", String(pct));
}

function paintMascot(s, currentStage) {
  let mood = "think";
  let line = "";

  if (s.status && s.status.startsWith("awaiting_")) {
    mood = "ask";
    line = MASCOT_WAITING;
  } else if (s.status === "done") {
    mood = "done";
    line = "루가 다 그렸어요!";
  } else if (s.status === "error" || s.status === "canceled") {
    mood = "error";
    line = s.status === "canceled" ? "루가 멈췄어요" : "루가 여기서 막혔어요";
  } else if (s.status === "queued") {
    mood = "think";
    line = "루가 차례를 기다리고 있어요";
  } else if (currentStage) {
    const hit = MASCOT_MOODS[currentStage.key];
    if (hit) [mood, line] = hit;
  }

  paintLouProgress(s);
  // 단계 그림은 #stageArt 가 그린다 — 단계 key 를 적으면 style.css 가
  // web/lou/stage/<key>.webp 로 바꿔 준다 (이야기 → 캐릭터 → 콘티 → 그림 → 검수).
  // 예전에는 이 값을 #mascot 에 적고 있어서, 실제 화면에서는 단계 그림이
  // 한 번도 안 바뀌었다 (CSS 는 .stage-art 를 보고 있었다).
  const art = $("#stageArt");
  if (art) {
    art.dataset.mood = mood;
    // 막혔을 때(error)만 그림을 직접 얹는다 — 루가 두 마리라 어느 쪽이
    // 나올지 뽑아야 하는데, 나머지 단계처럼 CSS 에 적어 두면 뽑을 수가 없다.
    // 막힌 것이 풀리면 다시 CSS 가 정하도록 얹었던 것을 걷는다.
    if (mood === "error") art.style.backgroundImage = `url("${louArt("error")}")`;
    else art.style.removeProperty("background-image");
    // 확인을 기다리는 중이어도 일하던 단계 그림을 그대로 둔다 — 어디서 멈췄는지가
    // 보여야 한다. 다 됐거나(done) 막혔을 때(error)는 mood 쪽 그림이 이긴다.
    if (currentStage && currentStage.key) art.dataset.stage = currentStage.key;
    else delete art.dataset.stage;
  }
  $("#mascotLine").textContent = line;
}

/* ---- 루와 놀기 ------------------------------------------------------- *
 *
 * 10분 가까이 이 화면을 본다. rail 은 무엇을 하는지 기계적으로 적고,
 * 마스코트 줄은 그걸 사람 말로 한 번 더 말한다. 여기 있는 것은 세 번째 —
 * **만질 수 있다**는 것. 기다림이 구경거리가 되면 시간이 덜 길다.
 *
 * 반응은 화면에만 있다. 서버로 아무것도 안 보내고, 돌고 있는 작업에도
 * 영향을 주지 않는다. 반응이 끝나면 원래 단계 그림으로 돌아간다. */


/* 루와 노는 자리의 실제 동작은 web/lou-play.js 에 있다 — 기다리는 화면(index)과
   화면 구경(demo)이 같은 코드를 쓰게 하려고 뺐다. 여기서는 setupLou() 만 부른다.
   (예전에는 demo.html 이 같은 로직을 통째로 베껴 갖고 있어서 둘이 갈라졌다.) */

function setSheetButtonsBusy(busy) {
  $("#sheetApproveBtn").disabled = busy;
  $("#sheetRetryBtn").disabled = busy;
}

// 승인 화면이 뜰 때마다 현재 p1.json 값을 수정 폼에 채운다. 실패해도(아직
// run_id 가 없거나 p1.json 이 없거나) 폼을 빈 채로 두고 그냥 넘어간다 —
// 수정은 선택 사항이라 이것 때문에 승인 화면 자체를 막지 않는다.
async function loadSheetFields() {
  if (!jobId) return;
  try {
    const res = await fetch(`/api/jobs/${jobId}/sheet-fields`);
    if (!res.ok) return;
    const f = await res.json();
    $("#sheetEditName").value = f.name || "";
    $("#sheetEditAppearance").value = f.appearance_en || "";
    $("#sheetEditDetails").value = (f.design_details || []).join("\n");
  } catch (err) {
    // 조용히 무시 — 수정 폼은 선택 사항이다.
  }
}

function sheetEditFields() {
  return {
    name: $("#sheetEditName").value,
    appearance_en: $("#sheetEditAppearance").value,
    design_details: $("#sheetEditDetails").value
      .split("\n").map(s => s.trim()).filter(Boolean),
  };
}

async function sendSheetDecision(decision) {
  if (!jobId) return;
  setSheetButtonsBusy(true);
  try {
    // 고른 항목·적은 말은 approve 에도 보낸다 — "이대로 진행"을 누르면서도
    // 불만은 적는 사람이 있고, 그게 다음 판을 고칠 근거가 된다.
    const body = { decision, ...fbRead(fbStageBox("sheet")) };
    // 수정한 값은 approve 에는 의미가 없다 — 이미 채택한 그림을 텍스트만
    // 바꿔서 바꿀 수는 없으므로, 반영하려면 retry 로 다시 그려야 한다.
    if (decision === "retry") body.fields = sheetEditFields();
    const res = await fetch(`/api/jobs/${jobId}/sheet-decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "전달하지 못했습니다");
    fbClear(fbStageBox("sheet"));
    // 다음 tick() 이 새 상태를 받아 화면을 바꾼다 — 여기서 직접 안 바꾼다.
  } catch (err) {
    toast(err.message);
    setSheetButtonsBusy(false);
  }
}

function setStoryButtonsBusy(busy) {
  $("#storyApproveBtn").disabled = busy;
  $("#storyRetryBtn").disabled = busy;
}

async function sendStoryDecision(decision) {
  if (!jobId) return;
  setStoryButtonsBusy(true);
  try {
    const res = await fetch(`/api/jobs/${jobId}/story-decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, ...fbRead(fbStageBox("story")) }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "전달하지 못했습니다");
    fbClear(fbStageBox("story"));
    // 다음 tick() 이 새 상태를 받아 화면을 바꾼다 — 여기서 직접 안 바꾼다.
  } catch (err) {
    toast(err.message);
    setStoryButtonsBusy(false);
  }
}

function setBoardButtonsBusy(busy) {
  $("#boardApproveBtn").disabled = busy;
  $("#boardRetryBtn").disabled = busy;
}

async function sendBoardDecision(decision) {
  if (!jobId) return;
  setBoardButtonsBusy(true);
  try {
    const res = await fetch(`/api/jobs/${jobId}/board-decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, ...fbRead(fbStageBox("board")) }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "전달하지 못했습니다");
    fbClear(fbStageBox("board"));
    // 다음 tick() 이 새 상태를 받아 화면을 바꾼다 — 여기서 직접 안 바꾼다.
  } catch (err) {
    toast(err.message);
    setBoardButtonsBusy(false);
  }
}

/* ---- 그림 검수 확인 (전문 모드) --------------------------------------- */

function qaItems(list, render) {
  return list.map(render).join("");
}

function renderArtQa(qa) {
  const fixed = qa.fixed || [], unresolved = qa.unresolved || [];
  const checked = qa.checked || 0;

  const parts = [`장 ${checked}개를 검수했습니다.`];
  if (fixed.length) parts.push(`${fixed.length}개는 다시 그려서 고쳤습니다.`);
  if (unresolved.length) parts.push(`${unresolved.length}개는 못 고쳤습니다.`);
  if (!fixed.length && !unresolved.length) parts.push("걸린 것은 없습니다.");
  $("#artqaSummary").textContent = parts.join(" ");

  const unresolvedBox = $("#artqaUnresolvedBox");
  unresolvedBox.hidden = !unresolved.length;
  $("#artqaUnresolved").innerHTML = qaItems(unresolved, u => `
    <li>
      <b>${esc(u.scene)}장</b>
      <span class="qa-rounds">${u.rounds ? `${esc(u.rounds)}번 다시 그림` : "다시 안 그림"}</span>
      <ul class="qa-issues">
        ${(u.issues || []).map(i => `<li>${esc(i.what)}</li>`).join("")}
      </ul>
    </li>`);

  const fixedBox = $("#artqaFixedBox");
  fixedBox.hidden = !fixed.length;
  $("#artqaFixed").innerHTML = qaItems(fixed, f => `
    <li><b>${esc(f.scene)}장</b>
      <span class="qa-rounds">${esc(f.rounds)}번 다시 그려서 통과</span></li>`);
}

async function sendArtqaDecision() {
  if (!jobId) return;
  const btn = $("#artqaApproveBtn");
  btn.disabled = true;
  // 이 화면의 상자를 직접 집는다 — data-fb-stage="scene" 은 결과 화면의 장별
  // 다시 그리기 상자도 쓰므로, fbStageBox("scene") 은 엉뚱한 것을 집을 수 있다.
  const box = $(".fb-box", $("#artqaApproval"));
  try {
    const res = await fetch(`/api/jobs/${jobId}/artqa-decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fbRead(box)),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "전달하지 못했습니다");
    fbClear(box);
    // 다음 tick() 이 done 을 받아 결과 화면으로 넘긴다.
  } catch (err) {
    toast(err.message);
    btn.disabled = false;
  }
}

function renderFailure(s) {
  $("#progEyebrow").textContent = s.status === "cancelled" ? "중단됨" : "실패";
  $("#progTitle").textContent = s.status === "cancelled"
    ? "중단했습니다" : "여기서 멈췄습니다";
  $("#progSub").textContent = s.error || "알 수 없는 오류";
  $("#clockLabel").textContent = "걸린 시간";
  $("#cancelBtn").textContent = "처음으로";
  $("#cancelBtn").onclick = forget;      // 실패한 작업을 계속 붙들고 있지 않는다
}

/* ------------------------------------------------------------------ 결과 */

/* 결과 화면이 그림과 내려받기를 **어디서** 가져오는가.
 *
 * 같은 완성본을 두 길로 연다: 방금 만든 것은 작업(job)으로, "내 웹툰" 목록에서
 * 고른 것은 run_id 로. 그림과 대사는 같고 주소만 다르므로, 주소를 만드는 함수만
 * 갈아 끼우고 그리는 코드는 하나로 둔다. */
let resultSrc = null;

function jobSource(id) {
  return {
    page: (no, w = 1080) => `/api/jobs/${id}/page/${no}?w=${w}`,
    download: `/api/jobs/${id}/episode.png`,
  };
}
function runSource(runId, ep) {
  const q = `ep=${ep}`;
  return {
    page: (no, w = 1080) =>
      `/api/runs/${encodeURIComponent(runId)}/page/${no}?w=${w}&${q}`,
    download: `/api/runs/${encodeURIComponent(runId)}/episode.png?${q}`,
  };
}

/* 결과 화면 **목업** — /demo/result.
 *
 * 실제로 만들지 않고 완성본 화면을 그대로 본다. 화면 코드는 진짜와 같은
 * paintResult() 하나만 쓰고, 데이터만 web/samples/mock.json 에서 온다 —
 * demo.html 처럼 화면을 통째로 베끼면 본편이 바뀔 때마다 갈라진다.
 *
 * "내려받기"는 진짜 파일을 준다. 샘플 장을 한 편으로 이어 붙인 뒤 실제
 * 내려받기와 **같은 길**(watermark.for_download)로 나가므로, LORE 표시가
 * 붙은 모습이 목업에서 그대로 보인다. */
async function showMockResult() {
  const r = await (await fetch("/static/samples/mock.json")).json();
  const scenes = r.scenes || [];
  resultSrc = {
    page: no => (scenes.find(s => s.no === no) || {}).image || "",
    download: "/api/demo/episode.png",
  };
  const cuts = scenes.reduce((n, s) => n + (s.cuts || []).length, 0);
  paintResult({
    ...r,
    run_id: "",                       // 목업이라 서버에 없는 작품이다 —
    pages: scenes,                    // 공유·다시 그리기·이어 만들기는 저절로 감춰진다
    page_count: scenes.length,
    cut_count: cuts,
    seconds: 0,
  });
  // 목업이라는 것을 화면이 스스로 말해야 한다 — 안 그러면 진짜 결과로 읽힌다
  const sub = $("#resSub");
  if (sub) sub.textContent += " · 화면 구경용 목업입니다";
  // 담을 작품이 없어도 단추는 보여 준다 — 목업의 일은 흐름을 보여주는 것이고,
  // 눌러 보면 로그인 전 사용자가 실제로 만나는 그 가입 창이 그대로 열린다.
  // 목업은 **내 작품을 보고 있을 때의 화면**을 보여주는 자리다. 단추가 몇 개인지가
  // 곧 보여줄 내용이라, 남의 작품처럼 감춰 버리면 배치가 달라진다.
  ["#downloadBtn", "#editorLink", "#claimBtn", "#claimNote"].forEach(sel => {
    const el = $(sel); if (el) el.hidden = false;
  });
  const wrap = $("#shareBtn") && $("#shareBtn").closest(".share-wrap");
  if (wrap) wrap.hidden = false;
}

async function showResult(attempt = 0) {
  resultSrc = jobSource(jobId);
  const res = await fetch(`/api/jobs/${jobId}/result`);
  const r = await res.json();
  if (!r.pages || !r.pages.length) {
    // 작업이 done 이 된 직후라 그림 파일이 아직 다 씌어지지 않았을 수 있다.
    // 예전에는 여기서 한 번 비면 화면이 그대로 멈췄다 — 다 만들어 놓고도
    // 못 보는 상태가 되고, 새로고침 말고는 빠져나갈 길이 없었다.
    if (attempt < 4) {
      $("#progSub").textContent = "컷을 불러오는 중입니다…";
      setTimeout(() => showResult(attempt + 1), 900 * (attempt + 1));
      return;
    }
    // 그래도 비면 **막다른 길로 두지 않는다.** 다시 시도할 단추와, 이미 그려진
    // 것이 있으면 편집실로 바로 갈 길을 준다.
    const sub = $("#progSub");
    sub.innerHTML =
      "완성했지만 컷을 읽지 못했습니다. " +
      `<button type="button" class="btn btn-quiet btn-sm" id="retryResult">다시 불러오기</button>` +
      (r.run_id
        ? ` <a class="btn btn-quiet btn-sm" href="/editor?run=${encodeURIComponent(r.run_id)}">편집실에서 열기</a>`
        : "");
    document.getElementById("retryResult")?.addEventListener(
      "click", () => showResult(0));
    return;
  }
  // 여기까지 온 것은 **이 브라우저가 시킨 작업**의 결과다 (job 으로 열었다).
  // 그 사실을 남겨 둬야 나중에 목록·링크로 다시 열었을 때 내 것인 줄 안다.
  rememberMyRun(r.run_id);
  paintResult(r);
}

/* 목록에서 고른 완성본. 작업(job)을 거치지 않으므로 하네스를 직접 돌린 회차나
   이어 만들어 job 기록이 없는 회차도 똑같이 열린다 (초롱 2화가 그랬다). */
async function showRunResult(runId, ep) {
  resultSrc = runSource(runId, ep);
  let r;
  try {
    const res = await fetch(
      `/api/runs/${encodeURIComponent(runId)}/result?ep=${ep}`);
    r = await res.json();
    if (!res.ok) throw new Error(r.error || "열지 못했습니다");
  } catch (err) {
    return toast(err.message);
  }
  if (!r.pages || !r.pages.length) {
    return toast(`${ep}화는 아직 그려진 장이 없습니다.`);
  }
  // 이 회차를 방금 만든 작업이 아니므로, 결과 화면에 남아 있던 job 을 끊는다 —
  // 안 끊으면 "새로 만들기" 나 새로고침이 엉뚱한 작업으로 돌아간다.
  jobId = null;
  sessionStorage.removeItem("lore_job");
  paintResult(r);
  history.replaceState(null, "",
    LORE.at(`/works?run=${encodeURIComponent(runId)}&ep=${ep}`));
}

/* 결과 화면 부제가 쓸 값. 스크롤을 따라 "몇 컷째" 가 바뀌므로 paintResult 가
   한 번 적고 끝내지 못한다 — 여기 담아 두고 스크롤할 때마다 다시 그린다. */
let resultPos = null;

/* 지금 화면 위쪽에 걸쳐 있는 장 → 그 장의 첫 컷 번호.
   장 하나에 perSheet 컷이 함께 구워지므로(pipeline 의 CUTS_PER_SHEET) n번째
   장의 첫 컷은 (n-1)*perSheet+1 이다. 어림이 아니라 굽는 규칙 그대로다. */
function currentCutNo() {
  const pages = $$("#reader .page");
  if (!pages.length || !resultPos?.total) return 0;
  let cur = pages[0];
  for (const p of pages) {
    // 상단바(59px) 아래로 내려온 장 중 마지막 것이 지금 읽는 장이다
    if (p.getBoundingClientRect().top <= 140) cur = p; else break;
  }
  const no = Number(cur.dataset.scene) || 1;
  return Math.min(resultPos.total, (no - 1) * resultPos.perSheet + 1);
}

function paintResultPos() {
  const el = $("#resSub");
  if (!el || !resultPos) return;
  const { prefix, total, tail } = resultPos;
  const at = currentCutNo();
  const body = !total ? ""
    : at ? ` · ${total}컷 중 ${at}컷째`
         : ` · 총 ${total}컷`;
  el.textContent = prefix + body + tail;
}

function paintResult(r) {
  $("#resGenre").textContent  = [r.genre, r.style_label].filter(Boolean).join(" · ");
  $("#resTitle").textContent  = r.title;
  $("#resLogline").textContent = r.logline || r.intro || "";
  const short = r.preview && r.planned_pages > r.page_count
    ? ` · 미리보기 (콘티 ${r.planned_pages}장 중 앞 ${r.page_count}장만 그렸습니다)` : "";
  // 얼마나 걸렸는지는 결과에도 남긴다 — 다음에 또 만들 때 기다릴 시간을
  // 가늠하는 유일한 근거다. 단계별 내역은 title 로 붙여 둔다.
  const took = r.seconds ? ` · ${mmss(r.seconds)} 걸림` : "";
  const epNo = r.episode || 1;
  // 예전에는 "3장 / 4컷 · 한 장에 3컷" 이라고 적었다. 장·컷은 그림을 굽는 쪽의
  // 단위(한 장에 몇 컷을 함께 그리는가)이지 읽는 사람의 단위가 아니다 — 보는
  // 사람은 자기가 지금 어디쯤 읽고 있는지가 궁금하다. 그래서 굽는 단위는 빼고
  // 읽는 자리(resultPos)로 바꾼다.
  resultPos = {
    prefix: `${r.character ? r.character + " · " : ""}${epNo}화`,
    total: Number(r.cut_count) || 0,
    perSheet: Number(r.cuts_per_sheet) || 1,
    tail: `${short}${took}`,
  };
  paintResultPos();
  $("#resSub").title = (r.stage_times || [])
    .map(s => `${s.title} ${mmss(s.seconds)}`).join("  ·  ");
  $("#downloadBtn").href = resultSrc.download;

  // 장 사이 여백과 지면 폭은 **파일과 같은 눈금**으로 그린다.
  //
  // 전에는 여기서 장을 딱 붙여 그렸다. 그런데 내려받은 episode.png 에는
  // 콘티의 gap_after 대로 여백이 들어가 있어서(episode.stitch), 화면에서 보고
  // 만든 것과 손에 쥔 파일이 다른 작품이 됐다 — 세로 스크롤에서 여백은
  // 장식이 아니라 호흡이라 그만큼 크게 달라진다.
  //
  // 서버가 장마다 gap(지면 폭의 몇 배)·width(지면 폭의 몇 배)를 실어 준다.
  // 그 값이 없는 옛 응답은 예전처럼 붙여 그린다.
  resultRunId = r.run_id || "";
  resultEpisode = epNo;
  resultLayoutMode = r.layout_mode || "fast";
  // 공유는 run_id 로 여는 주소라, 그것이 없으면 보낼 링크가 없다. 눌러도
  // 아무 일이 안 일어나는 단추를 두느니 감춘다.
  $("#shareBtn").hidden = !resultRunId;
  $("#titleEditBtn").hidden = !resultRunId;
  toggleShareMenu(false);
  openTitleEdit(false);
  wireMemory(resultRunId);
  $("#reader").innerHTML = r.pages.map((pg, i) => {
    // 마지막 장 뒤의 여백은 안 넣는다 — 그 아래는 이미 화면 끝이다.
    const gap = i === r.pages.length - 1 ? 0 : +pg.gap || 0;
    const w = +pg.width || 1;
    const style = [gap ? `margin-bottom:${(gap * 100).toFixed(2)}%` : "",
                   w !== 1 ? `width:${(w * 100).toFixed(2)}%;margin-left:auto;` +
                             "margin-right:auto" : ""].filter(Boolean).join(";");
    return `
    <div class="page" data-scene="${pg.no}"${style ? ` style="${style}"` : ""}>
      <img class="cut-img" src="${resultSrc.page(pg.no)}"
           alt="${pg.no}번째 장" loading="lazy">
      ${resultRunId ? pageTools(pg.no) : ""}
    </div>`;
  }).join("");
  if (resultRunId) {
    wireRegen();
    r.pages.forEach(pg => paintVersions(pg.no));
    paintArtQA();
  }

  paintEpisodeTabs(r);
  // 편집실 링크도 지금 보고 있는 작품·회차로 맞춘다. 예전에는 늘 목업으로
  // 갔다 — 다 만들어 놓고 "편집실에서 열기"를 누르면 남의 샘플이 떴다.
  $("#editorLink").href = resultRunId
    ? `/editor?run=${encodeURIComponent(resultRunId)}&ep=${epNo}` : "/editor";

  // 이어 만들기 단추 — 그린 작품이 있어야 뜻이 있고, **내 작품이어야** 한다.
  // 남의 연재를 내가 이어 그릴 자리가 아니다(크레딧도 내 것이 나간다).
  nextEpCtx = (resultRunId && isMyRun(resultRunId))
    ? { runId: resultRunId, next: r.next_episode || (epNo + 1),
        character: r.character || "", title: r.title || "" }
    : null;
  $("#nextEpBtn").hidden = !nextEpCtx;
  if (nextEpCtx) $("#nextEpBtn").textContent = `${nextEpCtx.next}화 만들기`;

  // 이어 그리기 — 콘티에 아직 안 그린 컷이 남아 있을 때만 뜬다.
  // 한 화를 통째로 굽지 않고 앞부분부터 보여주는 것이 지금의 방식이라,
  // 대부분의 결과 화면에는 이 단추가 있다.
  // 이어 그리기도 같다 — 남의 작품에 컷을 더 그려 붙일 수는 없다.
  moreCtx = (resultRunId && r.more_cuts && isMyRun(resultRunId))
    ? { runId: resultRunId, episode: epNo,
        drawn: r.drawn_units || 0, total: r.planned_cuts || 0 }
    : null;
  $("#moreCutsBtn").hidden = !moreCtx;
  if (moreCtx) {
    const shown = moreCtx.drawn * Number(r.cuts_per_sheet || 3);
    // 값은 실제 콘티가 정한다 — 남은 장면(이미지) 수 × 장당 값. 서버(/continue)와
    // 같은 셈이라 눌렀을 때 다른 값이 빠지지 않는다. 이제 한 번 누르면 나머지
    // 전부를 그린다.
    // 추가 결제가 없다는 것을 단추가 직접 말한다 — 결제가 또 나올까 봐
    // 안 누르는 것이 이 자리의 가장 큰 이탈이다.
    $("#moreCutsBtn").textContent =
      `1화 전체 보기 (남은 ${moreCtx.total - shown}컷 · 추가 결제 없음)`;
  }

  paintClaimBanner();
  view("result");
  window.scrollTo(0, 0);
}

/* ---- 그림 QA — 검수가 잡았지만 못 고친 것 ------------------------------
 *
 * 하네스가 그리면서 명백한 실패(작화 사고 · 서술과 다른 인원/대상/배경)를
 * 검수하고 한도 안에서 다시 그린다. 그래도 남은 것이 여기로 온다 — 검수는
 * "틀렸다"까지만 알고 "어떻게 고칠지"는 사용자가 아니까, 표시하고 다시
 * 그리기(피드백 창)로 잇는 것이 이 화면의 몫이다.
 * QA 를 안 켠 예전 run 은 빈 응답이라 아무것도 안 뜬다. */
async function paintArtQA() {
  let scenes;
  try {
    scenes = (await (await fetch(
      `/api/runs/${encodeURIComponent(resultRunId)}/art-qa?ep=${resultEpisode}`
    )).json()).scenes || {};
  } catch { return; }                      // 못 읽으면 표시만 빠진다
  for (const [no, rec] of Object.entries(scenes)) {
    if (!rec.issues || !rec.issues.length) continue;
    const page = $(`#reader .page[data-scene="${no}"]`);
    if (!page || $(".qa-note", page)) continue;
    const note = document.createElement("div");
    note.className = "qa-note";
    note.innerHTML =
      `<b>검수에서 잡았지만 못 고친 것</b>` +
      (rec.rounds ? `<small> — ${rec.rounds}번 다시 그려 봤습니다</small>` : "") +
      `<ul>${rec.issues.map(i => `<li>${esc(i.what)}</li>`).join("")}</ul>` +
      `<button type="button" class="btn btn-quiet btn-sm js-qa-regen">직접 고치기 — 다시 그리기</button>`;
    // 도구 줄 바로 뒤에 끼운다 — 그림 밑, 판 목록 위.
    const tools = $(".page-tools", page);
    if (tools) tools.insertAdjacentElement("afterend", note);
    else page.append(note);
    $(".js-qa-regen", note).addEventListener("click", () => {
      const box = $(".regen-box", page);
      if (!box) return;
      box.hidden = false;
      // 검수가 찾은 말을 피드백 칸에 미리 실어 준다 — 빈손으로 다시 그리면
      // 같은 분포에서 랜덤 뽑기라, 문제를 명시하는 쪽이 방향이 생긴다.
      const text = $(".js-regen-note", box);
      if (text && !text.value.trim()) {
        text.value = rec.issues.map(i => i.what).join(" / ").slice(0, 480);
      }
      box.scrollIntoView({ behavior: "smooth", block: "center" });
      text?.focus();
    });
  }
}

/* 회차 탭. 한 편밖에 없으면 안 그린다 — 고를 것이 없는 자리에 고르개를 두면
   "여기 뭔가 더 있나" 하고 누르게 된다. */
function paintEpisodeTabs(r) {
  const host = $("#resEpisodes");
  const eps = r.episodes || [];
  const cur = r.episode || 1;
  if (!r.run_id || eps.length < 2) { host.hidden = true; host.innerHTML = ""; return; }
  host.hidden = false;
  host.innerHTML = eps.map(n =>
    `<button type="button" class="ep-tab" data-ep="${n}"` +
    `${n === cur ? ' aria-current="true"' : ""}>${n}화</button>`).join("");
  $$(".ep-tab", host).forEach(b => b.addEventListener("click", () => {
    if (b.getAttribute("aria-current") === "true") return;
    showRunResult(r.run_id, Number(b.dataset.ep));
  }));
}

/* ------------------------------------------------- 장 다시 그리기 (#59)
 *
 * 그림은 컷이 아니라 **장 단위**로 굽는다 — 한 장에 3컷이 함께 그려지므로
 * "컷 하나만" 다시 뽑는 길은 없다. 다시 그리는 최소 단위가 장이다.
 *
 * 크레딧 차감은 없다 (#16 이 백로그). 실제 API 비용은 나간다. */

let resultRunId = "";
// 지금 결과 화면이 몇 화인가. 다시 그리기·되돌리기·판 목록이 전부 이 값을
// 보내야 한다 — 안 보내면 서버가 1화로 알아듣고 2화 화면을 보면서 **1화
// 그림을 덮어쓴다** (실제 코드 감사에서 발견).
let resultEpisode = 1;
let resultLayoutMode = "fast";   // 이어 그리기 값 계산용

/* ---- 공유 --------------------------------------------------------------- *
 *
 * 보내는 것은 **링크 하나**다. 그림 파일이 아니라 링크를 보내는 이유:
 * 한 편이 20MB 라 메신저가 받아 주지 않거나 화질을 깎고, 무엇보다 받은 사람이
 * 회차를 넘겨 가며 읽을 수가 없다. 링크로 열면 완성본 화면이 그대로 열린다.
 * 파일이 필요한 사람에게는 옆에 "PNG 내려받기" 가 이미 있다.
 *
 * 미리보기(제목·그림)는 서버가 만든다 — serve.py 의 og_tags 참고. 크롤러는
 * 자바스크립트를 안 돌려서 여기서 무엇을 그리든 카드에는 안 실린다.
 *
 * 지금은 링크를 아는 사람이 곧 볼 수 있는 사람이다. 공개 범위·만료는 계정이
 * 생긴 뒤의 일이라(#66) 화면에서도 그렇게 말한다. */

function shareUrl() {
  if (!resultRunId) return "";
  // 배포된 주소가 정해져 있으면 그것을 쓴다. 지금 보고 있는 주소를 그대로
  // 보내면 개발 중에는 127.0.0.1 이고 사설망에서는 192.168.x 라, 받은 사람이
  // 아무것도 못 연다. 서버가 LORE_PUBLIC_URL 로 알려 준다(#96).
  const base = (shareConfig.public_url || "").replace(/\/+$/, "") || location.origin;
  return `${base}/works?run=${encodeURIComponent(resultRunId)}&ep=${resultEpisode}`;
}

function shareTitle() {
  const t = ($("#resTitle")?.textContent || "").trim();
  return t ? `${t} — LORE` : "LORE 로 만든 웹툰";
}

/* 폰에는 공유 시트가 있고 PC 에는 없다. 없는 곳에서는 링크를 복사하는 것이
   할 수 있는 전부라, 단추 글자도 그때그때 맞춘다 — "공유" 라고 써 놓고
   복사만 되면 눌러 본 사람이 무슨 일이 일어났는지 모른다. */
function canOpenShareSheet() {
  return typeof navigator.share === "function";
}

async function copyLink(url) {
  try {
    await navigator.clipboard.writeText(url);
    return true;
  } catch {
    // 옛 브라우저이거나 https 가 아니면 clipboard 가 막힌다. 화면 밖에 잠깐
    // 만들어 두고 실행 명령으로 복사한다 — 이것마저 안 되면 false 다.
    try {
      const ta = document.createElement("textarea");
      ta.value = url;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;left:-9999px;top:0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch { return false; }
  }
}

async function copyAndTell() {
  toast(await copyLink(shareUrl())
    ? "링크를 복사했습니다 — 붙여넣기 하면 미리보기가 뜹니다"
    : "복사하지 못했습니다. 주소창의 주소를 그대로 보내 주세요.");
}

/* 공유 시트(폰)로 넘긴다. 여기에는 카톡·인스타가 이미 들어 있어서, 폰에서는
   이것 하나가 SNS 단추 여럿보다 낫다. */
async function shareToSheet() {
  try {
    await navigator.share({ title: shareTitle(), text: shareText(), url: shareUrl() });
  } catch (err) {
    if (err && err.name === "AbortError") return;   // 사용자가 닫은 것뿐이다
    await copyAndTell();
  }
}

/* ---- 어디로 보낼 수 있는가 ---------------------------------------------- *
 *
 * 셋의 사정이 다 다르다.
 *   트위터·페이스북·라인 — 주소 하나로 창을 연다. 등록도 열쇠도 필요 없다.
 *   카카오톡 — 공식 SDK 를 붙여야 하고, JavaScript 키와 **등록된 도메인**이
 *              있어야 한다. 키가 없으면 아예 안 그린다(서버의 kakao_js_key).
 *   인스타그램 — **웹에서 글을 올리는 길이 없다.** 공유 주소가 아예 없고,
 *              피드에는 링크도 안 걸린다. 인스타에 올리려면 그림 파일이
 *              가야 해서, 폰이면 공유 시트로 넘기고 PC 면 내려받기로 보낸다.
 *              단추를 만들어 두고 "안 됩니다" 하는 것보다 그게 정직하다. */

function shareText() {
  const title = ($("#resTitle")?.textContent || "").trim();
  const log = ($("#resLogline")?.textContent || "").trim();
  // 트위터는 280자다. 링크와 해시태그 자리를 빼고 로그라인을 줄인다.
  const short = log.length > 90 ? log.slice(0, 89) + "…" : log;
  return [title, short].filter(Boolean).join(" — ");
}

const SHARE_TARGETS = [
  {
    id: "x", label: "X (트위터)",
    href: () => "https://twitter.com/intent/tweet"
      + `?text=${encodeURIComponent(shareText() + " #LORE")}`
      + `&url=${encodeURIComponent(shareUrl())}`,
  },
  {
    id: "facebook", label: "페이스북",
    // 페이스북은 본문을 안 받는다 — 링크만 주면 og 태그로 카드를 만든다.
    href: () => "https://www.facebook.com/sharer/sharer.php"
      + `?u=${encodeURIComponent(shareUrl())}`,
  },
  {
    id: "line", label: "라인",
    href: () => "https://social-plugins.line.me/lineit/share"
      + `?url=${encodeURIComponent(shareUrl())}`
      + `&text=${encodeURIComponent(shareText())}`,
  },
];

function openShareWindow(url) {
  // 새 창으로 연다. 같은 탭에서 열면 만들던 것을 두고 나가게 된다.
  window.open(url, "_blank", "noopener,noreferrer,width=600,height=560");
}

function buildShareMenu() {
  const host = $("#shareMenu");
  if (!host) return;
  const rows = [];
  for (const t of SHARE_TARGETS) {
    rows.push(`<button type="button" class="share-item" data-share="${t.id}">${t.label}</button>`);
  }
  if (shareConfig.kakao_js_key) {
    rows.push(`<button type="button" class="share-item" data-share="kakao">카카오톡</button>`);
  }
  if (canOpenShareSheet()) {
    rows.push(`<button type="button" class="share-item" data-share="sheet">다른 앱으로…</button>`);
  }
  rows.push(`<button type="button" class="share-item" data-share="copy">링크 복사</button>`);
  // 인스타는 링크로 못 올린다 — 그림을 받아서 올리라고 말해 준다.
  rows.push(`<a class="share-item" id="shareInstaHint" download>인스타그램 — 그림 내려받기</a>`);
  host.innerHTML = rows.join("");
  const a = $("#shareInstaHint");
  if (a) a.href = resultSrc ? resultSrc.download : "#";
}

function toggleShareMenu(open) {
  const host = $("#shareMenu"), btn = $("#shareBtn");
  if (!host || !btn) return;
  const show = open === undefined ? host.hidden : open;
  if (show) buildShareMenu();
  host.hidden = !show;
  btn.setAttribute("aria-expanded", show ? "true" : "false");
}

async function onShareMenuClick(e) {
  const el = e.target.closest("[data-share]");
  if (!el) return;
  const kind = el.dataset.share;
  toggleShareMenu(false);
  if (kind === "copy") return copyAndTell();
  if (kind === "sheet") return shareToSheet();
  if (kind === "kakao") return shareToKakao();
  const target = SHARE_TARGETS.find(t => t.id === kind);
  if (target) openShareWindow(target.href());
}

/* 카카오는 키가 있을 때만 부른다 — buildShareMenu 가 그때만 단추를 그린다.
   SDK 는 처음 누를 때 받아 온다(안 쓰는 사람에게 받게 하지 않는다). */
let kakaoReady = null;
function loadKakao() {
  if (kakaoReady) return kakaoReady;
  kakaoReady = new Promise((res, rej) => {
    const s = document.createElement("script");
    // integrity 는 안 건다 — 해시를 손으로 적어 두면 카카오가 판을 올릴 때마다
    // 조용히 안 뜬다. 붙이려면 카카오 문서의 그 판 해시를 그대로 가져와야 한다.
    s.src = "https://t1.kakaocdn.net/kakao_js_sdk/2.7.2/kakao.min.js";
    s.crossOrigin = "anonymous";
    s.onload = () => res(window.Kakao);
    s.onerror = () => rej(new Error("카카오 SDK 를 받지 못했습니다"));
    document.head.appendChild(s);
  });
  return kakaoReady;
}

async function shareToKakao() {
  try {
    const Kakao = await loadKakao();
    if (!Kakao.isInitialized()) Kakao.init(shareConfig.kakao_js_key);
    Kakao.Share.sendDefault({
      objectType: "feed",
      content: {
        title: ($("#resTitle")?.textContent || "").trim() || "LORE 웹툰",
        description: ($("#resLogline")?.textContent || "").trim().slice(0, 100),
        imageUrl: `${location.origin}${shareImagePath()}`,
        link: { mobileWebUrl: shareUrl(), webUrl: shareUrl() },
      },
      buttons: [{ title: "웹툰 보기",
                  link: { mobileWebUrl: shareUrl(), webUrl: shareUrl() } }],
    });
  } catch (err) {
    // 도메인을 카카오에 등록하지 않으면 여기서 걸린다 — 가장 흔한 실패다.
    toast("카카오톡 공유를 열지 못했습니다. 링크 복사를 써 주세요.");
  }
}

/* 카톡 카드에 걸 그림. og:image 와 같은 것을 쓴다. */
function shareImagePath() {
  return resultSrc ? resultSrc.page(1, 1080) : "";
}

let shareConfig = {};

/* ---- 제목 고치기 --------------------------------------------------------- *
 *
 * 모델이 지은 이름이 늘 맞지는 않고, 공유가 붙은 뒤로는 그 이름이 카톡·트위터
 * 카드에 실려 남에게 먼저 보인다. 여기서 고친 것은 작품 폴더에 남아서
 * (titles.json) 목록·편집실·공유 미리보기·내려받는 파일 이름까지 따라온다.
 * 비우고 저장하면 모델이 지은 이름으로 되돌아간다. */

function openTitleEdit(open) {
  const box = $("#titleEdit"), row = $("#titleEditBtn");
  if (!box) return;
  box.hidden = !open;
  if (row) row.hidden = open;
  if (open) {
    const input = $("#titleInput");
    input.value = ($("#resTitle").textContent || "").trim();
    input.focus();
    input.select();
  }
}

async function saveTitle() {
  if (!resultRunId) return;
  const btn = $("#titleSaveBtn");
  btn.disabled = true;
  try {
    const res = await fetch(
      `/api/runs/${encodeURIComponent(resultRunId)}/title`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ episode: resultEpisode,
                               title: $("#titleInput").value }),
      });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "저장하지 못했습니다");
    // 서버가 돌려준 것이 **앞으로 보일 이름**이다 (비웠으면 원래 제목).
    $("#resTitle").textContent = data.title;
    openTitleEdit(false);
    toast("제목을 바꿨습니다");
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false;
  }
}

function setupTitleEdit() {
  const edit = $("#titleEditBtn");
  if (!edit) return;
  edit.addEventListener("click", () => openTitleEdit(true));
  $("#titleCancelBtn").addEventListener("click", () => openTitleEdit(false));
  $("#titleSaveBtn").addEventListener("click", saveTitle);
  $("#titleInput").addEventListener("keydown", e => {
    if (e.key === "Enter") { e.preventDefault(); saveTitle(); }
    if (e.key === "Escape") openTitleEdit(false);
  });
}

function setupShare() {
  const btn = $("#shareBtn");
  if (!btn) return;
  btn.addEventListener("click", () => toggleShareMenu());
  $("#shareMenu")?.addEventListener("click", onShareMenuClick);
  // 바깥을 누르면 닫는다.
  document.addEventListener("click", e => {
    if (!e.target.closest("#shareMenu") && !e.target.closest("#shareBtn")) {
      toggleShareMenu(false);
    }
  });
  getConfig().then(c => { shareConfig = c || {}; }).catch(() => { shareConfig = {}; });
}

function pageTools(no) {
  // 남의 작품에는 고치는 자리를 아예 안 그린다. 다시 그리기는 그림 모델을
  // 실제로 부르는 일이라(남의 작품을 내 손으로 바꿔 버린다), 감추는 정도가
  // 아니라 만들지 않는다.
  if (!isMyRun(resultRunId)) return "";
  return `
    <div class="page-tools">
      <button type="button" class="btn btn-quiet btn-sm js-regen-open">이 장 다시 그리기</button>
    </div>
    <div class="regen-box fb-box" data-fb-stage="scene" hidden>
      <p class="fb-lead">무엇이 마음에 안 드나요?
        <small>체크하면 루가 다시 그릴 때 훨씬 쉬워요! 비워두면 그냥 한 번 더 그립니다</small></p>
      <div class="fb-tags"></div>
      <label class="field fb-etc-note">
        <span>기타</span>
        <textarea rows="2" class="js-regen-note fb-text" maxlength="500"
          placeholder="예: 표정을 더 밝게 / 배경을 밤으로 / 인물을 왼쪽에"></textarea>
      </label>
      <label class="check-line">
        <input type="checkbox" class="js-regen-textless">
        <span>말풍선 없이 그림만 다시 그리기 <small>말풍선까지 안 그립니다 — 대사는 나중에 편집실에서 얹으세요</small></span>
      </label>
      <div class="regen-actions">
        <button type="button" class="btn btn-primary btn-sm js-regen-go">다시 그리기</button>
        <button type="button" class="btn btn-quiet btn-sm js-regen-cancel">닫기</button>
        <span class="regen-note js-regen-status"></span>
      </div>
    </div>
    <div class="page-versions" data-versions="${no}"></div>`;
}

function wireRegen() {
  $$("#reader .page").forEach(page => {
    const no  = Number(page.dataset.scene);
    const box = $(".regen-box", page);
    // 남의 작품에는 고치는 자리를 아예 안 그린다(pageTools 참고). 그래서 상자가
    // 없을 수 있다 — 예전에는 늘 있다고 믿고 바로 파고들다가, 남의 작품을 열면
    // 여기서 죽어 화면 전환 자체가 멈췄다(둘러보기에서 눌러도 안 넘어갔다).
    if (!box) return;
    // 장마다 상자가 하나씩이라 항목도 장마다 새로 그린다.
    fbChips("scene", box);
    $(".js-regen-open", page).addEventListener("click", () => {
      box.hidden = !box.hidden;
      if (!box.hidden) $(".js-regen-note", box).focus();
    });
    $(".js-regen-cancel", box).addEventListener("click", () => { box.hidden = true; });
    $(".js-regen-go", box).addEventListener("click", () => runRegen(no, box, page));
  });
}

async function runRegen(no, box, page) {
  const { tags, feedback } = fbRead(box);
  const textless = $(".js-regen-textless", box).checked;
  const status = $(".js-regen-status", page);
  const go     = $(".js-regen-go", page);
  go.disabled = true;
  status.textContent = "시작하는 중…";
  let job;
  try {
    const res = await fetch(
      `/api/runs/${encodeURIComponent(resultRunId)}/scenes/${no}/regen`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ feedback, textless, tags, episode: resultEpisode }) });
    job = await res.json();
    if (!res.ok) throw new Error(job.error || "시작하지 못했습니다");
    fbClear(box);
  } catch (err) {
    go.disabled = false;
    status.textContent = "";
    return toast(err.message);
  }

  // 폴링. 한 장 굽는 데 1~2분이라 2초면 충분하다.
  while (true) {
    await new Promise(r => setTimeout(r, 2000));
    let s;
    try { s = await (await fetch(`/api/regens/${job.id}`)).json(); }
    catch { continue; }                       // 잠깐 끊겨도 다음 번에 이어진다
    status.textContent = s.note || s.status;
    if (s.status === "done") {
      bustImage(page, no);
      paintVersions(no, s.versions);
      status.textContent = "새로 그렸습니다";
      toast(`${no}번째 장을 다시 그렸습니다`);
      break;
    }
    if (s.status === "error" || s.status === "cancelled") {
      // 실패해도 원래 그림은 서버가 되돌려 놓는다. 화면도 그대로 두면 된다.
      status.textContent = s.note || s.error || "실패했습니다";
      toast(s.error || "다시 그리지 못했습니다 — 원래 그림은 그대로입니다");
      break;
    }
  }
  go.disabled = false;
}

// 장마다 지금 그림을 마지막으로 새로 그린 시각. 판 목록의 "지금" 썸네일도
// 같은 값으로 캐시를 깨야 나란히 놓았을 때 옛 그림이 안 남는다.
const verBust = {};

/* 브라우저가 같은 주소를 캐시하므로, 새로 그려도 주소가 같으면 옛 그림이 뜬다. */
function bustImage(page, no) {
  verBust[no] = Date.now();
  const img = $(".cut-img", page);
  img.src = `${resultSrc.page(no)}&t=${verBust[no]}`;
}

/* 판 목록 — 고르는 자리가 아니라 **둘러보는** 자리다. 지금 그림과 지난 판을
 * 나란히 작게 늘어놓고, 아무 때나 눌러서 그때그때 바꿔 볼 수 있게 한다.
 * "새로 그린 걸 채택할지 고르세요" 모달을 만들지 않은 이유이기도 하다 —
 * 채택은 한 번뿐인 결정이 아니라, 나중에 다시 봐도 계속 바뀔 수 있는 것이다. */
async function paintVersions(no, versions) {
  const slot = $(`[data-versions="${no}"]`);
  if (!slot) return;
  if (!versions) {
    try {
      versions = (await (await fetch(
        `/api/runs/${encodeURIComponent(resultRunId)}/scenes/${no}/versions?ep=${resultEpisode}`)).json()).versions;
    } catch { return; }
  }
  if (!versions || !versions.length) { slot.innerHTML = ""; return; }
  const cur = `
    <span class="ver-thumb is-current" title="지금 걸린 그림">
      <img src="${resultSrc.page(no, 160)}&t=${verBust[no] || 0}" alt="지금 그림" loading="lazy">
      <span class="ver-label">지금</span>
    </span>`;
  const past = versions.map(v => `
    <button type="button" class="ver-thumb js-revert" data-v="${v.version}"
            title="이 판으로 바꾸기">
      <img src="/api/runs/${encodeURIComponent(resultRunId)}/scenes/${no}/versions/${v.version}?w=160&ep=${resultEpisode}"
           alt="v${v.version}" loading="lazy">
      <span class="ver-label">v${v.version}</span>
    </button>`).join("");
  // 지난 판으로 되돌리는 것도 남의 작품에서는 할 일이 아니다 — 판 자체를
  // 안 보여준다(무엇이 있었는지도 남의 작업 과정이다).
  if (!isMyRun(resultRunId)) { slot.innerHTML = ""; return; }
  slot.innerHTML = `
    <span class="ver-strip-label">지난 판 — 눌러서 바꿔 보기</span>
    <div class="ver-strip">${cur}${past}</div>`;
  $$(".js-revert", slot).forEach(btn => btn.addEventListener("click", async () => {
    btn.disabled = true;
    try {
      const res = await fetch(
        `/api/runs/${encodeURIComponent(resultRunId)}/scenes/${no}/revert`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ version: Number(btn.dataset.v), episode: resultEpisode }) });
      const out = await res.json();
      if (!res.ok) throw new Error(out.error || "되돌리지 못했습니다");
      bustImage($(`#reader .page[data-scene="${no}"]`), no);
      paintVersions(no, out.versions);
      toast(`${no}번째 장을 v${btn.dataset.v} 로 바꿨습니다`);
    } catch (err) {
      toast(err.message);
    }
    btn.disabled = false;
  }));
}



/* 이미 끝난 작업을 결과 화면으로 바로 연다 (진행 화면을 거치지 않는다). */
async function openExisting(id) {
  try {
    if (!id) {
      const res = await fetch("/api/latest");
      const d = await res.json();          // 본문은 한 번만 읽을 수 있다
      if (!res.ok) throw new Error(d.error || "없습니다");
      id = d.id;
    }
    const state = await (await fetch(`/api/jobs/${id}`)).json();
    if (state.error) throw new Error(state.error);
    jobId = id;
    sessionStorage.setItem("lore_job", jobId);
    if (state.status === "done") { await showResult(); return; }
    startPolling();                       // 아직 도는 중이면 진행 화면으로
  } catch (err) {
    toast(`${err.message} — 먼저 한 편 만들어 주세요.`);
    view("landing"); pickHero();
    window.scrollTo(0, 0);
  }
}

/* 이어 그리기 — 같은 화의 다음 3컷. 회차가 안 늘어나므로 다음 화 만들기와
   다른 자리다. 시작하면 진행 화면으로 넘어가고, 끝나면 결과가 다시 그려진다. */
async function continueCuts() {
  if (!moreCtx) return;
  const btn = $("#moreCutsBtn");
  btn.disabled = true;
  const label = btn.textContent;
  btn.textContent = "루가 이어 그리는 중…";
  try {
    const res = await fetch(
      `/api/runs/${encodeURIComponent(moreCtx.runId)}/continue`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ episode: moreCtx.episode, uid: UID }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "이어 그리지 못했습니다");
    if (data.credit_balance != null) { creditBalance = data.credit_balance; paintCreditPill(); }
    jobId = data.id;
    sessionStorage.setItem("lore_job", jobId);
    shownCuts = new Set();
    startPolling();
  } catch (err) {
    toast(err.message);
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}

/* ------------------------------------------------- 다음 화 이어서 만들기 (#72)
 *
 * 1화용 진행 화면(#progress)을 쓰지 않는다. 이어 만들기는 도는 단계가 셋뿐이고
 * (콘티 · 그림 · 잇기), 이야기와 캐릭터 시트는 1화 것을 그대로 쓴다. 사람이
 * 궁금해하는 것도 다르다 — "인물이 그대로 따라오는가", "몇 화가 나오는가".
 *
 * 회차 번호는 **서버가 정한다.** 화면이 보낸 번호를 믿으면 창을 두 개 띄워
 * 놓고 눌렀을 때 같은 번호를 두 번 만들려 든다. */

let nextEpCtx = null;
let moreCtx = null;      // { runId, next, character, title }
let nextEpJob = null;      // 도는 중인 작업 id
let nextEpPoll = null;

function openNextEp() {
  if (!nextEpCtx) return;
  $("#nextEpWork").textContent = [nextEpCtx.character, nextEpCtx.title]
    .filter(Boolean).join(" · ");
  $("#nextEpTitle").textContent = `${nextEpCtx.next}화 만들기`;
  $("#nextEpSub").textContent =
    `${nextEpCtx.next - 1}화에 이어서 만듭니다. 이야기와 캐릭터는 다시 만들지 않습니다.`;
  $("#nextEpAsk").hidden = false;
  $("#nextEpRun").hidden = true;
  $("#nextEpNote").value = "";
  view("nextep");
  window.scrollTo(0, 0);
}

function closeNextEp() {
  clearInterval(nextEpPoll); nextEpPoll = null; nextEpJob = null;
  view("result");
}

async function startNextEp() {
  if (!nextEpCtx) return;
  const go = $("#nextEpGo");
  go.disabled = true;
  try {
    const res = await fetch(
      `/api/runs/${encodeURIComponent(nextEpCtx.runId)}/next-episode`,
      { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ author_note: $("#nextEpNote").value.trim(), uid: UID }) });
    const out = await res.json();
    if (!res.ok) throw new Error(out.error || "시작하지 못했습니다");
    nextEpJob = out.id;
    // 서버가 정한 번호로 맞춘다 — 화면이 짐작한 것과 다를 수 있다.
    if (out.episode) {
      nextEpCtx.next = out.episode;
      $("#nextEpTitle").textContent = `${out.episode}화 만들기`;
    }
    $("#nextEpAsk").hidden = true;
    $("#nextEpRun").hidden = false;
    nextEpPoll = setInterval(tickNextEp, 1500);
    tickNextEp();
  } catch (err) {
    toast(err.message);
  }
  go.disabled = false;
}

async function tickNextEp() {
  if (!nextEpJob) return;
  let s;
  try { s = await (await fetch(`/api/jobs/${nextEpJob}`)).json(); }
  catch { return; }                        // 잠깐 끊겨도 다음 번에 이어진다

  const stages = s.stages || [];
  $("#nextEpSteps").innerHTML = stages.map((st, i) => {
    const cls = st.state === "done" ? "is-done"
              : (i === s.stage_index ? "is-active" : "");
    return `<li class="${cls}"><span class="dot"></span>
      <span>${esc(st.title)}</span>
      <small style="margin-left:auto;color:var(--muted,#8a8a94)">${esc(st.desc || "")}</small>
    </li>`;
  }).join("");
  const cur = stages[s.stage_index] || {};
  $("#nextEpNote2").textContent = cur.note || s.error || "";

  if (s.status === "done") {
    clearInterval(nextEpPoll); nextEpPoll = null;
    // 완성본은 1화와 같은 결과 화면에서 본다 — 읽는 화면은 회차가 달라도 같다.
    jobId = nextEpJob;
    sessionStorage.setItem("lore_job", jobId);
    nextEpJob = null;
    toast(`${nextEpCtx.next}화가 나왔습니다`);
    showResult();
    return;
  }
  if (s.status === "error" || s.status === "cancelled") {
    clearInterval(nextEpPoll); nextEpPoll = null;
    $("#nextEpNote2").textContent = s.error || "만들지 못했습니다";
    $("#nextEpAsk").hidden = false;       // 다시 눌러 볼 수 있게 되돌린다
    nextEpJob = null;
  }
  // 콘티 승인이 필요한 상태 — 이어 만들기에서는 "다시 짜기" 를 못 한다
  // (스토리 하네스가 회차를 되돌리는 길을 아직 안 준다). 진행만 물어본다.
  if (s.status === "awaiting_board_approval") {
    $("#nextEpNote2").innerHTML =
      `${esc(s.stages?.[s.stage_index]?.note || "콘티를 확인해 주세요")}<br>` +
      `<button type="button" class="btn btn-primary btn-sm" id="nextEpApprove">이대로 진행</button>`;
    document.getElementById("nextEpApprove")?.addEventListener("click", async () => {
      await fetch(`/api/jobs/${nextEpJob}/board-decision`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ decision: "approve" }) });
    }, { once: true });
  }
}

/* ------------------------------------------------- 내 웹툰 목록 (/works)
 *
 * 지금까지 만든 것을 볼 길이 편집실뿐이었다. 편집실은 **고치는 자리**라 도구가
 * 늘 곁에 붙어 있어서, 읽으려고 여는 곳으로는 맞지 않았다. 여기는 그냥 읽는
 * 자리다 — 고르면 완성본 화면(#result)이 그대로 열린다.
 *
 * 목록은 편집실과 같은 /api/runs 를 쓴다. 작업(job)을 안 거치므로 하네스를
 * 직접 돌린 것도, 이어 만들어 job 기록이 없는 회차도 빠짐없이 나온다. */

/* ---- 마이페이지 --------------------------------------------------------
 *
 * 「내 웹툰」(/works)이 이 서버에 있는 작품 전부라면, 여기는 **내 계정에
 * 저장한 것만** 이다. 둘을 나눈 이유: 계정 없이도 만들 수 있는 서비스라
 * 서버에는 로그인 전에 만든 것이나 남의 것이 섞여 있다.
 *
 * 목록은 /api/runs 를 받아 계정의 claimed_runs 로 거른다 — 서버에 새 API 를
 * 만들지 않아도 되고, 작품 카드 그리는 코드도 /works 와 그대로 나눠 쓴다. */
/* 큰 화면 조각들. 하나를 보이면 **나머지는 반드시 숨는다** — 예전에는 부르는
   쪽마다 숨길 목록을 따로 들고 있어서, 조각이 하나 늘 때(마이페이지) 어떤
   경로에서는 안 숨겨져 두 화면이 위아래로 이어 붙어 보였다. */
const SECTIONS = ["#create", "#progress", "#result", "#works", "#nextEp", "#mypage"];

function showOnly(id) {
  SECTIONS.forEach(sel => { const el = $(sel); if (el) el.hidden = sel !== id; });
}

function onlyMyPage() {
  view("mypage");
  window.scrollTo(0, 0);
}

async function showMyPage() {
  // 주소로 바로 들어온 경우 계정 상태가 아직 안 왔을 수 있다 — 기다렸다 본다.
  if (accountReady) { try { await accountReady; } catch { /* 아래에서 걸린다 */ } }
  if (!accountState.logged_in) return openAccountModal("login");
  onlyMyPage();
  if (!LORE.isAt("/mypage")) history.pushState(null, "", LORE.at("/mypage"));

  $("#myPhoto").src = accountState.photo_url || GUEST_PILL_PHOTO;
  $("#myNickname").textContent = accountState.nickname || "";
  refreshCreditBalance();          // 다른 탭에서 썼을 수 있다 — 열 때마다 새로 받는다

  const host = $("#myWorksGrid");
  host.innerHTML = `<p class="works-empty">불러오는 중…</p>`;
  // 둘러보기 목록(/api/runs)이 아니라 계정 전용 목록을 받는다 — 숨긴 작품은
  // 둘러보기에서 빠지므로, 그쪽에서 걸러 오면 내가 숨긴 것이 내 목록에서도
  // 사라진다. 이 주소는 숨긴 것까지 주고 공개 여부를 함께 붙여 준다.
  let runs = null;
  try { runs = (await (await fetch("/api/account/works")).json()).runs || []; }
  catch { /* 아래에서 */ }

  if (runs === null) {
    $("#myMeta").textContent = "";
    host.innerHTML = `<div class="works-empty">
      <img src="${louArt("error")}" alt="" aria-hidden="true">
      <b>목록을 가져오지 못했어요</b>
      서버가 떠 있는지 확인해 주세요.</div>`;
    return;
  }
  const hidden = runs.filter(r => r.public === false).length;
  $("#myMeta").textContent = `저장한 작품 ${runs.length}편`
    + (hidden ? ` · 그중 ${hidden}편은 나만 보기` : "");
  if (!runs.length) {
    host.innerHTML = `<div class="works-empty">
      <img src="${louArt("empty")}" alt="" aria-hidden="true">
      <b>아직 담아둔 작품이 없어요</b>
      완성본 화면에서 <b>계정에 담아두기</b>를 누르면 여기에 쌓입니다.
      <br><a class="inline-link" href="/#studio">내 캐릭터로 웹툰 만들기 →</a></div>`;
    return;
  }
  host.innerHTML = runs.map(r => workCard(r, true)).join("");
  bindOpen(host);
  bindPubToggles(host);
}

/* 마이페이지 **목업** — /demo/mypage. 계정을 안 만들어도 화면을 볼 수 있게
   가짜 계정과 작품 두 편을 넣는다. */
function showMockMyPage() {
  onlyMyPage();
  $("#myPhoto").src = "/static/lou/react/idle/01.webp";
  $("#myNickname").textContent = "루를 아는 사람";
  $("#myMeta").textContent = "저장한 작품 4편 · 화면 구경용 목업입니다";
  // 표지는 **단추**여야 한다. 목업이라고 눌리지 않는 것을 두면, 화면을 보러 온
  // 사람은 그것이 목업이라서인지 고장이라서인지 알 수 없다 — 실제로 "저장한
  // 작품 클릭이 안 된다"로 돌아왔다. 눌리면 완성본 목업이 열린다(진짜 마이
  // 페이지에서 카드를 눌렀을 때와 같은 자리).
  const card = (no, character, sub) => `
    <article class="works-card">
      <button type="button" class="works-cover" data-mock-open
              aria-label="${esc(character)} 열기">
        <img src="/static/samples/mock/scene${no}.jpg" alt="" loading="lazy">
      </button>
      <div class="works-body">
        <h3>${esc(character)}</h3>
        <p class="works-sub">${esc(sub)}</p>
      </div>
    </article>`;
  // 넉 장을 둔다 — 두 장이면 옆으로 밀 것이 없어서 줄이 줄인 줄 모른다.
  $("#myWorksGrid").innerHTML =
    card(1, "모모", "로맨스 판타지 · 약속의 무게, 장난의 시작")
    + card(3, "초롱", "무협 · 강호에 첫발")
    + card(2, "하람", "헌터·게이트 · 첫 번째 각성")
    + card(4, "유리", "학원로맨스 · 3학년 3반의 봄");
  $$("#myWorksGrid [data-mock-open]").forEach(b =>
    b.addEventListener("click", () => showMockResult()));
  $("#myLogout").hidden = true;
  // 목업에서도 상단 배지가 로그인 뒤 모습(사진 + 마이페이지)으로 보여야
  // "로그인하면 여기가 바뀐다"가 화면으로 전달된다. 진짜 로그인은 아니다.
  mockAccountPill = true;
  paintAccountPill();
  // 잔액도 숫자가 있어야 화면이 완성돼 보인다 — 목업이라 서버 값이 아니다.
  // (mockAccountPill 을 켠 **뒤에** 넣어야 진짜 잔액이 덮어쓰지 않는다.)
  // 목업 숫자도 실제 값 체계(한 편 8C)와 같은 눈금을 쓴다 — 화면마다 단위가
  // 다르면(120C vs 8C) 어느 쪽이 진짜인지 알 수 없게 된다.
  $("#myCreditNum").textContent = "72";
  $("#myCreditHint").textContent = "한 편에 8 C — 지금 9편 더 만들 수 있어요";
}

/* 만드는 도중에 둘러보기로 빠져나가는 길. 주소를 새로 여는 링크(<a href>)와
   달리 페이지를 다시 안 읽어서, 돌던 폴링과 루의 놀이 상태가 그대로 남는다. */
function goWorks() {
  if (!LORE.isAt("/works") || location.search) {
    history.pushState(null, "", LORE.at("/works"));
  }
  showWorks();
}

async function showWorks() {
  view("works");
  window.scrollTo(0, 0);

  const host = $("#worksGrid");
  host.innerHTML = `<p class="works-empty">불러오는 중…</p>`;
  let runs = null;
  try { runs = (await (await fetch("/api/runs")).json()).runs || []; }
  catch { /* 아래에서 */ }

  // 빈 화면·오류 화면에도 루를 세운다 — 글자만 있으면 고장난 것처럼 읽힌다.
  if (runs === null) {
    host.innerHTML = `<div class="works-empty">
      <img src="${louArt("error")}" alt="" aria-hidden="true">
      <b>목록을 가져오지 못했어요</b>
      서버가 떠 있는지 확인해 주세요.</div>`;
    return;
  }
  if (!runs.length) {
    host.innerHTML = `<div class="works-empty">
      <img src="${louArt("empty")}" alt="" aria-hidden="true">
      <b>아직 구경할 웹툰이 없어요</b>
      첫 작품이 이 자리에 걸립니다.
      <br><a class="inline-link" href="/#studio">내 캐릭터로 웹툰 만들기 →</a></div>`;
    return;
  }
  // map 은 두 번째 인자로 **번째 수**를 넘긴다 — workCard(r, mine) 에 그대로
  // 넘기면 두 번째 카드부터 mine 이 참이 돼서, 둘러보기인데 남의 작품에
  // 공개 스위치와 편집실 링크가 붙는다. 화살표로 감싸 한 개만 넘긴다.
  host.innerHTML = runs.map(r => workCard(r)).join("");
  bindOpen(host);
}

/* 작품 목록에서 카드를 눌러 여는 길. **목록에 한 번** 매단다.

   전에는 카드마다 따로 매달았다. 목록을 다시 그리면(공개 스위치를 켜거나
   회차가 늘면 그린다) 새로 꽂힌 카드에는 아무도 안 매달려서, 보기에는 멀쩡한
   카드가 눌러도 안 열렸다. 목록 자체에 매달면 다시 그려도 살아 있다.

   `closest` 로 찾으므로 표지 안의 <img> 를 눌러도 표지를 누른 것이 된다. */
function bindOpen(host) {
  if (!host || host.dataset.openBound) return;
  host.dataset.openBound = "1";
  host.addEventListener("click", e => {
    const b = e.target.closest("[data-open]");
    if (!b || !host.contains(b)) return;
    showRunResult(b.dataset.open, Number(b.dataset.ep) || 1);
  });
}

/* 작품 카드. 둘러보기와 마이페이지가 같은 카드를 쓰되, **내 것일 때만**
   편집실로 가는 길과 공개 스위치가 붙는다 — 남의 작품에 있을 수 없는 길이다. */
function workCard(r, mine = false) {
  const eps = r.episodes || [];
  const first = eps[0] || 1;
  // loading="lazy" 를 안 쓴다. 이 목록은 화면을 바꿔 끼우며 그리는데(hidden 이던
  // 자리에 innerHTML 로 꽂는다), 그 경로에서는 브라우저가 "화면에 들어왔다" 를
  // 다시 안 재서 표지가 영영 안 뜬다 — 그림체 썸네일에서 이미 같은 자리를
  // 겪었다. 표지는 ?w=320 으로 줄여 받으므로 한 장에 60KB 안쪽이다.
  const cover = r.cover_page
    ? `<img src="/api/runs/${encodeURIComponent(r.run_id)}/page/${r.cover_page}` +
      `?w=320&ep=${r.cover_episode || first}" alt="">`
    : `<span class="works-cover-empty" aria-hidden="true">🖼</span>`;
  // 회차마다 단추를 준다 — "몇 편이 있다"를 세는 것과 "그 편을 연다"가 같은
  // 자리에 있어야, 2화가 있는데 1화만 열리는 일이 안 생긴다.
  // 회차가 하나뿐이면 「1화」 딱지는 표지를 누르는 것과 똑같은 일을 한다 —
  // 좁은 카드에서 자리만 먹으므로 여러 화가 있을 때만 낸다.
  const epBtns = eps.length > 1 ? eps.map(n =>
    `<button type="button" class="works-ep" data-open="${esc(r.run_id)}" data-ep="${n}">`
    + `${n}화</button>`).join("") : "";
  return `
    <article class="works-card">
      <button type="button" class="works-cover" data-open="${esc(r.run_id)}"
              data-ep="${first}" aria-label="${esc(r.character || r.run_id)} 열기">
        ${cover}
      </button>
      <div class="works-body">
        <h3>${esc(r.character || "이름 없음")}</h3>
        <p class="works-sub">${esc([r.genre, r.title].filter(Boolean).join(" · "))}</p>
        <p class="works-count">${eps.length > 1 ? eps.length + "화 · " : ""}${r.page_count}장</p>
        <div class="works-eps">${epBtns}</div>
        ${mine ? myTools(r, first) : ""}
      </div>
    </article>`;
}

/* 내 작품에만 붙는 줄 — 편집실로 가는 길과 공개 스위치.
   공개가 기본이라 스위치는 대개 켜져 있다. 끄면 둘러보기에서 내려가고
   마이페이지에서는 그대로 보인다. */
function myTools(r, first) {
  const on = r.public !== false;
  return `
    <label class="works-pub">
      <input type="checkbox" class="works-pub-box" data-pub="${esc(r.run_id)}" ${on ? "checked" : ""}>
      <span>${on ? "둘러보기에 공개" : "나만 보기"}</span>
    </label>
    <a class="works-edit" href="/editor?run=${encodeURIComponent(r.run_id)}&ep=${first}">편집실에서 열기 →</a>`;
}

/* 스위치를 누르면 그 자리에서 서버에 알린다. 실패하면 되돌린다 — 껐다고
   보이는데 실제로는 걸려 있는 것이 제일 나쁘다. */
function bindPubToggles(host) {
  $$(".works-pub-box", host).forEach(box => box.addEventListener("change", async () => {
    const want = box.checked;
    const label = box.parentElement.querySelector("span");
    box.disabled = true;
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(box.dataset.pub)}/visibility`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ public: want }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || "바꾸지 못했습니다");
      label.textContent = want ? "둘러보기에 공개" : "나만 보기";
      toast(want ? "둘러보기에 걸었어요" : "둘러보기에서 내렸어요");
    } catch (err) {
      box.checked = !want;                 // 서버가 안 받았으면 화면도 되돌린다
      toast(err.message);
    } finally {
      box.disabled = false;
    }
  }));
}

/* ------------------------------------------------------------------ 잡동사니 */

/* 화면 전환은 여기 한 곳으로만 한다.
 *
 * 예전에는 부르는 쪽마다 "이건 보이고 저건 숨기고" 를 손으로 적었다. 그래서
 * 한 자리라도 빠뜨리면 두 화면이 위아래로 이어 붙었다 — 만들기를 밟다가
 * 「미리보기 만들기」를 누르면 진행 화면이 만들기 **아래에** 생겼고, 헤더의
 * LORE 로 홈에 와도 위저드가 홈 위에 남았다. 조각이 하나 늘 때마다(마이페이지,
 * 이어 만들기) 같은 사고가 되풀이됐다.
 *
 * 이제 화면 이름 하나만 넘기면 그 화면의 조각만 남고 나머지는 전부 닫힌다.
 * 새 화면을 만들면 여기 한 줄만 더하면 된다. */
const VIEW_SECTION = {
  landing: null,          // 홈은 CSS 가 보여준다(body[data-view] 참고)
  create:  "#create",
  running: "#progress",
  result:  "#result",
  works:   "#works",
  mypage:  "#mypage",
  nextep:  "#nextEp",
};

function view(name) {
  document.body.dataset.view = name;
  showOnly(VIEW_SECTION[name] ?? null);
  // 물빛(걸음) 표시는 만들기 화면만의 것이다. 남겨 두면 홈이나 결과 화면까지
  // 마지막 걸음의 색을 물고 온다.
  if (name !== "create") delete document.body.dataset.step;
  syncMini();
}

/* ---- 떠 있는 진행 표시 --------------------------------------------------- *
 *
 * 만드는 일은 서버에서 돈다. 그래서 진행 화면을 떠나도 작업은 안 멈추는데,
 * 예전에는 떠나는 순간 **어디까지 왔는지 볼 길이 사라졌다** — 그래서 사람들이
 * 몇 분씩 진행 화면만 붙들고 있었다. 이 동그란 표시가 그 정보를 들고 따라다닌다.
 *
 * 진행 화면(running)에서는 안 뜬다 — 그 화면이 곧 진행 표시라 겹친다.
 *
 * 끌어서 옮길 수 있다: 읽고 있는 글자를 가리면 치울 수 있어야 한다. 접으면
 * 오른쪽 가장자리 손잡이만 남는다 — 완전히 없애지 않는 이유는, 도로 펼 길이
 * 사라지면 "꺼졌다"와 구분이 안 되고 확인이 필요해 멈췄을 때 알릴 자리도
 * 없어지기 때문이다. */
const MINI_CIRC = 2 * Math.PI * 19;      // style.css 의 r=19 와 같아야 한다
const MINI_STAGE_ART = ["story", "sheet", "board", "art", "bind", "done"];
let miniState = null;                     // 마지막으로 받은 진행 상태
let miniFolded = sessionStorage.getItem("lore_mini_folded") === "1";

/* 앱은 480px 한 컬럼이라, fixed 로 두면 넓은 화면에서 컬럼 바깥 허공에 뜬다.
   실제 body 폭 안으로 가둔다. 창 크기가 바뀌어도 다시 가둔다. */
function miniPlace(x, y) {
  const el = $("#miniProg");
  if (!el) return;
  const b = document.body.getBoundingClientRect();
  const w = el.offsetWidth || 62, h = el.offsetHeight || 62;
  const pad = 10;
  // fixed 의 기준은 스크롤바를 뺀 폭이다 — innerWidth 를 쓰면 스크롤바만큼
  // 어긋나서 오른쪽 끝에 붙였을 때 컬럼 안으로 파고든다.
  const vw = document.documentElement.clientWidth;
  const vh = document.documentElement.clientHeight;
  const minX = Math.max(pad, b.left + pad);
  const maxX = Math.max(minX, Math.min(vw - w - pad, b.right - w - pad));
  const maxY = Math.max(pad, vh - h - pad);
  const cx = Math.min(Math.max(x, minX), maxX);
  const cy = Math.min(Math.max(y, pad), maxY);
  el.style.left = `${cx}px`;
  el.style.top = `${cy}px`;
  sessionStorage.setItem("lore_mini_at", JSON.stringify([cx, cy]));
}

function miniRestorePlace() {
  const el = $("#miniProg");
  if (!el) return;
  let at = null;
  try { at = JSON.parse(sessionStorage.getItem("lore_mini_at") || "null"); } catch { /* 기본자리로 */ }
  if (Array.isArray(at)) return miniPlace(at[0], at[1]);
  const b = document.body.getBoundingClientRect();
  miniPlace(b.right - 72 - 10, document.documentElement.clientHeight - 62 - 96);
}

/* 지금 이 화면에서 표시를 띄울지 말지. 진행 화면이면 숨고, 도는 작업이 없어도
   숨는다. 접힌 상태면 손잡이만 남긴다. */
function syncMini() {
  const el = $("#miniProg"), tab = $("#miniProgTab");
  if (!el || !tab) return;
  const live = !!jobId && document.body.dataset.view !== "running";
  el.hidden = !live || miniFolded;
  tab.hidden = !live || !miniFolded;
  if (live && !miniFolded) miniRestorePlace();
  // 손잡이도 앱 컬럼(480px)의 오른쪽 가장자리에 붙인다 — fixed 라 그냥 두면
  // 넓은 화면에서 컬럼 바깥 허공에 혼자 떨어져 붙는다.
  if (live && miniFolded) {
    const b = document.body.getBoundingClientRect();
    tab.style.right = `${Math.max(0, document.documentElement.clientWidth - b.right)}px`;
  }
}

function paintMini(s) {
  miniState = s;
  syncMini();
  const el = $("#miniProg");
  if (!el || el.hidden) {
    // 접혀 있어도 손잡이의 숫자는 갱신한다 — 접었다고 진행이 멈춘 건 아니다.
    const t = $("#miniProgTabPct");
    if (t) t.textContent = (s.status === "done" ? "완성" : `${louPercent(s)}%`);
    return;
  }

  const pct = louPercent(s);
  const arc = $("#miniProgArc");
  if (arc) arc.style.strokeDashoffset = String(MINI_CIRC * (1 - pct / 100));

  const state = s.status === "done" ? "done"
    : (s.status === "error" || s.status === "cancelled") ? "error"
    : (s.status || "").startsWith("awaiting_") ? "await" : "run";
  el.dataset.state = state;

  const pctEl = $("#miniProgPct");
  if (pctEl) pctEl.textContent = state === "done" ? "완성"
    : state === "await" ? "확인!"
    : state === "error" ? "멈춤" : `${pct}%`;

  // 얼굴은 지금 단계의 그림을 쓴다 — 표시만 보고도 어디쯤인지 짐작이 간다.
  const key = s.stages && s.stages[s.stage_index] && s.stages[s.stage_index].key;
  const face = $("#miniProgFace");
  if (face) {
    const want = state === "error" ? louArt("error")
      : state === "done" ? "/static/lou/stage/done.webp"
      : MINI_STAGE_ART.includes(key) ? `/static/lou/stage/${key}.webp`
      : "/static/lou/react/idle/01.webp";
    if (!face.getAttribute("src").endsWith(want)) face.src = want;
  }

  const go = $("#miniProgGo");
  if (go) go.setAttribute("aria-label", state === "done"
    ? "웹툰이 완성됐습니다 — 눌러서 보기"
    : state === "await" ? "확인이 필요합니다 — 눌러서 보기"
    : `만드는 중 ${pct}% — 눌러서 진행 화면으로`);
}

/* 표시를 눌렀을 때. 다 됐으면 완성본으로, 아니면 진행 화면으로 돌아간다. */
function miniOpen() {
  if (miniState && miniState.status === "done") { showResult(); return; }
  view("running");
  window.scrollTo(0, 0);
  // 떠나 있는 동안 renderProgress 를 안 그렸다 — 상태가 그대로면 확인 시트
  // 같은 것을 다시 안 그리므로, 처음 보는 것처럼 한 번 새로 그리게 한다.
  lastStatus = null;
  if (!poll) poll = setInterval(tick, 800);
  tick();
}

function setupMini() {
  const el = $("#miniProg"), go = $("#miniProgGo");
  if (!el || !go) return;

  // 끌기. 조금이라도 움직였으면 누른 것으로 안 친다 — 옮기려다 화면이
  // 바뀌어 버리면 옮길 수가 없다.
  let dragging = false, moved = false, dx = 0, dy = 0;
  go.addEventListener("pointerdown", e => {
    dragging = true; moved = false;
    const r = el.getBoundingClientRect();
    dx = e.clientX - r.left; dy = e.clientY - r.top;
    go.setPointerCapture(e.pointerId);
    el.dataset.dragging = "1";
  });
  go.addEventListener("pointermove", e => {
    if (!dragging) return;
    if (Math.abs(e.movementX) + Math.abs(e.movementY) > 0) moved = true;
    miniPlace(e.clientX - dx, e.clientY - dy);
  });
  const end = () => { dragging = false; delete el.dataset.dragging; };
  go.addEventListener("pointerup", end);
  go.addEventListener("pointercancel", end);
  go.addEventListener("click", e => {
    if (moved) { e.preventDefault(); moved = false; return; }
    miniOpen();
  });

  $("#miniProgHide").addEventListener("click", () => {
    miniFolded = true;
    sessionStorage.setItem("lore_mini_folded", "1");
    syncMini();
    if (miniState) paintMini(miniState);
  });
  $("#miniProgTab").addEventListener("click", () => {
    miniFolded = false;
    sessionStorage.removeItem("lore_mini_folded");
    syncMini();
    if (miniState) paintMini(miniState);
  });

  // 창이 좁아지면 표시가 화면 밖에 남을 수 있다 — 다시 가둔다.
  window.addEventListener("resize", () => {
    if (!$("#miniProg").hidden) miniRestorePlace();
  });
}

/* 루는 홈에 들어설 때마다 다른 모습으로 맞이한다 — 홈의 큰 그림도, 헤더의
   로고도. 새로고침도, 편집실이나 내 웹툰을 보다 돌아오는 것도 똑같이 새로
   뽑힌다. 기억해 두지 않는 것이 곧 규칙이라 저장소를 안 쓴다.

   로고 그림은 표정 원화(whale1·whale2 × 6종)에서 **고래 몸통만** 잘라 둔
   것이다. 원화에는 말풍선·하트·별이 옆에 붙어 있는데 32px 로 줄이면 얼룩으로
   뭉개져서, 알파가 이어진 가장 큰 덩어리만 남겨 뗐다. 그래서 12장 모두 작게
   줄여도 고래로 읽힌다. */
const HERO_LOUS = ["/static/lou/hero-whale2.png", "/static/lou/hero-whale1.png"];
/* 로고 12장 목록은 lou-art.js 가 들고 있다 — 편집실도 같은 로고를 쓴다. */

function swapLou(el, list) {
  if (!el) return;
  const pick = list[Math.floor(Math.random() * list.length)];
  if (el.getAttribute("src") !== pick) el.src = pick;
}
/* 이름은 그대로 두었다 — 홈으로 돌아가는 네 자리에서 이미 부르고 있다. */
function pickHero() {
  swapLou($("#heroLou"), HERO_LOUS);
  swapLou($("#brandLou"), LOU_LOGOS);
}

/* 걸음의 제목 옆에 앉은 루. 걸음을 옮길 때마다 바뀐다.
   방금 걸려 있던 그림과 헤더 로고에 걸린 그림은 후보에서 뺀다 — 안 그러면
   "안 바뀌었네" 로 보이거나 같은 고래가 화면에 둘 나온다. */
function pickWizLou() {
  const el = $("#wizLou");
  if (!el) return;
  const now = el.getAttribute("src");
  const brand = $("#brandLou") ? $("#brandLou").getAttribute("src") : "";
  const pool = LOU_LOGOS.filter(s => s !== now && s !== brand);
  el.src = pool[Math.floor(Math.random() * pool.length)];
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g,
    ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
}
function forget() {
  sessionStorage.removeItem("lore_job");
  jobId = null; clearInterval(poll); poll = null;
  miniState = null;              // 떠 있는 표시는 view() 안의 syncMini() 가 닫는다
  shownCuts = new Set(); $("#cutGrid").innerHTML = ""; $("#cutstrip").hidden = true;
  $("#cancelBtn").textContent = "중단"; $("#cancelBtn").onclick = null;
  $("#clockLabel").textContent = "경과";
  // view("landing") 하나로 큰 화면 조각이 전부 닫힌다 — 만들기·진행·결과·
  // 내 웹툰·이어 만들기·마이페이지까지(VIEW_SECTION 참고). 여기서 하나씩
  // 손으로 닫던 시절에 빠뜨린 조각이 홈 아래에 그대로 이어 붙곤 했다.
  view("landing"); pickHero();
  // 목업에서 켜 둔 "로그인한 척"도 여기서 푼다 — 안 풀면 홈에 돌아와도 배지가
  // 「마이페이지」로 남아, 로그인도 안 했는데 한 것처럼 보인다.
  mockAccountPill = false;
  paintAccountPill();
  // 대사 스크립트 자리는 새 결과 화면에서 없어졌다 — 남아 있을 때만 닫는다.
  // (없는 요소에 hidden 을 쓰면 여기서 죽어서, 홈으로 나가는 길 자체가 막힌다.)
  const script = $("#scriptPanel");
  if (script) script.hidden = true;
  // 이어 만들기는 화면만 닫아서는 안 된다 — 돌던 폴링과 붙잡고 있던 회차
  // 정보까지 놓아야 "새로 만들기" 가 앞 작품을 물고 오지 않는다.
  clearInterval(nextEpPoll); nextEpPoll = null; nextEpJob = null; nextEpCtx = null;
  // 화면 조각이 아니라 그 안의 단추들이다 — view() 가 안 건드린다.
  $("#nextEpBtn").hidden = true;
  $("#moreCutsBtn").hidden = true;
  // /result 로 들어왔으면 주소도 되돌린다 — 안 그러면 새로고침에 다시 결과가 뜬다.
  if (location.pathname !== LORE.HOME || location.search)
    history.replaceState(null, "", LORE.HOME);
  // #studio 는 만들기 화면 안에 있다 — 방금 닫았으니 거기로 스크롤할 수 없다.
  // 홈으로 왔으면 홈 맨 위가 맞다.
  window.scrollTo(0, 0);
}
let toastTimer = null;
function toast(msg) {
  const el = $("#toast");
  el.textContent = msg; el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 2600);
}

document.addEventListener("DOMContentLoaded", () => {
  buildForm();
  loadWorlds();
  loadFeedbackTags();
  setupPhoto();
  // 결과 화면 부제의 "몇 컷째". 한 번만 걸어 두고, 결과 화면이 아닐 때는
  // paintResultPos 가 알아서 아무것도 안 한다(resultPos 가 비어 있다).
  addEventListener("scroll", paintResultPos, { passive: true });
  $("#form").addEventListener("submit", submit);
  // 연출(빠르게/웹툰)이 바뀌면 그림 호출 수가 달라져 비용도 달라진다.
  document.querySelectorAll('input[name="layout_mode"]').forEach(
    el => el.addEventListener("change", paintCost));

  // 모드 — 폼을 만든 **뒤에** 적용해야 한다(applyMode 가 폼의 칸을 여닫는다).
  applyMode();
  // 위저드도 폼을 만든 뒤에 켠다(그림체·항목 칸이 있어야 요약을 그릴 수 있다).
  setupWizard();
  setupLou();
  setupTips();
  loadCreditConfig();       // /api/config 가 도착하면 비용 칩을 실제 값으로 다시 그린다
  refreshCreditBalance();
  paintCost();

  $("#chargeBtn").addEventListener("click", openChargeModal);
  $("#myChargeBtn")?.addEventListener("click", openChargeModal);
  $("#chargeModalClose").addEventListener("click", closeChargeModal);
  $("#chargeBack").addEventListener("click", () => chargeStep("package"));
  $("#chargeBackToCard").addEventListener("click", () => chargeStep("card"));
  document.querySelectorAll("[data-method]").forEach(b =>
    b.addEventListener("click", () => {
      chargeSelectedMethod = b.dataset.method;
      showChargeConfirm();
    }));
  $("#chargeConfirmNo").addEventListener("click", () => chargeStep("method"));
  $("#chargeConfirmYes").addEventListener("click", finishCharge);
  $("#chargeDoneClose").addEventListener("click", closeChargeModal);
  // 바탕을 눌러도 닫힌다 — 상자 자체를 누른 건 안 닫는다.
  $("#chargeModal").addEventListener("click", e => {
    if (e.target.id === "chargeModal") closeChargeModal();
  });

  accountReady = refreshAccount();
  // 로그인 전에는 계정 창을 열고, 로그인 뒤에는 마이페이지로 간다.
  $("#accountBtn").addEventListener("click", () => {
    if (accountState.logged_in) showMyPage();
    else openAccountModal();
  });
  $("#myLogout")?.addEventListener("click", async () => {
    await logout();
    location.href = LORE.HOME;
  });
  $("#accountModalClose").addEventListener("click", closeAccountModal);
  $("#accountModal").addEventListener("click", e => {
    if (e.target.id === "accountModal") closeAccountModal();
  });
  $("#tabLogin").addEventListener("click", () => switchAccountTab("login"));
  $("#tabSignup").addEventListener("click", () => switchAccountTab("signup"));
  $("#loginForm").addEventListener("submit", onLogin);
  $("#signupForm").addEventListener("submit", onSignup);
  $("#logoutBtn").addEventListener("click", logout);
  $("#claimBtn").addEventListener("click", claimCurrentRun);
  $("#photoUpload").addEventListener("change", e => {
    const file = e.target.files[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) return toast("이미지 파일만 됩니다");
    if (file.size > 3 * 1024 * 1024) return toast("사진이 너무 큽니다 (3MB 까지)");
    const fr = new FileReader();
    fr.onload = () => {
      signupPhoto = { kind: "upload", data_url: fr.result };
      $$(".photo-opt", $("#photoGrid")).forEach(b => b.classList.remove("is-selected"));
      $(".photo-upload-btn").classList.add("is-selected");
    };
    fr.readAsDataURL(file);
  });

  // 중단은 두 걸음이다 — 누르면 확인 창이 뜨고, 거기서 한 번 더 눌러야 실제로
  // 멈춘다. 되돌릴 수 없고 크레딧도 안 돌아오기 때문이다.
  $("#cancelBtn").addEventListener("click", () => {
    if (!jobId) return;
    $("#cancelModal").hidden = false;
    // 기본 손가락은 "계속 만들기" 위에 둔다 — 엔터 한 번에 중단되면 안 된다.
    $("#cancelKeep").focus();
  });
  $("#cancelKeep").addEventListener("click", () => { $("#cancelModal").hidden = true; });
  $("#cancelModal").addEventListener("click", e => {
    if (e.target.id === "cancelModal") $("#cancelModal").hidden = true;   // 바깥 누르면 닫기
  });
  $("#cancelConfirm").addEventListener("click", async () => {
    $("#cancelModal").hidden = true;
    if (!jobId) return;
    await fetch(`/api/jobs/${jobId}/cancel`, { method: "POST" });
  });
  $("#sheetApproveBtn").addEventListener("click", () => sendSheetDecision("approve"));
  $("#sheetRetryBtn").addEventListener("click", () => sendSheetDecision("retry"));
  $("#storyApproveBtn").addEventListener("click", () => sendStoryDecision("approve"));
  $("#storyRetryBtn").addEventListener("click", () => sendStoryDecision("retry"));
  $("#boardApproveBtn").addEventListener("click", () => sendBoardDecision("approve"));
  $("#boardRetryBtn").addEventListener("click", () => sendBoardDecision("retry"));
  $("#artqaApproveBtn").addEventListener("click", sendArtqaDecision);
  $("#nextEpBtn").addEventListener("click", openNextEp);
  $("#moreCutsBtn").addEventListener("click", continueCuts);
  $("#nextEpGo").addEventListener("click", startNextEp);
  $("#nextEpBack").addEventListener("click", closeNextEp);
  $("#nextEpCancel").addEventListener("click", async () => {
    if (nextEpJob) {
      try { await fetch(`/api/jobs/${nextEpJob}/cancel`, { method: "POST" }); }
      catch { /* 이미 끝났을 수 있다 */ }
    }
    closeNextEp();
  });
  setupShare();
  setupTitleEdit();
  setupMini();
  // 만드는 동안 다른 웹툰을 보러 나간다. 작업은 서버에서 도니까 안 멈춘다 —
  // 떠 있는 표시(#miniProg)가 진행을 들고 따라붙는다.
  $("#progBrowse")?.addEventListener("click", goWorks);
  // 웹툰 한 편은 길다 — 다 읽고 나서 위로 돌아가려면 한참 끌어야 한다.
  $("#toTopBtn")?.addEventListener("click", () => {
    document.querySelector("#result")?.scrollIntoView({ behavior: "smooth" });
  });

  // 주소로 바로 열기.
  //   /result                이미 만들어 둔 **마지막** 1화를 결과 화면으로
  //   /?job=<id>             그 작업을 결과 화면으로
  //   /works                 내가 만든 웹툰 목록
  //   /works?run=<id>&ep=N   그 작품의 그 회차를 완성본 화면으로
  // 폼을 거치지 않고 결과부터 보고 싶을 때가 있어서 둔 길이다.
  const params = new URLSearchParams(location.search);
  const asked = params.get("job");
  const wantResult = LORE.isAt("/result");
  const wantWorks = LORE.isAt("/works");
  const wantMock = LORE.isAt("/demo/result");
  if (LORE.isAt("/demo/mypage")) {
    showMockMyPage();
  } else if (LORE.isAt("/mypage")) {
    showMyPage();
  } else if (wantMock) {
    showMockResult();
  } else if (wantWorks) {
    const run = params.get("run");
    if (run) showRunResult(run, Number(params.get("ep")) || 1);
    else showWorks();
  } else if (asked || wantResult) {
    openExisting(asked);
  } else if (jobId) {
    startPolling();          // 새로고침해도 돌던 작업으로 돌아온다
  }

  // 둘러보기·마이페이지로 바로 들어왔는데 만들던 작업이 아직 남아 있으면,
  // 보고 있는 화면은 그대로 두고 뒤에서만 따라간다 — 헤더의 「둘러보기」는
  // 주소를 새로 여는 링크라 이 길로 온다. 표시는 syncMini() 가 띄운다.
  if (jobId && !poll && !asked && !wantResult && !wantMock
      && (wantWorks || LORE.isAt("/mypage"))) {
    startPolling({ background: true });
  }
});
