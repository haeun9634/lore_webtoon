/* 루와 놀기 — 기다리는 화면의 만질 수 있는 자리 --------------------------- *
 *
 * 10분 가까이 이 화면을 본다. 위쪽 띠는 지금 어디쯤인지를 기계적으로 적고,
 * 여기 있는 것은 그다음 — **만질 수 있다**는 것. 기다림이 구경거리가 되면
 * 시간이 덜 길다.
 *
 * 반응은 화면에만 있다. 서버로 아무것도 안 보내고, 돌고 있는 작업에도 영향을
 * 주지 않는다. 반응이 끝나면 가만히 있는 루로 돌아간다.
 *
 * 기다리는 화면(index.html)과 화면 구경(demo.html)이 이 파일을 같이 쓴다 —
 * 예전에는 demo 가 같은 로직을 통째로 베껴 갖고 있어서 둘이 갈라졌다.
 * 마크업(#mascot / #mascotStage / #mascotImg / #playSay)이 없으면
 * setupLou() 는 조용히 아무것도 안 한다.
 *
 * 그림은 web/lou/react/ 에 있다 — design-reference/interaction 에서
 * web/lou/_sync_react.py 가 골라 줄여 온 것. 어떤 컷이 있고 어떤 말을 하는지는
 * 그쪽 manifest.json 이 들고 있어서, 컷을 늘리거나 말을 고칠 때 이 파일은
 * 안 건드려도 된다. */
(() => {
"use strict";

const $ = s => document.querySelector(s);
const ART = "/static/lou/react";

let art = null;         // manifest.json — 못 읽으면 만지기를 조용히 끈다
let busy = false;       // 반응을 재생하는 중인가
let timer = null;
let idleTimer = null;
let idleFrame = 0;
let idleKind = "idle";
let asleep = false;     // 잠들었나 — 자는 루를 누르면 깨는 컷이 나온다
let touchedAt = 0;      // 마지막으로 사람이 만진 시각

const pick = list => list[Math.floor(Math.random() * list.length)];

/* 가끔 다른 판(그림체가 같은 시트에서 온 대안 컷)으로 논다 — 매번 똑같으면
   심심하다. `<kind>_alt` 가 manifest 에 있을 때만 후보가 된다(없으면 그냥
   kind 그대로). 한 번의 반응(예: 연속 클릭 한 세션, 드래그 한 번) 안에서는
   같은 판을 끝까지 써야 컷마다 그림체가 튀지 않는다 — 그래서 반응이
   **시작할 때 한 번만** 고르고, 그 반응이 끝날 때까지 그대로 쓴다. */
const ALT_CHANCE = 0.15;
function pickKind(base) {
  const alt = base + "_alt";
  return (art && art[alt] && Math.random() < ALT_CHANCE) ? alt : base;
}

function say(text) {
  const el = $("#playSay");
  if (el) el.textContent = text;
}

function show(kind, i) {
  const set = art && art[kind];
  const img = $("#mascotImg");
  if (!set || !img) return;
  const n = Math.max(0, Math.min(i, set.frames.length - 1));
  img.src = `${ART}/${kind}/${set.frames[n]}`;
  // 말은 컷 수와 길이가 같으면 컷을 따라가고, 아니면 그중 아무거나 고른다.
  if (set.say && set.say.length) {
    say(set.say.length === set.frames.length ? set.say[n] : pick(set.say));
  }
}

/* 한 흐름을 처음부터 끝까지 재생한다.
   `after` 는 다 재생한 뒤에 할 일 — 기본은 가만히 있는 루로 돌아가기다.
   잡고 흔드는 중에는 손을 아직 안 뗐으므로 idle 로 가면 안 되고, 끄는 컷으로
   돌아가야 한다. 그래서 끝을 부르는 쪽이 정하게 열어 뒀다. */
function play(kind, step = 520, hold = 1200, after = rest) {
  const set = art && art[kind];
  if (!set) return;
  busy = true;
  const box = $("#mascot");
  if (box) box.dataset.react = kind;
  clearTimeout(timer);
  let i = 0;
  (function next() {
    show(kind, i);
    if (i < set.frames.length - 1) { i += 1; timer = setTimeout(next, step); return; }
    timer = setTimeout(after, hold);
  })();
}

/* 한 컷만 띄운다 — "누를 때마다 아무 반응이나 하나" 쪽. */
function one(kind, hold = 1500) {
  const set = art && art[kind];
  if (!set) return;
  busy = true;
  const box = $("#mascot");
  if (box) box.dataset.react = kind;
  clearTimeout(timer);
  show(kind, Math.floor(Math.random() * set.frames.length));
  timer = setTimeout(rest, hold);
}

function rest() {
  busy = false;
  const box = $("#mascot");
  if (box) delete box.dataset.react;
  say("루를 눌러 보세요");
  idleFrame = -1;
  idleKind = "idle";
  idleTick();
}

/* 가만히 둘 때. 한동안 아무도 안 만지면 잠들고, 자는 루를 누르면 깬다.
   잠드는 흐름(sleep)과 깨는 흐름(wake)이 나뉘어 있는 이유가 이것이다 —
   한 덩어리로 두면 아무도 안 만졌는데 루가 혼자 깜짝 놀라며 깬다. */
const IDLE_TO_SLEEP = 20000;

function idleTick() {
  if (busy || !art) return;
  // 기다리는 화면이 아직 안 떴으면(폼을 채우는 중) 그림을 갈아 끼울 이유가 없다
  const box = $("#mascot");
  if (!box || !box.offsetParent) return;
  asleep = Date.now() - touchedAt > IDLE_TO_SLEEP && !!art.sleep;
  const kind = asleep ? "sleep" : "idle";
  const set = art[kind];
  if (!set) return;
  if (kind !== idleKind) { idleKind = kind; idleFrame = -1; }
  idleFrame = asleep
    ? Math.min(idleFrame + 1, set.frames.length - 1)   // 다 잠들면 거기서 멈춘다
    : (idleFrame + 1) % set.frames.length;
  const img = $("#mascotImg");
  if (img) img.src = `${ART}/${kind}/${set.frames[idleFrame]}`;
}

/* 다음에 쓸 그림을 미리 받아 둔다 — 처음 누를 때 한 박자 늦게 뜨면
   "반응이 없다"로 읽힌다. 38컷 전부 합쳐 300KB 가 안 되지만, 랜딩을 열자마자
   다 받을 이유는 없다: 가만히 있는 컷만 먼저 받고 나머지는 처음 만질 때 받는다. */
let preloaded = false;
function preload(kinds) {
  for (const kind of kinds) {
    const set = art[kind];
    if (!set) continue;
    for (const f of set.frames) { new Image().src = `${ART}/${kind}/${f}`; }
  }
}
function preloadRest() {
  if (preloaded) return;
  preloaded = true;
  preload(Object.keys(art).filter(k => k !== "idle" && k !== "sleep"));
}

/* ---- 흔들기 ------------------------------------------------------------ *
 *
 * 두 길로 들어온다.
 *
 * 1. **폰을 흔든다** (devicemotion). iOS 13+ 는 사람이 허락해야 가속도를
 *    알려주고, 그 물어보는 창은 사람이 무언가를 누른 직후에만 열 수 있다.
 *    그래서 루를 처음 누를 때 같이 묻고, 아직 안 물어봤거나 거절한 기기를
 *    위해 버튼도 하나 둔다.
 * 2. **잡고 흔든다** (아래 drag 쪽). 권한이 없어도, 가속도계가 없는 PC 에서도
 *    된다. 폰에서 1번이 안 잡히는 기기가 있어서 이쪽이 사실상 본길이다.
 *
 * 1번의 판정을 **가속도 크기가 아니라 변화량(jerk)** 으로 바꿨다. 예전에는
 * |x|+|y|+|z| > 34 였는데, accelerationIncludingGravity 에는 중력(9.8)이
 * 섞여 있어서 기기를 어느 쪽으로 들고 있느냐에 따라 가만히 있어도 기준값이
 * 달라졌다 — 어떤 자세에서는 세게 흔들어야 겨우 넘고, 어떤 자세에서는 걷기만
 * 해도 넘었다. 앞뒤 표본의 **차이**를 보면 중력이 저절로 빠지고 자세와
 * 무관해진다. */
const DRAG_SHAKE_FLIPS = 3;    // 이만큼 방향이 뒤집히면 "흔든다"
const DRAG_SHAKE_WINDOW = 900; // 그 뒤집힘이 이 시간 안에 몰려 있어야 한다
                               // (사람이 손목으로 흔들면 한 번 뒤집는 데 150~250ms 다.
                               //  그냥 끌고 다니다 방향을 바꾸는 것과는 확실히 다르다.)
const HINT_BASE = "누르기 · 연달아 누르기 · 꾹 누르기 · 끌어당기기 · 잡고 흔들기";
const SHAKE_JERK = 16;        // 표본 사이 가속도 변화(m/s²). 툭 치는 정도로는 안 넘는다
const SHAKE_GAP = 2000;       // 한 번 뜬 뒤 이만큼은 다시 안 뜬다

let shakeOn = false;
let shakeAsked = false;
let shakeAt = 0;
let lastAcc = null;

/* 지금 흔들기를 띄워도 되는가. 다른 반응이 재생 중이어도 흔들기는 끼어든다 —
   누르자마자 흔들었는데 아무 일도 안 일어나면 "안 되는 것"으로 읽힌다. */
function canShake() {
  return !!(art && art.shake) && Date.now() - shakeAt >= SHAKE_GAP;
}

function fireShake(hold = 1500, after) {
  shakeAt = Date.now();
  touchedAt = Date.now();
  play(pickKind("shake"), 380, hold, after || rest);
}

function onShake(e) {
  // acceleration 은 중력이 빠진 값이라 있으면 그걸 쓴다. iOS 는 둘 다 주는데
  // 안드로이드 일부는 acceleration 의 값이 전부 null 로 온다.
  const g = e.acceleration;
  const a = (g && g.x !== null) ? g : e.accelerationIncludingGravity;
  if (!a) return;
  const now = [a.x || 0, a.y || 0, a.z || 0];
  if (!lastAcc) { lastAcc = now; return; }
  const jerk = Math.abs(now[0] - lastAcc[0])
             + Math.abs(now[1] - lastAcc[1])
             + Math.abs(now[2] - lastAcc[2]);
  lastAcc = now;
  if (jerk < SHAKE_JERK || !canShake()) return;
  fireShake();
}

function startShake() {
  if (shakeOn) return;
  shakeOn = true;
  window.addEventListener("devicemotion", onShake);
  const btn = $("#shakeAllow");
  if (btn) btn.hidden = true;
  const hint = $("#playHint");
  if (hint) hint.textContent = HINT_BASE + " · 폰 흔들기";
}

async function askShake() {
  if (shakeOn || shakeAsked) return;
  shakeAsked = true;
  const DME = window.DeviceMotionEvent;
  if (!DME) return;
  if (typeof DME.requestPermission !== "function") { startShake(); return; }
  try {
    if (await DME.requestPermission() === "granted") return startShake();
  } catch (err) { /* 아래에서 버튼을 보여 준다 */ }
  const b = $("#shakeAllow");
  if (b) b.hidden = false;
}

function setupShake() {
  const DME = window.DeviceMotionEvent;
  const btn = $("#shakeAllow");
  if (!DME) return;
  // 허락이 필요 없는 기기(안드로이드·데스크톱)는 바로 켠다
  if (typeof DME.requestPermission !== "function") { startShake(); return; }
  if (!btn) return;
  btn.hidden = false;
  btn.addEventListener("click", async () => {
    shakeAsked = true;
    try { if (await DME.requestPermission() === "granted") startShake(); }
    catch (err) { /* 거절하면 그냥 흔들기만 없다 */ }
  });
}

/* ---- 배선 ------------------------------------------------------------- */
async function setupLou() {
  const box = $("#mascot");
  const stage = $("#mascotStage");
  if (!box || !stage) return;
  try {
    const res = await fetch(`${ART}/manifest.json`);
    if (!res.ok) throw new Error("no manifest");
    art = await res.json();
  } catch (err) {
    return;                      // 그림이 없으면 만지기 자체를 끈다 (조용히)
  }
  preload(["idle", "sleep"]);
  touchedAt = Date.now();
  clearInterval(idleTimer);
  idleTimer = setInterval(idleTick, 1500);
  idleTick();

  let down = false, sx = 0, sy = 0, ox = 0, oy = 0, at = 0;
  let far = 0, turns = 0, lastDir = 0, dragging = false;
  let clicks = 0, clickWindow = null, holdTimer = null;
  // 연속 클릭 한 세션, 드래그 한 번 안에서는 컷마다 그림체가 안 튀도록
  // 시작할 때 고른 판을 끝까지 쓴다 (pickKind 주석 참고).
  let multiclickKind = "multiclick";
  let dragKind = "drag";
  // 잡고 흔들기 — 끄는 중에 방향이 바뀐 시각들. 짧은 사이에 여러 번 바뀌면
  // "흔든다"로 본다. 오래된 것은 버려서, 천천히 왔다 갔다 하는 것과 구분한다.
  let flips = [];
  let dragShaking = false;

  const home = () => {
    box.dataset.home = "1";
    box.style.left = ""; box.style.top = "";
    setTimeout(() => { delete box.dataset.home; }, 500);
  };

  const tap = () => {
    if (asleep) {                    // 자고 있었으면 먼저 깨운다
      asleep = false;
      clicks = 0;
      play("wake", 700, 1300);
      return;
    }
    clicks += 1;
    clearTimeout(clickWindow);
    clickWindow = setTimeout(() => { clicks = 0; multiclickKind = "multiclick"; }, 1500);
    if (clicks === 1) { one("click"); return; }
    if (clicks === 2) multiclickKind = pickKind("multiclick");   // 이 세션에서 쓸 판을 한 번만 고른다
    // 연달아 누르면 점점 화난다 — 누른 횟수가 그대로 컷 번호가 된다
    clearTimeout(timer);
    busy = true;
    box.dataset.react = multiclickKind;
    show(multiclickKind, Math.min(clicks - 1, art[multiclickKind].frames.length - 1));
    timer = setTimeout(rest, 1800);
  };

  box.addEventListener("pointerdown", e => {
    box.setPointerCapture(e.pointerId);
    down = true; sx = e.clientX; sy = e.clientY; at = Date.now();
    far = 0; turns = 0; lastDir = 0; dragging = false;
    flips = []; dragShaking = false;
    touchedAt = Date.now();
    const r = box.getBoundingClientRect();
    ox = e.clientX - (r.left + r.width / 2);
    oy = e.clientY - (r.top + r.height / 2);
    clearTimeout(holdTimer);
    holdTimer = setTimeout(() => {          // 꾹 누르기 — 떼기 전에 시작한다
      if (!down || far > 14 || dragging || asleep) return;
      play("longpress", 900, 900);
    }, 550);
    preloadRest();                          // 처음 만지는 순간 나머지 컷을 받는다
    askShake();                             // iOS 는 사람 손짓이 있어야 물어볼 수 있다
  });

  stage.addEventListener("pointermove", e => {
    if (!down) return;
    const dx = e.clientX - sx, dy = e.clientY - sy;
    far = Math.max(far, Math.hypot(dx, dy));
    const dir = Math.sign(e.movementX || 0);
    const prevDir = lastDir;                 // 갱신 **전** 값이라야 뒤집힘을 잡는다
    const flipped = !!(dir && prevDir && dir !== prevDir);
    if (flipped) turns += 1;
    if (dir) lastDir = dir;
    touchedAt = Date.now();

    if (far > 60) {                          // 멀리 끌면 따라온다
      if (!dragging) {
        dragging = true;
        dragKind = pickKind("drag");             // 이 드래그 한 번 동안 쓸 판을 고른다
        clearTimeout(holdTimer); clearTimeout(timer);
        busy = true;
        box.dataset.grab = "1";
        box.dataset.react = dragKind;
        show(dragKind, 0);
      }
      const sr = stage.getBoundingClientRect();
      const w = box.offsetWidth / 2, h = box.offsetHeight / 2;
      box.style.left = `${Math.max(w, Math.min(e.clientX - sr.left - ox, sr.width - w))}px`;
      box.style.top = `${Math.max(h, Math.min(e.clientY - sr.top - oy, sr.height - h))}px`;
      // 잡은 채로 좌우로 마구 흔들면 흔들기. 폰의 가속도 권한이 없어도 되고,
      // 가속도계가 없는 PC 에서도 된다 — 사실상 이쪽이 본길이다.
      if (flipped) {
        const t = e.timeStamp || Date.now();
        flips.push(t);
        while (flips.length && t - flips[0] > DRAG_SHAKE_WINDOW) flips.shift();
        if (flips.length >= DRAG_SHAKE_FLIPS && !dragShaking && canShake()) {
          flips = [];
          dragShaking = true;
          // 흔드는 동안에도 루는 손을 계속 따라온다 — 그림만 흔들기 컷으로
          // 갈아 끼우고, 자리는 이 아래 pointermove 가 그대로 옮긴다.
          fireShake(500, () => {
            dragShaking = false;
            if (!down || !dragging) return rest();   // 그새 놓았으면 그냥 마무리
            busy = true;
            box.dataset.react = dragKind;
            show(dragKind, Math.min(1, art[dragKind].frames.length - 1));
          });
        }
      }
    } else if (turns >= 3 && !dragging) {    // 제자리에서 문지르면 쓰다듬기
      turns = 0;
      clearTimeout(holdTimer);
      play(pickKind("pet"), 620, 1400);
    }
  });

  stage.addEventListener("pointerup", () => {
    if (!down) return;
    down = false;
    clearTimeout(holdTimer);
    delete box.dataset.grab;
    const held = Date.now() - at;
    touchedAt = Date.now();

    if (dragging) {                          // 놓아주면 기뻐하고 제자리로
      home();
      if (dragShaking) return;   // 흔들기 재생 중 — 끝나면 play 의 after 가 마무리한다
      show(dragKind, art[dragKind].frames.length - 1);
      clearTimeout(timer);
      timer = setTimeout(rest, 1400);
      return;
    }
    if (busy && held > 550) return;          // 꾹 누르기·쓰다듬기가 재생 중이면 둔다
    if (far > 14) return;
    tap();
  });

  stage.addEventListener("pointercancel", () => {
    down = false; delete box.dataset.grab; home();
  });

  // 키보드로도 만질 수 있어야 한다 — button 이라 Enter/Space 가 온다
  box.addEventListener("keydown", e => {
    if (e.key !== "Enter" && e.key !== " ") return;
    e.preventDefault();
    preloadRest();
    touchedAt = Date.now();
    tap();
  });

  setupShake();
}

/* ---- 팁 · TMI --------------------------------------------------------- *
 * 10분을 버티게 하는 세 번째 장치. 위쪽은 진행을 말하고, 가운데 루는 만지면
 * 반응하고, 여기는 그냥 읽을거리다. 한 번 뜨고 끝나면 곧 다시 심심해지니까
 * 몇 초마다 다음 것으로 넘어간다.
 *
 * 내용은 /static/lou/tips.json 에 있다 — 팁을 늘리거나 고칠 때 이 파일은
 * 안 건드려도 된다. 누르면 다음 것으로 바로 넘어간다. */
function shuffled(items, avoidFirst) {
  const a = items.slice();
  for (let i = a.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  // 방금 보여준 것이 또 첫 장으로 오면 한 칸 밀어 둔다
  if (avoidFirst && a.length > 1 && a[0] === avoidFirst) { [a[0], a[1]] = [a[1], a[0]]; }
  return a;
}

async function setupTips() {
  const box = $("#tips");
  const kindEl = $("#tipKind");
  const textEl = $("#tipText");
  if (!box || !kindEl || !textEl) return;

  let data;
  try {
    const res = await fetch("/static/lou/tips.json");
    if (!res.ok) throw new Error("no tips");
    data = await res.json();
  } catch (err) {
    return;                      // 팁이 없으면 그 줄 자체를 안 보여 준다
  }
  const items = (data.items || []).filter(x => x && x.text);
  if (!items.length) return;

  let order = shuffled(items);
  let i = 0;
  let timer = null;

  const paint = it => {
    box.dataset.kind = it.kind || "팁";
    kindEl.textContent = it.kind || "팁";
    textEl.textContent = it.text;
  };

  const step = () => {
    i += 1;
    if (i >= order.length) { order = shuffled(items, order[order.length - 1]); i = 0; }
    box.dataset.fade = "1";
    setTimeout(() => { paint(order[i]); delete box.dataset.fade; }, 300);
  };

  const restart = () => {
    clearInterval(timer);
    timer = setInterval(step, Math.max(3, data.seconds || 9) * 1000);
  };

  paint(order[0]);
  box.hidden = false;
  box.style.cursor = "pointer";
  box.title = "눌러서 다음 팁 보기";
  box.addEventListener("click", () => { step(); restart(); });
  restart();
}

window.setupLou = setupLou;
window.setupTips = setupTips;
})();
