#!/usr/bin/env python3
"""페이지를 그린다. **컷 하나에 한 번이 아니라, 페이지 하나에 한 번 부른다.**

붙은 컷을 따로 그리면 이음매에서 배경과 채색이 어긋나고, 호출 수도 컷 수만큼
늘어난다. 그래서 pages.group_pages 가 묶어 준 단위 그대로 한 번에 그린다.

## 그림체가 페이지마다 흔들리지 않게 하는 것

호출마다 참조 이미지를 붙인다. 순서가 곧 모델이 보는 순서다:

    1. 캐릭터 시트      — 이 인물이 누구인지. 매 페이지에 붙는다
    2. 직전 페이지       — 방금 그린 것과 같은 손으로 그리게 한다

둘째가 없으면(첫 페이지) 시트만 붙는다. webtoon-harness 의 조건 S+ 가 쓰는
순서와 같다 — 거기서 "시트만 붙이고 직전 것을 안 붙이면 같은 화 안에서
채색이 컷마다 갈린다" 를 이미 겪었다.
"""

from __future__ import annotations

import json
from pathlib import Path

import imagegen
import imageprompt
import llm
from llm import story

log, warn = story.log, story.warn

PAGE_DIR = "pages"
STAGE = "PAGE_IMAGE"


def page_path(run_dir: Path, n: int) -> Path:
    return run_dir / PAGE_DIR / f"page{n:02d}.png"


def sheet_refs(run_dir: Path) -> list[Path]:
    """매 호출에 붙일 캐릭터 시트."""
    one = run_dir / "sheet.png"
    return [one] if one.exists() else []


def build_prompts(run_dir: Path, continuous: bool = False) -> tuple[list, list[str]]:
    """(페이지 배열, 페이지마다의 프롬프트).

    시트 사양이 있으면 주인공 외형을 글로도 같이 준다 — 시트 그림이 붙어도
    "왼쪽 소매에만 노란 반사띠 두 줄" 같은 정밀한 값은 글이 더 정확하다.
    """
    pages_path = run_dir / "pages.json"
    if not pages_path.exists():
        raise SystemExit(f"{pages_path} 가 없습니다. 콘티 단계를 먼저 돌리세요.")
    pages = json.loads(pages_path.read_text(encoding="utf-8"))

    sheets, sheet_names = [], []
    spec_path = run_dir / "sheet_spec.json"
    if spec_path.exists():
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        sheets.append(imageprompt.sheet_line(spec))
        sheet_names.append(spec.get("name") or "")

    cast = []
    board_path = run_dir / "board.json"
    if board_path.exists():
        cast = (json.loads(board_path.read_text(encoding="utf-8")) or {}).get("cast") or []

    provider = llm.provider_for(STAGE)
    style = (llm.env("NH_STYLE") or llm.env("PAGE_STYLE")
             or imageprompt.DEFAULT_STYLE)
    return pages, imageprompt.page_prompts(pages, sheets=sheets, cast=cast,
                                           continuous=continuous, provider=provider,
                                           style=style, sheet_names=sheet_names)


def draw(run_dir: Path, dry_run: bool = False, only: list[int] | None = None,
         continuous: bool = False, allow_no_sheet: bool = False,
         on_page=None) -> list[dict]:
    """페이지를 순서대로 그린다. 이미 있는 페이지는 다시 안 그린다.

    **순서대로 그리는 것이 요점이다.** 직전 페이지를 참조로 붙이려면 그것이
    이미 있어야 한다. 병렬로 돌리면 그 사슬이 끊긴다 — 그래서 안 한다.

    on_page(meta) : 페이지 하나가 끝날 때마다 바로 부른다(선택). run.py 의
    record() 를 여기서 걸 수 있게 하는 자리다 — 예전에는 이 함수가 다 그린
    뒤 리스트를 통째로 돌려줘야만 비용이 기록됐는데, 그러면 중간에 취소되거나
    죽었을 때 이미 돈이 나간 앞쪽 페이지들의 기록이 통째로 사라졌다(실제로
    겪음, 2026-08-31 — 3장을 그리고 취소했는데 meta.json 에 0장으로 남음).
    """
    pages, prompts = build_prompts(run_dir, continuous=continuous)
    out_dir = run_dir / PAGE_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    sheets = sheet_refs(run_dir)
    if not sheets and not dry_run and not allow_no_sheet:
        # **경고가 아니라 멈춘다.** 시트는 인물의 기준점이고, 없으면 페이지가
        # 직전 페이지만 보고 이어 그려서 그림체와 색이 장마다 흘러간다.
        # 그렇게 나온 것은 다시 그려야 하므로 그 호출값이 통째로 낭비된다.
        # 실제로 11장을 시트 없이 그려 $0.45 를 날린 자리다.
        raise SystemExit(
            f"캐릭터 시트가 없습니다: {run_dir / 'sheet.png'}\n"
            "        시트 없이 그리면 페이지마다 다른 사람이 나옵니다.\n"
            "        먼저 --sheet 를 돌리거나, --sheet-from 으로 가져오세요.\n"
            "        정말 시트 없이 그리려면 --no-sheet 를 붙이세요.")

    made = []
    for i, (page, prompt) in enumerate(zip(pages, prompts), 1):
        if only and i not in only:
            continue
        out = page_path(run_dir, i)
        (out_dir / f"page{i:02d}.txt").write_text(prompt, encoding="utf-8")
        if dry_run:
            continue
        if out.exists():
            log(f"  페이지 {i}: 이미 있습니다 (다시 그리려면 지우세요)")
            continue

        # 직전 페이지 — **바로 앞 번호**를 본다. 건너뛰고 그렸으면 없을 수도
        # 있고, 그때는 시트만 붙는다.
        prev = page_path(run_dir, i - 1)
        refs = sheets + ([prev] if i > 1 and prev.exists() else [])

        log(f"[페이지 {i}/{len(pages)}] 컷 {len(page)}개 · 참조 {len(refs)}장 …")
        meta = imagegen.paint(STAGE, prompt, out, refs=refs, kind=imagegen.PAGE_KIND)
        meta["page"] = i
        meta["cuts"] = len(page)
        made.append(meta)
        if on_page:
            on_page(meta)
        log(f"  -> {out}")

    if dry_run:
        log(f"[페이지] 프롬프트 {len(pages)}장만 썼습니다 -> {out_dir}")
    return made
