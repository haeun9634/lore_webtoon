"""story-harness 가 만든 캐릭터 시트를 읽어 온다.

지금까지 캐릭터 외형은 두 군데에 손으로 있었다: config.yaml 의
character_appearance 와 refs/turnaround.png. 둘 다 사람이 채워 넣는 것이라
스토리 쪽 설정이 바뀌면 조용히 어긋났다. story-harness 가 캐릭터 시트를
만들게 되면서 그 두 가지가 run 폴더 안에 생긴다:

  runs/<run_id>/p1.json         appearance_en / design_details /
                                color_palette / expression_set
  runs/<run_id>/charsheet/      채택된 시트 3장 (turnaround / expressions / details)
  runs/<run_id>/charsheet_picks.json, meta.json   어느 것이 채택됐는지

이 파일은 그것을 읽기만 한다. 없으면 없다고 말하고 빈 손으로 돌아온다 —
예전 run 은 시트가 없고, 그때는 config.yaml 과 refs/ 가 그대로 쓰여야 한다.
그래서 여기서는 어떤 경우에도 예외를 던지지 않는다. 무엇이 없었는지는
notes 에 담아 run.py 가 화면에 찍는다.

## 기대하는 파일 형식

시트를 만드는 쪽(story-harness)이 아직 굳지 않았으므로, 읽는 쪽은 몇 가지
형태를 모두 받아준다. 어느 것으로 읽었는지는 항상 화면에 찍힌다.

  charsheet_picks.json
    {"turnaround": "charsheet/turnaround_c2.png", ...}
    {"picks": {"turnaround": {"file": "...", "candidate": 2}, ...}}

  meta.json
    {"charsheet": {"style_suffix": "...", "model": "...",
                   "paths": {"turnaround": "...", ...}}}

파일 이름만으로도 찾는다 — charsheet/ 안에 turnaround/expressions/details 라는
말이 든 이미지가 있으면 그것을 쓴다. 채택 기록이 없을 때의 마지막 수단이다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CHARSHEET_DIR = "charsheet"
# 두 번째 주연("그 한 사람")의 시트가 저장되는 자리. charsheet/ 와 섞이면
# 주인공 파일을 덮어쓰게 되므로 형제 폴더로 분리한다 — story.py --second-lead
# 가 여기 쓴다.
CHARSHEET_2ND_DIR = "charsheet_2nd"
PICKS_FILE = "charsheet_picks.json"

# 시트 종류. 순서가 곧 첨부 순서다 — 프롬프트의 "첫 번째 이미지" 설명과 맞아야 한다.
#
# "sheet" 는 story-harness 의 **통합 시트**다 — 한 장 안에 4면도·표정 6종·디테일·
# 컬러 팔레트가 네 구역으로 들어 있다. 세 장을 따로 뽑는 것(--split)보다 호출이
# 1/3 이고, 한 장 안에서 그린 것이라 세 장 사이의 그림체 흔들림이 없다.
#
# 맨 앞에 두는 이유: 통합 시트가 있으면 그것 하나로 충분하므로 첨부 순서에서
# 먼저 온다. 세 장짜리와 섞여 있어도 사람이 무엇을 채택했는지가 기준이다.
UNIFIED_KIND = "sheet"
SPLIT_KINDS = ("turnaround", "expressions", "details")
KINDS = (UNIFIED_KIND,) + SPLIT_KINDS
KIND_LABEL = {"sheet": "통합 시트 (4면도+표정+디테일)",
              "turnaround": "4면도", "expressions": "표정 6종",
              "details": "디테일 + 컬러 팔레트"}

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")


@dataclass
class Sheet:
    """읽어 온 캐릭터 시트 한 벌. 아무것도 못 읽어도 이 모양 그대로 돌아온다."""
    run_dir: Path
    name: str = ""                             # p1.json 의 name (컷별 등장 판별에 쓴다)
    gender: str = ""                           # p1.json 의 gender (있으면)
    age: str = ""                              # p1.json 의 age (없으면 빈 문자열)
    appearance: str = ""                       # p1.json 의 appearance_en
    design_details: str = ""
    color_palette: str = ""
    expression_set: str = ""
    paths: dict[str, Path] = field(default_factory=dict)   # {kind: 이미지 경로}
    sheet_style_suffix: str = ""               # 시트를 만들 때 쓴 style_suffix (문구)
    sheet_style_name: str = ""                 # 그 문구의 이름 (styles 표의 키)
    sheet_model: str = ""                      # 시트를 그린 이미지 모델
    source: str = ""                           # 어디서 경로를 찾았는지 (화면 표시용)
    notes: list[str] = field(default_factory=list)

    @property
    def has_images(self) -> bool:
        return bool(self.paths)

    def kinds(self) -> list[str]:
        return [k for k in KINDS if k in self.paths]

    def missing(self, want: list[str]) -> list[str]:
        return [k for k in want if k not in self.paths]


def _read_json(path: Path) -> Any:
    """읽히면 주고 아니면 None. 시트는 있으면 좋은 것이지 없으면 안 되는 것이 아니다."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def _text(value: Any) -> str:
    """문자열이면 그대로, 목록이면 줄로 잇는다. 팔레트는 목록으로 올 수 있다."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        parts = [_text(v) for v in value]
        return ", ".join(p for p in parts if p)
    if isinstance(value, dict):
        # {"jacket": "orange", ...} 같은 형태. 사람이 읽을 한 줄로 편다.
        parts = [f"{k}: {_text(v)}" for k, v in value.items() if _text(v)]
        return ", ".join(parts)
    if value is None:
        return ""
    return str(value).strip()


def _resolve(run_dir: Path, raw: Any, dirname: str = CHARSHEET_DIR) -> Path | None:
    """picks/meta 에 적힌 경로 문자열 → 실제 파일. run 폴더 기준 상대경로도 받는다."""
    text = str(raw or "").strip()
    if not text:
        return None
    p = Path(text)
    for cand in ([p] if p.is_absolute() else
                 [run_dir / p, run_dir / dirname / p.name]):
        if cand.exists() and cand.is_file():
            return cand
    return None


def _from_picks(run_dir: Path, data: Any, dirname: str = CHARSHEET_DIR) -> dict[str, Path]:
    """charsheet_picks.json 의 여러 형태를 하나로 받는다."""
    if not isinstance(data, dict):
        return {}
    block = data.get("picks") if isinstance(data.get("picks"), dict) else data
    out: dict[str, Path] = {}
    for kind in KINDS:
        item = block.get(kind)
        if isinstance(item, dict):
            item = item.get("file") or item.get("path") or item.get("filename")
        path = _resolve(run_dir, item, dirname)
        if path:
            out[kind] = path
    return out


def _from_dir(run_dir: Path, dirname: str = CHARSHEET_DIR) -> dict[str, Path]:
    """채택 기록이 없을 때의 마지막 수단 — 파일 이름으로 종류를 알아본다."""
    d = run_dir / dirname
    if not d.is_dir():
        return {}
    out: dict[str, Path] = {}
    for kind in KINDS:
        hits = sorted(p for p in d.iterdir()
                      if p.is_file() and p.suffix.lower() in IMAGE_EXT
                      and re.search(kind, p.name, re.IGNORECASE))
        if hits:
            # 여러 장이면 이름이 가장 뒤인 것 (보통 마지막 후보)을 쓴다.
            out[kind] = hits[-1]
    return out


def load(runs_root: Path, run_id: str) -> Sheet:
    """runs/<run_id> 에서 외형 사양과 채택된 시트를 읽는다. 실패해도 던지지 않는다."""
    run_dir = Path(runs_root) / run_id
    sheet = Sheet(run_dir=run_dir)
    if not run_dir.is_dir():
        sheet.notes.append(f"스토리 run 폴더가 없습니다: {run_dir}")
        return sheet

    # ---- 1. 외형 사양 (p1.json) ---------------------------------------- #
    p1 = _read_json(run_dir / "p1.json")
    if isinstance(p1, dict):
        sheet.name = _text(p1.get("name"))
        sheet.gender = _text(p1.get("gender") or p1.get("sex"))
        sheet.age = _text(p1.get("age") or p1.get("나이"))
        sheet.appearance = _text(p1.get("appearance_en"))
        sheet.design_details = _text(p1.get("design_details"))
        sheet.color_palette = _text(p1.get("color_palette"))
        sheet.expression_set = _text(p1.get("expression_set"))
        if not sheet.appearance:
            sheet.notes.append(
                "p1.json 에 appearance_en 이 없습니다 (예전 run 입니다) — "
                "config.yaml 의 character_appearance 를 씁니다.")
    else:
        sheet.notes.append(f"p1.json 을 읽지 못했습니다: {run_dir / 'p1.json'}")

    # ---- 2. 채택된 시트 경로 -------------------------------------------- #
    meta = _read_json(run_dir / "meta.json")
    block = meta.get(CHARSHEET_DIR) if isinstance(meta, dict) else None
    if isinstance(block, dict):
        sheet.sheet_style_suffix = _text(block.get("style_suffix"))
        sheet.sheet_style_name = _text(block.get("style") or block.get("style_name"))
        sheet.sheet_model = _text(block.get("model") or block.get("image_model"))

    for source, finder in (
        (PICKS_FILE, lambda: _from_picks(run_dir, _read_json(run_dir / PICKS_FILE))),
        ("meta.json", lambda: _from_picks(run_dir, block)),
        (f"{CHARSHEET_DIR}/ 파일 이름", lambda: _from_dir(run_dir)),
    ):
        found = finder()
        if found:
            sheet.paths, sheet.source = found, source
            break

    if not sheet.paths:
        if (run_dir / CHARSHEET_DIR).is_dir():
            sheet.notes.append(
                f"{run_dir / CHARSHEET_DIR} 에서 채택된 시트를 찾지 못했습니다 "
                f"({PICKS_FILE} 도, 이름으로도).")
        else:
            sheet.notes.append(
                f"캐릭터 시트가 아직 없습니다 ({run_dir / CHARSHEET_DIR} 없음).\n"
                f"        시트를 요구하는 조건(C / C+ / D)은 여기서 멈춥니다 — "
                f"config 의 refs 로 대신하지 않습니다.\n"
                f"        story-harness 에서 먼저 뽑으세요: "
                f"python story.py --charsheet --run-id {run_dir.name} --split")
    return sheet


def load_zone_text(runs_root: Path, run_id: str) -> dict[str, str]:
    """series.json 의 존 서술 → {zone_id: 그 자리가 사람 없이 어떻게 생겼는가}.

    **배경은 이미지로 미리 굽지 않는다.** 한 번 구운 배경을 모든 컷이 참조하면
    그 안에 잘못 들어간 것(자판기 위의 머그컵)이 화 전체에 박히고, 되돌리려면
    그 존의 컷을 전부 다시 뽑아야 한다. 실제로 첫 실행에서 그 일이 났다.

    대신 **글로 넘긴다.** 같은 존의 컷은 같은 서술을 받으므로 배경이 이어지고,
    틀린 곳은 series.json 한 줄을 고치면 다음 컷부터 바로 반영된다 — 다시
    구울 자산이 없다.
    """
    path = Path(runs_root) / run_id / "webtoon" / "series.json"
    data = _read_json(path)
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for z in data.get("zones") or []:
        if not isinstance(z, dict):
            continue
        zid = _text(z.get("zone_id"))
        label = _text(z.get("label"))
        if zid and label:
            out[zid] = label
    return out


def load_second_lead(runs_root: Path, run_id: str) -> Sheet:
    """'그 한 사람'(두 번째 주연)의 시트를 읽는다. 없어도 예외를 던지지 않는다.

    load() 와 달리 story.py 가 쓰는 형식 하나만 안다 — 여러 옛 형식을 받아줄
    필요가 없다(이 경로는 이번에 새로 생겼다). 외형 사양은 p1.json 이 아니라
    charsheet_2nd/lead.json 이고, 채택 경로는 meta.json 의 charsheet 가 아니라
    charsheet_second_lead 키에 있다 — 같은 키를 쓰면 주인공 것을 덮어쓴다.
    """
    run_dir = Path(runs_root) / run_id
    sheet = Sheet(run_dir=run_dir)
    if not run_dir.is_dir():
        return sheet

    spec = _read_json(run_dir / CHARSHEET_2ND_DIR / "lead.json")
    if isinstance(spec, dict):
        sheet.name = _text(spec.get("name"))
        sheet.gender = _text(spec.get("gender"))
        sheet.appearance = _text(spec.get("appearance_en"))
        sheet.design_details = _text(spec.get("design_details"))
        sheet.color_palette = _text(spec.get("color_palette"))
        sheet.expression_set = _text(spec.get("expression_set"))
    else:
        # 없는 게 정상일 수 있다 — 아직 그 인물의 시트를 안 뽑았을 뿐이다.
        # 컷에 그 사람이 없으면 이 sheet 는 그냥 안 쓰인다.
        return sheet

    meta = _read_json(run_dir / "meta.json")
    block = meta.get("charsheet_second_lead") if isinstance(meta, dict) else None
    if isinstance(block, dict):
        sheet.sheet_style_suffix = _text(block.get("style_suffix"))
        sheet.sheet_style_name = _text(block.get("style") or block.get("style_name"))
        sheet.sheet_model = _text(block.get("model") or block.get("image_model"))

    picks_path = run_dir / CHARSHEET_2ND_DIR / PICKS_FILE
    for source, finder in (
        (f"{CHARSHEET_2ND_DIR}/{PICKS_FILE}",
         lambda: _from_picks(run_dir, _read_json(picks_path), CHARSHEET_2ND_DIR)),
        ("meta.json (charsheet_second_lead)", lambda: _from_picks(run_dir, block, CHARSHEET_2ND_DIR)),
        (f"{CHARSHEET_2ND_DIR}/ 파일 이름", lambda: _from_dir(run_dir, CHARSHEET_2ND_DIR)),
    ):
        found = finder()
        if found:
            sheet.paths, sheet.source = found, source
            break

    if not sheet.paths:
        sheet.notes.append(
            f"'{sheet.name or '그 한 사람'}' 의 외형 사양은 있는데 시트 이미지가 "
            f"없습니다 ({run_dir / CHARSHEET_2ND_DIR}). "
            f"python story.py --charsheet --second-lead --run-id {run_dir.name}")
    return sheet


# --------------------------------------------------------------------------- #
# 성별
# --------------------------------------------------------------------------- #
# appearance_en 에 이 단어가 하나도 없으면 이미지 모델이 성별을 알아서 정한다.
# "Short swept-back blonde hair, sharp clear blue eyes, tall and broad-shouldered"
# 만으로는 남자인지 여자인지 정해지지 않는다.
_GENDER_WORDS = re.compile(
    r"\b(man|men|male|boy|gentleman|he|his|him|"
    r"woman|women|female|girl|lady|she|her|hers|"
    r"androgynous|nonbinary|non-binary)\b", re.IGNORECASE)

_MALE = {"m", "male", "man", "boy", "남", "남자", "남성"}
_FEMALE = {"f", "female", "woman", "girl", "여", "여자", "여성"}


def gender_line(raw: str) -> str:
    """성별 → 프롬프트에 박을 영어 한 문장. 모르면 빈 문자열."""
    key = str(raw or "").strip().lower()
    if not key:
        return ""
    if key in _MALE:
        return "The character is a man."
    if key in _FEMALE:
        return "The character is a woman."
    return f"The character's gender: {str(raw).strip()}."


def gender_warning(sheet: Sheet, config_gender: str) -> str:
    """성별을 아무도 말해 주지 않았을 때. 조용히 지나가면 전 컷이 틀린다."""
    if str(config_gender or "").strip() or sheet.gender.strip():
        return ""
    if _GENDER_WORDS.search(sheet.appearance):
        return ""
    if not sheet.appearance.strip():
        return ""
    return (
        "캐릭터의 성별이 어디에도 없습니다 — p1.json 에 gender 가 없고, "
        "appearance_en 에도 성별을 가리키는 단어가 없습니다.\n"
        "        이미지 모델이 컷마다 알아서 정하므로 전 컷이 틀릴 수 있습니다.\n"
        "        config.yaml 의 character_gender 에 male/female 을 적거나, "
        "story-harness 가 p1.json 에 gender 를 남기게 하세요.")


# --------------------------------------------------------------------------- #
# 프롬프트에 강제로 박히는 블록
# --------------------------------------------------------------------------- #
#
# 2026-08-23 LOCK_HEAD 에 "Written in Korean; follow them literally" 를
# 추가했다 — story.charsheet_prompts() 의 시트 생성 프롬프트는 이 문구를
# 이미 달고 있는데(story.py:4143 "FIXED DESIGN ELEMENTS ... Written in
# Korean; follow them literally"), 같은 design_details 를 매 컷 프롬프트에
# 다시 박는 이 자리(lock_text)에는 빠져 있었다. 시트 자체는 잘 나오는데
# (그 프롬프트는 명시가 있다) 개별 컷이 시트에서 벗어나는 사례가 실제로
# 있었다("헤어를 머리띠로 반묶음 — 오른쪽으로 흘러내린다" 같은 design_details
# 가 있는 캐릭터가 어느 컷에서 다른 머리로 나옴) — 컷 프롬프트에서는 이
# 한국어 문장이 어떻게 읽혀야 하는지가 안 적혀 있던 것이 원인 후보 중 하나다.
# 실사용자 지적: "지금 캐릭터 시트와 너무 다르게 나온 컷이 많아."
# ★ 언어를 단정하지 않는다. "written in Korean" 이라고 적었더니 P1 이
#   design_details 를 영어로 뽑은 run(사진 입력 경로)에서 지시가 거짓이 됐다 —
#   내용은 영어인데 "한국어로 적혀 있다"고 말하는 프롬프트를 모델이 어떻게
#   읽을지 알 수 없다. "글자 그대로, 한 단어도 빼지 말고"는 어느 언어든 성립한다.
LOCK_HEAD = ("These character design details must be followed literally, "
            "word for word, and must stay identical in every panel:")
PALETTE_HEAD = "Color palette (use these exact colors):"

# --------------------------------------------------------------------------- #
# 흑백 그림체용 팔레트 — 색을 **명도로 바꿔** 넘긴다.
#
# 왜 코드가 하는가: 팔레트는 프롬프트에서 {style} **뒤에** 붙고, 뒤에 온 것이
# 이긴다(scenegen.assemble 의 주석 "모델이 마지막에 읽은 것을 더 잘 지킨다").
# 그래서 흑백 그림체 문구가 "색을 쓰지 마라"고 아무리 세게 말해도, 그 아래에서
# 코드가 "outfit_sub: deep red (#A03A3A), accent: rose pink (#E25B7E)" 를 박으면
# 붉은 깃과 분홍 꽃잎이 그려진다 — 실제로 그렇게 나왔다.
#
# 산문으로 "뒤에 오는 색은 무시하라"고 부탁하는 대신 색을 아예 안 보낸다.
# hex 를 명도로 환산하는 것은 산수라서 코드가 할 일이다 (모델에게 시키면
# "#A03A3A 는 어두운 편" 같은 판단을 매번 새로 한다).
# 문구가 선화 쪽 어휘여야 한다. 예전에는 "cross-hatching" / "halftone screentone"
# 이라고 적었는데, 그러면 톤을 거의 쓰지 않기로 한 그림체 문구와 정면으로
# 부딪친다 — 코드가 뒤에서 해칭을 주문하는 셈이라 만화 원고로 돌아간다.
INK_STEPS = (
    (60, "solid black"),
    (120, "a dark fill, close to black, kept as a clean flat shape"),
    (190, "left white, with only a few light lines to suggest it is mid-toned"),
    (256, "bare white paper, with only a contour line to describe it"),
)
MONO_PALETTE_HEAD = (
    "VALUE MAP — this page is black ink on white paper and has NO COLOUR. "
    "The character's colours are given here as ink value only, never as colour:")
MONO_PALETTE_TAIL = (
    "Those are values, not colours. Do not render any of them as an actual "
    "colour, and do not add colour anywhere else in the panel either — not in "
    "the skin, the clothing, the sky, the light, the effects or the lettering. "
    "Every mark on this page is black ink or bare white paper.")

# 스팟 컬러 — 선화인데 **한두 군데만** 색이 남는다.
#
# 완전 무채색과 전면 컬러 사이가 필요하다. 붉은 눈처럼 그 인물을 그 인물로
# 만드는 색이 하나 있으면, 그것만 남기고 나머지를 먹으로 돌리는 것이 선화의
# 힘을 죽이지 않으면서 인물을 살리는 길이다. 색이 딱 하나뿐이라 그 자리가
# 화면에서 가장 먼저 읽힌다 — 오히려 전면 컬러보다 세다.
#
# 어느 항목을 남길지는 config 가 정한다 (monochrome_styles 의 값).
SPOT_HEAD = (
    "SPOT COLOUR — this page is black ink on white paper and is monochrome "
    "EXCEPT for the few items listed here. These keep their real colour and are "
    "the only colour anywhere in the image:")
SPOT_TAIL = (
    "Everything else on the page is black ink or bare white paper. Because they "
    "are the only colour in the frame, draw them cleanly and let them carry the "
    "eye — do not spread that colour into anything nearby, do not tint the "
    "linework, the skin, the sky or the effects with it, and do not add any "
    "other colour.")


def _luminance(hex_text: str) -> int | None:
    """'#A03A3A' → 지각 명도 0~255. 못 읽으면 None (그 줄은 색 이름만 지운다)."""
    raw = str(hex_text or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return None
    try:
        r, g, b = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None
    # ITU-R BT.601. 눈이 초록에 가장 예민하므로 단순 평균을 쓰지 않는다 —
    # 평균으로 재면 #A03A3A(붉은 도복)와 #4B4B4B(회색 눈)가 같은 칸에 들어간다.
    return round(0.299 * r + 0.587 * g + 0.114 * b)


def _ink_step(lum: int) -> str:
    for ceiling, how in INK_STEPS:
        if lum < ceiling:
            return how
    return INK_STEPS[-1][1]


def ink_palette(palette: str, keep: "tuple | list | set" = ()) -> str:
    """'hair: black (#232323), …' → 명도 지시. 비어 있으면 빈 문자열.

    keep 에 적힌 팔레트 항목(예: ("eyes",))은 **색을 그대로 남긴다** — 선화에
    스팟 컬러를 얹는 길이다. 나머지는 hex 를 명도로 환산해 먹으로 바꾼다.

    hex 가 없는 항목은 색 이름을 지우고 "이 부분도 색이 아니다" 로만 남긴다 —
    지어낸 명도를 넣으면 팔레트에 없던 정보가 생긴다.
    """
    text = str(palette or "").strip()
    if not text:
        return ""
    keep_set = {str(k).strip().lower() for k in (keep or ()) if str(k).strip()}
    ink_rows, spot_rows = [], []
    for chunk in text.split(","):
        item = chunk.strip()
        if not item:
            continue
        name, _, value = item.partition(":")
        name, value = name.strip(), value.strip()
        if not value:                       # "black (#232323)" 처럼 이름이 없는 항목
            name, value = "", item
        label = name or "this area"
        if name.lower() in keep_set:
            spot_rows.append(f"  {label}: {value}")
            continue
        found = re.search(r"#[0-9A-Fa-f]{3,6}", value)
        lum = _luminance(found.group(0)) if found else None
        if lum is None:
            ink_rows.append(f"  {label}: no colour — decide its value from the panel")
        else:
            ink_rows.append(f"  {label}: {_ink_step(lum)}")
    if not ink_rows and not spot_rows:
        return ""
    blocks = []
    if spot_rows:
        blocks.append("\n".join([SPOT_HEAD, *spot_rows, SPOT_TAIL]))
    if ink_rows:
        head = ("Everything else is ink value only, never colour:" if spot_rows
                else MONO_PALETTE_HEAD)
        tail = MONO_PALETTE_TAIL if not spot_rows else ""
        rows = [head, *ink_rows] + ([tail] if tail else [])
        blocks.append("\n".join(rows))
    return "\n".join(blocks)
EXPRESSION_HEAD = (
    "How this character's face moves — follow it literally. Pick the one "
    "that matches the panel and draw it plainly — a blank face reads as "
    "nothing:")

# 의상 고정. appearance_en 을 정면으로 덮어써야 하므로 문구가 강하다.
#
# p1.json 의 appearance_en 은 사진 여러 장에서 읽어 만들어진다. 사진마다 옷이
# 다르면 "usually seen in A, B, C, or D" 처럼 **여러 벌을 나열**하게 되고, 그
# 문장이 모든 프롬프트 맨 앞에 강제로 붙는다. 즉 코드가 컷마다 "이 넷 중
# 아무거나"라고 말하는 셈이라 옷이 매번 바뀐다. 실제로 그렇게 나왔다.
#
# design_details 는 "must stay identical in every panel" 로 지켜지는 것이
# 확인됐다(피어싱·목걸이는 유지됐다). 그래서 옷도 같은 자리에, 더 세게 박는다.
OUTFIT_HEAD = (
    "DEFAULT OUTFIT — the main character wears exactly this in every panel:")
# 대명사는 they/them 으로 둔다. 이 문구는 주인공이 누구든 그대로 나가는데,
# 예전에는 she/her 가 박혀 있어서 남성 주인공에게도 "her wardrobe" 가 붙었다.
# 성별은 appearance_en 과 gender_line() 이 따로 말하므로 여기서 다시 말할 이유가
# 없고, 두 자리가 어긋나면 이미지 모델이 어느 쪽을 따를지 알 수 없다.
OUTFIT_TAIL = (
    "The appearance line above may list several outfits this character has been "
    "seen in; ignore that variety — it describes their wardrobe, not this scene. "
    "Never restyle, swap or redesign any garment from panel to panel. Change the "
    "outfit ONLY when the panel description explicitly says they have changed "
    "clothes, and even then keep hair, accessories and every other design detail "
    "identical.")


def outfit_text(outfit: str) -> str:
    """기본 의상 한 벌을 못박는 블록. 비어 있으면 아무것도 넣지 않는다."""
    text = str(outfit or "").strip()
    return f"{OUTFIT_HEAD} {text}\n{OUTFIT_TAIL}" if text else ""


# 머리 고정. 의상과 같은 이유로, 같은 자리에, 같은 세기로 박는다.
#
# 왜 필요한가: 머리 길이는 appearance_en 에만 있고 design_details 에는 없는
# 일이 많다. p1.json 을 쓰는 LLM 이 design_details 를 "액세서리·특징" 목록으로
# 이해해서 "앞머리는 얼굴을 감싸는 형태" 처럼 **모양만** 적고 길이를 빠뜨리기
# 때문이다. 그런데 프롬프트에서 실제로 지켜지는 것은 design_details 쪽이다
# (피어싱·목걸이·주근깨는 유지됐다). appearance_en 은 맨 앞에 있지만 바로
# 아래에서 코드가 "그 줄의 옷 나열은 무시하라"고 말해 권위가 깎이고, 그림체
# 문구의 "HAIR: a few large shaped clumps" 가 단순화를 밀어붙인다.
#
# 결과: 시트는 허리까지 오는 롱 웨이브인데 컷은 단발로 나왔다. 길이를 아무도
# 강하게 말하지 않았기 때문이다. 그래서 appearance_en 에서 머리 구절만 뽑아
# design_details 와 같은 자리에 다시 박는다.
HAIR_HEAD = (
    "HAIR — the main character's hair is exactly this in every panel:")
HAIR_TAIL = (
    "Its LENGTH above all never changes from panel to panel. Do not shorten it, "
    "do not crop it to a bob, do not tuck it out of sight behind the shoulders "
    "or below the panel edge to avoid drawing it, and do not tie it up unless "
    "the panel description explicitly says so. If the panel is cropped so the "
    "ends fall outside the frame, the hair still reads as this length. The "
    "simplified clump-and-highlight rendering in the art-style note describes "
    "HOW the hair is drawn, never how long it is. If you are unsure, draw it "
    "LONGER rather than shorter — erring short is the mistake to avoid.")

# 길이 형용사 → 몸의 어느 지점까지인지.
#
# "long hair" 라고만 쓰면 매번 짧아진다. 실제로 그랬다: 시트는 가슴 아래까지
# 오는 롱웨이브인데 컷은 턱선 단발로 나왔고, HAIR 고정 문구를 넣은 뒤에도
# 쇄골까지밖에 안 왔다. 반면 "실버 피어싱 여러 개", "얇은 레이어드 목걸이"
# 처럼 **셀 수 있는** 지시는 한 번도 틀리지 않았다.
#
# 즉 문제는 문구의 세기가 아니라 종류다. long/short 은 상대적인 말이라
# 모델이 자기 기본값 쪽으로 당겨 가고, 그 기본값이 짧다. 그래서 상대어를
# 몸의 지점으로 바꿔 준다 — 그러면 셀 수 있는 지시와 같은 종류가 된다.
_LENGTH_ANCHOR = {
    "long": "it falls well past the shoulders to the middle of the chest",
    "waist": "it falls all the way to the waist",
    "waist-length": "it falls all the way to the waist",
    "hip-length": "it falls to the hips",
    "knee-length": "it falls to the knees",
    "mid-back": "it falls to the middle of the back",
    "elbow-length": "it falls to the elbows",
    "chest": "it falls to the middle of the chest",
    "shoulder": "it ends at the shoulders",
    "shoulder-length": "it ends at the shoulders",
    "chin-length": "it ends at the chin",
    "bob": "it ends at the jaw",
    "bobbed": "it ends at the jaw",
    "short": "it ends above the collar",
    "cropped": "it is cropped close, ending above the ears",
    "buzz": "it is buzzed to the scalp",
}


def length_anchor(hair: str) -> str:
    """머리 구절의 길이 형용사를 몸의 지점 한 문장으로 바꾼다. 없으면 빈 문자열.

    가장 긴 표현부터 본다 — "shoulder-length" 가 "shoulder" 보다 먼저 잡혀야
    한다. 여러 개가 나오면 첫 번째만 쓴다 (형용사가 겹치는 문장은 드물다).
    """
    text = str(hair or "").lower()
    for word in sorted(_LENGTH_ANCHOR, key=len, reverse=True):
        if re.search(rf"\b{re.escape(word)}\b", text):
            return _LENGTH_ANCHOR[word]
    return ""

# "hair" 앞으로 거슬러 올라가며 수식어를 모을 때, 여기서 멈춘다.
_HAIR_STOP = {
    "with", "and", "or", "of", "in", "on", "has", "have", "had", "is", "are",
    "wears", "wearing", "sports", "keeps", "a", "an", "the", "to", "by", "for",
    "she", "he", "they", "her", "his", "their", "its", "who", "whose", "that",
    "woman", "man", "girl", "boy", "person", "character", "young", "usually",
    "always", "often", "plus", "featuring", "including",
}
# 머리 구절 뒤에 이어지면 길이 정보인 것들 — "hair down to her waist" 처럼.
_HAIR_TRAIL = {"down", "past", "reaching", "falling", "cut", "tied", "pulled",
               "swept", "worn", "that", "which", "cascading", "hanging"}
# 길이를 말하는 단어. 이게 있는데 design_details 에는 없으면 그게 사고 지점이다.
_LENGTH_WORDS = re.compile(
    r"\b(long|short|shoulder|shoulder-length|waist|waist-length|chest|"
    r"mid-back|hip-length|bob|bobbed|cropped|buzz|chin-length|"
    r"knee-length|elbow-length)\b", re.IGNORECASE)


def hair_phrase(appearance: str) -> str:
    """appearance_en 에서 머리를 말하는 구절만 뽑아낸다. 못 찾으면 빈 문자열.

    "A young woman with messy, long ash blonde wavy hair, large bright lavender
    eyes..." → "messy, long ash blonde wavy hair"

    LLM 을 부르지 않는다. 이건 문장에서 이미 있는 구절을 집어 오는 일이지
    새로 쓰는 일이 아니고, 컷마다 호출이 붙으면 비용도 실패 지점도 는다.
    """
    text = str(appearance or "").strip()
    if not text:
        return ""
    # "hair" 를 포함한 문장 하나만 본다.
    sentence = ""
    for part in re.split(r"(?<=[.!?])\s+", text):
        if re.search(r"\bhair\b", part, re.IGNORECASE):
            sentence = part
            break
    if not sentence:
        return ""
    tokens = re.findall(r"[^\s]+", sentence)
    low = [t.strip(".,;:").lower() for t in tokens]
    try:
        end = low.index("hair")
    except ValueError:
        return ""
    start = end
    while start > 0 and low[start - 1] not in _HAIR_STOP and low[start - 1]:
        start -= 1
        if end - start > 8:            # 너무 멀리 거슬러 올라가지 않는다
            break
    tail = end + 1
    if tail < len(low) and low[tail] in _HAIR_TRAIL:
        while tail < len(tokens) and not tokens[tail].rstrip().endswith((",", ".", ";")):
            tail += 1
        tail = min(tail + 1, len(tokens))
    phrase = " ".join(tokens[start:tail]).strip(" ,;:.")
    return phrase if re.search(r"\bhair\b", phrase, re.IGNORECASE) else ""


def hair_text(hair: str) -> str:
    """머리를 못박는 블록. 비어 있으면 아무것도 넣지 않는다.

    길이 형용사가 있으면 몸의 지점으로 풀어 한 문장 더 붙인다 (length_anchor).
    """
    text = str(hair or "").strip().rstrip(".")
    if not text:
        return ""
    anchor = length_anchor(text)
    body = f"{text}. {anchor.capitalize()}." if anchor else f"{text}."
    return f"{HAIR_HEAD} {body}\n{HAIR_TAIL}"


def hair_warning(sheet: "Sheet | None", hair: str) -> str:
    """길이가 appearance 에만 있고 design_details 에는 없을 때 알린다.

    고쳐 넣기는 hair_text 가 이미 한다. 이 경고는 "이번에도 그 자리였다"를
    사람이 보게 하려는 것이다 — 원본(p1.json)을 고치면 다음 run 부터는 아예
    안 생긴다.
    """
    if sheet is None or not str(hair or "").strip():
        return ""
    if not _LENGTH_WORDS.search(hair):
        return ""
    if _LENGTH_WORDS.search(sheet.design_details or ""):
        return ""
    return (
        "머리 길이가 appearance_en 에만 있고 design_details 에는 없습니다 — "
        "프롬프트에서 실제로 지켜지는 쪽은 design_details 입니다.\n"
        "         코드가 HAIR 고정 문구를 따로 박아 이번 실행은 막습니다. "
        "원본에서 없애려면 p1.json 의 design_details 에 길이를 한 줄 넣으세요.")


# 소지품·머리장식 경고. hair_warning 과 같은 이유, 같은 자리.
#
# 실제 사고: 1컷·2컷 지팡이 디자인이 달랐고, 모자를 썼다 벗었다 했다. 머리
# 길이와 똑같은 패턴이다 — appearance_en 에는 "지팡이를 든", "모자를 쓴" 같은
# 서술이 있는데 design_details(실제로 지켜지는 자리)에는 안 들어간 것.
# hair 처럼 몸에 항상 있는 요소가 아니라 있을 수도 없을 수도 있는 것이라,
# 자동으로 문구를 만들어 박지는 않는다(hair_text 같은 함수 없음) — 있는지
# 없는지 자체가 창작 판단이라 코드가 지어내면 오히려 사고가 난다. 그래서
# hair_warning 과 동일하게 "경고만" 한다: 사람이 보고 p1.json 을 고친다.
_ACCESSORY_WORDS = {
    "staff": "지팡이", "wand": "지팡이", "cane": "지팡이",
    "sword": "검", "blade": "검", "dagger": "단검", "spear": "창",
    "bow": "활", "shield": "방패",
    "bag": "가방", "backpack": "가방", "satchel": "가방", "pouch": "주머니",
    "hat": "모자", "cap": "모자", "hood": "후드", "crown": "왕관",
    "circlet": "서클릿", "tiara": "티아라", "headband": "머리띠",
    "veil": "베일", "mask": "가면", "goggles": "고글",
    "cape": "망토", "cloak": "망토",
    "glasses": "안경", "earrings": "귀걸이",
}
_ACCESSORY_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _ACCESSORY_WORDS) + r")\b",
    re.IGNORECASE)


def accessory_warning(sheet: "Sheet | None", appearance: str) -> str:
    """소지품·머리장식이 appearance 에만 있고 design_details 에는 없을 때 알린다.

    hair_warning 과 동일한 컨벤션: 자동으로 고치지 않는다. 여기서 잡는 키워드는
    영문 사전식 목록이라 오탐(false positive)이 날 수 있지만, 경고일 뿐 출력을
    막지 않으므로 안전하다.
    """
    if sheet is None:
        return ""
    text = str(appearance or "").strip()
    if not text:
        return ""
    found = {m.group(1).lower() for m in _ACCESSORY_PATTERN.finditer(text)}
    if not found:
        return ""
    design = sheet.design_details or ""
    missing = sorted(w for w in found if not re.search(
        rf"\b{re.escape(w)}\b", design, re.IGNORECASE))
    if not missing:
        return ""
    labels = ", ".join(f"{w}({_ACCESSORY_WORDS[w]})" for w in missing)
    return (
        f"소지품·머리장식({labels})으로 보이는 단어가 appearance_en 에만 있고 "
        "design_details 에는 없습니다 — 프롬프트에서 실제로 지켜지는 쪽은 "
        "design_details 입니다.\n"
        "         컷마다 생겼다 사라지거나 다른 디자인으로 바뀔 수 있습니다. "
        "원본에서 없애려면 p1.json 의 design_details 에 해당 소지품을 위치·색·"
        "형태와 함께 한 줄 넣으세요 (오탐일 수 있습니다 — 실제로 지닌 소지품이 "
        "아니면 무시해도 됩니다).")


# 나이 → 얼굴·몸 지시. 실사용자 지적(2026-08): "나이 비율에 비해 얼굴이 성숙해
# 보인다. 나이대를 못 맞춘다" (18세로 적었는데 20대 중후반 얼굴이 나왔다).
#
# 원인은 프롬프트에 나이가 **아예 안 들어가고 있었던 것**이다. p1.json 에 age 가
# 있어도 charsheet 가 안 읽었고, 그래서 design_lock 에도 안 실렸다. 이미지 모델은
# 아무 말이 없으면 웹툰 주인공의 기본값(성인 초중반)으로 그린다.
#
# ★ 숫자만 주면 안 된다. "18 years old" 라고만 쓰면 모델이 거의 안 듣는다.
#   **얼굴의 어디가 달라지는지**를 적어야 실제로 바뀐다 (볼살·턱선·눈 크기 비율).
# ★ 등신은 여기서 건드리지 않는다 — 그건 head_ratio 쪽 일이다. 여기는 얼굴이다.
AGE_LOOK = (
    (0, 12,  "a CHILD: round soft face, full cheeks, no jawline definition, "
             "large eyes set low and wide in the face, small nose and mouth, "
             "short neck"),
    (13, 15, "an EARLY TEEN: still-soft round cheeks, a barely-there jawline, "
             "noticeably large eyes for the face, a small thin neck — clearly "
             "younger than a high-school upperclassman"),
    (16, 19, "a TEENAGER (high-school age): youthful soft cheeks with only a "
             "gentle jawline, eyes large relative to the face, a smooth "
             "unlined forehead, a slim neck. NOT an adult face — do not draw "
             "sharp cheekbones, a narrow defined jaw, or a mature sultry look"),
    (20, 29, "a YOUNG ADULT in their twenties: a defined but still soft "
             "jawline, balanced eye-to-face proportion, smooth skin"),
    (30, 44, "an ADULT in their thirties or forties: a clearly defined jaw and "
             "cheekbones, eyes in adult proportion to the face, faint "
             "expression lines"),
    (45, 200, "a MIDDLE-AGED OR OLDER person: a set jaw, visible expression "
              "lines around eyes and mouth, softer eyelids, an adult "
              "eye-to-face proportion"),
)
AGE_HEAD = "AGE — the face must read as"

_AGE_NUM = re.compile(r"(\d{1,3})")


def age_look(age: str) -> str:
    """'18' / '18세' / '열여덟' → 얼굴 지시문. 못 읽으면 빈 문자열.

    숫자를 못 찾으면 조용히 포기한다. 나이를 안 적은 캐릭터(대부분의 예전 run)
    에서 이 자리가 비어야 예전과 똑같이 동작하기 때문이다.
    """
    m = _AGE_NUM.search(str(age or ""))
    if not m:
        return ""
    try:
        n = int(m.group(1))
    except ValueError:
        return ""
    if not 0 <= n <= 200:
        return ""
    for lo, hi, look in AGE_LOOK:
        if lo <= n <= hi:
            return f"{AGE_HEAD} {look}. The character is {n} years old."
    return ""


def age_warning(sheet: "Sheet | None") -> str:
    """나이를 못 읽었을 때 알린다. hair_warning / accessory_warning 과 같은 컨벤션.

    나이를 아예 안 적은 경우는 경고하지 않는다 — 안 적는 것도 정상이다.
    적었는데 숫자를 못 뽑아낸 경우만 알린다 (예: "청년", "고등학생").
    """
    if sheet is None:
        return ""
    raw = str(sheet.age or "").strip()
    if not raw or age_look(raw):
        return ""
    return (
        f"p1.json 의 age(\"{raw}\")에서 숫자를 찾지 못해 나이 지시문을 못 넣었습니다.\n"
        "         나이를 안 넣으면 이미지 모델은 성인 초중반 얼굴로 그립니다 — "
        "실제로 18세 캐릭터가 20대 중후반으로 나온 적이 있습니다.\n"
        "         age 를 숫자로 적어 주세요 (예: \"18\" 또는 \"18세\").")


def lock_text(sheet: Sheet | None, outfit: str = "", hair: str = "",
              monochrome: bool = False, accent_keys: "tuple | list" = ()) -> str:
    """design_details / color_palette / expression_set 을 프롬프트 끝에 박는다.

    monochrome 이면 팔레트를 hex 대신 **명도 지시**로 바꿔 넣는다 (ink_palette).
    흑백 그림체에서 이 자리가 색을 되살리는 유일한 구멍이었다.
    accent_keys 에 적힌 항목만 색으로 남는다 (스팟 컬러).

    style_suffix 와 같은 자리에 같은 방식으로 들어간다 — 코드가 붙이고 LLM 은
    손대지 못한다. 턴어라운드 이미지만으로는 놓치는 것들(소매 반사띠 같은)을
    글자로도 못박기 위한 것이다. 이미지 한 장은 "대충 이런 사람"까지는 전하지만
    "왼쪽 소매에만 노란 반사띠 두 줄"은 전하지 못한다.

    표정도 같은 이유로 넣는다. 턴어라운드는 대개 무표정 한 가지뿐이라, 시트만
    붙이면 모든 컷이 그 무표정을 따라간다. p1.json 의 expression_set 은 이
    캐릭터의 얼굴이 감정마다 어떻게 움직이는지를 적어 둔 것이다 — 그게 없으면
    "당황"이라고 써 놔도 같은 얼굴이 나온다.

    의상은 맨 앞에 둔다. appearance_en 의 옷 나열을 덮어야 하는 문구이므로
    나머지 고정 문구보다 먼저 읽히는 편이 낫다. 머리도 같은 이유로 바로 뒤에
    붙는다 — hair 가 비어 있으면 appearance_en 에서 직접 뽑는다(hair_phrase).
    """
    parts: list[str] = []
    if outfit_text(outfit):
        parts.append(outfit_text(outfit))
    hair_line = str(hair or "").strip() or hair_phrase(
        sheet.appearance if sheet else "")
    if hair_text(hair_line):
        parts.append(hair_text(hair_line))
    if sheet is None:
        return "\n".join(parts)
    # 나이는 design_details 보다 **앞**에 둔다. 얼굴이 몇 살로 보이는지는 옷·
    # 소품보다 먼저 정해져야 하는 것이고, 뒤에 두면 앞의 긴 디테일 나열에
    # 묻힌다. age 가 없는 예전 run 은 빈 문자열이라 이 줄이 통째로 빠진다.
    age_line = age_look(sheet.age)
    if age_line:
        parts.append(age_line)
    if sheet.design_details:
        parts.append(f"{LOCK_HEAD} {sheet.design_details}")
    if sheet.color_palette:
        if monochrome:
            mono = ink_palette(sheet.color_palette, accent_keys)
            if mono:
                parts.append(mono)
        else:
            parts.append(f"{PALETTE_HEAD} {sheet.color_palette}")
    if sheet.expression_set:
        parts.append(f"{EXPRESSION_HEAD} {sheet.expression_set}")
    return "\n".join(parts)


def describe(sheet: Sheet) -> str:
    """화면에 한 줄로 찍을 요약."""
    if not sheet.has_images:
        return "시트 없음"
    kinds = ", ".join(f"{k}({KIND_LABEL[k]})" for k in sheet.kinds())
    return f"{kinds} · 출처 {sheet.source}"


def style_warning(sheet: Sheet, config_style: str, image_model: str,
                  style_name: str = "") -> list[str]:
    """시트와 컷이 같은 기준으로 만들어졌는지 확인한다.

    style_suffix 는 두 하네스의 유일한 공통 기준점이다. 시트를 만들 때 쓴 문구와
    지금 컷에 쓰는 문구가 다르면, 시트를 아무리 잘 붙여도 시트가 가리키는 그림체와
    컷이 향하는 그림체가 다른 곳이다.

    같아도 안심할 수 없다는 것까지 말한다 — 시트와 컷은 아예 다른 이미지 모델이
    그린다. 같은 문구를 줘도 손이 다르면 그림체가 다르다.
    """
    if not sheet.has_images:
        return []
    out: list[str] = []
    now = str(config_style or "").strip()
    made = sheet.sheet_style_suffix.strip()
    made_name = sheet.sheet_style_name.strip()
    mine = str(style_name or "").strip()

    if not made and not made_name:
        out.append(
            "시트가 어떤 그림체로 만들어졌는지 meta.json 에 없습니다 — "
            "지금 쓰는 그림체와 같은지 확인할 수 없습니다.\n"
            "        story-harness 의 --charsheet 가 meta.json 에 "
            "charsheet.style (이름) 과 charsheet.style_suffix (문구) 를 "
            "남기게 해주세요.")
    elif made and made != now:
        out.append(
            "시트를 만들 때의 그림체 문구와 지금 쓰는 문구가 다릅니다.\n"
            f"        시트: {made_name or '(이름 미기록)'} — {made}\n"
            f"        지금: {mine or '(이름 미상)'} — {now}\n"
            "        시트가 가리키는 그림체와 컷이 향하는 그림체가 다른 곳입니다. "
            f"같은 이름으로 맞추고 다시 실행하세요 (--style {mine or '<이름>'}).")
    elif made_name and mine and made_name != mine:
        # 문구는 같은데 이름표가 다르다 — 한쪽 config 가 뒤처졌다는 뜻이다.
        out.append(
            f"시트는 그림체 「{made_name}」 로 기록됐는데 지금은 「{mine}」 로 "
            f"돌고 있습니다 (문구 자체는 같습니다).\n"
            "        두 하네스의 styles 표가 어긋났을 수 있으니 확인하세요.")
    # 모델이 **실제로 다를 때만** 말한다. 예전에는 무조건 붙었는데, 시트를
    # story-harness 의 GEMINI_IMAGE_MODEL 로 뽑으면 컷과 같은 모델이 될 수 있고
    # 그때는 "시트 gemini-3-pro-image-preview vs 컷 gemini-3-pro-image-preview" 라는
    # 자기모순이 찍혔다. 틀린 경고가 섞이면 맞는 경고도 같이 안 읽힌다.
    made_model = (sheet.sheet_model or "").strip()
    if made_model != str(image_model or "").strip():
        who = f"시트 {made_model or '(모델 미기록)'} vs 컷 {image_model}"
        out.append(
            f"시트와 컷은 다른 이미지 모델이 그립니다 ({who}). style_suffix 가 같아도 "
            "그림체는 다를 수 있습니다 —\n"
            "        시트는 '무엇을 그릴지'의 기준이지 '어떻게 그릴지'의 보증이 아닙니다.")
    return out
