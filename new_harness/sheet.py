#!/usr/bin/env python3
"""캐릭터 시트 — 사양(JSON) 검사와 이미지 프롬프트, 그리고 실제 그리기.

이미지 호출 자체는 story-harness/story.py 의 make_sheet_painter 를 그대로 쓴다
(컷을 그리는 코드와 같은 경로다). 여기서 새로 짜는 것은 **무엇을 그릴지**뿐이다.

story.py 의 시트와 다른 점은 하나, 소지품(props) 영역이 있다는 것이다. 그래서
공통 지시도 여기 따로 둔다 — story.py 의 SHEET_COMMON_EN 은 "no props" 라고
못 박고 있어서 그대로 쓰면 소지품 영역이 지워진다.
"""

from __future__ import annotations

import json
import shutil
import re
from pathlib import Path

import imagegen
import imageprompt
import llm
from llm import story

PALETTE_KEYS = story.PALETTE_KEYS            # hair eyes skin outfit_main outfit_sub accent
EXPRESSION_COUNT = story.EXPRESSION_COUNT    # 6
DETAIL_MIN, DETAIL_MAX = story.DESIGN_DETAIL_MIN, story.DESIGN_DETAIL_MAX
HANGUL_RE = story.HANGUL_RE
HEX_RE = story.HEX_RE

MAX_PROPS = 4

COMMON_EN = (
    "Character reference sheet for a Korean webtoon production. "
    "Flat even lighting, pure white background (#FFFFFF), no cast shadows, "
    "no text, no labels, no watermark, no logo, no signature. "
    "Clean line art with flat colors. The character is identical in every "
    "figure on the sheet."
)


def _numbered(items) -> str:
    return "\n".join(f"  {i}. {x}" for i, x in enumerate(items, 1))


def parse_spec(text: str) -> dict:
    """모델 응답에서 사양 JSON 을 꺼내 모양을 맞춘다."""
    obj = story.extract_json(text)
    if not isinstance(obj, dict):
        raise story.ParseFailure("시트 사양이 JSON 객체가 아닙니다.")
    palette = obj.get("color_palette") if isinstance(obj.get("color_palette"), dict) else {}
    return {
        "name": str(obj.get("name") or "").strip(),
        "species": str(obj.get("species") or "").strip(),
        "species_en": str(obj.get("species_en") or "").strip(),
        "appearance_en": str(obj.get("appearance_en") or "").strip(),
        "design_details": [str(d).strip() for d in (obj.get("design_details") or [])
                           if str(d or "").strip()],
        "props": [str(p).strip() for p in (obj.get("props") or []) if str(p or "").strip()],
        "color_palette": {k: str(palette.get(k) or "").strip() for k in PALETTE_KEYS},
        "expression_set": [str(e).strip() for e in (obj.get("expression_set") or [])
                           if str(e or "").strip()],
    }


def gate_spec(spec: dict) -> list[str]:
    """그리기 전에 사양이 실제로 있는지 본다.

    사양 없이 이미지를 부르면 빈칸을 모델이 학습 데이터 평균값으로 채운다.
    그렇게 나온 시트는 "컷마다 다른 사람" 을 막지 못한다 — 돈만 쓰고 끝난다.
    """
    bad = []
    if not spec["name"]:
        bad.append("name 이 비어 있습니다.")

    if not spec["appearance_en"]:
        bad.append("appearance_en 이 없습니다. 이미지 프롬프트의 본문입니다.")
    elif HANGUL_RE.search(spec["appearance_en"]):
        bad.append("appearance_en 에 한글이 섞여 있습니다. 이미지 모델에 그대로 들어갑니다.")

    # species 가 비어 있으면 통과시킨다 — 새 입력 필드라, 이 칸이 없던 예전
    # 사양(및 이 필드를 안 채운 모델 응답)까지 여기서 막으면 예전처럼 돌던
    # 것이 갑자기 멈춘다. species 를 채웠을 때만 사람으로 뭉개지지 않았는지
    # 검사한다.
    species = spec.get("species", "")
    species_en = spec.get("species_en", "")
    if species and species != "사람":
        if not species_en:
            bad.append(f"species가 '{species}'인데 species_en이 없습니다. "
                       "appearance_en 을 종으로 시작하게 할 근거가 없습니다.")
        elif spec["appearance_en"] and species_en.lower() not in spec["appearance_en"].lower():
            bad.append(f"species가 '{species}'({species_en})인데 appearance_en 에 "
                       f"'{species_en}'이 없습니다 — 사람으로 뭉개졌을 수 있습니다.")

    n = len(spec["design_details"])
    if not DETAIL_MIN <= n <= DETAIL_MAX:
        bad.append(f"design_details 가 {n}개입니다 ({DETAIL_MIN}~{DETAIL_MAX}개). "
                   "고정 요소가 없으면 시트를 뽑아도 컷마다 다른 사람이 됩니다.")

    if len(spec["props"]) > MAX_PROPS:
        bad.append(f"props 가 {len(spec['props'])}개입니다 (최대 {MAX_PROPS}개). "
                   "많을수록 한 장 안에서 서로를 뭉갭니다.")

    if len(spec["expression_set"]) != EXPRESSION_COUNT:
        bad.append(f"expression_set 이 {len(spec['expression_set'])}개입니다 "
                   f"(정확히 {EXPRESSION_COUNT}개). 표정 시트는 이 목록을 그대로 그립니다.")

    empty = [k for k in PALETTE_KEYS if not spec["color_palette"].get(k)]
    if empty:
        bad.append(f"color_palette 의 {empty} 가 비어 있습니다.")
    else:
        no_hex = [k for k in PALETTE_KEYS if not HEX_RE.search(spec["color_palette"][k])]
        if no_hex:
            bad.append(f"color_palette 의 {no_hex} 에 #RRGGBB 가 없습니다. "
                       "hex 가 없으면 컷마다 색이 달라집니다.")
    return bad


def build_prompt(spec: dict, style: str = None) -> str:
    """사양 -> 이미지 프롬프트 한 장.

    영역을 말로만 나누면 모델이 섞어 버린다. 그래서 자리(위·가운데·아래)와
    "영역 사이에 여백" 을 못 박고, 각 영역의 개수까지 숫자로 준다.

    한국어 사양(design_details·props·expression_set)은 번역하지 않고 그대로
    싣는다. "왼쪽 소매의 노란 반사띠" 를 "yellow stripe" 로 옮기면 위치가
    사라져서 고정 요소가 고정이 아니게 된다.
    """
    palette = spec["color_palette"]
    color_line = " / ".join(f"{k}: {palette[k]}" for k in PALETTE_KEYS if palette.get(k))
    n_details = len(spec["design_details"])
    props = spec["props"]

    parts = [
        COMMON_EN,
        "",
        "[CHARACTER SHEET — ONE PAGE, SEPARATE REGIONS]",
        "A single landscape sheet holding the regions below, stacked with clear empty "
        "white space between them so each region reads as its own block. "
        "No frames, no borders, no captions, no labels.",
        "",
        "REGION 1 — TOP BAND: turnaround.",
        "  The SAME character four times in one horizontal row, left to right:",
        "  (1) front view  (2) three-quarter view  (3) side view  (4) back view.",
        "  Full body, standing at attention, arms relaxed at the sides, feet together,",
        "  neutral expression, camera at eye level.",
        "  All four stand on one shared ground line with exactly the same height and the",
        "  same proportions. The outfit, hair length and body type do not change between",
        "  views. The character carries nothing in these four figures.",
        "",
        f"REGION 2 — MIDDLE BAND: {EXPRESSION_COUNT} expressions.",
        f"  The SAME character's head and shoulders {EXPRESSION_COUNT} times in one",
        "  horizontal row, evenly spaced, all the same size, all facing the camera at the",
        "  same angle. Only the expression changes; face shape, hairstyle and hair length",
        "  are identical in all of them.",
        "",
        f"REGION 3 — BOTTOM LEFT: {n_details} close-up insets, one per fixed design "
        "element, each showing only that element, enlarged.",
    ]

    if props:
        parts += [
            "",
            f"REGION 4 — BOTTOM MIDDLE: {len(props)} carried items, drawn on their own as "
            "separate objects laid out in a row, not held by the character and with no "
            "character in this region. Each item is drawn from the angle that reads best, "
            "at a size that makes its material and wear visible.",
            "",
            "REGION 5 — BOTTOM RIGHT: one horizontal row of flat color swatch chips, one "
            "chip per palette entry, in the listed order.",
        ]
    else:
        parts += [
            "",
            "REGION 4 — BOTTOM RIGHT: one horizontal row of flat color swatch chips, one "
            "chip per palette entry, in the listed order.",
        ]

    parts += [
        "",
        f"CHARACTER\n{spec['appearance_en']}",
        "",
        f"COLOR PALETTE (use exactly these, and these are the chips in the swatch row)\n"
        f"{color_line}",
        "",
        "FIXED DESIGN ELEMENTS — visible and identical everywhere on the sheet, and one "
        "inset each in region 3. Written in Korean; follow them literally:",
        _numbered(spec["design_details"]),
    ]

    if props:
        parts += [
            "",
            "CARRIED ITEMS to draw as separate objects. Written in Korean; the size, "
            "material and wear described are what to draw:",
            _numbered(props),
        ]

    parts += [
        "",
        "EXPRESSIONS for region 2, left to right. Written in Korean; the part after the "
        "dash describes exactly what to draw:",
        _numbered(spec["expression_set"]),
    ]

    # **페이지와 같은 그림체 파일을 읽는다.** 여기가 갈라져 있으면 시트가
    # 다른 그림체로 그려지고, 그 시트가 매 페이지에 참조로 붙어서 페이지
    # 프롬프트의 그림체를 이긴다 (OpenAI 는 참조가 붙으면 편집 쪽으로 가서
    # 눈앞의 그림을 더 세게 따른다). 실제로 그래서 frost 를 넣고도 시트의
    # webtoon 그림체가 8장 내내 나왔다.
    if style is None:
        style = imageprompt.load_style(
            llm.env("NH_STYLE") or llm.env("PAGE_STYLE") or "")
    return "\n".join(parts) + f"\n\nSTYLE\n{style}\n"


def import_sheet(run_dir: Path, source: Path) -> dict:
    """이미 뽑아 둔 캐릭터 시트를 이 run 으로 가져온다. 호출 0회, 0원.

    시트 한 장이 제일 비싼 호출인데, 같은 인물로 다시 뽑을 때마다 새로 그리면
    돈도 쓰고 **인물도 조금씩 달라진다.** 이미 사람이 보고 채택한 시트가 있으면
    그것을 그대로 쓰는 쪽이 싸고 정확하다.

    source 로 받는 것:
      - story-harness 의 run 폴더  (p1.json + charsheet/sheet_c1.png)
      - new_harness 의 run 폴더    (sheet_spec.json + sheet.png)
      - 시트 png 하나              (사양 없이 그림만)
    """
    source = Path(source)
    if not source.exists():
        raise SystemExit(f"가져올 시트가 없습니다: {source}")

    png, spec = None, None
    if source.is_file():
        png = source
    else:
        # new_harness 쪽이 먼저다 — 우리 형식이라 그대로 쓴다.
        here = source / "sheet.png"
        spec_path = source / "sheet_spec.json"
        if here.exists():
            png = here
        if spec_path.exists():
            spec = json.loads(spec_path.read_text(encoding="utf-8"))

        if png is None:
            # story-harness 쪽. 사람이 채택한 후보를 따라간다.
            sheet_dir = source / "charsheet"
            picks = sheet_dir / "charsheet_picks.json"
            name = "sheet_c1.png"
            if picks.exists():
                chosen = (json.loads(picks.read_text(encoding="utf-8"))
                          .get("picks") or {}).get("sheet")
                name = chosen or name
            cand = sheet_dir / name
            if cand.exists():
                png = cand
        if spec is None:
            p1 = source / "p1.json"
            if p1.exists():
                spec = from_p1(json.loads(p1.read_text(encoding="utf-8")))

    if png is None:
        raise SystemExit(
            f"{source} 에서 시트 그림을 찾지 못했습니다.\n"
            "        story-harness run 이면 charsheet/sheet_c1.png 가, "
            "new_harness run 이면 sheet.png 가 있어야 합니다.")

    run_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(png, run_dir / "sheet.png")
    out = {"from": str(png), "spec": False}

    if spec is not None:
        bad = gate_spec(spec)
        if bad:
            # 그림은 이미 있으니 멈추지 않는다. 사양만 안 쓴다 — 모자란 사양을
            # 프롬프트에 실으면 그 빈칸을 모델이 지어낸다.
            story.warn(f"가져온 사양이 모자라 사양은 안 씁니다 ({'; '.join(bad)})")
        else:
            (run_dir / "sheet_spec.json").write_text(
                json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
            out["spec"] = True
            out["name"] = spec["name"]
    return out


def from_p1(p1: dict) -> dict:
    """story-harness 의 p1.json -> 우리 사양.

    story.charsheet_source 가 이미 같은 칸을 뽑아 준다. props 만 우리 쪽에
    새로 생긴 칸이라 비워 둔다 — 없는 것을 지어내지 않는다.
    """
    src = story.charsheet_source(p1)
    return {
        "name": src["name"],
        "appearance_en": src["appearance_en"],
        "design_details": src["design_details"],
        "props": [],
        "color_palette": dict(src["color_palette"]),
        "expression_set": src["expression_set"],
    }


def paint(prompt: str, out_path: Path, photos=None,
          provider: str = None, model: str = None, quality: str = None) -> dict:
    """시트 한 장을 그려 저장한다. (meta)

    모델은 .env 의 SHEET_IMAGE_PROVIDER / SHEET_IMAGE_MODEL 을 본다 — 다른
    단계와 같은 규칙이다 (llm.py 참고). 올린 사진을 참조로 같이 붙인다:
    글로 못 옮기는 인상은 사진이, "왼쪽 소매에만 노란 반사띠 두 줄" 같은
    정밀한 디테일은 사양이 맡는다.
    """
    return imagegen.paint("SHEET_IMAGE", prompt, out_path, refs=photos,
                          kind=imagegen.SHEET_KIND)
