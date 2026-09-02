/* 루의 상황별 그림 — 자리마다 어느 고래가 나올지 여기서 고른다.
 *
 * 루는 일부러 두 마리가 그려져 있다(design-reference 의 whale1 · whale2).
 * 같은 상황이라도 어느 쪽이 나올지 모르는 편이 살아 있는 느낌이라, 두 마리가
 * 다 그려진 자리는 화면에 뜰 때마다 하나를 뽑는다.
 *
 * 다만 원화가 두 마리 다 있는 자리만 뽑을 수 있다. 지금 그려진 것은:
 *   두 마리 다 — 오류 · 불러오는 중 · 만드는 중 · 알림
 *   whale2 만  — 빈 화면 · 길안내
 *   whale1 만  — 이야기의 네 단계(수면 · 항해 · 심해 · 완성)
 * 한 마리뿐인 자리는 후보가 하나라 늘 같은 그림이 나온다. 나중에 나머지 한
 * 마리가 그려지면 여기 배열에 한 줄 더하는 것으로 끝난다.
 *
 * 페이지 세 곳(홈 · 편집실 · 로딩 목업)이 같이 쓰므로 따로 떼어 뒀다.
 */
(function (global) {
  const A = "/static/lou/art/";

  const LOU_ART = {
    error:      [A + "error-1.png",      A + "error-2.png"],
    loading:    [A + "loading-1.png",    A + "loading-2.png"],
    generating: [A + "generating-1.png", A + "generating-2.png"],
    notice:     [A + "notice-1.png",     A + "notice-2.png"],
    empty:      [A + "empty-2.png"],
    guide:      [A + "guide-2.png"],
  };

  /* 이야기의 네 단계는 뜻이 다른 그림이라 뽑는 것이 아니다 — 수면은 수면,
     심해는 심해여야 한다. 이름으로 곧장 찾을 수 있게 같이 둔다. */
  const LOU_WORLD = {
    begins:   A + "world-begins.png",
    voyage:   A + "world-voyage.png",
    depth:    A + "world-depth.png",
    complete: A + "world-complete.png",
  };

  /* 헤더 로고 — 표정 원화에서 고래 몸통만 잘라 둔 12장(whale1 · whale2 × 6).
     홈에도 편집실에도 같은 로고가 걸리므로 여기서 함께 들고 있는다. */
  const LOU_LOGOS = ["curious", "default", "discover", "happy", "sleepy", "thinking"]
    .flatMap(e => ["/static/lou/logo-1-" + e + ".png",
                   "/static/lou/logo-2-" + e + ".png"]);

  function louLogo() {
    return LOU_LOGOS[Math.floor(Math.random() * LOU_LOGOS.length)];
  }

  function louArt(slot) {
    const list = LOU_ART[slot];
    if (!list || !list.length) return "";
    return list[Math.floor(Math.random() * list.length)];
  }

  global.LOU_ART = LOU_ART;
  global.LOU_LOGOS = LOU_LOGOS;
  global.louLogo = louLogo;
  global.LOU_WORLD = LOU_WORLD;
  global.louArt = louArt;
})(window);
