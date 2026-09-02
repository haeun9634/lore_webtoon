"""조연은 누구인가 — 컷마다 다른 사람으로 그려지는 것을 막는다.

주인공은 캐릭터 시트가 지켜 준다. 조연은 지켜 주는 것이 하나도 없었다.
파이프라인 어디에도 조연의 외형이 없기 때문이다:

    arc1_episodes.json
      "new_cast": [{"name": "시하의 동기 (이름 미정)",
                    "note": "시하와 윤재를 몰래 찍어 소문을 퍼뜨린 학과 동기"}]

이름과 한 줄 메모뿐이다. 그리고 이미지 프롬프트가 조연에 대해 말하는 것은
조건 문구의 이 한 줄이 전부였다:

    "any other people in the panel must look clearly different from the sheet"

= "주인공과 다르게만 그려라." 머리색도 키도 옷도 성별도 아무도 정해 주지
않았으니 모델이 매번 새로 만든다. 실제로 같은 화 안에서 윤재가 Scene 1 은
회색 티의 짧은 머리 남자, Scene 2 는 흰 셔츠에 데님 자켓을 걸친 다른 얼굴로
나왔다.

## 어떻게 고정하는가

cast.json 과 같은 길이다 — 코드가 초안을 만들고 사람이 고친다.

  1. 첫 실행에서 supporting.json 초안을 만든다. 스토리 쪽에서 이름을 긁어
     오되 외형은 **빈 칸**으로 둔다. 지어내지 않는다: 스토리가 정하지 않은
     것을 이 하네스가 정하면, 다음 화에서 스토리가 다른 말을 할 때 어긋난다.
  2. 사람이 빈 칸을 채운다 (API 호출 없이, 0원).
  3. 채워진 사람만 프롬프트에 박힌다. 그 컷 서술에 이름이 나올 때만 붙는다 —
     안 나오는 사람까지 매번 붙이면 프롬프트가 길어지고, 모델이 화면에 없는
     인물을 그려 넣는다.

빈 칸으로 두면 예전과 똑같이 동작한다. 채운 만큼만 고정된다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cast

SUPPORTING_FILE = "supporting.json"

# 프롬프트에 박히는 머리말. design_lock 과 같은 방식으로 코드가 붙인다.
HEAD = ("Recurring supporting characters. If any of them appear in this panel, "
        "draw them exactly as described here — same face, hair, build and "
        "outfit in every panel they appear in. They are NOT the main character; "
        "never give them the attached sheet's face:")

# 외형이 비어 있는 인물에게도 붙는 문구.
#
# 아무 말도 안 하면 모델은 이 인물을 매 컷 처음 만나는 사람으로 그린다. 외형을
# 지정할 수 없더라도 "같은 사람이다"는 말은 할 수 있고, 그것만으로도 한 화 안의
# 흔들림이 줄어든다. 특히 성별이 바뀌는 것은 이 한 줄로 대부분 막힌다.
CARRY_HEAD = (
    "These named people also appear in this episode. Their design is not "
    "specified here, so decide it once and then keep it: whatever face, hair, "
    "build, gender and clothing you give each of them must stay the same in "
    "every panel of this episode. Do not re-invent them per panel, and do not "
    "swap anyone's gender. They are NOT the main character:")

# 인물 카드의 항목. story-harness 의 webtoon.CAST_FIELDS 와 같은 이름이어야
# 한다 — 스토리가 채운 값을 그대로 받아 오기 때문이다.
CARD_FIELDS = ("gender", "appearance", "outfit", "personality")
CARD_LABEL = {"gender": "성별", "appearance": "외형",
              "outfit": "옷차림", "personality": "성격"}

# 스토리 단계는 한국어로 "남성/여성" 을 적는다. 그 낱말이 영문 프롬프트 한가운데
# 그대로 박히면 이미지 모델이 성별 지시를 흘린다 — 실제로 남자 후배가 여자로
# 그려졌다. 프롬프트에 나갈 때만 영어로 바꾼다(원본 값은 그대로 둔다).
GENDER_EN = {"남성": "male", "남자": "male", "남": "male",
             "여성": "female", "여자": "female", "여": "female"}


def en_gender(value: str) -> str:
    """'남성' → 'male'. 모르는 표현은 손대지 않는다 — 지어내는 것보다 낫다."""
    text = str(value or "").strip()
    return GENDER_EN.get(text, text)

# 이름 뒤에 붙는 설명을 떼어낸다. "하윤재 — 같은 학과 남후배, …" → "하윤재"
#
# 쉼표가 목록에 **있어야 한다.** p1 의 relational_gap.anchor 는 이름과 설명을
# 쉼표로 잇는다("운학, 화산파의 사형이자 청명의 유일한 친구"). 쉼표가 없으면 그
# 문장 전체가 이름이 되어, 같은 사람이 진짜 이름과 문장 두 사람으로 명부에 오르고
# 프롬프트가 "이 사람도 설계해서 매 컷 유지하라"고 두 번 지시한다 — 한 화에서
# 한 인물이 서로 다른 두 사람으로 그려진다. scan_story() 가 supporting_cast 를
# anchor 보다 먼저 넣어 막으려 한 것이 바로 이것인데, 여기서 못 자르면 그 순서
# 가드가 헛돈다(이름이 다르면 중복으로 안 걸리기 때문이다).
# 사람 이름에는 쉼표가 들어가지 않으므로 떼어내도 잃을 것이 없다.
NAME_SPLIT = re.compile(r"\s*[,、—–\-·:(（]\s*")
HANGUL_NAME = re.compile(r"[가-힣]{2,4}")


@dataclass
class Person:
    """조연 한 명의 인물 카드. story-harness 의 new_cast 와 같은 항목이다.

    외형(appearance)과 옷차림(outfit)을 나눠 둔다. 외형은 끝까지 안 바뀌지만
    옷은 장면에 따라 바뀔 수 있다 — 한 칸에 뭉쳐 두면 그리는 쪽이 둘을 구분하지
    못해 옷을 바꾸려다 머리색까지 흔든다. 주인공에게서 실제로 그 일이 났다.
    """
    name: str
    gender: str = ""
    appearance: str = ""      # 안 바뀌는 것 — 머리·눈·키·체형·특징
    outfit: str = ""          # 늘 입는 옷 한 벌
    personality: str = ""     # 표정과 자세로 드러나는 것
    note: str = ""            # 스토리가 준 한 줄. 카드를 채울 때 참고용이다.

    @property
    def filled(self) -> bool:
        return any(x.strip() for x in
                   (self.gender, self.appearance, self.outfit))

    def line(self) -> str:
        """프롬프트 한 줄. 성격은 표정 지시라 뒤에 따로 붙인다."""
        bits = [b for b in (en_gender(self.gender), self.appearance.strip()) if b]
        if not bits and not self.outfit.strip():
            return ""
        head = f"{self.name}: {', '.join(bits)}" if bits else f"{self.name}:"
        if self.outfit.strip():
            head += f". Always wears: {self.outfit.strip()}"
        if self.personality.strip():
            head += (f". Personality to show through expression and posture: "
                     f"{self.personality.strip()}")
        return head


@dataclass
class Book:
    """이 화의 조연 명부. 파일이 없어도 이 모양 그대로 돌아온다."""
    people: list[Person] = field(default_factory=list)
    source: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def filled(self) -> list[Person]:
        return [p for p in self.people if p.filled]

    @property
    def empty(self) -> list[Person]:
        return [p for p in self.people if not p.filled]


def supporting_path(ep_dir: Path) -> Path:
    return ep_dir / SUPPORTING_FILE


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(v) for v in value if _text(v))
    if isinstance(value, dict):
        return ", ".join(f"{k}: {_text(v)}" for k, v in value.items() if _text(v))
    return "" if value is None else str(value).strip()


def short_name(raw: str) -> str:
    """"하윤재 — 같은 학과 남후배, …" → "하윤재". 대조에 쓸 이름만 남긴다."""
    head = NAME_SPLIT.split(_text(raw), 1)[0].strip()
    return head or _text(raw)


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None


def scan_story(run_dir: Path, main_name: str = "") -> list[Person]:
    """스토리 산출물에서 조연 이름을 긁는다. 외형은 채우지 않는다.

    두 곳을 본다:
      p1.json  relational_gap.anchor — "모두에게 X, 한 명에게만 Y" 의 그 한 명.
               주인공 다음으로 자주 나오는 인물인데 new_cast 에는 없다.
      webtoon/arc*_episodes.json  new_cast[] — 화마다 새로 등장한 인물.

    이름이 겹치면 먼저 본 것을 남긴다. 스토리가 준 note 는 그대로 옮긴다 —
    사람이 외형을 채울 때 "이 사람이 누구였더라"를 다시 찾지 않게.
    """
    found: dict[str, Person] = {}
    main = short_name(main_name)

    def add(raw_name: str, note: str = "", card: Any = None) -> None:
        name = short_name(raw_name)
        if not name or (main and name == main):
            return
        if name in found:
            return
        row = card if isinstance(card, dict) else {}
        found[name] = Person(name=name, note=_text(note) or _text(raw_name),
                             **{k: _text(row.get(k)) for k in CARD_FIELDS})

    p1 = _read_json(run_dir / "p1.json")
    if isinstance(p1, dict):
        # supporting_cast 를 먼저 본다 — 여기가 조연 이름·성별·외형이 처음
        # 확정되는 자리다. anchor 는 같은 사람을 설명 문장째로 담고 있어서,
        # 먼저 넣으면 이름이 아니라 문장이 이름이 된다.
        for row in p1.get("supporting_cast") or []:
            if isinstance(row, dict):
                add(_text(row.get("name")),
                    _text(row.get("relation")) or _text(row.get("role")), row)
        gap = p1.get("relational_gap")
        if isinstance(gap, dict):
            anchor = _text(gap.get("anchor"))
            if anchor:
                add(anchor, anchor)

    for path in sorted((run_dir / "webtoon").glob("arc*_episodes.json")):
        data = _read_json(path)
        episodes = (data or {}).get("episodes") if isinstance(data, dict) else None
        for ep in episodes or []:
            for row in (ep.get("new_cast") or []) if isinstance(ep, dict) else []:
                if isinstance(row, dict):
                    # story-harness 가 외형을 채워 주면 그대로 받는다 (w5 가
                    # gender/appearance 를 쓰게 된 뒤의 run). 없으면 빈 칸이고
                    # 사람이 채운다 — 여기서 지어내지 않는다.
                    add(_text(row.get("name")), _text(row.get("note")), row)
                else:
                    add(_text(row))

    # 화가 진행되면 명부(series.json)가 더 정확하다 — 나중 화에서 외형이
    # 채워졌을 수 있다. 이미 찾은 사람의 빈 칸만 메운다.
    series = _read_json(run_dir / "webtoon" / "series.json")
    for row in (series or {}).get("cast") or [] if isinstance(series, dict) else []:
        if not isinstance(row, dict):
            continue
        name = short_name(row.get("name"))
        person = found.get(name)
        if person is None:
            add(_text(row.get("name")), _text(row.get("note")), row)
        else:
            for key in CARD_FIELDS:
                if not getattr(person, key).strip():
                    setattr(person, key, _text(row.get(key)))
    return list(found.values())


def write_draft(ep_dir: Path, people: list[Person]) -> Path:
    """초안을 쓴다. 스토리가 안 채운 칸은 빈 칸이다 — 지어내면 어긋난다."""
    path = supporting_path(ep_dir)
    payload = {
        "_읽는 법": "이 화에 나오는 조연입니다. 스토리 단계(w5)가 채운 값이 "
                    "그대로 들어옵니다. 비어 있으면 사람이 채우세요 — 채운 만큼 "
                    "그 사람이 나오는 컷마다 프롬프트에 박힙니다.",
        "_왜": "조연은 캐릭터 시트가 없어서, 비워 두면 컷마다 다른 사람으로 "
               "그려집니다. 성별까지 매번 바뀝니다.",
        "_항목": {
            "gender": "male | female | 자유 문구",
            "appearance": "**안 바뀌는 것만** — 머리(길이·색·모양), 눈, 키와 "
                          "체형, 특징 하나. 옷은 여기 적지 마세요.",
            "outfit": "**늘 입는 옷 한 벌.** 여러 벌 나열하면 컷마다 아무거나 "
                      "고릅니다 (주인공에게서 실제로 그 일이 났습니다).",
            "personality": "표정과 자세로 드러나는 성격·버릇. 얼굴이 밋밋하게 "
                           "나오는 것을 막습니다.",
        },
        "_어떻게": "영어로 적으세요 — 프롬프트에 그대로 들어갑니다. 예: "
                   "appearance \"tall slim young man, short messy black hair, "
                   "droopy eyes\" / outfit \"grey T-shirt under an open denim "
                   "jacket, black slacks, white sneakers\".",
        "_주의": "이 파일은 화마다 다릅니다. 다른 run 의 것을 복사해 오면 다른 "
                 "사람이 붙습니다.",
        "cast": [{"name": p.name,
                  **{k: getattr(p, k) for k in CARD_FIELDS},
                  "note": p.note} for p in people],
    }
    ep_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def load(ep_dir: Path, run_dir: Path | None = None,
         main_name: str = "") -> Book:
    """supporting.json 을 읽는다. 없으면 스토리에서 긁어 초안을 만들어 둔다.

    사람이 고친 파일이 언제나 최우선이다. 다만 스토리에 새 인물이 생겼는데
    파일에 없으면 빈 칸으로 덧붙인다 — 화가 진행되면서 조연이 늘기 때문이다.
    이미 채워 둔 값은 건드리지 않는다.
    """
    book = Book()
    path = supporting_path(ep_dir)
    data = _read_json(path)

    if isinstance(data, dict) and isinstance(data.get("cast"), list):
        for row in data["cast"]:
            if not isinstance(row, dict):
                continue
            name = short_name(row.get("name"))
            if name:
                book.people.append(Person(
                    name=name, note=_text(row.get("note")),
                    **{k: _text(row.get(k)) for k in CARD_FIELDS}))
        book.source = SUPPORTING_FILE
    elif data is not None:
        book.notes.append(f"{path} 를 읽지 못했습니다 (형식이 다릅니다) — "
                          f"조연 고정 없이 진행합니다.")
        return book

    if run_dir is None:
        return book

    known = {p.name for p in book.people}
    fresh = [p for p in scan_story(run_dir, main_name) if p.name not in known]
    if fresh:
        book.people.extend(fresh)
        write_draft(ep_dir, book.people)
        book.source = book.source or f"{SUPPORTING_FILE} (새로 만듦)"
        book.notes.append(
            f"조연 {len(fresh)}명을 새로 찾아 {SUPPORTING_FILE} 에 추가했습니다: "
            f"{', '.join(p.name for p in fresh)}")
    return book


def block(book: Book, text: str) -> str:
    """이 컷 서술에 이름이 나오는 조연만 골라 프롬프트 블록으로 만든다.

    전부 붙이지 않는 이유: 화면에 없는 인물을 설명하면 모델이 그 사람을 그려
    넣는다. 실제로 "조연은 주인공과 다르게 그려라"만 있던 때에도 없던 인물이
    끼어들었다.

    외형을 채운 사람과 안 채운 사람은 말하는 방식이 다르다. 채운 쪽은 "이렇게
    그려라", 안 채운 쪽은 "네가 정하되 이 화 내내 바꾸지 마라". 후자는 외형을
    지정하지 못해도 성별이 컷마다 뒤집히는 것은 막아 준다.
    """
    haystack = _text(text)
    if not haystack:
        return ""
    # 이름 대조는 cast.name_keys 와 같은 규칙이다. 명부에는 "하윤재" 로 있어도
    # 서술에는 "윤재가", "윤재는" 으로 나온다 — 전체 이름만 찾으면 한 번도 안
    # 걸린다 (실제로 그랬다). 성을 뗀 형태까지 키로 본다.
    here = [p for p in book.people
            if any(k in haystack for k in cast.name_keys(p.name))]

    parts: list[str] = []
    fixed = [p.line() for p in here if p.filled]
    fixed = [ln for ln in fixed if ln]
    if fixed:
        parts.append(f"{HEAD}\n" + "\n".join(f"- {ln}" for ln in fixed))

    loose = [p for p in here if not p.filled]
    if loose:
        parts.append(f"{CARRY_HEAD}\n"
                     + "\n".join(f"- {p.name}" for p in loose))
    return "\n".join(parts)


def table(book: Book) -> str:
    """--dry-run 에서 찍을 표. **어느 칸이** 비어 있는지가 한눈에 보여야 한다."""
    if not book.people:
        return "        (조연 없음)"
    rows = []
    for p in book.people:
        gone = [CARD_LABEL[k] for k in CARD_FIELDS if not getattr(p, k).strip()]
        mark = "완성" if not gone else ("빈칸 " + "·".join(gone))
        detail = p.line() or (p.note[:44] + ("…" if len(p.note) > 44 else ""))
        rows.append(f"        {p.name:<10} [{mark}]\n          {detail}")
    return "\n".join(rows)
