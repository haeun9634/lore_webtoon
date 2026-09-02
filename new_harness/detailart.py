#!/usr/bin/env python3
"""디테일 -> 사건 그림 직행 실험 (컷 대본·콘티를 건너뛴다).

## 왜 있는가

지금 흐름은 씬 -> 디테일 -> 컷 대본 -> 콘티 -> 그림이다. 그런데 컷 대본
단계에서 대사·컷·카메라를 다 못박고 나면, 그림은 그것을 성실히 옮기기만
해서 결과가 평평해진다(실측). 반대로 **디테일을 그대로 그림 모델에게 주고
"이 장면을 웹툰으로 그려라" 하면 훨씬 살아 있는 화면이 나온다** — 대신
장면 하나에 내용이 다 몰려 산만해지거나, 장면별로 따로 그리면 앞뒤 그림이
안 이어진다.

**그래서 한 장이 되는 단위는 장면이 아니라 사건이다.** 장면 하나에는 사건이
여러 개 들어 있다 — "일어난다 / 시계를 본다 / 방을 나간다 / 마주친다 /
인사한다 / 아침을 차린다 / 질문을 받는다" 가 한 장면이었다. 이것을 한 장에
다 그리게 하면 산만해지고, 그렇다고 컷을 하나씩 지정하면 연출을 사람이 다
짜는 것이 된다. 사건에서 끊으면 그림 모델이 사건 하나를 받아 **컷 수·구도·
여백·대사를 스스로 정한다.** 사건을 어떻게 나누고 사건 사이를 어떻게 잇는지는
구체화 단계가 정한다(prompt/detail_prompt, `scenes[].events[]`).

사건 칸이 없는 옛 run 은 장면 하나가 사건 하나로 읽혀(`pages.detail_events`)
예전처럼 장면당 한 장이 나온다.

그 둘을 같이 잡아 보려는 실험이다. 이어짐은 **글로 다 넣는 대신** 세 가지로
붙든다.

1. 고정 앵커 — 그림체·캐릭터 시트는 장면마다 **글자까지 같은 것**이 들어간다.
2. 직전 상태 콜백 — 직전 장면이 "어떻게 끝났는지" 한 줄만 넘긴다.
   (앞 내용을 통째로 다시 주면 다시 산만해진다)
3. 직전 그림 자체를 참조로 — 텍스트로는 못 잡는 조명·각도·인상을 잇는다.
   pageart.draw 가 페이지를 이어 그릴 때 쓰는 방식과 같다.

**첫 장면은 직전 그림이 없으므로 대신 제목을 준다** — 표지처럼 쓸 수 있게.

## 쓰는 법

    python detail_image_test.py --run-id <id> --dry-run   # 프롬프트만 (무료)
    python detail_image_test.py --run-id <id>             # 실제 생성 (과금)
    python detail_image_test.py --run-id <id> --only 2 3  # 그 장면만

결과는 run 폴더의 `detail_images/` 아래에만 쓴다 — 기존 파이프라인의
`pages/`·`board.json` 은 건드리지 않는다. 실험이라서 확정된 것이 아니다.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import imagegen
import imageprompt
import llm
import pages

HERE = Path(__file__).resolve().parent
RUNS_DIR = HERE / "runs"
PROMPT_DIR = HERE / "prompt"
STAGE = "PAGE_IMAGE"
PAGE_DIR = "pages"


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def record(run_dir: Path, call_meta: dict) -> None:
    """호출 하나(성공·실패 상관없이)를 run.py 의 meta.json 에 남긴다.

    run.py 의 record() 와 같은 파일·같은 모양이다 — 나중에 비용을 정산할
    때 이 run이 어느 스크립트로 그렸는지 신경 쓸 필요가 없게 한다.
    """
    path = run_dir / "meta.json"
    meta = read_json(path) or {"run_id": run_dir.name, "calls": []}
    meta["calls"].append(call_meta)
    write_json(path, meta)
    cost = call_meta.get("cost") or {}
    tag = "실패" if call_meta.get("error") else "완료"
    log(f"  [{tag}] {call_meta.get('stage')}  {call_meta.get('provider')}:"
        f"{call_meta.get('model')}  ${cost.get('total', 0):.4f}"
        + (f"  — {call_meta['error']}" if call_meta.get("error") else ""))


def cast_of(detail: dict, run_dir: Path) -> list[dict]:
    """조연 외모. 디테일이 적어 줬으면 그것, 없으면 옛 run 을 위해 콘티에서.

    주인공은 시트가 있어서 매번 같은 사람으로 나오지만 조연은 지정이 없으면
    장면마다 다른 사람이 그려진다 — 그래서 이것도 고정 앵커에 넣는다.
    """
    got = detail.get("cast")
    if not got:
        board = read_json(run_dir / "board.json") or {}
        got = board.get("cast") or []
    # 주인공은 시트로 이미 고정돼 있다 — cast 에 또 있으면 같은 사람을 두 번
    # 적게 되고, 두 설명이 조금이라도 다르면 그림이 흔들린다.
    hero = ((read_json(run_dir / "input.json") or {}).get("name") or "").strip()
    return [c for c in got
            if isinstance(c, dict) and (c.get("name") or "").strip()
            and (c.get("name") or "").strip() != hero]


def character_block(char: dict | None, spec: dict | None, cast: list[dict]) -> str:
    """장면마다 **글자까지 같게** 들어가는 인물 고정 앵커."""
    lines = []
    if spec:
        lines.append(imageprompt.sheet_line(spec))
    elif char:
        who = (char.get("name") or "").strip()
        desc = (char.get("description") or "").strip()
        lines.append(f"{who} — {desc}" if desc else who)
        for k, v in (char.get("fields") or {}).items():
            lines.append(f"- {k}: {v}")
    for one in cast:
        lines.append(f"{one['name']} — {(one.get('appearance') or '').strip()}")
    lines = [ln for ln in lines if ln and ln.strip()]
    if not lines:
        return ""
    return ("## 인물 (외모는 장면이 바뀌어도 그대로다)\n"
            "주인공은 첨부한 시트를 그대로 따른다. 아래 인물은 이 화 내내 같은 사람으로 그린다.\n"
            + "\n".join(lines))


def scene_text(scene: dict) -> str:
    """그릴 내용 — 사건 하나의 디테일 항목을 **빠짐없이** 편다.

    본문만 주면 그림이 '무슨 장면인지'는 알아도 '무엇이 보여야 하는지'를
    모른다. learns.how·guesses.from 은 눈에 보이는 근거가 적힌 칸이라
    그림에 그대로 쓸 값이다.
    """
    out = []
    if scene.get("function"):
        out.append(f"[이 장면이 하는 일] {scene['function']}")
    body = (scene.get("detail") or scene.get("source") or "").strip()
    if body:
        out += ["", body]

    learns = [x for x in (scene.get("learns") or []) if isinstance(x, dict)]
    if learns:
        out += ["", "[독자가 이 장면에서 알게 되는 것 — 화면에 보여야 한다]"]
        for x in learns:
            out.append(f"- {x.get('what', '')}  ← {x.get('how', '')}")

    guesses = [x for x in (scene.get("guesses") or []) if isinstance(x, dict)]
    if guesses:
        out += ["", "[인물이 짐작하는 것 — 확정이 아니라 그렇게 보이기만 한다]"]
        for x in guesses:
            out.append(f"- {x.get('what', '')}  ← {x.get('from', '')}")

    if scene.get("leads_to"):
        out += ["", f"[이 장면 뒤로 이어지는 방향 — 마지막 컷을 여기로 끊는다] "
                    f"{scene['leads_to']}"]
    return "\n".join(out).strip()


def episode_overview(scenes: list[dict], current_id) -> str:
    """이 화 전체 장면 목록 — 지금 장면이 전체 흐름 중 어디인지 보여준다.

    실험: 장면별 요약(글)만으로 이어 붙이던 것과 달리, 전체 줄거리를 매
    호출에 다 준다. 대신 지금 장면보다 뒤에 있는 사건을 미리 그리지 말라고
    명시한다 — 안 박으면 다음 장면 내용이 지금 그림에 새어 들어온다.
    """
    lines = ["## 이 화 전체 줄거리 (참고용 — 지금 그릴 것은 아래 「지금 장면」 하나뿐이다)",
             "",
             "아래는 이 화 전체 흐름이다. **지금 장면보다 뒤에 있는 사건은 지금 "
             "이 그림에 그리지 않는다** — 그 사건들은 나중 페이지에서 따로 그려진다. "
             "지금 이 그림은 오직 「지금 그릴 장면」한 칸만 그린다.",
             ""]
    for i, s in enumerate(scenes, 1):
        mark = " ← 지금 그릴 장면" if s.get("id") == current_id else ""
        summary = (s.get("function") or s.get("source") or "").strip()
        lines.append(f"{i}. {summary}{mark}")
    return "\n".join(lines)


def continuity_block(scene: dict, prev: dict | None) -> str:
    """이어짐 — 앞 사건과 이 사건 **사이**를 메운다.

    앞 장면을 통째로 다시 주면 이 그림에 앞 내용까지 그려 넣어 산만해진다.
    그래서 이어지는 데 필요한 것만 준다. 특히 `transition`(두 장면 사이에
    실제로 일어난 일)이 없으면 그림이 순간이동한다 — 앞은 식탁에서 끝났는데
    다음이 책상 청소부터 시작하면, 사람은 알아서 메우지만 그림 모델은 전혀
    다른 공간으로 건너뛴다(실측).
    """
    con = scene.get("continuity") or {}
    lines = []

    prev_end = (con.get("previous_ending") or "").strip()
    if not prev_end and prev:
        # 옛 run(이어짐 칸이 없는 디테일)을 위한 대비 — 앞 장면의 끝 상태를
        # 그쪽 continuity 에서, 그것도 없으면 본문 마지막 문장에서 가져온다.
        prev_con = prev.get("continuity") or {}
        prev_end = (prev_con.get("ending_state") or "").strip()
        if not prev_end:
            body = (prev.get("detail") or "").replace("\n", " ")
            tail = [s.strip() for s in body.split(".") if s.strip()]
            prev_end = (tail[-1] + ".") if tail else ""
    if prev_end:
        lines.append(f"- 직전 장면이 끝난 자리: {prev_end}")
    if con.get("transition"):
        lines.append(f"- 그 뒤 이 장면까지 사이에 일어난 일: {con['transition']}")
    if con.get("opening_state"):
        lines.append(f"- 이 장면이 시작되는 순간: {con['opening_state']}")
    for x in con.get("persistent_elements") or []:
        lines.append(f"- 그대로 유지되는 것: {x}")
    for x in con.get("visual_anchors") or []:
        lines.append(f"- 앞 그림과 이어지는 것: {x}")
    if not lines:
        return ""

    return ("## 앞 장면에서 이어지는 것 (여기 적힌 것은 그리는 내용이 아니라 "
            "이어 붙이는 기준이다)\n" + "\n".join(lines)
            + "\n\n첨부한 직전 그림과 같은 인물·같은 그림체·같은 세계다. 위 "
              "'그대로 유지되는 것'은 직전 그림과 같게 그리고, 나머지는 아래 "
              "「이 장면」이 정한다. **직전 그림의 내용을 다시 그리지 마라** — "
              "이 장면의 첫 컷이 직전 그림의 다음 순간이 되게 이어 그린다.")


def build_cover_prompt(*, title: str, genre: str, plot: str, first: dict,
                       char: dict | None, spec: dict | None, cast: list[dict],
                       provider: str, style: str) -> str:
    """표지 한 장. 컷을 나누지 않는 **한 장짜리 그림**이라 지시가 다르다."""
    blocks = [imageprompt.load_fixed_block(provider, style)]
    blocks.append("""\
## 이 그림은 표지다 (중요 — 위의 '페이지 구성'보다 이 절이 우선한다)

컷을 나누지 않는다. **한 장짜리 그림 하나**를 그린다. 말풍선·나레이션 상자·
효과음도 넣지 않는다.

- 이 화를 아직 안 읽은 사람이 보고 "무슨 이야기지?" 하고 눌러 보고 싶어지는
  그림이어야 한다.
- 주인공이 어떤 처지에 있는 사람인지, 여기가 어떤 세계인지가 한 장에서
  읽혀야 한다. 이 화의 특정 사건을 설명하지는 않는다.
- 제목을 그림 안에 글자로 넣는다. 인물의 얼굴을 가리지 않는 자리에 두고,
  아래 적힌 제목을 **글자 그대로** 쓴다.""")

    who = character_block(char, spec, cast)
    if who:
        blocks.append(who)

    lines = ["## 이 작품", f"제목(이 글자 그대로 그린다): {title}" if title else ""]
    if genre:
        lines.append(f"장르: {genre}")
    if plot:
        lines += ["", "줄거리:", plot]
    if first.get("detail"):
        lines += ["", "이 화가 시작되는 자리(분위기 참고용 — 이 장면을 그대로 "
                      "그리는 것이 아니다):", first["detail"]]
    blocks.append("\n".join(x for x in lines if x))
    return "\n\n".join(b for b in blocks if b) + "\n"


def build_prompt(scene: dict, prev: dict | None, *, n: int, total: int,
                 title: str, genre: str, plot: str,
                 char: dict | None, spec: dict | None, cast: list[dict],
                 provider: str, style: str,
                 all_scenes: list[dict] | None = None) -> str:
    """장면 하나 -> 그림 호출 하나에 보낼 프롬프트.

    고정 구조는 prompt/detail_image_prompt 에 있다(코드가 아니라 데이터).
    여기서는 그 자리에 인물·이어짐·장면·그림체만 끼워 넣는다.

    all_scenes 를 주면 전체 줄거리 개요(`episode_overview`)를 같이 넣는다 —
    장면 요약 한 줄 이어붙이기 대신 화 전체 흐름을 준다는 실험. 안 주면
    기존과 동일하게 직전 장면 상태만 넘긴다(하위호환, 기본은 꺼짐 아님 —
    호출부에서 all_scenes 를 안 넘기면 이 블록이 그냥 안 붙는다).
    """
    path = PROMPT_DIR / "detail_image_prompt"
    if not path.exists():
        raise SystemExit(f"프롬프트가 없습니다: {path}")
    text = path.read_text(encoding="utf-8")

    if prev is None:
        # 첫 장면은 도입부 설명이 **필수**다. 그림으로 짐작하게 두면 독자는
        # 인물이 누구인지도 모른 채 읽는다 — 실측: 주인공이 하녀라는 것도,
        # 여기가 어디인지도 안 나온 페이지가 나왔다. 그 사실은 줄거리에만
        # 있고 장면 본문에는 없어서 그림 모델이 알 방법이 없었다. 그래서
        # 전제를 여기서 같이 준다.
        lines = [f"## 이 화의 첫 장면이다 (전체 {total}장면 중 {n}번째) — 도입부 설명은 필수다",
                 "",
                 "독자는 이 작품을 지금 처음 본다. 아래 세 가지를 **페이지 위쪽의 첫 컷 "
                 "한두 개 안에서 나레이션(네모 상자)으로 반드시 글자로 밝힌다.** 그림으로 "
                 "짐작하게 두지 마라 — 안 적으면 독자는 이 인물이 누구인지, 여기가 "
                 "어디인지 모르는 채로 읽게 된다.",
                 "",
                 "1. 여기가 어디인가 (장소와 세계)",
                 "2. 이 인물이 누구이고, 여기서 무엇을 하는 사람인가 (신분·처지)",
                 "3. 지금이 어떤 상황인가 (이 일이 얼마나 되풀이돼 왔는지 포함)",
                 "",
                 "이 세 가지를 밝힌 **뒤에** 장면의 사건으로 들어간다. 사건이나 인물의 "
                 "반응부터 던지지 않는다.",
                 ""]
        if title or genre:
            lines.append(f"[작품] {title}" + (f" · {genre}" if genre else ""))
        if plot:
            lines += ["", "[이 화의 전제 — 위 나레이션에 쓸 사실은 여기 있다. "
                          "이 줄거리를 그리라는 뜻이 아니다]", plot]
        lines += ["", "첨부한 그림은 이 화의 표지다. 인물의 외모와 세계의 분위기만 "
                      "참고하고, 표지의 구도를 따라 그리지는 않는다."]
        con = "\n".join(lines)
    else:
        con = continuity_block(scene, prev)
        con = (con + f"\n\n(전체 {total}장면 중 {n}번째)") if con else \
              f"(전체 {total}장면 중 {n}번째)"

    if all_scenes:
        con = episode_overview(all_scenes, scene.get("id")) + "\n\n" + con

    return (text
            .replace("{people}", character_block(char, spec, cast))
            .replace("{continuity}", con)
            .replace("{scene}", scene_text(scene))
            .replace("{style}", imageprompt.load_style(style)))


def page_path(run_dir: Path, page_no: int) -> Path:
    """페이지 번호는 1부터다 — **1 이 표지**, 2 부터가 장면이다.

    기존 콘티 흐름과 **같은 이름·같은 자리**에 쓴다(pageart.page_path 와 동일).
    그래야 둘러보기·편집실·굽기가 이 결과를 그대로 읽는다 — 제품 쪽 코드를
    한 줄도 안 고치고 붙이려는 것이 이 규칙의 이유다.
    """
    return run_dir / PAGE_DIR / f"page{page_no:02d}.png"


def build_continue_prompt(direction: dict, char: dict | None, spec: dict | None,
                          cast: list[dict], *, scene_no: int, has_prev: bool) -> str:
    """실험 2 (v2): 구체화(detail.json) 없이, 방향(direction) 원본 그대로 그린다.

    씬 하나 = 이미지 하나로 되돌렸다 — v1(자연스럽게 이어지는 만큼 알아서
    그려라)은 모델이 순서를 안 지키고 뒤 장면(결말)으로 건너뛰는 문제가
    실측으로 나왔다(2번째 호출이 5번 장면을 그림). 그래서 **어느 장면을
    그릴지는 코드가 정하고**, 모델에게 남기는 자유는 "그 장면을 직전 그림과
    끊기지 않게 이어 그리는 것"뿐이다.

    {style} 자리는 호출부(draw_continue)가 채운다.
    """
    path = PROMPT_DIR / "detail_image_prompt"
    if not path.exists():
        raise SystemExit(f"프롬프트가 없습니다: {path}")
    text = path.read_text(encoding="utf-8")

    title = (direction.get("title") or "").strip()
    genre = (direction.get("genre") or "").strip()
    plot = (direction.get("plot") or "").strip()
    scenes = [s for s in (direction.get("scenes") or []) if isinstance(s, str) and s.strip()]
    this_scene = scenes[scene_no - 1] if 0 < scene_no <= len(scenes) else ""

    lines = ["## 이 화 전체 줄거리 (참고용 — 지금 그릴 것은 아래 「지금 그릴 장면」 하나뿐이다)", ""]
    if title or genre:
        lines.append(f"[작품] {title}" + (f" · {genre}" if genre else ""))
    if plot:
        lines += ["", "[줄거리]", plot]
    if scenes:
        lines += ["", "[장면들 — 순서대로 일어나는 사건들이다]"]
        for i, s in enumerate(scenes, 1):
            mark = " ← 지금 그릴 장면" if i == scene_no else ""
            lines.append(f"{i}. {s}{mark}")
    con = "\n".join(lines)

    goal = f"위 목록의 {scene_no}번 장면을 그린다: \"{this_scene}\"\n\n" \
           "이 장면만 그린다 — 앞이나 뒤에 있는 다른 장면 내용을 끌어오지 않는다."

    if has_prev:
        scene_instr = (
            goal + "\n\n"
            "첨부한 직전 그림이 바로 앞 장면이다. **직전 그림이 멈춘 순간에서 "
            "자연스럽게 이어지도록** 그린다 — 인물의 자세·위치·시간대·조명이 "
            "직전 그림과 뚝 끊기지 않아야 한다. 직전 그림에 이미 그려진 "
            "내용(같은 순간·같은 대사)을 다시 그리지 않는다."
        )
    else:
        scene_instr = goal + "\n\n이 화의 시작이다."

    return (text
            .replace("{people}", character_block(char, spec, cast))
            .replace("{continuity}", con)
            .replace("{scene}", scene_instr))


def draw_continue(run_dir: Path, dry_run: bool = False, only=None,
                  allow_no_sheet: bool = False, on_page=None) -> list[dict]:
    """이어그리기 — **지금의 최종 방식.** 구체화(detail.json)·콘티(board.json)·
    컷 대본을 전부 건너뛰고, story 단계(방향 후보) 산출물만으로 그린다.

    표지가 1페이지, 씬이 2페이지부터다 — draw()·pageart.draw 와 같은 자리
    (`pages/pageNN.png`)에 쓴다. 씬 하나 = 이미지 하나로 고정한다(모델이
    알아서 이어 그리게 뒀던 첫 버전은 순서를 안 지키고 뒤 장면으로 건너뛰는
    문제가 실측으로 나왔다). 이어짐은 직전 그림을 참조로 붙이는 것과, 매
    호출에 전체 줄거리를 같이 주는 것 둘로만 잡는다 — 씬 사이 상태를 글로
    미리 요약해 두는 구체화 단계가 없다.

    on_page(meta) : 한 장이 끝날 때마다(성공이든 실패든) 바로 부른다 — 중간에
    죽어도 이미 나간 돈과, 실패였다면 그 사유까지 meta.json 에 남는다.
    """
    pick = read_json(run_dir / "pick.json") or {}
    directions = read_json(run_dir / "directions.json") or []
    n = pick.get("n")
    direction = next((d for d in directions if d.get("n") == n), None) or (directions[0] if directions else {})
    if not direction:
        raise SystemExit(f"{run_dir / 'directions.json'} 가 없습니다. 이야기 단계를 먼저 돌리세요.")

    scenes = [s for s in (direction.get("scenes") or []) if isinstance(s, str) and s.strip()]
    if not scenes:
        raise SystemExit(f"{run_dir / 'directions.json'} 의 {n}번 방향에 장면이 없습니다.")

    char = read_json(run_dir / "input.json")
    spec = read_json(run_dir / "sheet_spec.json")
    hero = (char.get("name") or "").strip() if char else ""
    # cast — story 단계(방향 후보)가 직접 뽑는다(story_prompt 의 "등장인물").
    # board.json·detail.json 을 안 만드는 흐름이라 그 둘에서 가져올 수 없다.
    # 옛 run(story_prompt 가 등장인물을 안 뽑던 시절)을 위해 board.json 이
    # 있으면 그쪽도 여전히 봐준다 — 없으면 그냥 빈 목록이다.
    cast = [c for c in (direction.get("cast") or [])
           if isinstance(c, dict) and (c.get("name") or "").strip()
           and (c.get("name") or "").strip() != hero]
    if not cast:
        board = read_json(run_dir / "board.json") or {}
        cast = [c for c in (board.get("cast") or [])
               if isinstance(c, dict) and (c.get("name") or "").strip()
               and (c.get("name") or "").strip() != hero]

    sheet = run_dir / "sheet.png"
    if not sheet.exists() and not dry_run and not allow_no_sheet:
        raise SystemExit(
            f"캐릭터 시트가 없습니다: {sheet}\n"
            "        run.py --sheet 로 만들거나, 정말 없이 그리려면 --no-sheet 를 붙이세요.")
    refs_base = [sheet] if sheet.exists() else []

    # dry-run 은 키가 없어도 돌아야 한다 — backend_for() 는 키 없으면
    # SystemExit 이라, 진짜 생성일 때만 부른다.
    if dry_run:
        provider, model, quality = llm.provider_for(STAGE), "", ""
    else:
        provider, model, quality = imagegen.backend_for(STAGE)
    style = (llm.env("NH_STYLE") or llm.env("PAGE_STYLE") or imageprompt.DEFAULT_STYLE)
    dest = run_dir / PAGE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    log(f"[이어그리기] 표지 1장 + 장면 {len(scenes)}개 · 그림체 {style} · {provider}"
        + (f":{model}" if model else ""))

    title, genre, plot = direction.get("title") or "", direction.get("genre") or "", direction.get("plot") or ""

    made = []
    for n_ in range(0, len(scenes) + 1):  # 0 = 표지, 1..len(scenes) = 씬
        page_no = n_ + 1
        if n_ == 0:
            prompt = build_cover_prompt(title=title, genre=genre, plot=plot,
                                        first={"detail": scenes[0]}, char=char, spec=spec,
                                        cast=cast, provider=provider, style=style)
        else:
            has_prev = True  # 씬1의 직전은 표지, 그 뒤로는 항상 직전 씬이 있다
            prompt = (build_continue_prompt(direction, char, spec, cast,
                                            scene_no=n_, has_prev=has_prev)
                      .replace("{style}", imageprompt.load_style(style)))
        (dest / f"page{page_no:02d}.txt").write_text(prompt, encoding="utf-8")
        if only and page_no not in only:
            continue
        if dry_run:
            continue

        out = page_path(run_dir, page_no)
        label = "표지" if n_ == 0 else f"장면 {n_}/{len(scenes)}"
        if out.exists():
            log(f"  {label}: 이미 있습니다 (다시 그리려면 지우세요)")
            continue

        prev_img = page_path(run_dir, page_no - 1)
        refs = refs_base + ([prev_img] if page_no > 1 and prev_img.exists() else [])
        log(f"[{label}] 참조 {len(refs)}장 …")
        try:
            meta = imagegen.paint(STAGE, prompt, out, refs=refs, kind=imagegen.PAGE_KIND)
        except Exception as exc:                                     # noqa: BLE001
            # 실패해도 무엇에 얼마나 썼는지는 남겨야 나중에 비용을 정산할 수
            # 있다 — 성공 때와 같은 모양(stage·provider·model·cost)에 error 만
            # 더해서 on_page 로 넘긴다. 이어그리기는 직전 이미지가 있어야
            # 다음 장을 그릴 수 있으므로, 실패하면 여기서 멈춘다.
            err_meta = {"stage": STAGE, "provider": provider, "model": model,
                       "quality": quality, "page": page_no, "scene": n_,
                       "refs": [r.name for r in refs],
                       "cost": {"input": 0.0, "output": 0.0, "cache_read": 0.0,
                                "cache_write": 0.0, "total": 0.0},
                       "error": f"{type(exc).__name__}: {exc}",
                       "output_path": str(out)}
            if on_page:
                on_page(err_meta)
            log(f"  실패 [{label}]: {err_meta['error']}")
            raise
        meta["page"] = page_no
        meta["scene"] = n_
        made.append(meta)
        if on_page:
            on_page(meta)
        log(f"  -> {out}  (${meta['cost'].get('total', 0):.4f})")

    if dry_run:
        log(f"[이어그리기] 프롬프트만 썼습니다 -> {dest}")
    elif made:
        total = sum(m["cost"].get("total", 0) for m in made)
        log(f"끝났습니다 — {len(made)}장 · ${total:.4f} -> {dest}")
    return made


def draw(run_dir: Path, dry_run: bool = False, only=None,
         allow_no_sheet: bool = False, on_page=None,
         episode_context: bool = False) -> list[dict]:
    """디테일 -> 페이지 그림. **표지가 1페이지, 사건이 2페이지부터다.**

    결과를 기존 콘티 흐름과 같은 자리(`pages/pageNN.png` · `pages.json`)에
    쓴다 — 둘러보기·편집실·굽기가 그대로 읽는다.

    **순서대로 그리는 것이 요점이다.** 직전 페이지를 참조로 붙이려면 그것이
    이미 있어야 한다(pageart.draw 와 같은 이유로 병렬로 안 돌린다).

    on_page(meta) : 한 장이 끝날 때마다 바로 부른다 — 중간에 죽어도 이미
    나간 돈이 기록에 남게 하는 자리다.
    """
    detail = read_json(run_dir / "detail.json")
    if not detail or not detail.get("scenes"):
        raise SystemExit(f"{run_dir / 'detail.json'} 가 없습니다. 구체화를 먼저 돌리세요.")

    char = read_json(run_dir / "input.json")
    spec = read_json(run_dir / "sheet_spec.json")
    pick = read_json(run_dir / "pick.json") or {}
    title, genre = (pick.get("title") or ""), (pick.get("genre") or "")
    cast = cast_of(detail, run_dir)

    # 표지에는 줄거리를 준다 — 특정 장면이 아니라 이 화 전체를 대표해야 한다.
    plot = ""
    for d in read_json(run_dir / "directions.json") or []:
        if d.get("n") == pick.get("n"):
            plot = d.get("plot") or ""
            break

    sheet = run_dir / "sheet.png"
    refs_base = [sheet] if sheet.exists() else []
    if not refs_base and not dry_run and not allow_no_sheet:
        # 경고가 아니라 멈춘다 — 시트 없이 그리면 장면마다 다른 사람이 나오고,
        # 그렇게 나온 것은 다시 그려야 하므로 호출값이 통째로 낭비된다.
        raise SystemExit(
            f"캐릭터 시트가 없습니다: {sheet}\n"
            "        시트 없이 그리면 장면마다 다른 사람이 나옵니다.\n"
            "        run.py --sheet 로 만들거나 --sheet-from 으로 가져오세요.\n"
            "        정말 없이 그리려면 --no-sheet 를 붙이세요.")

    provider = llm.provider_for(STAGE)
    style = (llm.env("NH_STYLE") or llm.env("PAGE_STYLE")
             or imageprompt.DEFAULT_STYLE)

    # 그림 한 장 = 사건 하나. 장면 경계를 넘어 이어 편다 — 이어짐도 그림
    # 참조도 "바로 앞 사건" 이 기준이라, 장면이 바뀌는 자리에서 끊으면 안 된다.
    units = pages.flatten_events(detail["scenes"])
    dest = run_dir / PAGE_DIR
    dest.mkdir(parents=True, exist_ok=True)
    log(f"[디테일 직행] 표지 1장 + 사건 {len(units)}개"
        f"(장면 {len(detail['scenes'])}개) · 그림체 {style} · {provider}")

    # pages.json — 둘러보기가 페이지 수를 여기서 읽는다. 컷 대본을 안 거치는
    # 흐름이라 컷 목록이 없으므로, 페이지마다 무엇이 들어갔는지만 적는다.
    #
    # **dry-run 에서는 안 쓴다.** 프롬프트만 보려고 돌린 것이 이미 있는
    # 페이지 구성을 덮어쓰면, 콘티 흐름으로 만들어 둔 run 의 페이지 수가
    # 조용히 바뀐다(실측: 2026-09-01, dry-run 이 콘티 기반 pages.json 을
    # 갈아치웠다 — `--repage` 로 되돌릴 수 있었지만 알아채기 어려웠다).
    if not dry_run:
        pages_doc = [[{"source": "표지", "size": "full"}]]
        for u in units:
            pages_doc.append([{"scene": u.get("scene"), "event": u.get("event"),
                               "source": u.get("source", ""), "size": "full"}])
        write_json(run_dir / "pages.json", pages_doc)

    # 0 = 표지, 1..N = 사건. 표지를 따로 두는 이유: 표지는 컷을 안 나누는
    # 한 장짜리 그림이라 지시가 다르고, 첫 사건이 표지를 겸하면 둘 다
    # 어중간해진다. 페이지 번호는 여기에 1 을 더한 값이다.
    jobs = [(0, None, None)] + [(i, u, (units[i - 2] if i > 1 else None))
                                for i, u in enumerate(units, 1)]

    made = []
    for n, unit, prev_unit in jobs:
        page_no = n + 1
        if n == 0:
            prompt = build_cover_prompt(title=title, genre=genre, plot=plot,
                                        first=units[0], char=char, spec=spec,
                                        cast=cast, provider=provider, style=style)
        else:
            prompt = build_prompt(unit, prev_unit, n=n, total=len(units),
                                  title=title, genre=genre, plot=plot,
                                  char=char, spec=spec, cast=cast,
                                  provider=provider, style=style,
                                  all_scenes=detail["scenes"] if episode_context else None)
        (dest / f"page{page_no:02d}.txt").write_text(prompt, encoding="utf-8")
        if only and page_no not in only:
            continue
        if dry_run:
            continue

        out = page_path(run_dir, page_no)
        label = "표지" if n == 0 else f"사건 {n}/{len(units)}"
        if out.exists():
            log(f"  {label}: 이미 있습니다 (다시 그리려면 지우세요)")
            continue

        # 직전 그림을 마지막 참조로. 장면 1의 직전은 표지다(인물·세계의
        # 인상만 이어받는다).
        prev_img = page_path(run_dir, page_no - 1)
        refs = refs_base + ([prev_img] if page_no > 1 and prev_img.exists() else [])
        log(f"[{label}] 참조 {len(refs)}장 …")
        meta = imagegen.paint(STAGE, prompt, out, refs=refs, kind=imagegen.PAGE_KIND)
        meta["page"] = page_no
        # 어느 장면의 몇 번째 사건이었는지. 표지는 둘 다 없다.
        meta["scene"] = unit.get("scene") if unit else None
        meta["event"] = unit.get("event") if unit else None
        made.append(meta)
        if on_page:
            on_page(meta)
        log(f"  -> {out}  (${meta['cost'].get('total', 0):.4f})")

    if dry_run:
        log(f"[디테일 직행] 프롬프트만 썼습니다 -> {dest}")
    elif made:
        total = sum(m["cost"].get("total", 0) for m in made)
        log(f"끝났습니다 — {len(made)}장 · ${total:.4f} -> {dest}")
    return made


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--run-id", required=True, help="detail.json 이 있는 run")
    p.add_argument("--only", type=int, nargs="*", default=[],
                   help="이 페이지 번호만 (1 이 표지)")
    p.add_argument("--dry-run", action="store_true", help="프롬프트만 쓰고 호출하지 않는다")
    p.add_argument("--no-sheet", action="store_true",
                   help="캐릭터 시트 없이 진행 (인물이 장면마다 달라진다)")
    p.add_argument("--episode-context", action="store_true",
                   help="장면 하나 요약 대신 이 화 전체 줄거리를 매 호출에 준다 (실험)")
    p.add_argument("--continue-pages", action="store_true",
                   help="이어그리기(최종 방식): detail.json·board.json 없이 "
                        "direction 원본으로 표지+전체 씬을 그린다 (pages/ 에 씀)")
    args = p.parse_args(argv)
    if args.continue_pages:
        run_dir = RUNS_DIR / args.run_id
        draw_continue(run_dir, dry_run=args.dry_run, only=args.only or None,
                     allow_no_sheet=args.no_sheet,
                     on_page=lambda meta: record(run_dir, meta))
        return 0
    draw(RUNS_DIR / args.run_id, dry_run=args.dry_run, only=args.only or None,
         allow_no_sheet=args.no_sheet, episode_context=args.episode_context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
