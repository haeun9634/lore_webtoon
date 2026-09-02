#!/usr/bin/env python3
"""new_harness — 사진·설명·장르로 1화 이야기와 콘티, 그리고 캐릭터 시트를 만든다.

    입력 -> 이야기 후보 4개 -> (사람이 고름) -> 콘티 -> 캐릭터 시트 -> 페이지 그림
          story_prompt                storyboard_prompt   sheet_prompt   image_prompt

컷은 **한 장씩 그리지 않는다.** pages.py 가 붙일 수 있는 컷을 한 페이지로 묶고,
페이지 하나당 이미지 호출을 한 번 한다 (pageart.py).

이야기는 story-harness 를 거치지 않는다. prompt/ 안의 프롬프트가 전부다.
이미지 호출만 story-harness 것을 빌려 쓴다 (imagegen.py 참고).

사용법
  python run.py --plan                                 # 어느 단계가 어느 모델인지
  python run.py --character ../landing/jobs/<id>/character.json
  python run.py --name 이하은 --photo a.png --desc "..." --genre 판타지
  python run.py --run-id <id> --pick 2                 # 후보 고르고 콘티까지
  python run.py --run-id <id> --sheet                  # 캐릭터 시트
  python run.py --run-id <id> --sheet-from ../story-harness/runs/<run>  # 시트 재사용
  python run.py --run-id <id> --pages                  # 페이지 그림 (페이지당 1회 호출)
  python run.py --run-id <id> --page 3                 # 3페이지만 다시
  python run.py --name ... --photo a.png --all --pick 2   # 한 번에
  아무 명령에나 --dry-run 을 붙이면 프롬프트만 쓰고 호출은 안 한다 (0원).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
WEBTOON_HARNESS = HERE.parent / "webtoon-harness"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(WEBTOON_HARNESS) not in sys.path:
    sys.path.append(str(WEBTOON_HARNESS))     # append, 안 insert(0,...) — new_harness
                                               # 자신의 모듈(run.py 등 이름이 겹치는
                                               # 것)을 가리면 안 된다

import directing                              # noqa: E402  (webtoon-harness 것을 그대로 빌린다)
import imagegen                              # noqa: E402
import llm                                    # noqa: E402
import detailart                              # noqa: E402
import pageart                                # noqa: E402
import pages as pagemod                       # noqa: E402
import sheet as sheetmod                      # noqa: E402
from llm import story                         # noqa: E402
import samples                                # noqa: E402  (story-harness 것을 그대로 빌린다)
from pages import SIZES                       # noqa: E402

PROMPT_DIR = HERE / "prompt"
RUNS_DIR = HERE / "runs"

# landing 의 폼과 같은 칸. 여기 없는 칸은 설명 본문에 섞여 들어온다.
FIELD_KEYS = ("나이", "성별", "직업", "성격", "말투", "과거", "관계", "약점")

log, warn = story.log, story.warn


# --------------------------------------------------------------------- 입력

def read_character(path: Path) -> dict:
    """landing 이 쓰는 character.json 을 그대로 읽는다.

    폴더를 주면 그 안의 character.json 을 찾는다 — jobs/<id> 를 그대로
    넘길 수 있게 하기 위해서다.

    story(줄거리)는 **읽고 버린다.** story_prompt 가 "줄거리는 받지 않는다,
    네가 새로운 이야기를 만들어야 한다" 고 못 박고 있어서, 넘기면 프롬프트와
    입력이 서로 반대를 말하게 된다.
    """
    if path.is_dir():
        path = path / "character.json"
    if not path.exists():
        raise SystemExit(f"캐릭터 파일이 없습니다: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))

    photo = doc.get("photo")
    photos = [photo] if isinstance(photo, str) else list(photo or [])
    fields = doc.get("fields") if isinstance(doc.get("fields"), dict) else {}
    return normalize({
        "name": doc.get("name"),
        "description": doc.get("character"),
        "fields": {k: str(fields.get(k) or "").strip() for k in FIELD_KEYS},
        "genre": doc.get("genre"),
        "photos": photos,
        "photo_note": doc.get("photo_note"),
    })


def normalize(raw: dict) -> dict:
    """빈 칸은 빈 칸으로 둔다. 코드가 기본값을 채우면 작가가 준 것과 섞인다."""
    fields = {k: str(v).strip() for k, v in (raw.get("fields") or {}).items()
              if str(v or "").strip()}
    photos = []
    for p in raw.get("photos") or []:
        path = Path(p)
        if not path.exists():
            warn(f"사진을 찾지 못했습니다: {path}")
            continue
        photos.append(str(path.resolve()))
    return {
        "name": str(raw.get("name") or "").strip(),
        "description": str(raw.get("description") or "").strip(),
        "fields": fields,
        "genre": str(raw.get("genre") or "").strip(),
        "photos": photos,
        "photo_note": str(raw.get("photo_note") or "").strip(),
    }


def gate_input(char: dict) -> list[str]:
    """story_prompt 가 필수라고 적은 것만 본다 — 이름과 외관."""
    bad = []
    if not char["name"]:
        bad.append("캐릭터 이름이 없습니다 (필수).")
    if not char["photos"] and not char["description"] and not char["fields"]:
        bad.append("외관이 없습니다 — 사진이나 설명 중 하나는 있어야 합니다.")
    return bad


def input_block(char: dict, *, with_genre: bool = True) -> str:
    """프롬프트 뒤에 붙는 이번 입력."""
    lines = ["# 이번 입력", "", f"캐릭터 이름: {char['name']}"]

    if char["photos"]:
        n = len(char["photos"])
        note = f" ({char['photo_note']})" if char["photo_note"] else ""
        lines.append(f"외관: 첨부한 사진 {n}장을 보라{note}.")
    else:
        lines.append("외관: (사진 없음 — 아래 설명에서 읽는다)")

    if char["description"] or char["fields"]:
        lines += ["", "설명:"]
        if char["description"]:
            lines.append(char["description"])
        for k, v in char["fields"].items():
            lines.append(f"- {k}: {v}")
    else:
        lines += ["", "설명: (없음 — 네가 정한다)"]

    if with_genre:
        lines += ["", f"장르: {char['genre']}" if char["genre"]
                  else "장르: (없음 — 네가 정한다)"]
    return "\n".join(lines) + "\n"


def story_input_block(char: dict) -> str:
    """이야기 단계의 입력 — 장르가 주어졌을 때만 장르 참고 자료를 더한다.

    장르가 없으면 story_prompt 가 4개 방향마다 서로 다른 장르를 스스로
    고르므로, 어느 장르의 세계관을 붙일지 미리 알 수 없다 — 그때는 지금까지
    처럼 붙이지 않는다. detail_block 과 같은 자료를 쓴다(genre_lore_for·
    world_text_for) — 구체화 단계에서만 장르 세계관을 주면, 장면 목록 자체가
    이미 장르 색이 없는 소재(출입증·CCTV 등)로 굳어 있어서 구체화가 소재를
    바꿔치기하는 식으로만 손볼 수 있었다(2026-08-31, 사용자 지적).
    """
    block = input_block(char).rstrip("\n")
    genre = char["genre"]
    if not genre:
        return block + "\n"
    lines = [block]
    lore = genre_lore_for(genre)
    if lore:
        lines += ["", "## 이 장르의 모티프·캐릭터유형·전개패턴 (참고 자료)", "", lore]
    world = world_text_for(genre)
    if world:
        lines += ["", "## 이 장르의 세계관 — 이 이야기가 실제로 따르는 규칙", "", world]
    return "\n".join(lines) + "\n"


def load_prompt(name: str) -> str:
    path = PROMPT_DIR / name
    if not path.exists():
        raise SystemExit(f"프롬프트가 없습니다: {path}")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise SystemExit(f"프롬프트가 비어 있습니다: {path}")
    return text


def compose(prompt_name: str, block: str) -> str:
    """프롬프트 + 이번 입력. 입력은 **뒤**에 붙인다 — 모델은 뒤에 온 것을 더 세게 듣는다."""
    return f"{load_prompt(prompt_name)}\n\n---\n\n{block}"


# --------------------------------------------------------------------- 파싱
#
# 이야기 후보는 마크다운, 콘티는 JSON 이다. 형식이 다른 것은 읽는 사람이
# 다르기 때문이다 — 후보는 사람이 읽고 하나를 고르는 것이라 형식이 느슨해도
# 되고, 콘티는 컷마다 칸이 정해져 있어서 JSON 이 맞다.
#
# 후보 쪽은 원문(story.md)을 그대로 남기고 골라야 하는 만큼만 잘라 읽는다.
# 잘라 읽기가 실패해도 원문은 남는다.

# 줄 안의 공백만 허용한다 — \s 를 쓰면 줄바꿈까지 먹어서, 값이 빈 줄
# ("인물:" 처럼 뒤가 비는 줄)에서 **다음 줄을 값으로 집어간다.**
S = r"[ \t]*"

DIRECTION_RE = re.compile(rf"^##{S}방향{S}(\d+){S}[—–\-:]?{S}(.*)$", re.M)
SECTION_RE = re.compile(rf"^###{S}(.+?){S}$", re.M)
GENRE_RE = re.compile(rf"^{S}장르{S}[:：]{S}(.+?){S}$", re.M)
BULLET_RE = re.compile(rf"^{S}(?:[-*·]|\d+[.)]){S}(.+?){S}$", re.M)


def _sections(body: str) -> dict:
    """### 로 나뉜 토막들."""
    out, marks = {}, list(SECTION_RE.finditer(body))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out[m.group(1).strip()] = body[m.end():end].strip()
    return out


def _bullets(text: str) -> list[str]:
    """번호나 - 로 시작하는 줄. 없으면 빈 줄로 나눈 문단."""
    hits = [m.group(1).strip() for m in BULLET_RE.finditer(text)]
    if hits:
        return hits
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def _cast_bullets(text: str) -> list[dict]:
    """"이름 — 외모" 한 줄씩 -> [{"name", "appearance"}]. 구분자가 없는 줄은 버린다.

    board.json·detail.json 이 만들던 cast(조연 외모 고정)를 story 단계에서
    바로 만든다 — 콘티·구체화를 건너뛰는 이어그리기 흐름은 그 둘이 없어서,
    여기서 안 만들면 조연 외모를 고정할 데가 없다.
    """
    out = []
    for line in _bullets(text):
        for sep in ("—", "–", "-"):
            if sep in line:
                name, _, appearance = line.partition(sep)
                name, appearance = name.strip(), appearance.strip()
                if name and appearance:
                    out.append({"name": name, "appearance": appearance})
                break
    return out


def parse_directions(md: str) -> list[dict]:
    """story_prompt 의 응답에서 방향 4개를 잘라 읽는다."""
    marks = list(DIRECTION_RE.finditer(md))
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        body = md[m.end():end]
        sec = _sections(body)
        genre = GENRE_RE.search(body.split("###")[0])
        out.append({
            "n": int(m.group(1)),
            "title": m.group(2).strip(),
            "genre": genre.group(1).strip() if genre else "",
            "plot": sec.get("줄거리", "").strip(),
            "scenes": _bullets(sec.get("장면 목록", "")),
            "cast": _cast_bullets(sec.get("등장인물", "")),
            "hidden": _bullets(sec.get("밝히지 않은 것", "")),
            "raw": (m.group(0) + body).strip(),
        })
    return out


def _num(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value) -> str:
    return str(value).strip() if value not in (None, "") else ""


def _dicts(value) -> list[dict]:
    return [v for v in (value or []) if isinstance(v, dict)]


def _wide(text: str) -> int:
    """터미널에서 차지하는 칸 수. 한글은 두 칸인데 len() 은 하나로 센다."""
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1
               for c in str(text))


def _pad(text: str, width: int) -> str:
    return str(text) + " " * max(0, width - _wide(text))


def parse_board(text: str) -> dict:
    """storyboard_prompt 의 응답(JSON) -> {"cast": [...], "scenes": [...]}.

    모양만 맞추고 값은 안 고친다. 여기서 빈칸을 채우면 모델이 안 적은 것과
    코드가 지어낸 것이 섞이고, 그건 다음 단계(이미지 프롬프트)가 구별할 수
    없다. 없는 것은 없는 채로 내려보낸다.

    번호가 없으면 나온 순서로 매긴다 — 컷 순서는 이 뒤로 계속 쓰이는 값이라
    비워 두면 페이지 묶기부터 어긋난다.
    """
    obj = story.extract_json(text)
    if not isinstance(obj, dict):
        raise story.ParseFailure("콘티가 JSON 객체가 아닙니다.")

    cast = [{"name": _text(c.get("name")), "appearance": _text(c.get("appearance"))}
            for c in _dicts(obj.get("cast"))]

    scenes = []
    for si, scene in enumerate(_dicts(obj.get("scenes")), 1):
        cuts = []
        for ci, cut in enumerate(_dicts(scene.get("cuts")), 1):
            camera = cut.get("camera") if isinstance(cut.get("camera"), dict) else {}
            background = (cut.get("background")
                          if isinstance(cut.get("background"), dict) else {})
            cuts.append({
                "id": _num(cut.get("id"), ci),
                "size": _text(cut.get("size")).lower(),
                "camera": {k: _text(camera.get(k)) for k in ("shot", "angle")},
                "background": {k: _text(background.get(k)) for k in ("type", "desc")},
                "characters": _dicts(cut.get("characters")),
                # order 가 곧 읽는 순서다. 빠진 것은 나온 자리로 채워 뒤로 민다.
                "dialogue": sorted(_dicts(cut.get("dialogue")),
                                   key=lambda d: _num(d.get("order"), 10_000)),
                "sfx": _dicts(cut.get("sfx")),
                "forbid": [_text(f) for f in (cut.get("forbid") or []) if _text(f)],
                "note": _text(cut.get("note")),
            })
        scenes.append({
            "id": _num(scene.get("id"), si),
            "summary": _text(scene.get("summary")),
            "location": _text(scene.get("location")),
            "time": _text(scene.get("time")),
            # 컷을 쓰기 전에 모델이 스스로 적어 두는 샷 계획. 없어도 된다 —
            # 옛 응답이나 이 필드를 안 쓰는 프롬프트도 그대로 읽힌다.
            "camera_plan": _text(scene.get("camera_plan")),
            "cuts": cuts,
        })
    return {"cast": cast, "scenes": scenes}


def parse_detail(text: str) -> dict:
    """detail_prompt 의 응답(JSON) -> {"scenes": [...], "hidden": [...]}.

    장면은 **사건(`events`)으로 나뉘어 온다** — 사건 하나가 그림 한 장이다.
    사건 칸이 없는 옛 응답은 장면 자체를 사건 하나로 읽는다
    (`pages.detail_events`) — 그래서 옛 run 은 결과가 안 바뀐다.
    """
    obj = story.extract_json(text)
    if not isinstance(obj, dict):
        raise story.ParseFailure("구체화 결과가 JSON 객체가 아닙니다.")
    scenes = []
    for i, s in enumerate(_dicts(obj.get("scenes")), 1):
        one = {"id": _num(s.get("id"), i)}
        one.update(_parse_beat(s))
        # 사건. 장면과 **같은 칸**을 쓴다 — 읽는 쪽이 둘을 구별할 필요가 없다.
        one["events"] = [dict(_parse_beat(e), id=_num(e.get("id"), j))
                         for j, e in enumerate(_dicts(s.get("events")), 1)]
        scenes.append(one)
    # cast — 조연 외모를 화 전체에 걸쳐 고정한다. 주인공은 시트가 하지만
    # 조연은 이것이 없으면 장면마다 다른 사람이 그려진다.
    cast = [{"name": _text(c.get("name")), "appearance": _text(c.get("appearance"))}
            for c in _dicts(obj.get("cast")) if _text(c.get("name"))]
    return {"scenes": scenes, "cast": cast,
            "hidden": [_text(x) for x in (obj.get("hidden") or []) if _text(x)]}


def _parse_beat(raw: dict) -> dict:
    """한 덩어리(장면 또는 사건) — 무엇이 벌어지고, 무엇을 알게 되고,
    앞뒤로 어떻게 이어지는가.

    장면과 사건이 같은 칸을 쓴다. 사건으로 나누기 전에는 이것이 장면에 직접
    적혀 있었고, 지금은 사건마다 적힌다 — 같은 함수로 읽으면 옛 응답과 새
    응답이 저절로 같은 모양이 된다.
    """
    return {
        "source": _text(raw.get("source")),
        "function": _text(raw.get("function")),
        "detail": _text(raw.get("detail")),
        # learns 는 {what, how} 다. how 가 곧 "그걸 어떻게 알았나" 라,
        # 문자열로만 오면 근거가 없는 것으로 본다.
        "learns": [{"what": _text(x.get("what")), "how": _text(x.get("how"))}
                   if isinstance(x, dict) else {"what": _text(x), "how": ""}
                   for x in (raw.get("learns") or [])
                   if _text(x.get("what") if isinstance(x, dict) else x)],
        # guesses 도 근거가 붙는다. 근거를 못 대면 그 짐작을 버려야지
        # 지어내면 안 되므로, from 이 비어 있는지 게이트가 본다.
        "guesses": [{"what": _text(x.get("what")), "from": _text(x.get("from"))}
                    if isinstance(x, dict) else {"what": _text(x), "from": ""}
                    for x in (raw.get("guesses") or [])
                    if _text(x.get("what") if isinstance(x, dict) else x)],
        # 이어짐 — 사건마다 따로 그림이 될 때 앞뒤가 안 끊기게 하는 칸이다
        # (detail_prompt 6-2 참고). 안 온 칸은 빈 채로 둔다 — 여기서
        # 채우면 모델이 안 적은 것과 코드가 지어낸 것이 섞인다.
        "continuity": _continuity(raw.get("continuity")),
        "leads_to": _text(raw.get("leads_to")),
    }


def _continuity(raw) -> dict:
    """장면의 이어짐 칸. 없으면 전부 빈 값 — 옛 run 과 모양이 같아진다."""
    raw = raw if isinstance(raw, dict) else {}
    return {
        "previous_ending": _text(raw.get("previous_ending")),
        "transition": _text(raw.get("transition")),
        "opening_state": _text(raw.get("opening_state")),
        "ending_state": _text(raw.get("ending_state")),
        "persistent_elements": [_text(x) for x in (raw.get("persistent_elements") or [])
                                if _text(x)],
        "visual_anchors": [_text(x) for x in (raw.get("visual_anchors") or [])
                           if _text(x)],
    }


def _parse_cuts(raw_cuts) -> list[dict]:
    """컷 목록(JSON) -> 정규화된 컷 목록. parse_cutscript 와 컷 대본 검수·보강
    (parse_cutscript_fix) 이 같은 컷 스키마를 쓰므로 여기서 하나로 모은다."""
    cuts = []
    for j, c in enumerate(_dicts(raw_cuts), 1):
        lines = []
        for k, d in enumerate(_dicts(c.get("lines")), 1):
            txt = _text(d.get("text"))
            if not txt:
                continue
            pri = _text(d.get("priority")).lower()
            lines.append({"order": _num(d.get("order"), k),
                          "type": _text(d.get("type")) or "말",
                          "speaker": _text(d.get("speaker")),
                          "text": txt,
                          # 안 적혀 있으면 지켜야 하는 줄로 본다 — 잃는
                          # 쪽보다 남기는 쪽이 안전하다.
                          "priority": pri if pri in ("required", "optional")
                                      else "required"})
        cuts.append({
            "id": _num(c.get("id"), j),
            "purpose": _text(c.get("purpose")),
            "source_information": [_text(x) for x in
                                   (c.get("source_information") or [])
                                   if _text(x)],
            "event": _text(c.get("event")),
            "reader_learns": [_text(x) for x in (c.get("reader_learns") or [])
                              if _text(x)],
            "lines": lines,
            "sfx": [_text(x) for x in (c.get("sfx") or []) if _text(x)],
            "must_show": [_text(x) for x in (c.get("must_show") or []) if _text(x)],
        })
    return cuts


def parse_cutscript(text: str) -> dict:
    """cutscript_prompt 의 응답(JSON) -> {"scenes": [{id, cuts: [...]}]}.

    컷 대본이다 — 컷을 어디서 나누고 무슨 말을 할지까지만 정해져 있고,
    카메라·배경·표정은 아직 없다. 그것은 콘티(storyboard) 단계가 채운다.
    """
    obj = story.extract_json(text)
    if not isinstance(obj, dict):
        raise story.ParseFailure("컷 대본 결과가 JSON 객체가 아닙니다.")
    scenes = []
    for i, s in enumerate(_dicts(obj.get("scenes")), 1):
        scenes.append({"id": _num(s.get("id"), i), "cuts": _parse_cuts(s.get("cuts"))})
    return {"scenes": scenes}


def warn_script_kept(board: dict, script: dict | None) -> list[str]:
    """콘티가 컷 대본의 내용을 지켰는가. 대본이 없으면 볼 것이 없다.

    **컷 경계 자체는 보지 않는다.** 대본의 컷 하나를 리액션·발견·화자
    전환 같은 이유로 여러 컷으로 넓히거나, 같은 시간·공간에서 자연스러운
    것을 한 컷에 묶는 것은 정상적인 연출 선택이다 — 컷 수가 다르다는
    것만으로는 아무것도 말해주지 않는다(실측: 이런 정상적인 확장에도
    매번 "컷 수가 다르다" 경고가 떴다). 그래서 여기서는 **내용이
    보존됐는가**만 본다 — 필수 대사가 글자 그대로 있는가, 그리고 대본의
    순서가 뒤바뀌지 않았는가.
    """
    if not script or not script.get("scenes"):
        return []
    out = []
    got = [_text(d.get("text"))
           for s in board.get("scenes") or []
           for c in s.get("cuts") or []
           for d in c.get("dialogue") or []]
    cursor = 0
    for s in script["scenes"]:
        for c in s.get("cuts") or []:
            for d in c.get("lines") or []:
                if d.get("priority", "required") != "required":
                    continue
                text = d.get("text")
                where = f"장면 {s.get('id')} 컷 {c.get('id')}"
                if text not in got:
                    out.append(f"{where}: 대본의 필수 대사가 콘티에 그대로 "
                               f"없습니다 — \"{text}\"")
                    continue
                try:
                    idx = got.index(text, cursor)
                except ValueError:
                    out.append(f"{where}: 필수 대사 순서가 대본과 다릅니다 "
                               f"— \"{text}\" 가 대본보다 앞선 자리에 있습니다")
                    continue
                cursor = idx + 1
    return out


def _keywords(text: str) -> list[str]:
    """이 문장을 대표하는 낱말들. "실렸는지" 를 낱말 겹침으로만 보기 위한 것.

    뜻이 같은지는 코드가 못 가린다 — 그래서 흔한 낱말을 빼고, 남은 것이
    하나도 안 보일 때만 "안 실렸다" 고 본다. 오탐보다 놓치는 쪽으로 기운다.
    """
    common = {"그것", "이것", "자신", "사람", "생각", "모습", "장면", "때문",
              "이라는", "라는", "하는", "되는", "있는", "없는", "것을", "것이"}
    return [w for w in re.findall(r"[가-힣]{2,}", text or "")
            if len(w) >= 2 and w not in common]


def _mentions(fact: str, carrier: str) -> bool:
    """`fact` 의 낱말이 `carrier` 에 하나라도 나오는가.

    조사가 붙어서 그대로는 안 겹친다("자명종은" vs "자명종"). 그래서 낱말의
    앞부분(2글자 이상)이 겹치면 실린 것으로 본다 — 어간이 대개 앞에 온다.
    이걸 안 하면 실제로 실린 것을 "안 실렸다" 고 잡는다(실측).
    """
    words = _keywords(fact)
    if not words:
        return True                      # 볼 것이 없으면 트집 잡지 않는다
    for w in words:
        for end in range(len(w), 1, -1):
            if w[:end] in carrier:
                return True
    return False


def _knowledge(scene: dict) -> tuple[list, list]:
    """장면 하나가 담고 있는 앎·추측 전부.

    사건으로 나뉘면 이것들이 사건마다 적히므로 장면 칸은 비어 있다. 장면
    단위로 보는 검사(컷 대본)는 그 둘을 합쳐서 봐야 나뉘기 전과 같은 것을 본다.
    """
    learns, guesses = [], []
    for e in pagemod.detail_events(scene):
        learns += list(e.get("learns") or [])
        guesses += list(e.get("guesses") or [])
    return learns, guesses


def gate_cutscript(script: dict, detail: dict | None) -> list[str]:
    """컷 대본이 장면의 정보를 흘렸는지 본다. 멈추지 않고 알린다.

    이 단계를 따로 둔 이유가 "정보가 사라지지 않게" 이므로, 그것만 본다 —
    문장이 좋은지는 사람이 판단할 몫이다.
    """
    bad = []
    detail_by_id = {s.get("id"): s for s in (detail or {}).get("scenes") or []}
    for s in script.get("scenes") or []:
        cuts = s.get("cuts") or []
        if not cuts:
            bad.append(f"장면 {s.get('id')}: 컷이 없습니다.")
            continue
        for c in cuts:
            if not c.get("purpose"):
                bad.append(f"장면 {s.get('id')} 컷 {c.get('id')}: purpose 가 없습니다 "
                           "— 하는 일을 못 적으면 컷이 아닙니다.")
            if not c.get("event"):
                bad.append(f"장면 {s.get('id')} 컷 {c.get('id')}: event 가 없습니다.")
            for d in c.get("lines") or []:
                if d.get("type") not in LINE_TYPES:
                    bad.append(f"장면 {s.get('id')} 컷 {c.get('id')}: "
                               f"lines 의 type=\"{d.get('type')}\" 은 목록에 "
                               f"없습니다 ({' · '.join(LINE_TYPES)}). 소리는 "
                               "sfx 에 적습니다.")
            # 잠가 놓고 아무 데도 안 실으면 잠근 것이 아니다. 낱말이 겹치는지로만
            # 본다 — 뜻이 같은지는 코드가 못 가린다.
            carrier = " ".join(
                [d.get("text", "") for d in c.get("lines") or []]
                + (c.get("must_show") or []) + (c.get("reader_learns") or []))
            for fact in c.get("source_information") or []:
                if not _mentions(fact, carrier):
                    bad.append(f"장면 {s.get('id')} 컷 {c.get('id')}: 지켜야 할 "
                               f"사실이 대사에도 그림에도 안 실렸습니다 — "
                               f"\"{fact}\"")
        # 알게 되는 것·추측이 여럿인데 컷이 하나면 장면을 나눈 것이 아니라
        # 줄인 것이다 — 합치라는 말을 요약하라는 말로 읽은 자리다.
        src = detail_by_id.get(s.get("id")) or {}
        learns, guesses = _knowledge(src)
        beats = len(learns) + len(guesses)
        if beats >= 2 and len(cuts) < 2:
            bad.append(f"장면 {s.get('id')}: 독자가 알아야 하는 것·추측이 "
                       f"{beats}개인데 컷이 {len(cuts)}개뿐입니다 — 뭉갠 것 "
                       "아닌지 보세요.")

    # 구체화의 `learns` 가 대본 어딘가에 실렸는지. 낱말이 겹치는지로만 본다 —
    # 뜻이 같은지는 코드가 못 가리므로, 아예 흔적도 없는 것만 잡는다.
    if detail:
        by_id = {s.get("id"): s for s in script.get("scenes") or []}
        for s in detail.get("scenes") or []:
            target = by_id.get(s.get("id"))
            if not target:
                bad.append(f"장면 {s.get('id')}: 대본에 이 장면이 없습니다.")
                continue
            blob = " ".join(
                " ".join([c.get("purpose", ""), c.get("event", "")]
                         + c.get("reader_learns", []) + c.get("must_show", [])
                         + [d.get("text", "") for d in c.get("lines", [])])
                for c in target.get("cuts") or [])
            for x in _knowledge(s)[0]:
                what = x.get("what") or ""
                if not _mentions(what, blob):
                    bad.append(f"장면 {s.get('id')}: 독자가 알아야 하는 것이 대본에 "
                               f"안 실렸습니다 — \"{what}\"")
    return bad


def gate_detail(detail: dict, direction: dict) -> list[str]:
    """구체화가 제 일을 했는지. **인과는 여기서 본다** — 콘티가 아니라.

    콘티에서 "밖에 있다가 갑자기 안에 있다" 를 잡으려던 것은 증상을 쫓는
    것이었다. 원인은 그 앞에서 이유가 지워진 채 넘어온 것이라, 지워졌는지를
    지워지는 자리에서 본다.
    """
    bad = []
    scenes = detail.get("scenes") or []
    if not scenes:
        return ["장면이 하나도 없습니다."]

    want = len(direction.get("scenes") or [])
    if want and len(scenes) < want:
        bad.append(f"장면 목록은 {want}개인데 {len(scenes)}개만 구체화됐습니다. "
                   "빠진 장면이 있습니다.")

    # 비어 있는지·근거가 붙었는지는 **사건 단위**로 본다 — 그림 한 장이 되는
    # 단위가 사건이라, 비어 있으면 그 한 장이 통째로 비는 자리다. 사건 칸이
    # 없는 옛 run 은 장면이 곧 사건 하나로 접혀서(pages.detail_events) 예전과
    # 글자까지 같은 문장이 나온다.
    units = pagemod.flatten_events(scenes)
    split = any(s.get("events") for s in scenes)
    for u in units:
        where = f"장면 {u['scene']}" + (f" 사건 {u['event']}" if split else "")
        if not _text(u.get("detail")):
            bad.append(f"{where}: detail 이 비어 있습니다.")
        if not _text(u.get("leads_to")):
            bad.append(f"{where}: leads_to 가 없습니다. 이 장면이 다음에 무엇을 "
                       "부르는지가 비어 있습니다.")

        # 근거 없는 앎. 이것 하나가 "자국을 보고 신발 패턴을 안다" 를 만든다.
        for one in u.get("learns") or []:
            if not one["how"]:
                bad.append(f"{where}: \"{one['what'][:30]}\" 를 어떻게 알았는지가 "
                           "없습니다. 근거가 없으면 learns 가 아니라 guesses 입니다.")
        for one in u.get("guesses") or []:
            if not one["from"]:
                bad.append(f"{where}: \"{one['what'][:30]}\" 를 무엇을 보고 짐작했는지가 "
                           "없습니다. 근거를 못 대면 그 짐작을 빼야 합니다.")

    # 길이는 **장면 단위**로 본다. 묻는 것이 "장면 목록 한 줄이 그 이상으로
    # 풀렸는가" 라서 사건으로 나눈다고 기준이 달라지지 않는다 — 사건마다
    # 이 길이를 요구하면 잘게 나눌수록 걸리게 되어, 나누라고 해 놓고 나누면
    # 벌하는 꼴이 된다.
    for s in scenes:
        body = " ".join(_text(e.get("detail"))
                        for e in pagemod.detail_events(s)).strip()
        if body and len(body) < DETAIL_MIN_LEN:
            bad.append(f"장면 {s['id']}: detail 이 {len(body)}자뿐입니다. "
                       "장면 목록 한 줄과 다를 바가 없습니다 — 구체화가 안 됐습니다.")

    # 사건 사이가 비면 그림이 순간이동한다 — 앞 사건은 식탁에서 끝났는데
    # 다음 사건이 책상 청소부터 시작하면, 사람은 알아서 메우지만 그림 모델은
    # 전혀 다른 공간으로 건너뛴다(실측). **사건으로 나눈 것만 본다** — 옛
    # run 에는 이 칸 자체가 없어서 다시 돌리면 전부 걸린다.
    if split:
        for u in units[1:]:
            con = u.get("continuity") or {}
            if not _text(con.get("transition")):
                bad.append(f"장면 {u['scene']} 사건 {u['event']}: 앞 사건과 이 사건 "
                           "사이에 무슨 일이 있었는지(transition)가 비어 있습니다. "
                           "이 칸이 비면 그림이 건너뜁니다.")
            if not _text(con.get("previous_ending")):
                bad.append(f"장면 {u['scene']} 사건 {u['event']}: 앞 사건이 끝난 "
                           "자리(previous_ending)가 비어 있습니다.")

    if not any(u.get("learns") for u in units):
        bad.append("인물이 새로 알게 되는 것이 한 장면에도 없습니다. "
                   "알아낸 것이 없으면 다음 행동의 근거가 생기지 않습니다.")

    # 마지막 사건이 감정으로 끝나면 다음 화를 안 부른다.
    last = _text(units[-1].get("leads_to"))
    if last and not any(ch.isdigit() for ch in last) and \
            any(w in last for w in FEELING_WORDS):
        bad.append(f"마지막 장면이 감정으로 끝납니다 (\"{last[:40]}\"). "
                   "다음에 무엇을 할 수밖에 없게 되는 발견이나, 독자만 알게 되는 "
                   "것이 필요합니다.")
    return bad


SEVERITY = ("critical", "major", "minor")
ISSUE_KINDS = ("인과", "지식", "출처", "신규", "연속성", "인물", "추측", "연결")


def parse_review(text: str) -> dict:
    """review_prompt 의 응답(JSON) -> {"verdict": ..., "issues": [...]}.

    verdict 는 **믿지 않고 다시 센다.** critical 이 하나라도 있으면 FAIL 이라는
    규칙을 모델이 지켰는지는 여기서 확인할 수 있고, 어긋나면 센 쪽이 맞다.
    """
    obj = story.extract_json(text)
    if not isinstance(obj, dict):
        raise story.ParseFailure("검수 결과가 JSON 객체가 아닙니다.")

    scenes = []
    for one in _dicts(obj.get("scenes")):
        scenes.append({
            "id": _num(one.get("id"), 0),
            "actions": _dicts(one.get("actions")),
            "knows": _dicts(one.get("knows")),
            "new": _dicts(one.get("new")),
            "conflicts": [_text(x) for x in (one.get("conflicts") or []) if _text(x)],
        })

    issues = []
    for one in _dicts(obj.get("issues")):
        sev = _text(one.get("severity")).lower()
        issues.append({
            "scene": _num(one.get("scene"), 0),
            "kind": _text(one.get("kind")),
            "severity": sev if sev in SEVERITY else "major",
            "what": _text(one.get("what")),
            "where": _text(one.get("where")),
        })
    issues.sort(key=lambda i: (SEVERITY.index(i["severity"]), i["scene"]))
    fail = any(i["severity"] == "critical" for i in issues)
    return {"verdict": "FAIL" if fail else "PASS",
            "scenes": scenes, "issues": issues}


def review_unanswered(review: dict) -> list[str]:
    """검수가 스스로 적어 놓고 issues 로 안 옮긴 것.

    답을 쓰게 한 이유가 이것이다 — "없음" · enough:false · "처음" 을 적어
    놓고도 문제로 안 올리면, 그 자리는 코드가 짚을 수 있다.
    """
    flagged = {(i["scene"], i["what"]) for i in review.get("issues") or []}
    out = []
    for s in review.get("scenes") or []:
        n = s["id"]
        for a in s["actions"]:
            if _text(a.get("why")) in ("없음", "모름", ""):
                out.append(f"장면 {n}: \"{_text(a.get('what'))[:30]}\" 의 이유가 "
                           "없다고 적어 놓고 문제로 안 올렸습니다.")
        for k in s["knows"]:
            if k.get("enough") is False:
                out.append(f"장면 {n}: \"{_text(k.get('what'))[:30]}\" 를 그 근거로 "
                           "알 수 없다고 적어 놓고 문제로 안 올렸습니다.")
        for w in s["new"]:
            if _text(w.get("from")) in ("처음", "없음", ""):
                out.append(f"장면 {n}: \"{_text(w.get('what'))[:30]}\" 가 여기서 "
                           "처음 나온다고 적어 놓고 문제로 안 올렸습니다.")
        for c in s["conflicts"]:
            out.append(f"장면 {n}: 부딪힘을 적어 놓고 문제로 안 올렸습니다 — {c[:40]}")
    # 이미 issues 에 같은 장면이 올라가 있으면 굳이 다시 말하지 않는다
    scenes_flagged = {sc for sc, _ in flagged}
    return [x for x in out if not any(f"장면 {sc}:" in x for sc in scenes_flagged)]


def review_counts(review: dict) -> dict:
    out = {s: 0 for s in SEVERITY}
    for one in review.get("issues") or []:
        out[one["severity"]] += 1
    return out


def gate_board(board: dict) -> list[str]:
    """그림으로 넘기기 전에 비면 안 되는 칸만 본다 — **무결성만**.

    콘티 프롬프트의 "내보내기 전에 확인" 중 **코드가 판정할 수 있는 것**만
    옮겼다. 좌우가 장면 안에서 유지됐는지 같은 것은 여기서 본다 — 사람이
    페이지를 다 그린 뒤에 발견하면 다시 그리는 값이 비싸다.

    여기서 보는 것은 전부 "칸이 비었다 · 값이 목록에 없다 · 장면 안에서
    모순된다" 같은 **구조** 문제다. "재미있게 읽히는가" 처럼 판단이 섞이는
    것은 `directing_warnings` 로 뺐다 — 구조 문제는 고치면 그림이 맞게
    나오지만, 연출 판단은 사람이 보고 그대로 둘 수도 있는 것이라 한 목록에
    섞으면 어느 쪽인지 못 가른다.
    """
    bad = []
    scenes = board.get("scenes") or []
    if not scenes:
        return ["장면이 하나도 없습니다."]

    for scene in scenes:
        where = f"장면 {scene['id']}"
        if not scene["location"]:
            bad.append(f"{where}: location 이 없습니다.")
        if not scene["cuts"]:
            bad.append(f"{where}: 컷이 없습니다.")

        # 이름 -> 좌우. **둘 이상 나온 컷에서만** 센다.
        #
        # 콘티 프롬프트의 규칙이 "한 컷에 두 명 이상 나오면 각자 position 을
        # 적는다. 한 번 정한 좌우는 그 장면이 끝날 때까지 바꾸지 않는다" 다.
        # 좌우를 고정하는 이유가 **둘의 자리가 서로 바뀌면 독자가 누가 누군지
        # 놓치기 때문**이라, 혼자 나오는 컷에는 걸 이유가 없다. 혼자 복도를
        # 걸어가는 인물이 가운데에서 오른쪽으로 옮겨 가는 것은 정상적인
        # 연출이고, 그것까지 잡으면 게이트가 매번 울려서 아무도 안 보게 된다.
        seats = {}
        for cut in scene["cuts"]:
            spot = f"{where} 컷 {cut['id']}"
            if cut["size"] not in SIZES:
                bad.append(f"{spot}: size 가 '{cut['size']}' 입니다 "
                           f"({' / '.join(SIZES)}).")
            people = cut["characters"]
            crowded = len(people) > 1
            for who in people:
                name = _text(who.get("name"))
                if not who.get("moment"):
                    bad.append(f"{spot}: {name or '이름 없음'} 에 moment 가 없습니다.")
                pos = _text(who.get("position"))
                if crowded and not pos:
                    bad.append(f"{spot}: 인물이 둘 이상인데 {name} 에 position 이 "
                               "없습니다.")
                if crowded and pos and name:
                    if seats.setdefault(name, pos) != pos:
                        bad.append(f"{spot}: {name} 의 좌우가 장면 안에서 바뀝니다 "
                                   f"({seats[name]} -> {pos}).")
            for line in cut["dialogue"]:
                if not _text(line.get("text")):
                    bad.append(f"{spot}: 대사에 text 가 비어 있습니다.")
            for one in cut["sfx"]:
                if not _text(one.get("text")):
                    bad.append(f"{spot}: 효과음에 text 가 비어 있습니다.")
    return bad


# 화 하나가 읽히는지 보는 눈금. 전부 **셀 수 있는 것**만 본다.
#
# 이 절이 생긴 이유: 형식은 다 맞는데 읽으면 무슨 내용인지 모르는 콘티가
# 그대로 그림까지 갔다. 7컷에 대사 3줄, 전부 혼잣말, 나레이션 0 — 무성영화가
# 나왔다. 셋 다 세면 알 수 있는 것이었는데 안 세고 있었다.
MIN_LINES_PER_CUT = 0.5      # 컷 두 개당 대사 한 줄
SOLO_SCENE_SHARE = 0.5       # 1컷짜리 장면이 이 비율을 넘으면 흐름이 안 나온다
OPENING_HINT_LEN = 25        # 첫 대사가 이보다 짧으면 상황을 못 잡아준 것으로 본다
DETAIL_MIN_LEN = 80          # 이보다 짧으면 장면 목록 한 줄을 옮겨 적은 것이다
# 마지막 장면이 이런 말로 끝나면 사건이 아니라 감정으로 끝난 것이다.
FEELING_WORDS = ("긴장", "경계", "관망", "불안", "초조", "두려", "느낀다",
                 "느끼게", "다짐", "각오", "생각하게")


def gate_readable(board: dict) -> list[str]:
    """읽히는가. 형식이 아니라 **화 전체의 모양**을 본다."""
    scenes = board.get("scenes") or []
    cuts = [c for s in scenes for c in s["cuts"]]
    if not cuts:
        return []

    lines = [l for c in cuts for l in c["dialogue"] if _text(l.get("text"))]
    kinds = {_text(l.get("type")) for l in lines}
    bad = []

    if len(lines) < len(cuts) * MIN_LINES_PER_CUT:
        bad.append(f"컷 {len(cuts)}개에 대사가 {len(lines)}줄뿐입니다. "
                   "그림만으로 상황을 다 말하게 되어 읽는 사람이 따라오기 "
                   "어렵습니다.")
    # 대사가 전부 "생각" 인 것 자체는 문제가 아니다. 혼잣말만으로도 잘
    # 읽히는 화가 있다 — 문제는 그 혼잣말이 **그림을 따라 말할 때** 인데,
    # 그건 세어서 알 수 없다. 그래서 여기서 안 잡고 프롬프트 14번에 맡긴다.

    # 첫 장면만 본다. 독자가 이 세계도 인물도 모르는 자리라, 여기서 헤매면
    # 뒤를 안 읽는다 (프롬프트 13번).
    opening = scenes[0]["cuts"]
    lead = [l for c in opening for l in c["dialogue"] if _text(l.get("text"))]
    if lead and not any(_text(l.get("type")) == "나레이션" for l in lead):
        # **첫 줄**을 본다. 잡으려는 것은 "독자가 아직 아무것도 모르는데
        # 인물이 짧게 반응부터 하고 시작하는 것" 이다. 예전에는 첫 장면에서
        # 가장 짧은 줄로 봤는데(min), 그러면 첫 컷에서 상황을 다 세워 놓고도
        # 뒤에 짧은 물음 한 줄이 있으면 걸렸다 — 컷 대본 단계를 붙인 뒤
        # 실제로 그 오탐이 났다.
        short = _text(lead[0].get("text"))
        if len(short) <= OPENING_HINT_LEN:
            bad.append(
                f"첫 장면에 나레이션이 없고 첫 대사가 짧습니다 (\"{short}\"). "
                "독자는 아직 여기가 어디인지 모릅니다 — 장소나 상황을 잡아주는 "
                "한 줄이 필요합니다.")

    solo = [s["id"] for s in scenes if len(s["cuts"]) == 1]
    if len(solo) > len(scenes) * SOLO_SCENE_SHARE:
        bad.append(f"장면 {len(scenes)}개 중 {len(solo)}개가 1컷입니다 "
                   f"(장면 {solo}). '인물이 한다 → 상황이 바뀐다 → 알아챈다' "
                   "가 한 컷에 안 들어갑니다.")
    return bad


# 카메라가 단조로워지는 눈금. 이 절도 gate_readable 처럼 **셀 수 있는 것**만 본다.
CLOSEUP_SHOTS = ("클로즈업", "극클로즈업")
FRONT_ANGLE = "정면"
CONSEC_SHOT_MAX = 3       # 같은 shot 이 이 개수를 넘겨 연달아 나오면 잡는다
CLOSEUP_MAX_SHARE = 0.5   # 클로즈업 계열이 전체 컷의 이 비율을 넘으면 단조롭다
# 프롬프트는 "한 장면에서 정면이 절반을 넘지 않는다" 고 한다. 여기는 화
# 전체 기준이라 조금 느슨하게 두되, 예전 0.8 은 너무 헐거웠다 — 정면이
# 64% 여도 안 걸렸다.
FRONT_ANGLE_MAX_SHARE = 0.6
# storyboard_prompt 의 `## 값 목록` 과 같아야 한다. 그림 프롬프트가 이 값을
# 그대로 쓰므로, 목록 밖 낱말이 들어오면 그 컷은 지시가 흐려진 채 그려진다.
ANGLES = ("정면", "하이앵글", "로우앵글", "부감")
FACINGS = ("앞모습", "옆모습", "뒷모습", "뒤통수만")
# 컷 대본의 lines[].type. storyboard_prompt 의 dialogue[].type 과 같은 목록이다.
LINE_TYPES = ("말", "생각", "외침", "화면밖", "나레이션", "글")
SHOT_VARIETY_MIN_CUTS = 6  # 컷이 이보다 적으면 비율이 우연히 쏠릴 수 있어 안 본다


def directing_warnings(board: dict) -> list[str]:
    """연출 참고 — 이대로도 그림은 나온다. 판단은 사람 몫이다.

    `gate_board` 와 갈라놓은 이유: 여기서 잡히는 것은 "의도한 연출일 수도
    있다" 는 값이라, 콘티를 버리거나 다시 뽑을 근거가 아니다. 형식이 깨진
    `gate_board` 의 결과와 한 목록에 섞이면 어느 쪽이 반드시 고쳐야 하는
    것이고 어느 쪽이 그냥 참고인지 구별이 안 된다.

    `gate_readable`(대사 밀도·오프닝·1컷 장면)에 카메라 쏠림 눈금을 더했다.
    """
    bad = list(gate_readable(board))
    scenes = board.get("scenes") or []
    seq = [(s.get("id"), c.get("id"), c)
           for s in scenes for c in (s.get("cuts") or [])]
    if not seq:
        return bad

    def shot_of(c):
        return _text((c.get("camera") or {}).get("shot"))

    def angle_of(c):
        return _text((c.get("camera") or {}).get("angle"))

    # 같은 shot 이 너무 오래 이어지면 화면이 단조롭다.
    run_shot, run_len, run_start = None, 0, None
    for sid, cid, c in seq:
        shot = shot_of(c)
        if shot and shot == run_shot:
            run_len += 1
        else:
            run_shot, run_len, run_start = shot, 1, (sid, cid)
        if run_len == CONSEC_SHOT_MAX + 1:
            bad.append(f"장면 {run_start[0]} 컷 {run_start[1]} 부터 '{shot}' 이 "
                       f"{run_len}컷 연속입니다. 화면이 단조로워질 수 있습니다.")

    # 클로즈업 계열·정면 앵글이 전체를 뒤덮으면 리듬이 안 산다. 컷이 적으면
    # 비율이 우연히도 쏠릴 수 있어 SHOT_VARIETY_MIN_CUTS 미만은 안 본다.
    total = len(seq)
    if total >= SHOT_VARIETY_MIN_CUTS:
        closeups = sum(1 for _, _, c in seq if shot_of(c) in CLOSEUP_SHOTS)
        if closeups / total > CLOSEUP_MAX_SHARE:
            bad.append(f"컷 {total}개 중 {closeups}개가 클로즈업 계열입니다 "
                       f"({closeups / total:.0%}). 거리감 있는 샷을 섞는 것을 "
                       "고려하세요.")
        fronts = sum(1 for _, _, c in seq if angle_of(c) == FRONT_ANGLE)
        if fronts / total > FRONT_ANGLE_MAX_SHARE:
            bad.append(f"컷 {total}개 중 {fronts}개가 정면 앵글입니다 "
                       f"({fronts / total:.0%}). 하이앵글·로우앵글·부감을 섞는 "
                       "것을 고려하세요.")

    # 장면이 스스로 적어 둔 카메라 계획(camera_plan)과 실제 컷이 다르면
    # 알린다 — 계획을 안 쓴 장면(옛 응답 포함)은 그냥 건너뛴다.
    #
    # 계획은 "shot/angle, shot/angle" 로 적게 돼 있지만, 앵글까지 계획하게
    # 하기 전의 옛 응답은 "shot, shot" 이다. 어느 쪽이든 읽는다 — 형식을
    # 바꿨다고 옛 run 이 전부 어긋난 것으로 보이면 안 된다.
    for s in scenes:
        plan = _text(s.get("camera_plan"))
        if not plan:
            continue
        planned = [p.strip() for p in plan.split(",") if p.strip()]
        cuts = s.get("cuts") or []
        with_angle = any("/" in p for p in planned)
        if with_angle:
            actual = [f"{shot_of(c)}/{_text((c.get('camera') or {}).get('angle'))}"
                      for c in cuts]
        else:
            actual = [shot_of(c) for c in cuts]
        if planned != actual:
            label = "shot/angle" if with_angle else "shot"
            bad.append(f"장면 {s.get('id')}: 카메라 계획({', '.join(planned)})과 "
                       f"실제 컷의 {label}({', '.join(actual)})이 다릅니다.")

    # 값 목록에 없는 카메라 값. 앵글을 계획하게 한 뒤로 모델이 "아이레벨"
    # 처럼 목록 밖 낱말을 만들어 내는 것을 실측했다 — 그림 프롬프트가 이
    # 값을 그대로 쓰므로 조용히 흘리면 안 된다.
    off = []
    for s in scenes:
        for c in s.get("cuts") or []:
            cam = c.get("camera") or {}
            v = _text(cam.get("angle"))
            if v and v not in ANGLES:
                off.append(f"장면 {s.get('id')} 컷 {c.get('id')}: angle=\"{v}\"")
            # facing 은 인물마다 하나씩이다(camera 가 아니라 characters[]) —
            # 한 컷에 인물이 둘 이상이면 서로 달라도 정상이다.
            for ch in c.get("characters") or []:
                fv = _text(ch.get("facing")) if isinstance(ch, dict) else ""
                if fv and fv not in FACINGS:
                    off.append(f"장면 {s.get('id')} 컷 {c.get('id')} "
                               f"{_text(ch.get('name'))}: facing=\"{fv}\"")
    if off:
        bad.append("값 목록에 없는 카메라 값입니다 (그림 프롬프트가 이 값을 "
                   f"그대로 씁니다): {', '.join(off[:6])}"
                   + (f" 외 {len(off) - 6}개" if len(off) > 6 else ""))
    return bad


# --------------------------------------------------------------------- run

def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_meta(run_dir: Path) -> dict:
    path = run_dir / "meta.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"run_id": run_dir.name, "calls": []}


def record(run_dir: Path, call_meta: dict) -> None:
    meta = load_meta(run_dir)
    meta["calls"].append(call_meta)
    write_json(run_dir / "meta.json", meta)
    cost = call_meta.get("cost") or {}
    tag = "실패" if call_meta.get("error") else ""
    log(f"  {tag}{call_meta['stage']}  {call_meta['provider']}:{call_meta['model']}  "
        f"{story.cost_text(cost.get('total'))}"
        + (f"  — {call_meta['error']}" if call_meta.get("error") else ""))


def record_error(run_dir: Path, stage: str, provider: str, model: str, exc: Exception) -> None:
    """호출이 실패했을 때도 meta.json 에 흔적을 남긴다 — 성공 때(record)와 같은
    자리, 비용은 0으로. 실패 사유가 로그에서만 스쳐 지나가면 나중에 이 run이
    왜 멈췄는지, 어디까지 돈이 나갔는지 다시 알아낼 수 없다."""
    record(run_dir, {
        "stage": stage, "provider": provider, "model": model,
        "usage": None, "stop": None,
        "cost": {"input": 0.0, "output": 0.0, "cache_read": 0.0,
                 "cache_write": 0.0, "total": 0.0},
        "error": f"{type(exc).__name__}: {exc}",
    })


def read_input(run_dir: Path) -> dict:
    path = run_dir / "input.json"
    if not path.exists():
        raise SystemExit(f"{path} 가 없습니다. 먼저 이야기 단계를 돌리세요.")
    return json.loads(path.read_text(encoding="utf-8"))


DIRECTIONS_PER_RUN = 4


def _distinct_structures(genre: str, first: dict, n: int = DIRECTIONS_PER_RUN) -> list[dict]:
    """회차 구조를 서로 다른 것으로 n개. 첫 번째는 pick_fresh 가 뽑아 준 것을 쓴다.

    장르 제약이 세서 n개를 못 채우면 있는 만큼만 준다 — 겹치는 구조를
    억지로 채워 넣느니 그 방향은 구조 없이 가는 편이 낫다.
    """
    out, seen = [], set()
    for cand in [first] + [samples.pick_structure(genre) for _ in range(n * 6)]:
        if len(out) >= n:
            break
        key = str((cand or {}).get("구조", {}).get("이름") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out


def _pick_engines(n: int = DIRECTIONS_PER_RUN) -> list[dict]:
    """서사 엔진 — "이 인물이 무엇을 하는 이야기인가". 방향마다 서로 다르게.

    축(어디에 서 있는가)·구조(어떤 순서로 보여주는가)와 다른 층이다. 축과
    구조를 방향별로 갈라도 4개가 전부 "상대에게 숨겨진 감정이 있고
    주인공은 모른다"로 수렴하는 것을 실측하고 넣었다(2026-08-31) — 소재는
    달라도 그 위에 얹히는 갈등 공식이 같으면 읽는 경험이 같다.

    story_prompt 에 목록만 주고 "서로 다르게 하라"고 했을 때는 장르가
    끌어당기는 쪽으로 다시 수렴했다. 축·구조처럼 값을 박아야 갈린다.
    "비밀과 추적"이 하나를 넘지 않는 것은 서로 다른 것을 뽑는 것만으로
    저절로 지켜진다.
    """
    try:
        doc = json.loads((PROMPT_DIR / "story_engines.json").read_text(encoding="utf-8"))
        values = [v for v in (doc.get("엔진") or {}).get("값") or []
                  if isinstance(v, dict) and v.get("이름")]
    except (OSError, json.JSONDecodeError):
        return []                       # 없으면 엔진 없이 간다 — 예전과 같다
    if not values:
        return []
    pool = list(values)
    random.shuffle(pool)
    return [pool[i % len(pool)] for i in range(n)]


def _engine_block(engine: dict) -> str:
    if not engine:
        return ""
    lines = [f"[서사 엔진] {engine.get('이름', '')} — 핵심 동사: "
             f"{engine.get('핵심동사', '')}"]
    for key in ("설명", "전개"):
        if str(engine.get(key) or "").strip():
            lines.append(f"  {engine[key]}")
    return "\n".join(lines)


def _distinct_axes(genre: str, first: dict, n: int = DIRECTIONS_PER_RUN) -> list[dict]:
    """이야기 변수를 방향마다 하나씩. **축 하나하나가 방향끼리 안 겹치게** 뽑는다.

    조합 단위로만 다르게 뽑으면 축 하나가 4개 방향에 똑같이 걸릴 수 있고,
    그러면 소재가 달라도 넷이 같은 이야기로 읽힌다 — 2026-08-31 실측에서
    관계_구도(삼각관계)가 4개 전부에 나왔다. 그래서 축별로 값을 갈라 준다.

    1번 방향은 pick_fresh 가 뽑아 준 것을 그대로 쓴다. 최근 run 들과 겹치지
    않게 고른 값이라 이것을 버리면 run 사이 반복 회피가 사라진다.
    값이 n개보다 적은 축(장르 제약)은 있는 만큼만 돌려 쓴다.
    """
    table = samples.load_axes()
    if not table:
        return []
    gkey = samples._override_key(table, genre)
    picked: list[dict] = [{} for _ in range(n)]
    for axis in samples.axis_names():
        values = samples._axis_values(table, axis, gkey)
        if not values:
            continue
        head = (first or {}).get(axis)
        rest = [v for v in values
                if not head or v.get("이름") != head.get("이름")]
        random.shuffle(rest)
        chosen = ([head] if head else []) + rest
        for i in range(n):
            picked[i][axis] = chosen[i % len(chosen)]
    return picked


def story_variety_block(run_dir: Path, char: dict) -> str:
    """방향별 이야기 변수 · 회차 구조 — story-harness/samples.py 를 빌린다.

    **방향마다 하나씩** 뽑는다. story-harness 는 run 하나가 이야기 하나라
    "run 당 한 벌"이 곧 "이야기 당 한 벌"이었는데, new_harness 는 run
    하나가 이야기 4개다 — 그래서 원래 의도대로 옮기면 방향 단위가 맞다.
    (한 벌을 4개가 나눠 쓰게 했다가 관계_구도가 4개 전부에 같이 걸리는
    것을 실측으로 확인하고 고쳤다. 2026-08-31.)

    run 과 run 사이의 반복 회피(samples.pick_fresh 가 최근 run 들의
    axes.json 을 보고 겹치는 조합을 피하는 것)는 그대로 살아 있다 —
    1번 방향이 pick_fresh 가 고른 값을 그대로 받고, axes.json 의
    "축"·"구조" 키(story-harness 와 같은 스키마)에 그 값이 남는다.
    방향별 전체는 "방향별_축"·"방향별_구조" 에 따로 남긴다.
    """
    axes, structure, fresh = samples.pick_fresh(char["genre"], runs_dir=RUNS_DIR)
    axes_list = _distinct_axes(char["genre"], axes) if axes else []
    structures = _distinct_structures(char["genre"], structure) if structure else []
    engines = _pick_engines()

    if axes or structure or engines:
        write_json(run_dir / "axes.json",
                   {"축": axes, "구조": structure,
                    "방향별_축": axes_list, "방향별_구조": structures,
                    "방향별_엔진": engines})
    for i in range(max(len(axes_list), len(structures), len(engines))):
        bits = []
        if i < len(engines):
            bits.append(str(engines[i].get("이름") or ""))
        if i < len(axes_list):
            bits.append(samples.axes_summary(axes_list[i]))
        if i < len(structures):
            bits.append(samples.structure_summary(structures[i]))
        if bits:
            log(f"  방향 {i + 1}: {' | '.join(b for b in bits if b)}")
    if (axes or structure) and not fresh:
        log("  (최근 생성물과 조합이 겹칩니다 — 고를 수 있는 폭이 좁습니다)")

    count = max(len(axes_list), len(structures), len(engines))
    if not count:
        return ""
    parts = [
        "", "## 방향별 서사 엔진 · 이야기 변수 · 회차 구조 — 참고가 아니라 지시다", "",
        "아래 값은 방향 번호에 그대로 대응한다. **방향 N 은 N 번 값으로 쓴다.** "
        "4개가 서로 다른 이야기가 되게 하는 장치가 이것이다 — 값을 무시하고 그 "
        "장르에서 가장 흔한 설정으로 돌아가면 넷이 비슷해지고, 지난 생성들과도 "
        "비슷해진다.", "",
        "**서사 엔진이 가장 세다.** 소재와 무대가 달라도 엔진이 같으면 넷이 같은 "
        "이야기로 읽힌다 — 실제로 그렇게 나온 적이 있다(소재는 다 달랐는데 넷 다 "
        "'상대에게 숨겨진 감정이 있고 주인공은 모른다'였다). 장르가 익숙한 공식으로 "
        "끌어당겨도 배정된 엔진 쪽으로 간다. 엔진은 이야기가 무엇을 하는지를, "
        "이야기 변수는 인물이 어디에 서서 무엇과 부딪히는지를, 회차 구조는 그것을 "
        "어떤 순서로 보여줄지를 정한다. 소재는 장르에서 고르고 이 위에 얹는다.",
    ]
    for i in range(count):
        parts += ["", f"### 방향 {i + 1}", ""]
        for txt in (_engine_block(engines[i]) if i < len(engines) else "",
                    samples.axes_block(axes_list[i]) if i < len(axes_list) else "",
                    samples.structure_block(structures[i]) if i < len(structures) else ""):
            if txt:
                parts += [txt, ""]
    return "\n".join(parts)


def stage_story(run_dir: Path, char: dict, dry_run: bool, note: str = "") -> list[dict]:
    block = story_input_block(char).rstrip("\n") + "\n" + story_variety_block(run_dir, char)
    note = (note or "").strip()
    if note:
        # 다시 만들기에서 사람이 남긴 요청 — 캐릭터 설정 자체가 아니라 "이번엔
        # 이렇게 더 반영해 달라"는 한 번짜리 지시라, story_input_block 이 아니라
        # 여기서 따로 붙인다(캐릭터 파일을 고치면 다음 시도에도 계속 남는다).
        block += f"\n\n## 이번 시도에 추가로 반영할 것\n사용자가 방금 다시 만들기를 " \
                 f"요청하며 남긴 말이다. 가능한 한 반영한다:\n{note}"
    prompt = compose("story_prompt", block)
    write_text(run_dir / "story_prompt.txt", prompt)
    if dry_run:
        log(f"[이야기] 프롬프트만 썼습니다 -> {run_dir / 'story_prompt.txt'}")
        return []

    call = llm.Call("STORY")
    log(f"[이야기] {call.describe()} 로 후보 4개를 만듭니다…")
    try:
        text, meta = call(prompt, images=llm.load_images(char["photos"]))
    except Exception as exc:                                          # noqa: BLE001
        record_error(run_dir, "STORY", call.provider, call.model, exc)
        raise
    write_text(run_dir / "story.md", text)
    record(run_dir, meta)

    directions = parse_directions(text)
    if len(directions) != 4:
        warn(f"방향을 {len(directions)}개만 읽었습니다 (4개여야 합니다). "
             f"원문은 {run_dir / 'story.md'} 에 그대로 있습니다.")
    write_json(run_dir / "directions.json", directions)
    return directions


def show_directions(directions: list[dict]) -> None:
    for d in directions:
        genre = f"  [{d['genre']}]" if d["genre"] else ""
        print(f"\n── {d['n']}. {d['title']}{genre}")
        if d["plot"]:
            print(f"   {d['plot'].splitlines()[0]}")
        for s in d["scenes"]:
            print(f"     · {s}")


def choose(directions: list[dict], pick: int | None) -> dict:
    if pick is not None:
        for d in directions:
            if d["n"] == pick:
                return d
        raise SystemExit(f"방향 {pick} 이 없습니다 (있는 것: "
                         f"{[d['n'] for d in directions]}).")
    show_directions(directions)
    while True:
        answer = input("\n어느 방향으로 갈까요? 번호: ").strip()
        for d in directions:
            if answer == str(d["n"]):
                return d
        print("목록에 있는 번호를 넣으세요.")


# 장르 문자열(자유 텍스트, 예: "헌터·게이트") -> story-harness/worlds.json
# 프리셋 라벨의 키워드. 여러 개 걸리면 첫 번째로 매칭된 것을 쓴다. 장르가
# 이 목록에 없으면(오컬트 미스터리·좀비 아포칼립스 등) 조용히 건너뛴다 —
# 세계관 문장 없이도 지금까지처럼 돌아간다.
_WORLD_KEYWORDS = {
    "hunter_gate": ("헌터", "게이트"),
    "academy_magic": ("마법학교", "마법", "학원"),
    "idol_agency": ("아이돌", "연습생"),
    "hero_city": ("히어로", "능력자", "빌런"),
    "post_disaster": ("재난", "좀비", "아포칼립스"),
    "royal_court": ("궁정", "왕궁", "무협"),
}


def genre_lore_for(genre: str) -> str:
    """장르에 맞는 story-harness 의 장르 템플릿(모티프·캐릭터유형·전개패턴·
    체크리스트)을 그대로 빌린다. 없으면 빈 문자열.

    story-harness/samples/genre_template.json 의 `_preset_map` 이 "헌터·게이트"
    같은 한글 장르명을 이미 판타지·액션·스릴러 같은 실제 템플릿 조합으로
    라우팅해 둔 상태다(story.resolve_genre_templates). world_text_for 보다
    훨씬 구체적이라 — 던전·이세계 전이·용/드래곤 같은 실제 소재 목록과
    캐릭터 유형·클리셰까지 들어 있다. 이걸 못 찾고 있다가 사용자가 다시
    짚어서 뒤늦게 붙였다.
    """
    genre = (genre or "").strip()
    if not genre:
        return ""
    try:
        names = story.resolve_genre_templates(genre)
        if not names:
            return ""
        return story.genre_template_block(names)
    except Exception:
        return ""


def world_text_for(genre: str) -> str:
    """장르에 맞는 story-harness/worlds.json 세계관 한 문단. 없으면 빈 문자열.

    detail_prompt 가 "장르"만 받고 구체적인 세계 규칙을 못 받아서, 구체화
    단계가 장르 특유의 소재(마나·몬스터·게이트 현상 등) 없이 아무 장르에나
    쓸 수 있는 일반적인 소재(출입증·CCTV·무전기)로 채우는 문제가 있었다
    (2026-08-30, 사용자 지적). story-harness 가 이미 갖고 있는 프리셋
    문장을 그대로 빌려 온다 — 새 문장을 짓지 않는다.
    """
    genre = (genre or "").strip()
    if not genre:
        return ""
    path = llm.STORY_HARNESS / "worlds.json"
    if not path.exists():
        return ""
    try:
        presets = json.loads(path.read_text(encoding="utf-8")).get("presets") or {}
    except Exception:
        return ""
    for key, keywords in _WORLD_KEYWORDS.items():
        if any(kw in genre for kw in keywords):
            return (presets.get(key) or {}).get("text") or ""
    return ""


def detail_block(char: dict, direction: dict, run_dir: Path) -> str:
    """구체화 단계의 입력 — 줄거리 · 장면 목록 · 캐릭터 · 장르 · 밝히지 않을 것."""
    lines = ["# 이번 입력", "", "## 줄거리", "", direction["plot"],
             "", "## 장면 목록", ""]
    lines += [f"{i}. {s}" for i, s in enumerate(direction["scenes"], 1)]

    lines += ["", "## 캐릭터 정보", "", f"이름: {char['name']}"]
    if char["description"]:
        lines.append(f"설명: {char['description']}")
    for k, v in char["fields"].items():
        lines.append(f"- {k}: {v}")

    spec_path = run_dir / "sheet_spec.json"
    if spec_path.exists():
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        lines.append(f"외관: {spec['appearance_en']}")
        for d in spec.get("design_details") or []:
            lines.append(f"- 고정 요소: {d}")

    genre = direction["genre"] or char["genre"] or ""
    lines += ["", "## 장르", "", genre or "(정해진 것 없음)"]
    lore = genre_lore_for(genre)
    if lore:
        lines += ["", "## 이 장르의 모티프·캐릭터유형·전개패턴 (참고 자료)", "", lore]
    world = world_text_for(genre)
    if world:
        lines += ["", "## 이 장르의 세계관 — 이 이야기가 실제로 따르는 규칙", "", world]
    lines += ["", "## 밝히지 않을 것", ""]
    lines += [f"- {h}" for h in direction["hidden"]] or ["(없음)"]
    return "\n".join(lines) + "\n"


def picked_direction(run_dir: Path, pick: int | None) -> dict:
    """이 run 에서 고른 방향. --pick 을 안 줘도 pick.json 에서 찾는다."""
    path = run_dir / "directions.json"
    if not path.exists():
        raise SystemExit(f"{path} 가 없습니다. 이야기 단계를 먼저 돌리세요.")
    picked = run_dir / "pick.json"
    n = pick or (json.loads(picked.read_text(encoding="utf-8"))["n"]
                 if picked.exists() else None)
    if n is None:
        raise SystemExit("--pick <번호> 로 어느 방향인지 알려주세요.")
    return choose(json.loads(path.read_text(encoding="utf-8")), n)


def stage_detail(run_dir: Path, char: dict, direction: dict, dry_run: bool) -> dict:
    """장면 목록 -> 실제 이야기. 콘티가 창작하지 않아도 되게 만드는 단계다."""
    prompt = compose("detail_prompt", detail_block(char, direction, run_dir))
    write_text(run_dir / "detail_prompt.txt", prompt)
    if dry_run:
        log(f"[구체화] 프롬프트만 썼습니다 -> {run_dir / 'detail_prompt.txt'}")
        return {}

    call = llm.Call("DETAIL")
    log(f"[구체화] {call.describe()} 로 장면을 이야기로 폅니다…")
    text, meta = call(prompt)
    write_text(run_dir / "detail_raw.txt", text)
    record(run_dir, meta)

    detail = parse_detail(text)
    write_json(run_dir / "detail.json", detail)
    events = sum(len(pagemod.detail_events(s)) for s in detail["scenes"])
    log(f"  장면 {len(detail['scenes'])}개 · 사건 {events}개(그림 {events}장) · "
        f"숨길 것 {len(detail['hidden'])}개 -> {run_dir / 'detail.json'}")

    bad = gate_detail(detail, direction)
    if bad:
        warn(f"구체화에 손볼 곳이 {len(bad)}개 있습니다:")
        for one in bad:
            warn(f"  - {one}")
        write_json(run_dir / "detail_issues.json", bad)
    return detail


def _scene_lines(detail: dict) -> list[str]:
    """구체화된 장면을 프롬프트에 실을 줄로. 컷 대본과 콘티가 같이 쓴다.

    장면이 사건으로 나뉘어 있으면 사건마다 소제목을 단다. 사건 칸이 없는 옛
    run 은 장면 하나가 사건 하나라 예전과 **글자까지 같은 줄**이 나온다.
    """
    lines = []
    for s in detail.get("scenes") or []:
        lines.append(f"### 장면 {s['id']} — {s['source']}")
        lines.append("")
        events = pagemod.detail_events(s)
        for e in events:
            if s.get("events"):
                head = f"#### 사건 {e.get('id')}"
                if e.get("source"):
                    head += f" — {e['source']}"
                lines += [head, ""]
            lines.append(e.get("detail") or "")
            if e.get("learns"):
                lines.append("")
                for x in e["learns"]:
                    how = f" ({x['how']})" if x.get("how") else ""
                    lines.append(f"- 인물이 알게 되는 것: {x['what']}{how}")
            for g in e.get("guesses") or []:
                src = f" ({g['from']})" if g.get("from") else ""
                lines.append(f"- 인물의 추측 (아직 사실이 아니다): {g['what']}{src}")
            if e.get("leads_to"):
                lines.append(f"- 그래서 다음: {e['leads_to']}")
            lines.append("")
    return lines


def cutscript_block(char: dict, direction: dict, run_dir: Path) -> str:
    """컷 대본 단계의 입력 — 구체화된 장면 · 캐릭터 · 장르 · 숨길 것."""
    detail_path = run_dir / "detail.json"
    detail = (json.loads(detail_path.read_text(encoding="utf-8"))
              if detail_path.exists() else None)

    # 줄거리를 같이 준다. 구체화된 장면에는 "지금 무슨 일이 벌어지는가" 는
    # 있어도 "이 인물이 여기서 무엇을 하는 사람인가" 는 없을 때가 많은데,
    # 첫 컷에서 독자를 앉혀 놓으려면 그것이 필요하다 — 안 줬더니 첫 컷이
    # 배경 설명 없이 인물의 반응부터 시작했다.
    lines = ["# 이번 입력", "", "## 줄거리", "", direction["plot"], "", "## 장면", ""]
    if detail and detail.get("scenes"):
        lines += _scene_lines(detail)
    else:
        lines += [f"{i}. {s}" for i, s in enumerate(direction["scenes"], 1)]

    lines += ["", "## 캐릭터 정보", "", f"이름: {char['name']}"]
    if char["description"]:
        lines.append(f"설명: {char['description']}")
    for k, v in char["fields"].items():
        lines.append(f"- {k}: {v}")

    lines += ["", "## 장르", "",
              direction["genre"] or char["genre"] or "(정해진 것 없음)"]

    hidden = (detail or {}).get("hidden") or direction["hidden"]
    lines += ["", "## 밝히지 않을 것", ""]
    lines += [f"- {h}" for h in hidden] or ["(없음)"]
    return "\n".join(lines) + "\n"


def stage_cutscript(run_dir: Path, char: dict, direction: dict,
                    dry_run: bool) -> dict:
    """장면 -> 컷 대본. **연출 전에 이야기를 확정하는 단계다.**

    콘티 한 번에 컷 분할·대사·카메라를 다 시키면, 그림을 어떻게 보여줄지에
    끌려가면서 장면에 적힌 서사 정보가 사라진다(실측 — 인물이 여기서 무엇을
    하는 사람인지, 얼마나 그래 왔는지가 통째로 빠지고 분위기만 읊는 나레이션
    한 줄이 남았다. 콘티 프롬프트에 "정보를 잃지 마라" 를 넣고 다시 돌려도
    같았다). 그래서 컷을 어디서 나누고 무슨 말을 할지를 **먼저** 확정하고,
    콘티는 그것을 화면으로 옮기기만 하게 나눴다.
    """
    prompt = compose("cutscript_prompt", cutscript_block(char, direction, run_dir))
    write_text(run_dir / "cutscript_prompt.txt", prompt)
    if dry_run:
        log(f"[컷 대본] 프롬프트만 썼습니다 -> {run_dir / 'cutscript_prompt.txt'}")
        return {}

    call = llm.Call("CUTSCRIPT")
    log(f"[컷 대본] {call.describe()} 로 장면을 컷으로 나눕니다…")
    text, meta = call(prompt)
    write_text(run_dir / "cutscript_raw.txt", text)
    record(run_dir, meta)

    script = parse_cutscript(text)
    write_json(run_dir / "cutscript.json", script)
    total = sum(len(s["cuts"]) for s in script["scenes"])
    log(f"  장면 {len(script['scenes'])}개 · 컷 {total}개 "
        f"-> {run_dir / 'cutscript.json'}")

    detail_path = run_dir / "detail.json"
    detail = (json.loads(detail_path.read_text(encoding="utf-8"))
              if detail_path.exists() else None)
    bad = gate_cutscript(script, detail)
    if bad:
        warn(f"컷 대본에 손볼 곳이 {len(bad)}개 있습니다:")
        for one in bad:
            warn(f"  - {one}")
        write_json(run_dir / "cutscript_issues.json", bad)
    return script


# ------------------------------------------------------- 컷 대본 검수·자기수정
#
# story/detail 단계의 review_prompt·fix_prompt 와는 다른 층이다 — 저건 "상세
# 스토리가 논리적으로 앞뒤가 맞는가" 를 본다. 여기는 "이 컷스크립트가 그대로
# 웹툰이 됐을 때, 사전 정보가 전혀 없는 독자가 화면만 보고 이해하는가" 를
# 본다. 그래서 입력도 상세 스토리가 아니라 컷(purpose·lines·must_show)이고,
# 장면을 하나씩 순서대로(그 앞 장면까지 읽은 것을 전제로) 처리한다.
#
# **호출은 장면당 한 번이다.** 검수와 수정을 따로 부르지 않는다 — 같은
# 호출 안에서 독자로서 읽고, 문제가 있으면 스스로 진단하고 고치고, 고친
# 것을 스스로 다시 확인해서 최종본을 낸다(모델이 직접 하지, 다른 단계로
# 안 넘긴다). 검수와 수정을 별도 호출로 나눴을 때는 "빠진 낱말을 찾아
# 그 자리에 문장 하나 끼워 넣는" 손쉬운 길로 흘러갔다(실측) — 그렇다고
# 한 프롬프트에서 진단과 처방을 동시에 자유롭게 하게 두면 같은 문제가
# 재현될 수 있어서, 프롬프트 안에서 "컷마다 순서대로 읽기 -> 진단 ->
# 처방 순서(순서 변경 -> 문장 재작성 -> 컷 분리 -> must_show 보강 ->
# 나레이션 최소 -> 새 줄 최후수단) -> 스스로 재확인" 을 강제한다.
#
# `cutscript.json`(원본)은 그대로 두고, 결과는 전부 `cutscript_fix/`
# 아래에만 쓴다 — 원본과 최종본을 나란히 남겨서 무엇이 왜 바뀌었는지
# 나중에도 비교할 수 있게 한다. 하지만 **콘티(board_block)가 실제로
# 따르는 것은 원본이 아니라 이 최종본(`cutscript_fix/cutscript_final.json`)
# 이다** — `load_cutscript` 참고. 기본 흐름(story → detail → 컷 대본 →
# 컷 대본 픽스 → 콘티)에서 항상 자동으로 돈다. 컷 대본만 다시 돌리고
# 콘티는 아직 안 갈 때(`--cutscript-fix` 단독 호출)를 위해 별도 함수로
# 남겨 둔다.

def _fmt_cuts_json(cuts: list[dict]) -> str:
    return json.dumps(cuts, ensure_ascii=False, indent=2)


def cutscript_fix_header(char: dict, direction: dict) -> list[str]:
    """컷 대본 검수·자기수정의 입력 머리말 — 줄거리·캐릭터·장르·밝히지 않을 것."""
    lines = ["## 줄거리", "", direction["plot"], "",
             "## 캐릭터 정보", "", f"이름: {char['name']}"]
    if char["description"]:
        lines.append(f"설명: {char['description']}")
    for k, v in char["fields"].items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## 장르", "",
              direction["genre"] or char["genre"] or "(정해진 것 없음)"]
    lines += ["", "## 밝히지 않을 것", ""]
    lines += [f"- {h}" for h in direction["hidden"]] or ["(없음)"]
    return lines


def cutscript_fix_block(char: dict, direction: dict, script: dict) -> str:
    """컷 대본 검수·자기수정 단계의 입력 — 이 화 전체의 컷스크립트 한 번에."""
    lines = cutscript_fix_header(char, direction)
    lines += ["", "## 이 화 전체의 컷스크립트 (장면 순서대로, 각 장면 안에서는 컷 순서대로)", "",
              "```json", json.dumps(script["scenes"], ensure_ascii=False, indent=2), "```"]
    return "\n".join(lines) + "\n"


def parse_cutscript_fix(text: str) -> dict:
    """cutscript_fix_prompt 의 응답(JSON) -> 검수+자기수정 결과 한 번의 것."""
    obj = story.extract_json(text)
    if not isinstance(obj, dict):
        raise story.ParseFailure("컷 대본 검수 결과가 JSON 객체가 아닙니다.")
    exp = obj.get("reader_experience") or {}
    diagnosis = []
    for d in _dicts(obj.get("diagnosis")):
        diagnosis.append({
            "scene": _num(d.get("scene"), 0),
            "cuts": [_num(x, 0) for x in (d.get("cuts") or []) if _num(x, 0)],
            "type": _text(d.get("type")),
            "severity": _text(d.get("severity")).lower() or "high",
            "problem": _text(d.get("problem")),
            "why_it_matters": _text(d.get("why_it_matters")),
        })
    scenes = []
    for i, s in enumerate(_dicts(obj.get("scenes")), 1):
        scenes.append({"id": _num(s.get("id"), i), "cuts": _parse_cuts(s.get("cuts"))})
    verdict = _text(obj.get("verdict")).upper()
    if verdict not in ("PASS", "FAIL"):
        # 모델이 verdict 를 안 지켰을 때의 안전망 — 진단이 있으면 FAIL.
        verdict = "FAIL" if diagnosis else "PASS"
    return {
        "verdict": verdict,
        "changes_made": verdict == "FAIL",
        "reader_experience": {
            "understands": [_text(x) for x in (exp.get("understands") or []) if _text(x)],
            "confused": [_text(x) for x in (exp.get("confused") or []) if _text(x)],
        },
        "diagnosis": diagnosis,
        "scenes": scenes,
    }


def stage_cutscript_fix(run_dir: Path, char: dict, direction: dict,
                         dry_run: bool) -> dict:
    """컷 대본을 **고치지 않고** 그대로 둔 채, 이 화 전체를 검수 에이전트에게
    한 번에 준다 — 호출 딱 한 번으로 처음부터 끝까지 독자로서 읽고, 필요하면
    스스로 고치고, 고친 것을 스스로 다시 확인까지 마친 최종본을 받는다.
    장면별로 나눠 부르지 않는다.
    """
    path = run_dir / "cutscript.json"
    if not path.exists():
        raise SystemExit(f"{path} 가 없습니다. 컷 대본을 먼저 돌리세요.")
    script = json.loads(path.read_text(encoding="utf-8"))
    out_dir = run_dir / "cutscript_fix"

    prompt = compose("cutscript_fix_prompt", cutscript_fix_block(char, direction, script))
    write_text(out_dir / "reader_prompt.txt", prompt)
    if dry_run:
        log(f"[컷 검수·자기수정] 프롬프트만 썼습니다 -> {out_dir / 'reader_prompt.txt'}")
        return {}

    call = llm.Call("CUTSCRIPT_FIX")
    n_cuts = sum(len(s["cuts"]) for s in script["scenes"])
    log(f"[컷 검수·자기수정] {call.describe()} 로 장면 {len(script['scenes'])}개 · "
        f"컷 {n_cuts}개를 한 번에 읽고, 필요하면 스스로 고칩니다…")
    # 판단이 흔들리지 않게 온도를 0으로 — 같은 컷을 두고 어제는 잡고
    # 오늘은 놓치는 것을 실측으로 봤다.
    text, meta = call(prompt, temperature=0.0)
    write_text(out_dir / "reader_raw.txt", text)
    record(run_dir, meta)

    result = parse_cutscript_fix(text)
    write_json(out_dir / "reader_result.json", result)
    log(f"  {result['verdict']} — changes_made={result['changes_made']}")
    for one in result["reader_experience"]["confused"]:
        log(f"    독자가 못 잡음: {one}")
    for d in result["diagnosis"]:
        log(f"    [{d['severity']:6}] 장면 {d['scene']} 컷 {d['cuts']} ({d['type']}) {d['problem']}")

    scenes = result["scenes"] or script["scenes"]
    write_json(out_dir / "cutscript_final.json", {"scenes": scenes})
    log(f"  -> {out_dir / 'cutscript_final.json'}")
    return result


def review_block(char: dict, direction: dict, run_dir: Path) -> str:
    """검수 단계의 입력 — 구체화가 받은 것 전부 + 구체화 결과.

    구체화가 받은 것을 그대로 줘야 "입력에 없던 것을 만들었는가" 를 볼 수 있다.
    """
    path = run_dir / "detail.json"
    if not path.exists():
        raise SystemExit(f"{path} 가 없습니다. 구체화를 먼저 돌리세요.")
    detail = json.loads(path.read_text(encoding="utf-8"))

    lines = [detail_block(char, direction, run_dir).rstrip(), "",
             "## 상세 스토리 (검수할 것)", ""]
    for s in detail["scenes"]:
        lines.append(f"### 장면 {s['id']} — {s['source']}")
        if s.get("function"):
            lines.append(f"이 장면이 하는 일: {s['function']}")
        for e in pagemod.detail_events(s):
            if s.get("events"):
                head = f"#### 사건 {e.get('id')}"
                if e.get("source"):
                    head += f" — {e['source']}"
                lines.append(head)
                if e.get("function"):
                    lines.append(f"이 사건이 하는 일: {e['function']}")
            lines += ["", e.get("detail") or "", ""]
            for x in e.get("learns") or []:
                lines.append(f"- 안다: {x['what']}  ← {x['how']}")
            for g in e.get("guesses") or []:
                lines.append(f"- 짐작: {g['what']}  ← {g['from']}")
            lines += [f"- 그래서 다음: {e.get('leads_to') or ''}", ""]
    return "\n".join(lines) + "\n"


def stage_review(run_dir: Path, char: dict, direction: dict, dry_run: bool) -> dict:
    """구체화 결과를 처음 읽는 독자의 눈으로 본다. **고치지 않는다.**

    만드는 쪽과 보는 쪽을 나누는 것이 요점이다. 구체화는 빈칸을 채우려고
    없던 것을 만들어내는데, 같은 호출에 "그러지 마라" 를 아무리 넣어도 자기가
    만든 것은 그럴듯해 보인다. 읽는 역할을 따로 준다.
    """
    prompt = compose("review_prompt", review_block(char, direction, run_dir))
    write_text(run_dir / "review_prompt.txt", prompt)
    if dry_run:
        log(f"[검수] 프롬프트만 썼습니다 -> {run_dir / 'review_prompt.txt'}")
        return {}

    call = llm.Call("REVIEW")
    log(f"[검수] {call.describe()} 로 독자의 눈으로 읽습니다…")
    # 검수는 발상이 아니라 대조다. 온도를 낮춘다.
    text, meta = call(prompt, temperature=0.2)
    write_text(run_dir / "review_raw.txt", text)
    record(run_dir, meta)

    review = parse_review(text)
    write_json(run_dir / "review.json", review)

    n = review_counts(review)
    log(f"  {review['verdict']} — critical {n['critical']} · major {n['major']} "
        f"· minor {n['minor']}")
    for one in review["issues"]:
        log(f"    [{one['severity']:8}] 장면 {one['scene']} ({one['kind']}) "
            f"{one['what']}")
    for one in review_unanswered(review):
        warn(f"  {one}")
    return review


def fix_block(char: dict, direction: dict, run_dir: Path, review: dict) -> str:
    """보강 단계의 입력 — 검수가 본 것 전부 + 지적 목록."""
    lines = [review_block(char, direction, run_dir).rstrip(), "",
             "## 검수 지적 (이번에 고칠 것)", ""]
    for one in review["issues"]:
        lines.append(f"### 장면 {one['scene']} · {one['kind']} · {one['severity']}")
        lines.append(one["what"])
        if one["where"]:
            lines.append(f"> {one['where']}")
        lines.append("")
    return "\n".join(lines) + "\n"


def apply_fix(detail: dict, patch: dict) -> tuple[dict, list[int]]:
    """고친 장면만 갈아 끼운다. 나머지는 **글자 하나 안 바뀐다.**

    보강 모델이 지적받은 장면만 출력하므로, 안 나온 장면은 손댈 방법이 없다.
    전체를 다시 내게 하고 "나머지는 그대로 두라" 고 부탁하는 것보다 확실하다.
    """
    by_id = {s["id"]: s for s in patch.get("scenes") or []}
    scenes, changed = [], []
    for one in detail["scenes"]:
        new = by_id.get(one["id"])
        if new and new != one:
            scenes.append(new)
            changed.append(one["id"])
        else:
            scenes.append(one)
    # cast(조연 외모)·hidden 은 보강이 안 내는 칸이라 그대로 들고 간다. 예전엔
    # cast 를 빠뜨려서, 보강을 한 번 돌리면 조연 외모가 통째로 사라졌다.
    return {"scenes": scenes, "cast": detail.get("cast") or [],
            "hidden": detail.get("hidden") or []}, changed


def stage_fix(run_dir: Path, char: dict, direction: dict, review: dict,
              dry_run: bool) -> dict:
    """지적받은 장면만 고친다. 이야기를 다시 쓰지 않는다."""
    if not review or not review.get("issues"):
        log("[보강] 지적이 없습니다. 그대로 갑니다.")
        return {}

    prompt = compose("fix_prompt", fix_block(char, direction, run_dir, review))
    write_text(run_dir / "fix_prompt.txt", prompt)
    if dry_run:
        log(f"[보강] 프롬프트만 썼습니다 -> {run_dir / 'fix_prompt.txt'}")
        return {}

    call = llm.Call("FIX")
    log(f"[보강] {call.describe()} 로 지적 {len(review['issues'])}건을 봅니다…")
    text, meta = call(prompt, temperature=0.3)
    write_text(run_dir / "fix_raw.txt", text)
    record(run_dir, meta)

    patch = parse_detail(text)
    obj = story.extract_json(text)
    notes = [_text(x) for x in ((obj or {}).get("notes") or []) if _text(x)]

    path = run_dir / "detail.json"
    detail = json.loads(path.read_text(encoding="utf-8"))
    # 고치기 전 것을 남긴다 — 무엇이 달라졌는지 나중에 볼 수 있어야 한다.
    write_json(run_dir / "detail_before_fix.json", detail)

    merged, changed = apply_fix(detail, patch)
    write_json(path, merged)
    write_json(run_dir / "fix_notes.json", {"changed": changed, "notes": notes})

    log(f"  장면 {changed or '없음'} 을 고쳤습니다 -> {path}")
    for one in notes:
        warn(f"  못 고침: {one}")
    return merged


def load_cutscript(run_dir: Path) -> dict | None:
    """콘티가 실제로 따라야 할 컷 대본.

    `cutscript_fix/cutscript_final.json`(컷 대본 검수·자기수정의 최종본)이
    있으면 그것을 쓴다 — 자기수정까지 마친 것이 실제 최종본이라는 뜻이다.
    없으면(아직 픽스를 안 돌린 옛 run, 또는 `--board` 만 단독으로 다시
    부르는 경우) `cutscript.json`(원본)으로 그대로 돌아간다.
    """
    final_path = run_dir / "cutscript_fix" / "cutscript_final.json"
    if final_path.exists():
        return json.loads(final_path.read_text(encoding="utf-8"))
    script_path = run_dir / "cutscript.json"
    if script_path.exists():
        return json.loads(script_path.read_text(encoding="utf-8"))
    return None


def board_block(char: dict, direction: dict, run_dir: Path) -> str:
    """콘티 단계의 입력 — 구체화된 이야기 · 캐릭터 정보 · 장르.

    구체화(detail.json)가 있으면 **그것을 준다.** 장면 목록 한 줄이 아니라
    실제로 무슨 일이 벌어지고 인물이 무엇을 알게 되는지가 적힌 것이라,
    콘티는 창작하지 않고 그것을 컷으로 펼치기만 하면 된다.
    """
    detail_path = run_dir / "detail.json"
    detail = (json.loads(detail_path.read_text(encoding="utf-8"))
              if detail_path.exists() else None)

    lines = ["# 이번 입력", "", "## 장면", ""]
    haystack = []          # 연출 지식을 태그로 골라 붙일 때 검색할 서술
    if detail and detail.get("scenes"):
        lines += _scene_lines(detail)
        haystack += [e.get("detail") or "" for s in detail["scenes"]
                     for e in pagemod.detail_events(s)]
    else:
        lines += [f"{i}. {s}" for i, s in enumerate(direction["scenes"], 1)]
        haystack += direction["scenes"]

    # 컷 대본이 있으면 **컷 분할과 대사는 이미 끝난 것이다.** 콘티는 그것을
    # 화면으로 옮기기만 한다 — 대본 없이 한 번에 시켰을 때 서사 정보가
    # 연출에 잡아먹히던 것을 막으려고 나눈 단계다(stage_cutscript 참고).
    script = load_cutscript(run_dir)
    if script and script.get("scenes"):
        lines += ["", "## 컷 대본 — 이대로 컷을 만든다", "",
                  "컷을 나누는 일과 무슨 말을 할지는 이미 끝났다. 컷을 더 나누거나 "
                  "합치지 말고, 이 순서 그대로 만든다.", "",
                  "`대사`는 **글자 그대로** `dialogue[].text` 에 옮긴다 — 줄이거나 "
                  "다듬거나 합치지 마라. 여기 있는 줄이 사라지면 독자가 상황을 "
                  "못 따라온다. `보여야 하는 것`은 그 컷 그림에 반드시 있어야 "
                  "한다.", "",
                  "네가 정하는 것은 **어떻게 보여줄 것인가** 뿐이다 — 카메라·배경·"
                  "인물 위치·표정·동작·말풍선 모양과 자리.", ""]
        for s in script["scenes"]:
            lines.append(f"### 장면 {s['id']}")
            lines.append("")
            for c in s.get("cuts") or []:
                lines.append(f"**컷 {c['id']}** — {c.get('event') or ''}")
                if c.get("purpose"):
                    lines.append(f"- 이 컷이 하는 일: {c['purpose']}")
                for x in c.get("source_information") or []:
                    lines.append(f"- 지켜야 할 사실 (고치지 마라): {x}")
                for x in c.get("reader_learns") or []:
                    lines.append(f"- 독자가 알게 되는 것: {x}")
                for x in c.get("must_show") or []:
                    lines.append(f"- 보여야 하는 것: {x}")
                for d in c.get("lines") or []:
                    who = d.get("speaker") or ""
                    kind = d.get("type") or "말"
                    lock = ("[필수 — 글자 그대로]"
                            if d.get("priority", "required") == "required"
                            else "[빼도 됨]")
                    lines.append(f"- 대사({kind}{' · ' + who if who else ''}) "
                                 f"{lock}: {d.get('text')}")
                for x in c.get("sfx") or []:
                    lines.append(f"- 효과음: {x}")
                lines.append("")

    lines += ["", "## 캐릭터 정보", "", f"이름: {char['name']}"]
    if char["photos"]:
        lines.append(f"외관: 첨부한 사진 {len(char['photos'])}장을 보라.")

    # 시트를 먼저 뽑았으면 그 사양을 같이 준다 — 콘티가 새 인물의 외관을
    # 확정할 때(storyboard_prompt 9번) 주인공만 다른 사람이 되는 것을 막는다.
    spec_path = run_dir / "sheet_spec.json"
    if spec_path.exists():
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        lines.append(f"외관(확정): {spec['appearance_en']}")
        for d in spec.get("design_details") or []:
            lines.append(f"- 고정 요소: {d}")
        for p in spec.get("props") or []:
            lines.append(f"- 소지품: {p}")

    if char["description"]:
        lines += ["", f"설명: {char['description']}"]
    for k, v in char["fields"].items():
        lines.append(f"- {k}: {v}")

    lines += ["", "## 장르", "", direction["genre"] or char["genre"] or "(정해진 것 없음)"]
    if not detail:
        lines += ["", "## 줄거리 (배경 이해용 — 이대로 나누라는 뜻은 아니다)", "",
                  direction["plot"]]
    hidden = (detail or {}).get("hidden") or direction["hidden"]
    if hidden:
        lines += ["", "## 밝히지 않을 것 — 컷에서 답을 보여주지 마라", ""]
        lines += [f"- {h}" for h in hidden]

    # 이번 화 서술에 등장하는 태그와 겹치는 연출 지식만 골라 붙인다 —
    # story-harness/webtoon-harness 가 쓰는 것과 같은 저장소, 같은 방식
    # (directing.resolve_notes, 정확 태그 매칭). 하나도 안 걸리면 아무것도
    # 안 붙는다 — 안 맞는 연출 지식을 우기는 것보다 낫다.
    notes = directing.resolve_notes(directing.DEFAULT_ROOT, *haystack)
    if notes:
        lines += ["", "## 연출 참고", "", notes]
    return "\n".join(lines) + "\n"


def page_ratio_cap(given: int | None) -> int:
    """페이지 높이 상한. 안 주면 **지금 그림을 그릴 캔버스**에서 뽑는다.

    프로바이더마다 캔버스 모양이 달라서(Gemini 1.78 · OpenAI 1.50) 같은 컷
    묶음이 다른 두께로 나온다. 손으로 맞추게 두면 프로바이더를 바꿀 때마다
    이 값을 같이 바꿔야 하는 것을 잊는다.
    """
    if given is not None:
        return given
    aspect = imagegen.page_aspect(llm.provider_for("PAGE_IMAGE"))
    return pagemod.max_ratio_for(aspect)


def repage(run_dir: Path, max_ratio: int | None = None) -> list:
    """board.json -> pages.json. 호출 0회 — 묶는 방식만 바꿔 다시 짤 때 쓴다."""
    max_ratio = page_ratio_cap(max_ratio)
    path = run_dir / "board.json"
    if not path.exists():
        raise SystemExit(f"{path} 가 없습니다. 콘티 단계를 먼저 돌리세요.")
    board = json.loads(path.read_text(encoding="utf-8"))
    flat = pagemod.flatten_cuts(board["scenes"])
    pages = pagemod.group_pages(flat, max_ratio=max_ratio)
    write_json(run_dir / "pages.json", pages)
    tall = [sum(pagemod.HEIGHT_RATIO[pagemod.cut_size(c)] for c in pg) for pg in pages]
    log(f"  페이지 {len(pages)}장 · 높이합계 {tall} -> {run_dir / 'pages.json'}")
    return pages


def stage_board(run_dir: Path, char: dict, direction: dict, dry_run: bool,
                max_ratio: int | None = None) -> None:
    prompt = compose("storyboard_prompt", board_block(char, direction, run_dir))
    write_text(run_dir / "board_prompt.txt", prompt)
    if dry_run:
        log(f"[콘티] 프롬프트만 썼습니다 -> {run_dir / 'board_prompt.txt'}")
        return

    # pick.json 은 "실제로 확정된 선택"의 기록이라, 호출이 실제로 일어나는
    # 경우에만(dry-run 이 아닐 때만) 갱신한다 — dry-run 으로 다른 방향을
    # 훑어보기만 해도 이 값이 덮어써지면, 나중에 --pick 없이 이어할 때
    # 엉뚱한 방향으로 이어진다(실측: 2026-09-01, 테스트용 dry-run 이 실제
    # 진행 중이던 run 의 pick.json 을 조용히 바꿔치기했다).
    write_json(run_dir / "pick.json", {"n": direction["n"], "title": direction["title"],
                                       "genre": direction["genre"]})

    call = llm.Call("BOARD")
    log(f"[콘티] {call.describe()} 로 방향 {direction['n']} 을 컷으로 나눕니다…")
    text, meta = call(prompt, images=llm.load_images(char["photos"]))
    # 원문을 먼저 남긴다. 아래에서 파싱이 죽어도 응답은 안 사라진다.
    write_text(run_dir / "board_raw.txt", text)
    record(run_dir, meta)

    board = parse_board(text)
    write_json(run_dir / "board.json", board)

    scenes = board["scenes"]
    total = sum(len(s["cuts"]) for s in scenes)
    log(f"  장면 {len(scenes)}개 · 컷 {total}개 -> {run_dir / 'board.json'}")

    # 게이트는 **멈추지 않고 알린다.** 좌우가 한 번 어긋난 것 때문에 콘티
    # 전체를 버리게 하면, 고쳐 쓰면 될 것을 다시 뽑느라 또 돈을 쓴다.
    #
    # 무결성(bad)과 연출 경고(warns)는 따로 적는다 — 하나는 "구조가 깨져서
    # 반드시 고쳐야 하는 것", 하나는 "이대로도 그림은 나오지만 참고할 것"
    # 이라, 섞어 두면 어느 쪽인지 못 가른다.
    bad = gate_board(board)
    script = load_cutscript(run_dir)
    warns = directing_warnings(board) + warn_script_kept(board, script)
    if bad:
        warn(f"콘티에 반드시 손볼 곳이 {len(bad)}개 있습니다 (구조가 깨졌습니다):")
        for one in bad:
            warn(f"  - {one}")
    if warns:
        warn(f"연출 참고할 점이 {len(warns)}개 있습니다 (그림은 이대로도 나옵니다):")
        for one in warns:
            warn(f"  - {one}")
    if bad or warns:
        write_json(run_dir / "board_issues.json", {"integrity": bad, "directing": warns})

    repage(run_dir, max_ratio)


def stage_sheet(run_dir: Path, char: dict, dry_run: bool,
                spec_only: bool = False, note: str = "") -> None:
    photos = char["photos"]
    block = input_block(char)
    note = (note or "").strip()
    if note:
        # 다시 만들기에서 남긴 한 번짜리 요청 — character.json 을 고치지 않고
        # 여기서만 붙인다(stage_story 의 note 와 같은 이유).
        block += f"\n\n## 이번 시도에 추가로 반영할 것\n사용자가 방금 다시 만들기를 " \
                 f"요청하며 남긴 말이다. 가능한 한 반영한다:\n{note}"
    prompt = compose("sheet_prompt", block)
    write_text(run_dir / "sheet_spec_prompt.txt", prompt)

    spec_path = run_dir / "sheet_spec.json"
    if spec_path.exists():
        log(f"[시트] 사양이 이미 있습니다 -> {spec_path} (재사용)")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    elif dry_run:
        log(f"[시트] 사양 프롬프트만 썼습니다 -> {run_dir / 'sheet_spec_prompt.txt'}")
        return
    else:
        call = llm.Call("SHEET")
        log(f"[시트] {call.describe()} 로 사양을 적습니다…")
        try:
            text, meta = call(prompt, images=llm.load_images(photos), temperature=0.4)
        except Exception as exc:                                      # noqa: BLE001
            record_error(run_dir, "SHEET", call.provider, call.model, exc)
            raise
        record(run_dir, meta)
        spec = sheetmod.parse_spec(text)
        bad = sheetmod.gate_spec(spec)
        if bad:
            write_json(run_dir / "sheet_spec_rejected.json", spec)
            raise SystemExit("시트 사양이 모자랍니다 — 그리기 전에 멈춥니다:\n  - "
                             + "\n  - ".join(bad))
        write_json(spec_path, spec)

    image_prompt = sheetmod.build_prompt(spec)
    write_text(run_dir / "sheet_prompt.txt", image_prompt)
    if spec_only:
        log(f"[시트] 사양까지만 했습니다. 그림은 안 그렸습니다 -> {spec_path}")
        return
    if dry_run:
        log(f"[시트] 이미지 프롬프트만 썼습니다 -> {run_dir / 'sheet_prompt.txt'}")
        return

    out = run_dir / "sheet.png"
    if out.exists():
        log(f"[시트] {out} 가 이미 있습니다. 다시 뽑으려면 지우세요.")
        return
    # 사진은 **안 붙인다.** 사양(appearance_en)이 기준이다.
    #
    # OpenAI 는 참조 이미지가 붙으면 편집 쪽으로 가서 "이 그림을 고쳐라" 에
    # 가깝게 읽는다. 올린 사진이 낙서나 다른 화풍이면 그것을 따라가느라
    # 사양대로 안 그린다. 사양은 이미 사진을 보고 쓴 것이라(SHEET 단계에서
    # 사진을 첨부해 읽는다) 여기서 사진을 또 붙일 이유가 없다.
    log("[시트] 그리는 중… (사진 없이 사양만)")
    sheet_provider, sheet_model, _q = imagegen.backend_for("SHEET_IMAGE")
    try:
        meta = sheetmod.paint(image_prompt, out)
    except Exception as exc:                                          # noqa: BLE001
        record_error(run_dir, "SHEET_IMAGE", sheet_provider, sheet_model, exc)
        raise
    record(run_dir, meta)
    log(f"  -> {out}")


def stage_pages(run_dir: Path, dry_run: bool, only=None,
                allow_no_sheet: bool = False) -> None:
    """페이지를 그린다 — **컷 하나에 한 번이 아니라 페이지 하나에 한 번.**

    비용은 페이지 하나가 끝날 때마다 바로 기록한다(on_page) — 다 그린 뒤
    한꺼번에 기록하면, 중간에 취소되거나 죽었을 때 이미 돈이 나간 앞쪽
    페이지들의 기록이 통째로 사라진다.
    """
    made = pageart.draw(run_dir, dry_run=dry_run, only=only,
                        allow_no_sheet=allow_no_sheet,
                        on_page=lambda meta: record(run_dir, meta))
    if made:
        log(f"[페이지] {len(made)}장 그렸습니다 -> {run_dir / pageart.PAGE_DIR}")


def stage_detail_pages(run_dir: Path, dry_run: bool, only=None,
                       allow_no_sheet: bool = False) -> None:
    """이어그리기(최종 방식) — **구체화·콘티·컷 대본을 전부 건너뛰고**
    story 단계(방향 후보) 산출물만으로 표지+전체 씬을 그린다.

    2026-09-02 이전에는 이 함수가 `detailart.draw()`(구체화 후 씬 단위)를
    불렀다 — 이제는 `detailart.draw_continue()`를 부른다. 씬 하나가 페이지
    하나가 되는 것은 같지만, 무엇을 그릴지 결정하는 재료가 detail.json이
    아니라 directions.json(+pick.json)이다. `detailart.draw()`·`build_prompt()`
    등 구체화 버전 코드는 지우지 않고 그대로 남겨 뒀다 — 나중에 다시 비교할
    수 있게.

    쓰는 자리가 `pages/` 로 같아서 둘러보기·편집실은 어느 흐름으로 만든
    것인지 몰라도 된다.
    """
    made = detailart.draw_continue(run_dir, dry_run=dry_run, only=only,
                                   allow_no_sheet=allow_no_sheet,
                                   on_page=lambda meta: record(run_dir, meta))
    if made:
        log(f"[이어그리기] {len(made)}장 그렸습니다 -> {run_dir / detailart.PAGE_DIR}")


# --------------------------------------------------------------------- CLI

def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="new_harness — 이야기 후보 · 콘티 · 캐릭터 시트",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--character", type=Path,
                   help="landing 의 character.json (또는 jobs/<id> 폴더)")
    p.add_argument("--name", help="캐릭터 이름 (필수)")
    p.add_argument("--photo", action="append", default=[], help="사진 (여러 번 가능)")
    p.add_argument("--desc", default="", help="설명 (선택)")
    p.add_argument("--genre", default="", help="장르 (선택)")

    p.add_argument("--run-id", help="이어서 할 run")
    p.add_argument("--pick", type=int, help="고를 방향 번호 (없으면 물어본다)")
    p.add_argument("--detail", action="store_true",
                   help="스토리 구체화만 (콘티로 이어가지 않는다)")
    p.add_argument("--cutscript", action="store_true",
                   help="컷 대본만 (컷 분할과 대사까지. 연출은 안 한다)")
    p.add_argument("--board", action="store_true",
                   help="콘티만 (앞 단계를 다시 돌리지 않는다)")
    p.add_argument("--review", action="store_true",
                   help="구체화 결과를 검수만 한다 (고치지 않는다)")
    p.add_argument("--fix", action="store_true",
                   help="검수 지적을 반영한다 (지적된 장면만 고친다)")
    p.add_argument("--cutscript-fix", action="store_true",
                   help="컷 대본만 다시 검수·자기수정한다 (기본 흐름에서 이미 "
                        "자동으로 도는 단계 — 컷 대본을 손으로 고친 뒤 다시 "
                        "돌리는 등 단독 재실행용. cutscript.json 은 안 건드리고 "
                        "결과는 cutscript_fix/ 아래에만 쓴다)")
    p.add_argument("--sheet", action="store_true", help="캐릭터 시트만")
    p.add_argument("--sheet-spec", action="store_true",
                   help="시트 사양(글)만. 그림은 안 그린다")
    p.add_argument("--sheet-from", type=Path,
                   help="이미 뽑아 둔 시트를 가져온다 (story-harness run 폴더 · "
                        "new_harness run 폴더 · png 하나). 호출 0회")
    p.add_argument("--pages", action="store_true",
                   help="페이지 그림만 (페이지 하나당 호출 한 번)")
    p.add_argument("--detail-pages", action="store_true",
                   help="이어그리기(최종 방식) — 구체화·콘티·컷 대본을 전부 "
                        "건너뛰고 방향 후보로 바로 페이지를 그린다 "
                        "(1페이지가 표지, 장면 하나가 페이지 하나)")
    p.add_argument("--pick-save", action="store_true",
                   help="다른 단계를 안 돌리고 pick.json 만 남긴다 — 이어그리기 "
                        "흐름은 구체화가 없어서, 방향을 고른 뒤 검수 화면으로 "
                        "가기 전에 이걸로 pick 만 기록한다 (호출 0회)")
    p.add_argument("--restory", action="store_true",
                   help="기존 run 에서 이야기 후보 4개를 다시 만든다 (방향 고르기 "
                        "화면에서 '다시 만들기' — --note 와 같이 쓸 수 있다)")
    p.add_argument("--page", type=int, action="append", default=[],
                   help="그 번호 페이지만 다시 (여러 번 가능)")
    p.add_argument("--no-sheet", action="store_true",
                   help="캐릭터 시트 없이 페이지를 그린다 (인물이 장마다 달라진다)")
    p.add_argument("--all", action="store_true",
                   help="이야기 -> 콘티 -> 시트 -> 페이지 그림까지 한 번에")
    p.add_argument("--max-ratio", type=int, default=None,
                   help="한 페이지의 높이 비율 합계 상한 (tiny1 small2 normal3 "
                        "large5). 안 주면 그림 프로바이더의 캔버스에서 뽑는다")
    p.add_argument("--repage", action="store_true",
                   help="콘티는 그대로 두고 페이지 묶기만 다시 한다 (호출 0회)")
    p.add_argument("--dry-run", action="store_true", help="프롬프트만 쓰고 호출하지 않는다")
    p.add_argument("--note", default="", help="다시 만들기에서 이번 시도에만 추가로 "
                                              "반영할 요청 (이야기·시트 단계에서 씀)")
    p.add_argument("--plan", action="store_true", help="단계별 모델만 보여준다")
    args = p.parse_args(argv)

    if args.plan:
        rows = llm.plan()
        cols = [
            ("단계", lambda r: r["stage"]),
            ("", lambda r: r["label"]),
            ("모델", lambda r: f"{r['provider']}:{r['model']}"),
            ("어디서", lambda r: r["from"]),
        ]
        table = [[head for head, _ in cols]] + [[get(r) for _, get in cols]
                                                for r in rows]
        widths = [max(_wide(row[i]) for row in table) for i in range(len(cols))]
        for i, row in enumerate(table):
            print("  " + "  ".join(_pad(cell, w) for cell, w in zip(row, widths)).rstrip())
            if i == 0:
                print("  " + "  ".join("─" * w for w in widths))
        print("\n  바꾸려면 .env 에 <단계>_PROVIDER / <단계>_MODEL 을 적으세요 "
              "(.env.example 참고).")
        return 0

    if args.run_id:
        run_dir = RUNS_DIR / args.run_id
        if not run_dir.exists():
            raise SystemExit(f"그런 run 이 없습니다: {run_dir}")
        char = read_input(run_dir)
        new_run = False
    else:
        char = (read_character(args.character) if args.character
                else normalize({"name": args.name, "description": args.desc,
                                "genre": args.genre, "photos": args.photo}))
        bad = gate_input(char)
        if bad:
            raise SystemExit("입력이 모자랍니다:\n  - " + "\n  - ".join(bad))
        run_dir = RUNS_DIR / story.new_run_id()
        write_json(run_dir / "input.json", char)
        new_run = True
        log(f"run: {run_dir}")

    # 시트 가져오기는 어느 흐름이든 **가장 먼저** 한다 — 뒤의 단계가 이 시트를
    # 참조로 쓰고, 이미 있으면 시트 단계가 새로 그리지 않는다.
    if args.repage:
        repage(run_dir, args.max_ratio)
        return 0

    if args.sheet_from:
        got = sheetmod.import_sheet(run_dir, args.sheet_from)
        who = f" ({got['name']})" if got.get("name") else ""
        log(f"[시트] 가져왔습니다{who} <- {got['from']}")
        log(f"  사양도 함께: {'예' if got['spec'] else '아니오 (그림만)'}")

    # 한 단계만 다시 돌리는 길. --all 이면 아래 전체 흐름을 탄다.
    #
    # --sheet-from 만 준 것도 여기서 끝난다 — 시트를 가져다 놓는 것이 그
    # 명령의 전부인데, 그냥 흘려보내면 아래 이야기 단계로 내려가 "어느 방향으로
    # 갈까요" 를 묻는다 (실제로 그래서 EOFError 로 죽었다).
    if not args.all and (args.detail or args.cutscript or args.board
                         or args.review or args.fix or args.cutscript_fix
                         or args.sheet or args.sheet_spec or args.pages or args.detail_pages
                         or args.page or args.sheet_from or args.pick_save or args.restory):
        if args.restory:
            # 방향 후보를 다시 만든다 — 이전 pick.json 은 더 이상 유효하지
            # 않다(방향 번호가 새로 나온 4개와 안 맞을 수 있다), 지운다.
            (run_dir / "pick.json").unlink(missing_ok=True)
            stage_story(run_dir, char, args.dry_run, note=args.note)
        if args.pick_save:
            chosen = picked_direction(run_dir, args.pick)
            write_json(run_dir / "pick.json", {"n": chosen["n"], "title": chosen["title"],
                                               "genre": chosen["genre"]})
            log(f"[방향 선택] {chosen['n']}번 저장했습니다 -> {run_dir / 'pick.json'}")
        if args.detail:
            chosen = picked_direction(run_dir, args.pick)
            write_json(run_dir / "pick.json", {"n": chosen["n"], "title": chosen["title"],
                                               "genre": chosen["genre"]})
            stage_detail(run_dir, char, chosen, args.dry_run)
        if args.cutscript:
            stage_cutscript(run_dir, char, picked_direction(run_dir, args.pick),
                            args.dry_run)
        if args.board:
            # 앞 단계를 다시 돌리지 않고 콘티만 — 구체화가 이미 끝난 run 에서
            # 콘티만 다시 뽑을 때(검수에서 되돌아온 경우) 쓴다. 없으면
            # `--pick N` 으로 둘 다 돌려야 해서 구체화 호출값이 그대로 버려진다.
            stage_board(run_dir, char, picked_direction(run_dir, args.pick),
                        args.dry_run, args.max_ratio)
        if args.review:
            stage_review(run_dir, char, picked_direction(run_dir, args.pick),
                         args.dry_run)
        if args.fix:
            path = run_dir / "review.json"
            if not path.exists():
                raise SystemExit(f"{path} 가 없습니다. 검수를 먼저 돌리세요.")
            stage_fix(run_dir, char, picked_direction(run_dir, args.pick),
                      json.loads(path.read_text(encoding="utf-8")), args.dry_run)
        if args.cutscript_fix:
            stage_cutscript_fix(run_dir, char, picked_direction(run_dir, args.pick),
                                 args.dry_run)
        if args.sheet or args.sheet_spec:
            stage_sheet(run_dir, char, args.dry_run, spec_only=args.sheet_spec, note=args.note)
        if args.detail_pages:
            stage_detail_pages(run_dir, args.dry_run, only=args.page or None,
                               allow_no_sheet=args.no_sheet)
        elif args.pages or args.page:
            stage_pages(run_dir, args.dry_run, only=args.page or None,
                        allow_no_sheet=args.no_sheet)
        return 0

    directions = []
    if new_run or args.all:
        directions = stage_story(run_dir, char, args.dry_run, note=args.note)
        if args.dry_run:
            return 0
        if not args.all and args.pick is None:
            show_directions(directions)
            print(f"\n골랐으면:  python run.py --run-id {run_dir.name} --pick <번호>")
            return 0
    else:
        path = run_dir / "directions.json"
        if not path.exists():
            raise SystemExit(f"{path} 가 없습니다. 이야기 단계를 먼저 돌리세요.")
        directions = json.loads(path.read_text(encoding="utf-8"))

    if not directions:
        raise SystemExit("고를 방향이 없습니다. story.md 를 보고 프롬프트를 확인하세요.")

    direction = choose(directions, args.pick)
    stage_detail(run_dir, char, direction, args.dry_run)
    # 컷 대본이 콘티보다 먼저다 — 컷 분할과 대사를 확정한 뒤에야 연출로
    # 넘어간다 (stage_cutscript 의 주석 참고).
    stage_cutscript(run_dir, char, direction, args.dry_run)
    # 컷 대본을 독자로서 읽고 스스로 고친다 (stage_cutscript_fix 의 주석
    # 참고) — 이 결과(cutscript_final.json)를 콘티가 실제로 따른다
    # (board_block 의 load_cutscript 참고).
    stage_cutscript_fix(run_dir, char, direction, args.dry_run)
    # 검수·보강은 흐름에서 뺐다. 검수가 실제로 무엇을 잡는지 아직 확인이
    # 안 됐고(한 번 돌렸을 때 0개였다), 아무것도 못 잡은 결과로 고치면 고칠
    # 것이 없다. --review · --fix 로 따로 부른다.
    stage_board(run_dir, char, direction, args.dry_run, args.max_ratio)

    if args.all or args.sheet:
        # 시트가 페이지보다 **먼저** 나와야 한다. 페이지를 그릴 때 참조로
        # 붙는 것이 이 시트다.
        stage_sheet(run_dir, char, args.dry_run)
    if args.all or args.pages:
        stage_pages(run_dir, args.dry_run,
                    allow_no_sheet=args.no_sheet)

    log(f"끝났습니다 -> {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
