#!/usr/bin/env python3
"""페이지 하나 -> 이미지 생성 프롬프트 하나.

콘티(board.json)는 구조화된 JSON 이지만 이미지 모델은 JSON 을 읽는 물건이
아니다. 여기서 그것을 사람이 읽는 문장으로 되돌린다.

무엇을 **빼는지**가 이 파일의 절반이다. 콘티에는 그림에 안 그려지는 칸이
섞여 있다 — note(연출 의도 메모) · sfx[].reason(왜 넣었는지) ·
scenes[].summary(원본 장면 문장). 그대로 넘기면 모델이 메모를 그림으로
그린다. 그려지는 것은 dialogue[].text 와 sfx[].text 뿐이다.

고정 블록은 prompt/image_prompt 에 있다. 여기서는 컷 데이터만 만든다.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROMPT_DIR = HERE / "prompt"
WEBTOON_HARNESS = HERE.parent / "webtoon-harness"
if str(WEBTOON_HARNESS) not in sys.path:
    sys.path.append(str(WEBTOON_HARNESS))     # append, 안 insert(0,...) — new_harness
                                               # 자신의 모듈(run.py 등 이름이 겹치는
                                               # 것)을 가리면 안 된다

import directing  # noqa: E402  (webtoon-harness 것을 그대로 빌린다)

# 컷 높이 비율. full 은 숫자가 아니라 페이지 전체다.
HEIGHT_RATIO = {"tiny": 1, "small": 2, "normal": 3, "large": 5, "full": None}

# 대사 종류 -> 말풍선 모양. 콘티가 bubble.shape 를 적어 주면 그것을 쓰고,
# 비어 있을 때만 이 표로 채운다.
SHAPE_FOR = {
    "말": "둥근 타원",
    "생각": "구름",
    "외침": "뾰족",
    "화면밖": "둥근 타원",
    "나레이션": "네모 상자",
}
# 꼬리를 그릴 수 없는 것들 — 말하는 사람이 화면에 없거나 애초에 소리가 아니다.
NO_TAIL = ("나레이션", "글")

# 이미 "여기까지" 를 품고 있는 범위 표현. 뒤에 "까지" 를 또 붙이면
# "손만까지 나온다" 가 된다 (person_line 참고).
LIMITED = ("만", "뿐", "일부")


def _t(value) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _eul(word: str) -> str:
    """받침에 맞는 목적격 조사. `직전을` · `직후를`.

    조사를 하나로 박으면 프롬프트에 "직후을" 이 나간다. 사람은 읽어 넘기지만
    이 문장은 이미지 모델이 읽는 문장이고, 어색한 한국어는 그만큼 덜 또렷한
    지시다.
    """
    last = (word or "")[-1:]
    if not last or not ("가" <= last <= "힣"):
        return "를"
    return "을" if (ord(last) - 0xAC00) % 28 else "를"


def camera_line(camera) -> str:
    """{shot, angle} -> `상반신, 정면 앵글`.

    facing(인물이 카메라 쪽으로 어느 면을 보이는가)은 여기 없다 — 인물마다
    다를 수 있어서 person_line 에서 인물별로 적는다.
    """
    camera = camera if isinstance(camera, dict) else {}
    shot, angle = (_t(camera.get(k)) for k in ("shot", "angle"))
    return ", ".join(p for p in (
        shot,
        f"{angle} 앵글" if angle else "") if p)


def background_line(background) -> str:
    """{type, desc} -> `실제공간 — 높은 천장과 …`."""
    background = background if isinstance(background, dict) else {}
    kind, desc = _t(background.get("type")), _t(background.get("desc"))
    if kind and desc:
        return f"{kind} — {desc}"
    return kind or desc


def person_line(who) -> str:
    """인물 하나 -> 한 문장.

    칸이 비면 그 조각만 빠진다 — 모델이 낸 것을 읽는 자리라, 칸 하나를 안
    채웠다고 그 인물을 통째로 버리는 쪽이 더 나쁘다.
    """
    who = who if isinstance(who, dict) else {}
    name, style = _t(who.get("name")), _t(who.get("style"))
    where, moment = _t(who.get("position")), _t(who.get("moment"))
    facing, face, act, frame = (_t(who.get(k))
                                 for k in ("facing", "expression", "action", "framing"))

    head = f"{name} ({style})" if style else name
    body = ", ".join(p for p in (f"화면 {where}" if where else "",
                                  f"{facing}" if facing else "", face, act) if p)
    out = f"{head}: {body}" if body else head
    if moment:
        out += f". 동작의 {moment}{_eul(moment)} 그린다"
    if frame:
        # framing 은 값 목록이 없는 자유 텍스트다 ("상반신" · "무릎 위" · "손만" ·
        # "손과 눈 일부"). "까지" 를 한 가지로 박으면 "손만까지 나온다" 가 된다.
        tail = " 나온다" if frame.endswith(LIMITED) else "까지 나온다"
        out += f". 화면에는 {frame}{tail}"
    return out + "."


def bubble_line(line) -> list[str]:
    """대사 하나 -> [모양·꼬리·위치 줄, 글자 줄].

    글자는 **한 글자도 안 바꾼다.** 여기서 손대면 그림에 다른 말이 그려진다.
    """
    line = line if isinstance(line, dict) else {}
    kind = _t(line.get("type"))
    speaker = _t(line.get("speaker"))
    text = _t(line.get("text"))
    bubble = line.get("bubble") if isinstance(line.get("bubble"), dict) else {}
    shape, tail, where = (_t(bubble.get(k)) for k in ("shape", "tail", "position"))

    if kind == "글":
        spot = where or "화면이나 종이"
        head = f"말풍선 아님 — {spot}에 적힌 글로 그린다"
        return [f"  - {head}", f'    "{text}"']

    parts = [shape or SHAPE_FOR.get(kind, "둥근 타원")]
    if kind not in NO_TAIL:
        if tail in ("없음", "no", "none"):
            parts.append("꼬리 없음")
        elif tail:
            # "컷 바깥" 은 방향이지 사람이 아니다 — 조사를 붙이면 말이 안 된다.
            parts.append(f"꼬리는 {tail}으로" if tail == "컷 바깥"
                         else f"꼬리는 {tail}을 향함")
        elif speaker:
            parts.append(f"꼬리는 {speaker}을 향함")
    if where:
        parts.append(f"위치 {where}")
    return [f"  - {' / '.join(parts)}", f'    "{text}"']


def sfx_line(one) -> str:
    """효과음 하나. reason 은 검토용이라 **넣지 않는다.**"""
    one = one if isinstance(one, dict) else {}
    text, where = _t(one.get("text")), _t(one.get("position"))
    return f'  - "{text}"' + (f" / 위치 {where}" if where else "")


def cut_size(cut) -> str:
    import pages
    return pages.cut_size(cut)


def cut_block(cut, number: int, with_place: bool = False, linked: bool = False) -> str:
    """컷 하나 -> 프롬프트 조각.

    with_place 면 장소·시간대를 이 컷에 붙인다. 페이지 전체가 한 장소일 때는
    앞에서 한 번만 적으므로(place_block) 여기서는 끈다.

    linked 면 이 컷이 앞 컷과 배경이 그대로 이어진다는 문구를 붙인다
    (pages.linked 로 판정한 값을 그대로 받는다 — 여기서 다시 안 잰다).
    """
    import pages
    cut = cut if isinstance(cut, dict) else {}
    size = cut_size(cut)
    ratio = HEIGHT_RATIO.get(size)
    lines = [f"### 컷 {number} (높이 비율 {ratio})" if ratio
             else f"### 컷 {number} (페이지 전체)"]

    if with_place:
        for key, label in (("location", "장소"), ("time", "시간대")):
            value = _t(cut.get(key))
            if value:
                lines.append(f"{label}: {value}")

    camera = camera_line(cut.get("camera"))
    if camera:
        lines.append(f"카메라: {camera}")

    background = background_line(cut.get("background"))
    if background:
        lines.append(f"배경: {background}")
    if linked:
        lines.append("이 배경은 앞 컷에서 그대로 이어진다 — 새로 그리지 않고 "
                     "카메라만 움직인 것처럼 그린다.")

    if pages.cut_weight(cut) == "light":
        lines.append("무게: 배경 없이 인물만 그린다 — 페이지 안에서 이 컷은 "
                     "폭을 좁게 잡는다.")

    people = [p for p in (cut.get("characters") or []) if isinstance(p, dict)]
    if people:
        lines.append("인물:")
        lines += [f"  - {person_line(p)}" for p in people]

    speech = [d for d in (cut.get("dialogue") or [])
              if isinstance(d, dict) and _t(d.get("text"))]
    if speech:
        lines.append("말풍선:")
        for one in speech:
            lines += bubble_line(one)

    sfx = [s for s in (cut.get("sfx") or [])
           if isinstance(s, dict) and _t(s.get("text"))]
    if sfx:
        lines.append("효과음 (말풍선 없이 글자만 그린다):")
        lines += [sfx_line(s) for s in sfx]

    forbid = [_t(f) for f in (cut.get("forbid") or []) if _t(f)]
    if forbid:
        lines.append("그리지 않을 것: " + " / ".join(forbid))

    # note 는 여기 없다 — 연출 의도 메모라 그림에 안 그려진다.
    return "\n".join(lines)


def sheet_line(spec: dict) -> str:
    """sheet_spec.json -> 캐릭터 시트 한 사람 몫."""
    parts = [f"{spec.get('name') or '이름 없음'} — {spec.get('appearance_en') or ''}".strip()]
    details = spec.get("design_details") or []
    if details:
        parts.append("       고정 요소: " + " / ".join(details))
    props = spec.get("props") or []
    if props:
        parts.append("       소지품: " + " / ".join(props))
    return "\n".join(parts)


def cast_lines(cast, page=None, skip=()) -> list[str]:
    """board.json 의 cast -> 시트 줄. page 를 주면 **그 페이지에 나오는 사람만.**

    안 나오는 사람까지 적으면 모델이 그 사람을 화면에 넣는다 — 고정 블록의
    "지정되지 않은 인물을 추가하지 않는다" 와 정면으로 부딪힌다.

    skip 에 든 이름은 뺀다. **시트 사양이 있는 인물이 여기 해당한다** —
    콘티의 cast 에도 주인공이 들어 있어서, 안 빼면 같은 인물의 외형이 두 번
    나가고 둘이 어긋난다(시트는 "분홍 망토 + 흰 옷", cast 는 "하얀 옷").
    자세하고 그림까지 있는 시트 쪽이 기준이다.
    """
    here = None
    if page is not None:
        here = {_t(p.get("name")) for cut in page
                for p in (cut.get("characters") or []) if isinstance(p, dict)}
    skip = {_t(s) for s in skip if _t(s)}
    out = []
    for one in cast or []:
        if not isinstance(one, dict):
            continue
        name, look = _t(one.get("name")), _t(one.get("appearance"))
        if not name or name in skip or (here is not None and name not in here):
            continue
        out.append(f"{name} — {look}" if look else name)
    return out


DEFAULT_STYLE = "webtoon_lock_bg"


def load_style(name: str = "") -> str:
    """그림체 문구. prompt/style/<이름> 에 있다.

    **코드가 아니라 데이터다.** 그림체를 바꾸는 것은 .env 의 PAGE_STYLE 한
    줄이고, 새 그림체를 만드는 것은 prompt/style/ 에 파일 하나를 더 놓는
    일이다. 여기가 비어 있으면 매번 다른 그림이 나온다 — 선 굵기·채색·명암·
    색조가 안 적힌 프롬프트는 모델에게 아무 말도 안 한 것과 같다.
    """
    name = (name or "").strip() or DEFAULT_STYLE
    path = PROMPT_DIR / "style" / name
    if not path.exists():
        have = sorted(p.name for p in (PROMPT_DIR / "style").glob("*")) or ["(없음)"]
        raise SystemExit(f"그림체가 없습니다: {path}\n"
                         f"        있는 것: {', '.join(have)}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"그림체가 비어 있습니다: {path}")
    return "\n".join("  " + ln if ln.strip() else ln for ln in text.splitlines())


def load_fixed_block(provider: str = "", style: str = "") -> str:
    """고정 블록. 프로바이더 전용 파일이 있으면 그것을 쓴다.

        prompt/image_prompt.openai   GPT 로 그릴 때
        prompt/image_prompt.gemini   Gemini 로 그릴 때
        prompt/image_prompt          없을 때 쓰는 공통

    나누는 이유는 캔버스 모양과 참조 이미지를 부르는 방식이 다르기 때문이다.
    OpenAI 는 참조가 붙으면 편집 쪽으로 가서 "이 그림을 고쳐라" 에 가깝게
    읽으므로, "새로 그린다" 를 더 세게 말해 줘야 한다.
    """
    name = (provider or "").strip().lower()
    for cand in ([PROMPT_DIR / f"image_prompt.{name}"] if name else []) + \
                [PROMPT_DIR / "image_prompt"]:
        if cand.exists():
            text = cand.read_text(encoding="utf-8").strip()
            if text:
                return text.replace("{style}", load_style(style))
            raise SystemExit(f"프롬프트가 비어 있습니다: {cand}")
    raise SystemExit(f"프롬프트가 없습니다: {PROMPT_DIR / 'image_prompt'}")


def place_block(page) -> str:
    """페이지 전체가 한 장소면 그것을 앞에 한 번 적는다. 아니면 빈 문자열.

    페이지마다 따로 호출하므로, 장소를 안 적으면 같은 홀이 페이지마다 다른
    홀로 그려진다. 한 페이지 안에서 장소가 갈리면 여기서 뭉뚱그리지 않고
    컷마다 적는다(cut_block) — 틀린 하나를 앞에 크게 박는 것이 제일 나쁘다.
    """
    places = {_t(c.get("location")) for c in (page or [])}
    times = {_t(c.get("time")) for c in (page or [])}
    if len(places) != 1 or not places.pop():
        return ""
    lines = ["## 장소", _t(page[0].get("location"))]
    if len(times) == 1:
        one = times.pop()
        if one:
            lines.append(f"시간대: {one}")
    return "\n".join(lines)


def page_haystack(page) -> str:
    """이 페이지의 컷들에서 연출 지식을 태그로 골라 붙일 때 검색할 서술.

    webtoon-harness 의 scenegen.build_prompt 와 같은 방식(설명+대사를
    이어 붙인 문자열, 정확 태그 매칭)이다. note·sfx.reason 같은 안 그려지는
    칸은 안 섞는다 — 태그 매칭이 그림에 없는 내용으로 걸릴 이유가 없다.
    """
    parts = []
    for cut in page or []:
        parts.append(background_line(cut.get("background")))
        for p in cut.get("characters") or []:
            if isinstance(p, dict):
                parts.append(_t(p.get("action")))
                parts.append(_t(p.get("expression")))
        for d in cut.get("dialogue") or []:
            if isinstance(d, dict):
                parts.append(_t(d.get("text")))
        for s in cut.get("sfx") or []:
            if isinstance(s, dict):
                parts.append(_t(s.get("text")))
    return " ".join(p for p in parts if p)


SD_BLOCK = (
    "## 그림체 (SD)\n"
    "- SD: 2~3등신으로 축약된 형태. 얼굴이 크고 몸이 작다.\n"
    "  선은 단순하게, 표정은 과장되게.\n"
    "  SD여도 그 인물의 머리색, 눈색, 옷의 주요 색은 유지한다.\n"
    "- 한 컷 안에서 인물마다 다른 그림체가 지정될 수 있다. 지정된 대로 그린다."
)


def page_has_sd(page) -> bool:
    """이 페이지의 컷 중 하나라도 SD 인물이 있는가.

    없으면 SD_BLOCK 을 아예 안 붙인다 — LD 인물만 있는 페이지에 "2~3등신"
    문구가 같이 있으면 모델이 비율을 흔들 수 있다.
    """
    for cut in page or []:
        for who in cut.get("characters") or []:
            if _t(who.get("style")).upper() == "SD":
                return True
    return False


def build_page_prompt(page, sheets=None, cast=None, start_number: int = 1,
                      provider: str = "", style: str = "", sheet_names=()) -> str:
    """페이지(컷 배열) 하나 -> 호출 한 번에 보낼 프롬프트.

    컷 번호는 **페이지 안에서 1부터** 센다. 화면에 그려 넣는 번호라 페이지
    안에서 겹치지 않는 것이 전부고, 콘티의 원래 번호를 그대로 쓰면 장면이
    다른 컷이 한 페이지에 모였을 때 "컷 1" 이 두 개가 된다. 화 전체로 이어
    세고 싶으면 start_number 를 넘긴다.

    페이지 안에서 바로 앞 컷과 배경이 이어지는 컷(pages.linked)에는 그
    문구를 붙인다 — 페이지 경계를 넘는 이어짐은 안 본다(다른 호출이라
    앞 페이지가 뭘 그렸는지 이 프롬프트만으로는 모른다).
    """
    blocks = [load_fixed_block(provider, style)]
    if page_has_sd(page):
        blocks.append(SD_BLOCK)

    who = ([s for s in (sheets or []) if _t(s)]
           + cast_lines(cast, page, skip=sheet_names))
    if who:
        blocks.append("## 캐릭터 시트\n" + "\n".join(who))

    place = place_block(page)
    if place:
        blocks.append(place)

    notes = directing.resolve_notes(directing.DEFAULT_ROOT, page_haystack(page))
    if notes:
        blocks.append("## 연출 참고\n" + notes)

    import pages
    for i, cut in enumerate(page or []):
        prev = page[i - 1] if i > 0 else None
        blocks.append(cut_block(cut, start_number + i, with_place=not place,
                                linked=pages.linked(prev, cut)))
    return "\n\n".join(blocks) + "\n"


def page_prompts(pages_, sheets=None, cast=None, continuous: bool = False,
                 provider: str = "", style: str = "", sheet_names=()) -> list[str]:
    """페이지 배열 -> 프롬프트 배열. continuous 면 컷 번호를 화 전체로 이어 센다."""
    out, n = [], 1
    for page in pages_ or []:
        out.append(build_page_prompt(page, sheets, cast,
                                     start_number=n if continuous else 1,
                                     provider=provider, style=style,
                                     sheet_names=sheet_names))
        n += len(page)
    return out
