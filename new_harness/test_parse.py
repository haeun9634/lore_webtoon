#!/usr/bin/env python3
"""new_harness 검사 — 모델 응답을 잘라 읽는 부분과 시트 사양 게이트.

호출은 하지 않는다. 돈이 안 든다.

    python3 test_parse.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import imageprompt as IP  # noqa: E402
import pages as P        # noqa: E402
import run as R          # noqa: E402
import sheet as S        # noqa: E402
import stitch as ST      # noqa: E402

FAILED = []


def check(name: str, got, want) -> None:
    if got != want:
        FAILED.append(f"{name}\n    나온 것: {got!r}\n    바라던 것: {want!r}")


def ok(name: str, cond, why: str = "") -> None:
    if not cond:
        FAILED.append(f"{name}{('  — ' + why) if why else ''}")


# ------------------------------------------------------------- 이야기 후보

STORY_MD = """\
네, 네 방향을 제안합니다.

## 방향 1 — 밤에만 열리는 강의실

장르: 오컬트 미스터리

### 줄거리
하은은 폐강된 강의실에 불이 켜져 있는 것을 본다.
들어가 보니 칠판에 내일 시험 문제가 이미 적혀 있다.

### 장면 목록
1. 하은이 야간 자습을 마치고 나오다 3층 복도의 불빛을 본다.
2. 문을 두 번 지나쳤다가 결국 손잡이를 돌린다.
3. 칠판에 적힌 문제를 사진으로 찍는다.
4. 다음 날 시험지에서 같은 문제를 발견하고 손을 멈춘다.

### 밝히지 않은 것
- 누가 칠판에 적었는지
- 하은 말고 그 강의실을 본 사람이 있는지

## 방향 2 — 택배가 먼저 안다

장르: 일상 스릴러

### 줄거리
받은 적 없는 택배가 문 앞에 놓인다.

### 장면 목록
- 하은이 문 앞의 상자를 발견하고 송장을 확인한다.
- 자기 이름이 맞는데 보낸 사람 칸이 비어 있다.
- 상자를 열자 어제 잃어버린 이어폰이 들어 있다.

### 밝히지 않은 것
- 누가 주웠고 왜 돌려줬는지

## 방향 3 — 한 정거장 더

장르: 로맨스

### 줄거리
매일 같은 칸에 타는 사람이 있다.

### 장면 목록
1. 하은이 늘 타던 칸을 놓치고 다음 칸에 탄다.
2. 옆자리 사람이 하은의 이름을 부른다.

### 밝히지 않은 것
- 그 사람이 어떻게 이름을 아는지

## 방향 4 — 물이 마르지 않는 층

장르: 판타지

### 줄거리
기숙사 4층 복도만 늘 젖어 있다.

### 장면 목록
1. 하은이 젖은 복도에서 미끄러지고, 물이 위가 아니라 아래에서 올라온 것을 본다.
2. 관리인에게 말하지만 4층은 작년에 폐쇄됐다는 답을 듣는다.
3. 자기 방 열쇠에 4층 호수가 적혀 있는 것을 확인한다.

### 밝히지 않은 것
- 왜 하은의 열쇠만 4층인지
- 물이 어디서 오는지
"""


def test_directions() -> None:
    ds = R.parse_directions(STORY_MD)
    check("방향 개수", len(ds), 4)
    check("번호", [d["n"] for d in ds], [1, 2, 3, 4])
    check("제목", ds[0]["title"], "밤에만 열리는 강의실")
    check("장르", [d["genre"] for d in ds],
          ["오컬트 미스터리", "일상 스릴러", "로맨스", "판타지"])
    check("장면 개수 (번호 목록)", len(ds[0]["scenes"]), 4)
    check("장면 개수 (- 목록)", len(ds[1]["scenes"]), 3)
    check("첫 장면", ds[0]["scenes"][0],
          "하은이 야간 자습을 마치고 나오다 3층 복도의 불빛을 본다.")
    check("밝히지 않은 것", len(ds[3]["hidden"]), 2)
    ok("줄거리에 장면 목록이 안 섞였다", "장면" not in ds[0]["plot"], ds[0]["plot"])
    ok("머리말은 방향에 안 들어갔다", "네 방향을 제안합니다" not in ds[0]["raw"])

    # 고르기 — 번호로 찾는다
    check("--pick 3", R.choose(ds, 3)["title"], "한 정거장 더")
    try:
        R.choose(ds, 9)
    except SystemExit:
        pass
    else:
        FAILED.append("없는 번호를 골랐는데 안 멈췄다")


# ------------------------------------------------------------------- 콘티

BOARD_JSON = """설명을 붙여 드립니다.

```json
{
  "cast": [
    {"name": "담당 교수",
     "appearance": "40대 초반, 큰 키에 마른 체격. 짧은 은회색 머리, 짙은 청색 눈."},
    {"name": "관리인", "appearance": "60대, 굽은 등, 회색 작업복."}
  ],
  "scenes": [
    {
      "id": 1,
      "summary": "하일은 입학식에서 이름이 불리자 지팡이를 들고 주문을 외운다",
      "location": "마법학교 중앙 대강당의 입학식장",
      "time": "실내조명",
      "cuts": [
        {
          "id": 1,
          "size": "large",
          "camera": {"shot": "광각", "angle": "정면"},
          "background": {"type": "실제공간", "desc": "높은 천장과 늘어선 마법등"},
          "characters": [
            {"name": "하일", "style": "LD", "position": "왼쪽", "facing": "앞모습",
             "expression": "긴장한 표정", "action": "이름이 불려 고개를 든다",
             "moment": "직후", "framing": "무릎 위"},
            {"name": "담당 교수", "style": "LD", "position": "오른쪽", "facing": "옆모습",
             "expression": "무표정", "action": "명단을 본다",
             "moment": "도중", "framing": "상반신"}
          ],
          "dialogue": [
            {"order": 2, "speaker": null, "type": "나레이션", "text": "입학식 사흘째.",
             "bubble": {"shape": "네모 상자", "tail": null, "position": "왼쪽 위"}},
            {"order": 1, "speaker": "담당 교수", "type": "화면밖", "text": "하일.",
             "bubble": {"shape": "둥근 타원", "tail": "컷 바깥", "position": "오른쪽 위"}}
          ],
          "sfx": [
            {"text": "웅성…", "source": "학생들", "position": "오른쪽 아래",
             "reason": "이름이 불린 뒤 이는 술렁임"}
          ],
          "forbid": [],
          "note": "시선이 하일에게 모이는 흐름을 만든다"
        },
        {
          "id": 2,
          "size": "normal",
          "camera": {"shot": "상반신", "angle": "정면"},
          "background": {"type": "효과", "desc": "지팡이 끝에서 흔들리는 마력"},
          "characters": [
            {"name": "하일", "style": "LD", "position": "왼쪽",
             "expression": "초조한 표정", "action": "주문을 외우다 말이 꼬임",
             "moment": "도중", "framing": "상반신"}
          ],
          "dialogue": [
            {"order": 1, "speaker": "하일", "type": "말", "text": "……그리고, 어둠을—",
             "bubble": {"shape": "둥근 타원", "tail": "하일", "position": "왼쪽 위"}},
            {"order": 2, "speaker": "하일", "type": "생각", "text": "아니, 빛을……?",
             "bubble": {"shape": "구름", "tail": "하일", "position": "오른쪽 아래"}}
          ],
          "sfx": [],
          "forbid": ["교수의 얼굴"],
          "note": "메모는 그림에 안 나가야 한다"
        }
      ]
    },
    {
      "id": 2,
      "summary": "관리인이 하일을 부른다",
      "location": "기숙사 복도",
      "time": "밤",
      "cuts": [
        {
          "id": 1,
          "size": "tiny",
          "camera": {"shot": "부분", "angle": "정면"},
          "background": {"type": "없음", "desc": ""},
          "characters": [
            {"name": "하일", "style": "LD", "expression": "(얼굴 없음)",
             "action": "손이 멈춘다", "moment": "직전", "framing": "손만"}
          ],
          "dialogue": [
            {"order": 1, "speaker": null, "type": "글", "text": "파일은 삭제해 주세요.",
             "bubble": {"shape": null, "tail": null, "position": "노트북 화면 안"}}
          ],
          "sfx": [{"text": "사아…", "source": "복도", "position": "화면 전체",
                   "reason": "정적"}],
          "forbid": [],
          "note": ""
        }
      ]
    }
  ]
}
```
"""


def test_board() -> None:
    board = R.parse_board(BOARD_JSON)
    check("cast 2명", [c["name"] for c in board["cast"]], ["담당 교수", "관리인"])
    scenes = board["scenes"]
    check("장면 2개", len(scenes), 2)
    check("장소", scenes[0]["location"], "마법학교 중앙 대강당의 입학식장")
    check("시간대", scenes[1]["time"], "밤")
    check("장면 1 컷 수", len(scenes[0]["cuts"]), 2)

    cut = scenes[0]["cuts"][0]
    check("size", cut["size"], "large")
    check("카메라", cut["camera"], {"shot": "광각", "angle": "정면"})
    check("배경", cut["background"]["type"], "실제공간")
    check("인물 2명", len(cut["characters"]), 2)
    # facing 은 camera 가 아니라 인물마다 하나씩이다 — 마주 보는 두 인물이
    # 서로 다른 facing 을 가질 수 있어야 한다(storyboard_prompt 참고).
    check("인물별 facing", [c["facing"] for c in cut["characters"]], ["앞모습", "옆모습"])
    # order 가 뒤집혀 온 것을 바로 세운다 — 읽는 순서가 곧 배치 순서다
    check("order 대로 정렬", [d["order"] for d in cut["dialogue"]], [1, 2])
    check("정렬된 첫 대사", cut["dialogue"][0]["text"], "하일.")
    check("forbid 는 배열", scenes[0]["cuts"][1]["forbid"], ["교수의 얼굴"])

    check("JSON 만 와도 같다", len(R.parse_board(
        BOARD_JSON[BOARD_JSON.index("{"):BOARD_JSON.rindex("}") + 1])["scenes"]), 2)
    try:
        R.parse_board("JSON 이 아닙니다")
    except Exception:
        pass
    else:
        FAILED.append("JSON 이 아닌데 안 멈췄다")

    # 번호가 없으면 나온 순서로 매긴다
    guessed = R.parse_board('{"scenes":[{"cuts":[{"size":"normal"},{"size":"tiny"}]}]}')
    check("장면 번호를 매긴다", guessed["scenes"][0]["id"], 1)
    check("컷 번호를 매긴다", [c["id"] for c in guessed["scenes"][0]["cuts"]], [1, 2])


def test_gate_board() -> None:
    check("멀쩡한 콘티는 통과", R.gate_board(R.parse_board(BOARD_JSON)), [])

    def issues(obj) -> list:
        return R.gate_board(R.parse_board(json.dumps(obj, ensure_ascii=False)))

    ok("장면이 없으면 잡는다", issues({"scenes": []}))
    ok("location 이 없으면 잡는다",
       any("location" in x for x in issues(
           {"scenes": [{"id": 1, "cuts": [{"size": "normal"}]}]})))
    ok("size 가 이상하면 잡는다",
       any("size" in x for x in issues(
           {"scenes": [{"id": 1, "location": "홀", "cuts": [{"size": "거대"}]}]})))
    ok("moment 가 없으면 잡는다",
       any("moment" in x for x in issues({"scenes": [{"id": 1, "location": "홀", "cuts": [
           {"size": "normal", "characters": [{"name": "하일"}]}]}]})))
    ok("둘 이상인데 position 이 없으면 잡는다",
       any("position" in x for x in issues({"scenes": [{"id": 1, "location": "홀", "cuts": [
           {"size": "normal", "characters": [
               {"name": "하일", "moment": "도중"},
               {"name": "교수", "moment": "도중"}]}]}]})))
    ok("한 명뿐이면 position 이 없어도 된다",
       not any("position" in x for x in issues({"scenes": [{"id": 1, "location": "홀",
           "cuts": [{"size": "normal", "characters": [
               {"name": "하일", "moment": "도중"}]}]}]})))
    # 좌우가 장면 안에서 바뀌는 것 — 다 그린 뒤에 발견하면 다시 그리는 값이 비싸다.
    # 단, 콘티 프롬프트의 규칙이 "한 컷에 두 명 이상" 이라 그 경우에만 본다.
    def two(pos_a: str, pos_b: str) -> list:
        return issues({"scenes": [{"id": 1, "location": "홀", "cuts": [
            {"size": "normal", "characters": [
                {"name": "교수", "moment": "도중", "position": pos_a},
                {"name": "하일", "moment": "도중", "position": "왼쪽"}]},
            {"size": "normal", "characters": [
                {"name": "교수", "moment": "도중", "position": pos_b},
                {"name": "하일", "moment": "도중", "position": "왼쪽"}]}]}]})

    ok("둘 이상인 컷에서 좌우가 바뀌면 잡는다", any("좌우" in x for x in two("오른쪽", "가운데")))
    ok("안 바뀌면 안 잡는다", not any("좌우" in x for x in two("오른쪽", "오른쪽")))
    # 혼자 나오는 컷은 안 잡는다 — 복도를 걸어가며 화면 안에서 옮겨 가는 것은
    # 정상적인 연출이고, 그것까지 잡으면 게이트가 매번 울려 아무도 안 본다
    ok("혼자면 좌우가 바뀌어도 안 잡는다",
       not any("좌우" in x for x in issues({"scenes": [{"id": 1, "location": "복도", "cuts": [
           {"size": "normal", "characters": [
               {"name": "박하은", "moment": "도중", "position": "가운데"}]},
           {"size": "normal", "characters": [
               {"name": "박하은", "moment": "도중", "position": "오른쪽"}]}]}]})))
    ok("대사 text 가 비면 잡는다",
       any("text" in x for x in issues({"scenes": [{"id": 1, "location": "홀", "cuts": [
           {"size": "normal", "dialogue": [{"order": 1, "text": ""}]}]}]})))


# --------------------------------------------------------------- 시트 사양

GOOD_SPEC = """{
  "name": "이하은",
  "appearance_en": "A young Korean woman in her early twenties, shoulder-length black hair tucked behind one ear, dark brown eyes, slim build, oversized grey hoodie over a white tee, dark jeans.",
  "design_details": [
    "왼쪽 손목에만 감은 검정 헤어끈 두 겹",
    "후드 오른쪽 주머니만 실밥이 터져 벌어져 있다",
    "왼쪽 눈썹 끝에 짧은 흉터 한 줄"
  ],
  "props": [
    "A4 가 겨우 들어가는 낡은 캔버스 에코백, 회색, 바닥 모서리가 닳아 실이 보인다"
  ],
  "color_palette": {
    "hair": "ink black (#22252A)",
    "eyes": "dark brown (#4A3229)",
    "skin": "warm ivory (#F1E0CE)",
    "outfit_main": "ash grey (#8E8B85)",
    "outfit_sub": "off white (#F2F0EA)",
    "accent": "muted coral (#D9705F)"
  },
  "expression_set": [
    "평온 — 입은 다물고 눈꺼풀이 살짝 내려온, 힘이 빠진 얼굴",
    "놀람 — 눈이 크게 열리고 눈썹이 위로, 입은 작게 벌어진",
    "두려움 — 눈은 크게 뜬 채 눈썹 안쪽이 올라가고 턱에 힘이 들어간",
    "결심 — 입술을 안으로 물고 눈은 한 점을 보는",
    "지침 — 눈을 반쯤 감고 고개가 살짝 기운",
    "안도 — 눈꼬리가 내려가고 입꼬리가 아주 조금 올라간"
  ]
}"""


def test_spec() -> None:
    spec = S.parse_spec("설명을 붙여서 드립니다:\n```json\n" + GOOD_SPEC + "\n```")
    check("이름", spec["name"], "이하은")
    check("고정 요소 3개", len(spec["design_details"]), 3)
    check("소지품 1개", len(spec["props"]), 1)
    check("표정 6개", len(spec["expression_set"]), 6)
    check("게이트 통과", S.gate_spec(spec), [])

    def bad(mutate, why: str) -> None:
        import copy
        broken = copy.deepcopy(spec)
        mutate(broken)
        ok(f"게이트가 잡는다: {why}", S.gate_spec(broken), why)

    bad(lambda s: s.update(appearance_en="검은 머리의 대학생"), "appearance_en 에 한글")
    bad(lambda s: s.update(appearance_en=""), "appearance_en 이 빔")
    bad(lambda s: s.update(name=""), "이름이 빔")
    bad(lambda s: s["design_details"].pop(), "고정 요소가 2개")
    bad(lambda s: s["expression_set"].pop(), "표정이 5개")
    bad(lambda s: s["color_palette"].update(eyes=""), "팔레트 한 칸이 빔")
    bad(lambda s: s["color_palette"].update(eyes="짙은 갈색"), "팔레트에 hex 가 없음")
    bad(lambda s: s.update(props=["가", "나", "다", "라", "마"]), "소지품이 5개")

    # 소지품이 없어도 통과한다 — 없는 것을 지어내게 만들면 안 된다
    import copy
    empty = copy.deepcopy(spec)
    empty["props"] = []
    check("소지품 0개도 통과", S.gate_spec(empty), [])


def test_sheet_prompt() -> None:
    spec = S.parse_spec(GOOD_SPEC)
    text = S.build_prompt(spec, style="Korean webtoon style")

    ok("4면도 영역", "REGION 1" in text and "turnaround" in text)
    ok("표정 영역", "REGION 2" in text and "6 expressions" in text)
    ok("디테일 영역", "REGION 3" in text and "3 close-up insets" in text)
    ok("소지품 영역", "REGION 4" in text and "1 carried items" in text)
    ok("색상 칩 영역", "REGION 5" in text and "swatch chips" in text)
    ok("소지품을 지우지 않는다", "no props" not in text)
    ok("고정 요소가 한글 그대로", "왼쪽 손목에만 감은 검정 헤어끈 두 겹" in text)
    ok("소지품이 한글 그대로", "낡은 캔버스 에코백" in text)
    ok("hex 가 그대로", "#22252A" in text)
    ok("스타일이 끝에", text.strip().endswith("Korean webtoon style"))

    spec["props"] = []
    text2 = S.build_prompt(spec, style="x")
    ok("소지품이 없으면 영역도 없다", "carried items" not in text2)
    ok("소지품이 없어도 색상 칩은 있다", "swatch chips" in text2)
    ok("소지품 없을 땐 REGION 5 도 없다", "REGION 5" not in text2)


# ------------------------------------------------------------------- 입력

def test_input() -> None:
    char = R.normalize({"name": "이하은", "description": "  ",
                        "fields": {"성격": "겁이 많다", "직업": ""},
                        "genre": "", "photos": []})
    check("빈 칸은 지운다", char["fields"], {"성격": "겁이 많다"})
    check("빈 설명은 빈 문자열", char["description"], "")
    ok("이름만 있고 설명이 있으면 통과", R.gate_input(char) == [])

    check("이름이 없으면 막는다",
          len(R.gate_input(R.normalize({"name": "", "fields": {"성격": "x"}}))), 1)
    check("이름만 있고 외관이 아무것도 없으면 막는다",
          len(R.gate_input(R.normalize({"name": "이하은"}))), 1)

    block = R.input_block(char)
    ok("장르가 없으면 그렇다고 말한다", "장르: (없음 — 네가 정한다)" in block)
    ok("사진이 없으면 그렇다고 말한다", "사진 없음" in block)
    ok("필드가 줄로 들어간다", "- 성격: 겁이 많다" in block)


# --------------------------------------------------------------- 페이지 묶기

def cuts(*sizes) -> list:
    """크기 목록 -> 컷 배열. 순서를 확인할 수 있게 번호를 붙인다."""
    return [{"n": i, "size": s} for i, s in enumerate(sizes, 1)]


def shape(pages) -> list:
    """페이지마다 컷 번호. 순서가 지켜졌는지 한눈에 보려고."""
    return [[c["n"] for c in page] for page in pages]


def test_pages() -> None:
    check("빈 입력", P.group_pages([]), [])
    check("None 도 빈 페이지", P.group_pages(None), [])

    check("가벼운 컷은 모인다",
          shape(P.group_pages(cuts("normal", "small", "tiny"))), [[1, 2, 3]])
    check("large 는 혼자",
          shape(P.group_pages(cuts("large"))), [[1]])
    check("full 도 혼자",
          shape(P.group_pages(cuts("full"))), [[1]])

    # 모으는 도중 large 를 만나면 거기서 끊는다
    check("도중에 large 를 만나면 끊는다",
          shape(P.group_pages(cuts("normal", "small", "large", "tiny", "normal"))),
          [[1, 2], [3], [4, 5]])
    check("large 가 연달아 오면 각자 한 장",
          shape(P.group_pages(cuts("large", "full", "large"))), [[1], [2], [3]])
    check("large 로 시작해도 빈 페이지가 안 생긴다",
          shape(P.group_pages(cuts("large", "normal"))), [[1], [2]])
    check("large 로 끝나도 빈 페이지가 안 생긴다",
          shape(P.group_pages(cuts("normal", "large"))), [[1], [2]])

    # 최대 개수
    # 개수 축만 보려면 높이 축을 끈다. 둘 다 켜져 있고 먼저 걸리는 쪽에서 끊는다
    check("개수 5개에서 넘어간다",
          shape(P.group_pages(cuts(*["normal"] * 7), max_ratio=None)),
          [[1, 2, 3, 4, 5], [6, 7]])
    check("정확히 5개면 한 장",
          shape(P.group_pages(cuts(*["normal"] * 5), max_ratio=None)),
          [[1, 2, 3, 4, 5]])
    check("max_per_page=2",
          shape(P.group_pages(cuts(*["small"] * 5), max_per_page=2, max_ratio=None)),
          [[1, 2], [3, 4], [5]])
    # tiny 만 있으면 높이(5)보다 개수(5)가 먼저 걸린다
    check("자잘한 컷은 개수가 먼저 막는다",
          shape(P.group_pages(cuts(*["tiny"] * 7))), [[1, 2, 3, 4, 5], [6, 7]])
    # normal 만 있으면 개수(3<5)보다 높이(9)가 먼저 걸린다
    check("보통 컷은 높이가 먼저 막는다",
          shape(P.group_pages(cuts(*["normal"] * 7))), [[1, 2, 3], [4, 5, 6], [7]])
    check("max_per_page=1 이면 전부 한 장씩",
          shape(P.group_pages(cuts("tiny", "small", "normal"), max_per_page=1)),
          [[1], [2], [3]])
    check("max_per_page 는 large 를 안 건드린다",
          shape(P.group_pages(cuts("normal", "large", "normal"), max_per_page=1)),
          [[1], [2], [3]])
    try:
        P.group_pages(cuts("normal"), max_per_page=0)
    except ValueError:
        pass
    else:
        FAILED.append("max_per_page=0 인데 안 막았다")

    # 순서는 어떤 경우에도 안 바뀐다 — 페이지를 이어 붙이면 원래 배열이다
    mixed = cuts("normal", "large", "tiny", "small", "full", "normal", "normal",
                 "normal", "normal", "small", "large")
    for limit in (1, 2, 3, 5, 99):
        flat = [c for page in P.group_pages(mixed, max_per_page=limit) for c in page]
        check(f"순서가 그대로 (max={limit})", flat, mixed)

    # 크기 읽기
    check("한글 키도 읽는다",
          shape(P.group_pages([{"n": 1, "크기": "large"}, {"n": 2, "크기": "normal"}])),
          [[1], [2]])
    check("대문자도 읽는다", P.cut_size({"size": "FULL"}), "full")
    check("앞뒤 공백도 읽는다", P.cut_size({"size": "  large  "}), "large")
    check("모르는 값은 normal", P.cut_size({"size": "거대"}), "normal")
    check("빈 값은 normal", P.cut_size({"size": ""}), "normal")
    check("크기 칸이 없으면 normal", P.cut_size({"n": 1}), "normal")
    check("dict 가 아니어도 안 죽는다", P.cut_size("large"), "normal")
    check("모르는 크기는 모이는 쪽으로",
          shape(P.group_pages([{"n": 1, "size": "거대"}, {"n": 2, "size": "normal"}])),
          [[1, 2]])

    # 원본을 건드리지 않는다
    original = cuts("normal", "large")
    P.group_pages(original)
    check("입력 배열이 그대로", original, cuts("normal", "large"))


def test_cut_weight() -> None:
    check("large 는 full", P.cut_weight({"size": "large"}), "full")
    check("full 은 full", P.cut_weight({"size": "full"}), "full")
    check("배경 없는 tiny 는 light",
          P.cut_weight({"size": "tiny", "background": {"type": "없음"}}), "light")
    check("배경 있는 tiny 는 normal",
          P.cut_weight({"size": "tiny", "background": {"type": "실제공간"}}), "normal")
    check("배경 없는 small 도 light",
          P.cut_weight({"size": "small", "background": {"type": "단색"}}), "light")
    check("normal 크기는 배경이 없어도 normal(무게)",
          P.cut_weight({"size": "normal", "background": {"type": "없음"}}), "normal")
    check("배경 칸이 없으면 normal", P.cut_weight({"size": "tiny"}), "normal")


def test_linked() -> None:
    a = {"size": "normal", "location": "복도", "time": "밤",
         "background": {"type": "실제공간"}}
    b = dict(a)
    ok("같은 장소·시간·실제공간이면 이어진다", P.linked(a, b))
    ok("장소가 다르면 안 이어진다", not P.linked(a, dict(b, location="다른 곳")))
    ok("시간대가 다르면 안 이어진다", not P.linked(a, dict(b, time="낮")))
    ok("배경 종류가 다르면 안 이어진다",
       not P.linked(a, dict(b, background={"type": "단색"})))
    ok("large 컷 자신은 안 이어진다", not P.linked(dict(a, size="large"), b))
    ok("large 컷으로도 안 이어진다", not P.linked(a, dict(b, size="full")))
    ok("앞 컷이 없으면 거짓", not P.linked(None, b))


def test_page_weight() -> None:
    light_cut = {"size": "tiny", "background": {"type": "없음"}}
    normal_cut = {"size": "small", "background": {"type": "실제공간"}}
    check("전부 light 면 페이지도 light", P.page_weight([light_cut, dict(light_cut)]), "light")
    check("하나라도 normal 이면 페이지도 normal",
          P.page_weight([light_cut, normal_cut]), "normal")
    check("large 혼자인 페이지는 normal(그대로 꽉 채운다)",
          P.page_weight([{"size": "large"}]), "normal")
    check("빈 페이지는 normal", P.page_weight([]), "normal")


def test_page_gap_after() -> None:
    a = {"size": "normal", "location": "복도", "time": "밤",
         "background": {"type": "실제공간"}}
    linked_next = [dict(a)]
    check("이어지면 0", P.page_gap_after([a], linked_next), 0)

    big = [dict(a, size="large")]
    check("직전이 large/full 이면 3", P.page_gap_after(big, [dict(a, location="옥상")]), 3)

    apart = [dict(a, location="옥상")]
    check("장소가 바뀌면 2", P.page_gap_after([a], apart), 2)

    same_place_diff_time = [dict(a, time="아침")]
    check("이어짐 조건은 아닌데 장소도 안 바뀌면 1",
          P.page_gap_after([a], same_place_diff_time), 1)

    check("앞뒤 페이지가 없으면 1", P.page_gap_after([], [a]), 1)
    check("앞뒤 페이지가 없으면 1 (뒤)", P.page_gap_after([a], []), 1)


def test_scene_head() -> None:
    board = R.parse_board(BOARD_JSON)
    flat = P.flatten_cuts(board["scenes"])
    check("컷 3개로 펴진다", len(flat), 3)
    check("어느 장면의 몇 컷인지 남는다",
          [(c["scene"], c["cut"]) for c in flat], [(1, 1), (1, 2), (2, 1)])
    check("장소가 컷까지 내려온다",
          [c["location"] for c in flat],
          ["마법학교 중앙 대강당의 입학식장"] * 2 + ["기숙사 복도"])
    check("시간대도", [c["time"] for c in flat], ["실내조명"] * 2 + ["밤"])
    check("크기는 콘티에서 온 그대로",
          [P.cut_size(c) for c in flat], ["large", "normal", "tiny"])
    # large 는 혼자, normal+tiny 가 한 장
    check("펴서 바로 묶인다",
          [[(c["scene"], c["cut"]) for c in page] for page in P.group_pages(flat)],
          [[(1, 1)], [(1, 2), (2, 1)]])
    check("장면이 없으면 빈 배열", P.flatten_cuts([]), [])

    # 컷이 스스로 적었으면 장면 값으로 안 덮는다
    own = P.flatten_cuts([{"id": 1, "location": "홀",
                           "cuts": [{"id": 1, "location": "복도"}]}])
    check("컷이 적은 장소가 이긴다", own[0]["location"], "복도")


# ------------------------------------------------- 이미지 생성 프롬프트

def test_image_prompt_pieces() -> None:
    check("카메라를 문장으로 편다",
          IP.camera_line({"shot": "상반신", "angle": "정면"}),
          "상반신, 정면 앵글")
    check("칸이 모자라도 있는 것까지",
          IP.camera_line({"shot": "극클로즈업"}), "극클로즈업")
    check("배경", IP.background_line({"type": "실제공간", "desc": "복도"}),
          "실제공간 — 복도")
    check("설명이 없으면 종류만", IP.background_line({"type": "없음"}), "없음")

    check("인물을 문장으로 편다 (facing 포함)",
          IP.person_line({"name": "하일", "style": "LD", "position": "왼쪽",
                          "facing": "옆모습",
                          "expression": "긴장한 표정", "action": "고개를 든다",
                          "moment": "직후", "framing": "무릎 위"}),
          "하일 (LD): 화면 왼쪽, 옆모습, 긴장한 표정, 고개를 든다. 동작의 직후를 "
          "그린다. 화면에는 무릎 위까지 나온다.")
    check("위치가 없으면 그 조각만 빠진다",
          IP.person_line({"name": "하일", "style": "LD", "expression": "웃는다",
                          "moment": "직전", "framing": "전신"}),
          "하일 (LD): 웃는다. 동작의 직전을 그린다. 화면에는 전신까지 나온다.")
    # 조사를 하나로 박으면 "직후을" 이 프롬프트로 나간다
    check("받침 없는 순간은 를", IP._eul("직후"), "를")
    check("받침 있는 순간은 을", IP._eul("직전"), "을")

    # framing 은 값 목록이 없는 자유 텍스트다 — "손만까지 나온다" 가 안 나와야 한다
    def frame(value: str) -> str:
        return IP.person_line({"name": "하일", "framing": value})

    ok("상반신까지", frame("상반신").endswith("화면에는 상반신까지 나온다."))
    ok("무릎 위까지", frame("무릎 위").endswith("화면에는 무릎 위까지 나온다."))
    ok("손만 나온다", frame("손만").endswith("화면에는 손만 나온다."))
    ok("일부 나온다", frame("손과 눈 일부").endswith("화면에는 손과 눈 일부 나온다."))

    # 대사 종류가 곧 말풍선 모양이다
    check("말",
          IP.bubble_line({"speaker": "하일", "type": "말", "text": "안녕",
                          "bubble": {"shape": "둥근 타원", "tail": "하일",
                                     "position": "왼쪽 위"}}),
          ["  - 둥근 타원 / 꼬리는 하일을 향함 / 위치 왼쪽 위", '    "안녕"'])
    ok("화면밖은 꼬리가 컷 바깥으로",
       "꼬리는 컷 바깥으로" in IP.bubble_line(
           {"speaker": "???", "type": "화면밖", "text": "들어와.",
            "bubble": {"shape": "둥근 타원", "tail": "컷 바깥"}})[0])
    ok("꼬리 없음도 그대로",
       "꼬리 없음" in IP.bubble_line(
           {"type": "화면밖", "text": "x", "bubble": {"tail": "없음"}})[0])
    ok("나레이션은 꼬리를 안 단다",
       "꼬리" not in IP.bubble_line(
           {"type": "나레이션", "text": "921년",
            "bubble": {"shape": "네모 상자"}})[0])
    ok("shape 가 비면 종류로 채운다",
       "구름" in IP.bubble_line({"speaker": "하일", "type": "생각", "text": "어?"})[0])
    check("글은 말풍선이 아니라 적힌 것을 그린다",
          IP.bubble_line({"type": "글", "text": "파일은 삭제해 주세요.",
                          "bubble": {"position": "노트북 화면 안"}})[0],
          "  - 말풍선 아님 — 노트북 화면 안에 적힌 글로 그린다")
    check("대사 글자는 한 글자도 안 바뀐다",
          IP.bubble_line({"speaker": "하일", "type": "말",
                          "text": "……그리고, 어둠을—"})[1],
          '    "……그리고, 어둠을—"')

    check("효과음은 글자와 위치만",
          IP.sfx_line({"text": "웅성…", "source": "학생들", "position": "오른쪽 아래",
                       "reason": "술렁임"}),
          '  - "웅성…" / 위치 오른쪽 아래')


def test_image_prompt_page() -> None:
    board = R.parse_board(BOARD_JSON)
    pages = P.group_pages(P.flatten_cuts(board["scenes"]))
    text = IP.build_page_prompt(pages[0], sheets=["하일 — 마른 체격의 소년."],
                                cast=board["cast"])

    ok("고정 블록이 앞에", text.startswith("세로로 읽는 웹툰 페이지를 그린다."))
    ok("주인공 시트", "하일 — 마른 체격의 소년." in text)
    ok("이 페이지에 나오는 조연만", "담당 교수 — 40대 초반" in text)
    ok("안 나오는 조연은 안 적는다", "관리인" not in text)
    ok("장소가 앞에 한 번", "## 장소\n마법학교 중앙 대강당의 입학식장" in text)
    ok("시간대도", "시간대: 실내조명" in text)
    ok("컷 1 은 높이 비율 5", "### 컷 1 (높이 비율 5)" in text)
    ok("카메라", "카메라: 광각, 정면 앵글" in text)
    ok("배경", "배경: 실제공간 — 높은 천장과 늘어선 마법등" in text)
    ok("인물 (facing 포함)", "하일 (LD): 화면 왼쪽, 앞모습, 긴장한 표정" in text)
    ok("좌우가 둘 다", "담당 교수 (LD): 화면 오른쪽" in text)
    ok("나레이션이 먼저 오지 않는다 (order 대로)",
       text.index('"하일."') < text.index('"입학식 사흘째."'))
    ok("효과음 절", "효과음 (말풍선 없이 글자만 그린다):" in text)
    ok("효과음 글자", '"웅성…" / 위치 오른쪽 아래' in text)

    # 그림에 안 그려지는 칸은 프롬프트에 없어야 한다
    ok("note 가 안 나간다", "시선이 하일에게 모이는" not in text)
    ok("sfx reason 이 안 나간다", "술렁임" not in text)
    ok("summary 가 안 나간다", "하일은 입학식에서" not in text)

    page2 = pages[1]
    text2 = IP.build_page_prompt(page2, cast=board["cast"])
    ok("장소가 갈리면 앞에 안 적는다", "## 장소" not in text2)
    ok("대신 컷마다", "장소: 마법학교 중앙 대강당의 입학식장" in text2
       and "장소: 기숙사 복도" in text2)
    ok("forbid", "그리지 않을 것: 교수의 얼굴" in text2)
    ok("글 대사", "말풍선 아님 — 노트북 화면 안에 적힌 글로 그린다" in text2)

    # 컷 번호는 페이지 안에서 1부터
    check("컷 번호가 안 겹친다", text2.count("### 컷 1 ("), 1)
    ok("1, 2 로 센다", "### 컷 1 (" in text2 and "### 컷 2 (" in text2)
    prompts = IP.page_prompts(pages, cast=board["cast"], continuous=True)
    check("페이지 수만큼", len(prompts), 2)
    ok("이어 세면 두 번째는 컷 2 부터", "### 컷 2 (" in prompts[1])

    full = IP.build_page_prompt([{"size": "full"}])
    ok("full 은 페이지 전체", "### 컷 1 (페이지 전체)" in full)
    ok("시트가 없으면 절도 없다", "## 캐릭터 시트" not in full)


def blank_cut(**over) -> dict:
    base = {"size": "normal", "camera": {}, "background": {},
            "characters": [], "dialogue": [], "sfx": []}
    base.update(over)
    return base


def test_directing_hints() -> None:
    """무게(light)·이어짐(linked) 힌트가 이미지 프롬프트에 붙는지."""
    light_page = [blank_cut(size="tiny", background={"type": "없음"})]
    ok("가벼운 컷엔 폭 힌트가 붙는다",
       "폭을 좁게" in IP.build_page_prompt(light_page))

    normal_page = [blank_cut(background={"type": "실제공간", "desc": "복도"})]
    ok("보통 컷엔 무게 힌트가 없다",
       "폭을 좁게" not in IP.build_page_prompt(normal_page))

    linked_page = [
        blank_cut(location="복도", time="밤",
                  background={"type": "실제공간", "desc": "입구"}),
        blank_cut(location="복도", time="밤",
                  background={"type": "실제공간", "desc": "안쪽"}),
    ]
    text = IP.build_page_prompt(linked_page)
    first, second = text.split("### 컷 2")
    ok("첫 컷엔 이어짐 힌트가 없다", "그대로 이어진다" not in first)
    ok("둘째 컷엔 이어짐 힌트가 있다", "그대로 이어진다" in second)

    apart_page = [
        blank_cut(location="복도", time="밤",
                  background={"type": "실제공간", "desc": "입구"}),
        blank_cut(location="옥상", time="밤",
                  background={"type": "실제공간", "desc": "난간"}),
    ]
    ok("장소가 바뀌면 이어짐 힌트가 없다",
       "그대로 이어진다" not in IP.build_page_prompt(apart_page))


def test_sheet_line() -> None:
    spec = S.parse_spec(GOOD_SPEC)
    line = IP.sheet_line(spec)
    ok("이름으로 시작", line.startswith("이하은 — "))
    ok("외형", "shoulder-length black hair" in line)
    ok("고정 요소", "왼쪽 손목에만 감은 검정 헤어끈 두 겹" in line)
    ok("소지품", "낡은 캔버스 에코백" in line)
    spec["props"] = []
    ok("소지품이 없으면 그 줄도 없다", "소지품:" not in IP.sheet_line(spec))


def test_ratio_break() -> None:
    check("기본은 9 — normal 셋에서 끊는다",
          shape(P.group_pages(cuts(*["normal"] * 5))), [[1, 2, 3], [4, 5]])
    check("None 이면 높이로 안 끊는다",
          shape(P.group_pages(cuts(*["normal"] * 5), max_ratio=None)),
          [[1, 2, 3, 4, 5]])
    check("max_ratio=9 면 normal 3개",
          shape(P.group_pages(cuts(*["normal"] * 7), max_ratio=9)),
          [[1, 2, 3], [4, 5, 6], [7]])
    check("얹기 전에 본다 — 상한을 넘긴 페이지가 안 나간다",
          shape(P.group_pages(cuts("tiny", "small", "normal", "normal"), max_ratio=8)),
          [[1, 2, 3], [4]])
    check("개수와 비율 중 먼저 걸리는 쪽",
          shape(P.group_pages(cuts(*["tiny"] * 6), max_per_page=4, max_ratio=99)),
          [[1, 2, 3, 4], [5, 6]])
    check("large 는 비율과 무관하게 혼자",
          shape(P.group_pages(cuts("normal", "large", "normal"), max_ratio=99)),
          [[1], [2], [3]])
    try:
        P.group_pages(cuts("normal"), max_ratio=0)
    except ValueError:
        pass
    else:
        FAILED.append("max_ratio=0 인데 안 막았다")


# ------------------------------------------------------------- 페이지 그리기

def test_pageart() -> None:
    import shutil
    import tempfile

    import imagegen
    import pageart

    # 페이지는 세로로 길어야 한다. 시트 칸은 안 건드렸는지 같이 본다
    check("페이지 칸이 생겼다", imagegen.story.CHARSHEET_SIZES["page"], "1024x1536")
    check("페이지 비율", imagegen.story.CHARSHEET_RATIOS["page"], "9:16")
    check("시트 칸은 그대로", imagegen.story.CHARSHEET_SIZES["sheet"], "1536x1024")

    root = Path(tempfile.mkdtemp(prefix="nh-pageart-"))
    try:
        run_dir = root / "run"
        run_dir.mkdir()
        board = R.parse_board(BOARD_JSON)
        R.write_json(run_dir / "board.json", board)
        R.write_json(run_dir / "pages.json",
                     P.group_pages(P.flatten_cuts(board["scenes"])))
        R.write_json(run_dir / "sheet_spec.json", S.parse_spec(GOOD_SPEC))

        pgs, prompts = pageart.build_prompts(run_dir)
        check("페이지 2장", len(pgs), 2)
        check("프롬프트도 2장", len(prompts), 2)
        ok("시트 사양이 프롬프트에", "이하은 — A young Korean woman" in prompts[0])
        ok("조연도", "담당 교수 — 40대 초반" in prompts[0])

        # 시트가 없으면 참조도 없다
        check("시트가 없으면 빈 목록", pageart.sheet_refs(run_dir), [])
        (run_dir / "sheet.png").write_bytes(b"x")
        check("시트가 있으면 그것 하나",
              [p.name for p in pageart.sheet_refs(run_dir)], ["sheet.png"])

        # --dry-run 은 프롬프트만 쓰고 그림은 안 만든다
        quiet, pageart.log = pageart.log, lambda *_: None
        try:
            made = pageart.draw(run_dir, dry_run=True)
        finally:
            pageart.log = quiet
        check("dry-run 은 아무것도 안 그린다", made, [])
        ok("프롬프트는 남는다", (run_dir / "pages" / "page01.txt").exists())
        ok("그림은 없다", not (run_dir / "pages" / "page01.png").exists())

        # 참조 사슬 — 첫 장은 시트만, 그다음부터 직전 페이지가 붙는다
        pageart.page_path(run_dir, 1).parent.mkdir(exist_ok=True)
        check("1페이지 자리", pageart.page_path(run_dir, 1).name, "page01.png")
        check("2페이지 자리", pageart.page_path(run_dir, 2).name, "page02.png")

        # pages.json 이 없으면 콘티부터 하라고 멈춘다
        (run_dir / "pages.json").unlink()
        try:
            pageart.build_prompts(run_dir)
        except SystemExit:
            pass
        else:
            FAILED.append("pages.json 이 없는데 안 멈췄다")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_stitch_rhythm() -> None:
    """페이지 사이 여백·폭 — pages.json 이 있을 때/없을 때."""
    import shutil
    import tempfile

    from PIL import Image

    root = Path(tempfile.mkdtemp(prefix="nh-stitch-"))
    try:
        run_dir = root / "run"
        (run_dir / "pages").mkdir(parents=True)
        # 페이지 셋: 1(보통) -> 2(장소가 바뀜, 여백 2단계) -> 3(light, 좁게)
        sizes = [(100, 200), (100, 150), (100, 80)]
        for i, (w, h) in enumerate(sizes, 1):
            Image.new("RGB", (w, h), "black").save(run_dir / "pages" / f"page{i:02d}.png")

        pages_data = [
            [{"size": "normal", "location": "복도", "time": "밤",
              "background": {"type": "실제공간"}}],
            [{"size": "normal", "location": "옥상", "time": "밤",
              "background": {"type": "실제공간"}}],
            [{"size": "tiny", "location": "옥상", "time": "밤",
              "background": {"type": "없음"}}],
        ]
        (run_dir / "pages.json").write_text(json.dumps(pages_data), encoding="utf-8")

        gaps, ratios = ST.page_rhythm(pages_data, 3)
        check("첫 페이지 앞엔 여백 없음", gaps[0], 0)
        check("2번째는 장소가 바뀌어 2단계", gaps[1], 2)
        # 3번째는 2번째와 장소·시간대는 같지만 배경이 없다시피 한(light) 컷이라
        # linked() 조건(둘 다 실제공간)을 안 넘는다 — 기본값 1단계로 떨어진다.
        check("3번째는 이어짐 조건은 아니라 기본 1단계", gaps[2], 1)
        check("1·2번은 꽉 채움", ratios[0:2], [1.0, 1.0])
        ok("3번은 light 라 좁다", ratios[2] < 1.0)

        out = ST.stitch(run_dir)
        with Image.open(out) as im:
            w, h = im.size
        gtab = ST.strip.gap_ratio_table()
        gap1 = ST.strip.gap_px(100, gaps[1], gtab)
        gap2 = ST.strip.gap_px(100, gaps[2], gtab)
        expect_h = 200 + gap1 + 150 + gap2 + 80 * ratios[2]
        check("세로 길이가 여백만큼 늘어난다", h, round(expect_h))
        check("폭은 그대로(가장 넓은 페이지 기준)", w, 100)

        # pages.json 없이도(옛 run) 예전처럼 여백 없이 이어 붙는다
        (run_dir / "pages.json").unlink()
        out2 = ST.stitch(run_dir, out_path=root / "run" / "no_rhythm.png")
        with Image.open(out2) as im2:
            _, h2 = im2.size
        check("pages.json 이 없으면 여백 없이 그대로 합친 높이",
              h2, sum(h for _, h in sizes))
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_import_sheet() -> None:
    """이미 뽑아 둔 시트 가져오기 — 시트가 제일 비싼 호출이라 재사용이 중요하다."""
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(prefix="nh-import-"))
    try:
        # story-harness 모양의 원본을 만든다
        src = root / "src"
        (src / "charsheet").mkdir(parents=True)
        (src / "charsheet" / "sheet_c2.png").write_bytes(b"PNG-2")
        (src / "charsheet" / "sheet_c1.png").write_bytes(b"PNG-1")
        (src / "charsheet" / "charsheet_picks.json").write_text(
            json.dumps({"picks": {"sheet": "sheet_c2.png"}}), encoding="utf-8")
        spec = S.parse_spec(GOOD_SPEC)
        (src / "p1.json").write_text(json.dumps({
            "name": spec["name"],
            "appearance_en": spec["appearance_en"],
            "design_details": spec["design_details"],
            "color_palette": spec["color_palette"],
            "expression_set": spec["expression_set"],
        }, ensure_ascii=False), encoding="utf-8")

        run_dir = root / "run"
        got = S.import_sheet(run_dir, src)
        check("사람이 채택한 후보를 따라간다", Path(got["from"]).name, "sheet_c2.png")
        check("그림이 복사됐다", (run_dir / "sheet.png").read_bytes(), b"PNG-2")
        ok("사양도 가져왔다", got["spec"])
        check("이름", got["name"], "이하은")

        out = json.loads((run_dir / "sheet_spec.json").read_text(encoding="utf-8"))
        check("고정 요소가 그대로", out["design_details"], spec["design_details"])
        check("표정도", len(out["expression_set"]), 6)
        # props 는 우리 쪽에 새로 생긴 칸이라 p1 에 없다 — 지어내지 않는다
        check("소지품은 빈 채로", out["props"], [])

        # 채택 기록이 없으면 c1
        (src / "charsheet" / "charsheet_picks.json").unlink()
        check("기록이 없으면 c1",
              Path(S.import_sheet(root / "run2", src)["from"]).name, "sheet_c1.png")

        # png 하나만 줘도 된다 (사양 없이 그림만)
        only = S.import_sheet(root / "run3", src / "charsheet" / "sheet_c1.png")
        ok("사양 없이 그림만", not only["spec"])
        ok("그림은 왔다", (root / "run3" / "sheet.png").exists())

        # new_harness run 폴더를 주면 우리 형식을 그대로 읽는다
        again = S.import_sheet(root / "run4", run_dir)
        ok("우리 형식도 읽는다", again["spec"])
        check("우리 쪽 sheet.png 를 집는다", Path(again["from"]).name, "sheet.png")

        # 시트가 없으면 어디를 봐야 하는지 말하고 멈춘다
        try:
            S.import_sheet(root / "run5", root / "없는폴더")
        except SystemExit:
            pass
        else:
            FAILED.append("없는 경로인데 안 멈췄다")
    finally:
        shutil.rmtree(root, ignore_errors=True)


def scene_cuts(shots, angles=None, location="홀", time="낮", camera_plan="") -> dict:
    """shot 값 목록 -> 장면 하나 (컷마다 shot·angle 만 갈아 끼운다)."""
    angles = angles or ["정면"] * len(shots)
    cuts = []
    for i, (sh, an) in enumerate(zip(shots, angles), 1):
        cuts.append({
            "id": i, "size": "normal",
            "camera": {"shot": sh, "angle": an},
            "background": {"type": "실제공간", "desc": "x"},
            "characters": [{"name": "하일", "moment": "도중"}],
            "dialogue": [{"order": 1, "type": "말", "text": "대사"}] if i % 2 == 0 else [],
            "sfx": [], "forbid": [], "note": "",
        })
    return {"id": 1, "location": location, "time": time,
            "camera_plan": camera_plan, "cuts": cuts}


def dboard(shots, angles=None, camera_plan="") -> dict:
    return R.parse_board(json.dumps(
        {"cast": [], "scenes": [scene_cuts(shots, angles, camera_plan=camera_plan)]},
        ensure_ascii=False))


def test_directing_warnings() -> None:
    """연출 경고 — 그림은 나오지만 사람이 보고 판단할 것들."""
    # 같은 shot 이 4컷 연속되면 잡는다
    consec = dboard(["클로즈업"] * 4 + ["상반신"] * 2)
    ok("연속 shot 을 잡는다", any("연속" in w for w in R.directing_warnings(consec)))
    ok("gate_board 는 연출(연속)을 안 본다 — 그건 directing_warnings 몫",
       not any("연속" in w for w in R.gate_board(consec)))

    # 컷이 적으면(3개) 4연속이 안 생기니 안 잡는다, 비율 눈금도 안 본다
    few = dboard(["클로즈업"] * 3)
    ok("컷이 적으면 연속도 비율도 안 본다",
       not any("연속" in w or "계열" in w or "정면 앵글" in w
               for w in R.directing_warnings(few)))

    # 클로즈업 계열이 절반을 넘으면 잡는다 (연속은 안 되게 섞는다)
    closeup_heavy = dboard(
        ["클로즈업", "상반신", "극클로즈업", "상반신", "클로즈업", "극클로즈업"])
    warns = R.directing_warnings(closeup_heavy)
    ok("클로즈업 비율을 잡는다", any("클로즈업 계열" in w for w in warns))
    ok("섞여 있으면 연속은 안 잡는다", not any("연속" in w for w in warns))

    # 정면 앵글이 80% 를 넘으면 잡는다
    front_heavy = dboard(
        ["상반신", "무릎", "클로즈업", "전신", "상반신", "무릎"],
        angles=["정면"] * 5 + ["하이앵글"])
    ok("정면 앵글 비율을 잡는다",
       any("정면 앵글" in w for w in R.directing_warnings(front_heavy)))

    # camera_plan 이 실제 shot 과 다르면 잡는다. 안 쓴 장면은 조용하다.
    match = dboard(["광각", "상반신"], camera_plan="광각, 상반신")
    ok("계획과 실제가 같으면 안 잡는다",
       not any("카메라 계획" in w for w in R.directing_warnings(match)))
    mismatch = dboard(["광각", "상반신"], camera_plan="광각, 클로즈업")
    ok("계획과 실제가 다르면 잡는다",
       any("카메라 계획" in w for w in R.directing_warnings(mismatch)))
    nofield = dboard(["광각", "상반신"])
    ok("camera_plan 을 안 쓰면 그냥 넘어간다",
       not any("카메라 계획" in w for w in R.directing_warnings(nofield)))


def test_gate_readable() -> None:
    """읽히는가 — 형식은 맞는데 무슨 내용인지 모르는 콘티를 잡는다."""
    def board(scenes) -> dict:
        return {"cast": [], "scenes": [
            {"id": i, "summary": "", "location": "홀", "time": "낮",
             "cuts": [dict({"id": j, "size": "normal", "camera": {}, "background": {},
                            "characters": [], "sfx": [], "forbid": [], "note": ""}, **c)
                      for j, c in enumerate(cuts, 1)]}
            for i, cuts in enumerate(scenes, 1)]}

    def say(kind: str, text: str = "말") -> dict:
        return {"order": 1, "type": kind, "text": text}

    # 컷마다 말·나레이션이 섞여 있고 장면이 여러 컷이면 조용하다
    healthy = board([
        [{"dialogue": [say("나레이션", "카페, 오후 3시")]}, {"dialogue": [say("말")]}],
        [{"dialogue": [say("생각")]}, {"dialogue": [say("말")]}],
    ])
    check("멀쩡하면 조용하다", R.gate_readable(healthy), [])

    quiet = board([[{"dialogue": []}, {"dialogue": []}],
                   [{"dialogue": []}, {"dialogue": []}]])
    ok("대사가 없으면 잡는다", any("대사가" in x for x in R.gate_readable(quiet)))

    # 전부 "생각" 인 것 자체는 문제가 아니다 — 혼잣말만으로 잘 읽히는 화가 있다.
    long = "여기 들어올 수 있는 건 나뿐이어야 하는데, 명부엔 다섯 명이 적혀 있어."
    thinky = board([[{"dialogue": [say("생각", long)]}, {"dialogue": [say("생각", long)]}],
                    [{"dialogue": [say("생각", long)]}, {"dialogue": [say("생각", long)]}]])
    ok("전부 생각이어도 안 잡는다",
       not any("한 종류" in x for x in R.gate_readable(thinky)))

    # 첫 장면이 짧은 반응으로 시작하면 잡는다 — 독자가 여기가 어딘지 모른다
    blunt = board([[{"dialogue": [say("생각", "뭐지…?")]},
                    {"dialogue": [say("생각", long)]}],
                   [{"dialogue": [say("생각", long)]}, {"dialogue": [say("생각", long)]}]])
    ok("첫 대사가 짧고 나레이션이 없으면 잡는다",
       any("첫 장면" in x for x in R.gate_readable(blunt)))
    ok("첫 장면에 나레이션이 있으면 안 잡는다",
       not any("첫 장면" in x for x in R.gate_readable(board([
           [{"dialogue": [say("나레이션", "카페, 오후 3시")]},
            {"dialogue": [say("생각", "뭐지…?")]}],
           [{"dialogue": [say("생각", long)]}, {"dialogue": [say("생각", long)]}]]))))

    solo = board([[{"dialogue": [say("말")]}],
                  [{"dialogue": [say("나레이션")]}],
                  [{"dialogue": [say("생각")]}]])
    ok("1컷 장면이 많으면 잡는다", any("1컷" in x for x in R.gate_readable(solo)))
    ok("장면이 여러 컷이면 그건 안 잡는다",
       not any("1컷" in x for x in R.gate_readable(healthy)))

    check("컷이 없으면 아무 말 안 한다", R.gate_readable({"scenes": []}), [])


def copy_scenes(scenes) -> list:
    import copy
    return copy.deepcopy(scenes)


def test_detail() -> None:
    """구체화 — 아는 것과 추측을 가르고, 근거가 붙어 있는지 본다."""
    def learn(what: str, how: str = "화면에서 읽었다") -> dict:
        return {"what": what, "how": how}

    def detail(scenes) -> dict:
        return R.parse_detail(json.dumps({"scenes": scenes, "hidden": ["정체"]},
                                         ensure_ascii=False))

    good = [
        {"id": 1, "source": "기록을 대조한다",
         "detail": "명부에는 여섯 명이 적혀 있는데 열화상 화면에는 일곱 번째 실루엣이 "
                   "찍혀 있다. 하은은 두 기록의 시각이 같은 구간을 가리키는지 다시 "
                   "확인한다. 같은 시각이다. 하은은 통제선을 넘어 안으로 들어간다.",
         "learns": [learn("명부에 없는 사람이 먼저 들어왔다",
                          "명부 6명과 열화상 7명을 나란히 놓고 셌다")],
         "guesses": [{"what": "장비 오류일 수도 있다",
                      "from": "신호가 15초만 잡혔다 사라졌다"}],
         "leads_to": "직접 확인하러 안으로 들어간다"},
        {"id": 2, "source": "흔적을 발견한다",
         "detail": "바닥에 떨어진 뱃지를 줍는다. 뱃지 앞면에 찍힌 등급 표시가 명부에 "
                   "적힌 어느 등급과도 맞지 않는다. 하은은 뱃지를 주머니에 넣고 "
                   "흔적이 이어진 통로 안쪽으로 걸음을 옮긴다.",
         "learns": [learn("명부에 없는 등급의 사람이 있다", "뱃지에 등급이 적혀 있었다")],
         "guesses": [],
         "leads_to": "뱃지를 흘린 사람을 찾아 통로로 들어간다"},
    ]
    d = detail(good)
    check("장면 2개", len(d["scenes"]), 2)
    check("learns 는 what/how", d["scenes"][0]["learns"][0]["how"],
          "명부 6명과 열화상 7명을 나란히 놓고 셌다")
    check("guesses 는 what/from", d["scenes"][0]["guesses"][0]["from"],
          "신호가 15초만 잡혔다 사라졌다")

    # 근거 없는 짐작 — 근거를 못 대면 지어내지 말고 빼야 한다
    loose = copy_scenes(good)
    loose[0]["guesses"] = [{"what": "누군가 나를 추적하고 있다"}]
    ok("근거 없는 추측을 잡는다",
       any("무엇을 보고 짐작했는지" in x
           for x in R.gate_detail(detail(loose), {"scenes": ["a", "b"]})))
    check("멀쩡하면 조용하다",
          R.gate_detail(d, {"scenes": ["a", "b"]}), [])

    # how 가 없으면 근거 없는 앎이다 — "자국을 보고 신발 패턴을 안다" 가 이것
    noref = copy_scenes(good)
    noref[0]["learns"] = [{"what": "이 발자국은 명부에 없는 사람 것이다"}]
    ok("근거가 없으면 잡는다",
       any("어떻게 알았는지" in x for x in R.gate_detail(detail(noref),
                                                         {"scenes": ["a", "b"]})))
    # 문자열로만 와도 근거 없음으로 본다
    plain = copy_scenes(good)
    plain[0]["learns"] = ["그냥 안다"]
    ok("문자열 learns 도 근거 없음",
       any("어떻게 알았는지" in x for x in R.gate_detail(detail(plain),
                                                         {"scenes": ["a", "b"]})))

    # 마지막이 감정으로 끝나면 다음 화를 안 부른다
    feel = copy_scenes(good)
    feel[-1]["leads_to"] = "하은은 더욱 깊은 경계와 긴장 상태로 상황을 관망하게 된다"
    ok("감정으로 끝나면 잡는다",
       any("감정으로" in x for x in R.gate_detail(detail(feel), {"scenes": ["a", "b"]})))

    # 장면이 빠지면
    ok("빠진 장면을 잡는다",
       any("빠진 장면" in x for x in R.gate_detail(d, {"scenes": ["a", "b", "c"]})))

    # 구체화가 안 된 것
    thin = copy_scenes(good)
    thin[0]["detail"] = "기록을 대조한다."   # 짧으면 옮겨 적은 것이다
    ok("옮겨 적기만 하면 잡는다",
       any("구체화가 안" in x for x in R.gate_detail(detail(thin), {"scenes": ["a", "b"]})))


# --------------------------------------------------------------- 사건 나누기

def _con(prev: str = "앞이 끝난 자리", trans: str = "그 사이에 자리를 옮긴다") -> dict:
    return {"previous_ending": prev, "transition": trans,
            "opening_state": "시작 상태", "ending_state": "끝 상태",
            "persistent_elements": ["옷"], "visual_anchors": ["창"]}


def _event(n: int, body: str, **over) -> dict:
    one = {"id": n, "source": f"사건 {n}", "detail": body,
           "learns": [{"what": f"{n}번에서 알게 되는 것", "how": "직접 봤다"}],
           "guesses": [], "leads_to": f"{n}번 다음에 벌어지는 일",
           "continuity": _con("", "") if n == 1 else _con()}
    one.update(over)
    return one


BODY_A = ("문 앞에 선 채로 손잡이를 잡았다가 놓는다. 안에서 나는 소리가 멎기를 "
          "기다렸다가 다시 잡는다. 세 번째에 문을 밀고 들어가, 등 뒤로 문이 "
          "닫히는 소리를 끝까지 듣고 나서야 손을 뗀다.")
BODY_B = ("책상 위에 놓인 것을 하나씩 제자리로 돌려놓다가, 어제와 같은 자리에 "
          "같은 방향으로 놓인 것을 보고 손을 멈춘다. 일부러 반대로 돌려놓고, "
          "한 걸음 물러서서 그 자리를 다시 본다.")


def test_detail_events() -> None:
    """장면은 사건으로 나뉘고, **사건 하나가 그림 한 장**이 된다."""
    raw = {"scenes": [
        {"id": 1, "source": "안으로 들어간다", "function": "이야기를 연다",
         "events": [_event(1, BODY_A), _event(2, BODY_B)]},
        {"id": 2, "source": "다시 확인한다", "function": "의심을 굳힌다",
         "events": [_event(3, BODY_A)]},
    ], "cast": [{"name": "관리인", "appearance": "50대, 회색 작업복"}],
        "hidden": ["정체"]}
    d = R.parse_detail(json.dumps(raw, ensure_ascii=False))

    check("장면 2개", len(d["scenes"]), 2)
    check("1장면에 사건 2개", len(d["scenes"][0]["events"]), 2)
    check("사건에 detail 이 있다", d["scenes"][0]["events"][1]["detail"], BODY_B)
    check("사건에 이어짐이 있다",
          d["scenes"][0]["events"][1]["continuity"]["transition"],
          "그 사이에 자리를 옮긴다")
    check("장면 칸은 id·source·function 만 찬다", d["scenes"][0]["detail"], "")
    check("cast 는 그대로", d["cast"][0]["name"], "관리인")

    # 편면 = 그림 순서. 장면 경계를 넘어 이어진다
    units = P.flatten_events(d["scenes"])
    check("사건 3개", len(units), 3)
    check("장면 경계를 넘어 잇는다", [(u["scene"], u["event"]) for u in units],
          [(1, 1), (1, 2), (2, 3)])

    # 옛 run — 사건 칸이 없으면 장면 자체가 사건 하나다
    old = R.parse_detail(json.dumps({"scenes": [
        {"id": 1, "source": "s", "detail": BODY_A, "leads_to": "다음",
         "learns": [{"what": "a", "how": "b"}]}]}, ensure_ascii=False))
    check("옛 응답은 events 가 빈다", old["scenes"][0]["events"], [])
    folded = P.detail_events(old["scenes"][0])
    check("장면 하나가 사건 하나로 접힌다", len(folded), 1)
    check("접은 사건이 장면 본문을 갖는다", folded[0]["detail"], BODY_A)

    # 게이트 — 사건 단위로 본다
    check("멀쩡하면 조용하다", R.gate_detail(d, {"scenes": ["a", "b"]}), [])

    hole = json.loads(json.dumps(raw))
    hole["scenes"][0]["events"][1]["detail"] = ""
    bad = R.gate_detail(R.parse_detail(json.dumps(hole, ensure_ascii=False)),
                        {"scenes": ["a", "b"]})
    ok("어느 사건이 비었는지 짚어 준다",
       any("장면 1 사건 2: detail 이 비어" in x for x in bad))

    # 길이는 장면 단위로 본다 — 사건마다 요구하면 잘게 나눌수록 걸린다
    split_thin = json.loads(json.dumps(raw))
    for e in split_thin["scenes"][0]["events"]:
        e["detail"] = "짧게 적는다."
    bad = R.gate_detail(R.parse_detail(json.dumps(split_thin, ensure_ascii=False)),
                        {"scenes": ["a", "b"]})
    ok("장면 전체가 짧으면 잡는다",
       any(x.startswith("장면 1: detail 이") and "구체화가 안" in x for x in bad))
    ok("사건 하나씩은 안 잰다",
       not any("사건 1: detail 이 " in x for x in bad))

    # 사건 사이가 비면 그림이 순간이동한다
    jump = json.loads(json.dumps(raw))
    jump["scenes"][1]["events"][0]["continuity"]["transition"] = ""
    bad = R.gate_detail(R.parse_detail(json.dumps(jump, ensure_ascii=False)),
                        {"scenes": ["a", "b"]})
    ok("사이가 비면 잡는다",
       any("장면 2 사건 3" in x and "transition" in x for x in bad))

    # 첫 사건은 이어받을 앞이 없다 — 비어 있어도 안 잡는다
    ok("첫 사건은 비어도 된다",
       not any("사건 1: 앞 사건" in x for x in R.gate_detail(d, {"scenes": ["a"]})))

    # 옛 run 에는 이 칸 자체가 없다. 다시 돌려도 안 걸려야 한다
    ok("옛 run 은 이어짐으로 안 걸린다",
       not any("transition" in x for x in R.gate_detail(old, {"scenes": ["a"]})))

    # 프롬프트에 실을 줄 — 사건마다 소제목이 붙는다
    lines = "\n".join(R._scene_lines(d))
    ok("사건 소제목", "#### 사건 2 — 사건 2" in lines)
    ok("사건 본문", BODY_B in lines)
    old_lines = "\n".join(R._scene_lines(old))
    ok("옛 run 은 소제목이 없다", "#### 사건" not in old_lines)


def test_detail_pages() -> None:
    """디테일 직행 — 표지 한 장 + **사건마다 한 장.**"""
    import shutil
    import tempfile

    import detailart

    raw = {"scenes": [
        {"id": 1, "source": "안으로 들어간다", "function": "연다",
         "events": [_event(1, BODY_A), _event(2, BODY_B)]},
        {"id": 2, "source": "다시 확인한다", "function": "굳힌다",
         "events": [_event(3, BODY_A)]},
    ], "cast": [{"name": "관리인", "appearance": "50대, 회색 작업복"}],
        "hidden": []}

    root = Path(tempfile.mkdtemp(prefix="nh-detailart-"))
    try:
        run_dir = root / "run"
        run_dir.mkdir()
        R.write_json(run_dir / "detail.json",
                     R.parse_detail(json.dumps(raw, ensure_ascii=False)))
        R.write_json(run_dir / "input.json", {"name": "이하은"})
        R.write_json(run_dir / "pick.json", {"n": 1, "title": "제목", "genre": "판타지"})

        quiet, detailart.log = detailart.log, lambda *_: None
        try:
            made = detailart.draw(run_dir, dry_run=True)
        finally:
            detailart.log = quiet
        check("dry-run 은 아무것도 안 그린다", made, [])

        texts = sorted(p.name for p in (run_dir / "pages").glob("*.txt"))
        check("표지 1 + 사건 3 = 4장", texts,
              ["page01.txt", "page02.txt", "page03.txt", "page04.txt"])
        ok("표지는 표지라고 말한다",
           "이 그림은 표지다" in (run_dir / "pages" / "page01.txt").read_text(encoding="utf-8"))
        two = (run_dir / "pages" / "page03.txt").read_text(encoding="utf-8")
        ok("2페이지 뒤는 사건 본문", BODY_B in two)
        ok("앞 사건과 이어 붙인다", "그 사이에 자리를 옮긴다" in two)
        ok("조연 외모가 매 장에 붙는다", "관리인 — 50대, 회색 작업복" in two)

        # 옛 run — 장면 하나가 한 장이다(사건 칸이 없다)
        old_dir = root / "old"
        old_dir.mkdir()
        R.write_json(old_dir / "detail.json", R.parse_detail(json.dumps(
            {"scenes": [{"id": 1, "source": "s", "detail": BODY_A,
                         "leads_to": "다음"},
                        {"id": 2, "source": "t", "detail": BODY_B,
                         "leads_to": "다음"}]}, ensure_ascii=False)))
        R.write_json(old_dir / "input.json", {"name": "이하은"})
        R.write_json(old_dir / "pick.json", {"n": 1, "title": "제목", "genre": ""})
        quiet, detailart.log = detailart.log, lambda *_: None
        try:
            detailart.draw(old_dir, dry_run=True)
        finally:
            detailart.log = quiet
        check("옛 run 은 표지 1 + 장면 2 = 3장",
              sorted(p.name for p in (old_dir / "pages").glob("*.txt")),
              ["page01.txt", "page02.txt", "page03.txt"])
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_review_and_fix() -> None:
    """검수는 잡기만 하고, 보강은 지적받은 장면만 고친다."""
    r = R.parse_review(json.dumps({"verdict": "PASS", "issues": [
        {"scene": 3, "kind": "인과", "severity": "major",
         "what": "통신을 왜 했는지 없음", "where": "신호 없음 표시가 뜬다"},
        {"scene": 5, "kind": "신규", "severity": "critical",
         "what": "없던 과거를 만듦", "where": "이전에 겪었던 것과 비슷하다"},
        {"scene": 1, "kind": "추측", "severity": "minor", "what": "약함", "where": ""},
    ]}, ensure_ascii=False))
    # critical 이 있으면 모델이 PASS 라고 해도 FAIL 이다 — 세어서 다시 정한다
    check("verdict 를 다시 센다", r["verdict"], "FAIL")
    check("무거운 것부터", [i["severity"] for i in r["issues"]],
          ["critical", "major", "minor"])
    check("개수", R.review_counts(r), {"critical": 1, "major": 1, "minor": 1})

    clean = R.parse_review('{"verdict": "FAIL", "issues": []}')
    check("지적이 없으면 PASS", clean["verdict"], "PASS")
    # 모르는 severity 는 major 로 본다 — 조용히 흘려보내지 않는다
    odd = R.parse_review('{"issues": [{"scene": 1, "severity": "심각", "what": "x"}]}')
    check("모르는 무게는 major", odd["issues"][0]["severity"], "major")

    # 보강 — 안 나온 장면은 글자 하나 안 바뀐다
    detail = {"scenes": [{"id": i, "source": f"s{i}", "function": "",
                          "learns": [], "guesses": [],
                          "detail": f"원래 {i}", "leads_to": f"다음 {i}"}
                         for i in (1, 2, 3)],
              "hidden": ["정체"]}
    patch = {"scenes": [dict(detail["scenes"][1], detail="고친 2")]}
    merged, changed = R.apply_fix(detail, patch)
    check("고친 장면만", changed, [2])
    check("2번은 바뀜", merged["scenes"][1]["detail"], "고친 2")
    check("1번은 그대로", merged["scenes"][0], detail["scenes"][0])
    check("3번도 그대로", merged["scenes"][2], detail["scenes"][2])
    check("hidden 은 유지", merged["hidden"], ["정체"])
    check("장면 수가 안 늘어난다", len(merged["scenes"]), 3)

    # 없는 id 를 보내도 장면이 안 생긴다
    ghost, ch = R.apply_fix(detail, {"scenes": [dict(detail["scenes"][0], id=9)]})
    check("모르는 id 는 버린다", len(ghost["scenes"]), 3)
    check("바뀐 것 없음", ch, [])

    # 같은 내용을 보내면 바뀐 것으로 안 센다
    same, ch2 = R.apply_fix(detail, {"scenes": [dict(detail["scenes"][0])]})
    check("같으면 안 센다", ch2, [])

    check("빈 패치", R.apply_fix(detail, {"scenes": []})[1], [])


def main() -> int:
    for fn in (test_directions, test_detail, test_detail_events,
               test_detail_pages, test_review_and_fix,
               test_board, test_gate_board, test_directing_warnings,
               test_gate_readable, test_spec,
               test_sheet_prompt, test_input, test_pages, test_cut_weight,
               test_linked, test_page_weight, test_page_gap_after, test_scene_head,
               test_image_prompt_pieces, test_image_prompt_page,
               test_directing_hints, test_sheet_line,
               test_ratio_break, test_pageart, test_stitch_rhythm, test_import_sheet):
        fn()
    if FAILED:
        print("FAILED:")
        for f in FAILED:
            print("  - " + f)
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
