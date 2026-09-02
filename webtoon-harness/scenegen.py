"""Scene 모드 — 컷 여러 개를 "웹툰 페이지 한 장"으로 묶어 한 번에 생성.

컷 모드는 컷 1개 = 이미지 1장이다. Scene 모드는 컷 N개(기본 3) = 이미지 1장이며,
한 장 안에 패널이 여러 개 들어간다. 컷 10개 기준 호출 수가 30회에서 12회로 준다.

두 모드를 나란히 비교하는 것이 목적이므로 프롬프트의 고정 부분(외형·스타일)은
컷 모드와 글자 그대로 같게 쓴다. 달라지는 것은 두 가지뿐이다:
  1) 장면 서술이 패널 여러 개로 묶여 들어간다 (prompts/scene_gen.txt)
  2) 레이아웃 지시가 붙는다 (config 의 layout_templates)

말풍선은 모델이 빈 껍데기만 그리고, 글자는 뷰어가 그 위에 얹는다. CSS 로 그린
말풍선은 그림과 따로 놀았기 때문이다 — 선 굵기도 질감도 원근도 맞지 않는다.
그래서 코드가 맨 끝에 강제로 붙이는 문구는 "말풍선 금지" 가 아니라
"말풍선 안의 글자 금지" 다. config 로 끌 수 없다.
효과음은 반대로 그림에 녹아드는 레터링이라 모델이 글자까지 직접 그린다.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field
from typing import Any

import directing

CACHE_FILE = "scenes.json"

# --------------------------------------------------------------------------- #
# 글자를 누가 그리는가 — scene.lettering 이 정한다.
#
#   overlay   말풍선은 빈 껍데기로 그리고 글자는 뷰어가 얹는다. 한글이 절대
#             안 깨지지만, 말풍선 모양과 글자가 따로 논다.
#   in_image  대사·나레이션·속마음까지 모델이 그림 안에 직접 그린다. 효과음을
#             이미 그렇게 맡기고 있으므로 같은 논리다. 한글이 깨질 수 있고,
#             깨지는지는 뽑아 봐야 안다.
#
# 어느 쪽이든 코드가 프롬프트 맨 끝에 강제로 한 줄을 박는다. config 로 문구를
# 바꿀 수는 없고, 어느 쪽을 쓸지만 고른다.
# --------------------------------------------------------------------------- #
#   none      말풍선도 그리지 않는다. 컷은 그림만이고 글자는 **전부** 후처리다.
#             액션 컷용이다 — 풍선과 효과음 레터링이 얹히는 순간 그 컷은
#             "그림 한 장"이 아니라 "완성된 만화 페이지"가 되고, 동작이 아니라
#             레터링이 먼저 읽힌다. 자리 비우기(bubble_zone)는 그대로 둔다.
#   sfx_only  **효과음만** 그림에 굽고 말풍선·나레이션은 후처리한다.
#             효과음은 레터링이 아니라 그림의 일부다 — 기울고, 깨지고, 인물
#             뒤로 지나가고, 칸 밖으로 넘친다. 그걸 나중에 얹으면 그냥 글자가
#             된다. 반대로 대사 풍선은 위치가 바뀌기 쉬워서 후처리가 낫다.
#             none 으로 두면 효과음까지 사라져 웹툰다움이 눈에 띄게 준다.
LETTERING_MODES = ("in_image", "overlay", "none", "sfx_only")

NO_TEXT = "No dialogue text, no lettering inside bubbles, no watermark."
DRAW_TEXT = (
    "Draw the Korean text inside every speech bubble, caption box and thought "
    "bubble, exactly as given, in clean legible Hangul at a readable size. "
    # 실제 피드백(2026-08-23): 그림 한가운데 영어 문장이 장식처럼 그려져 나왔다.
    # 풍선 안 글자만 허락하고 나머지는 전부 막는다 — 간판·옷·배경의 알아볼 수
    # 없는 글자는 지시한 적 없는 것이 새어 나온 것이다.
    "Write NO other text anywhere else in the image — no English words or "
    "sentences, no random lettering on signs, clothing, walls or backgrounds, "
    "no decorative gibberish. No watermark.")
NO_BUBBLE = (
    "Draw NO speech bubbles, NO thought bubbles, NO caption boxes, NO "
    "sound-effect lettering and NO text of any kind anywhere in this image — not "
    "in Korean, not in English, not as decoration. This is artwork only; every "
    "balloon and every word is added afterwards. No watermark, no signature.")
SFX_ONLY = (
    "Draw NO speech bubbles, NO thought bubbles and NO caption boxes, and no "
    "dialogue text of any kind — those are added afterwards. The ONLY lettering "
    "in this image is the Korean sound effect described above, drawn as part of "
    "the artwork. No watermark, no signature.")


def lettering(cfg: dict[str, Any]) -> str:
    """scene.lettering 값. 모르는 값이면 세운다 — 조용히 반대로 도는 것이 최악이다."""
    mode = str((cfg.get("scene") or {}).get("lettering") or "in_image").strip().lower()
    if mode not in LETTERING_MODES:
        raise SceneError(
            f'config.yaml 의 scene.lettering 값 "{mode}" 를 모릅니다. '
            f"{' 또는 '.join(LETTERING_MODES)} 이어야 합니다.")
    return mode


def lettering_tail(cfg: dict[str, Any]) -> str:
    mode = lettering(cfg)
    if mode == "in_image":
        return DRAW_TEXT
    if mode == "sfx_only":
        return SFX_ONLY
    return NO_BUBBLE if mode == "none" else NO_TEXT


# 흑백 그림체의 마지막 못. assemble() 이 프롬프트 **맨 끝**에 붙인다 — 같은
# 파일의 seam 주석과 같은 이유다(모델은 마지막에 읽은 것을 가장 잘 지킨다).
# 그림체 문구는 프롬프트 중간에 있고, 그 뒤로 조건 extra·조연·의상·머리·팔레트가
# 줄줄이 따라오면서 "색"이라는 낱말이 여러 번 지나간다. 그중 하나라도 색을
# 부르면 페이지 전체가 컬러로 돌아간다.
MONO_TAIL = (
    "FINAL CONSTRAINT, OVERRIDING EVERYTHING ABOVE: this image is BLACK INK ON "
    "WHITE PAPER. There is no colour anywhere in it — not one tinted pixel. Skin, "
    "hair, clothing, sky, fire, blood, petals and light are all rendered in black "
    "ink and bare white paper. If anything above named a colour, draw it as its "
    "value in ink instead. Not coloured, not sepia, not a single accent colour, "
    "not a greyscale painting — inked line art.")

# 스팟 컬러가 있을 때의 마지막 못. {spots} 자리에 "the eyes" 처럼 들어간다.
# MONO_TAIL 을 그대로 쓰면 "색이 하나도 없다"가 스팟 컬러를 죽인다.
SPOT_TAIL = (
    "FINAL CONSTRAINT, OVERRIDING EVERYTHING ABOVE: this image is BLACK INK ON "
    "WHITE PAPER, and the ONLY colour anywhere in it is {spots}. Everything else "
    "— skin, hair, clothing, sky, fire, petals, light, effect lines — is black "
    "ink and bare white paper with no tint at all. If anything above named a "
    "colour for anything else, draw that as its value in ink instead. Not a "
    "coloured illustration, not sepia, not a greyscale painting — line art with "
    "one spot colour.")


def style_common_tail(cfg: dict[str, Any]) -> str:
    """모든 그림체가 지키는 공통 계약(비실사·배경 예산). **프롬프트 맨 끝**이다.

    style_contract 가 v2 일 때만 나온다. v1 이면 빈 문자열이라 예전 프롬프트와
    한 글자도 안 다르다.

    왜 끝인가 — 2026-08-27 에 그림체 문구 **앞**에 붙여서 한 컷 뽑아 봤다가
    되돌린 자리다. 앞에 두면 뒤따르는 장면 서술(영화 언어로 쓰여 있다: "먼지가
    깔린 폐허", "석양이 잔해를 비춘다")에 그대로 덮여서, 안 붙인 것보다 배경이
    **더** 빽빽해졌다. 같은 문구를 맨 끝에 붙였을 때는 하늘이 색면 하나로
    떨어졌다. 이 파일이 이미 같은 말을 두 번 하고 있다 — 이음매도 head_ratio 도
    "뒤에 온 것이 앞을 덮는다" 는 이유로 끝에 있다.
    """
    if str(cfg.get("style_contract") or "v1").strip().lower() != "v2":
        return ""
    return str(cfg.get("style_common") or "").strip()


def monochrome(cfg: dict[str, Any]) -> bool:
    """지금 그림체가 흑백인가. run.py 가 style_monochrome 에 넣어 둔다."""
    return bool(cfg.get("style_monochrome"))


def mono_tail(cfg: dict[str, Any], spots: bool = True) -> str:
    """흑백 못. 스팟 컬러가 있으면 그것만 예외로 남기는 문장으로 바꾼다.

    spots=False 는 **주인공이 안 나오는 컷**이다. 이 자리에서 "주인공의 붉은 눈만
    색이다" 라고 말하면, 화면에 있는 사람이 조연뿐일 때 그 조연이 그 색을 가져간다
    — 실제로 적장이 주인공의 붉은 눈을 달고 나왔다. 주인공이 없으면 스팟 컬러도
    없으므로 완전 무채색으로 말한다.
    """
    keys = [str(k).strip() for k in (cfg.get("style_accent_keys") or []) if str(k).strip()]
    if not keys or not spots:
        return MONO_TAIL
    joined = ", ".join(keys)
    text = " and ".join(joined.rsplit(", ", 1)) if len(keys) > 1 else joined
    return SPOT_TAIL.format(spots=f"the main character's {text}")


class SceneError(RuntimeError):
    """Scene 분해/프롬프트 생성 실패. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


@dataclass
class Scene:
    scene_number: int
    cuts: list[dict[str, Any]]          # prompts.json 의 컷 dict 그대로
    panels: list[str] = field(default_factory=list)   # 패널별 영어 장면 서술 (LLM)
    layout: str = ""                    # config layout_templates 중 하나
    warnings: list[str] = field(default_factory=list)  # 금지어 lint 결과
    # 9단계(페이지 편집)가 고른 **바탕 컷 번호**. 이 화면에서 지면을 깔고 다른
    # 컷이 그 위에 얹히는 컷이다. None 이면 layout_text 가 예전처럼 크기로
    # 고른다 — 9단계가 없던 옛 run 이 그대로 재현된다.
    base_cut: int | None = None

    @property
    def gap_after(self) -> int:
        """이 Scene 뒤의 여백 = 마지막 컷의 gap_after. 연출이 없으면 1(보통)."""
        if not self.cuts:
            return 1
        gap = self.cuts[-1].get("gap_after")
        return gap if isinstance(gap, int) and 0 <= gap <= 3 else 1

    @property
    def weight(self) -> str:
        """이 Scene 이 지면을 얼마나 먹는가 — full | normal | light.

        `grouping: weight` 로 묶인 Scene 은 안의 컷이 전부 같은 weight 다
        (group_by_weight 의 불변식 — light 는 light 끼리만 묶이고, full·normal 은
        애초에 혼자 한 Scene 을 이룬다). 그래서 첫 컷의 값이 곧 Scene 전체의 값이다.
        rhythm/fixed 로 묶인 옛 Scene 은 이 칸이 없어 normal 로 읽힌다 — 예전과
        같다.
        """
        if not self.cuts:
            return "normal"
        w = str(self.cuts[0].get("weight") or "normal").strip().lower()
        return w if w in ("full", "normal", "light") else "normal"

    @property
    def beats(self) -> list[str]:
        return [str(c.get("beat") or "") for c in self.cuts]

    @property
    def cut_numbers(self) -> list[int]:
        return [int(c["cut_number"]) for c in self.cuts]

    @property
    def label(self) -> str:
        nums = self.cut_numbers
        return f"컷 {nums[0]}" if len(nums) == 1 else f"컷 {nums[0]}~{nums[-1]}"

    def description(self) -> str:
        return "\n".join(f"[컷 {c['cut_number']}] {c.get('description') or ''}"
                         for c in self.cuts)

    def dialogue(self) -> str:
        mark = {"dialogue": "", "narration": "N ", "thought": "T ", "sfx": "SFX "}
        lines = []
        for c in self.cuts:
            for key in ("dialogue", "narration", "thought", "sfx"):
                text = str(c.get(key) or "").strip()
                if text:
                    lines.append(f"[컷 {c['cut_number']}] {mark[key]}{text}")
        return "\n".join(lines)

    def reader_only(self) -> bool:
        return any(c.get("reader_only") for c in self.cuts)


def group(cuts: list[dict[str, Any]], per: int) -> list[Scene]:
    """컷 목록을 앞에서부터 per 개씩 묶는다. 마지막 묶음은 짧을 수 있다.

    연출(W7.5)이 없는 run 의 예비 경로다. 개수로 자르면 경계가 아무 데나 떨어진다 —
    설명하다 만 자리에서 화면이 넘어가고, 궁금증이 남지 않는다.
    """
    if per < 1:
        raise SceneError("config.yaml 의 scene.cuts_per_scene 은 1 이상이어야 합니다.")
    return [Scene(scene_number=i, cuts=cuts[s:s + per])
            for i, s in enumerate(range(0, len(cuts), per), 1)]


def group_by_fit(cuts: list[dict[str, Any]], need, limit: float) -> list[Scene]:
    """**캔버스에 실제로 들어가는 만큼** 묶는다. 개수 규칙이 없다.

    한 장에 몇 컷이라는 규칙은 어느 숫자를 골라도 임의다 — 3컷도 4컷도 장면이
    무엇을 하려는지와 무관하다. 대신 물리적인 사실 하나만 본다: 이미지 모델이
    받는 캔버스에는 가장 긴 세로가 있고(9:16, 그보다 길면 400 이 온다), 컷을
    세로로 쌓으면 필요한 세로가 그만큼 늘어난다.

    그래서 **다음 컷을 더 넣어도 아직 캔버스 안에 들어가면 넣고, 넘치면 거기서
    끊는다.** 결과는 장마다 다르다 — wide 둘은 한 장에 들어가고, impact 하나는
    혼자 한 장을 쓴다. 컷의 내용(size)이 정하는 것이지 개수가 정하는 것이 아니다.

    넘치는 채로 두면 모델이 남는 폭에 컷을 나란히 놓는다. 세로 스크롤이 아니라
    만화 페이지가 되는 자리다.

    need(cut) : 이 컷이 먹는 세로. 폭 1 일 때의 높이(= 1/비율).
    limit     : 한 장이 쓸 수 있는 세로의 최대치 (= 1/가장_긴_세로_비율).

    scene_break 는 이 함수가 안 본다 — 부르는 쪽이 먼저 이야기 경계로 잘라
    놓고, 그 안을 이 함수가 다시 나눈다. 이야기가 한 화면이라고 한 자리를
    캔버스 사정으로 넘어가지 않기 위해서다.
    """
    scenes: list[Scene] = []
    bucket: list[dict[str, Any]] = []
    used = 0.0

    def flush() -> None:
        nonlocal used
        if bucket:
            scenes.append(Scene(scene_number=len(scenes) + 1, cuts=list(bucket)))
            bucket.clear()
        used = 0.0

    for c in cuts:
        want = max(1e-6, float(need(c)))
        # 컷 하나가 혼자서도 넘치면(impact 등) 그 컷은 혼자 한 장이다.
        if bucket and used + want > limit:
            flush()
        bucket.append(c)
        used += want
    flush()
    if not scenes:
        raise SceneError("묶을 컷이 하나도 없습니다.")
    return scenes


def group_by_weight(cuts: list[dict[str, Any]], max_light: int = 3,
                    combine_normal: bool = False) -> list[Scene]:
    """컷의 **무게**가 묶음을 정한다. 개수 규칙이 아예 없다.

    "한 장에 3컷" 도 "한 컷에 한 장" 도 둘 다 임의의 규칙이었다. 3컷씩 묶으면
    배경이 있는 컷 셋이 한 캔버스에 들어가 격자가 되고, 1컷씩 뽑으면 스쳐 가는
    리액션 한 컷이 절정 컷과 같은 지면·같은 비용을 먹는다. 실제 웹툰에서 컷의
    무게는 균일하지 않으므로, 묶음도 균일할 이유가 없다.

    콘티가 계산해 둔 weight 를 그대로 따른다:

      full   통컷이거나 화면을 꽉 채우는 컷. **혼자 한 장.**
      normal 보통 컷. combine_normal 이 꺼져 있으면(예전 동작) **혼자 한 장**
             (컷 모드와 같다). 켜져 있으면 light 와 똑같이 묶인다 — 실측해
             보니 콘티가 float(=light)를 거의 안 써서 컷 대부분이 normal 로
             남았고, 그러면 이 함수가 사실상 컷 모드와 같아져 버렸다
             (2026-08-27). "무거운 컷만 혼자, 나머지는 합쳐서"가 원래
             의도였으므로 normal 도 묶는 쪽이 그 의도에 맞다 — 다만 예전 run
             을 다시 돌려도 그대로 나오게, 켜는 것은 새 옵션으로만 한다.
      light  떠 있는 컷(float). 배경이 없다 — 그래서 **연달아 붙은 것끼리
             한 장에 묶어도 격자가 안 생긴다.** 나눌 배경 자체가 없기 때문이다.

    max_light 는 한 장에 들어갈 묶는 컷(light, combine_normal 이면 normal 도)의
    상한이다. 배경이 없어도 넷을 넘기면 캔버스가 세로로 길어져 인물이 작아지기
    시작한다.

    weight 가 없는 옛 컷은 전부 normal 로 읽힌다 — combine_normal 이 꺼져
    있으면(기본) 결과가 컷 하나당 한 장, 즉 컷 모드와 같아진다(예전과 동일).
    """
    if max_light < 1:
        raise SceneError("한 장에 묶을 light 컷 수는 1 이상이어야 합니다.")
    solo_weights = {"full"} if combine_normal else {"full", "normal"}
    scenes: list[Scene] = []
    bucket: list[dict[str, Any]] = []

    def flush() -> None:
        if bucket:
            scenes.append(Scene(scene_number=len(scenes) + 1, cuts=list(bucket)))
            bucket.clear()

    for c in cuts:
        w = str(c.get("weight") or "normal").strip().lower()
        if w not in solo_weights:
            bucket.append(c)
            if len(bucket) >= max_light:
                flush()
            continue
        flush()                       # 무거운 컷 앞에서 가벼운 묶음을 끊는다
        scenes.append(Scene(scene_number=len(scenes) + 1, cuts=[c]))
    flush()
    if not scenes:
        raise SceneError("묶을 컷이 하나도 없습니다.")
    # 위에서 무거운 컷을 먼저 넣은 자리가 있어 번호가 어긋날 수 있다 — 다시 매긴다.
    for i, sc in enumerate(scenes, 1):
        sc.scene_number = i
    return scenes


def group_by_break(cuts: list[dict[str, Any]],
                   max_cuts: int = 0) -> list[Scene]:
    """scene_break 가 true 인 컷 뒤에서 끊는다 (W7.5 연출 기반).

    개수가 아니라 리듬이 경계를 정한다. beat 가 hold/turn 으로 끝나는 자리에서만
    끊기므로, 화면 한 번이 끝날 때마다 작은 궁금증이 남는다.

    다만 한 장에 들어갈 수 있는 컷 수에는 물리적인 한계가 있다. 캔버스는
    9:16(세로 1.78배)이 최대인데 거기에 컷 4개를 넣으라고 하면 모델은 격자를
    만든다 — 세로 스크롤이 아니라 만화 페이지가 된다. 그래서 리듬이 정한
    경계는 그대로 두되, 너무 커진 묶음만 앞에서부터 잘라 나눈다.

    max_cuts=0 이면 자르지 않는다 (예전 동작).
    """
    scenes: list[Scene] = []
    bucket: list[dict[str, Any]] = []

    def flush(b: list[dict[str, Any]]) -> None:
        """리듬 경계는 살리되 크기 상한만 지킨다. 넘치면 **고르게** 나눈다.

        앞에서부터 max 씩 잘랐더니 4컷이 3+1 이 되어 마지막 컷이 혼자 한 장을
        받았다. 그 컷이 인서트(사물·화면)면 사물 하나가 캔버스를 통째로 먹는다 —
        실제로 휴대폰 한 대가 한 장이 됐다.

        그래서 조각 수만 정하고 나머지를 앞쪽부터 하나씩 나눠 준다:
        4컷·상한3 → 2+2, 5컷·상한3 → 3+2, 7컷·상한3 → 3+2+2.
        혼자 남는 컷이 없어지고 묶음 크기도 덜 튄다.
        """
        if not (max_cuts and len(b) > max_cuts):
            scenes.append(Scene(scene_number=len(scenes) + 1, cuts=b))
            return
        parts = -(-len(b) // max_cuts)          # 올림
        base, extra = divmod(len(b), parts)
        at = 0
        for i in range(parts):
            take = base + (1 if i < extra else 0)
            scenes.append(Scene(scene_number=len(scenes) + 1,
                                cuts=b[at:at + take]))
            at += take

    for c in cuts:
        bucket.append(c)
        if c.get("scene_break"):
            flush(bucket)
            bucket = []
    if bucket:                       # 마지막 컷에 경계가 없으면 남은 것을 한 장으로
        flush(bucket)
    if not scenes:
        raise SceneError("컷이 없어 Scene 을 만들 수 없습니다.")
    return scenes


def assign_layouts(scenes: list[Scene], templates: list[str], mode: str, seed: str) -> None:
    """Scene 마다 레이아웃 템플릿을 하나씩 붙인다.

    random 이어도 seed(run_id+화)로 고정한다. 다시 실행할 때 레이아웃이 바뀌면
    "레이아웃이 달라서 좋아진 건지 조건이 달라서 좋아진 건지"를 알 수 없다.
    """
    if not templates:
        raise SceneError("config.yaml 의 scene.layout_templates 가 비어 있습니다. "
                         "레이아웃 지시는 Scene 모드의 핵심 변수입니다.")
    order = list(range(len(templates)))
    if str(mode).strip().lower() == "random":
        random.Random(seed).shuffle(order)
    elif str(mode).strip().lower() != "cycle":
        raise SceneError(f'config.yaml 의 scene.layout_pick 값 "{mode}" 를 모릅니다. '
                         f"cycle 또는 random 이어야 합니다.")
    for i, sc in enumerate(scenes):
        sc.layout = str(templates[order[i % len(order)]]).strip()


# --------------------------------------------------------------------------- #
# 말풍선 / 효과음 / 화면 보정 — 코드가 고르고 코드가 박는다.
#
# scene_gen(LLM)은 패널 **안의 내용**만 쓴다. 모양을 고르는 일까지 맡기면 매번
# 조금씩 달라져서 "이번엔 왜 다르지"를 추적할 수 없고, --dry-run 으로 미리 볼
# 수도 없다. 여기서 고르면 호출 없이 전부 눈으로 확인된다.
# --------------------------------------------------------------------------- #
SHOUT = re.compile(r"[!！]")
TRAIL = re.compile(r"(\.\.\.|[…⋯])")
ARTICLE = re.compile(r"^(a|an)\s+", re.IGNORECASE)
# 모양 문구가 이미 크기를 말하고 있으면(속삭임의 "small ...") 크기를 또 붙이지 않는다.
HAS_SIZE = re.compile(r"^(small|medium|large|big|huge|tiny)\b", re.IGNORECASE)


def _phrase(text: str) -> str:
    """config 의 모양 문구에서 맨 앞 관사를 뗀다. 앞에 크기 낱말을 붙여야 하는데
    그대로 두면 "A medium a caption ..." 이 된다."""
    return ARTICLE.sub("", str(text or "").strip())


def bubble_kind(cut: dict[str, Any], field: str) -> str:
    """이 글자에 어떤 말풍선을 씌울지. w7 이 bubble_shape 를 주면 그것이 우선."""
    given = str(cut.get("bubble_shape") or "").strip().lower()
    if given:
        return given
    if field == "narration":
        return "narration"
    if field == "thought":
        return "thought"
    if cut.get("reader_only"):
        return "flashback"
    text = str(cut.get(field) or "").strip()
    if SHOUT.search(text):
        return "shout"
    if TRAIL.search(text) or (text.startswith("(") and text.endswith(")")):
        return "whisper"
    return "normal"


SPEECH_KINDS = ("narration", "dialogue", "thought")


def speech_rows(cut: dict[str, Any]) -> list[dict[str, Any]]:
    """이 컷의 말 목록 [{kind, text, speaker, side}].

    cut_rows() 가 실어 준 lines 가 있으면 그것이 전부다. 없으면(옛 run) 옛 세
    칸에서 같은 모양을 만든다. storyload.speech_lines 와 같은 규칙이며, 이쪽은
    Cut 객체가 아니라 **dict** 를 받는다.
    """
    rows = cut.get("lines")
    if isinstance(rows, list) and rows:
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            kind = str(row.get("kind") or "dialogue").strip().lower()
            if text and kind in SPEECH_KINDS:
                out.append({"kind": kind, "text": text,
                            "speaker": str(row.get("speaker") or "").strip(),
                            "side": str(row.get("side") or "").strip().lower()})
        return out
    speaker = str(cut.get("speaker") or "").strip()
    side = str(cut.get("speaker_side") or "").strip().lower()
    out = []
    for kind in SPEECH_KINDS:
        text = str(cut.get(kind) or "").strip()
        if not text:
            continue
        out.append({"kind": kind, "text": text,
                    "speaker": "" if kind == "narration" else speaker,
                    "side": "" if kind == "narration" else side})
    return out


def bubble_clause(cfg: dict[str, Any], cut: dict[str, Any]) -> list[str]:
    """이 컷의 대사·나레이션·속마음을 그릴 지시. 글자를 넣을지는 lettering 이 정한다."""
    shapes = dict((cfg.get("scene") or {}).get("bubbles") or {})
    mode = lettering(cfg)
    if not shapes or mode in ("none", "sfx_only"):
        # 둘 다 풍선 자체를 안 그린다. 자리는 bubble_zone_clause 가 비워 둔다.
        return []
    draw = mode == "in_image"
    out: list[str] = []
    rows = speech_rows(cut)
    multi = len([r for r in rows if r["kind"] != "narration"]) > 1
    for row in rows:
        field, text = row["kind"], row["text"]
        kind = bubble_kind(cut, field)
        shape = _phrase(shapes.get(kind) or shapes.get("normal") or "")
        if not shape:
            continue
        # 말풍선 꼬리를 누구에게 붙일지. 콘티가 speaker 를 정해 보내므로 짐작하지
        # 않는다 — 세 사람이 주고받는 장면에서 꼬리가 엉뚱한 쪽을 가리키면 대사가
        # 통째로 다른 사람 것이 된다. 나레이션 상자는 화자가 없다.
        tail = ""
        who = row["speaker"] or str(cut.get("speaker") or "").strip()
        side = row["side"] or str(cut.get("speaker_side") or "").strip().lower()
        if who and field in ("dialogue", "thought"):
            # "대사인데 생각구름으로 그려진" 실제 피드백(2026-08-23) 때문에
            # 무엇이 소리이고 무엇이 속마음인지 풍선마다 못박는다 — 모양 서술
            # (config 의 bubbles 표)만으로는 모델이 가끔 구름을 골랐다.
            tail = ((" This line is SPOKEN ALOUD — a speech bubble with a "
                     "solid outline, never a cloud-shaped thought bubble. "
                     "Its tail points at the character who is speaking")
                    if field == "dialogue" else
                    (" This is an INNER THOUGHT, not spoken — a cloud-shaped "
                     "thought bubble. It belongs to the character whose inner "
                     "voice this is"))
            tail += " (the same person in every panel where they appear)."
            # 한 컷에 풍선이 둘 이상이면 좌우를 못박아야 꼬리가 갈라지고 읽는
            # 순서가 선다. 하나뿐이면 배치는 그리는 쪽에 맡긴다.
            if side == "offscreen":
                # 화면 밖 목소리. 이 값이 있는데 프롬프트가 몰라서, 그리는 쪽은
                # 늘 화면 안에서 화자를 찾았다 — 그 컷에 없는 인물의 대사가
                # 엉뚱한 사람에게 붙었다. 웹툰의 정상 문법이므로 막지 않고,
                # **어떻게 그릴지**를 말해 준다.
                tail = (" This line is spoken by someone who is NOT VISIBLE in "
                        "this panel — an off-panel voice. The bubble sits at the "
                        "very edge of the panel with its tail pointing off the "
                        "edge, out of frame, toward the unseen speaker. Do NOT "
                        "attach the tail to anyone who is drawn here, and do NOT "
                        "add a new character to be the speaker.")
            elif multi and side in ("left", "right", "center"):
                tail += (f" This bubble sits on the {side} side of the panel."
                         if side != "center" else
                         " This bubble sits in the middle of the panel.")
        if draw:
            # 글자가 실제로 들어가므로 길이에 맞는 크기가 중요해진다.
            size = ("small" if len(text) <= 10 else
                    "medium" if len(text) <= 25 else "large")
            head = shape if HAS_SIZE.match(shape) else f"{size} {shape}"
            out.append(f'A {head}, carrying the Korean text "{text}" '
                       f"in clean legible Hangul.{tail}")
        else:
            out.append(f"A {shape}, completely blank inside with "
                       f"no lettering.{tail}")
    if len(out) > 1:
        out.append(f"There are {len(out)} separate balloons in this panel; "
                   "arrange them so the reader reads them top to bottom in the "
                   "order given, and keep them from overlapping each other or "
                   "covering a face.")
    return out


def sfx_clause(cfg: dict[str, Any], cut: dict[str, Any]) -> list[str]:
    """효과음 — **낱말만** 코드가 보장한다. 어떻게 생겼는지는 scene_gen 이 쓴다.

    낱말을 코드가 쥐는 이유: 한글이 정확해야 하고, 굽기 전에 눈으로 확인되어야
    한다. LLM 이 다시 쓰면 "스윽" 이 "스슥" 이 된다.

    꾸미는 방식을 넘긴 이유: 예전에는 beat 로 골랐다. 그런데 beat 는 이야기의
    리듬이지 소리가 아니다 — "쿵" 과 "톡톡톡" 이 같은 beat 에 있으면 같은
    레터링을 받았다. 어떤 소리인지 아는 것은 그 패널을 쓰는 쪽뿐이다.

    **lettering 모드를 따른다.** 예전에는 모드와 무관하게 언제나 이미지에
    구웠다 — 효과음은 그림에 녹아드는 레터링이라는 이유였는데, 그 결과
    overlay 모드에서도 한글이 깨질 수 있는 자리가 하나 남아 있었다. 글자를
    합성으로 돌리기로 한 이상 예외를 둘 이유가 없다.
    """
    text = str(cut.get("sfx") or "").strip()
    if not text:
        return []
    if lettering(cfg) not in ("in_image", "sfx_only"):
        # 자리만 비워 둔다. 실제 글자는 뷰어가(none 이면 사람이) 얹는다.
        return ["Leave clear empty space in this panel where a hand-lettered "
                "sound effect will be placed later — no lettering drawn here."]
    return [f'The Korean sound effect "{text}" is drawn into this panel as '
            f'lettering, spelled exactly as written.']


# 화면 안 글자 — 휴대폰·모니터·전광판. 말풍선이 아니라 UI 다.
#
# 이미지 모델은 한글 UI 를 못 그린다. 단톡방 문구를 서술에 적어 넘겼더니 글자가
# 아예 안 나오거나 뭉개진 획이 나왔다. 그래서 **화면은 비워 그리게 하고** 글자는
# 합성한다 — lettering 모드와 무관하게 언제나 그렇다. 말풍선과 달리 여기는
# 선택지가 없다: 한글 UI 를 그려 달라고 하면 반드시 깨진다.
SCREEN_UI_CLAUSE = (
    "A device screen ({where}) is clearly visible in this panel, angled so its "
    "full face reads flat to the camera. Draw the screen's frame, glow and "
    "surroundings but leave the screen surface itself EMPTY — a clean blank "
    "panel of even colour with no text, no icons, no UI chrome of any kind. "
    "Korean text will be composited onto it afterwards.")


def screen_ui_clause(cfg: dict[str, Any], cut: dict[str, Any]) -> list[str]:
    """휴대폰·모니터 화면 안의 글자. 화면은 비워 그리고 글자는 합성한다."""
    text = str(cut.get("screen_text") or "").strip()
    if not text:
        return []
    where = str((cfg.get("scene") or {}).get("screen_ui_hint")
                or "a phone screen").strip()
    return [SCREEN_UI_CLAUSE.format(where=where)]


# 종이 위의 글자 — 편지·쪽지·간판·책·현수막.
#
# 실사용자 지적(2026-08): "편지지의 글자가 온전하게 읽을 수 있는 글자로 출력되게
# 수정되어야 할 것 같음." 그리고 같은 컷에서 편지 속 이름이 사용자가 적은 이름
# (초롱)과 달랐다.
#
# 화면(screen_text)은 이미 비워 그리고 합성하는데, **종이는 그 길이 없었다.**
# 콘티에 구조화된 칸이 없어서 편지 내용이 서술의 자유 문장으로 넘어가고, 이미지
# 모델이 한글을 직접 그리려다 뭉갠다. 한글 자모는 획이 많아 작은 크기에서 반드시
# 깨진다 — 이건 모델을 잘 달래서 될 일이 아니다.
#
# 그래서 여기서는 **읽히는 척하지 말라**고만 한다. 진짜 문구가 필요하면
# screen_text 로 넘겨서 합성 경로를 타야 하고, 그게 아니면 글자는 글자 모양의
# 질감으로 남는 편이 낫다 — 뭉개진 가짜 한글보다 훨씬 덜 어색하다.
PROP_TEXT_CLAUSE = (
    "WRITING ON PAPER OR SIGNS in this panel (a letter, a note, a page, a "
    "signboard, a banner, a book): do NOT attempt to render legible Korean or "
    "English words. Korean letterforms break apart at this size and come out as "
    "broken strokes that read as a mistake. Draw the writing as an abstract "
    "texture instead — even rows of small marks that clearly read as 'writing' "
    "from a distance without resolving into letters — or leave the surface "
    "blank. Never invent words, names or signatures."
)

# 글자가 적힐 만한 물건. 서술에서 이 낱말이 보이면 위 절을 붙인다.
_PROP_TEXT_WORDS = re.compile(
    r"\b(letter|envelope|note|notes|page|pages|paper|document|scroll|sign|"
    r"signboard|signage|banner|poster|book|books|notebook|diary|journal|"
    r"newspaper|ledger|map|label|plaque|placard)\b", re.IGNORECASE)


def prop_text_clause(cut: dict[str, Any], panel_text: str = "") -> list[str]:
    """종이 위 글자 지시. 그럴 만한 물건이 안 보이면 붙이지 않는다.

    screen_text 가 있는 컷에는 안 붙인다 — 그쪽은 이미 "비워 그리고 합성한다"
    는 더 정확한 지시를 받고 있고, 두 지시가 겹치면 서로 어긋난다.
    """
    if str(cut.get("screen_text") or "").strip():
        return []
    haystack = " ".join(str(x or "") for x in (
        panel_text, cut.get("description"), cut.get("props")))
    return [PROP_TEXT_CLAUSE] if _PROP_TEXT_WORDS.search(haystack) else []


# 말풍선이 놓일 자리를 비워 두라는 지시. 보장이 아니라 확률을 올리는 힌트다 —
# 최종 안전장치는 합성 단계(bubbles.py)이고, 이건 그 앞에서 얼굴 위에 글자가
# 얹히는 경우를 줄인다.
ZONE_WORDS = {
    "top": "the upper third", "bottom": "the lower third",
    "left": "the left third", "right": "the right third",
    "center": "the middle",
}


def bubble_zone_clause(cut: dict[str, Any]) -> list[str]:
    """이 컷에서 글자가 놓일 자리를 비워 두라는 한 줄."""
    where = ZONE_WORDS.get(str(cut.get("bubble_zone") or "").strip().lower())
    if not where:
        return []
    return [f"Keep {where} of this panel visually quiet — no faces and no "
            f"important detail there. Speech balloons will sit in that space."]


def treatment_clause(cfg: dict[str, Any], cut: dict[str, Any]) -> list[str]:
    """연출이 컷에 직접 적어 둔 보정만 박는다.

    beat 로 고르던 고정 문구는 없앴다. 13컷짜리 한 화에 같은 문장이 4번·3번
    그대로 반복됐다 — build 비트면 무조건 같은 vignette 였다. 같은 비트라도
    잔디밭 낮과 밤 복도는 다른 보정을 받아야 하는데 코드는 그 차이를 모른다.
    지금은 어휘(scene.treatment_guide)를 scene_gen 에 넘기고 거기서 고른다.

    다만 컷에 treatment 필드가 직접 적혀 있으면 사람이나 연출이 지목한 것이므로
    그대로 박는다 — 넘겨짚지 않는다.
    """
    given = str(cut.get("treatment") or "").strip()
    return [f"{given}."] if given else []


# 거리 — 콘티의 shot 을 그리는 쪽 말로 옮긴다.
#
# 예전에는 이것을 **코드가 옮기지 않았다.** 거리가 프롬프트에 들어가는 유일한 길이
# prompt_gen/scene_gen 의 LLM 이 영어 서술에 그 말을 써 주는 것뿐이었고, 안 쓰면
# 이미지 모델이 알아서 정했다. 실제로 콘티가 `클로즈업 · 얼굴이 화면을 가득 채운다`
# 인 컷이 수십 명이 늘어선 원경 투샷으로 나왔다 — 그 화에서 가장 중요한 얼굴이
# 사라졌다. 크기·앵글·그림체를 전부 코드가 박으면서 거리만 LLM 에 맡길 이유가 없다.
# 아래 SHOT_EN(파일 뒤쪽)과 **다른 물건이다.** 저쪽은 텍스트 LLM 에게 넘기는 짧은
# 힌트이고("close-up filling the frame with the face"), 이쪽은 이미지 모델에게
# 코드가 직접 박는 지시다. 같은 낱말을 써도 세기가 달라야 한다 — 힌트는 참고이고
# 이것은 명령이라, 여기서는 "물러서지 마라"까지 말한다.
SHOT_FRAMING_EN = {
    "원경": "FRAMING — an extreme wide establishing shot: the figures are small "
            "in a large space and the place itself is the subject.",
    "전신": "FRAMING — a full-body shot: the whole figure, head to feet, fills "
            "most of the frame height.",
    "중간": "FRAMING — a medium shot, framed from roughly the waist up.",
    "바스트": "FRAMING — a bust shot, framed from the chest up. The face is the "
             "subject and the background is barely present.",
    "클로즈업": "FRAMING — a close-up: the face fills most of the frame and the "
              "expression is unmistakable. Do NOT pull back, do NOT show the "
              "whole body, do NOT show the wider scene.",
    "익스트림": "FRAMING — an extreme close-up on one detail (eyes, mouth, hands, "
              "an object) that fills the frame. Nothing else is in shot.",
    "인서트": "FRAMING — an insert shot of an object or detail. No face in frame.",
}


def shot_clause(cut: dict[str, Any]) -> list[str]:
    """거리 지시. 모르는 값이면 아무것도 붙이지 않는다 (콘티가 값을 늘릴 수 있다)."""
    text = SHOT_FRAMING_EN.get(str(cut.get("shot") or "").strip())
    return [text] if text else []


# 시선 — 세로 스크롤에서만 성립하는 연출이다. 독자의 눈이 다음 컷으로 넘어가는
# 길을 인물의 시선이 만든다. 콘티가 컷마다 정하는데, 지금까지 그 값은 텍스트
# LLM 에게 참고로만 넘어갔고(그것도 Scene 모드에서만) 이미지 프롬프트에는
# 한 번도 도달하지 않았다.
GAZE_EN = {
    "down": "The character's eyes are cast downward, leading the reader's eye "
            "toward the bottom of the panel.",
    "toward-next": "The character looks off toward the bottom edge of the panel, "
                   "pulling the reader onward to what comes next.",
    "at-viewer": "The character looks straight out of the panel at the reader, "
                 "meeting them head-on.",
    "away": "The character looks away, out of the panel and off to the side, "
            "their attention somewhere the reader cannot see.",
}


def gaze_clause(cut: dict[str, Any]) -> list[str]:
    """시선 지시. 인물이 없는 컷(인서트)에는 gaze 가 없으므로 자연히 빠진다."""
    text = GAZE_EN.get(str(cut.get("gaze") or "").strip().lower())
    return [text] if text else []


# 포즈 — 실사용자 지적: "'이 검 엄청 가벼워요' 컷의 포즈가 어색하다."
#
# 포즈는 지금까지 코드가 한 마디도 안 하는 자리였다. shot(거리) · composition
# (구도) · gaze(시선)는 절이 있는데 몸이 어떻게 서 있는지는 전부 패널 서술의
# 자유 문장에 맡겨져 있었다. 그래서 모델이 기본값으로 돌아간다 — 정면으로 서서
# 카메라를 보고 팔은 몸 옆에 붙은, 게임 캐릭터 셀렉트 화면 같은 자세.
#
# 무엇을 하는 포즈인지는 코드가 알 수 없다(그건 서술의 몫이다). 코드가 할 수
# 있는 것은 **어떤 포즈가 어색한지**를 막는 것뿐이라, 금지 쪽으로만 적는다.
POSE_CLAUSE = (
    "POSE: give the body real weight and intent — the pose must show what the "
    "character is doing and how heavy or light it is. Shift the weight onto one "
    "leg, let the shoulders and hips tilt against each other, and let the arms "
    "do something specific. If a character holds or swings an object, the grip, "
    "the wrist angle and the strain in the arm must match how heavy that object "
    "is. Avoid a stiff symmetrical front-facing stand with both arms hanging "
    "straight down and both feet flat and parallel — that reads as a character "
    "select screen, not a story panel."
)


def pose_clause(cfg: dict[str, Any], cut: dict[str, Any]) -> list[str]:
    """포즈 지시. config 의 pose_guidance 로 켠다(기본 꺼짐).

    인물이 없는 컷(인서트·원경)에는 붙이지 않는다 — 사물만 있는 컷에 "체중을
    한쪽 다리에" 라고 말하면 없는 인물을 만들어 넣는다. 실제로 인서트 컷에
    사람이 나오는 것은 콘티 게이트가 따로 잡을 만큼 잦은 사고다.
    """
    if not cfg.get("pose_guidance"):
        return []
    if str(cut.get("shot") or "").strip().lower() in ("insert", "인서트"):
        return []
    return [POSE_CLAUSE]


def panel_clauses(cfg: dict[str, Any], cut: dict[str, Any],
                  panel_text: str = "") -> str:
    """패널 하나에 코드가 덧붙이는 전부.

    거리 → 구도 → 시선 → 포즈 → 말풍선 → 효과음 → 화면 UI → 자리 비우기 → 보정
    순이다. 거리와 구도가 맨 앞인 이유: 나머지는 "그 위에 무엇을 얹을지" 인데
    이 둘은 **무엇을 그릴지** 라서, 뒤에 두면 모델이 이미 잡은 화면에 억지로
    끼워 맞춘다. 포즈는 그 셋 바로 뒤다 — 몸이 정해진 다음에 말풍선 자리가
    정해져야 말풍선이 얼굴을 가리지 않는다.
    """
    parts = (shot_clause(cut) + composition_clause(cut) + gaze_clause(cut)
             + pose_clause(cfg, cut)
             + bubble_clause(cfg, cut)
             + sfx_clause(cfg, cut) + screen_ui_clause(cfg, cut)
             + prop_text_clause(cut, panel_text)
             + bubble_zone_clause(cut) + treatment_clause(cfg, cut))
    return " ".join(p for p in parts if p)


# 구도 — 콘티가 고른 낱말을 그리는 쪽 말로 옮긴다. 서술의 "몰래 촬영한다" 같은
# 의도는 그려지지 않지만 이 문구는 그려진다.
COMPOSITION_EN = {
    "over-the-shoulder": (
        "Framed over a character's shoulder: that character's shoulder and the "
        "back of their head sit large in the near foreground, slightly out of "
        "focus, and we look past them at the subject beyond"),
    "two-shot": (
        "A two-shot: both characters share the frame at the same time, their "
        "distance from each other clearly readable"),
    "silhouette": (
        "The subject reads as a silhouette — backlit so the shape is filled "
        "dark against a bright background, features lost"),
    "reflection": (
        "We see the subject as a reflection — in a mirror, a window or water — "
        "with the reflecting surface itself visible"),
    "frame-in-frame": (
        "A frame within the frame: something in the near foreground (a screen, "
        "a doorway, a gap) contains the real subject, which appears smaller "
        "inside it"),
}


def composition_clause(cut: dict[str, Any]) -> list[str]:
    """구도 지정. none 이면 아무것도 붙이지 않는다."""
    kind = str(cut.get("composition") or "none").strip().lower()
    head = COMPOSITION_EN.get(kind)
    if not head:
        return []
    note = str(cut.get("composition_note") or "").strip()
    return [f"{head}. {note}" if note else f"{head}."]


# 컷이 고를 수 있는 지면 레이아웃. 콘티(w7)가 컷마다 하나를 고른다.
#
# 여기가 생긴 이유: 지금까지 이 자리는 **무조건 겹침**이었다. 가장 큰 컷이
# 바탕(BASE LAYER)이 되고 나머지가 그 위에 얹혔다(OVER THE BASE). 겹침 자체가
# 나쁜 것이 아니라 — 실제 웹툰도 강조할 때 겹친다 — 그것을 **모델이 통제 없이
# 결정**하는 것이 문제였다. 스쳐 가는 리액션도 절정 컷도 똑같이 겹쳤다.
#
# 이제 겹침은 콘티가 "여기는 겹쳐라"라고 말한 자리에서만 일어난다. 나머지는
# 위아래로 분리된 띠가 되어 세로 스크롤이 읽히는 대로 읽힌다.
LAYOUT_KINDS = ("normal", "tight", "overlap", "full_bleed")

LAYOUT_EN = {
    "normal": ("a separate horizontal band with a clear gutter above and below "
               "it — it must NOT overlap or bleed into the neighbouring panels"),
    "tight":  ("a separate horizontal band that touches the panel above it with "
               "no gutter between them, but still does not overlap it"),
    "full_bleed": ("edge to edge with no border and no gutter — the artwork runs "
                   "off all four sides of its band"),
}


def layout_kind(cut: dict[str, Any]) -> str:
    """이 컷이 고른 지면 레이아웃. 없으면 "" — 예전 동작(겹침)으로 간다.

    빈 문자열을 돌려주는 것이 중요하다. 옛 run 의 컷에는 이 칸이 없는데, 없을 때
    "normal"(겹치지 마라)로 읽어 버리면 **예전에 뽑은 화를 다시 그리면 지면이
    통째로 달라진다** — harness-is-final 이 막는 바로 그 일이다.
    """
    v = str(cut.get("layout") or "").strip().lower()
    return v if v in LAYOUT_KINDS else ""


def layout_text(cfg: dict[str, Any], scene: Scene) -> str:
    """{layout} 자리에 들어갈 문구. w7 의 size 를 패널 높이·폭으로 옮긴다.

    지금까지 이 자리에는 config 의 고정 문구가 순서대로 돌아가며 들어갔다
    ("three horizontal panels stacked with thin white gutters, equal heights").
    그래서 어떤 화를 뽑아도 균등한 가로 띠가 나왔다 — 만화 페이지지 웹툰이 아니다.
    w7 은 이미 컷마다 size 를 정해 두었는데 그 값이 여기까지 오지 않았다.

    size 가 하나도 없으면(예전 run) 예전처럼 고정 템플릿을 쓴다.
    """
    comp = dict((cfg.get("scene") or {}).get("composition") or {})
    table = dict((cfg.get("scene") or {}).get("panel_style") or {})
    if not comp or not comp.get("slots"):
        return scene.layout          # composition 설정이 없으면 예전 템플릿

    def weight_of(cut: dict[str, Any]) -> float:
        spec = dict(table.get(str(cut.get("size") or "").strip().lower()) or {})
        try:
            return max(0.05, float(spec.get("height") or 1.0))
        except (TypeError, ValueError):
            return 1.0

    weights = [weight_of(c) for c in scene.cuts]
    total = sum(weights) or 1.0
    # 바탕 컷 — **9단계가 골랐으면 그것을 쓴다.** 크기로 고르면 tall 이라서
    # 바탕이 되고 wide 라서 안 되는 일이 벌어진다. 어느 컷에서 독자가 멈춰야
    # 하는가는 크기가 아니라 이야기가 정한다(9단계 프롬프트 참고).
    base_i = None
    if scene.base_cut is not None:
        for i, c in enumerate(scene.cuts):
            if c.get("cut_number") == scene.base_cut:
                base_i = i
                break
    if base_i is None:
        # 9단계가 없거나 그 번호를 못 찾았다 — 예전대로 가장 큰 컷.
        # 같으면 뒤쪽: 감정의 정점은 대개 뒤에 온다.
        base_i = max(range(len(weights)), key=lambda i: (weights[i], i))

    slots = [str(s).strip() for s in (comp.get("slots") or []) if str(s).strip()]
    renders = dict((cfg.get("scene") or {}).get("panel_render") or {})

    def render_note(cut: dict[str, Any]) -> str:
        note = str(renders.get(
            str(cut.get("render_style") or "normal").strip().lower()) or "").strip()
        return f" {note}." if note else ""

    lines: list[str] = []
    base_cut = scene.cuts[base_i]
    where = ("upper" if base_i * 3 < len(scene.cuts)
             else "middle" if base_i * 3 < len(scene.cuts) * 2 else "lower")
    # 바탕 컷은 이 장에서 가장 큰 컷이다. 크기 지시만 주면 독자는 그냥 지나간다 —
    # 시청 시간은 크기가 아니라 볼 것의 양에 따라간다(Ikuta et al. 2023). 그래서
    # 크기 뒤에 밀도 지시를 한 줄 더 붙인다.
    density = str(comp.get("base_density") or "").strip()
    lines.append(
        f"BASE LAYER — Panel {base_i + 1}: {str(comp.get('base') or '').strip()}. "
        f"Its focal subject sits in the {where} part of the sheet so the reading "
        f"order still runs from top to bottom."
        f"{' ' + density + '.' if density else ''}{render_note(base_cut)}")

    k = 0
    for i, (cut, weight) in enumerate(zip(scene.cuts, weights)):
        if i == base_i:
            continue
        pct = round(weight / total * 100)
        kind = layout_kind(cut)
        if kind and kind != "overlap":
            # 콘티가 "겹치지 마라"고 한 컷 — 바탕 위에 얹지 않고 띠로 세운다.
            lines.append(
                f"PANEL {i + 1}: {LAYOUT_EN[kind]}. It takes roughly {pct}% of "
                f"the sheet height.{render_note(cut)}")
            continue
        # overlap 이거나(콘티가 그렇게 고름) 칸이 아예 없는 옛 컷 — 예전대로 얹는다.
        slot = slots[k % len(slots)]
        k += 1
        why = str(cut.get("overlap_reason") or "").strip()
        lines.append(
            f"OVER THE BASE — Panel {i + 1}: {slot}, covering roughly "
            f"{pct}% of the sheet."
            f"{' It deliberately overlaps the base panel: ' + why + '.' if why else ''}"
            f"{render_note(cut)}")

    rules = str(comp.get("rules") or "").strip()
    return "\n".join(lines) + (f"\n{rules}" if rules else "")


def render_style(scene: Scene) -> str:
    """이 Scene 한 장에 적용할 작화 변주.

    Scene 은 컷 여러 개가 한 장에 구워진다. 한 패널만 SD 로 그리라고 시킬 방법이
    없으므로, 묶인 컷이 전부 같은 render_style 일 때만 그것을 쓴다. 섞여 있으면
    normal 로 둔다 — 한 컷 때문에 페이지 전체가 SD 가 되는 편이 더 나쁘다.
    (컷 모드에서는 컷마다 따로 적용되므로 이런 문제가 없다.)
    """
    kinds = {str(c.get("render_style") or "normal").strip().lower() for c in scene.cuts}
    return kinds.pop() if len(kinds) == 1 else "normal"


def scene_zone(scene: Scene) -> str:
    """이 Scene 한 장에 붙일 존 배경 자산의 id. 컷마다 존이 갈리면 붙이지 않는다.

    render_style 과 같은 이유다 — 한 장 안에 두 존이 섞이면 배경 하나를 붙이는
    것이 오히려 틀린 신호가 된다. zone 이 없는 컷(예전 run)이 섞여도 마찬가지로
    붙이지 않는다.
    """
    zones = {str(c.get("zone") or "").strip() for c in scene.cuts}
    zones.discard("")
    if len(zones) == 1:
        return zones.pop()
    return ""


# 콘티가 "여기는 배경이 이어진다"고 확정한 자리에 덧붙이는 문구.
#
# 위의 seam_text 는 이미 "웬만하면 같은 장소"라고 말하지만, 어디까지나 웬만하면
# 이다 — 서술이 다른 곳을 가리키면 모델이 그쪽을 따른다. 그게 기본값으로는 맞다.
# 다만 콘티가 여백 0 · 같은 zone 으로 확정한 자리(vertical_link)는 추측할 것이
# 없다. 무대는 확실히 그대로이고 카메라만 아래로 내려간 자리라, 거기서는 못박는다.
LINK_SEAM = (
    "This join is a VERTICAL CAMERA MOVE, not a cut: the sheet above and this "
    "sheet are one continuous space that the reader scrolls down through. The "
    "place does not change at all — same room or street, same architecture, same "
    "horizon line, same light direction and colour temperature — and the only "
    "thing that changed is that the camera travelled further DOWN, so this sheet "
    "shows what lies below what the sheet above showed. Line the two up so the "
    "walls, floor, sky or ground read as the same continuous surface.")


def seam_text(prev: Scene | None, nxt: Scene | None,
              link_above: bool = False) -> str:
    """이 장의 위·아래가 무엇과 붙는가.

    Scene 을 한 장씩 따로 굽고 그것을 세로로 **틈 없이** 이어 붙인다. 그런데
    프롬프트가 앞뒤 장을 한 마디도 말해 주지 않으면, 모델은 매번 자기 안에서
    완결되는 그림을 그린다 — 실제로 그렇게 나왔다. 이어 붙이면 잔디밭에서
    캠퍼스로, 복도로 뚝뚝 끊긴다.

    앞 장의 **마지막 컷**과 뒷 장의 **첫 컷**만 알려 준다. 장 전체를 넘기면
    모델이 앞 장을 다시 그리려 든다 — 필요한 것은 맞닿는 한 컷씩뿐이다.
    """
    lines: list[str] = []
    if prev is not None and prev.cuts:
        tail = str(prev.cuts[-1].get("description") or "").strip()
        lines.append(
            "CONTINUES FROM ABOVE. The sheet directly above this one ended with: "
            f"\"{tail}\" — the top of this sheet is joined to it with no gap. "
            "Unless the description says the story has moved somewhere else, this "
            "is the SAME PLACE in the SAME TONE: the same room or street with the "
            "same surfaces and the same objects in it, the same light coming from "
            "the same direction, the same colour grade, and the same emotional "
            "temperature. Everything that fills the place carries over with it, "
            "down to the anonymous figures in the background. Do not restate that "
            "moment and do not copy its layout; just make sure the reader cannot "
            "tell where one sheet ended and this one began.")
        if link_above:
            lines.append(LINK_SEAM)
    if nxt is not None and nxt.cuts:
        head = str(nxt.cuts[0].get("description") or "").strip()
        lines.append(
            "LEADS INTO BELOW. The sheet directly under this one begins with: "
            f"\"{head}\" — leave the bottom edge open toward it: let the artwork "
            "run off the bottom edge and keep the eye moving downward.")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 등신 비율 (head_ratio) — 실사용자 지적으로 새로 만든 축
# --------------------------------------------------------------------------- #
# 실사용자 지적(2026-08): "SD 로 넣은 캐릭터가 웹툰에서는 LD 로 출력된다."
# 그리고 팀과 사용자가 쓰는 낱말 자체가 어긋나 있었다. 사용자 기준은 이렇다:
#
#   SD  머리 비중이 매우 크다 (2~3등신)
#   MD  중간 등신 (4~5등신)
#   LD  실제 등신 (7~8등신)
#
# ★ 이름 충돌 주의 — 이 저장소에는 이미 "sd" 가 있다. 그건 **컷의 종류**다
#   (render_style: normal | sd | emphasis, config 의 styles.<이름>.sd). 코미디용
#   2~3등신 삽입 컷을 가리키는 말이라, 지금 이 축과는 완전히 다른 것이다.
#   그래서 이 축의 config 키를 `head_ratio` 로 따로 뒀다. 값에 sd/md/ld 를 그대로
#   쓰는 것은 **사용자가 그 낱말로 말하기 때문**이고, 키 이름이 다르므로
#   `head_ratio: sd` 와 `render_style: sd` 는 서로 헷갈릴 자리가 없다.
#
# ★ 왜 config 의 styles 문구를 고치지 않고 여기에 따로 두는가: styles 의 일곱
#   그림체는 전부 PROPORTION 줄에 성인 등신을 **박아** 두었다(7~9등신). 그 줄을
#   고치면 그림체마다 다시 균형을 잡아야 하고, 예전 run 의 결과도 바뀐다.
#   대신 프롬프트 **뒤쪽**에 덮어쓰는 문구를 붙인다 — 이 저장소의 규칙대로
#   뒤에 온 것이 이긴다 (style_suffix·design_lock 과 같은 방식).
HEAD_RATIO = {
    "sd": (
        "HEAD-TO-BODY RATIO — OVERRIDE any head-count given above. Draw every "
        "character SUPER-DEFORMED at 2 to 3 heads tall: the head is as large as "
        "the entire torso, the face fills most of the head, the limbs are short "
        "and simplified, and there is almost no neck. This is the defining "
        "feature of the art and it must hold in EVERY panel, including wide "
        "shots and serious moments — a serious scene drawn at this ratio simply "
        "reads as a cute character being serious, which is correct and intended."),
    "md": (
        "HEAD-TO-BODY RATIO — OVERRIDE any head-count given above. Draw every "
        "character at a MID ratio of 4 to 5 heads tall: the head is clearly "
        "larger than realistic but the body still has real shoulders, waist and "
        "legs. Faces stay expressive and slightly enlarged. Hold this ratio in "
        "EVERY panel, including wide shots."),
    "ld": (
        "HEAD-TO-BODY RATIO — draw every character at a REALISTIC ratio of 7 to "
        "8 heads tall, with correct adult anatomy and a head that is small "
        "relative to the body. Hold this ratio in EVERY panel."),
}
HEAD_RATIO_LABEL = {"sd": "SD (2~3등신)", "md": "MD (4~5등신)", "ld": "LD (7~8등신)"}


def sticker_flat(cfg: dict[str, Any]) -> bool:
    """스티커 평면화 문구를 붙일까. config 의 flat_stickers 로 켠다(기본 꺼짐)."""
    return bool(cfg.get("flat_stickers"))


def head_ratio(cfg: dict[str, Any]) -> str:
    """config 의 head_ratio 값. 비었거나 모르는 값이면 빈 문자열(=그림체 기본)."""
    key = str(cfg.get("head_ratio") or "").strip().lower()
    return key if key in HEAD_RATIO else ""


def head_ratio_tail(cfg: dict[str, Any]) -> str:
    """등신 비율 덮어쓰기 문구. head_ratio 가 없으면 빈 문자열이라 예전과 같다."""
    key = head_ratio(cfg)
    return HEAD_RATIO[key] if key else ""


# --------------------------------------------------------------------------- #
# 스티커 평면화 — 실사용자 지적 "스티커가 3D 느낌이라 그림체와 안 맞는다"
# --------------------------------------------------------------------------- #
# 여기서 말하는 스티커는 그림 안에 그려지는 작은 장식들이다 — 땀방울, 하트,
# 별, 반짝임, 화난 십자 표시, 물음표, 뭉게구름 같은 것. 이미지 모델은 아무 말이
# 없으면 이것들을 **입체로** 그린다(그라데이션·하이라이트·드롭섀도). 그러면
# 만화 그림 위에 3D 이모지를 얹은 것처럼 보여서 그림체와 따로 논다.
STICKER_FLAT = (
    "EMOTE MARKS AND SMALL SYMBOLS — sweat drops, hearts, stars, sparkles, "
    "anger crosses, question and exclamation marks, puff clouds and similar "
    "cartoon marks must be drawn COMPLETELY FLAT, in the same ink and the same "
    "line weight as the rest of the drawing, as if inked by the same hand on "
    "the same layer. They are part of the drawing, not stickers placed on top "
    "of it. NO gradients, NO glossy highlights, NO drop shadows, NO bevels, NO "
    "3D or plastic or emoji rendering, NO outer glow, and no rim of white "
    "separating them from the art."
)


def assemble(cfg: dict[str, Any], appearance: str, scene: Scene, extra: str,
             with_lock: bool = True, style_text: str = "",
             prev: "Scene | None" = None, nxt: "Scene | None" = None,
             link_above: bool = False) -> str:
    """Scene 프롬프트 조립. 코드가 강제한다 — LLM 은 패널 서술만 썼다.

    컷 모드의 run.assemble() 과 짝이다. 같은 자리에 같은 문구가 들어가야
    두 모드의 차이가 "묶음 + 레이아웃" 으로만 남는다. lock(캐릭터 시트의
    design_details/color_palette)도 그래서 양쪽 같은 자리에 붙는다.

    style_text: 작화 변주까지 얹은 {style} 문구. 비우면 style_suffix 그대로.
    prev/nxt : 위아래로 붙는 장. 이음매 문구를 만드는 데만 쓴다.
    link_above: 이 장의 첫 컷이 앞 장 마지막 컷에서 **배경이 이어지는** 자리인가
                (콘티의 vertical_link). 켜면 이음매 문구를 못박는다.
    """
    lock = str(cfg.get("design_lock") or "") if with_lock else ""
    # 패널 서술(LLM) 뒤에 말풍선·효과음·보정을 코드가 붙인다. LLM 이 고르게 두면
    # 매번 조금씩 달라져 --dry-run 으로 미리 볼 수 없다.
    rows = []
    for i, text in enumerate(scene.panels, 1):
        cut = scene.cuts[i - 1] if i - 1 < len(scene.cuts) else {}
        extra_clauses = panel_clauses(cfg, cut, text)
        rows.append(f"Panel {i}: {text.strip()}"
                    + (f" {extra_clauses}" if extra_clauses else ""))
    panels = "\n".join(rows)
    # v2 는 컷 분할을 살리는 템플릿을 쓴다(config 의 prompt_template_v2 주석 참고).
    # 없거나 v1 이면 예전 템플릿 그대로라, 옛 run 은 한 글자도 안 바뀐다.
    template = str(cfg["scene"]["prompt_template"])
    if str(cfg.get("style_contract") or "v1").strip().lower() == "v2":
        template = str(cfg["scene"].get("prompt_template_v2") or template)
    text = template
    for token, value in (
        ("{appearance}", appearance.strip()),
        ("{panel_count}", str(len(scene.panels))),
        ("{panels}", panels),
        ("{layout}", layout_text(cfg, scene).strip()),
        ("{style}", (style_text or str(cfg["style_suffix"])).strip()),
        ("{extra}", str(extra or "").strip()),
    ):
        text = text.replace(token, value)
    # 이음매는 레이아웃 지시 바로 뒤가 아니라 끝에 둔다 — 모델이 마지막에 읽은
    # 것을 더 잘 지키고, 이건 "이 장을 어떻게 끝낼 것인가" 의 지시라서 그렇다.
    seam = seam_text(prev, nxt, link_above)
    if seam:
        text = f"{text.rstrip()}\n{seam}"
    if lock.strip():
        text = f"{text.rstrip()}\n{lock.strip()}"
    tail = str(cfg.get("global_suffix") or "").strip()
    if tail:
        text = f"{text.rstrip()}\n{tail}"
    # 등신 비율은 그림체 문구(PROPORTION)를 덮어써야 하므로 그보다 뒤에 온다.
    # head_ratio 를 안 적으면 빈 문자열이라 예전 프롬프트와 한 글자도 안 다르다.
    ratio = head_ratio_tail(cfg)
    if ratio:
        text = f"{text.rstrip()}\n{ratio}"
    if sticker_flat(cfg):
        text = f"{text.rstrip()}\n{STICKER_FLAT}"
    text = f"{text.rstrip()}\n{lettering_tail(cfg)}"
    if monochrome(cfg):
        text = f"{text.rstrip()}\n{mono_tail(cfg)}"
    # 공통 계약은 **제일 마지막**이다 — 그림체 문구도 장면 서술도 다 덮어야
    # 한다(style_common_tail 주석 참고). v1 이면 빈 문자열이라 안 바뀐다.
    common = style_common_tail(cfg)
    if common:
        text = f"{text.rstrip()}\n{common}"
    text = text.replace("1 panels", "1 panel")  # 마지막 묶음이 1컷일 때
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------- #
# scene_gen (텍스트 LLM) — 컷 서술을 패널 서술로. 화당 1회, 조건과 무관하게 공유.
# --------------------------------------------------------------------------- #
# 콘티(W5)가 무대에 적는 여섯 칸. **여섯 개를 다 읽어야 한다.**
#
# 예전에는 앞의 넷만 읽고 props 와 movement 를 버렸다. 그런데 W5 는 props 를
# 이렇게 강조하며 쓴다: "인물 없이 사물만 나오는 컷이 여기서 나오고, 그런 컷이
# 없으면 화 전체가 얼굴 나열이 된다." 배경을 실제 장소로 만드는 것이 바로 그
# 만질 수 있는 사물들인데, 그림 단계가 그걸 못 보고 있었다.
STAGING_FIELDS = (
    ("place", "Place"),
    ("time", "Time of day"),
    ("weather", "Weather / season"),
    ("light", "Light source"),
    ("props", "Objects actually visible in this place"),
    ("movement", "How people move through it"),
)


def staging_text(setting: dict[str, Any] | None) -> str:
    """무대를 프롬프트에 박는다 — 이 화 내내 같아야 하는 것.

    이게 없으면 패널마다 장소와 조명이 새로 정해진다. Scene 을 한 장씩 따로
    굽는 구조라서, 적어 주지 않으면 이어 볼 방법이 아예 없다. 무엇을 그릴지는
    콘티가 정하고 여기서는 옮길 뿐이다.
    """
    rows = []
    for key, label in STAGING_FIELDS:
        value = _text_value((setting or {}).get(key))
        if value:
            rows.append(f"{label}: {value}")
    return "\n".join(rows) if rows else \
        "(not given — pick one reading and keep it identical in every panel)"


def _text_value(value: Any) -> str:
    """props 는 목록으로 온다. 나머지는 문자열."""
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v).strip() for v in value if str(v or "").strip())
    return str(value or "").strip()


def scene_intent(story_scenes: list, scene_number: int) -> dict[str, str]:
    """콘티가 이 Scene 에 적어 둔 의도 — 무슨 장면(what)이고 어떤 공기(mood)인가.

    **mood 가 이 파이프라인에서 가장 중요한 한 줄이다.** 컷 서술(description)은
    "무엇이 보이는가" 만 말한다. "어떤 공기로 그릴 것인가" 는 여기에만 있고,
    이게 안 넘어오면 그림 쪽 LLM 이 패널마다 톤을 새로 정한다 — 같은 장면인데
    한 컷은 서정적이고 다음 컷은 스릴러가 된다.

    Scene 번호는 1부터이고 콘티의 scenes 배열 순서와 같다 (둘 다 last_cut 으로
    끊은 같은 경계다). 길이가 어긋나면 빈 dict 를 돌려 조용히 넘어간다.
    """
    if not isinstance(story_scenes, list):
        return {}
    i = scene_number - 1
    if not 0 <= i < len(story_scenes):
        return {}
    sc = story_scenes[i]
    if not isinstance(sc, dict):
        return {}
    out = {}
    for key in ("what", "mood"):
        value = str(sc.get(key) or "").strip()
        if value:
            out[key] = value
    return out


def treatment_text(cfg: dict[str, Any] | None) -> str:
    """화면 보정 어휘 — 고르라고 주는 목록이 아니라 "이런 것들이 있다" 이다.

    문구를 통째로 박던 것을 그만두고 어휘만 넘긴다. 같은 비트라도 잔디밭 낮과
    밤 복도는 다른 보정을 받아야 하는데, 그 차이를 아는 것은 mood 를 가진
    이쪽뿐이다.
    """
    guide = dict(((cfg or {}).get("scene") or {}).get("treatment_guide") or {})
    if not guide:
        return "(none given — choose from the mood, or leave the panel plain)"
    rows = []
    intents = dict(guide.get("intents") or {})
    if intents:
        rows.append("What each beat wants the screen to do:")
        for beat, intent in intents.items():
            text = str(intent or "").strip()
            rows.append(f"  {beat:<8} {text or '(no treatment — leave it plain)'}")
    box = str(guide.get("toolbox") or "").strip()
    if box:
        rows.append("")
        rows.append(f"Techniques available (not a menu to pick from — a sense of "
                    f"the range): {box}")
    # 흑백 그림체면 여기서 말해 줘야 한다. 이 어휘 목록에는 "colour temperature
    # shift", "a single saturated accent" 처럼 색이 있어야 성립하는 것이 섞여
    # 있고, 5.1 항은 효과음 레터링에 "what colour" 를 아예 물어본다. 그대로 두면
    # 패널 서술에 "massive cracked dark red lettering" 이 적혀 나오고, 그건
    # 그림체 문구가 아니라 **그 패널의 지시**라서 이미지 모델이 그대로 따른다
    # (실제로 그렇게 나왔다).
    if monochrome(cfg):
        rows.append("")
        rows.append(
            "THIS EPISODE IS DRAWN IN BLACK INK WITH NO COLOUR AT ALL. Never name "
            "a colour anywhere in your panel descriptions — not for clothing, "
            "light, fire, blood, petals or sound-effect lettering. Describe value "
            "instead: solid black, dense hatching, open screentone, bare white "
            "paper. Ignore every colour-dependent item in the list above (colour "
            "temperature shifts, saturated accents, desaturation); reach for the "
            "ink techniques instead — heavy blacks, hatching, halftone, speed "
            "lines, focus lines, white slash trails.")
    # 장르가 있으면 톤의 상한을 말해 준다. 실사용자 지적(2026-08): 로맨스 판타지를
    # 골랐는데 "덫에 걸린 생쥐" 장면이 피 묻은 덫과 새빨간 조명의 공포 연출로
    # 나왔다 — "공포 느낌을 따로 작성하지 않았는데 뭔가 공포 분위기로 간 것 같다."
    #
    # 원인은 이 단계가 **소재만 보고 톤을 정하기 때문**이다. 덫·숲·밤이라는
    # 낱말만 있으면 모델은 그 조합의 가장 극적인 그림(=공포)으로 간다. 장르는
    # 여기까지 한 번도 전달된 적이 없었다 (scenegen 전체에 genre 가 없었다).
    warn = genre_tone_guard(cfg)
    if warn:
        rows.append("")
        rows.append(warn)
    return "\n".join(rows)


# 어두운 톤이 **장르상 맞는** 장르들. 여기 속하면 톤 상한을 걸지 않는다.
DARK_GENRES = ("스릴러", "공포", "호러", "오컬트", "좀비", "느와르", "미스터리",
               "thriller", "horror", "occult", "zombie", "noir", "mystery")

GENRE_TONE_GUARD = (
    "TONE CEILING — this episode's genre is {genre}, which is NOT a horror or "
    "thriller genre. Do not let the subject matter alone push the panel into "
    "horror. A trap, a forest at night, an injured animal, a dark corridor or a "
    "wound is a situation, not a horror scene: draw it with the tension the "
    "story asks for and no more. Specifically, do NOT reach for blood-red or "
    "sickly green key light, blood smears, gore, dread-filled negative space, "
    "or a threatening presence in the dark unless the scene's own mood line "
    "explicitly calls for fear. When a night or forest scene needs atmosphere, "
    "reach for cool moonlight, blue and green shadow, mist and warm lantern "
    "light instead."
)


def genre_tone_guard(cfg: dict[str, Any] | None) -> str:
    """장르가 어두운 계열이 아니면 톤 상한 문구를 준다. 장르가 없으면 빈 문자열.

    장르를 config 에 안 넣은 예전 run 은 빈 문자열이라 프롬프트가 안 바뀐다.
    """
    genre = str((cfg or {}).get("genre") or "").strip()
    if not genre:
        return ""
    low = genre.lower()
    if any(word in low for word in DARK_GENRES):
        return ""
    return GENRE_TONE_GUARD.format(genre=genre)


def build_prompt(template: str, title: str, scenes: list[Scene],
                 setting: dict[str, Any] | None = None,
                 story_scenes: list | None = None,
                 cfg: dict[str, Any] | None = None) -> str:
    payload = []
    for sc in scenes:
        row = {"scene_number": sc.scene_number}
        row.update(scene_intent(story_scenes or [], sc.scene_number))
        row["cuts"] = [_cut_for_prompt(c) for c in sc.cuts]
        payload.append(row)
    # 이번 화 컷 서술·대사에 등장하는 태그와 겹치는 연출 지식만 골라 붙인다 —
    # story-harness 의 resolve_directing_notes 와 같은 저장소, 같은 방식.
    haystack = " ".join(
        f"{c.get('description', '')} {c.get('dialogue', '')}"
        for row in payload for c in row["cuts"])
    directing_notes = directing.resolve_notes(directing.DEFAULT_ROOT, haystack)
    return (template.replace("{episode_title}", title)
                    .replace("{scene_count}", str(len(scenes)))
                    .replace("{staging}", staging_text(setting))
                    .replace("{treatment_guide}", treatment_text(cfg))
                    .replace("{directing_notes}", directing_notes or "(none)")
                    .replace("{scenes_json}", json.dumps(payload, ensure_ascii=False, indent=2)))


def overlay_lines(cuts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """뷰어가 그림 위에 얹을 글자들. 대사·나레이션·속마음.

    표시 규약은 bubbles.is_narration 이 이미 쓰던 것을 따른다:
      대사    그대로
      나레이션 [대괄호]
      속마음   (소괄호)
    효과음은 여기 없다 — 그림 안에 레터링으로 그려지기 때문이다.
    한 컷에 여럿이 있으면 여러 줄이 된다.
    """
    out: list[dict[str, Any]] = []
    for c in cuts:
        num = int(c["cut_number"])
        zone = str(c.get("bubble_zone") or "none").strip().lower()
        for key, wrap in (("dialogue", "{}"), ("narration", "[{}]"),
                          ("thought", "({})")):
            text = str(c.get(key) or "").strip()
            if text:
                out.append({"cut": num, "text": wrap.format(text), "kind": key,
                            # 콘티가 정해 둔 자리. 사람이 사각형을 그리기 전까지
                            # 자동 배치의 근거가 된다 (bubbles.auto_regions).
                            "zone": zone})
        # 화면 안 글자는 말풍선이 아니라 화면 UI 로 얹힌다. 자리는 그 화면이
        # 어디 있는지에 달려 있어서 콘티가 정할 수 없다 — 사람이 그린다.
        screen = str(c.get("screen_text") or "").strip()
        if screen:
            out.append({"cut": num, "text": screen, "kind": "screen_text",
                        "zone": "none"})
    return out


# 콘티(한글) -> 이미지 프롬프트(영어). 콘티가 거리와 앵글을 **직교하는 두 축**으로
# 정하므로 여기서도 따로 옮긴다. 한 낱말로 뭉치면 같은 클로즈업이 올려다본 것인지
# 내려다본 것인지가 사라진다.
SHOT_EN = {
    "원경": "extreme wide shot, figures small in the environment",
    "전신": "full shot, the whole figure visible head to toe",
    "중간": "medium shot from the waist up",
    "바스트": "medium close-up, chest up",
    "클로즈업": "close-up filling the frame with the face",
    "익스트림": "extreme close-up on a single detail (eyes, hand, object)",
    "인서트": "insert shot of an object or detail, no face in frame",
}
ANGLE_EN = {
    "수평": "eye-level angle",
    "부감": "high angle looking down, the subject made smaller",
    "앙각": "low angle looking up, the subject made larger",
    "수직": "top-down bird's-eye view",
    "기울임": "dutch tilt, the horizon visibly canted",
}


def _cut_for_prompt(c: dict[str, Any]) -> dict[str, Any]:
    """LLM 에 넘길 컷 한 개. 연출이 붙어 있으면 gaze 와 beat 도 같이 넘긴다.

    gap_after 와 scene_break 은 넘기지 않는다. 그 둘은 이미 Scene 을 어떻게 나눌지로
    반영되었고, 패널 안에 그릴 수 있는 것이 아니다. gaze 만 그림의 내용이다.
    """
    out = {"cut_number": c["cut_number"],
           "description": c.get("description") or "",
           "dialogue": c.get("dialogue") or ""}
    # 텍스트 세 종류를 더 넘긴다. narration/thought 는 **빈 상자를 그리게** 하려는
    # 것이고(글자는 뷰어가 얹는다), sfx 는 **그 낱말 그대로** 그리게 하려는 것이다.
    # 예전에는 scene_gen 이 서술을 보고 효과음을 지어냈다 — 이제 W7 이 정한다.
    for key in ("narration", "thought", "sfx"):
        if str(c.get(key) or "").strip():
            out[key] = str(c[key]).strip()
    if c.get("gaze"):
        out["gaze"] = str(c["gaze"])
    if c.get("beat"):
        out["beat"] = str(c["beat"])
    # 카메라. 콘티가 낱말로 정한 것을 영어 샷 용어로 옮겨 넘긴다 — 안 넘기면
    # 그림 쪽 LLM 이 거리를 매번 임의로 정하고, 그러면 컷 60% 가 얼굴이 된다
    # (콘티에서 그 비율을 세어 막는 이유가 그림에 닿지 않는다).
    if SHOT_EN.get(str(c.get("shot") or "").strip()):
        out["shot"] = SHOT_EN[str(c["shot"]).strip()]
    if ANGLE_EN.get(str(c.get("angle") or "").strip()):
        out["angle"] = ANGLE_EN[str(c["angle"]).strip()]
    # 화자 — 말풍선 꼬리를 누구에게 붙일지. 없으면 그리는 쪽이 짐작한다.
    if str(c.get("speaker") or "").strip():
        out["speaker"] = str(c["speaker"]).strip()
    return out


def fill_panels(scenes: list[Scene], parsed: Any) -> list[int]:
    """LLM 응답을 Scene 에 채우고, 패널을 못 받은 Scene 번호를 돌려준다."""
    raw = parsed.get("scenes") if isinstance(parsed, dict) else parsed
    if not isinstance(raw, list):
        raise SceneError(f"scene_gen 응답에서 scenes 를 찾지 못했습니다: {str(parsed)[:200]}")

    by_cut: dict[int, str] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        for p in item.get("panels") or []:
            if not isinstance(p, dict):
                continue
            try:
                by_cut[int(p["cut_number"])] = str(p.get("scene") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue

    missing: list[int] = []
    for sc in scenes:
        sc.panels = [by_cut.get(n, "") for n in sc.cut_numbers]
        if not all(sc.panels):
            missing.append(sc.scene_number)
    return missing


def to_json(scenes: list[Scene]) -> list[dict[str, Any]]:
    return [{"scene_number": sc.scene_number,
             "cut_numbers": sc.cut_numbers,
             "layout": sc.layout,
             "panels": sc.panels,
             # 연출 — 뷰어가 여백을 그릴 때 쓴다. 연출이 없으면 전부 기본값이다.
             "gap_after": sc.gap_after,
             "beats": sc.beats,
             "gazes": [str(c.get("gaze") or "") for c in sc.cuts],
             # 대사는 이미지에 그리지 않는다. 말풍선으로 얹으려면 컷별로 남아 있어야 한다.
             "dialogues": overlay_lines(sc.cuts),
             # 9단계가 고른 바탕 컷. 캐시에서 다시 읽을 때 이게 없으면 크기로
             # 다시 골라 버려서, 같은 run 을 재실행하면 배치가 달라진다.
             "base_cut": sc.base_cut,
             "warnings": sc.warnings} for sc in scenes]


def from_json(data: list[dict[str, Any]], cuts: list[dict[str, Any]]) -> list[Scene]:
    """scenes.json 캐시 → Scene 목록. 컷 번호가 안 맞으면 SceneError."""
    by_num = {int(c["cut_number"]): c for c in cuts}
    out: list[Scene] = []
    for item in data:
        try:
            nums = [int(n) for n in item["cut_numbers"]]
            picked = [by_num[n] for n in nums]
        except (KeyError, TypeError, ValueError) as exc:
            raise SceneError(f"{CACHE_FILE} 이 지금 컷과 맞지 않습니다: {exc}") from exc
        out.append(Scene(scene_number=int(item["scene_number"]), cuts=picked,
                         panels=[str(p) for p in item.get("panels") or []],
                         layout=str(item.get("layout") or ""),
                         base_cut=(int(item["base_cut"])
                                   if item.get("base_cut") is not None else None),
                         warnings=[str(w) for w in item.get("warnings") or []]))
    return out
