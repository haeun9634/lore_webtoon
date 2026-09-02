"""Scene 이미지들을 세로로 이어 붙여 **웹툰 1화 한 장**으로 만든다.

이 하네스는 지금까지 Scene 을 한 장씩 따로 굽고 폴더에 흩어 두었다. 보려면
HTML 뷰어를 열어야 했고, 넘겨줄 것도 PNG 여러 장이었다. 그런데 만들려는 것은
"장면 모음"이 아니라 **한 편의 웹툰**이다. 세로로 쭉 이어져서 스크롤로 읽히는
그것 하나가 결과물이어야 한다.

그래서 생성이 끝나면 채택본을 순서대로 이어 붙여 episode.png 한 장을 남긴다.
후보가 1장이면 채택 기록이 없어도 c1 이 곧 채택본이다.

## 왜 그냥 붙이기만 하는가

이음매를 코드로 보정하고 싶은 유혹이 있다 — 겹쳐서 페이드하거나, 색을 맞추거나.
하지만 그건 잘못을 감추는 것이지 고치는 것이 아니다. 이음매가 튀면 그건
**프롬프트가 앞뒤 장을 이어 그리지 못했다는 신호**이고, 그 신호는 보여야 한다.
가리면 다음에 무엇을 고쳐야 하는지 알 수 없다.

폭이 다른 장이 섞이면 가장 좁은 폭에 맞춘다. 늘리지 않는다 — 늘리면 그 장만
흐릿해져서, 원인이 생성인지 이어붙이기인지 구분할 수 없게 된다.
"""

from __future__ import annotations

import os
from pathlib import Path

import strip     # 여백 눈금(gap_ratio_table)과 가벼운 컷 폭(width_ratio)을 그대로 쓴다

EPISODE_FILE = "episode.png"

# 한 장이 너무 크면(2K x 7장 = 세로 16,800px) 뷰어와 편집기가 버거워한다.
# PNG 자체 한계(65,535px)보다 훨씬 앞에서 실용 한계가 온다.
#
# EPISODE_MAX_HEIGHT 로 올릴 수 있다 — 무게 묶음(grouping: weight)은 컷
# 대부분이 자기 장을 가져서 12컷이면 12장 × 2752px = 33,024px 로 이 상한을
# 넘는다. 안 열어 두면 그 모드는 그림을 다 그려 놓고 마지막 합치기에서 항상
# 죽는다. 기본값은 그대로라 이 값을 안 준 실행은 예전과 똑같다.
try:
    MAX_HEIGHT = int(os.environ.get("EPISODE_MAX_HEIGHT", "") or 30000)
except ValueError:
    MAX_HEIGHT = 30000


class StitchError(RuntimeError):
    """이어 붙이기 실패. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


def episode_path(ep_dir: Path) -> Path:
    return ep_dir / EPISODE_FILE


def pick_paths(ep_dir: Path, conditions: list[str], numbers: list[int],
               picks: dict[tuple[str, int], int]) -> tuple[str, list[Path]]:
    """어느 조건의 그림으로 1화를 만들 것인가 + 그 파일 목록.

    조건을 고르는 이유: --sheet-only 는 config 의 조건을 전부 훑으므로 첫 번째가
    A(첨부 없음, 폴더도 없음)일 수 있다. 실제로 뽑아 둔 것을 붙여야 하므로
    **이미지가 가장 많이 있는 조건**을 고른다. 같으면 앞의 것.

    후보 번호는 picks.csv 를 보고, 기록이 없거나 그 파일이 없으면 c1 을 쓴다 —
    후보가 1장이면 채택이라는 말 자체가 성립하지 않기 때문이다.
    """
    best_cond, best_paths, best_hits = "", [], -1
    for cond in conditions:
        paths = []
        for n in numbers:
            k = picks.get((cond, n)) or 1
            p = ep_dir / cond / f"scene{n}_c{k}.png"
            if not p.exists() and k != 1:
                p = ep_dir / cond / f"scene{n}_c1.png"
            paths.append(p)
        hits = sum(1 for p in paths if p.exists())
        if hits > best_hits:
            best_cond, best_paths, best_hits = cond, paths, hits
    return best_cond, best_paths


def stitch(paths: list[Path], out: Path,
          gaps: list[int] | None = None, ratios: list[float] | None = None,
          gap_table: dict[int, float] | None = None) -> tuple[int, int]:
    """세로로 이어 붙여 한 장으로 저장한다. (가로, 세로) 를 돌려준다.

    **장(Scene) 안**은 틈 없이 이어진다 — 그 안의 컷들은 한 호출에서 함께
    구워지므로, 이음매를 코드로 메우면 잘못을 감추는 것이지 고치는 것이 아니다.
    이음매가 튀면 그건 프롬프트가 앞뒤 컷을 이어 그리지 못했다는 신호이고, 그
    신호는 보여야 한다.

    **장과 장 사이**는 다르다. `grouping: weight` 에서는 무거운 컷(bleed·impact)
    이 혼자 한 장을 이루므로, 그 장은 컷 모드의 컷 하나와 다를 것이 없다 —
    그런데 이 함수가 예전처럼 장끼리 무조건 붙여 버리면, 컷 모드에서는 지키는
    gap_after 의 리듬(붙임 · 보통 · 길게 · 낙차)이 장 모드에서만 사라진다.

    gaps: 각 장 **뒤**의 gap_after(0~3). 없으면(None) 전부 0 으로 봐서
          예전처럼 틈 없이 붙는다 — 옛 호출부는 안 건드려도 그대로 돈다.
    ratios: 각 장이 지면 폭을 얼마나 쓸까(0~1). 없으면 전부 1.0(꽉 채움).
    gap_table: strip.gap_ratio_table() 이 돌려주는 눈금표. 없으면 strip 의
               기본값(GAP_RATIO)을 쓴다.

    picks·paths 는 컷 모드의 write_strip 과 자리를 맞춰 왔다 — 여백·폭 계산도
    strip.gap_px / strip.width_ratio 를 그대로 써서, 같은 gap_after=2 가 컷
    모드와 장 모드에서 다른 px 로 벌어지는 일이 없게 한다.
    """
    try:
        from PIL import Image
    except ImportError as exc:      # pragma: no cover - 환경 문제
        raise StitchError(
            "Pillow 가 없어 1화를 이어 붙일 수 없습니다.\n"
            "        pip install Pillow") from exc

    n = len(paths)
    gaps = gaps if gaps is not None else [0] * n
    ratios = ratios if ratios is not None else [1.0] * n
    if len(gaps) != n or len(ratios) != n:
        raise StitchError("gaps/ratios 의 길이가 paths 와 다릅니다 (코드 버그).")

    rows = [(p, g, r) for p, g, r in zip(paths, gaps, ratios) if p.exists()]
    if not rows:
        raise StitchError("이어 붙일 이미지가 하나도 없습니다.")

    images = []
    try:
        for p, gap, ratio in rows:
            im = Image.open(p)
            im.load()
            images.append((im.convert("RGB"), gap, ratio))
    except OSError as exc:
        raise StitchError(f"이미지를 읽지 못했습니다: {exc}") from exc

    # 지면 폭은 ratio == 1.0(꽉 채우는 장) 중 가장 좁은 것이 정한다. strip.py 의
    # stitch_strip 과 같은 규칙이다 — 가벼운 장 하나가 화면 전체를 좁히면 안 된다.
    full = [im.width for im, _g, r in images if r >= 0.999]
    width = min(full) if full else min(im.width for im, _g, _r in images)

    table = gap_table or strip.GAP_RATIO
    placed = []
    for im, gap, ratio in images:
        target = width if ratio >= 0.999 else max(1, round(width * ratio))
        w = min(im.width, target)       # 늘리지 않는다 — 늘리면 그 장만 흐려진다
        if w != im.width:
            im = im.resize((w, max(1, round(im.height * w / im.width))),
                           Image.LANCZOS)
        placed.append((im, strip.gap_px(width, gap, table), w))

    total = sum(im.height + g for im, g, _w in placed)
    total -= placed[-1][1]              # 마지막 뒤 여백은 읽히지 않는다
    if total > MAX_HEIGHT:
        raise StitchError(
            f"이어 붙이면 세로 {total:,}px 입니다 (상한 {MAX_HEIGHT:,}px).\n"
            f"        Scene 을 줄이거나 provider.options.image_size 를 낮추세요.")

    sheet = Image.new("RGB", (width, total), (255, 255, 255))
    y = 0
    for i, (im, gap, w) in enumerate(placed):
        x = (width - w) // 2            # 지면보다 좁은 장은 가운데 정렬
        sheet.paste(im, (x, y))
        y += im.height + (gap if i < len(placed) - 1 else 0)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return width, total
