# -*- coding: utf-8 -*-
"""워터마크 검사 — pytest 아님. 그냥 돌리면 마지막 줄에 ALL PASS 가 찍힌다.

    cd landing && python test_watermark.py

여기서 지키려는 것은 넷이다.

1. **원본을 안 건드린다.** 표시는 내보낼 때만 붙는 것이라, 저장물이 한 바이트도
   안 바뀌어야 한다. 이게 깨지면 다시 구울 때마다 표시가 겹쳐 찍힌다.
2. **캐시가 원본을 따라온다.** 그림을 다시 그렸는데 예전 표시본이 나가면
   사용자는 안 고쳐진 줄 안다.
3. **실패해도 내려받기는 된다.** 표시는 있으면 좋은 것이지, 없다고 파일을 못
   주는 것이 아니다.
4. **세로로 아주 긴 그림에서도** 띠와 마크가 제 크기로 들어간다.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from PIL import Image                      # noqa: E402

import watermark                           # noqa: E402

FAILED: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if cond else 'FAIL'}  {label}{'  — ' + detail if detail and not cond else ''}")
    if not cond:
        FAILED.append(label)


def make(path: Path, w: int, h: int, color=(120, 170, 200)) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (w, h), color).save(path)
    return path


def test_stamp_grows_and_keeps_width(tmp: Path) -> None:
    print("표시를 얹으면 폭은 그대로, 높이는 띠만큼 늘어난다")
    src = make(tmp / "a.png", 800, 1200)
    out = watermark.stamp(src, tmp / "out" / "a_wm.png", "초롱 · 1화")
    got = Image.open(out)
    check("폭은 안 변한다", got.width == 800, f"{got.width}")
    band = watermark._fit(800 * watermark.BAND_RATIO,
                          watermark.BAND_MIN, watermark.BAND_MAX)
    check("높이는 띠 높이만큼 는다", got.height == 1200 + band,
          f"{got.height} != {1200 + band}")


def test_source_untouched(tmp: Path) -> None:
    print("원본은 한 바이트도 안 바뀐다")
    src = make(tmp / "b.png", 600, 900)
    before = src.read_bytes()
    watermark.stamp(src, tmp / "out" / "b_wm.png")
    check("원본 그대로", src.read_bytes() == before)


def test_cache_follows_source(tmp: Path) -> None:
    print("캐시는 원본이 새로 그려지면 다시 만든다")
    root = tmp / "ep"
    src = make(root / "episode.png", 500, 700, (200, 120, 120))
    first = watermark.for_download(src, root, "초롱 · 1화")
    check("캐시 폴더에 생긴다", first.parent.name == watermark.CACHE_DIR, str(first))
    stamp1 = first.stat().st_mtime

    again = watermark.for_download(src, root, "초롱 · 1화")
    check("안 바뀌었으면 다시 안 그린다",
          again == first and again.stat().st_mtime == stamp1)

    # 원본을 다시 그린다 — 크기까지 바꿔서 눈으로도 구분되게
    make(root / "episode.png", 500, 1100, (120, 200, 140))
    import os
    os.utime(src, (stamp1 + 10, stamp1 + 10))
    third = watermark.for_download(src, root, "초롱 · 1화")
    band = watermark._fit(500 * watermark.BAND_RATIO,
                          watermark.BAND_MIN, watermark.BAND_MAX)
    check("원본이 새것이면 다시 그린다",
          Image.open(third).height == 1100 + band, str(Image.open(third).size))


def test_falls_back_to_source(tmp: Path) -> None:
    print("표시를 못 붙여도 내려받기는 된다")
    root = tmp / "broken"
    root.mkdir(parents=True, exist_ok=True)
    bad = root / "episode.png"
    bad.write_bytes("이건 그림이 아니다".encode("utf-8"))
    got = watermark.for_download(bad, root, "초롱 · 1화")
    check("원본 경로를 그대로 돌려준다", got == bad, str(got))

    gone = root / "없는파일.png"
    check("없는 파일도 그대로 돌려준다",
          watermark.for_download(gone, root) == gone)

    watermark.ENABLED = False
    try:
        src = make(root / "c.png", 400, 400)
        check("꺼 두면 원본 그대로", watermark.for_download(src, root) == src)
    finally:
        watermark.ENABLED = True


def test_tall_strip(tmp: Path) -> None:
    print("세로로 아주 긴 한 편에서도 띠가 제 크기로 들어간다")
    src = make(tmp / "tall.png", 900, 24000)
    out = watermark.stamp(src, tmp / "out" / "tall_wm.png", "초롱 · 1화")
    got = Image.open(out)
    band = got.height - 24000
    check("띠 높이는 상한을 안 넘는다", band <= watermark.BAND_MAX, str(band))
    check("띠 높이는 하한을 넘는다", band >= watermark.BAND_MIN, str(band))
    # 띠는 종이색 바탕이라, 그림(파랑)과 확실히 달라야 눈에 띈다
    check("띠가 실제로 밝게 그려졌다",
          got.getpixel((5, got.height - 3))[0] > 200,
          str(got.getpixel((5, got.height - 3))))


def test_caption_too_long_is_dropped(tmp: Path) -> None:
    print("작품 이름이 너무 길면 겹치는 대신 뺀다")
    src = make(tmp / "d.png", 420, 500)
    out = watermark.stamp(src, tmp / "out" / "d_wm.png", "아" * 200)
    check("그래도 그려진다", Image.open(out).width == 420)


def test_cut_layout_matches_stitch_rules(tmp: Path) -> None:
    print("cut_layout() 은 episode.py.stitch() 와 같은 자리에 컷을 놓는다")
    # 800폭 꽉채움 두 장 + 가벼운(0.55배) 한 장. 세 번째는 원본이 더 넓어서
    # (1000px) 줄어드는 경우까지 같이 본다.
    a = make(tmp / "a.png", 800, 400)
    b = make(tmp / "b.png", 800, 300)
    c = make(tmp / "c.png", 1000, 200)
    # gaps[i] 는 그 컷 "뒤"(다음 컷과의 사이)의 gap_after 다 — episode.py.stitch()
    # 와 같은 규칙. 그래서 컷0·1 사이를 벌리려면 gaps[0] 을 준다.
    bounds = watermark.cut_layout(
        [a, b, c], gaps=[2, 0, 0], ratios=[1.0, 1.0, 0.55],
        gap_table={0: 0.0, 1: 0.07, 2: 0.26, 3: 0.62})
    check("컷 3개 다 나온다", bounds is not None and len(bounds) == 3, str(bounds))
    (x0, y0, w0, h0), (x1, y1, w1, h1), (x2, y2, w2, h2) = bounds
    check("첫 컷은 맨 위, 왼쪽 끝", (x0, y0) == (0, 0), str((x0, y0)))
    check("꽉채움 컷은 지면 폭 그대로", (w0, h0) == (800, 400), str((w0, h0)))
    gap = watermark._strip.gap_px(800, 2, {0: 0.0, 1: 0.07, 2: 0.26, 3: 0.62})
    check("둘째 컷은 첫 컷 높이 + gap_after 만큼 내려간다",
          y1 == 400 + gap, f"{y1} != {400 + gap}")
    check("가벼운 컷은 0.55배로 줄고 가운데 정렬", w2 == 440 and x2 == (800 - 440) // 2,
          str((x2, w2)))
    check("더 넓은 원본은 지면 폭까지만 줄지 늘지 않는다", w0 <= 800 and w1 <= 800)


def test_percut_marks_land_inside_each_cut(tmp: Path) -> None:
    print("cut_bounds 를 주면 컷마다 표시가 찍힌다 (한 장 전체에 하나가 아니라)")
    src = make(tmp / "ep.png", 800, 1000)
    # 위 500 / 아래 500 두 컷으로 가정하고 각각 자리를 준다.
    bounds = [(0, 0, 800, 500), (0, 500, 800, 500)]
    out = watermark.stamp(src, tmp / "out" / "ep_wm.png", "초롱 · 1화",
                           cut_bounds=bounds)
    got = Image.open(out).convert("RGB")
    bg = (120, 170, 200)

    def has_mark(x0: int, y0: int, x1: int, y1: int) -> bool:
        # 글자는 빈틈이 있어 한 점만 찍으면 운이 나쁘면 그 사이를 짚는다 —
        # 모서리 상자를 훑어서 배경과 다른 픽셀이 하나라도 있는지 본다.
        return any(got.getpixel((x, y)) != bg
                   for x in range(x0, x1, 3) for y in range(y0, y1, 3))

    check("첫 컷 자기 자리 안(오른쪽 아래)에 표시가 찍힌다",
          has_mark(650, 420, 800, 500))
    check("둘째 컷 자기 자리 안에도 따로 찍힌다",
          has_mark(650, 920, 800, 1000))
    check("표시가 컷 경계를 넘어가진 않는다 (첫 컷 아래쪽엔 없다)",
          not has_mark(650, 500, 800, 560))


def test_percut_cache_file_differs_from_whole_mark(tmp: Path) -> None:
    print("컷별 표시는 예전(한 장짜리) 캐시와 다른 파일로 떨어진다")
    root = tmp / "ep"
    src = make(root / "episode.png", 800, 1000)
    whole = watermark.for_download(src, root, "초롱 · 1화")
    percut = watermark.for_download(
        src, root, "초롱 · 1화", cut_bounds=[(0, 0, 800, 500), (0, 500, 800, 500)])
    check("서로 다른 캐시 파일에 떨어진다", whole != percut, f"{whole} == {percut}")


def test_percut_bad_bounds_falls_back(tmp: Path) -> None:
    print("컷 자리가 이상하면(캔버스 밖 등) 한 장짜리 마크로 돌아간다")
    src = make(tmp / "e.png", 400, 400)
    out = watermark.stamp(src, tmp / "out" / "e_wm.png",
                           cut_bounds=[(0, 0, 9999, 9999)])
    check("그래도 그려진다", Image.open(out).size == (400, 400 + watermark._fit(
        400 * watermark.BAND_RATIO, watermark.BAND_MIN, watermark.BAND_MAX)))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="wm-test-"))
    try:
        for fn in (test_stamp_grows_and_keeps_width, test_source_untouched,
                   test_cache_follows_source, test_falls_back_to_source,
                   test_tall_strip, test_caption_too_long_is_dropped,
                   test_cut_layout_matches_stitch_rules,
                   test_percut_marks_land_inside_each_cut,
                   test_percut_cache_file_differs_from_whole_mark,
                   test_percut_bad_bounds_falls_back):
            fn(tmp / fn.__name__)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if FAILED:
        print("\nFAILED: " + ", ".join(FAILED))
        return 1
    print("\nALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
