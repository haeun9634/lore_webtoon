#!/usr/bin/env python3
"""페이지 낱장을 위아래로 이어 붙여 한 장(episode.png)으로 만든다.

**말풍선 편집은 안 한다.** new_harness 는 지금 대사를 이미지 모델이 픽셀에
직접 그려 넣는다 — webtoon-harness 처럼 말풍선 자리를 비워 두고 편집기가
글자를 얹는 방식이 아니다. 그래서 여기서 만드는 episode.png 는 "그려진 그대로
이어 붙인 결과"이고, 나중에 대사를 옮기거나 고칠 수 없다. 그게 필요해지면
이 파일이 아니라 new_harness 자체(콘티→이미지 프롬프트 단계)에 말풍선 자리를
비우는 절을 새로 넣어야 한다 — 지금은 그 작업을 안 하기로 했다.

**페이지 사이 여백·폭은 webtoon-harness 것을 그대로 쓴다.** 픽셀 계산
(`strip.gap_px`/`strip.width_ratio`)을 새로 만들지 않는다 — 다만 여백
**단계**(0~3)를 매기는 기준은 다르다. story-harness 의 `derive_layout`은
컷의 beat·transition·render_style 로 매기는데 new_harness 콘티에는 그
필드가 없다. 대신 `pages.page_gap_after`가 있는 것(linked·size·location)
으로 같은 취지를 낸다 — `pages.py`의 그 함수 docstring 참고.

`pages.json`이 있고 페이지 수가 맞으면 여백·폭을 계산해서 넣고, 없거나
안 맞으면(옛 run, 손으로 만든 페이지 등) **예전처럼** 여백 없이 가운데
정렬만 한다 — 새 계산이 안 되는 자리에서 멈추지 않는다.

폭이 페이지마다 다르면(캔버스 설정을 바꿔 가며 그린 run 등) 가장 넓은 폭에
맞춰 나머지를 가운데 정렬한다 — 자르거나 늘리지 않는다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
WEBTOON_HARNESS = HERE.parent / "webtoon-harness"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(WEBTOON_HARNESS) not in sys.path:
    sys.path.append(str(WEBTOON_HARNESS))     # append, 안 insert(0,...) — new_harness
                                               # 자신의 모듈(run.py 등 이름이 겹치는
                                               # 것)을 가리면 안 된다

import pages as pagemod  # noqa: E402  (sys.path 를 세운 뒤에야 import 할 수 있다)
import strip              # noqa: E402  (webtoon-harness 의 gap_px/width_ratio 를 빌린다)

PAGE_GLOB = "page*.png"
OUT_NAME = "episode.png"


def page_files(run_dir: Path) -> list[Path]:
    """pages/pageNN.png 를 번호 순서로. 번호를 못 읽는 파일은 뺀다."""
    pages_dir = run_dir / "pages"
    files = []
    for p in pages_dir.glob(PAGE_GLOB):
        digits = "".join(c for c in p.stem if c.isdigit())
        if digits:
            files.append((int(digits), p))
    return [p for _, p in sorted(files)]


def load_pages(run_dir: Path) -> list | None:
    """pages.json (컷 배열의 배열). 없거나 읽을 수 없으면 None."""
    path = run_dir / "pages.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, list) else None


def page_rhythm(pages_data: list | None, count: int) -> tuple[list[int], list[float]]:
    """pages.json -> (여백 단계 목록, 폭 비율 목록). 못 쓰면 예전 그대로(0, 1.0)."""
    if not pages_data or len(pages_data) != count:
        return [0] * count, [1.0] * count
    gaps = [0] + [pagemod.page_gap_after(pages_data[i - 1], pages_data[i])
                  for i in range(1, count)]
    ratios = [strip.width_ratio({"weight": pagemod.page_weight(pg)}) for pg in pages_data]
    return gaps, ratios


def stitch(run_dir: Path, out_path: Path | None = None) -> Path:
    """run_dir/pages/page*.png 를 위아래로 이어 붙여 저장한다. (결과 경로)"""
    files = page_files(run_dir)
    if not files:
        raise SystemExit(f"{run_dir / 'pages'} 에 이어 붙일 페이지가 없습니다.")

    images = [Image.open(p).convert("RGB") for p in files]
    width = max(im.width for im in images)
    gap_levels, ratios = page_rhythm(load_pages(run_dir), len(images))
    gtab = strip.gap_ratio_table()
    gaps_px = [strip.gap_px(width, lv, gtab) for lv in gap_levels]

    placed = []
    for im, ratio in zip(images, ratios):
        target = width if ratio >= 0.999 else max(1, round(width * ratio))
        w = min(im.width, target)          # 늘리지 않는다 — 늘리면 그 페이지만 흐려진다
        if w != im.width:
            im = im.resize((w, max(1, round(im.height * w / im.width))), Image.LANCZOS)
        placed.append((im, w))

    total_height = sum(im.height for im, _w in placed) + sum(gaps_px)

    canvas = Image.new("RGB", (width, total_height), "white")
    y = 0
    for i, (im, w) in enumerate(placed):
        y += gaps_px[i]
        x = (width - w) // 2               # 지면보다 좁은 페이지는 가운데 정렬
        canvas.paste(im, (x, y))
        y += im.height

    out_path = out_path or (run_dir / OUT_NAME)
    canvas.save(out_path)
    return out_path


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="페이지를 이어 붙여 episode.png 를 만든다.")
    ap.add_argument("--run-id", required=True, help="new_harness/runs/<run-id>")
    args = ap.parse_args(argv)

    run_dir = Path(__file__).resolve().parent / "runs" / args.run_id
    if not run_dir.exists():
        raise SystemExit(f"그런 run 이 없습니다: {run_dir}")

    out = stitch(run_dir)
    files = page_files(run_dir)
    print(f"[이어붙이기] {len(files)}장 -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
