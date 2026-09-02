/* 사용자 검수 화면의 그리기 — 방향 카드 · 콘티.
 *
 * newharness.html(실제 동작)과 demo.html(목업)이 **같은 함수를 쓴다.**
 * 목업이 손으로 베낀 마크업을 들고 있으면, 컷 칸이 하나 늘 때마다 둘이
 * 어긋난다. 여기 있는 것은 전부 "값 -> HTML 문자열"인 순수 함수다 —
 * 누르면 무엇을 하는지(고르기·승인)는 각 페이지가 붙인다. 목업에서는
 * 아무 일도 일어나지 않아야 하고, 실제 화면에서는 서버로 나가야 하므로
 * 그 부분은 공유하지 않는다.
 *
 * 스타일은 nh-review.css 에 같이 있다. */
window.NHReview = (function () {
  const esc = (s) => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");

  /* 방향 카드 하나. 장면은 접어 둔다 — 고르는 데 필요한 것은 제목·장르·
     줄거리이고, 넷을 견줄 때 장면까지 펼쳐져 있으면 한 화면에 안 들어온다. */
  function directionCardHtml(d) {
    const scenes = (d.scenes || []).map(s => `<li>${esc(s)}</li>`).join("");
    return `
      <h3>${esc(d.n)}. ${esc(d.title)} ${d.genre ? `[${esc(d.genre)}]` : ""}</h3>
      <p>${esc(d.plot)}</p>
      ${scenes ? `<details>
        <summary>장면 ${(d.scenes || []).length}개 보기</summary>
        <ul>${scenes}</ul>
      </details>` : ""}`;
  }

  /* 한 칸이 무엇인지는 흐름마다 다르다 — 콘티 흐름은 "컷"(한 장에 여럿이
     들어간다), 디테일 직행 흐름은 "사건"(하나가 그림 한 장이 된다). 세는
     것과 부르는 말이 어긋나면 검수하는 사람이 몇 장을 그리는지 못 센다. */
  function unitWord(summary) {
    return summary && summary.engine === "detail" ? "사건" : "컷";
  }

  /* 검수하는 사람이 봐야 하는 것은 대사가 아니라 "이 칸이 어떤 그림이
     되는가" 라서 카메라·배경·인물을 같이 보여준다. */
  function cutHtml(c, word) {
    const tags = [c.shot, c.angle, c.size].filter(Boolean)
      .map(t => `<span class="nh-tag">${esc(t)}</span>`).join("");
    const who = (c.characters || []).map(p => `
      <p class="nh-cut-who"><b>${esc(p.name)}</b>${p.expression ? ` · ${esc(p.expression)}` : ""}${
        p.action ? `<br>${esc(p.action)}` : ""}</p>`).join("");
    const lines = (c.dialogue || []).map(d => `
      <p class="nh-line"><i>${esc(d.speaker)}</i>“${esc(d.text)}”</p>`).join("");
    const sfx = (c.sfx || []).length
      ? `<p class="nh-line nh-sfx">효과음 ${(c.sfx || []).map(esc).join(" · ")}</p>` : "";
    return `
      <div class="nh-cut">
        <div class="nh-cut-head"><span class="nh-cut-no">${word || "컷"} ${esc(c.id)}</span>${tags}</div>
        ${c.background ? `<p class="nh-cut-bg">${esc(c.background)}</p>` : ""}
        ${who}${lines}${sfx}
      </div>`;
  }

  function castHtml(cast) {
    return (cast || [])
      .map(c => `<span title="${esc(c.appearance)}">${esc(c.name)}</span>`).join("");
  }

  function countLabel(summary) {
    if (!summary) return "";
    if (summary.engine === "direction") {
      return `장면 ${(summary.scenes || []).length}개`;
    }
    if (!summary.cut_count) return "";
    const word = unitWord(summary);
    const tail = word === "사건" ? ` (그림 ${summary.cut_count}장)` : "";
    return `장면 ${(summary.scenes || []).length}개 · ${word} ${summary.cut_count}개${tail}`;
  }

  /* engine이 "direction"이면(이어그리기 — 콘티·컷 대본이 없다) 컷 토글을
     안 그린다. 어차피 컷 칸이 전부 빈 채로 와서(background·characters·
     dialogue 없음), 펼쳐도 요약 문장만 되풀이해 보여주고 정보가 없다. */
  function simpleScenesHtml(scenes) {
    return (scenes || []).map(s => `
      <div class="nh-scene">
        <div class="nh-scene-head">장면 ${esc(s.id)}</div>
        <p class="nh-scene-sum">${esc(s.summary)}</p>
      </div>`).join("");
  }

  /* 첫 장면만 펴 둔다 — 칸이 20개를 넘는 일이 흔해서, 다 펴 두면
     "이대로 진행" 단추까지 한참 스크롤해야 한다. */
  function scenesHtml(scenes, word) {
    return (scenes || []).map((s, i) => `
      <div class="nh-scene">
        <div class="nh-scene-head">장면 ${esc(s.id)}</div>
        <p class="nh-scene-where">${[s.location, s.time].filter(Boolean).map(esc).join(" · ")}</p>
        <p class="nh-scene-sum">${esc(s.summary)}</p>
        <details ${i === 0 ? "open" : ""}>
          <summary>${word || "컷"} ${(s.cuts || []).length}개 보기</summary>
          <div>${(s.cuts || []).map(c => cutHtml(c, word)).join("")}</div>
        </details>
      </div>`).join("");
  }

  /* 콘티 검수 화면을 통째로 채운다. 세 자리(cast·개수·장면)를 한 번에
     넣으므로, 부르는 쪽은 어느 칸이 어디인지 몰라도 된다. */
  function fillBoard(summary, sel) {
    if (!summary) return;
    const ids = Object.assign(
      { cast: "#boardCast", count: "#boardCount", scenes: "#boardScenes" }, sel || {});
    const cast = document.querySelector(ids.cast);
    const count = document.querySelector(ids.count);
    const scenes = document.querySelector(ids.scenes);
    if (cast) cast.innerHTML = castHtml(summary.cast);
    if (count) count.textContent = countLabel(summary);
    if (scenes) {
      scenes.innerHTML = summary.engine === "direction"
        ? simpleScenesHtml(summary.scenes)
        : scenesHtml(summary.scenes, unitWord(summary));
    }
  }

  /* "다시 만들기" 버튼을 누르면 바로 요청을 보내지 않고, 요청 사항을 적을
     수 있는 칸을 편다 — 비워 두고 확인해도 된다(placeholder 로 안내). 이
     버튼은 다른 클릭 리스너를 따로 달지 않는다 — 요청은 항상 이 칸의
     "다시 만들기" 확인 버튼으로만 나간다.
     retryBtn 은 `.nh-approval-actions` 안에 있어야 한다(패널을 그 바로
     뒤에 붙인다). onSubmit(note) 이 실제 요청을 보내는 자리다 — 이
     함수는 UI만 맡고 네트워크 호출은 모른다(목업 페이지는 onSubmit 에서
     아무 것도 안 하면 그만이다). */
  function wireRetryNote(retryBtnId, onSubmit) {
    const btn = document.getElementById(retryBtnId);
    if (!btn) return;
    const actions = btn.closest(".nh-approval-actions") || btn.parentElement;
    const panel = document.createElement("div");
    panel.className = "nh-retry-note";
    panel.hidden = true;
    panel.innerHTML = `
      <textarea placeholder="다시 만들 때 반영할 것이 있으면 적어 주세요 (비워 두고 다시 만들기를 눌러도 됩니다)"></textarea>
      <div class="nh-retry-note-actions">
        <button type="button" class="btn btn-quiet btn-sm" data-act="cancel">취소</button>
        <button type="button" class="btn btn-primary btn-sm" data-act="confirm">다시 만들기</button>
      </div>`;
    actions.insertAdjacentElement("afterend", panel);
    const textarea = panel.querySelector("textarea");
    btn.addEventListener("click", () => {
      panel.hidden = false;
      textarea.focus();
    });
    panel.querySelector('[data-act="cancel"]').addEventListener("click", () => {
      panel.hidden = true;
    });
    panel.querySelector('[data-act="confirm"]').addEventListener("click", () => {
      const note = textarea.value;
      panel.hidden = true;
      textarea.value = "";
      onSubmit(note);
    });
  }

  return { directionCardHtml, cutHtml, castHtml, countLabel, scenesHtml,
          simpleScenesHtml, fillBoard, wireRetryNote };
})();
