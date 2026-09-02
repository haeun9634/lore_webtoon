#!/usr/bin/env python3
"""컷을 이미지 생성 단위(페이지)로 묶는다.

콘티는 컷 단위로 나오지만 그림은 컷 단위로 부르지 않는다. 무거운 컷은 혼자
한 장을 쓰고, 가벼운 컷들은 한 장에 모아 그린다 — 붙은 컷을 따로 그리면
이음매에서 배경이 어긋나고, 호출 수도 그만큼 늘어난다.

    large · full   -> 혼자 한 페이지
    tiny · small · normal -> 순서대로 모으다가 large/full 을 만나면 거기서 끊는다

컷 순서는 어떤 경우에도 바뀌지 않는다. 페이지를 순서대로 이어 붙이면 원래
컷 배열이 그대로 나온다.
"""

from __future__ import annotations

# storyboard_prompt 의 "크기" 값과 같다.
ALONE = ("large", "full")             # 혼자 한 페이지
GROUPED = ("tiny", "small", "normal")  # 모아서 한 페이지
SIZES = GROUPED + ALONE

DEFAULT_MAX_PER_PAGE = 5

# 컷 높이 비율. 이미지 프롬프트가 쓰는 표와 같은 값이다
# (imageprompt.HEIGHT_RATIO). 여기 있는 것은 **모아 그리는 컷** 기준이라
# large/full 은 어차피 혼자 한 장이므로 합계에 안 들어간다.
HEIGHT_RATIO = {"tiny": 1, "small": 2, "normal": 3, "large": 5, "full": 99}

# 한 페이지의 높이 비율 합계 상한.
#
# 개수만으로 끊으면 normal 다섯 개(합계 15)가 한 장에 들어간다. 페이지는 이미지
# **한 장**이고 그 장의 모양은 정해져 있으므로, 컷을 많이 넣을수록 각 컷이 그
# 안에서 납작해진다. 페이지의 세로/가로를 A, 합계를 R 이라 하면 normal 한 컷의
# 가로:세로는
#
#     R / (3 x A)
#
#     A=1.78, R=15  ->  2.8 : 1   (띠. 인물 상반신도 답답하다)
#     A=1.78, R= 9  ->  1.7 : 1
#     A=1.78, R= 6  ->  1.1 : 1   (거의 정사각. 페이지가 늘어 호출이 더 나간다)
#
# 그래서 상한은 **캔버스 모양에서 나온다.** 목표 컷 모양을 1.7:1 로 두면
# R = 3 x A x 1.7 = 5.1 x A 다. 캔버스가 프로바이더마다 다르므로(imagegen 참고)
# 이 값도 따라 움직여야 한다:
#
#     Gemini  9:16      A=1.78  ->  9
#     OpenAI  1024x1536 A=1.50  ->  8
TARGET_PANEL_ASPECT = 1.7      # normal 컷의 가로:세로. 웹툰 보통 컷은 조금 가로로 길다
DEFAULT_PAGE_ASPECT = 1.78     # 안 알려주면 Gemini 9:16 으로 본다


def max_ratio_for(page_aspect: float = DEFAULT_PAGE_ASPECT) -> int:
    """캔버스 세로/가로 -> 한 페이지의 높이 비율 합계 상한."""
    return max(HEIGHT_RATIO["normal"],
               round(HEIGHT_RATIO["normal"] * page_aspect * TARGET_PANEL_ASPECT))


DEFAULT_MAX_RATIO = max_ratio_for()

# 콘티 파서는 한글 키로 저장하고(run.parse_board), 손으로 만든 입력은 보통
# size 로 쓴다. 둘 다 받는다 — 키 이름 때문에 묶기가 실패하면 원인을 찾기가
# 그림이 이상한 것보다 어렵다.
SIZE_KEYS = ("size", "크기")


def cut_size(cut) -> str:
    """컷의 크기. 모르는 값이면 normal 로 본다.

    모델이 낸 것을 읽는 자리라 대소문자나 오타 하나로 멈추지 않는다.
    normal 로 두면 그 컷은 "모아서 그리는 보통 컷" 이 된다 — 혼자 한 장을
    차지하는 쪽보다 되돌리기 쉬운 실수다.
    """
    if not isinstance(cut, dict):
        return "normal"
    for key in SIZE_KEYS:
        value = str(cut.get(key) or "").strip().lower()
        if value:
            return value if value in SIZES else "normal"
    return "normal"


def group_pages(cuts, max_per_page: int = DEFAULT_MAX_PER_PAGE,
                max_ratio: int | None = DEFAULT_MAX_RATIO) -> list[list]:
    """컷 배열 -> 페이지 배열. 각 페이지는 컷 배열이다.

    개수(max_per_page)와 높이 비율 합계(max_ratio) 둘 중 **먼저 걸리는 쪽**에서
    끊는다. max_ratio=None 이면 개수로만 끊는다 — 그러면 normal 다섯 개가 한
    장에 들어가고, 9:16 캔버스에서 각 컷이 2.8:1 띠가 된다(DEFAULT_MAX_RATIO
    주석의 산수 참고).
    """
    if max_per_page < 1:
        raise ValueError(f"max_per_page 는 1 이상이어야 합니다 (받은 값: {max_per_page})")
    if max_ratio is not None and max_ratio < 1:
        raise ValueError(f"max_ratio 는 1 이상이어야 합니다 (받은 값: {max_ratio})")

    pages: list[list] = []
    holding: list = []

    def flush() -> None:
        if holding:
            pages.append(holding.copy())
            holding.clear()

    for cut in cuts or []:
        size = cut_size(cut)
        if size in ALONE:
            flush()                 # 모으던 것을 여기서 끊고
            pages.append([cut])     # 이 컷은 혼자 한 장
            continue
        # 이 컷을 얹으면 비율 합계가 넘치는가. **얹기 전에** 본다 — 넘긴 뒤
        # 끊으면 상한을 이미 넘은 페이지가 나간다.
        if max_ratio is not None and holding:
            here = sum(HEIGHT_RATIO[cut_size(c)] for c in holding)
            if here + HEIGHT_RATIO[size] > max_ratio:
                flush()
        holding.append(cut)
        if len(holding) == max_per_page:
            flush()
    flush()
    return pages


# 배경이 없다시피 한 컷 — 무게(cut_weight)와 이어짐(linked) 판정에 같이 쓴다.
NO_BG = ("없음", "단색", "그라데이션")


def _t(value) -> str:
    return str(value).strip() if value not in (None, "") else ""


def cut_weight(cut) -> str:
    """컷의 무게: full(혼자 한 페이지) · light(배경 없이 가벼움) · normal.

    새 필드를 만들지 않는다 — size 는 이미 ALONE/GROUPED 를 가르고,
    background.type 은 이미 컷마다 있는 값이다. light 는 그 둘에서 그대로
    끌어낸다: tiny·small 이면서 배경이 없다시피 한(NO_BG) 컷은 페이지 안에서
    폭을 좁게 잡아도 되는 컷이라는 뜻이다 — 인물만 그리면 되므로.

    large·full 은 애초에 혼자 한 페이지를 쓰므로(ALONE) light 로 안 내려간다.
    """
    size = cut_size(cut)
    if size in ALONE:
        return "full"
    background = cut.get("background") if isinstance(cut, dict) else None
    kind = _t((background or {}).get("type")) if isinstance(background, dict) else ""
    if size in ("tiny", "small") and kind in NO_BG:
        return "light"
    return "normal"


def linked(prev_cut, cut) -> bool:
    """`cut` 이 `prev_cut` 과 배경이 그대로 이어지는가 (카메라만 움직인다).

    같은 장소·시간대에 둘 다 실제공간 배경일 때만 참이다. large·full 은
    장면 전환이나 인물의 첫 등장(원칙 6)에 쓰이는 크기라 이어 붙이면 안
    되므로 뺀다. `prev_cut` 이 없으면(페이지의 첫 컷) 항상 거짓이다.

    flatten_cuts 가 내려보낸 location·time 을 그대로 쓴다 — 이 함수는 편
    구성이 끝난 뒤(페이지로 묶은 뒤) 컷 순서대로만 불린다.
    """
    if not isinstance(prev_cut, dict) or not isinstance(cut, dict):
        return False
    if cut_size(prev_cut) in ALONE or cut_size(cut) in ALONE:
        return False
    place = _t(cut.get("location"))
    if not place or _t(prev_cut.get("location")) != place:
        return False
    if _t(prev_cut.get("time")) != _t(cut.get("time")):
        return False
    prev_bg = _t((prev_cut.get("background") or {}).get("type"))
    bg = _t((cut.get("background") or {}).get("type"))
    return prev_bg == "실제공간" and bg == "실제공간"


def page_weight(page) -> str:
    """페이지 전체의 무게 — 이어 붙일 때(stitch.py) 폭을 얼마나 쓸지 결정한다.

    group_pages 가 이미 ALONE(large/full)은 혼자 한 페이지로 떼어 두므로,
    여기서 다시 나눌 건 없다. **모아 묶인 컷이 전부** light(배경 없는
    tiny/small)이면 그 페이지 전체가 떠 있는 것으로 본다 — 인물만 있고
    배경이 없는 컷들만 모인 페이지라, 지면을 꽉 채울 이유가 없다.
    """
    if not page:
        return "normal"
    if all(cut_weight(c) == "light" for c in page):
        return "light"
    return "normal"


def page_gap_after(page, next_page) -> int:
    """`page` 뒤, `next_page` 앞에 얼마나 벌릴지 (0~3).

    story-harness 의 `derive_layout`은 beat·transition·render_style 로
    이걸 정하는데, new_harness 콘티에는 그 필드가 없다. 대신 있는 것 —
    이어지는가(linked) · 앞 페이지 마지막 컷이 large/full 인가(전환점을
    막 지났는가) · 장소가 바뀌었는가 — 로 같은 취지를 낸다:

        이어짐(linked)              -> 0  (동작이 그대로 계속된다, 안 벌린다)
        직전 컷이 large/full        -> 3  (전환점 뒤. 숨 돌릴 자리를 준다)
        장소가 바뀜                 -> 2  (장면이 넘어간다)
        나머지                      -> 1  (기본)

    반환값은 그대로 `strip.gap_px(width, level, table)`에 먹인다 — 픽셀
    변환은 새로 안 만들고 webtoon-harness 것을 그대로 쓴다.
    """
    if not page or not next_page:
        return 1
    last, first = page[-1], next_page[0]
    if linked(last, first):
        return 0
    if cut_size(last) in ALONE:
        return 3
    if _t(last.get("location")) != _t(first.get("location")):
        return 2
    return 1


# 장면에 붙는 값 중 컷까지 따라 내려가야 하는 것.
# 페이지는 장면 경계를 안 지키므로(가벼운 컷은 장면을 넘어 모인다), 여기서
# 안 내려보내면 페이지를 만든 뒤에는 그 컷이 어디서 벌어지는지 알 수 없다.
CARRY_DOWN = ("location", "time")


def flatten_cuts(scenes) -> list:
    """board.json 의 장면 배열 -> 컷 하나짜리 배열.

    어느 장면의 몇 번째 컷이었는지를 scene·cut 에 남긴다 — 편 뒤에는 그
    자리를 다시 알 길이 없고, 페이지를 만든 뒤에도 "장면 2 의 1컷" 을 짚을
    수 있어야 한다. 장소·시간대도 같이 내려보낸다(CARRY_DOWN).
    """
    out = []
    for scene in scenes or []:
        carried = {k: scene[k] for k in CARRY_DOWN if str(scene.get(k) or "").strip()}
        for cut in scene.get("cuts") or []:
            # 컷이 스스로 적은 값이 있으면 그것을 남긴다 — 장면 값으로 덮지 않는다.
            out.append(dict(carried, **cut,
                            scene=scene.get("id"), cut=cut.get("id")))
    return out


# ------------------------------------------------------------------- 사건

# 구체화(detail.json)에서 그림 한 장이 되는 단위의 칸. 장면과 사건이 같은
# 칸을 쓴다 — 옛 run 은 장면 자체가 사건 하나이기 때문이다(아래 참고).
EVENT_FIELDS = ("source", "function", "detail", "learns", "guesses",
                "continuity", "leads_to")


def detail_events(scene) -> list:
    """장면 하나 -> 사건 배열. **사건 하나가 그림 한 장이다.**

    장면 하나에는 사건이 여러 개 들어 있다 — "일어난다 / 시계를 본다 /
    나간다 / 마주친다 / 인사한다 / 아침을 차린다 / 질문을 받는다" 가 한
    장면이었다. 이것을 한 장에 다 그리게 하면 그림이 산만해지고, 그렇다고
    컷을 하나씩 지정하면 연출을 사람이 다 짜는 것이 된다. 그래서 **사건**
    에서 끊는다 — 그림 모델은 사건 하나를 받아 컷 수·구도·여백을 스스로
    정한다.

    **사건 칸이 없는 옛 detail.json 은 장면 자체를 사건 하나로 읽는다.**
    그러면 옛 run 은 예전처럼 장면당 그림 한 장이라 결과가 안 바뀐다.
    """
    got = [e for e in (scene.get("events") or []) if isinstance(e, dict)]
    if got:
        return got
    one = {k: scene[k] for k in EVENT_FIELDS if k in scene}
    one["id"] = 1
    return [one]


def flatten_events(scenes) -> list:
    """detail.json 의 장면 배열 -> 사건 하나짜리 배열.

    어느 장면의 몇 번째 사건이었는지를 scene·event 에 남긴다 — 편 뒤에는 그
    자리를 다시 알 길이 없다. **장면 경계를 넘어 이어 편다**: 사건 사이의
    이어짐(continuity)은 장면이 바뀌는 자리에서도 끊기면 안 되고, 그림도
    바로 앞 사건의 그림을 참조로 받는다.
    """
    out = []
    for scene in scenes or []:
        for i, ev in enumerate(detail_events(scene), 1):
            out.append(dict(ev, scene=scene.get("id"), event=ev.get("id", i)))
    return out
