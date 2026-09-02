"""랜딩페이지 뒤에서 도는 오케스트레이터.

사용자가 보는 것은 **캐릭터 시트 한 장과 입력창 하나**뿐이다. 그 뒤에서는
story-harness 와 webtoon-harness 의 최종 파이프라인이 순서대로 돈다:

    1. story.py --character         이야기 설계 (LOOK·SEED·P1·P2·P3·SCENE)
    2. story.py --charsheet         캐릭터 시트 1장 (후보 1장 → 자동 채택)
    3. webtoon.py --run             회차 설계 · 콘티 (4~8단계)
    4. run.py --mode scene -c S+    한 장에 3컷씩 그림 (말풍선·대사 포함)
    5. (같은 실행)                  장을 세로로 이어 붙여 episode.png

## 하네스는 바깥에서 조종한다

두 하네스는 완성본이라 원칙적으로 건드리지 않는다. **바깥에서 주는 것**으로만
제품 동작을 만든다:

    --config <job>/config.yaml      원본 config.yaml 을 복사해 이 실행에만 쓸
                                    값을 덮어쓴다 (그림체 · 말풍선 · 인물 고정값)
    WEBTOON_HARNESS_DIR=<job>       story.py 의 --charsheet 가 그림체 문구를
                                    읽어 가는 곳. 이걸 job 폴더로 돌려야 시트와
                                    컷이 **같은 그림체**를 본다
    --skip-human-gate               블라인드 평가는 연구용 관문이라 제품에서는
                                    건너뛴다 (아래 참고)

예외가 하나 있다 — `scene.grouping` 은 바깥에서 줄 수 있는 값이 아예 없어서
webtoon-harness 에 스위치를 더했다 (기본값 `rhythm` = 예전 그대로). 한 장에
정확히 N컷을 넣으려면 연출의 리듬 경계를 꺼야 하는데, 상한만으로는 안 된다:
상한은 큰 묶음을 **고르게** 쪼개므로 4컷 묶음에 상한 3을 걸면 2+2 가 된다.

## 블라인드 평가를 건너뛰는 것에 대해

webtoon.py 는 원래 사람이 "다음 화가 궁금한가"에 답해야 컷으로 넘어간다.
재미 판정은 하네스에서 사람만 하는 일이기 때문이다. 랜딩페이지는 사람을 세울
자리가 없으므로 `--skip-human-gate` 로 지나간다. **재미가 검증됐다는 뜻이
아니다** — 그 관문이 없는 상태로 뽑은 결과라는 뜻이다.

## 진행 상황은 자식 프로세스의 stdout 에서 읽는다

하네스는 진행률 API 를 제공하지 않는다. 대신 사람이 보라고 찍는 줄들이 있고
(`P3 [통과] …`, `4단계 통과: Arc 3개`, `[3/4] scene_S+ / Scene3 / c1`), 그 줄들이 곧
단계 표시가 된다. 못 읽는 줄은 그냥 로그로 흘린다 — 표시가 한 칸 늦을 수는
있어도 틀린 단계를 보여주지는 않는다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import overlay          # 편집실에서 얹은 것을 저장하고 그림에 굽는다
import report           # picks.csv 읽기 — overlay 의 sys.path 설정 뒤에 와야 한다
import watermark        # 내려받기 표시 — cut_bounds() 가 컷 자리 계산을 넘긴다

HERE = Path(__file__).resolve().parent
JOBS_DIR = HERE / "jobs"
STORY = HERE.parent / "story-harness"
WEBTOON = HERE.parent / "webtoon-harness"


def _dotenv(path: Path) -> dict[str, str]:
    """의존성 없는 최소 .env 파서 (story.py·run.py 의 것과 같은 규칙).

    이미 설정된 환경변수가 .env 파일보다 우선한다 — 배포에서 환경변수로
    준 값을 파일이 덮어써 버리면 안 된다."""
    values: dict[str, str] = {}
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.removeprefix("export ").partition("=")
            key, val = key.strip(), val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            values[key] = val
    return {**values, **{k: v for k, v in os.environ.items() if v}}


# 캐릭터 시트를 어느 쪽으로 그릴지. **제품의 기본은 openai** 다 — 하네스
# 자체 기본(story.py 의 gemini, "시트는 컷과 같은 모델로")과 일부러 다르게
# 골라 둔 값이라, 여기서 명시로 주지 않으면 하네스 기본으로 되돌아간다.
# .env 의 SHEET_IMAGE_PROVIDER 로 바꿀 수 있다(gemini | openai).
# 모델 이름은 story.py 가 .env 에서 읽는다 — openai 면 OPENAI_IMAGE_MODEL
# (기본 gpt-image-2), gemini 면 GEMINI_IMAGE_MODEL.
# 컷 쪽은 webtoon-harness 의 WEBTOON_IMAGE_PROVIDER 가 따로 정한다.
_ENV = _dotenv(STORY / ".env")
SHEET_IMAGE_PROVIDER = (_ENV.get("SHEET_IMAGE_PROVIDER") or "openai").strip().lower()
# 빈 값이면 --quality 를 아예 안 붙인다 — story.py 의 기본(medium)에 맡긴다.
SHEET_IMAGE_QUALITY = (_ENV.get("OPENAI_IMAGE_QUALITY") or "").strip().lower()

# 그림 조건. 합격본이 S+ 다 — 통합 시트 + 직전 컷을 붙여서, 조연이 같은
# 사람으로 이어지고 채색이 컷마다 갈리지 않는다. config.yaml 자체가
# "한 화를 통째로 뽑을 때는 S 가 아니라 S+" 라고 못박고 있다.
CONDITION = "S+"

# 확인 화면(시트·이야기·콘티·그림 검수)에서 사람 응답을 기다리는 최대 시간.
# 2026-08-26: 실사용에서 화면을 못 찾아 승인을 놓쳤더니 작업이 무한정 멈춰
# 있었다 — 그 사고 이후로 넣음. 시간이 차면 응답이 온 것처럼 취급하지 않고
# **그냥 진행(승인)** 한 것으로 치고 넘어간다 — decision 이 끝까지 비어
# 있으면(=retry 가 아니면) 각 단계 코드가 이미 "승인"으로 읽으므로, 여기서는
# wait() 에 timeout 만 주면 된다.
APPROVAL_TIMEOUT_SEC = 30


def _await_approval(job: "Job", event: threading.Event, stage: str) -> None:
    """승인 대기를 최대 APPROVAL_TIMEOUT_SEC초로 막는다. 시간이 차면 이유를
    남기고 그냥 진행 — 응답을 기다리는 동안 UI를 못 찾거나 자리를 비워도
    작업이 영영 멈춰 있지 않는다."""
    answered = event.wait(timeout=APPROVAL_TIMEOUT_SEC)
    event.clear()
    if not answered:
        job.note(f"{APPROVAL_TIMEOUT_SEC}초 동안 응답이 없어 승인으로 넘어갑니다 ({stage})")
        job.add_log(f"[승인 시간초과] {stage} — 응답 없이 {APPROVAL_TIMEOUT_SEC}초 지나 자동 승인")

# 한 장에 3컷. Gemini 는 호출당 이미지 1장이라 "3컷씩 생성"은 곧 "한 장에
# 3칸"이다 — 12컷짜리 한 화가 이미지 4장이 되고 호출도 비용도 1/3 이 된다.
#
# 대가는 픽셀이다. 캔버스 세로 2400px(9:16 · 2K)을 셋으로 나누므로 컷 하나가
# 800px 이 된다. 하네스 README 가 "얼굴이 작다는 느낌은 800px 아래에서 나오기
# 시작한다"고 적어 둔 그 경계이고, 4 로 올리면 격자(만화책 페이지)가 나오기
# 시작하는 지점이라 3 이 이음매와 격자 사이의 타협점이다.
#
# 컷 사이 여백도 모델이 정하게 된다 — 컷 모드에서는 콘티의 gap_after 를 보고
# 코드가 정했다. 되돌리려면 MODE 를 "cut" 으로 바꾸면 그 경로가 그대로 산다.
MODE = "scene"
CUTS_PER_SHEET = 3

# 위 두 값은 **기본 경로**다. 사용자가 폼에서 "웹툰"을 고르면 컷 모드로 간다.
#
# 컷 모드에서는 컷 하나가 캔버스 하나를 통째로 쓴다. 그러면 위에 적어 둔 대가가
# 그대로 사라진다 — 격자가 안 나오고(모델이 배치할 칸이 없다), 컷 사이 여백을
# 콘티의 gap_after 대로 코드가 넣고, 컷이 800px 로 줄지 않는다. 대신 이미지
# 호출이 컷 수만큼이라 세 배가 된다. 그래서 고르게 두고 기본은 그대로 둔다.
# 웹툰 모드도 run.py 에는 "scene" 으로 간다. 컷 모드가 아니라 **묶음 규칙을
# 무게로 바꾼 scene 모드**이기 때문이다 (config 의 scene.grouping: weight).
# 무거운 컷은 어차피 혼자 한 장이 되므로 컷 모드와 같은 그림이 나오고, 그 위에
# 배경 없는 가벼운 컷만 여럿이 한 장을 나눠 쓴다 — 컷 모드로는 못 하는 것이다.
LAYOUT_MODES = {
    "fast":    {"mode": "scene", "label": "빠르게 · 한 장에 3컷"},
    "webtoon": {"mode": "scene", "label": "웹툰 · 무게가 묶음을 정함"},
}


def layout_mode(form: dict[str, Any]) -> str:
    """폼의 layout_mode → fast | webtoon. **모르는 값은 webtoon 이다.**

    예전에는 fast 가 기본이었다. 그런데 fast 는 3컷을 한 캔버스에 몰아넣어
    배치를 모델에게 통째로 맡기는 모드라, 콘티가 컷마다 계산해 둔 것들
    (gap_after 여백 · size: impact 통컷 · vertical_link 배경 연결)이 **픽셀에
    닿을 자리가 없다.** 실측: 한 화의 컷 9 가 gap_after=3(폰 화면 하나를 비워라)
    이고 컷 11 이 size=impact/weight=full(한 장을 통째로 써라)인데, fast 로
    그리면 둘 다 그냥 사라진다.

    fast 를 지우지는 않는다 — 폼이 명시적으로 "fast" 를 주면 그대로 간다.
    기본에서만 뺐다.
    """
    v = str((form or {}).get("layout_mode") or "").strip().lower()
    return v if v in LAYOUT_MODES else "webtoon"


# --------------------------------------------------------------------------- #
# 일반 모드 · 전문 모드
# --------------------------------------------------------------------------- #
#
# 만드는 사람은 두 부류다. 하나는 "알아서 잘 만들어 줘" 이고, 하나는 "내가
# 정하겠다" 다. 지금까지는 뒤엣것 하나만 있었다 — 폼에 그림체·연출·등신 비율이
# 다 펼쳐져 있고, 처음 온 사람은 그중 무엇을 골라야 하는지 알 수가 없다.
#
# 그래서 **기능을 두 벌 만들지 않는다.** 만드는 길(캐릭터 → 이야기 → 시트 →
# 콘티 → 그림)은 하나뿐이고, 모드가 정하는 것은 두 가지뿐이다:
#
#   1. 폼에서 무엇을 **보여줄 것인가** — 일반은 안 보여주고 기본값으로 간다.
#      (안 보여준다고 값이 사라지는 게 아니다. 같은 기본값이 들어간다.)
#   2. 어느 단계에서 사람을 **세울 것인가** — 아래 checkpoints().
#
# 값 자체는 한 벌이라, 일반 모드로 만든 작품을 전문 모드로 이어 만들어도
# (create_next 가 origin_form 을 물려받는다) 아무것도 안 깨진다.

def expert_mode(form: dict[str, Any]) -> bool:
    """전문 모드로 만드는 중인가. 모르면 일반 모드 — 기본이 안전한 쪽이다."""
    return bool((form or {}).get("expert"))


# 각 단계에서 "사람이 볼 때까지 멈출 것인가".
#
#   True  — 결과가 멀쩡해도 무조건 멈추고 사람에게 보여준다.
#   False — 하네스 게이트가 소진돼(STATUS_HUMAN) 자동으로는 더 못 고칠 때만
#           멈춘다. 지금까지의 동작이다.
#
# 시트는 두 모드 모두 True 다. "아예 다른 사람이 됐다"는 사고는 뒤 컷 전부를
# 오염시키므로 일반 모드에서도 여기는 세워야 한다 — 다만 화면이 다르다.
# 일반 모드는 이유 항목(FEEDBACK_TAGS["sheet"])을 고르고 다시 만들기만,
# 전문 모드는 지금처럼 외형 사양을 직접 고치는 폼까지 연다.
def checkpoints(form: dict[str, Any]) -> dict[str, bool]:
    expert = expert_mode(form)
    return {
        "sheet": True,       # 두 모드 공통 — 얼굴이 틀어지면 전부가 틀어진다
        "story": expert,
        "board": expert,
        "artqa": expert,
    }


# 그림 QA 가 한 장을 최대 몇 번까지 다시 그릴 것인가. 전문 모드에서만 고를 수
# 있고, 그 밖에는 하네스에 맞춘 기본값 2 다. 0 이면 QA 는 돌되 다시 그리지
# 않는다 — "무엇이 걸렸는지는 보고 싶지만 비용은 더 안 쓰겠다" 는 선택이다.
ART_QA_REGEN_DEFAULT = 2
ART_QA_REGEN_MAX = 4


def art_qa_regen_max(form: dict[str, Any]) -> int:
    if not expert_mode(form):
        return ART_QA_REGEN_DEFAULT
    try:
        n = int((form or {}).get("art_qa_regen_max"))
    except (TypeError, ValueError):
        return ART_QA_REGEN_DEFAULT
    return max(0, min(ART_QA_REGEN_MAX, n))


# 비용 안내용 환율. webtoon-harness config.yaml 의 pricing.usd_to_krw 와 같은 값.
USD_TO_KRW = 1400

STYLES = {
    "webtoon":   "일반 웹툰",
    "romance":   "로맨스 판타지",
    "cinematic": "시네마틱 반실사",
    "pastel":    "일상툰 감성",
    "noir":      "다크 느와르",
    "shoujo":    "순정 · BL",
    "frost":     "세미리얼 · 성인향",
    "game":      "게임 원화",
}

# 사용자에게 보이는 단계. 하네스의 내부 단계 이름(P1/W5/…)은 올리지 않는다 —
# 무엇을 하고 있는지가 보여야지, 어느 프롬프트가 도는지가 보일 필요는 없다.
STAGE_SPEC: list[dict[str, Any]] = [
    {
        "key": "story", "title": "이야기 설계",
        "desc": "캐릭터에서 이야기를 만듭니다",
        "steps": [
            ("look",    "사진에서 외형 읽기"),
            ("seed",    "장르·세계관 정하기"),
            ("card",    "캐릭터 카드 쓰기"),
            ("premise", "이야기 뼈대 세우기"),
            ("judge",   "구조 검수"),
            ("scene",   "첫 장면 쓰기"),
        ],
    },
    {
        "key": "sheet", "title": "캐릭터 시트",
        "desc": "컷마다 같은 얼굴이 나오도록 기준 그림을 만듭니다",
        "steps": [
            ("spec", "외형 사양 정리"),
            ("draw", "시트 그리기"),
            ("pick", "기준 시트 확정"),
        ],
    },
    {
        "key": "board", "title": "회차 설계 · 콘티",
        "desc": "1화를 컷으로 나누고 대사를 붙입니다",
        "steps": [
            ("arc",     "큰 줄거리"),
            ("episode", "1화 설계"),
            ("check",   "연출 검사"),
            ("cuts",    "컷 나누기"),
        ],
    },
    {
        "key": "art", "title": "그림 그리기",
        "desc": f"한 장에 {CUTS_PER_SHEET}컷씩 그립니다 — 말풍선과 대사가 함께 들어갑니다",
        "steps": [
            ("prompt", "장면 서술 옮기기"),
            ("group",  f"{CUTS_PER_SHEET}컷씩 묶기"),
            ("draw",   "장 그리기"),
        ],
    },
    {
        "key": "bind", "title": "한 편으로 잇기",
        "desc": "그린 장을 순서대로 세로로 이어 붙입니다",
        "steps": [("strip", "이어 붙이기")],
    },
]

TODO, ACTIVE, DONE, ERROR, SKIP = "todo", "active", "done", "error", "skip"


# 이어 만들기(2화 이상)에서 도는 단계. 이야기·시트는 1화 것을 그대로 쓰므로
# 목록에서 아예 뺀다 — SKIP 으로 두면 화면에 회색 줄로 남아서 "안 한 것"처럼
# 보이는데, 실제로는 **할 필요가 없는** 것이다.
NEXT_STAGE_KEYS = ("board", "art", "bind")
# 이어 그리기 — 콘티는 이미 있고 **그림만 더 그린다**. 그래서 두 단계뿐이다.
MORE_STAGE_KEYS = ("art", "bind")


# --------------------------------------------------------------------------- #
# config 덮어쓰기
#
# 원본을 고치지 않고 복사본만 바꾼다. run.py 는 config 안의 상대경로를 자기
# ROOT 기준으로 푸므로(run.rel_path), 복사본이 다른 폴더에 있어도 그대로 돈다.
# --------------------------------------------------------------------------- #

def _replace_block(text: str, key: str, value: str) -> str:
    """최상위 키 하나를 통째로 바꾼다. 블록 스칼라(`>-` + 들여쓴 줄)도 지운다."""
    pattern = re.compile(rf"(?m)^{re.escape(key)}:.*(?:\n[ \t]+\S.*)*")
    if not pattern.search(text):
        raise RuntimeError(f"config.yaml 에서 '{key}' 를 찾지 못했습니다.")
    return pattern.sub(f"{key}: {value}", text, count=1)


def build_config(job_dir: Path, style: str, head_ratio: str = "",
                 genre: str = "", mode: str = "fast",
                 qa_regen_max: int = ART_QA_REGEN_DEFAULT) -> Path:
    """이 실행에만 쓸 config.yaml. 원본에서 몇 값만 바꾼다."""
    text = (WEBTOON / "config.yaml").read_text(encoding="utf-8")

    # 1. 그림체 — 시트(story.py)와 컷(run.py)이 같은 값을 봐야 한다.
    text = _replace_block(text, "style_default", style)

    # 2. 말풍선과 대사를 그림 안에 그린다. 하네스 기본값은 sfx_only(효과음만)
    #    인데, 그건 액션 컷에서 글자가 동작을 가리는 것을 막으려는 선택이다.
    #    제품에서는 대사가 보여야 하므로 in_image 로 되돌린다.
    text = re.sub(r"(?m)^  lettering:.*$", "  lettering: in_image", text, count=1)

    # 3~5. 인물 고정값은 실험용 run 의 주인공(청명)에 맞춰져 있다. 그대로 두면
    #      **누가 들어와도 그 사람의 도복을 입는다.** 전부 비운다 —
    #      기준은 이 실행의 p1.json 이고, 없으면 run.py 가 스스로 멈춘다.
    text = _replace_block(text, "character_appearance", '""')
    text = _replace_block(text, "character_gender", '""')
    text = _replace_block(text, "outfit_lock", '""')

    # 6. 한 장에 몇 컷을 묶을지 — **세 값을 다 바꿔야** 3컷씩이 된다.
    #
    #    grouping 을 fixed 로 두지 않으면 연출(W7.5)의 scene_break 가 경계를
    #    정하고, 상한(max_cuts_per_scene)은 큰 묶음을 **고르게** 쪼갤 뿐이다.
    #    실제로 4+4+2+2 짜리 한 화에 상한 3을 걸었더니 2,2,2,2,2,2 가 나왔다 —
    #    3은 한 번도 안 나온다. 3컷씩이 목적이면 리듬을 꺼야 한다.
    #
    #    대가: 경계가 이야기의 리듬과 무관하게 떨어진다. 설명하다 만 자리에서
    #    장이 넘어갈 수 있다. rhythm 으로 되돌리려면 이 한 줄만 지우면 된다.
    text = re.sub(r"(?m)^  grouping:.*$", "  grouping: fixed", text, count=1)
    text = re.sub(r"(?m)^  cuts_per_scene:.*$",
                  f"  cuts_per_scene: {CUTS_PER_SHEET}", text, count=1)
    text = re.sub(r"(?m)^  max_cuts_per_scene:.*$",
                  f"  max_cuts_per_scene: {CUTS_PER_SHEET}", text, count=1)

    # 7. 실사용자 피드백(2026-08)으로 생긴 값들. 하네스 기본은 전부 꺼짐이라
    #    (예전 run 재현용) 제품 쪽에서 켠다.
    #
    #    · 스티커 평면화 · 포즈 지시 — 사용자가 고를 것이 아니라 항상 맞는
    #      쪽이라 그냥 켠다. "스티커가 3D 라 그림체와 안 맞는다", "포즈가
    #      어색하다"에 대해 끄고 싶어할 이유가 없다.
    #    · 등신 비율 — 사용자가 고른다. 안 골랐으면 그림체 기본값.
    #    · 장르 — 톤 상한에만 쓴다. 로판을 골랐는데 공포 조명이 나오던 문제.
    text = _replace_block(text, "flat_stickers", "true")
    text = _replace_block(text, "pose_guidance", "true")

    #    · 그림 QA — 명백히 망한 그림(작화 사고 · 서술과 다른 인원/대상/배경)만
    #      잡아서 최대 2번 다시 그린다. 하네스 기본은 꺼짐(예전 run 재현용)이라
    #      제품이 켠다. 미적 판단은 안 잡는다 — 그건 결과 화면의 "다시 그리기"
    #      (사용자 피드백)가 맡는 영역이고, 검수는 QA 지 예술 감독이 아니다.
    #      한도가 차도 그림은 버리지 않고 art_qa.json 에 남겨서, 결과 화면이
    #      "검수에서 잡았지만 못 고친 것"으로 보여준다.
    #
    #      다시 그리는 횟수는 전문 모드에서만 고를 수 있다(art_qa_regen_max).
    #      일반 모드는 늘 2 — 고를 것을 안 주는 것이 이 모드의 뜻이고, 2 는
    #      하네스가 정한 값이다. 검수 자체는 두 모드 모두 켠다.
    text = _replace_block(
        text, "art_qa", f"{{enabled: true, regen_max: {int(qa_regen_max)}}}")
    if head_ratio in ("sd", "md", "ld"):
        text = _replace_block(text, "head_ratio", head_ratio)
    if genre.strip():
        # 값에 콜론·따옴표가 들어와도 YAML 이 안 깨지게 통째로 인용한다.
        safe = genre.strip().replace('"', "'")
        text = _replace_block(text, "genre", f'"{safe}"')

    # 8. 세로 스크롤 연출 — "웹툰"을 고른 실행에서만 켠다.
    #
    #    · vertical_link — 같은 장소에서 붙어 있는 두 컷의 배경을 위에서 아래로
    #      이어 그린다. 무대는 그대로 두고 카메라만 내려가는 자리라, 스크롤
    #      자체가 카메라가 된다. 직전 컷이 첨부되는 조건(S+)에서만 뜻이 있는데
    #      제품이 쓰는 조건이 마침 S+ 다.
    #    · gap_ratio — 컷 사이 여백을 몇 px 로 그릴지. 하네스 기본값
    #      (0 / 56 / 208 / 496px @800폭)은 세로 스크롤 작법이 쓰는 눈금보다
    #      좁다. 특히 낙차(3)가 폰 화면 하나를 못 채워서 "조금 넓은 여백"이
    #      된다. 아래 값은 0 / 128 / 256 / 720px 로, 각각 작법이 말하는
    #      빠른 동작(100~150) · 감정(200~300) · 낙차(600~800) 범위에 든다.
    #    · stitch_gaps — 위 gap_ratio·light_width 를 **장과 장 사이 이어붙이기
    #      (episode.stitch)에도 실제로 적용**한다. 이게 없으면 config 에 값만
    #      채워질 뿐 정작 최종 이미지는 장끼리 무조건 틈 없이 붙는다 — 2026-08-23
    #      감사에서 나온 값이 죽은 채로 있던 자리(이슈 #110).
    #
    #    "빠르게"(scene 모드, 개수로 3컷씩 고정)에서는 셋 다 안 켠다 — 컷 사이
    #    여백도 배경 연결도 한 캔버스 안에서 모델이 정하는 구조라 코드가 넣을
    #    자리가 없다.
    if mode == "webtoon":
        text = _replace_block(text, "vertical_link", "true")
        text = re.sub(r"(?m)^  gap_ratio:.*$",
                      "  gap_ratio: {0: 0.0, 1: 0.16, 2: 0.32, 3: 0.90}",
                      text, count=1)
        text = re.sub(r"(?m)^  stitch_gaps:.*$", "  stitch_gaps: true", text, count=1)
        # 9. 묶기는 **컷의 무게**가 정한다 (scene.grouping: weight).
        #
        #    한 번은 이걸 썼다가 rhythm 으로 되돌린 적이 있다 — 실측해 보니
        #    콘티가 weight 를 거의 안 써서 한 화 12컷이 전부 normal 로 나오고,
        #    weight 모드는 원래 normal 도 "혼자 한 장"으로 다뤄서 결과가 컷
        #    모드와 같아졌다(이미지 12번, "한 장에 3컷"(fixed)보다 세 배 비쌈).
        #
        #    그런데 rhythm(+fit_to_canvas)도 실측해 보니 같은 증상이었다 —
        #    콘티가 scene_break 로 4/4/4 를 나눠 줘도, 캔버스 세로 예산(9:16)이
        #    tall·impact 컷 **하나만으로 거의 다 차서** 옆에 아무것도 못
        #    붙였다(2026-08-27 실측: 12컷 중 11장이 1컷). "무거운 컷만 혼자,
        #    나머지는 합쳐서"가 원래 바라던 결과인데, 리듬+캔버스 예산은 그걸
        #    흉내만 내고 실제로는 못 만들고 있었다.
        #
        #    그래서 weight 로 돌아오되, 문제였던 지점(normal 도 혼자 한 장)만
        #    새 하네스 옵션으로 끈다 — weight_combine_normal(2026-08-27 추가,
        #    scenegen.group_by_weight). full(통컷·bleed·impact)만 그대로 혼자
        #    한 장이고, 나머지는(light 는 물론 normal 도) 붙는다. 한 장에
        #    묶는 상한(max_light_per_scene)은 하네스 기본(3)을 그대로 쓴다 —
        #    넷을 넘기면 인물이 작아진다는 이유가 여기서도 똑같이 적용된다.
        text = re.sub(r"(?m)^  grouping:.*$", "  grouping: weight", text, count=1)
        text = re.sub(r"(?m)^  weight_combine_normal:.*$",
                      "  weight_combine_normal: true", text, count=1)

    out = job_dir / "config.yaml"
    out.write_text(text, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# 입력 → 캐릭터 JSON
# --------------------------------------------------------------------------- #

FIELD_KEYS = ("나이", "성별", "직업", "성격", "말투", "과거", "관계", "약점")

# 한 사람을 여러 각도로 찍은 사진을 몇 장까지 받을 것인가.
#
# 여러 장을 받는 이유는 하나다 — 한 장으로는 늘 안 보이는 칸이 남는다(하의,
# 뒤통수, 신발). 다른 각도가 그 칸을 채운다. 반대로 장수를 늘릴수록 첨부가
# 커져 LOOK 호출이 비싸지고, 서로 어긋나는 칸도 같이 늘어난다. 4장이면
# 앞·옆·전신·얼굴을 덮는다.
MAX_PHOTOS = 4


def job_photos(job_dir: Path) -> list:
    """이 작업에 올라온 사진. 순서가 곧 LOOK 에 붙는 순서다.

    옛 job 은 photo.png 하나뿐이고 새 job 은 photo1.png… 를 쓴다. 둘 다 읽는다 —
    예전 작업의 결과 화면이 그대로 열려야 한다.
    """
    out = [job_dir / f"photo{i}.png" for i in range(1, MAX_PHOTOS + 1)]
    out = [p for p in out if p.exists()]
    legacy = job_dir / "photo.png"
    if legacy.exists():
        out.insert(0, legacy)
    return out


def world_presets() -> list[dict[str, str]]:
    """세계관 프리셋 목록. story-harness 의 worlds.json 이 유일한 출처다.

    여기서 목록을 따로 들고 있으면 두 곳이 갈라진다 — story.py 는 실제로
    `world.preset` 키를 worlds.json 에서 찾아 본문으로 바꾸므로(world_preset_text),
    화면이 보여 준 키가 거기 없으면 그 실행은 통째로 멈춘다.
    """
    try:
        data = json.loads((STORY / "worlds.json").read_text(encoding="utf-8"))
    except Exception:                                          # noqa: BLE001
        return []
    out = []
    for key, v in (data.get("presets") or {}).items():
        if not isinstance(v, dict):
            continue
        text = str(v.get("text") or "").strip()
        out.append({
            "key": key,
            "label": str(v.get("label") or key),
            # 고르면 무엇이 들어가는지 화면에서 바로 보여 준다. 고르고 나서야
            # 아는 것보다 고르기 전에 아는 편이 낫다.
            "text": text,
        })
    return out


def _drop_job_photos(job) -> None:
    """시트가 승인되면 올린 사진을 지운다.

    화면이 "올린 사진은 캐릭터를 만드는 데만 씁니다" 라고 말하는데 지우는
    코드가 없어서, jobs/<job_id>/photoN.png 가 영영 남아 있었다. 남아 있는
    동안은 /api/jobs/<id>/photo 로 꺼낼 수도 있었다.

    character.json 의 경로는 그대로 둔다 — 그 파일을 다시 여는 단계가 없고
    (read_character 는 이야기 단계에서 한 번만 부른다), 지우면 옛 job 을 다시
    열었을 때 모양이 달라진다. 파일이 없어지는 것으로 충분하다.
    """
    gone = 0
    for path in job_photos(job.dir):
        try:
            path.unlink()
            gone += 1
        except OSError:
            pass                        # 못 지워도 만드는 것 자체는 안 막는다
    if gone:
        # has_photo 를 같이 내린다 — 파일만 지우고 표시를 남기면 화면이
        # "사진이 있다" 고 믿고 빈 자리를 그린다.
        job.has_photo = False
        job.note(f"올린 사진 {gone}장을 지웠습니다 — 시트가 나왔으니 더 쓰지 않습니다")
        job.save()


def write_character(job_dir: Path, form: dict[str, Any]) -> Path:
    """폼 입력을 story.py 가 읽는 캐릭터 파일로.

    빈 칸은 **빈 칸으로 둔다.** 코드가 기본값을 채우면 작가가 준 것과 코드가
    지어낸 것이 섞이고, 그건 하네스가 하지 않기로 한 일이다(read_character).
    """
    fields = {k: str(form.get("fields", {}).get(k, "")).strip() for k in FIELD_KEYS}
    doc: dict[str, Any] = {
        "name": str(form.get("name", "")).strip(),
        "character": str(form.get("character", "")).strip(),
        "fields": {k: v for k, v in fields.items() if v},
        "genre": str(form.get("genre", "")).strip(),
        # 프리셋과 자유 입력은 같이 올 수 있다. story.py 는 자유 입력이 있으면
        # 그쪽을 쓰고, 비어 있을 때만 프리셋 본문을 채운다(read_character) —
        # 골라 두고 직접 고쳐 쓴 사람의 글이 프리셋에 덮이지 않게 하는 순서다.
        "world": {"preset": str(form.get("world_preset", "")).strip(),
                  "text": str(form.get("world", "")).strip()},
        "story": str(form.get("story", "")).strip(),
    }
    # 사진은 여러 장일 수 있다. story.read_character 의 photo 는 문자열도
    # 배열도 받으므로, 한 장이면 예전처럼 문자열로 넘긴다 — 옛 job 폴더
    # (photo.png 하나만 있는)도 그대로 열린다.
    shots = job_photos(job_dir)
    if shots:
        doc["photo"] = str(shots[0]) if len(shots) == 1 else [str(p) for p in shots]
        note = str(form.get("photo_note", "")).strip()
        if note:
            doc["photo_note"] = note

    path = job_dir / "character.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Job
# --------------------------------------------------------------------------- #

@dataclass
class Job:
    id: str
    form: dict[str, Any]
    dir: Path
    style: str
    preview: bool
    has_photo: bool

    # 이어 만들기 (#72). episode 가 2 이상이면 **이야기·시트 단계를 건너뛰고**
    # 콘티부터 시작한다 — 인물과 세계는 1화에서 이미 정해졌고, 다시 만들면
    # 그게 흔들린다. run_id 도 새로 파지 않고 이 값을 그대로 쓴다.
    episode: int = 1

    # 이어 그리기 — 앞 3컷을 미리보기로 본 뒤 "다음 장면도 볼까요?" 를 누르면
    # 여기에 다음 시작 컷 번호가 담긴다(4, 7, 10 …). 0 이면 보통 실행이다.
    # 콘티·이야기·시트는 이미 있으므로 그림과 이어 붙이기만 다시 돈다.
    cut_from: int = 0

    # queued | running | awaiting_story_approval | awaiting_board_approval |
    # awaiting_sheet_approval |
    # done | error | cancelled
    status: str = "queued"
    run_id: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None

    stages: list[dict[str, Any]] = field(default_factory=list)
    stage_i: int = 0
    log: list[str] = field(default_factory=list)

    art_total: int = 0
    art_done: int = 0
    art_seconds: list[float] = field(default_factory=list)
    ready_cuts: list[int] = field(default_factory=list)

    # 이미지 모델이 "못 그리겠다"고 거절한 적이 있는가. 거절은 실패와 다르다 —
    # 다시 시도해도 같은 답이 오고, 고칠 사람은 우리가 아니라 사용자다.
    # (예: 캐릭터 나이를 13세로 적으면 미성년 묘사로 보고 거절할 수 있다.)
    saw_refusal: bool = False

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _cancel: bool = field(default=False, repr=False)

    # awaiting_sheet_approval 동안 execute() 를 세워 두는 신호. state.json 에는
    # 안 남는다 — 서버가 재시작되면 execute() 를 돌리던 스레드 자체가 죽어서
    # 이 Event 를 아무도 못 깨우고, "running" 이 재시작 후 error 로 바뀌는 것과
    # 같은 이유로 load() 에서 error 로 바꾼다.
    sheet_approval: threading.Event = field(default_factory=threading.Event, repr=False)
    sheet_decision: str = field(default="", repr=False)
    sheet_edit_fields: dict[str, Any] | None = field(default=None, repr=False)
    sheet_fixes: list[str] = field(default_factory=list, repr=False)

    def decide_sheet(self, decision: str, fields: dict[str, Any] | None = None,
                     fixes: list[str] | None = None) -> None:
        """승인 화면의 '이대로 진행'/'수정 후 다시 만들기' 클릭이 여기로 온다.

        fields 는 사람이 approvalSheet 화면에서 고친 p1.json 일부 필드(선택) —
        retry 일 때만 의미가 있다. approve 에 fields 가 오면 무시한다 (이미
        채택한 그림은 텍스트를 나중에 고쳐도 안 바뀌므로, 고친 걸 반영하려면
        다시 그려야 한다 — retry 경로로만 받는다).

        fixes 는 고른 항목·적은 말에서 뽑은 지시문(sheet_corrections)이다.
        fields 와 함께 오지만 가는 곳이 다르다 — fields 는 사양 자체를 바꾸고,
        fixes 는 "같은 사양을 어느 쪽으로 다시 읽어라"를 프롬프트 끝에 붙인다.
        일반 모드에는 fields 폼이 없으므로 그 모드에서는 fixes 만 간다.
        """
        with self._lock:
            self.sheet_decision = decision
            self.sheet_edit_fields = fields or None
            self.sheet_fixes = list(fixes or [])
        self.sheet_approval.set()

    # awaiting_story_approval 용 — sheet_approval 과 같은 이유, 같은 방식.
    # 스토리 단계가 STATUS_HUMAN(게이트 재시도 소진)으로 끝났을 때만 켜진다.
    story_approval: threading.Event = field(default_factory=threading.Event, repr=False)
    story_decision: str = field(default="", repr=False)
    story_note: str = field(default="", repr=False)

    def decide_story(self, decision: str, note: str = "") -> None:
        """스토리 확인 화면의 '이대로 진행'/'다시 만들기' 클릭이 여기로 온다."""
        with self._lock:
            self.story_decision = decision
            self.story_note = note
        self.story_approval.set()

    # awaiting_board_approval 용 — story_approval 과 같은 이유, 같은 방식.
    # 콘티(webtoon.py, W4~W8) 단계가 STATUS_HUMAN 으로 끝났을 때만 켜진다.
    board_approval: threading.Event = field(default_factory=threading.Event, repr=False)
    board_decision: str = field(default="", repr=False)
    board_note: str = field(default="", repr=False)

    def decide_board(self, decision: str, note: str = "") -> None:
        """콘티 확인 화면의 '이대로 진행'/'다시 만들기' 클릭이 여기로 온다."""
        with self._lock:
            self.board_decision = decision
            self.board_note = note
        self.board_approval.set()

    # awaiting_artqa_approval 용 — 그림이 다 나온 뒤, 끝났다고 하기 전에 한 번.
    #
    # 앞의 셋과 성격이 다르다. 여기는 **되돌아갈 단계가 없다** — 그림은 이미
    # 다 그려졌고 다시 그리기는 장 단위로(결과 화면의 regen) 하는 일이다.
    # 그래서 결정이 approve 하나뿐이고, 이 자리가 하는 일은 "그림 QA 가 무엇을
    # 잡았고 무엇을 못 고쳤는지"를 끝나기 전에 반드시 한 번 보게 하는 것이다.
    # 일반 모드는 이 자리를 안 세우고 결과 화면의 노트로만 알린다.
    artqa_approval: threading.Event = field(default_factory=threading.Event, repr=False)

    def decide_artqa(self) -> None:
        """그림 검수 화면의 '확인했습니다' 클릭이 여기로 온다."""
        self.artqa_approval.set()

    # ---- 상태 -------------------------------------------------------------- #

    @property
    def is_next(self) -> bool:
        """이어 만들기인가 (2화 이상)."""
        return int(self.episode) > 1

    @property
    def is_more(self) -> bool:
        """이어 그리기인가 (같은 화의 다음 컷들)."""
        return int(self.cut_from) > 0

    def build_stages(self) -> None:
        self.stages = []
        webtoon = layout_mode(self.form) == "webtoon"
        if self.is_more:
            specs = [sp for sp in STAGE_SPEC if sp["key"] in MORE_STAGE_KEYS]
        elif self.is_next:
            specs = [sp for sp in STAGE_SPEC if sp["key"] in NEXT_STAGE_KEYS]
        else:
            specs = STAGE_SPEC
        for spec in specs:
            steps = []
            for key, label in spec["steps"]:
                state = SKIP if (key == "look" and not self.has_photo) else TODO
                # 컷 모드에는 "묶기" 단계가 없다 — 컷 하나가 곧 한 장이다.
                if key == "group" and webtoon:
                    label = "컷 무게대로 묶기"
                steps.append({"key": key, "label": label, "state": state})
            desc = spec["desc"]
            if spec["key"] == "board":
                # "1화" 가 박혀 있으면 3화를 만들 때도 1화라고 적힌다.
                desc = f"{int(self.episode)}화를 컷으로 나누고 대사를 붙입니다"
                for st in steps:
                    if st["key"] == "episode":
                        st["label"] = f"{int(self.episode)}화 설계"
                    # 큰 줄거리(arc)는 1화에서 이미 세웠다 — 이어 만들 때는
                    # arcs.json 을 그대로 재사용하므로 도는 단계가 아니다.
                    if st["key"] == "arc" and self.is_next:
                        st["state"] = SKIP
            if webtoon and spec["key"] == "art":
                desc = "무거운 컷은 한 장씩, 가벼운 컷은 묶어서 그립니다"
            elif webtoon and spec["key"] == "bind":
                desc = "컷을 콘티가 정한 여백대로 세로로 이어 붙입니다"
            self.stages.append({
                "key": spec["key"], "title": spec["title"], "desc": desc,
                "state": TODO, "note": "", "steps": steps,
                "started_at": None, "seconds": None,
            })

    @property
    def stage(self) -> dict[str, Any]:
        return self.stages[self.stage_i]

    def _step(self, key: str) -> dict[str, Any] | None:
        for s in self.stage["steps"]:
            if s["key"] == key:
                return s
        return None

    def mark(self, key: str, state: str) -> None:
        """이 단계의 하위 항목 하나를 표시하고, 그 앞의 것들은 끝난 것으로 본다.

        앞 항목을 같이 닫는 이유: 하네스가 모든 전환을 찍지는 않는다. P2 가
        시작됐다는 줄은 없고 P3 결과 줄만 있다. 뒤엣것이 보였다면 앞엣것은
        끝난 것이 맞다.
        """
        steps = self.stage["steps"]
        idx = next((i for i, s in enumerate(steps) if s["key"] == key), None)
        if idx is None:
            return
        with self._lock:
            for s in steps[:idx]:
                if s["state"] in (TODO, ACTIVE):
                    s["state"] = DONE
            steps[idx]["state"] = state

    def note(self, text: str) -> None:
        with self._lock:
            self.stage["note"] = text

    def add_log(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            if len(self.log) > 400:
                del self.log[:100]

    def stage_seconds(self) -> float:
        """단계에 실제로 쓴 시간의 합. 총 경과의 예비 경로다."""
        return sum(float(st.get("seconds") or 0) for st in self.stages)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            if self.started_at:
                elapsed = (self.finished_at or now) - self.started_at
            else:
                # 지난 실행에서 복원했는데 시작 시각이 없는 경우. 0:00 으로
                # 보여주면 "안 걸렸다"로 읽히므로 단계 시간의 합으로 대신한다.
                elapsed = self.stage_seconds()
            art = None
            if self.art_total:
                avg = (sum(self.art_seconds) / len(self.art_seconds)
                       if self.art_seconds else None)
                left = self.art_total - self.art_done
                art = {
                    "done": self.art_done, "total": self.art_total,
                    "eta_sec": round(avg * left) if avg and left > 0 else None,
                }
            return {
                "id": self.id,
                "status": self.status,
                "run_id": self.run_id,
                "error": self.error,
                "elapsed": round(elapsed, 1),
                "stage_index": self.stage_i,
                "stages": json.loads(json.dumps(self.stages, ensure_ascii=False)),
                "art": art,
                "ready_cuts": list(self.ready_cuts),
                "log": self.log[-60:],
                "style": self.style,
                "style_label": STYLES.get(self.style, self.style),
                "preview": self.preview,
                "has_photo": self.has_photo,
                # 거절이 있었을 때만 파일을 읽는다. 매 폴링(1초)마다 읽으면
                # 아무 일도 없는 대부분의 run 에서 헛일이 된다.
                "refusals": (read_refusals(self.run_id, self.episode)
                             if self.saw_refusal and self.run_id else []),
                "episode": int(self.episode),
                "is_next": self.is_next,
                "is_more": self.is_more,
                "cut_from": int(self.cut_from),
                # 화면이 어느 검수 화면을 어떤 깊이로 그릴지 정하는 근거.
                # 폼(form)에서 다시 읽으므로 새로고침해도 같은 값이 나온다.
                "expert": expert_mode(self.form),
                # 그림 검수 확인 화면이 쓸 값. 그 단계에서만 읽는다 —
                # 매 폴링(0.8초)마다 art_qa.json 을 여는 것은 헛일이다.
                "art_qa": (art_qa_summary(self.run_id, self.episode)
                           if self.status == "awaiting_artqa_approval" and self.run_id
                           else None),
                # 확인 화면이 **무엇을** 확인할지. 그 단계에서만 읽는다 —
                # 매 폴링(0.8초)마다 run 폴더를 뒤지는 것은 헛일이다.
                #
                # 이것이 없던 동안 스토리·콘티 확인 화면은 "이대로 진행할까요?"
                # 만 묻고 정작 이야기를 안 보여줬다. 사람은 게이트가 무엇에
                # 걸렸는지만 읽고 찍어서 눌러야 했다.
                "story_preview": (story_preview(self.run_id)
                                  if self.status == "awaiting_story_approval"
                                  and self.run_id else None),
                "board_preview": (board_preview(self.run_id, self.episode)
                                  if self.status == "awaiting_board_approval"
                                  and self.run_id else None),
            }

    # ---- 저장 · 복원 -------------------------------------------------------- #
    #
    # 서버를 껐다 켜면 만들어 둔 웹툰을 못 보게 되면 안 된다. 끝난 작업은
    # state.json 으로 남기고, 다음 실행이 그것을 읽어 결과 화면을 다시 연다.
    # (돌던 중이었다면 되살리지 않는다 — 하위 프로세스는 서버와 함께 죽었다.)

    def save(self) -> None:
        try:
            (self.dir / "state.json").write_text(json.dumps({
                "id": self.id, "status": self.status, "run_id": self.run_id,
                "error": self.error, "style": self.style, "preview": self.preview,
                "has_photo": self.has_photo, "form": self.form,
                "episode": int(self.episode),
                "stages": self.stages, "stage_i": self.stage_i,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "ready_cuts": self.ready_cuts,
                # 재시작 후에도 결과 화면의 거절 표시가 남아야 한다 — 이 값이
                # 없으면 snapshot() 이 refusals.jsonl 을 아예 안 읽는다.
                "saw_refusal": self.saw_refusal,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass                      # 기록을 못 남겨도 이번 실행은 살아 있다

    @classmethod
    def load(cls, path: Path) -> "Job | None":
        try:
            d = json.loads((path / "state.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        # 그림 검수 확인만 남은 채로 서버가 꺼졌으면 그것은 실패가 아니다 —
        # episode.png 는 이미 다 나와 있고 남은 것은 사람이 한 번 보는 일뿐이다.
        # 이것을 error 로 바꾸면 다 만든 웹툰이 "끊겼습니다"로 사라진다.
        # 못 본 검수 결과는 결과 화면의 노트(art_qa.json)에 그대로 남는다.
        if d.get("status") == "awaiting_artqa_approval":
            d["status"] = "done"
        if d.get("status") in ("running", "awaiting_sheet_approval",
                               "awaiting_story_approval", "awaiting_board_approval"):
            d["status"] = "error"
            d["error"] = "서버가 다시 시작되어 이 작업은 끊겼습니다."
        job = cls(id=d["id"], form=d.get("form") or {}, dir=path,
                  style=d.get("style") or "webtoon", preview=bool(d.get("preview")),
                  has_photo=bool(d.get("has_photo")),
                  # 회차 칸이 없는 옛 state.json 은 1화다.
                  episode=int(d.get("episode") or 1))
        job.status = d.get("status") or "error"
        job.run_id = d.get("run_id")
        job.error = d.get("error")
        job.stages = d.get("stages") or []
        job.stage_i = int(d.get("stage_i") or 0)
        job.started_at = d.get("started_at")
        job.finished_at = d.get("finished_at")
        job.ready_cuts = list(d.get("ready_cuts") or [])
        job.saw_refusal = bool(d.get("saw_refusal"))
        if not job.stages:
            job.build_stages()
        return job

    # ---- 실행 -------------------------------------------------------------- #

    def cancel(self) -> None:
        self._cancel = True
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        # awaiting_*_approval 이면 프로세스가 없다 — execute() 가 해당
        # *_approval.wait() 에 걸려 있으므로 깨워야 _cancel 을 보고 멈춘다.
        self.sheet_approval.set()
        self.story_approval.set()
        self.board_approval.set()
        self.artqa_approval.set()

    def _env(self) -> dict[str, str]:
        env = dict(os.environ)
        # 한글이 깨지지 않게. 콘솔(cp949)로 나가는 것이 아니라 파이프로 받는다.
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        # story.py --charsheet 가 그림체 문구를 여기서 읽는다. job 폴더를
        # 가리켜야 시트와 컷이 같은 그림체를 본다.
        env["WEBTOON_HARNESS_DIR"] = str(self.dir)
        # beat 게이트를 느슨하게 — 하네스 기본은 엄격(beat 의 동사가 컷에
        # 문자열 그대로 나와야 통과)이라, 같은 장면을 다른 낱말로 쓰면 걸린다.
        # 그러면 재시도가 소진되고 컷이 한 개도 저장되지 않아 **제품이 한 편도
        # 못 만든다.** 하네스 기본값은 예전 run 재현을 위해 그대로 두고 제품에서만
        # 켠다. 사람이 .env 에 직접 값을 정해 뒀으면 그 뜻을 존중해 덮지 않는다.
        env.setdefault("BEAT_GATE_LOOSE", "1")
        # 무게 묶음(웹툰 연출)은 컷 대부분이 자기 장을 가져서 한 편이 세로
        # 33,000px 을 넘는다 — 하네스 기본 상한(30,000px)이면 다 그려 놓고
        # 합치기에서 죽는다. 12컷 × 2752px 에 여유를 둔 값.
        env.setdefault("EPISODE_MAX_HEIGHT", "40000")
        return env

    def _run(self, cmd: list[str], cwd: Path, on_line: Callable[[str], None]) -> int:
        display = " ".join(["python", *cmd])
        self.add_log(f"$ {display}")
        with (self.dir / "log.txt").open("a", encoding="utf-8") as fh:
            fh.write(f"\n$ {display}\n")
        proc = subprocess.Popen(
            [sys.executable, "-u", *cmd], cwd=str(cwd), env=self._env(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self._proc = proc
        with (self.dir / "log.txt").open("a", encoding="utf-8") as fh:
            for raw in proc.stdout:                     # type: ignore[union-attr]
                line = raw.rstrip("\n")
                fh.write(line + "\n")
                if line.strip():
                    self.add_log(line)
                    on_line(line)
        self._proc = None
        return proc.wait()


# --------------------------------------------------------------------------- #
# stdout 읽기 — 단계마다 무엇을 신호로 보는가
# --------------------------------------------------------------------------- #

RE_SHEET_MADE = re.compile(r"^\s+(\w+) 후보 (\d+) ·")
RE_JOB = re.compile(r"^\[(\d+)/(\d+)\]")
# Scene 모드는 scene3_c1.png, 컷 모드는 cut3_c1.png 로 떨어진다. MODE 를
# 되돌려도 진행 표시가 같이 살아 있어야 하므로 둘 다 받는다.
RE_OK_UNIT = re.compile(r"OK \(([\d.]+)s\).*?(?:cut|scene)(\d+)_c\d+\.png")
# "[scene_gen] 컷 12개 → Scene 4개 (묶음 3, 3, 3, 3 · 3개씩 고정)"
RE_GROUPED = re.compile(r"컷 (\d+)개 → Scene (\d+)개 \(묶음 ([\d,\s+]+?)\s*·")


def _story_line(job: Job, line: str) -> None:
    if "LOOK: 사진" in line:
        job.mark("look", ACTIVE)
        job.note("올려주신 사진에서 머리·눈·체형·옷을 읽는 중")
    elif line.lstrip().startswith("SEED:") or line.lstrip().startswith("템플릿:"):
        job.mark("seed", DONE)
        job.mark("card", ACTIVE)
        job.note("캐릭터 카드를 쓰는 중 — 1초 안에 손가락을 멈추게 하는 한 장")
    elif "카드 게이트 실패" in line:
        job.note("캐릭터 카드가 기준에 걸렸습니다 — 다시 쓰는 중")
    elif line.lstrip().startswith("P3 ["):
        job.mark("judge", DONE)
        job.mark("scene", ACTIVE)
        job.note("첫 장면을 쓰는 중")
    elif "-> P1 재실행" in line or "-> P2 재실행" in line:
        job.mark("premise", ACTIVE)
        job.note("구조 검수에서 되돌아왔습니다 — 다시 쓰는 중")
    elif "장면 점검 통과" in line:
        job.mark("scene", DONE)
        job.note(line.strip())
    elif "장면 점검 걸림" in line:
        job.note("장면 점검에 걸렸습니다 — 고쳐 쓰는 중")


def _sheet_line(job: Job, line: str) -> None:
    if "사양을 만들었습니다" in line or "사양이 이미 있습니다" in line:
        job.mark("spec", DONE)
        job.mark("draw", ACTIVE)
        job.note("4면도 · 표정 · 디테일 · 색을 한 장에 그리는 중 (1~2분)")
    elif "캐릭터 시트 ·" in line:
        job.mark("spec", DONE)
        job.mark("draw", ACTIVE)
    elif RE_SHEET_MADE.match(line):
        job.mark("draw", DONE)
    elif "자동 채택" in line:
        job.mark("pick", DONE)
        job.note("기준 시트 확정 — 이제 모든 컷이 이 얼굴을 따라갑니다")


def _board_line(job: Job, line: str) -> None:
    if "4단계 통과" in line:
        job.mark("arc", DONE)
        job.mark("episode", ACTIVE)
        job.note("1화에 무엇을 담을지 설계하는 중")
    elif "화 검사 통과" in line:
        job.mark("check", DONE)
        job.mark("cuts", ACTIVE)
        job.note("장면을 컷으로 나누고 대사를 붙이는 중")
    elif "형식 게이트 실패" in line or "검사 불합격" in line:
        job.mark("check", ACTIVE)
        job.note("1화 설계가 검사에 걸렸습니다 — 다시 쓰는 중")
    elif "화 통과 ·" in line:
        job.mark("cuts", DONE)
        job.note(line.strip().split("·", 1)[-1].strip())


def _art_line(job: Job, line: str) -> None:
    if line.startswith("[scene_gen]") or line.startswith("[prompt_gen]"):
        done = "완료" in line or "캐시" in line
        job.mark("prompt", DONE if done else ACTIVE)
        if not done:
            job.note("컷 서술을 그림이 알아듣는 말로 옮기는 중")
        m = RE_GROUPED.search(line)
        if m:
            # "묶음 3+3+3+3" — 마지막 묶음만 작아질 수 있으므로 그대로 보여준다.
            job.mark("group", DONE)
            job.note(f"컷 {m.group(1)}개를 {m.group(2)}장으로 묶었습니다 "
                     f"(묶음 {m.group(3)})")
        elif done:
            job.mark("group", ACTIVE)
        return
    m = RE_JOB.match(line)
    if m:
        i, n = int(m.group(1)), int(m.group(2))
        job.mark("group", DONE)
        job.mark("draw", ACTIVE)
        with job._lock:
            job.art_total = n
        job.note(f"{n}장 중 {i}번째 장을 그리는 중 (한 장에 {CUTS_PER_SHEET}컷)")
        return
    m = RE_OK_UNIT.search(line)
    if m:
        secs, unit = float(m.group(1)), int(m.group(2))
        with job._lock:
            job.art_seconds.append(secs)
            job.art_done += 1
            if unit not in job.ready_cuts:
                job.ready_cuts.append(unit)
                job.ready_cuts.sort()
    elif line.lstrip().startswith("↳ 모델이 거절했습니다"):
        # 안전 필터 거절. 재시도해도 같은 답이 오므로 "다시 시도하는 중"이라고
        # 하면 거짓말이 된다. 사유는 다음 줄들로 이어져 오고, 원문 전체는
        # 하네스가 refusals.jsonl 에 남긴다 — 그건 결과 화면에서 읽는다.
        job.note("모델이 이 장을 그리기를 거절했습니다 — 사유를 확인해 주세요")
        with job._lock:
            job.saw_refusal = True
    elif line.lstrip().startswith("실패 (시도"):
        job.note("한 장이 실패했습니다 — 다시 시도하는 중")


def _bind_line(job: Job, line: str) -> None:
    if line.startswith("episode.png"):
        job.mark("strip", DONE)
        job.note(line.strip())
    elif "이어 붙이지 못했습니다" in line:
        # 합치기 실패 사유는 이 [경고] 한 줄에만 있다 ("세로 33,024px 입니다
        # (상한 …)" 등). 안 옮기면 화면에는 "잇지 못했습니다"만 남고, 고칠
        # 단서는 log.txt 를 열어야 보인다.
        job.note(line.strip().removeprefix("[경고]").strip())


# --------------------------------------------------------------------------- #
# 파이프라인
# --------------------------------------------------------------------------- #

# story.py/webtoon.py 의 STATUS_HUMAN 과 같은 문자열. 두 CLI 모두 게이트가
# 소진돼 사람 확인이 필요한 상태에서도 프로세스 종료 코드는 0 이라(각자의
# main() 이 항상 return 0) exit code 만으로는 못 잡고, 각 단계가 남긴
# meta.json 의 status 를 직접 읽어야 한다 — make_episode.py 의 stage_status()
# 와 같은 이유, 같은 방식.
STATUS_HUMAN = "사람확인필요"


def _meta_status(meta_path: Path) -> tuple[str | None, str]:
    """단계가 남긴 meta.json 의 (status, note). 없거나 못 읽으면 (None, "")."""
    if not meta_path.exists():
        return None, ""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, ""
    return data.get("status"), data.get("note") or ""


def _latest_run(before: set[str]) -> str | None:
    runs = STORY / "runs"
    fresh = [d for d in runs.iterdir()
             if d.is_dir() and d.name not in before and (d / "p1.json").exists()]
    if not fresh:
        return None
    return max(fresh, key=lambda d: d.stat().st_mtime).name


def _enter(job: Job, index: int) -> None:
    with job._lock:
        job.stage_i = index
        job.stage["state"] = ACTIVE
        job.stage["started_at"] = time.time()


def _leave(job: Job, ok: bool = True) -> None:
    with job._lock:
        st = job.stage
        st["state"] = DONE if ok else ERROR
        if st["started_at"]:
            st["seconds"] = round(time.time() - st["started_at"], 1)
        if ok:
            for s in st["steps"]:
                if s["state"] in (TODO, ACTIVE):
                    s["state"] = DONE


class Failed(RuntimeError):
    pass


# 승인 화면에서 사람이 직접 고칠 수 있게 여는 p1.json 필드. 여기 없는 필드
# (color_palette, expression_set 등)는 지금은 화면에 안 보여준다 — appearance_en
# 과 design_details 가 "아예 다른 사람이 됐다"/"소품이 컷마다 바뀐다" 피드백의
# 직접 원인이라 이 둘 + name 만으로 시작한다.
SHEET_EDIT_FIELDS = ("name", "appearance_en", "design_details")


def sheet_fields(run_id: str) -> dict[str, Any]:
    """승인 화면 수정 폼에 채워 줄 현재 p1.json 값."""
    p1 = _read_json(STORY / "runs" / run_id, "p1.json")
    return {
        "name": str(p1.get("name") or ""),
        "appearance_en": str(p1.get("appearance_en") or ""),
        "design_details": [str(d) for d in (p1.get("design_details") or []) if str(d or "").strip()],
    }


def _apply_sheet_edits(run_dir: Path, fields: dict[str, Any]) -> None:
    """사람이 고친 필드를 p1.json 에 그대로 반영한다 (화이트리스트 밖은 무시).

    이 다음에 charsheet 폴더를 지우고 다시 뽑으면, 새 시트는 이 고친 값으로
    그려진다 — story.py 의 --charsheet 는 p1.json 을 읽기만 하고 새로 쓰지
    않으므로(3236행에서 한 번만 씀), 여기서 먼저 써 둬야 반영된다.
    """
    p1_path = run_dir / "p1.json"
    p1 = _read_json(run_dir, "p1.json")
    if not p1:
        return
    if "name" in fields:
        name = str(fields.get("name") or "").strip()
        if name:
            p1["name"] = name
    if "appearance_en" in fields:
        text = str(fields.get("appearance_en") or "").strip()
        if text:
            p1["appearance_en"] = text
    if "design_details" in fields:
        raw = fields.get("design_details")
        items = raw if isinstance(raw, list) else str(raw or "").splitlines()
        details = [str(d).strip() for d in items if str(d or "").strip()]
        if details:
            p1["design_details"] = details
    p1_path.write_text(json.dumps(p1, ensure_ascii=False, indent=2), encoding="utf-8")


# ---- 고른 항목 → 다음 시트 프롬프트에 실리는 지시 --------------------------- #
#
# 항목을 고르게 해 놓고 기록만 하면, 사용자는 자기가 말한 것이 반영된다고
# 믿는데 실제로는 같은 사양으로 한 번 더 뽑을 뿐이다 — 다시 만들기가 사실상
# 재추첨이 된다. 일반 모드에는 외형 사양을 고치는 폼이 없으므로, 그 모드에서는
# 이 항목들이 **유일한** 전달 수단이다.
#
# 라벨을 그대로 싣지 않고 지시문으로 옮기는 이유: "얼굴이 원본과 달라요" 는
# 불만이지 지시가 아니다. 이미지 모델에는 무엇을 어느 쪽으로 고치라는 말이
# 가야 한다. 아래 문장은 전부 "지난 판이 이랬다 → 이렇게 하라" 꼴이다.
#
# story.py 의 charsheet 프롬프트는 design_details·expression_set 을 한국어
# 그대로 싣는다. 한글이 막히는 곳은 appearance_en 하나뿐이라
# (gate_charsheet_source), 한국어 지시문이 그대로 나가도 게이트에 안 걸린다.
SHEET_FIX_BY_TAG = {
    "face": "지난 시트는 얼굴이 참고와 달랐다. 얼굴형과 이목구비 배치를 "
            "CHARACTER 설명과 참고 사진 쪽에 더 가깝게 맞춰라.",
    "outfit": "지난 시트는 옷·장신구가 지정과 달랐다. 위 FIXED DESIGN ELEMENTS 의 "
              "복장을 글자 그대로 그리고, 거기 없는 옷을 지어내지 마라.",
    "hair": "지난 시트는 머리 모양이 지정과 달랐다. 머리 길이·묶음 형태·앞머리를 "
            "CHARACTER 설명대로 맞추고, 네 방향과 표정 전부에서 같게 유지하라.",
    "prop": "지난 시트는 고정 소품이 빠지거나 달랐다. 위 FIXED DESIGN ELEMENTS 의 "
            "소품을 하나도 빠뜨리지 말고 전부 그려라.",
    "age": "지난 시트는 나이대가 안 맞았다. 얼굴 비율과 체형을 CHARACTER 설명의 "
           "나이대로 맞춰라.",
    "style": "지난 시트는 화풍이 지정과 달랐다. 맨 아래 STYLE 절의 화풍을 그대로 따르라.",
    "ratio": "지난 시트는 등신 비율이 안 맞았다. 머리와 몸의 비율을 지정된 등신에 "
             "맞추고, 네 방향에서 같은 키·같은 비율로 세워라.",
}

# 프롬프트 꼬리가 무한정 길어지지 않게. 다시 만들기를 여러 번 누르면 지시가
# 쌓이는데(아래 참고), 너무 많아지면 서로 부딪히고 모델이 앞엣것부터 흘린다.
SHEET_FIX_MAX = 8


def sheet_corrections(tags: list[str] | None, text: str = "") -> list[str]:
    """고른 항목과 적은 말 → 시트 프롬프트에 실을 지시 목록."""
    out = [SHEET_FIX_BY_TAG[t] for t in (tags or []) if t in SHEET_FIX_BY_TAG]
    said = (text or "").strip()[:FEEDBACK_TEXT_MAX]
    if said:
        # 사용자가 적은 말은 옮기지 않고 그대로 싣는다 — "망토를 안 그렸어요"
        # 처럼 항목으로는 못 담는 것이 여기 들어오고, 요약하면 그게 사라진다.
        out.append(f"작가가 적은 말 — 그대로 반영하라: {said}")
    return out


def _merge_sheet_corrections(run_dir: Path, fixes: list[str]) -> None:
    """이번에 고른 지시를 p1.json 의 sheet_corrections 에 **쌓는다**.

    덮어쓰지 않고 쌓는 이유: 다시 만들기는 charsheet 폴더를 지우고 p1.json 만
    보고 처음부터 다시 뽑는다. 1판에서 "머리가 다르다"고 해서 고쳐졌더라도 그
    사실은 그림에만 있었고 지워졌으므로, 2판에서 "옷이 다르다"만 남기면 머리
    지시가 사라져 되돌아간다. 같은 문장은 한 번만 남기고(중복 제거) 최근 것을
    뒤에 둔다 — 프롬프트 끝쪽이 더 세게 읽히므로 방금 한 말이 이긴다.
    """
    p1 = _read_json(run_dir, "p1.json")
    if not p1:
        return
    kept = [str(c).strip() for c in (p1.get("sheet_corrections") or [])
            if str(c or "").strip()]
    for line in fixes:
        if line in kept:
            kept.remove(line)          # 다시 말한 것은 맨 뒤로 옮긴다
        kept.append(line)
    p1["sheet_corrections"] = kept[-SHEET_FIX_MAX:]
    (run_dir / "p1.json").write_text(
        json.dumps(p1, ensure_ascii=False, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# 이어 만들기 (#72) — 콘티 · 그림 · 잇기만 돈다
#
# 스토리 하네스는 이미 이 일을 할 줄 안다. `webtoon.py --run <run_id>` 는 회차
# 번호를 인자로 받지 않고 series.json 의 next_no() 를 보고 **다음 화**를 만든다.
# 그래서 1화가 있는 run 에 그대로 부르면 2화가 나오고, 앞 화의 인물·설정·미회수
# 복선(ledger.json)이 자동으로 이어진다. 여기서 새로 만든 것은 그 길을 제품
# 화면에 잇는 것뿐이다.
#
# 못 하는 것: 콘티가 마음에 안 들 때 **같은 회차를 다시 짜는 것.** webtoon.py 는
# 성공하면 series.json 에 그 회차를 적고, 다시 부르면 그 다음 회차를 만든다 —
# 되돌리려면 series.json·ledger.json 을 회차 단위로 롤백해야 하는데 그 길이
# 아직 없다. 그래서 승인 화면은 "이대로 진행" 과 "중단" 만 준다.
# --------------------------------------------------------------------------- #

def _more_cuts_stages(job: "Job", run_id: str, job_dir: Path) -> None:
    """같은 화의 다음 컷들을 그리고 다시 이어 붙인다.

    콘티(webtoon)는 건드리지 않는다 — 이미 있는 것을 그대로 읽어서 지정한
    컷 범위만 run.py 에 넘긴다. 끝나면 episode.png 를 **처음부터 지금까지
    그린 전부**로 다시 굽는다(--cuts 없이 한 번 더 돌리는 것이 아니라,
    run.py 가 이미 있는 장을 재사용하고 이어 붙이기만 다시 한다).
    """
    first = int(job.cut_from)
    # 끝까지 그린다. 예전에는 다음 한 장(3컷)만 그려서 "이어서 보기"를 서너 번
    # 눌러야 했다 — 이제 남은 것 전부를 한 번에 그리고 값도 한 번에 받는다
    # (serve 의 /continue 가 남은 장면 수 × 장당 값으로 계산).
    total = planned_cuts(run_id, job.episode)
    last = total if total >= first else first + CUTS_PER_SHEET - 1

    _enter(job, 0)
    job.note(f"{first}~{last}컷을 그리는 중")
    mode = run_mode(run_id, job.episode)
    art_cmd = ["run.py", "--run-id", run_id, "--episode", str(job.episode),
               "--mode", mode, "-c", CONDITION, "--style", job.style,
               "--config", str(job_dir / "config.yaml"), "--yes",
               "--cuts", f"{first}-{last}"]

    def art_or_bind(line: str) -> None:
        if job.stage_i == 0 and (line.startswith("episode.png")
                                 or line.startswith("완료:")):
            _leave(job)
            _enter(job, 1)
            job.note("그린 장을 순서대로 이어 붙이는 중")

    code = job._run(art_cmd, WEBTOON, art_or_bind)
    if job._cancel:
        raise Failed("취소됨")
    if code != 0:
        raise Failed("다음 장면을 그리지 못했습니다.")
    _leave(job)


def _next_episode_stages(job: "Job", run_id: str, job_dir: Path) -> None:
    # ---- 1. 콘티 ---------------------------------------------------------- #
    _enter(job, 0)
    job.note("앞 화를 읽는 중")
    before = set(made_episodes(run_id))
    board_meta = STORY / "runs" / run_id / "webtoon" / "meta.json"

    cmd = ["webtoon.py", "--run", run_id, "--episodes", "1", "--skip-human-gate"]
    note = str(job.form.get("author_note") or "").strip()
    if note:
        cmd += ["--author-note", note]
    code = job._run(cmd, STORY, lambda ln: _board_line(job, ln))
    if job._cancel:
        raise Failed("취소됨")

    made = sorted(set(made_episodes(run_id)) - before)
    if code != 0 or not made:
        raise Failed("다음 화 콘티를 만들지 못했습니다.")
    # 실제로 몇 화가 나왔는지는 하네스가 정한다(next_no). 화면이 말하는 번호를
    # 여기에 맞춰 둔다 — 어긋나면 그림을 엉뚱한 폴더에서 찾는다.
    job.episode = made[-1]
    # 라벨만 제자리에서 고친다. 예전에는 build_stages() 를 통째로 다시 불렀는데,
    # 그러면 지금 도는 콘티 단계의 state·started_at·하위 표시가 전부 TODO 로
    # 초기화돼서 진행 표시가 리셋되고 걸린 시간이 안 남았다.
    with job._lock:
        for st in job.stages:
            if st["key"] != "board":
                continue
            st["desc"] = f"{int(job.episode)}화를 컷으로 나누고 대사를 붙입니다"
            for s in st["steps"]:
                if s["key"] == "episode":
                    s["label"] = f"{int(job.episode)}화 설계"

    # webtoon.py 의 main() 은 게이트 소진(STATUS_HUMAN)에서도 종료 코드가 0 이다.
    # meta.json 을 직접 읽어야 한다 — story.py 와 같은 사정.
    status, why = _meta_status(board_meta)
    if status == STATUS_HUMAN:
        job.status = "awaiting_board_approval"
        job.note("콘티 단계 게이트 재시도가 소진됐습니다 — 확인해 주세요"
                 + (f" ({why})" if why else ""))
        job.save()
        _await_approval(job, job.board_approval, "콘티(이어 만들기)")
        with job._lock:
            decision = job.board_decision
            job.board_decision = ""
        job.status = "running"
        if job._cancel or decision == "retry":
            # 여기서 "다시" 는 지원하지 않는다 (위 주석 참고) — 멈추고 사람에게
            # 넘긴다. 콘티 자체는 남아 있으므로 나중에 그림만 이어 그릴 수 있다.
            raise Failed("콘티를 확인하고 중단했습니다. "
                         f"{job.episode}화 콘티는 그대로 남아 있습니다.")
    _leave(job)

    # ---- 2·3. 그림 + 이어 붙이기 ------------------------------------------ #
    _enter(job, 1)
    job.note("컷 서술을 옮기는 중")
    mode = LAYOUT_MODES[layout_mode(job.form)]["mode"]
    art_cmd = ["run.py", "--run-id", run_id, "--episode", str(job.episode),
               "--mode", mode, "-c", CONDITION, "--style", job.style,
               "--config", str(job_dir / "config.yaml"), "--yes"]
    if job.preview:
        half = max(CUTS_PER_SHEET, -(-planned_cuts(run_id, job.episode) // 2))
        art_cmd += ["--cuts", f"1-{half}"]

    def art_or_bind(line: str) -> None:
        if job.stage_i == 1 and (line.startswith("episode.png")
                                 or line.startswith("완료:")):
            _leave(job)
            _enter(job, 2)
            job.note("그린 장을 순서대로 이어 붙이는 중")
        if job.stage_i == 1:
            _art_line(job, line)
        else:
            _bind_line(job, line)

    code = job._run(art_cmd, WEBTOON, art_or_bind)
    if job._cancel:
        raise Failed("취소됨")
    if job.stage_i == 1:
        _leave(job)
        _enter(job, 2)
    # 완성본이 있으면 종료 코드보다 그것을 믿는다 — 1화 쪽과 같은 이유
    # (한 장 거절돼도 나머지와 완성본이 있으면 결과 화면으로 간다).
    if not (episode_dir(run_id, job.episode) / "episode.png").exists():
        if code != 0:
            raise Failed("그림 생성이 실패했습니다.")
        raise Failed("그림은 나왔지만 한 편으로 잇지 못했습니다.")
    _leave(job)

    # ---- 4. 그림 검수 확인 (전문 모드) ------------------------------------ #
    #
    # 1화와 같은 자리, 같은 조건. 이어 만들기는 form 을 1화에서 물려받으므로
    # (create_next 의 origin_form) 전문 모드로 시작한 작품은 2화에서도 여기서
    # 멈춘다 — 회차마다 다르게 굴면 사용자가 규칙을 못 읽는다.
    #
    # 앞의 콘티 승인과 달리 여기는 이어 만들기에서도 그대로 쓸 수 있다.
    # 콘티 쪽은 "다시"가 없어서(위 주석) 전문 모드라고 늘 세우면 승인 아니면
    # 중단뿐인 갈림길이 되지만, 이 자리는 원래 확인 하나뿐이다.
    if checkpoints(job.form)["artqa"]:
        qa = art_qa_summary(run_id, job.episode)
        if qa.get("fixed") or qa.get("unresolved"):
            job.status = "awaiting_artqa_approval"
            job.note("그림 검수 결과를 확인해 주세요")
            job.save()
            _await_approval(job, job.artqa_approval, "그림 검수(이어 만들기)")
            # 여기서는 _cancel 을 안 본다 — 1화 쪽과 같은 이유(그 주석 참고).
            job.status = "running"


def execute(job: Job) -> None:
    job.status = "running"
    job.started_at = time.time()
    job.build_stages()
    job_dir = job.dir

    # 어느 단계에서 사람을 세울지는 **시작할 때 한 번** 정한다. 도는 도중에
    # 모드를 바꿔도 이번 실행의 검수 지점은 안 바뀐다 — 이야기는 자동으로
    # 넘어갔는데 콘티에서만 갑자기 멈추는 식이 되면 사용자가 무슨 규칙인지 못
    # 읽는다.
    gates = checkpoints(job.form)

    try:
        build_config(job_dir, job.style,
                     head_ratio=str(job.form.get("head_ratio") or "").strip().lower(),
                     genre=str(job.form.get("genre") or ""),
                     mode=layout_mode(job.form),
                     qa_regen_max=art_qa_regen_max(job.form))

        # ---- 이어 만들기 — 이야기·시트를 건너뛰고 콘티부터 -------------- #
        #
        # 인물·세계·캐릭터 시트는 1화에서 이미 정해졌고, 여기서 다시 만들면
        # 그게 흔들린다(같은 캐릭터가 다른 얼굴이 된다). run_id 도 새로 파지
        # 않고 그대로 쓰므로, 스토리 하네스의 series.json·ledger.json 이
        # 이어져서 앞 화의 인물·설정·미회수 복선이 그대로 따라온다.
        # ---- 이어 그리기 — 콘티는 그대로 두고 다음 컷만 그린다 ---------- #
        #
        # 미리보기로 앞 3컷을 본 사람이 "다음 장면도 볼까요?" 를 누른 자리다.
        # 이야기·시트·콘티는 이미 run 안에 있으므로 다시 돌지 않는다 — 다시
        # 돌면 같은 화의 앞뒤가 서로 다른 콘티에서 나오게 된다.
        if job.is_more:
            run_id = job.run_id or ""
            if not run_id:
                raise Failed("이어 그릴 작품을 찾지 못했습니다.")
            (job_dir / "run_id.txt").write_text(run_id, encoding="utf-8")
            _more_cuts_stages(job, run_id, job_dir)
            job.status = "done"
            job.finished_at = time.time()
            return

        if job.is_next:
            run_id = job.run_id or ""
            if not run_id:
                raise Failed("이어 만들 작품을 찾지 못했습니다.")
            (job_dir / "run_id.txt").write_text(run_id, encoding="utf-8")
            _next_episode_stages(job, run_id, job_dir)
            job.status = "done"
            job.finished_at = time.time()
            return

        char_path = write_character(job_dir, job.form)

        # ---- 1. 이야기 --------------------------------------------------- #
        _enter(job, 0)
        # 사람이 "다시 만들기"를 누르며 적은 말. 다음 바퀴의 story.py 에
        # --author-note 로 실려 P1·P2 프롬프트의 {retry_feedback} 자리에 들어간다.
        story_note = ""
        prev_run_id = ""
        # 아직 한 번도 안 돌린 설치에는 runs/ 가 없다 (gitignore 라 새로 받은
        # 폴더·새 worktree 는 늘 이 상태로 시작한다). 없다고 터지면 첫 생성이
        # FileNotFoundError 트레이스백으로 죽어서, 처음 쓰는 사람이 가장 먼저
        # 보는 화면이 그것이 된다. story.py 가 어차피 여기에 쓰므로 미리 만든다.
        (STORY / "runs").mkdir(parents=True, exist_ok=True)
        while True:
            job.note("캐릭터를 읽는 중")
            before = {d.name for d in (STORY / "runs").iterdir() if d.is_dir()}
            cmd = ["story.py", "--character", str(char_path), "--scenes", "3", "--no-read"]
            if story_note:
                cmd += ["--author-note", story_note]
            # 작가 규칙 — 다시 만들기는 새 run_id 를 만들므로, 이전 run 의
            # memory.json 을 파일로 넘긴다. story.py 가 새 run 폴더에 사본을
            # 남기고 P1·P2·SCENE 프롬프트에 싣는다.
            prev_mem = (STORY / "runs" / prev_run_id / "memory.json"
                        if prev_run_id else None)
            if prev_mem and prev_mem.exists():
                cmd += ["--memory-file", str(prev_mem)]
            code = job._run(cmd, STORY, lambda ln: _story_line(job, ln))
            if job._cancel:
                raise Failed("취소됨")
            if code != 0:
                raise Failed("이야기를 만들지 못했습니다.")
            run_id = _latest_run(before)
            if not run_id:
                raise Failed("이야기는 돌았지만 결과 폴더를 찾지 못했습니다.")
            # 이야기를 다시 만들면 run_id 가 새로 생긴다 (story.py 는 --character 를
            # 받으면 늘 새 폴더를 판다). 지금까지 적은 피드백을 새 폴더로 옮겨
            # 붙여야 "이 작품에 무슨 말을 했는가"가 한 파일에서 이어진다.
            if prev_run_id and prev_run_id != run_id:
                _carry_feedback(prev_run_id, run_id)
            prev_run_id = run_id
            job.run_id = run_id
            (job_dir / "run_id.txt").write_text(run_id, encoding="utf-8")
            if not (STORY / "runs" / run_id / "scenes.json").exists():
                raise Failed("장면까지 나오지 못했습니다. 캐릭터 설명을 조금 더 "
                             "구체적으로 적고 다시 시도해 주세요.")

            # story.py 의 main() 은 게이트가 소진돼 사람 확인이 필요한
            # 상태(STATUS_HUMAN)에서도 종료 코드는 항상 0 을 낸다 — 그래서
            # exit code 만으로는 못 잡고 meta.json 을 직접 읽는다.
            status, note = _meta_status(STORY / "runs" / run_id / "meta.json")
            human = status == STATUS_HUMAN
            # 일반 모드는 게이트가 소진됐을 때만 멈춘다(지금까지의 동작).
            # 전문 모드는 멀쩡히 통과했어도 멈춘다 — 이야기가 마음에 안 드는
            # 것은 게이트가 잡는 종류의 문제가 아니고, 여기서 안 잡으면 콘티와
            # 그림까지 다 나온 뒤에야 알게 된다.
            if not human and not gates["story"]:
                break                  # STATUS_OK(또는 알 수 없는 값) — 정상 진행

            job.status = "awaiting_story_approval"
            if human:
                job.note("구조 검수에서 게이트 재시도가 소진됐습니다 — 확인해 주세요"
                         + (f" ({note})" if note else ""))
            else:
                job.note("이야기가 나왔습니다 — 확인해 주세요")
            job.save()
            _await_approval(job, job.story_approval, "이야기 구조")
            with job._lock:
                decision = job.story_decision
                job.story_decision = ""
                story_note = job.story_note
                job.story_note = ""
            job.status = "running"
            if job._cancel:
                raise Failed("취소됨")
            if decision != "retry":
                break                   # approve (또는 알 수 없는 값 — 진행 쪽이 안전)
            # 다시 만들기 — 시트처럼 같은 run_id 폴더를 지우고 재시도하는 방식이
            # 아니다. story.py 는 --character 를 받으면 항상 새 run_id 를
            # 만들므로, 같은 캐릭터 입력으로 통째로 한 번 더 돈다.
            job.note("캐릭터를 다시 읽는 중 — 이야기를 새로 만드는 중")
        _leave(job)

        # ---- 2. 캐릭터 시트 ---------------------------------------------- #
        _enter(job, 1)
        job.note("외형 사양을 정리하는 중")
        sheet_dir = STORY / "runs" / run_id / "charsheet"
        picks = sheet_dir / "charsheet_picks.json"
        while True:
            # 시트 이미지 기본값은 story.py 안에서 gemini 다 — 텍스트 단계용
            # --provider(.env PROVIDER=openai)는 여기 안 먹는다. 제품은 시트를
            # OpenAI(gpt-image-2)로 뽑기로 정했으므로 여기서 명시로 준다.
            # 바꾸려면 .env 의 SHEET_IMAGE_PROVIDER (위 상수 참고).
            #
            # --author-note 는 여기 안 붙인다. 시트 프롬프트는 p1.json 의
            # appearance_en·design_details 로만 만들어지고 그 두 값은 게이트가
            # (개수·추상어) 지키고 있어서, 사람이 쓴 한국어 문장을 끼워 넣으면
            # gate_charsheet_source 에서 걸린다. 시트를 실제로 바꾸는 길은
            # 승인 화면의 수정 폼(_apply_sheet_edits)이다 — 고른 항목과 적은
            # 말은 기록만 하고, 무엇을 어떻게 바꿀지는 그 폼이 받는다.
            sheet_cmd = ["story.py", "--charsheet", "--run-id", run_id,
                         "--provider", SHEET_IMAGE_PROVIDER, "--yes"]
            # 품질은 openai 쪽 인자다 — gemini 로 그릴 때 붙이면 뜻이 없다.
            if SHEET_IMAGE_QUALITY and SHEET_IMAGE_PROVIDER == "openai":
                sheet_cmd += ["--quality", SHEET_IMAGE_QUALITY]
            code = job._run(sheet_cmd, STORY, lambda ln: _sheet_line(job, ln))
            if job._cancel:
                raise Failed("취소됨")
            if code != 0 or not picks.exists():
                raise Failed("캐릭터 시트를 만들지 못했습니다. "
                             "조건 S+ 는 시트 없이는 돌 수 없습니다.")

            # 시트가 나온 뒤 사람이 보는 지점 — P0-1. story.py 의 --yes 와
            # 후보 1장 자동 채택(자체 게이트)은 그대로 두고, 그 다음 단계로
            # 넘어가기 전에 여기서 한 번 세운다. "아예 다른 사람이 됐다" 같은
            # 사고가 이 지점에서 멈춰야 뒤 컷 전부가 오염되지 않는다.
            job.status = "awaiting_sheet_approval"
            job.note("캐릭터 시트가 나왔습니다 — 확인해 주세요")
            job.save()
            _await_approval(job, job.sheet_approval, "캐릭터 시트")
            with job._lock:
                decision = job.sheet_decision
                job.sheet_decision = ""
                edit_fields = job.sheet_edit_fields
                job.sheet_edit_fields = None
                fixes = list(job.sheet_fixes)
                job.sheet_fixes = []
            job.status = "running"
            if job._cancel:
                raise Failed("취소됨")
            if decision != "retry":
                # 승인된 순간부터 올린 사진은 쓸 데가 없다. 사진을 여는 곳은
                # 둘뿐이고(이야기 단계의 LOOK, 시트 그리기) 둘 다 지나왔다 —
                # 뒤 단계는 시트 그림만 본다. 그래서 여기서 지운다.
                #
                # 승인 **전**에는 못 지운다. 「수정 후 다시 만들기」가 같은
                # 사진으로 시트를 다시 그리기 때문이다.
                _drop_job_photos(job)
                break                   # approve (또는 알 수 없는 값 — 진행 쪽이 안전)
            if edit_fields:
                job.note("고친 내용을 저장하는 중")
                _apply_sheet_edits(STORY / "runs" / run_id, edit_fields)
            # 고른 항목·적은 말을 다음 판 프롬프트에 싣는다. 사양을 바꾸는
            # edit_fields 와 달리 이쪽은 지시로 붙는다 — 일반 모드에는 수정
            # 폼이 없으므로 여기가 사용자의 말이 그림에 닿는 유일한 길이다.
            if fixes:
                job.note("고쳐 달라고 한 것을 정리하는 중")
                _merge_sheet_corrections(STORY / "runs" / run_id, fixes)
            # 다시 만들기 — story.py 는 이 폴더가 있으면 재생성을 건너뛰므로
            # (story.py 의 "다시 뽑고 싶으면 이 폴더를 사람이 직접 지운다"와
            # 동일한 방식) 지우고 같은 루프를 한 번 더 돈다.
            shutil.rmtree(sheet_dir, ignore_errors=True)
            job.note("시트를 다시 만드는 중")
        _leave(job)

        # ---- 3. 콘티 ------------------------------------------------------ #
        _enter(job, 2)
        board_meta = STORY / "runs" / run_id / "webtoon" / "meta.json"
        replan = False
        board_note = ""
        while True:
            job.note("큰 줄거리를 세우는 중" if not replan else "콘티를 다시 짜는 중")
            cmd = ["webtoon.py", "--run", run_id, "--episodes", "1", "--skip-human-gate"]
            if replan:
                cmd.append("--replan")
            if board_note:
                cmd += ["--author-note", board_note]
            code = job._run(cmd, STORY, lambda ln: _board_line(job, ln))
            if job._cancel:
                raise Failed("취소됨")
            cuts_path = STORY / "runs" / run_id / "webtoon" / "ep01_cuts.json"

            # webtoon.py 의 main() 도 STATUS_HUMAN/실패에서 종료 코드는 항상 0 —
            # story.py 와 같은 사정. meta.json 을 직접 읽어야 한다.
            #
            # **이 판정이 컷 파일 검사보다 먼저 와야 한다.** 게이트가 소진되면
            # webtoon.py 는 컷을 한 개도 안 쓰고 멈추므로(로그의 "컷 0"),
            # 순서가 반대면 ep01_cuts.json 이 없다는 이유로 먼저 실패해서
            # **승인 화면에 영영 닿지 못한다** — 그 화면이 존재하는 이유가 바로
            # 이 경우인데도. 2026-08-23 실제 실행에서 이렇게 막혔다:
            # meta.json 은 '사람확인필요' 인데 화면에는 "콘티를 만들지
            # 못했습니다" 만 떴고, 사용자가 왜 걸렸는지도 다시 시도할 길도 없었다.
            status, note = _meta_status(board_meta)
            human = status == STATUS_HUMAN
            if code != 0 or (not cuts_path.exists() and not human):
                raise Failed("콘티(컷 설계)를 만들지 못했습니다.")
            # 스토리 단계와 같은 규칙 — 일반은 게이트 소진 때만, 전문은 늘.
            if not human and not gates["board"]:
                break                  # STATUS_OK(또는 알 수 없는 값) — 정상 진행

            job.status = "awaiting_board_approval"
            if human:
                job.note("콘티 단계 게이트 재시도가 소진됐습니다 — 확인해 주세요"
                         + (f" ({note})" if note else ""))
            else:
                job.note("콘티가 나왔습니다 — 확인해 주세요")
            job.save()
            _await_approval(job, job.board_approval, "콘티")
            with job._lock:
                decision = job.board_decision
                job.board_decision = ""
                board_note = job.board_note
                job.board_note = ""
            job.status = "running"
            if job._cancel:
                raise Failed("취소됨")
            if decision != "retry":
                # 게이트가 소진된 자리는 두 가지다. 컷이 나왔는데 기준에 걸린
                # 것이면 "이대로 진행" 이 말이 된다 — 사람이 보고 괜찮다고 한
                # 것이니 그 콘티로 그린다. 컷이 아예 안 나온 것이면 진행할
                # 대상이 없으므로, 그리기로 넘어가 봐야 거기서 다시 죽는다.
                # 그때 나오는 말("컷 서술을 옮기지 못했습니다")은 원인에서
                # 멀어져서 더 알아보기 어렵다 — 여기서 멈추고 이유를 말한다.
                #
                # 정식 파일이 없어도 **초안**(게이트에 걸린 마지막 시도)이
                # 있으면 그걸 정식 파일로 승격해서 그대로 쓴다 — 사람이
                # "이대로 진행"을 눌렀다는 것은 그 초안을 보고 괜찮다고 한
                # 것이니, 뒷단계(그림)가 읽을 자리에 실제로 놓아 줘야 진짜
                # "이대로 진행"이 된다. 초안조차 없을 때만 막는다.
                if not cuts_path.exists():
                    draft_path = cuts_path.with_name("ep01_cuts.draft.json")
                    if draft_path.exists():
                        cuts_path.write_text(
                            draft_path.read_text(encoding="utf-8"),
                            encoding="utf-8")
                        job.add_log("  초안을 정식 콘티로 승격했습니다 — 이대로 그립니다")
                    else:
                        raise Failed(
                            "콘티가 한 컷도 나오지 않아 이대로는 진행할 수 없습니다. "
                            "무엇이 걸렸는지 적어서 '다시 만들기'를 눌러 주세요."
                            + (f" ({note})" if note else ""))
                break                   # approve — 이 콘티 그대로 진행
            replan = True
        _leave(job)

        # ---- 4·5. 그림 + 이어 붙이기 -------------------------------------- #
        # 한 번의 실행이 두 가지를 한다. 컷이 다 나오면 run.py 가 그대로
        # episode.png 까지 만든다.
        _enter(job, 3)
        job.note("컷 서술을 옮기는 중")
        mode = LAYOUT_MODES[layout_mode(job.form)]["mode"]
        cmd = ["run.py", "--run-id", run_id, "--episode", "1",
               "--mode", mode, "-c", CONDITION, "--style", job.style,
               "--config", str(job_dir / "config.yaml"), "--yes"]
        if job.preview:
            # 미리보기 = **전체의 절반가량.** 이 자리는 콘티(webtoon.py)가
            # 이미 끝난 뒤라 이 화의 실제 컷 수를 안다 — 고정 컷 수(앞 3컷,
            # 앞 6컷)로 자르면 컷이 많은 화에서는 감질맛만 나고 적은 화에서는
            # 미리보기가 거의 전부가 된다. 절반은 이야기가 어디로 가는지
            # 읽히는 최소 분량이다. 컷을 이미지로 어떻게 묶을지는 run.py 가
            # 정하므로(1컷=1장일 수도, 여러 컷=1장일 수도) 여기서는 컷 기준
            # 절반만 자르고, 값 계산은 그려진 뒤의 실제 장 수로 한다.
            half = max(CUTS_PER_SHEET, -(-planned_cuts(run_id, 1) // 2))
            cmd += ["--cuts", f"1-{half}"]

        def art_or_bind(line: str) -> None:
            # episode.png 줄이 보이는 순간 마지막 단계로 넘어간다.
            if job.stage_i == 3 and (line.startswith("episode.png")
                                     or line.startswith("완료:")):
                _leave(job)
                _enter(job, 4)
                job.note("그린 장을 순서대로 이어 붙이는 중")
            if job.stage_i == 3:
                _art_line(job, line)
            else:
                _bind_line(job, line)

        code = job._run(cmd, WEBTOON, art_or_bind)
        if job._cancel:
            raise Failed("취소됨")
        if job.stage_i == 3:
            _leave(job)
            _enter(job, 4)
        # 완성본이 있는지 **먼저** 본다. run.py 는 12장 중 1장만 실패(거절 포함)
        # 해도 종료 코드 1을 내는데, code 만 보고 죽으면 11장과 episode.png 가
        # 있어도 사용자는 결과 화면에 영영 못 간다 — 거절 사유 표시(refusals)도
        # 결과 화면이 아니라 진행 화면에만 있어서 아무도 못 본다. 완성본이
        # 있으면 그대로 보여 주고, 실패는 화면의 거절/실패 표시가 맡는다.
        out = WEBTOON / "outputs" / run_id / "ep1" / "episode.png"
        if not out.exists():
            if code != 0:
                raise Failed("그림 생성이 실패했습니다.")
            raise Failed("그림은 나왔지만 한 편으로 잇지 못했습니다.")
        _leave(job)

        # ---- 6. 그림 검수 확인 (전문 모드) -------------------------------- #
        #
        # 그림 QA 는 두 모드 모두 돈다. 다른 것은 **결과를 언제 보여주는가**다.
        # 일반 모드는 끝내고 결과 화면에서 "못 고친 것"만 노트로 알린다 —
        # 자동으로 고쳐진 것은 아예 안 보인다(알 필요가 없다).
        # 전문 모드는 끝났다고 하기 전에 여기서 세워서, 잡힌 것 전부를
        # (다시 그려서 고쳐진 것까지) 보여준다.
        #
        # 잡힌 것이 하나도 없으면 안 세운다 — 보여줄 것이 없는 화면을 띄우고
        # 확인 버튼을 누르게 하는 것은 검수가 아니라 절차다.
        qa = (art_qa_summary(job.run_id, job.episode)
              if gates["artqa"] and job.run_id else {})
        if qa.get("fixed") or qa.get("unresolved"):
            job.status = "awaiting_artqa_approval"
            job.note("그림 검수 결과를 확인해 주세요")
            job.save()
            _await_approval(job, job.artqa_approval, "그림 검수")
            # **여기서는 _cancel 을 안 본다.** 앞의 세 승인 자리와 다른 점이다.
            # 그 자리들은 아직 만들 것이 남아 있어서 취소가 "그만 만든다"는
            # 뜻이지만, 여기는 episode.png 까지 다 나온 뒤다 — 취소할 대상이
            # 없다. 그런데도 취소로 처리하면 **다 만든 웹툰이 "중단됨"이 되어**
            # 결과 화면으로 못 간다. 취소든 확인이든 완성으로 끝낸다.
            # (cancel() 이 이 Event 를 깨우는 것은 그대로 둔다 — 안 그러면
            #  중단을 눌렀을 때 아무 반응 없이 화면이 멈춘 것처럼 보인다.)

        job.status = "done"
        job.finished_at = time.time()

    except Failed as exc:
        job.status = "cancelled" if job._cancel else "error"
        job.error = str(exc)
        job.finished_at = time.time()
        _leave(job, ok=False)
    except Exception as exc:                                   # noqa: BLE001
        job.status = "error"
        job.error = f"{type(exc).__name__}: {exc}"
        job.finished_at = time.time()
        _leave(job, ok=False)
    finally:
        job.save()


# --------------------------------------------------------------------------- #
# 결과 읽기
# --------------------------------------------------------------------------- #

def episode_dir(run_id: str, episode: int = 1) -> Path:
    """그 회차의 그림이 떨어지는 폴더.

    하네스는 회차마다 폴더를 따로 쓴다(`outputs/<run>/ep1`, `ep2`, …) — 장 번호가
    회차마다 1부터 다시 시작하므로, 한 폴더에 몰면 2화 1장이 1화 1장을 덮어쓴다.
    기본값이 1인 이유는 이 함수를 부르는 옛 자리들이 전부 1화를 뜻하기 때문이다.
    """
    return WEBTOON / "outputs" / run_id / f"ep{int(episode)}"


def cuts_filename(episode: int = 1) -> str:
    """그 회차의 콘티 파일 이름. 스토리 하네스는 두 자리로 적는다(ep01_cuts.json)."""
    return f"ep{int(episode):02d}_cuts.json"


def cuts_path(run_id: str, episode: int = 1) -> Path:
    return STORY / "runs" / run_id / "webtoon" / cuts_filename(episode)


def made_episodes(run_id: str) -> list[int]:
    """이 작품에 콘티가 나와 있는 회차 번호 — 작은 것부터.

    series.json 이 아니라 **파일**을 센다. 콘티까지만 나오고 그림이 없는 회차도
    있고(중간에 끊긴 실행), 하네스를 직접 돌려 만든 회차도 있어서, 상태 파일보다
    떨어진 결과가 언제나 사실에 가깝다.
    """
    wt = STORY / "runs" / run_id / "webtoon"
    if not wt.is_dir():
        return []
    out = []
    for p in wt.glob("ep*_cuts.json"):
        m = re.fullmatch(r"ep(\d+)_cuts\.json", p.name)
        if m:
            out.append(int(m.group(1)))
    return sorted(out)


def episode_caption(run_id: str, episode: int = 1) -> str:
    """워터마크 띠 오른쪽에 적을 한 줄 — "초롱 · 1화".

    파일 이름(episode_filename)과 달리 사람이 읽는 자리라 밑줄 대신 가운뎃점을
    쓰고, "말풍선" 같은 파일 구분은 안 붙인다.
    """
    name = str(_read_json(STORY / "runs" / run_id, "p1.json").get("name") or "").strip()
    return f"{name} · {int(episode)}화" if name else f"{int(episode)}화"


def episode_filename(run_id: str, episode: int = 1, baked: bool = False) -> str:
    """내려받을 때 붙는 이름 — 작품(주인공 이름)과 회차를 반영한다.

    예전에는 `webtoon_<run_id>_1화.png` 였다. run_id 는 만들어진 시각이라
    사람에게는 아무 뜻이 없고, 회차도 1화로 박혀 있어서 2화를 받아도 1화라고
    적혔다. 여러 편을 받아 폴더에 모아 두면 어느 것이 무엇인지 알 수 없다.

    파일 이름에 쓸 수 없는 글자는 지운다 — 이름은 사용자가 적은 것이라
    슬래시·콜론이 들어올 수 있고, 그대로 두면 저장이 실패한다.
    """
    name = str(_read_json(STORY / "runs" / run_id, "p1.json").get("name") or "").strip()
    safe = re.sub(r'[\\/:*?"<>|]', "", name).strip()
    head = safe or run_id
    tail = "_말풍선" if baked else ""
    return f"{head}_{int(episode)}화{tail}.png"


# --------------------------------------------------------------------------- #
# 편집실에서 얹은 것 — 저장하고, 그림에 굽는다
#
# 지금까지 편집실의 말풍선·스티커는 **브라우저에만** 있었다. 공들여 배치해 놓고도
# 가져갈 수 있는 것은 말풍선 없는 원본뿐이었다. 여기가 그 둘을 잇는다.
# 그리는 일 자체는 overlay.py 가 한다 — 이쪽은 경로와 장 목록만 맞춰 준다.
# --------------------------------------------------------------------------- #

def _scene_numbers(run_id: str, episode: int = 1) -> list[int]:
    """이 회차의 장 번호. scenes.json 이 없으면 컷 하나가 곧 한 장이다."""
    ep_dir = episode_dir(run_id, episode)
    grouping = _read_json(ep_dir, "scenes.json").get("scenes") or []
    if grouping:
        return sorted({int(sc.get("scene_number") or 0) for sc in grouping} - {0})
    cuts = _read_json(STORY / "runs" / run_id / "webtoon",
                      f"ep{int(episode):02d}_cuts.json").get("cuts") or []
    return sorted({int(c.get("cut_number") or 0) for c in cuts} - {0})


def _scene_layout(run_id: str, episode: int = 1) -> dict[int, tuple[int, str]]:
    """장 번호 -> (gap_after, weight). overlay.bake() 가 다시 이어 붙일 때 쓴다.

    **편집실에서 고친 여백이 있으면 그것이 이긴다.** 콘티가 정한 gap_after 는
    글로 읽고 계산한 값이라, 그림이 나온 뒤에 보면 너무 붙었거나 너무 벌어져
    있을 수 있다. 그때 사람이 화면에서 고친 값이 최종본까지 그대로 가야 한다.

    scenegen.Scene.gap_after/.weight 와 같은 규칙이다(마지막 컷의 gap_after,
    첫 컷의 weight) — 여기는 Scene 객체가 없어 원본 컷 dict 에서 직접 뽑는다.
    scenes.json 이 없는 옛 화(컷 하나 = 장 하나)는 빈 dict 를 돌려주고, 그러면
    overlay.bake() 가 기본값(여백 1·꽉 채움)으로 잇는다 — 예전과 같다.
    """
    ep_dir = episode_dir(run_id, episode)
    grouping = _read_json(ep_dir, "scenes.json").get("scenes") or []
    if not grouping:
        return {}
    cuts = _read_json(STORY / "runs" / run_id / "webtoon",
                      f"ep{int(episode):02d}_cuts.json").get("cuts") or []
    by_no = {int(c.get("cut_number") or 0): c for c in cuts}
    out: dict[int, tuple[int, str]] = {}
    for sc in grouping:
        no = int(sc.get("scene_number") or 0)
        nums = [int(n) for n in (sc.get("cut_numbers") or [])]
        if not nums:
            continue
        last, first = by_no.get(nums[-1]) or {}, by_no.get(nums[0]) or {}
        gap = last.get("gap_after")
        gap = gap if isinstance(gap, int) and 0 <= gap <= 3 else 1
        weight = str(first.get("weight") or "normal").strip().lower()
        out[no] = (gap, weight if weight in ("full", "normal", "light", "wide") else "normal")

    for no, g in overlay.gap_overrides(overlay.load_overlay(ep_dir)).items():
        if no in out:
            out[no] = (g, out[no][1])
    return out


def _strip_gap_table() -> dict[int, float]:
    """하네스 기본 여백 눈금. config 를 못 찾은 옛 run 이 쓴다."""
    try:
        import strip as _strip                                  # noqa: PLC0415
        return _strip.gap_ratio_table()
    except Exception:                                           # noqa: BLE001
        return {0: 0.0, 1: 0.07, 2: 0.26, 3: 0.62}


def _width_ratio(weight: str) -> float:
    """그 무게의 컷이 쓰는 지면 폭(배)."""
    try:
        import strip as _strip                                  # noqa: PLC0415
        return float(_strip.width_ratio({"weight": weight}))
    except Exception:                                           # noqa: BLE001
        w = str(weight).strip().lower()
        return 0.55 if w == "light" else (1.15 if w == "wide" else 1.0)


def _run_gap_table(run_id: str) -> dict[int, float] | None:
    """그 실행이 실제로 쓴 여백 눈금(scene.gap_ratio). 못 찾으면 None.

    하네스 기본은 {0:0, 1:0.07, 2:0.26, 3:0.62} 인데 "웹툰" 연출은 이것을
    {0:0, 1:0.16, 2:0.32, 3:0.90} 으로 덮어쓴다. 다시 구울 때 기본값으로 이으면
    같은 화가 원본보다 절반쯤 촘촘해진다 — 세로 스크롤에서 여백은 장식이 아니라
    호흡이라, 그만큼 다른 작품이 된다.
    """
    cfg = _origin_config(run_id)
    if not cfg:
        return None
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"(?m)^  gap_ratio:\s*\{(.*?)\}\s*$", text)
    if not m:
        return None
    out: dict[int, float] = {}
    for k, v in re.findall(r"(\d+)\s*:\s*([\d.]+)", m.group(1)):
        try:
            out[int(k)] = float(v)
        except ValueError:
            continue
    return out or None


def _mtime(p: Path | None) -> float:
    try:
        return p.stat().st_mtime if p else 0.0
    except OSError:
        return 0.0


def final_unit(run_id: str, no: int, episode: int = 1) -> Path | None:
    """화면과 내려받기가 **실제로 내보내는** 장 그림.

    편집실에서 얹은 말풍선·스티커가 있으면 그것이 구워진 그림을 준다. 없으면
    원본 그대로다. 전에는 모든 보는 자리가 원본(unit_image)만 봐서, 편집실에서
    얹고 저장해도 결과 화면·둘러보기·내려받기에는 안 나왔다 — 저장은 되는데
    아무 데도 안 보이니 저장이 안 된 것과 같았다.

    굽기는 **볼 때** 한다. 저장할 때마다 한 편을 통째로 구우면 말풍선 한 번
    옮길 때마다 그 일을 다 하게 된다. 대신 밑그림이나 얹은 것이 구운 것보다
    새로우면(다시 그렸거나 방금 고쳤으면) 그 장만 다시 굽는다.
    """
    base = unit_image(run_id, no, episode)
    if not base:
        return None
    ep_dir = episode_dir(run_id, episode)
    ov = overlay.overlay_path(ep_dir)
    if not ov.exists():
        return base
    try:
        data = overlay.load_overlay(ep_dir)
    except Exception:                                           # noqa: BLE001
        return base
    if not overlay.has_items(data, no):
        return base
    out = overlay.baked_scene_path(ep_dir, no)
    if _mtime(out) >= max(_mtime(base), _mtime(ov)):
        return out
    try:
        return overlay.bake_one(ep_dir, no, base, data)
    except Exception:                                           # noqa: BLE001
        # 구우려다 실패했다고 화면이 비면 안 된다 — 원본이라도 보여 준다.
        return base


def final_episode(run_id: str, episode: int = 1) -> Path:
    """내려받기가 내보내는 **한 편**. 얹은 것이 있으면 구운 판이다.

    final_unit 과 같은 규칙이되 한 편이라 통째로 굽는다. 얹은 것이 하나도
    없으면 원본 episode.png 를 그대로 준다 — 굽는 값이 없다.
    """
    ep_dir = episode_dir(run_id, episode)
    plain = ep_dir / "episode.png"
    ov = overlay.overlay_path(ep_dir)
    if not ov.exists():
        return plain
    try:
        data = overlay.load_overlay(ep_dir)
    except Exception:                                           # noqa: BLE001
        return plain
    # scenes.json 도 콘티도 없는 화(옛 실행·부분 복구)는 그려 둔 그림을 센다 —
    # 목록을 못 만들면 얹은 것이 있어도 굽지 못하고 원본이 나간다.
    numbers = (_scene_numbers(run_id, episode)
               or list(range(1, drawn_units(run_id, episode) + 1)))
    if not any(overlay.has_items(data, n) for n in numbers):
        return plain
    out = overlay.baked_episode_path(ep_dir)
    newest = max([_mtime(ov)] + [_mtime(unit_image(run_id, n, episode))
                                 for n in numbers])
    if _mtime(out) >= newest:
        return out
    try:
        overlay.bake(ep_dir, numbers, lambda n: unit_image(run_id, n, episode),
                     data, _scene_layout(run_id, episode), _run_gap_table(run_id))
    except Exception:                                           # noqa: BLE001
        return plain
    return out if out.exists() else plain


def read_overlay(run_id: str, episode: int = 1) -> dict[str, Any]:
    return overlay.load_overlay(episode_dir(run_id, episode))


def write_overlay(run_id: str, body: Any, episode: int = 1) -> dict[str, Any]:
    ep_dir = episode_dir(run_id, episode)
    if not ep_dir.exists():
        raise Failed("그 작품의 회차 폴더를 찾지 못했습니다.")
    data = overlay.save_overlay(ep_dir, body)
    return {"ok": True, "items": overlay.count_items(data)}


def baked_episode(run_id: str, episode: int = 1) -> Path | None:
    p = overlay.baked_episode_path(episode_dir(run_id, episode))
    return p if p.exists() else None


def cut_bounds(run_id: str, episode: int = 1, baked: bool = False
                ) -> list[tuple[int, int, int, int]] | None:
    """내려받는 최종본 안에서 컷마다 자리 — watermark.for_download() 에 넘겨서
    컷마다 표시를 찍게 한다. baked=True 면 편집실에서 구운 컷 그림을 우선
    쓴다(없으면 원본으로 대체). 못 구하면 None — 호출부가 한 장짜리 마크로
    돌아간다.
    """
    ep_dir = episode_dir(run_id, episode)
    numbers = (_scene_numbers(run_id, episode)
               or list(range(1, drawn_units(run_id, episode) + 1)))
    if not numbers:
        return None
    paths: list[Path] = []
    for n in numbers:
        p = overlay.baked_scene_path(ep_dir, n) if baked else None
        if not p or not p.exists():
            p = unit_image(run_id, n, episode)
        if not p or not Path(p).exists():
            return None
        paths.append(Path(p))
    layout = _scene_layout(run_id, episode)
    gaps = [layout.get(n, (0, "normal"))[0] for n in numbers]
    ratios = [_width_ratio(layout.get(n, (0, "normal"))[1]) for n in numbers]
    table = _run_gap_table(run_id) or _strip_gap_table()
    return watermark.cut_layout(paths, gaps, ratios, table)


def bake_overlay(run_id: str, body: Any, episode: int = 1) -> dict[str, Any]:
    """얹은 것을 그림에 굽는다. body 에 얹은 것이 실려 오면 그것을 먼저 저장한다.

    저장과 굽기를 한 번에 하는 이유: 사용자가 누르는 버튼은 하나("이미지로
    뽑기")인데, 저장이 따로 왕복하면 그 사이에 실패했을 때 화면에 보이는 것과
    구운 것이 갈린다.
    """
    ep_dir = episode_dir(run_id, episode)
    if not ep_dir.exists():
        raise Failed("그 작품의 회차 폴더를 찾지 못했습니다.")
    data = (overlay.save_overlay(ep_dir, body)
            if isinstance(body, dict) and body.get("scenes") is not None
            else overlay.load_overlay(ep_dir))
    numbers = _scene_numbers(run_id, episode)
    if not numbers:
        raise Failed("이 회차의 장을 찾지 못했습니다.")
    try:
        res = overlay.bake(ep_dir, numbers,
                           lambda n: unit_image(run_id, n, episode), data,
                           _scene_layout(run_id, episode),
                           _run_gap_table(run_id))
    except overlay.OverlayError as exc:
        raise Failed(str(exc)) from exc
    res["url"] = f"/api/runs/{run_id}/baked.png?ep={int(episode)}"
    res["items"] = overlay.count_items(data)
    return res


def episode_title(run_id: str, episode: int = 1) -> str:
    """그 회차의 제목.

    arc{N}_episodes.json 이 아니라 **series.json** 을 본다. arc 파일에 실리는 것은
    5단계가 쓴 회차 카드 그대로라 회차 번호 칸이 없고, 게다가 회차가 쌓이면 2화가
    arc2 로 넘어갈 수 있어서(story-harness 의 arc_for_episode) 파일 하나만 봐서는
    못 찾는다. series.json 은 회차마다 no·title 을 같이 남긴다.

    사람이 고쳐 둔 제목이 있으면 그것이 이긴다 — 아래 titles.json 참고.
    """
    mine = user_title(run_id, episode)
    if mine:
        return mine
    wt = STORY / "runs" / run_id / "webtoon"
    for ep in (_read_json(wt, "series.json").get("episodes") or []):
        if isinstance(ep, dict) and int(ep.get("no") or 0) == int(episode):
            return str(ep.get("title") or "")
    return ""


# ---- 사람이 고친 제목 -------------------------------------------------------
#
# 모델이 지은 제목이 늘 맞지는 않는다. 특히 공유가 붙은 뒤로는 이 제목이
# 카톡·트위터 카드에 그대로 실려서, 마음에 안 드는 이름이 남에게 먼저 보인다.
#
# **series.json 을 안 고친다.** 그쪽은 하네스가 쓴 것이고 이어 만들기(2화)가
# 다시 읽는 파일이라, 사람이 손대면 하네스의 기록과 제품의 표시가 섞인다.
# 대신 옆에 titles.json 을 둔다 — 없으면 예전 그대로 동작하고, 지우면 모델이
# 지은 이름으로 되돌아간다.
TITLE_MAX = 60


def titles_path(run_id: str) -> Path:
    return STORY / "runs" / run_id / "titles.json"


def user_title(run_id: str, episode: int = 1) -> str:
    """사람이 고쳐 둔 그 회차 제목. 없으면 빈 문자열."""
    try:
        doc = json.loads(titles_path(run_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(doc, dict):
        return ""
    return str(doc.get(str(int(episode))) or "").strip()[:TITLE_MAX]


def set_user_title(run_id: str, episode: int, title: str) -> str:
    """제목을 고쳐 둔다. 빈 값을 주면 지운다(모델이 지은 이름으로 되돌아간다).

    돌려주는 것은 **이 회차가 앞으로 보일 이름**이다 — 지웠으면 원래 이름.
    """
    path = titles_path(run_id)
    if not path.parent.is_dir():
        raise Failed("그런 작품이 없습니다.")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            doc = {}
    except (OSError, ValueError):
        doc = {}
    key = str(int(episode))
    clean = " ".join(str(title or "").split())[:TITLE_MAX]
    if clean:
        doc[key] = clean
    else:
        doc.pop(key, None)
    try:
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except OSError as exc:
        raise Failed("제목을 저장하지 못했습니다.") from exc
    return episode_title(run_id, episode) or f"{int(episode)}화"


# 하네스(run.py)의 REFUSAL_HINTS 와 짝이다. 저쪽은 터미널에, 이쪽은 화면에 쓴다.
# 사유 코드는 이미지 모델이 주는 것이라 둘 다 같은 표를 봐야 말이 안 갈린다.
REFUSAL_HINTS = {
    "PROHIBITED_CONTENT": "모델이 금지된 내용으로 판단했습니다. 캐릭터 나이가 "
                          "어리면(대략 15세 미만) 걸리는 경우가 많습니다 — 나이를 "
                          "올리거나 폭력·노출 묘사를 덜어 보세요.",
    "IMAGE_SAFETY": "이미지 안전 필터에 걸렸습니다. 유혈·상해 묘사나 어린 "
                    "캐릭터의 신체 묘사가 원인인 경우가 많습니다.",
    "SAFETY": "안전 필터에 걸렸습니다. 장면 설명에서 폭력·공포 묘사를 덜어 보세요.",
    "BLOCKLIST": "차단된 표현이 프롬프트에 들어 있습니다. 장면 설명이나 대사에 "
                 "쓴 낱말 중 하나가 걸렸습니다.",
    "SPII": "개인정보로 보이는 내용이 들어 있습니다. 실존 인물의 이름 같은 것이 "
            "들어갔는지 보세요.",
    "RECITATION": "저작물을 그대로 재현하려는 것으로 판단했습니다. 기존 작품의 "
                  "캐릭터나 장면을 그대로 지시하지 않았는지 보세요.",
}


def read_refusals(run_id: str, episode: int = 1, limit: int = 20) -> list[dict[str, Any]]:
    """하네스가 남긴 refusals.jsonl 을 읽어 화면에 쓸 모양으로 돌려준다.

    파일이 없으면 빈 목록이다 — 거절이 한 번도 없었으면 안 만들어지고, 예전
    run 에는 애초에 없다. 없다고 오류로 취급하면 안 된다.
    """
    path = episode_dir(run_id, episode) / "refusals.jsonl"
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            code = str(rec.get("reason") or "UNKNOWN").upper()
            out.append({
                "reason": code,
                "hint": REFUSAL_HINTS.get(code, "모델이 생성을 거절했습니다."),
                # 모델이 직접 한 말. 무엇을 고쳐야 할지는 대개 여기에만 있다.
                "model_said": str(rec.get("model_said") or "")[:400],
                "cut_number": rec.get("cut_number"),
                "unit": rec.get("unit") or "장",
                "description": str(rec.get("description_ko") or "")[:200],
                "timestamp": rec.get("timestamp") or "",
            })
    except OSError:
        return []
    return out[-limit:]


# --------------------------------------------------------------------------- #
# 승인 화면이 보여줄 것
# --------------------------------------------------------------------------- #
#
# 스토리·콘티 확인 화면은 "이대로 진행할까요?" 를 묻는 자리인데, 정작 **무엇을**
# 진행할지를 안 보여주고 있었다. 사람은 게이트가 무엇에 걸렸는지만 읽고
# 찍어서 눌러야 했다 — 확인이 아니라 도박이다.
#
# 두 함수 모두 없는 값에는 관대하다. 승인 화면은 이미 "뭔가 잘 안 된" 자리라
# (게이트가 소진돼서 왔다) 파일이 덜 씌어 있을 수 있는데, 여기서 터지면
# 화면이 아예 안 뜨고 사용자는 진행도 취소도 못 한다.

def story_preview(run_id: str) -> dict[str, Any]:
    """스토리 단계까지 나온 것 — 제목 · 로그라인 · 훅 · 장면들."""
    run_dir = STORY / "runs" / run_id
    scenes_doc = _read_json(run_dir, "scenes.json")
    p1 = _read_json(run_dir, "p1.json")
    p2 = _read_json(run_dir, "p2.json")
    scenes = []
    for s in (scenes_doc.get("scenes") or []):
        if not isinstance(s, dict):
            continue
        scenes.append({
            "no": int(s.get("no") or len(scenes) + 1),
            "one_line": str(s.get("one_line") or "").strip(),
            "text": str(s.get("text") or "").strip(),
            # 무엇이 달라졌는가 — 장면이 이야기를 실제로 움직였는지 보는 값이다.
            "changed": str(s.get("changed") or "").strip(),
        })
    return {
        "title": str(scenes_doc.get("title") or "").strip(),
        "hook": str(scenes_doc.get("hook") or "").strip(),
        "logline": str(p2.get("logline") or "").strip(),
        "character": str(p1.get("name") or "").strip(),
        "personality": str(p1.get("personality") or "").strip(),
        "scenes": scenes,
    }


def board_preview(run_id: str, episode: int = 1) -> dict[str, Any]:
    """콘티 단계까지 나온 것 — 회차 제목과 컷별 대사·연출.

    정식 파일이 없으면 **초안**(epNN_cuts.draft.json)을 읽는다. 게이트 재시도가
    소진되면 하네스가 정식 파일 대신 마지막 시도를 초안으로 남긴다 — 예전에는
    그마저 버려져서, 확인 화면이 "콘티를 확인해 주세요" 라고 말하면서 보여줄
    콘티가 없었다.
    """
    wt = STORY / "runs" / run_id / "webtoon"
    doc = _read_json(wt, f"ep{int(episode):02d}_cuts.json")
    draft = False
    if not doc:
        doc = _read_json(wt, f"ep{int(episode):02d}_cuts.draft.json")
        draft = bool(doc)
    cuts = []
    raw = doc.get("cuts") if isinstance(doc, dict) else doc
    for c in (raw or []):
        if not isinstance(c, dict):
            continue
        cuts.append({
            "no": int(c.get("cut_number") or c.get("no") or len(cuts) + 1),
            "shot": str(c.get("shot") or "").strip(),
            "speaker": str(c.get("speaker") or "").strip(),
            "dialogue": str(c.get("dialogue") or "").strip(),
            "narration": str(c.get("narration") or "").strip(),
            "thought": str(c.get("thought") or "").strip(),
            "sfx": str(c.get("sfx") or "").strip(),
            "description": str(c.get("description") or "").strip(),
        })
    return {
        "title": episode_title(run_id, episode),
        "episode": int(episode),
        "cuts": cuts,
        # 초안이면 화면이 "게이트에 걸린 마지막 시도" 라고 말해 준다 —
        # 통과한 콘티처럼 보이면 안 된다.
        "draft": draft,
    }


def read_art_qa(run_id: str, episode: int = 1) -> dict[int, dict[str, Any]]:
    """하네스의 그림 QA 최종 판정(art_qa.json)을 장 번호별로 돌려준다.

    {장번호: {"rounds": 다시 그린 횟수, "issues": [남은 막는 이슈], ...}}.
    파일이 없으면(QA 를 안 켠 예전 run) 빈 dict — refusals 와 같은 취급이다.
    결과 화면이 이걸로 "검수에서 잡았지만 못 고친 것"을 장 밑에 표시하고,
    다시 그리기(사용자 피드백)로 잇는다.
    """
    path = episode_dir(run_id, episode) / "art_qa.json"
    if not path.exists():
        return {}
    try:
        units = (json.loads(path.read_text(encoding="utf-8")) or {}).get("units") or {}
    except (OSError, ValueError):
        return {}
    out: dict[int, dict[str, Any]] = {}
    for rec in units.values():
        if not isinstance(rec, dict):
            continue
        try:
            no = int(rec.get("no") or 0)
        except (TypeError, ValueError):
            continue
        if no <= 0:
            continue
        # 같은 장을 여러 후보(c1·c2)로 뽑은 경우 마지막 판정이 이긴다 —
        # 제품은 후보 1장이라 실질적으로 겹치지 않는다.
        out[no] = {
            "rounds": int(rec.get("rounds") or 0),
            "checked": bool(rec.get("checked")),
            "issues": [{"what": str(i.get("what") or "")[:200],
                        "kind": str(i.get("kind") or "artifact")}
                       for i in (rec.get("issues") or []) if isinstance(i, dict)],
        }
    return out


def art_qa_summary(run_id: str, episode: int = 1) -> dict[str, Any]:
    """그림 QA 가 무엇을 했는지 한 눈에. 전문 모드의 검수 확인 화면이 쓴다.

    결과 화면의 노트(read_art_qa)와 보는 각도가 다르다. 노트는 "못 고친 것"만
    말한다 — 사용자가 손댈 것이 그것뿐이라서다. 여기는 **다시 그려서 고친
    것까지** 센다. 검수를 켜 둔 사람이 알고 싶은 것은 남은 흠만이 아니라
    "검수가 실제로 일을 했는가" 이기 때문이다.

    fixed 는 어림이다 — 다시 그린 뒤 이슈가 안 남았으면 고쳐진 것으로 본다.
    하네스가 판마다의 판정을 안 남기므로 그보다 정확히는 셀 수 없다.
    """
    units = read_art_qa(run_id, episode)
    fixed, unresolved = [], []
    for no in sorted(units):
        rec = units[no]
        if rec.get("issues"):
            unresolved.append({"scene": no, "issues": rec["issues"],
                               "rounds": rec.get("rounds") or 0})
        elif rec.get("rounds"):
            fixed.append({"scene": no, "rounds": rec["rounds"]})
    return {
        "checked": sum(1 for r in units.values() if r.get("checked")),
        "total": len(units),
        "fixed": fixed,
        "unresolved": unresolved,
    }


# --------------------------------------------------------------------------- #
# 사용자 피드백
# --------------------------------------------------------------------------- #
#
# 지금까지 피드백은 두 갈래로 흩어져 있었다. 화면에서 받은 말은 그 자리에서
# 프롬프트에 얹혀 쓰이고 사라졌고(다시 그리기), 사람이 인터뷰에서 들은 말은
# story-harness/docs/user_feedback_summary.md 에 손으로 옮겨 적었다. 앞엣것은
# 남지 않아 무엇이 자주 나오는지 셀 수 없었고, 뒤엣것은 앱과 이어져 있지 않다.
#
# 여기서 하는 일은 화면에서 받은 말을 **run 폴더에 남기는 것**이다. DB 는 아직
# 없다 — refusals.jsonl 과 같은 자리에 같은 방식으로 한 줄씩 쌓는다.

# 고를 수 있는 항목. 자유 입력만 받으면 대부분 아무것도 안 적고 넘어가고,
# 적더라도 집계가 안 된다. 항목은 지어낸 것이 아니라
# story-harness/docs/user_feedback_summary.md 에 실제로 올라온 말에서 뽑았다.
FEEDBACK_TAGS: dict[str, list[dict[str, str]]] = {
    "sheet": [
        {"id": "face", "label": "얼굴이 원본과 달라요"},
        {"id": "outfit", "label": "옷·장신구가 달라요"},
        {"id": "hair", "label": "머리 모양이 달라요"},
        {"id": "prop", "label": "소품(무기·모자 등)이 달라요"},
        {"id": "age", "label": "나이대가 안 맞아요"},
        {"id": "style", "label": "그림체가 생각과 달라요"},
        {"id": "ratio", "label": "등신 비율이 안 맞아요"},
        {"id": "etc", "label": "기타"},
    ],
    "story": [
        {"id": "genre", "label": "고른 장르 느낌이 안 나요"},
        {"id": "personality", "label": "성격이 설정과 달라요"},
        {"id": "logic", "label": "개연성이 없어요"},
        {"id": "line", "label": "대사가 어색해요"},
        {"id": "name", "label": "이름이 잘못 나와요"},
        {"id": "pace", "label": "전개가 급하거나 지루해요"},
        {"id": "etc", "label": "기타"},
    ],
    "board": [
        {"id": "flow", "label": "컷 흐름이 끊겨요"},
        {"id": "missing", "label": "중요한 장면이 빠졌어요"},
        {"id": "angle", "label": "컷 앵글이 어색해요"},
        {"id": "balance", "label": "컷 분량 배분이 이상해요"},
        {"id": "line", "label": "대사 배치가 어색해요"},
        {"id": "etc", "label": "기타"},
    ],
    "scene": [
        {"id": "character", "label": "캐릭터가 이상해요"},
        {"id": "background", "label": "배경이 이상해요"},
        {"id": "pose", "label": "포즈가 어색해요"},
        {"id": "face", "label": "표정이 안 맞아요"},
        {"id": "text", "label": "글자가 깨져요"},
        {"id": "light", "label": "색·조명이 별로예요"},
        {"id": "artifact", "label": "이상한 게 그려졌어요"},
        {"id": "etc", "label": "기타"},
    ],
}

# 어느 항목이 어느 단계 것인지. 화면이 보낸 id 를 그대로 믿지 않는다.
_TAG_LABELS = {stage: {t["id"]: t["label"] for t in tags}
               for stage, tags in FEEDBACK_TAGS.items()}

FEEDBACK_TEXT_MAX = 500
_feedback_lock = threading.Lock()

# ---- 작가 규칙 (user memory) ------------------------------------------------
#
# 작가가 작품마다 직접 선언하는 규칙. 피드백(위)이 "지난 결과에 대한 말"이라면
# 이것은 "앞으로 모든 생성이 지킬 것" 이다. 하네스(story.py·webtoon.py·run.py)가
# runs/<run_id>/memory.json 을 읽어 매 단계 프롬프트에 싣는다.
#   always  — 항상 실린다 ("초롱은 존댓말을 안 쓴다" 같은 작품 전체 규칙)
#   keyword — 태그가 그 단계 문맥에 나타날 때만 ("북부대공 → 문장은 은빛 늑대")
# 글자수 상한은 하네스의 것(story.MEMORY_*_LIMIT)과 같은 값이어야 한다 —
# 화면이 더 받아 놓고 하네스가 자르면 작가는 왜 안 실리는지 모른다.
MEMORY_ALWAYS_MAX = 500
MEMORY_KEYWORD_MAX = 1500


def memory_path(run_id: str) -> Path:
    return STORY / "runs" / run_id / "memory.json"


def read_memory(run_id: str) -> dict[str, Any]:
    """이 작품의 규칙. 없으면 빈 구조 — 화면이 빈 편집칸을 그리면 된다."""
    empty: dict[str, Any] = {"always": [], "keyword": []}
    got = _read_json(STORY / "runs" / run_id, "memory.json")
    if not isinstance(got, dict):
        return empty
    return {"always": [e for e in (got.get("always") or [])
                       if isinstance(e, dict) and str(e.get("text") or "").strip()],
            "keyword": [e for e in (got.get("keyword") or [])
                        if isinstance(e, dict) and str(e.get("text") or "").strip()
                        and [t for t in (e.get("tags") or []) if str(t or "").strip()]]}


def write_memory(run_id: str, data: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """규칙을 저장한다. (정리된 규칙, 오류 문구) — 오류면 저장 안 한다.

    검증을 여기서 하는 이유: 하네스는 상한 초과분을 조용히 자른다(실행을
    멈추지 않으려고). 화면에서는 자르지 말고 **저장을 거절**해야 작가가 자기
    글이 어디까지 실리는지 안다.
    """
    always, keyword = [], []
    a_used = 0
    for e in (data.get("always") or []):
        t = " ".join(str((e or {}).get("text") or "").split())
        if not t:
            continue
        a_used += len(t)
        always.append({"text": t})
    if a_used > MEMORY_ALWAYS_MAX:
        return {}, f"항상 적용 규칙이 {a_used}자입니다 ({MEMORY_ALWAYS_MAX}자까지)"
    k_used = 0
    for e in (data.get("keyword") or []):
        t = " ".join(str((e or {}).get("text") or "").split())
        tags = [str(x).strip() for x in ((e or {}).get("tags") or [])
                if str(x or "").strip()]
        if not t:
            continue
        if not tags:
            return {}, f"키워드 규칙 '{t[:20]}…' 에 키워드가 없습니다"
        k_used += len(t)
        keyword.append({"tags": tags, "text": t})
    if k_used > MEMORY_KEYWORD_MAX:
        return {}, f"키워드 규칙이 {k_used}자입니다 ({MEMORY_KEYWORD_MAX}자까지)"
    cleaned = {"always": always, "keyword": keyword}
    path = memory_path(run_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    except OSError as exc:
        return {}, f"저장하지 못했습니다: {exc}"
    return cleaned, ""


def feedback_path(run_id: str) -> Path:
    return STORY / "runs" / run_id / "feedback.jsonl"


def clean_tags(stage: str, raw: Any) -> list[str]:
    """화면이 보낸 항목 id 중 이 단계에 실제로 있는 것만. 순서는 표시 순서."""
    known = _TAG_LABELS.get(stage) or {}
    picked = {str(t) for t in raw} if isinstance(raw, list) else set()
    return [t["id"] for t in FEEDBACK_TAGS.get(stage, []) if t["id"] in picked]


def append_feedback(run_id: str, stage: str, tags: list[str], text: str,
                    scene_no: int | None = None, decision: str = "") -> None:
    """피드백 한 줄을 run 폴더에 남긴다.

    남기지 못해도 작업은 그대로 간다 — 기록은 곁다리다. 사용자가 다시 그리기를
    눌렀는데 디스크가 꽉 찼다는 이유로 그리기가 멈추면 그게 더 나쁘다.
    """
    if not run_id or not (tags or text):
        return                          # 아무것도 안 고른 채 그냥 누른 경우
    rec = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "stage": stage,
        "decision": decision,
        "tags": tags,
        "tag_labels": [(_TAG_LABELS.get(stage) or {}).get(t, t) for t in tags],
        "text": text[:FEEDBACK_TEXT_MAX],
    }
    if scene_no is not None:
        rec["scene"] = int(scene_no)
    path = feedback_path(run_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _feedback_lock, path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def read_feedback(run_id: str) -> list[dict[str, Any]]:
    """이 run 에 쌓인 피드백 전부. 없으면 빈 목록 (옛 run 에는 파일이 없다)."""
    path = feedback_path(run_id)
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    except OSError:
        return []
    return out


def _carry_feedback(old_run_id: str, new_run_id: str) -> None:
    """옛 run 에 쌓인 피드백을 새 run 앞에 붙인다 (이야기를 다시 만들 때)."""
    old = read_feedback(old_run_id)
    if not old:
        return
    path = feedback_path(new_run_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _feedback_lock, path.open("a", encoding="utf-8") as fh:
            for rec in old:
                rec = dict(rec, carried_from=old_run_id)
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def author_note(stage: str, tags: list[str], text: str) -> str:
    """고른 항목 + 자유 입력을 모델에게 넘길 한 덩이 글로.

    항목만 고르고 아무 말도 안 적는 사람이 대부분이다. 그때도 "무엇이
    불만인지"는 넘어가야 하므로 항목 이름 자체를 문장으로 쓴다.
    """
    labels = [(_TAG_LABELS.get(stage) or {}).get(t, t) for t in tags]
    parts = []
    if labels:
        parts.append("작가가 고른 항목: " + ", ".join(labels))
    note = " ".join(str(text or "").split())
    if note:
        parts.append("작가가 적은 말: " + note)
    return "\n".join(parts)


def unit_image(run_id: str, no: int, episode: int = 1) -> Path | None:
    """장(Scene) 하나의 그림. MODE 를 컷으로 되돌려도 같은 함수로 찾는다.

    Scene 모드는 `scene_S+/scene3_c1.png`, 컷 모드는 `S+/cut3_c1.png` 다.
    조건은 S+ 가 기본이고, 시트가 없어 A 로 떨어진 옛 실행도 받아 준다.

    **`picks.csv` 에 채택 기록이 있으면 그 후보를 쓴다.** 지금 제품은 후보를
    1장만 뽑아서 `_c1` 고정과 다를 것이 없지만(#113), 나중에 후보를 여러 장
    뽑게 되면 이 함수가 "사람이 고른 후보"가 아니라 "무조건 1번 후보"를
    화면·최종본에 내보내게 된다. `folder` 가 곧 picks.csv 의 condition 값이다
    (컷 모드는 `cond` 그대로, Scene 모드는 `scene_{cond}` — run.scene_cond 와
    같은 규칙). 기록이 없거나 그 파일이 없으면 c1 로 떨어진다.
    """
    ep = episode_dir(run_id, episode)
    picks = report.load_picks(ep)
    for cond in (CONDITION, "S", "A"):
        for folder, stem in ((f"scene_{cond}", "scene"), (cond, "cut")):
            k = picks.get((folder, no)) or 1
            p = ep / folder / f"{stem}{no}_c{k}.png"
            if p.exists():
                return p
            if k != 1:
                p1 = ep / folder / f"{stem}{no}_c1.png"
                if p1.exists():
                    return p1
    return None


def planned_pages(run_id: str, episode: int = 1) -> int:
    """이 회차가 필요로 하는 이미지 장 수 — 콘티 뒤 scenes.json 의 묶음 수.

    scenes.json 은 화당 1회, --cuts 로 일부만 그려도 **전체** 묶음을 캐시한다
    (run.py generate_scenes). 그래서 미리보기만 그린 시점에도 남은 장 수를
    정확히 알 수 있다 — "마저 그리기" 값이 여기서 나온다. 없으면 0.
    """
    grouping = _read_json(episode_dir(run_id, episode), "scenes.json").get("scenes") or []
    return len(grouping)


def drawn_units(run_id: str, episode: int = 1) -> int:
    """지금까지 그려 둔 장(또는 컷)이 몇 개인가.

    미리보기는 앞 3컷(=한 장)만 그리므로 보통 1 이다. "다음 장면"을 누를
    때마다 하나씩 는다. 번호는 1부터 이어지므로, 빈 자리가 나오면 거기서
    센 것을 그대로 쓴다 — 중간이 비어 있으면 그 앞까지만 그린 것이다.
    """
    n = 0
    while unit_image(run_id, n + 1, episode) is not None:
        n += 1
        if n > 500:                      # 망가진 폴더에서 무한히 돌지 않게
            break
    return n


# --------------------------------------------------------------------------- #
# 공유
# --------------------------------------------------------------------------- #
#
# 공유는 두 갈래로 나간다. 하나는 **링크**(카톡·트위터에 붙이면 미리보기가
# 뜬다), 하나는 **그림 파일**(폰의 공유 시트로 바로 내보낸다).
#
# 링크 쪽이 서버 일이다. SNS 미리보기를 만드는 크롤러는 자바스크립트를 안
# 돌리므로, 화면이 그리는 제목·그림은 크롤러에게 안 보인다 — 서버가 HTML 을
# 내보낼 때 <head> 에 미리 박아 줘야 한다(serve.py 의 og_html).
#
# 계정이 없어서 "링크를 아는 사람만" 같은 접근 권한은 아직 못 만든다. 지금은
# run_id 를 아는 사람이 곧 볼 수 있는 사람이다 — 주소에 6자리 무작위가 붙어
# 있어서 찍어서 맞히기는 어렵지만, **비밀이 아니다.** 권한·만료는 회원 기능이
# 생긴 뒤의 일이다(#66).

def share_meta(run_id: str, episode: int = 1) -> dict[str, Any] | None:
    """공유 링크의 미리보기에 실을 것. 그림이 하나도 없으면 None.

    list_runs() 를 안 쓴다 — 그쪽은 runs/ 를 통째로 훑어서 목록을 만드는
    함수라, 한 편의 미리보기를 그리려고 부르면 남의 폴더를 전부 읽는다.
    """
    run_dir = STORY / "runs" / run_id
    if not run_dir.is_dir():
        return None
    ep = int(episode or 1)
    if ep not in made_episodes(run_id):
        return None
    # 표지로 쓸 장. 1번이 있다고 칠 수 없다 — 3·4번만 뽑아 둔 run 이 흔하다.
    cover = next((n for n in range(1, 13) if unit_image(run_id, n, ep)), None)
    if cover is None:
        return None                        # 그릴 것이 없으면 공유할 것도 없다
    p1 = _read_json(run_dir, "p1.json")
    p2 = _read_json(run_dir, "p2.json")
    return {
        "run_id": run_id,
        "episode": ep,
        "title": episode_title(run_id, ep) or f"{ep}화",
        "character": str(p1.get("name") or ""),
        "genre": str(_read_json(run_dir, "meta.json").get("input", {}).get("genre") or ""),
        "logline": str(p2.get("logline") or ""),
        "cover_page": cover,
    }


def planned_cuts(run_id: str, episode: int = 1) -> int:
    """콘티가 계획한 컷 수. 못 읽으면 0 — 그때는 상한을 안 건다."""
    for name in ("scenes.json", "episode.json", "board.json"):
        data = _read_json(episode_dir(run_id, episode), name)
        cuts = data.get("cuts") if isinstance(data, dict) else None
        if isinstance(cuts, list) and cuts:
            return len(cuts)
        scenes = data.get("scenes") if isinstance(data, dict) else None
        if isinstance(scenes, list) and scenes:
            total = 0
            for sc in scenes:
                nums = (sc or {}).get("cut_numbers") or []
                total += len(nums)
            if total:
                return total
    return 0


def run_mode(run_id: str, episode: int = 1) -> str:
    """이 실행이 어느 모드로 그려졌는가 — "scene" | "cut".

    폼 값이 아니라 **떨어진 파일**을 본다. 다시 그리기는 job 이 사라진 뒤에도
    (서버를 껐다 켜거나, 하네스를 직접 돌린 실행에서도) 눌릴 수 있어서, 그때
    모드를 틀리면 run.py 가 있지도 않은 장을 찾거나 컷을 통째로 다시 묶는다.
    아무것도 없으면 기본값(scene)으로 본다 — 지금까지의 방식이다.
    """
    ep = episode_dir(run_id, episode)
    for cond in (CONDITION, "S", "A"):
        if any((ep / f"scene_{cond}").glob("scene*_c*.png")):
            return "scene"
        if any((ep / cond).glob("cut*_c*.png")):
            return "cut"
    return MODE


# --------------------------------------------------------------------------- #
# 장(Scene) 다시 그리기
#
# 이미지는 컷이 아니라 **장 단위**로 굽는다 — 한 장에 3컷이 함께 그려진다.
# 그래서 "컷 하나만" 다시 뽑는 길은 없고, 다시 그리는 최소 단위는 장이다.
#
# 지키는 것 두 가지:
#   1. 새로 그리다 실패해도 **이미 있던 그림은 그대로 남는다.** 다시 그리기를
#      눌렀다가 원본까지 잃으면 누구도 그 버튼을 두 번 누르지 않는다.
#   2. 이전 판을 버리지 않는다. 새로 뽑은 게 더 나쁠 수 있고, 그건 눌러 보기
#      전에는 모른다.
# --------------------------------------------------------------------------- #

def scene_cut_range(run_id: str, scene_no: int, episode: int = 1) -> tuple[int, int] | None:
    """그 장에 들어 있는 컷 번호의 처음과 끝. run.py 의 --cuts 에 그대로 준다.

    scene 모드에서 --cuts 는 "그 컷이 들어 있는 장"을 고르므로, 장 하나를
    다시 그리려면 그 장의 컷 범위를 주면 된다.
    """
    grouping = _read_json(episode_dir(run_id, episode), "scenes.json").get("scenes") or []
    for sc in grouping:
        if int(sc.get("scene_number") or 0) != int(scene_no):
            continue
        nums = [int(n) for n in (sc.get("cut_numbers") or [])]
        if nums:
            return min(nums), max(nums)
    # scenes.json 이 없는 옛 실행 — editor_data 와 같은 규칙으로 떨어진다
    # (장 번호 = 컷 번호).
    cuts = _read_json(STORY / "runs" / run_id / "webtoon",
                      cuts_filename(episode)).get("cuts") or []
    if any(int(c.get("cut_number") or 0) == int(scene_no) for c in cuts):
        return int(scene_no), int(scene_no)
    return None


def _versions_dir(run_id: str, episode: int = 1) -> Path:
    return episode_dir(run_id, episode) / "versions"


def _ep_q(episode: int) -> str:
    """주소에 붙일 회차 꼬리표. 1화는 안 붙인다 — 예전 주소가 그대로 살아야 한다."""
    return "" if int(episode) == 1 else f"?ep={int(episode)}"


def scene_versions(run_id: str, scene_no: int,
                   episode: int = 1) -> list[dict[str, Any]]:
    """그 장의 지난 판 목록. 최신이 앞에 온다."""
    vdir = _versions_dir(run_id, episode)
    if not vdir.exists():
        return []
    out = []
    for p in vdir.glob(f"scene{int(scene_no)}.v*.png"):
        try:
            v = int(p.stem.rsplit(".v", 1)[1])
        except (ValueError, IndexError):
            continue
        out.append({"version": v, "at": p.stat().st_mtime,
                    "url": f"/api/runs/{run_id}/scenes/{scene_no}/versions/{v}"
                           + _ep_q(episode)})
    return sorted(out, key=lambda d: -d["version"])


def _next_version(run_id: str, scene_no: int, episode: int = 1) -> int:
    got = scene_versions(run_id, scene_no, episode)
    return (got[0]["version"] + 1) if got else 1


def archive_scene(run_id: str, scene_no: int, episode: int = 1) -> int | None:
    """지금 걸려 있는 그림을 판본으로 떠 둔다. 새로 굽기 **직전**에 부른다.

    **이미 판본으로 있는 그림이면 새로 뜨지 않고 그 번호를 돌려준다.**
    이게 없던 동안, 지난 판을 눌러 보기만 해도 판본이 계속 늘어났다 — v1~v3 를
    번갈아 눌러 보면 v4·v5·v6 이 생기고, 그 셋은 v1~v3 와 픽셀 하나까지 같은
    그림이었다. 사용자가 본 것이 그것이다 ("갑자기 v7 v8 이런 식으로 생성").
    되돌리기가 되돌리기 전 그림을 떠 두는 것 자체는 맞다 — 되돌린 것을 다시
    되돌릴 수 있어야 하니까. 다만 그 그림이 이미 판본에 있으면 뜰 것이 없다.

    돌려주는 번호는 실패했을 때 되살릴 자리라(version_path), 기존 번호를
    돌려줘도 복구는 그대로 된다.
    """
    src = unit_image(run_id, scene_no, episode)
    if not src:
        return None
    vdir = _versions_dir(run_id, episode)
    vdir.mkdir(parents=True, exist_ok=True)
    same = _version_matching(run_id, scene_no, src, episode)
    if same is not None:
        return same
    v = _next_version(run_id, scene_no, episode)
    shutil.copy2(src, vdir / f"scene{int(scene_no)}.v{v}.png")
    return v


def _version_matching(run_id: str, scene_no: int, src: Path,
                      episode: int = 1) -> int | None:
    """이 그림과 **내용이 같은** 판본이 이미 있으면 그 번호. 없으면 None.

    크기부터 본다 — 판본이 수십 장이어도 대개 첫 비교에서 갈린다. 크기가 같을
    때만 바이트를 읽는다. 읽다 실패하면 "같지 않다"로 본다(판본을 하나 더 뜨는
    것이 지우는 것보다 안전하다).
    """
    try:
        size = src.stat().st_size
        blob = None
        for got in scene_versions(run_id, scene_no, episode):
            p = version_path(run_id, scene_no, got["version"], episode)
            if p is None or p.stat().st_size != size:
                continue
            if blob is None:
                blob = src.read_bytes()
            if p.read_bytes() == blob:
                return int(got["version"])
    except OSError:
        return None
    return None


def version_path(run_id: str, scene_no: int, version: int,
                 episode: int = 1) -> Path | None:
    p = _versions_dir(run_id, episode) / f"scene{int(scene_no)}.v{int(version)}.png"
    return p if p.exists() else None


def revert_scene(run_id: str, scene_no: int, version: int,
                 episode: int = 1) -> bool:
    """지난 판으로 되돌린다. 되돌리기 전의 그림도 판본으로 남긴다 —
    되돌린 것을 다시 되돌릴 수 있어야 한다."""
    src = version_path(run_id, scene_no, version, episode)
    dest = unit_image(run_id, scene_no, episode)
    if not src or not dest:
        return False
    archive_scene(run_id, scene_no, episode)
    shutil.copy2(src, dest)
    # copy2 는 **판본 파일의 옛 mtime 까지** 복사한다. 그대로 두면 되돌린
    # 그림이 캐시(JPEG)보다 오래된 파일이 되어, thumbnail() 이 "캐시가 더
    # 새것" 이라며 옛 그림을 계속 내려보낸다 — 화면상 되돌리기가 아무 일도
    # 안 한 것처럼 보인다. job 폴더 캐시는 _clear_cache 가 못 보는 곳이라
    # 지우는 것으로는 부족하고, 시간을 지금으로 찍어야 양쪽 캐시가 다 진다.
    os.utime(dest, None)
    _clear_cache(run_id, scene_no, episode)
    return True


def _clear_cache(run_id: str, scene_no: int, episode: int = 1) -> None:
    """줄여 둔 그림을 지운다. 안 지우면 새로 그려도 화면은 옛 그림을 계속 준다
    (thumbnail 이 mtime 으로 캐시를 판단하는데, job 폴더 캐시는 여기서 못 본다)."""
    for cache in episode_dir(run_id, episode).glob("cache/page*"):
        if cache.stem.startswith(f"page{int(scene_no)}_"):
            cache.unlink(missing_ok=True)


def _append_to_extra(text: str, cond: str, note: str) -> str:
    """조건의 `extra:` 블록 **끝에** 한 줄 덧붙인다.

    S+ 의 extra 는 블록 스칼라(`>-`)이고, 그 안에 시트를 어떻게 보라는 지침이
    통째로 들어 있다. 통으로 바꾸면 그 지침이 사라져서 다시 그린 장만 얼굴이
    달라진다 — 덮어쓰지 않고 뒤에 붙이는 이유다.
    """
    lines = text.splitlines(keepends=True)
    # 조건 블록의 시작. 키가 S+ 처럼 따옴표가 붙어 있을 수도 있다.
    head = re.compile(rf'^  "?{re.escape(cond)}"?:\s*$')
    start = next((i for i, l in enumerate(lines) if head.match(l.rstrip("\n"))), -1)
    if start < 0:
        return text
    # 그 블록 안의 extra 줄.
    ex = -1
    for i in range(start + 1, len(lines)):
        s = lines[i].rstrip("\n")
        if s and not s.startswith("    "):
            break                      # 다음 조건으로 넘어갔다
        if re.match(r"^    extra:", s):
            ex = i
            break
    if ex < 0:
        return text
    if not re.match(r"^    extra:\s*[>|]", lines[ex].rstrip("\n")):
        return text                    # 블록 스칼라가 아니면 건드리지 않는다
    # 블록 스칼라 본문이 끝나는 자리를 찾는다 (더 깊이 들여쓴 줄들).
    end = ex + 1
    while end < len(lines):
        s = lines[end].rstrip("\n")
        if s.strip() and not s.startswith("      "):
            break
        end += 1
    lines.insert(end, f"      {note}\n")
    return "".join(lines)


def _origin_config(run_id: str) -> Path | None:
    """그 run 을 만들 때 쓴 config.yaml. 못 찾으면 None.

    다시 그릴 때 config 를 원본에서 새로 만들면 **그림체가 바뀐다** —
    build_config 가 style_default 를 덮어쓰기 때문이다. 한 장만 다른 그림체로
    그려지면 그게 재생성 실패보다 나쁘다. 그래서 그 실행이 실제로 쓴 config 를
    먼저 찾는다.
    """
    if not JOBS_DIR.is_dir():
        return None
    # **최신 job 부터** 본다. 같은 run_id 를 가리키는 job 폴더가 둘 이상일 수
    # 있고(1화를 만든 job, 2화를 이어 만든 job), 예전에는 정렬 없이 훑어 첫
    # 매치를 썼다 — 어느 config 를 물려받을지가 OS 의 디렉터리 순서에 달려
    # 있었다(#114). job_id 는 `YYYYmmdd-HHMMSS-xxxx` 라 이름 역순이 곧 최신순이다.
    for job_dir in sorted(JOBS_DIR.iterdir(), reverse=True):
        marker = job_dir / "run_id.txt"
        cfg = job_dir / "config.yaml"
        if not (marker.exists() and cfg.exists()):
            continue
        try:
            if marker.read_text(encoding="utf-8").strip() == run_id:
                return cfg
        except OSError:
            continue
    return None


# 다시 그리기에서 고를 수 있는 글자 모드. 하네스의 scene.lettering 값 그대로다
# (webtoon-harness/scenegen.py 의 LETTERING_MODES).
#
# 2026-08-23 "overlay"에서 "none"으로 바꿨다. overlay는 말풍선 **모양**은
# 그대로 그리고 그 안 글자만 비우는 값인데, 그 자리를 채우는 쪽
# (webtoon-harness/bubbles.py)은 review.html에서 사람이 내려받은
# bubbles.json을 --view로 합성하는 별도 도구다 — 랜딩의 다시 그리기 경로
# 어디도 그걸 부르지 않는다. 그래서 텅 빈 말풍선 껍데기만 영영 남았다
# ("글자는 없고 말풍선은 있어서 더 어색하다"는 실사용자 지적). "none"은
# 말풍선 자체를 안 그린다 — 화면·편집실 문구("말풍선 없이 그립니다")가
# 이미 이 동작을 약속하고 있었으니, 실제 동작을 그 말에 맞춘 것이기도 하다.
REGEN_LETTERING = "none"


def origin_form(run_id: str) -> dict[str, Any]:
    """그 작품을 만들 때 사람이 넣은 입력(input.json). 못 찾으면 빈 dict.

    이어 만들 때 그림체·등신·연출 모드를 여기서 물려받는다 — 다시 고르게 하면
    같은 작품의 회차마다 그림이 달라진다. _origin_config 과 같은 방식으로 job 을
    찾는다(run_id.txt 가 이 run 을 가리키는 폴더).
    """
    if not JOBS_DIR.is_dir():
        return {}
    for job_dir in sorted(JOBS_DIR.iterdir(), reverse=True):   # 최신 job 부터 (#114)
        marker = job_dir / "run_id.txt"
        if not marker.exists():
            continue
        try:
            if marker.read_text(encoding="utf-8").strip() != run_id:
                continue
        except OSError:
            continue
        got = _read_json(job_dir, "input.json")
        if got:
            return got
    return {}


def regen_config(run_id: str, feedback: str, style: str = "",
                 textless: bool = False, episode: int = 1) -> Path:
    """다시 그리기 전용 config. 피드백을 조건의 {extra} 뒤에 얹는다.

    하네스를 고치지 않는다 — run.py 의 프롬프트 틀에 이미 {extra} 자리가 있고
    그 값은 config 의 조건에서 온다(cond_extra). 그래서 config 사본만 만들면
    사용자가 쓴 말이 그림 프롬프트에 그대로 붙는다.
    """
    out_dir = episode_dir(run_id, episode) / "regen"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "config.yaml"
    # 예전에는 job 의 config.yaml 사본을 그대로 썼다. 그림체가 안 바뀌는 것은
    # 좋았는데, **프롬프트 문구까지 작품을 만들던 날짜에 얼어붙었다** — 시트
    # 참조를 강하게 고쳐도(2026-08-23, S+ 문구) 기존 작품의 다시 그리기는
    # 영원히 옛 문구로 돌았다. 실제로 그렇게 됐다: "시트와 옷이 다르다"는
    # 피드백을 받고 다시 그렸는데, 그 재생성이 문제의 옛 문구로 그려졌다.
    #
    # 그래서 뒤집는다: config 는 **지금 코드로 새로 굽고**, 사용자가 고른
    # 것(그림체·등신·장르·연출 모드)만 원래 입력(input.json)에서 이식한다.
    # "그림체가 바뀌면 안 된다"는 원래 이유는 이걸로 그대로 지켜진다 —
    # build_config 의 style 이 그 사용자의 선택이니까.
    form = origin_form(run_id)
    if form:
        build_config(out_dir,
                     str(form.get("style") or style or "webtoon"),
                     head_ratio=str(form.get("head_ratio") or "").strip().lower(),
                     genre=str(form.get("genre") or ""),
                     mode=layout_mode(form))
    else:
        # 하네스를 직접 돌린 run 이라 폼이 없다. 그림체는 호출자가 준 것을
        # 쓴다(안 주면 하네스 기본값).
        build_config(out_dir, style or next(iter(STYLES)))
    text = path.read_text(encoding="utf-8")
    note = " ".join(str(feedback or "").split())
    if note:
        # 줄바꿈만 지운다. 블록 스칼라 안이라 따옴표는 그대로 둬도 되고,
        # 오히려 이스케이프하면 그 글자가 프롬프트에 그대로 나간다.
        text = _append_to_extra(text, CONDITION,
                                f"Revision requested by the author: {note}")
    if textless:
        # build_config 가 in_image 로 되돌려 둔 값을 다시 덮는다 — 같은 자리를
        # 같은 정규식으로 바꾸는 것이라 build_config 의 규칙과 짝이 맞는다.
        text = re.sub(r"(?m)^  lettering:.*$",
                      f"  lettering: {REGEN_LETTERING}", text, count=1)
    path.write_text(text, encoding="utf-8")
    return path


def zone_list(run_id: str) -> list[dict[str, Any]]:
    """이 실행이 쓰는 존(배경) 목록과 그 존을 쓰는 컷·장.

    **배경은 이미지로 굽지 않는다.** 한 번 구운 배경을 모든 컷이 참조하면 그
    안에 잘못 들어간 것(자판기 위의 머그컵)이 화 전체에 박히고, 되돌리려면 그
    존의 컷을 전부 다시 뽑아야 한다 — 실제로 그렇게 났고, 그래서 하네스는
    존을 **글로** 넘긴다(charsheet.load_zone_text).

    그러면 관리할 자산은 이미지가 아니라 **서술 한 줄**이다. 여기서 하는 일은
    그 한 줄이 어디에 쓰이는지 보여 주는 것뿐이다 — 틀린 곳을 찾으면
    series.json 한 줄을 고치면 되고, 다시 구울 자산이 없다.
    """
    run_dir = STORY / "runs" / run_id
    zones = {}
    for z in (_read_json(run_dir / "webtoon", "series.json").get("zones") or []):
        if not isinstance(z, dict):
            continue
        zid = str(z.get("zone_id") or "").strip()
        if zid:
            zones[zid] = {"zone_id": zid,
                          "label": str(z.get("label") or "").strip(),
                          "cuts": [], "scenes": []}

    by_cut = {}
    for c in (_read_json(run_dir / "webtoon", "ep01_cuts.json").get("cuts") or []):
        no = int(c.get("cut_number") or 0)
        zid = str(c.get("zone") or "").strip()
        if not no or not zid:
            continue
        by_cut[no] = zid
        # series.json 에 없는 존을 컷이 가리킬 수 있다. 그래도 목록에서 지우지
        # 않는다 — 서술이 비어 있다는 것 자체가 고칠 거리다.
        zones.setdefault(zid, {"zone_id": zid, "label": "", "cuts": [], "scenes": []})
        zones[zid]["cuts"].append(no)

    grouping = _read_json(episode_dir(run_id), "scenes.json").get("scenes") or []
    for sc in grouping:
        nums = [int(n) for n in (sc.get("cut_numbers") or [])]
        kinds = {by_cut.get(n) for n in nums} - {None}
        # 한 장에 두 존이 섞이면 하네스가 존 서술을 아예 안 붙인다
        # (scenegen.scene_zone). 그 사실을 그대로 보여 준다.
        if len(kinds) == 1:
            zones[kinds.pop()]["scenes"].append(int(sc.get("scene_number") or 0))

    return sorted(zones.values(), key=lambda z: (z["cuts"] or [999])[0])


@dataclass
class Regen:
    """장 하나를 다시 그리는 작업. 전체 파이프라인 Job 과 달리 단계가 없다."""
    id: str
    run_id: str
    scene_no: int
    episode: int = 1
    feedback: str = ""
    textless: bool = False                  # 말풍선까지 없이 그림만 (REGEN_LETTERING)
    status: str = "queued"                  # queued / running / done / error
    error: str = ""
    note: str = ""
    version: int | None = None              # 되돌아갈 수 있는 직전 판
    started_at: float = 0.0
    finished_at: float = 0.0
    _proc: subprocess.Popen | None = field(default=None, repr=False)
    _cancel: bool = False

    def snapshot(self) -> dict[str, Any]:
        return {"id": self.id, "run_id": self.run_id, "scene": self.scene_no,
                "episode": self.episode,
                "status": self.status, "error": self.error, "note": self.note,
                "version": self.version, "textless": self.textless,
                "image": f"/api/runs/{self.run_id}/page/{self.scene_no}"
                         + _ep_q(self.episode),
                "versions": scene_versions(self.run_id, self.scene_no, self.episode)}

    def cancel(self) -> None:
        self._cancel = True
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()


class RegenRunner:
    """다시 그리기 작업들. 한 번에 하나만 돌린다 — 같은 run 의 두 장을 동시에
    구우면 직전 장을 참조하는 S+ 조건이 서로를 덮어쓴다."""

    def __init__(self) -> None:
        self.jobs: dict[str, Regen] = {}
        self._lock = threading.Lock()
        self._gate = threading.Semaphore(1)

    # 끝난 작업을 몇 개까지 들고 있을까. 화면이 끝난 뒤에도 결과를 한 번 더
    # 물어볼 수 있어야 해서(폴링이 늦게 도착한다) 바로 버리지는 않는다. 다만
    # 예전에는 **아무것도 안 버렸다** — 서버를 하루 켜 두고 다시 그리기를 계속
    # 누르면 메모리가 계속 늘었다(#114).
    KEEP_FINISHED = 50

    def get(self, rid: str) -> Regen | None:
        return self.jobs.get(rid)

    def _prune(self) -> None:
        """끝난 작업 중 오래된 것부터 버린다. 돌고 있는 것은 절대 안 버린다.

        호출자가 _lock 을 잡은 상태로 부른다.
        """
        done = [j for j in self.jobs.values()
                if j.status in ("done", "error", "cancelled")]
        if len(done) <= self.KEEP_FINISHED:
            return
        # finished_at 이 0 인 것(아직 안 찍힌 것)은 가장 최근으로 본다 — 버릴
        # 후보의 맨 뒤로 밀어서, 애매한 것을 먼저 버리지 않게 한다.
        done.sort(key=lambda j: j.finished_at or float("inf"))
        for j in done[:len(done) - self.KEEP_FINISHED]:
            self.jobs.pop(j.id, None)

    def start(self, run_id: str, scene_no: int, feedback: str = "",
              style: str = "", textless: bool = False,
              tags: list[str] | None = None, episode: int = 1) -> Regen:
        tags = tags or []
        append_feedback(run_id, "scene", tags, feedback, scene_no=scene_no,
                        decision="retry")
        # 고른 항목도 프롬프트로 간다 — 대부분은 항목만 누르고 아무 말도 안 적는다.
        job = Regen(id=uuid.uuid4().hex[:12], run_id=run_id, scene_no=int(scene_no),
                    episode=int(episode),
                    feedback=author_note("scene", tags, feedback),
                    textless=textless)
        with self._lock:
            self.jobs[job.id] = job
            self._prune()
        threading.Thread(target=self._work, args=(job, style), daemon=True).start()
        return job

    def _work(self, job: Regen, style: str) -> None:
        with self._gate:
            # 줄 서서 기다리는 동안 취소를 눌렀을 수 있다. cancel() 은 _proc 만
            # 죽이는데 대기 중에는 _proc 이 아직 없다 — 여기서 안 보면 취소된
            # 작업이 차례가 오자마자 한 장을 통째로 그려서 돈만 쓰고 버린다.
            if job._cancel:
                job.status = "cancelled"
                job.finished_at = time.time()
                return
            backup = None
            try:
                job.status = "running"
                job.started_at = time.time()

                rng = scene_cut_range(job.run_id, job.scene_no, job.episode)
                if not rng:
                    raise Failed("그 장을 찾지 못했습니다.")

                # 굽기 **전에** 지금 그림을 떠 둔다. run.py 는 같은 자리에
                # 덮어쓰므로, 이걸 안 하면 실패했을 때 원본까지 사라진다.
                job.note = "지금 그림을 보관하는 중"
                job.version = archive_scene(job.run_id, job.scene_no, job.episode)
                if job.version:
                    backup = version_path(job.run_id, job.scene_no, job.version,
                                          job.episode)

                job.note = "다시 그리는 중"
                cfg = regen_config(job.run_id, job.feedback, style, job.textless,
                                   job.episode)
                cmd = ["run.py", "--run-id", job.run_id,
                       "--episode", str(job.episode),
                       "--mode", run_mode(job.run_id, job.episode), "-c", CONDITION,
                       "--cuts", f"{rng[0]}-{rng[1]}",
                       "--config", str(cfg), "--yes"]
                code = self._spawn(job, cmd)
                if job._cancel:
                    raise Failed("취소됨")
                if code != 0:
                    raise Failed("그림을 다시 그리지 못했습니다.")

                _clear_cache(job.run_id, job.scene_no, job.episode)
                job.status = "done"
                job.note = "새로 그렸습니다"
            except Failed as exc:
                job.status = "cancelled" if job._cancel else "error"
                job.error = str(exc)
                self._restore(job, backup)
            except Exception as exc:                            # noqa: BLE001
                job.status = "error"
                job.error = f"{type(exc).__name__}: {exc}"
                self._restore(job, backup)
            finally:
                job.finished_at = time.time()
                job._proc = None

    def _restore(self, job: Regen, backup: Path | None) -> None:
        """실패했으면 있던 그림을 되돌려 놓는다. **이게 이 기능의 약속이다** —
        다시 그리기를 눌렀다가 원본까지 잃으면 아무도 두 번 누르지 않는다."""
        if not backup or not backup.exists():
            return
        dest = unit_image(job.run_id, job.scene_no, job.episode)
        if dest:
            try:
                shutil.copy2(backup, dest)
                _clear_cache(job.run_id, job.scene_no, job.episode)
                job.note = "실패해서 원래 그림으로 되돌렸습니다"
            except OSError:
                pass

    def _spawn(self, job: Regen, cmd: list[str]) -> int:
        log = episode_dir(job.run_id, job.episode) / "regen" / f"{job.id}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            [sys.executable, "-u", *cmd], cwd=str(WEBTOON), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        job._proc = proc
        with log.open("w", encoding="utf-8") as fh:
            fh.write(" ".join(["python", *cmd]) + "\n")
            for raw in proc.stdout:                 # type: ignore[union-attr]
                line = raw.rstrip("\n")
                fh.write(line + "\n")
                if line.strip():
                    job.note = line.strip()[:120]
        return proc.wait()


regens = RegenRunner()


def _read_json(base: Path, name: str) -> dict:
    """산출물 하나를 읽는다. 없거나 깨졌으면 빈 dict — 편집기는 일부만 있어도 열려야 한다."""
    try:
        return json.loads((base / name).read_text(encoding="utf-8-sig"))
    except Exception:                                          # noqa: BLE001
        return {}


def list_runs(limit: int = 60) -> list[dict[str, Any]]:
    """편집기 고르개에 뿌릴 run 목록. 그림이 하나라도 있는 것만.

    작업(Job)을 거치지 않는다 — 랜딩에서 만든 것이든 하네스를 직접 돌린 것이든
    똑같이 보여야 한다. 편집기는 "이미 그려진 것을 고치는 자리" 라서, 어떻게
    만들어졌는지는 상관이 없다.
    """
    out = []
    root = STORY / "runs"
    if not root.is_dir():
        return out
    for run_dir in sorted(root.glob("2026*"), reverse=True):
        rid = run_dir.name
        # 콘티가 나온 회차 전부. 1화만 세면 이어 만든 2화가 목록에서 사라진다.
        planned = made_episodes(rid)
        if not planned:
            continue
        # 1번 장만 보지 않는다. 일부만 뽑아 둔 run 이 흔하고(3·4번만 뽑는 식),
        # 그런 run 도 그려진 장은 편집할 수 있어야 한다.
        drawn = [e for e in planned
                 if any(unit_image(rid, n, e) for n in range(1, 13))]
        if not drawn:
            continue                       # 그림이 하나도 없으면 편집할 것이 없다
        p1 = _read_json(run_dir, "p1.json")
        # 목록에 그림을 걸려면 **어느 장을 걸지**를 알아야 한다. 1번 장이 있다고
        # 칠 수 없다 — 3·4번만 뽑아 둔 run 이 흔하다. 그래서 표지로 쓸 장을
        # 실제로 찾고, 같은 김에 몇 장이 그려졌는지도 센다.
        cover_ep = drawn[0]
        pages = [n for n in range(1, 13) if unit_image(rid, n, cover_ep)]
        out.append({
            "run_id": rid,
            "character": str(p1.get("name") or ""),
            "title": episode_title(rid, drawn[0]) or f"{drawn[0]}화",
            "genre": str(_read_json(run_dir, "meta.json").get("input", {}).get("genre") or ""),
            # 이어 만든 회차까지. 화면이 "다음 화" 를 붙일지 정하는 근거다.
            "episodes": drawn,
            "planned_episodes": planned,
            "next_episode": (planned[-1] + 1) if planned else 1,
            # 목록 카드가 쓰는 것 — 표지 그림 주소를 만들 재료와 규모 표시.
            "cover_episode": cover_ep,
            "cover_page": pages[0] if pages else None,
            "page_count": len(pages),
        })
        if len(out) >= limit:
            break
    return out


def editor_data(run_id: str, episode: int = 1) -> dict[str, Any]:
    """편집기 화면이 그대로 먹는 모양. mock.json 과 같은 구조다.

    result(job) 과 두 가지가 다르다:
      · **Job 이 아니라 run_id 로** 만든다. 하네스를 직접 돌린 run 도 열린다.
      · 장 그림의 주소를 같이 준다 (`image` · `w` · `h`). 편집기는 그림 위에
        말풍선을 얹으므로 원본 크기를 알아야 좌표를 퍼센트로 다룰 수 있다.
    """
    run_dir = STORY / "runs" / run_id
    data = _read_json(run_dir / "webtoon", cuts_filename(episode))
    if not data:
        return {}
    p1 = _read_json(run_dir, "p1.json")
    p2 = _read_json(run_dir, "p2.json")

    def cut_card(c: dict[str, Any]) -> dict[str, Any]:
        return {"no": int(c.get("cut_number") or 0),
                "shot": str(c.get("shot") or ""),
                "beat": str(c.get("beat") or ""),
                "speaker": str(c.get("speaker") or ""),
                "dialogue": str(c.get("dialogue") or ""),
                "narration": str(c.get("narration") or ""),
                "thought": str(c.get("thought") or ""),
                "sfx": str(c.get("sfx") or ""),
                "description": str(c.get("description") or ""),
                # 한 컷에 말이 여러 줄일 수 있다(콘티 새 형식). 있으면 그대로 넘긴다 —
                # 편집기가 말풍선을 몇 개 얹어야 하는지는 이 값이 정한다.
                "lines": c.get("lines") or []}

    by_no = {int(c.get("cut_number") or 0): c for c in (data.get("cuts") or [])}
    ep_dir = episode_dir(run_id, episode)
    grouping = _read_json(ep_dir, "scenes.json").get("scenes") or []
    if not grouping:
        grouping = [{"scene_number": n, "cut_numbers": [n]} for n in sorted(by_no)]

    # 화면도 파일과 **같은 여백·같은 폭**으로 이어야 한다. 전에는 이 값이
    # 아예 안 실려서 리더가 장을 딱 붙여 그렸다 — 내려받은 episode.png 에는
    # 여백이 있는데 화면에는 없어서, 보고 만든 것과 받은 것이 서로 달랐다.
    layout = _scene_layout(run_id, episode)
    gaps = _run_gap_table(run_id) or _strip_gap_table()
    scenes = []
    for sc in grouping:
        no = int(sc.get("scene_number") or 0)
        src = unit_image(run_id, no, episode)
        if not src:
            continue
        w, h = _image_size(src)
        gap_after, weight = layout.get(no, (0, "normal"))
        scenes.append({
            "no": no,
            "image": f"/api/runs/{run_id}/page/{no}" + _ep_q(episode),
            "w": w, "h": h,
            # 아래 여백 — 지면 폭의 몇 배인가 (episode.stitch 와 같은 눈금).
            "gap": round(float(gaps.get(int(gap_after), 0.0)), 4),
            # 그 여백이 몇 단인가 (0 붙임 · 1 한 박자 · 2 쉼 · 3 크게 쉼).
            # 편집실이 이 단을 올리고 내려서 여백을 고친다 — 배수를 직접
            # 만지면 콘티가 쓰는 눈금과 다른 값이 생겨서, 다시 구울 때 맞출
            # 기준이 없어진다.
            "gap_step": int(gap_after),
            # 이 장이 쓰는 지면 폭 — 떠 있는 컷(light)은 좁게 들어간다.
            "width": round(_width_ratio(weight), 4),
            "cuts": [cut_card(by_no[n]) for n in (sc.get("cut_numbers") or [])
                     if n in by_no],
        })

    planned = made_episodes(run_id)
    return {
        "run_id": run_id,
        "episode": int(episode),
        "episodes": planned,
        # 단(0~3) -> 지면 폭의 몇 배. 편집실이 여백을 바꿀 때 이 표로 미리
        # 그린다 — 서버에 물어보고 기다리면 끌면서 볼 수가 없다.
        "gap_scale": {str(k): round(float(v), 4) for k, v in sorted(gaps.items())},
        "next_episode": (planned[-1] + 1) if planned else 1,
        "title": episode_title(run_id, episode) or f"{int(episode)}화",
        "character": str(p1.get("name") or ""),
        "genre": str(_read_json(run_dir, "meta.json").get("input", {}).get("genre") or ""),
        "style_label": "",
        "logline": str(p2.get("logline") or ""),
        "cuts_per_sheet": str(CUTS_PER_SHEET),
        # 이어 그리기 판단용 — 지금까지 그린 장 수와 콘티가 계획한 컷 수.
        # more_cuts 가 참이면 화면에 "다음 장면 이어서 보기" 가 뜬다.
        "drawn_units": drawn_units(run_id, episode),
        "planned_cuts": planned_cuts(run_id, episode),
        "more_cuts": bool(planned_cuts(run_id, episode)
                          and drawn_units(run_id, episode) * CUTS_PER_SHEET
                          < planned_cuts(run_id, episode)),
        "scenes": scenes,
    }


def _image_size(path: Path) -> tuple[int, int]:
    """그림의 원본 크기. Pillow 가 없으면 어림값으로 떨어진다 (좌표는 퍼센트라
    비율만 맞으면 화면이 크게 어긋나지 않는다)."""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:                                          # noqa: BLE001
        return (900, 1600)


def run_cost(run_id: str) -> dict[str, Any]:
    """작품 하나에 실제로 얼마가 들었나 — **세 원장을 한 줄로 합친다.**

    지금까지 비용이 세 군데에 흩어져 있었고, 어디에도 합계가 없었다:
      · 이야기      story-harness/runs/{id}/meta.json      usage.cost.usd
      · 캐릭터 시트 .../charsheet/charsheet_meta.json       usage.cost_usd
      · 그림·프롬프트 webtoon-harness/outputs/{id}/ep*/usage.json
    시트는 특히 어느 합계에도 안 섞여서, 세 곳을 사람이 더해야 "이 작품에 얼마"
    를 알 수 있었다.

    **어림값과 실측을 구분해서 돌려준다.** 텍스트는 실제 토큰 x 단가표라 정확하고,
    이미지는 단가표가 비어 있어 장당 고정값으로 센다. 둘을 한 숫자로 뭉치면
    "정확한 합계" 처럼 보이므로, estimated 에 어느 부분이 어림인지 남긴다.
    """
    run_dir = STORY / "runs" / run_id
    parts, estimated, notes = [], [], []
    seconds = 0.0

    meta = _read_json(run_dir, "meta.json")
    cost = ((meta.get("usage") or {}).get("cost") or {})
    if cost:
        parts.append({"part": "이야기", "usd": float(cost.get("usd") or 0.0),
                      "basis": f"실제 토큰 x 단가표 ({cost.get('rates_as_of') or '기준일 미상'})"})
        seconds += float(meta.get("elapsed_sec") or 0.0)
        if not cost.get("complete", True):
            estimated.append("이야기")
        for m in (cost.get("unpriced_models") or []):
            notes.append(f"단가 없는 모델: {m}")

    sheet = _read_json(run_dir / "charsheet", "charsheet_meta.json")
    su = sheet.get("usage") or {}
    if su.get("cost_usd") is not None:
        parts.append({"part": "캐릭터 시트",
                      "usd": float(su.get("cost_usd") or 0.0),
                      "basis": f"{su.get('images_made', 0)}장 x 장당 고정 "
                               f"({su.get('unit_cost_source') or '근거 미상'})"})
        estimated.append("캐릭터 시트")

    # 화가 여럿이면 ep1·ep2… 를 모두 더한다.
    ep_root = WEBTOON / "outputs" / run_id
    for ep_dir in sorted(ep_root.glob("ep*")) if ep_root.is_dir() else []:
        u = _read_json(ep_dir, "usage.json")
        tot = u.get("total") or {}
        if not tot:
            continue
        parts.append({"part": f"그림 ({ep_dir.name})",
                      "usd": float(tot.get("cost_usd") or 0.0),
                      "basis": f"호출 {tot.get('calls', 0)}회"
                               + (f" · {u.get('calls_priced_flat')}회는 고정 단가 어림"
                                  if u.get("calls_priced_flat") else "")})
        seconds += float(tot.get("seconds") or 0.0)
        if u.get("calls_priced_flat"):
            estimated.append(ep_dir.name)

    total = round(sum(p["usd"] for p in parts), 4)
    return {"run_id": run_id, "parts": parts, "total_usd": total,
            "total_krw": int(round(total * USD_TO_KRW)),
            "seconds": round(seconds, 1),
            "estimated": estimated, "notes": notes,
            "exact": not estimated}


def _result_body(run_id: str, episode: int, style_label: str) -> dict[str, Any]:
    """완성본 한 편 + 그 안에 무엇이 담겼는지 — job 이 있든 없든 공통인 부분.

    결과물의 단위는 **장(Scene)** 이다 — 한 장에 컷이 3개씩 들어 있으므로,
    화면에도 장을 보여주고 그 장이 어느 컷들을 담고 있는지 같이 준다.
    대사 스크립트가 컷 단위여야 "이 말풍선이 몇 번 컷 것인가"를 볼 수 있다.

    `result(job)` 과 `result_by_run(run_id, episode)` 둘 다 이걸 쓴다 — 랜딩에서
    만든 것이든(job 있음) 하네스를 직접 돌렸거나 편집기로 이어 만든 것이든(job
    없음) 같은 모양으로 결과 화면에 떨어져야, "완성본 보기"가 어떻게 만들어진
    것인지에 상관없이 똑같이 동작한다.
    """
    run_dir = STORY / "runs" / run_id
    cut_file = run_dir / "webtoon" / cuts_filename(episode)
    if not cut_file.exists():
        return {}
    data = json.loads(cut_file.read_text(encoding="utf-8-sig"))

    def load(base: Path, name: str) -> dict:
        try:
            return json.loads((base / name).read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return {}

    p1, p2 = load(run_dir, "p1.json"), load(run_dir, "p2.json")
    title = episode_title(run_id, episode) or f"{int(episode)}화"

    def cut_card(c: dict) -> dict:
        return {
            "no": int(c.get("cut_number") or 0),
            "speaker": str(c.get("speaker") or ""),
            "dialogue": str(c.get("dialogue") or ""),
            "narration": str(c.get("narration") or ""),
            "thought": str(c.get("thought") or ""),
            "sfx": str(c.get("sfx") or ""),
            "description": str(c.get("description") or ""),
            "shot": str(c.get("shot") or ""),
        }

    by_no = {int(c.get("cut_number") or 0): c for c in (data.get("cuts") or [])}

    # 어느 컷이 어느 장에 묶였는지는 그림 쪽이 안다 (scenes.json).
    ep_dir = episode_dir(run_id, episode)
    grouping = load(ep_dir, "scenes.json").get("scenes") or []
    if not grouping:
        # 컷 모드로 되돌렸거나 아직 묶기 전 — 컷 하나를 한 장으로 본다.
        grouping = [{"scene_number": n, "cut_numbers": [n]} for n in sorted(by_no)]

    # 결과 화면도 파일과 같은 여백·폭으로 잇는다 (편집실이 쓰는 /episode 와
    # 같은 값 — 두 화면이 다른 리듬으로 보이면 어느 쪽이 진짜인지 알 수 없다).
    layout = _scene_layout(run_id, episode)
    gap_table = _run_gap_table(run_id) or _strip_gap_table()

    pages, drawn_cuts = [], 0
    for sc in grouping:
        no = int(sc.get("scene_number") or 0)
        if not unit_image(run_id, no, episode):
            continue                       # 아직 안 그렸거나 미리보기로 빠진 장
        cards = [cut_card(by_no[n]) for n in (sc.get("cut_numbers") or [])
                 if n in by_no]
        drawn_cuts += len(cards)
        gap_after, weight = layout.get(no, (0, "normal"))
        pages.append({"no": no, "cuts": cards,
                      "gap": round(float(gap_table.get(int(gap_after), 0.0)), 4),
                      "width": round(_width_ratio(weight), 4)})

    ep_png = ep_dir / "episode.png"
    planned = made_episodes(run_id)
    return {
        "title": title,
        "character": str(p1.get("name") or ""),
        "intro": str(p1.get("intro") or ""),
        "logline": str(p2.get("logline") or ""),
        "genre": str(load(run_dir, "meta.json").get("input", {}).get("genre") or ""),
        "style_label": style_label,
        "cuts_per_sheet": CUTS_PER_SHEET,
        # 이어 그리기 값 계산용 — 웹툰 연출이면 장당 값이 3배다(page_cost).
        "layout_mode": layout_mode(origin_form(run_id) or {}),
        "pages": pages,
        "page_count": len(pages),
        "cut_count": drawn_cuts,
        "planned_cuts": len(by_no),
        "planned_pages": len(grouping),
        "has_episode_png": ep_png.exists(),
        "run_id": run_id,
        "episode": int(episode),
        # 이 작품에 그려진 회차 전부 — 화면이 회차 탭을 그리는 근거다.
        "episodes": planned,
        "next_episode": (planned or [0])[-1] + 1,
    }


def result(job: Job) -> dict[str, Any]:
    """job 이 방금 완성한 결과물 — 걸린 시간처럼 job 에만 있는 정보를 더한다."""
    if not job.run_id:
        return {}
    body = _result_body(job.run_id, job.episode, STYLES.get(job.style, job.style))
    if not body:
        return {}
    body.update({
        # 얼마나 걸렸는가. 단계별로도 준다 — "어디서 오래 걸렸나"가 총 시간보다
        # 쓸모 있다 (그림이 대부분이고, 이야기가 길어지면 재생성이 돈 것이다).
        "seconds": round(
            (job.finished_at - job.started_at) if (job.started_at and job.finished_at)
            else job.stage_seconds(), 1),
        "stage_times": [{"title": st["title"], "seconds": st.get("seconds")}
                        for st in job.stages if st.get("seconds") is not None],
        "preview": job.preview,
    })
    return body


def result_by_run(run_id: str, episode: int = 1) -> dict[str, Any]:
    """job 을 거치지 않고 run_id 로 바로 여는 완성본 — "내 웹툰" 목록에서 쓴다.

    job 이 없는 회차도 있다 (하네스를 직접 돌렸거나 편집기의 "다음 화 이어서
    만들기" 로 만든 회차는 landing/jobs/ 에 기록이 안 남는다) — 그런 회차도
    똑같이 완성본으로 열 수 있어야 한다.
    """
    run_dir = STORY / "runs" / run_id
    style_label = ""
    try:
        meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8-sig"))
        style_key = str(meta.get("charsheet", {}).get("style") or "")
        style_label = STYLES.get(style_key, style_key)
    except (OSError, json.JSONDecodeError):
        pass
    return _result_body(run_id, episode, style_label)


# --------------------------------------------------------------------------- #
# 큐 — 한 번에 한 편만
#
# 이미지 호출이 12회 나가는 일이라 동시에 여러 편을 돌리면 요금과 rate limit 이
# 같이 터진다. 뒤에 온 요청은 줄을 선다.
# --------------------------------------------------------------------------- #

class Runner:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.queue: list[str] = []
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def restore(self) -> int:
        """지난 실행에서 끝난 작업들을 다시 읽어 온다 (결과 화면만 다시 열립니다)."""
        if not JOBS_DIR.exists():
            return 0
        found = 0
        for d in sorted(JOBS_DIR.iterdir()):
            if not d.is_dir() or d.name in self.jobs:
                continue
            job = Job.load(d)
            if job:
                self.jobs[job.id] = job
                found += 1
        return found

    def create(self, form: dict[str, Any], photo=None) -> Job:
        """photo 는 bytes 하나 또는 bytes 목록. 한 사람을 여러 각도로 찍은 것이다."""
        job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        shots = [photo] if isinstance(photo, (bytes, bytearray)) else list(photo or [])
        for i, raw in enumerate(shots[:MAX_PHOTOS], 1):
            (job_dir / f"photo{i}.png").write_bytes(raw)
        style = str(form.get("style") or "webtoon")
        if style not in STYLES:
            style = "webtoon"
        job = Job(id=job_id, form=form, dir=job_dir, style=style,
                  preview=bool(form.get("preview")), has_photo=bool(shots))
        job.build_stages()
        (job_dir / "input.json").write_text(
            json.dumps(form, ensure_ascii=False, indent=2), encoding="utf-8")

        with self._lock:
            self.jobs[job_id] = job
            self.queue.append(job_id)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain, daemon=True)
                self._worker.start()
        return job

    def create_more(self, run_id: str, cut_from: int) -> Job:
        """이어 그리기 — 같은 화의 다음 컷들 (미리보기 다음 장면).

        create_next() 와 달리 회차가 안 늘어난다. 콘티도 안 만든다. 하는 일은
        "이미 있는 콘티의 다음 3컷을 그리고 다시 이어 붙이기" 하나뿐이다.
        그림 설정(그림체·연출)은 처음 만들 때 쓴 값을 그대로 물려받는다 —
        여기서 다시 고르게 하면 같은 화의 앞뒤가 다른 그림체가 된다.
        """
        form = dict(origin_form(run_id) or {})
        if not form:
            raise Failed("이어 그릴 작품을 찾지 못했습니다.")
        form.pop("preview", None)          # 컷 범위는 cut_from 이 정한다

        job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        style = str(form.get("style") or "webtoon")
        if style not in STYLES:
            style = "webtoon"
        job = Job(id=job_id, form=form, dir=job_dir, style=style,
                  preview=False, has_photo=False,
                  cut_from=max(1, int(cut_from)))
        job.run_id = run_id
        job.build_stages()
        (job_dir / "input.json").write_text(
            json.dumps(form, ensure_ascii=False, indent=2), encoding="utf-8")
        (job_dir / "run_id.txt").write_text(run_id, encoding="utf-8")

        with self._lock:
            self.jobs[job_id] = job
            self.queue.append(job_id)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain, daemon=True)
                self._worker.start()
        return job

    def create_next(self, run_id: str, form: dict[str, Any] | None = None) -> Job:
        """이어 만들기 — 이미 있는 작품의 다음 화 (#72).

        create() 와 다른 점은 셋뿐이다: 사진을 안 받고, run_id 를 새로 파지 않고,
        회차가 2 이상이다. 나머지(대기줄·워커·config)는 같은 길을 쓴다.

        그림 설정(그림체·등신·연출 모드)은 **1화가 쓴 값을 그대로 물려받는다.**
        여기서 다시 고르게 하면 같은 작품의 회차마다 그림체가 달라진다.
        """
        planned = made_episodes(run_id)
        if not planned:
            raise Failed("1화 콘티가 없는 작품입니다.")
        form = {**(origin_form(run_id) or {}), **(form or {})}
        # 미리보기는 이어 만들 때 물려받지 않는다 — 앞 화를 미리보기로 뽑았다고
        # 다음 화도 앞부분만 나오면 연재가 안 된다. 사용자가 다시 고르게 둔다.
        form.pop("preview", None)

        job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        style = str(form.get("style") or "webtoon")
        if style not in STYLES:
            style = "webtoon"
        job = Job(id=job_id, form=form, dir=job_dir, style=style,
                  preview=False, has_photo=False,
                  episode=planned[-1] + 1)
        job.run_id = run_id
        job.build_stages()
        (job_dir / "input.json").write_text(
            json.dumps(form, ensure_ascii=False, indent=2), encoding="utf-8")
        (job_dir / "run_id.txt").write_text(run_id, encoding="utf-8")

        with self._lock:
            self.jobs[job_id] = job
            self.queue.append(job_id)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain, daemon=True)
                self._worker.start()
        return job

    def position(self, job_id: str) -> int:
        with self._lock:
            return self.queue.index(job_id) if job_id in self.queue else 0

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self.queue:
                    self._worker = None
                    return
                job = self.jobs[self.queue[0]]
            try:
                execute(job)
            finally:
                with self._lock:
                    if self.queue and self.queue[0] == job.id:
                        self.queue.pop(0)

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)


# --------------------------------------------------------------------------- #
# CLI — 서버 없이 비용만 보고 싶을 때
#   python pipeline.py --cost <run_id>
#   python pipeline.py --cost            (편집 가능한 run 전부)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="작품 하나에 든 비용·시간")
    ap.add_argument("--cost", nargs="?", const="", metavar="RUN_ID",
                    help="run_id 하나, 또는 비우면 전부")
    a = ap.parse_args()

    if a.cost is None:
        ap.print_help()
        raise SystemExit(0)

    ids = [a.cost] if a.cost else [r["run_id"] for r in list_runs()]
    grand = 0.0
    for rid in ids:
        c = run_cost(rid)
        if not c["parts"]:
            print(f"{rid}  (원장 없음)")
            continue
        grand += c["total_usd"]
        mark = "" if c["exact"] else "  ~어림"
        print()
        print(f"{rid}   ${c['total_usd']:.4f} "
              f"({c['total_krw']:,}원) · {c['seconds']:.0f}초{mark}")
        for part in c["parts"]:
            print(f"   {part['part']:<16} ${part['usd']:>8.4f}   {part['basis']}")
        for note in c["notes"]:
            print(f"   ! {note}")
        if c["estimated"]:
            print(f"   어림값: {', '.join(c['estimated'])} "
                  f"— 실제 토큰이 아니라 고정 단가로 셌습니다")
    if len(ids) > 1:
        print()
        print(f"합계 ${grand:.4f} ({int(round(grand * USD_TO_KRW)):,}원)")
