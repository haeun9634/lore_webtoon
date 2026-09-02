"""new_harness 연결 — 최소 실험 경로.

pipeline.py 의 5단계(story-harness+webtoon-harness) 흐름과는 **별도 경로**다.
new_harness 는 이야기·콘티·시트·그림을 run.py 하나 안에서 끝내는 단일
파이프라인이라 pipeline.py 의 STAGE_SPEC(look/seed/card/...)이 안 맞고,
산출물 단위(컷/장면이 아니라 페이지)도 달라서 같은 Job 을 못 쓴다.

## 왜 run.py 를 세 번 나눠 부르는가

`run.py --run-id <id> --pick <n> --all` 을 그대로 쓰면 안 된다 — run.py 의
main() 은 `new_run or args.all` 이면 무조건 이야기 단계(stage_story)부터 다시
돈다. run_id 로 이어 하는 중이라도 `--all` 을 주는 순간 이미 고른 방향과
무관하게 새 이야기 후보 4개를 다시 뽑는다(실제로 읽어서 확인함, 2026-08-31).
그래서 이어할 때는 `--all` 을 아예 안 쓰고, 세 번으로 나눈다:

    1. `--character <path>`           이야기 후보 4개 (사람이 고를 것)
    2. `--run-id <id> --pick <n>`      (--all 없이) 구체화 + 콘티만
    3. `--run-id <id> --sheet --pages` 시트 + 페이지 그림 (한 호출 안에서
                                       시트가 먼저 돌아 pages 가 참조로 쓴다)

이렇게 나누면 1번에서 보여준 후보 그대로 2번이 고르고, 이야기가 두 번
불리지 않는다.

## 편집실(overlay) 연동에 대해

처음엔 new_harness 가 대사를 이미지에 직접 그려 넣는 것(README 의 미해결
경고)을 이유로 편집실 연동을 미뤘는데, 확인해 보니 전제가 틀렸다 —
overlay.py 는애초에 밑그림에 빈 자리가 있어야 한다는 가정이 없다. 편집실이
얹는 말풍선·스티커는 **밑그림과 무관하게 화면 퍼센트 좌표(x·y·w)로 그
위에 그냥 올라간다** (`overlay.render_scene`) — 지금 webtoon-harness 화도
대사를 그림에 그대로 생성하고 그 위에 편집실로 덧대는 것과 같은 방식이다.
그래서 new_harness 의 "페이지"를 pipeline.py 의 "장(scene)"과 똑같이 —
번호 매겨진 밑그림 한 장으로만— 취급하면 overlay.py 를 그대로 재사용할 수
있다. new_harness 코드는 한 줄도 안 고쳤다.

## 검수(승인) 단계 — 2026-08-31 추가

처음엔 콘티(구체화+콘티)와 시트를 한 번에 이어서 돌렸는데, 그러면 사람이
볼 자리가 없다 — 시트 얼굴이 틀어지거나 콘티가 이상해도 페이지를 다 그린
뒤에야 안다. 그래서 세 번을 **네 번**으로 다시 나눴다:

    1. `--character <path>`             이야기 후보 4개 (사람이 고름)
    2. `--run-id <id> --pick <n> --detail`  구체화만  [멈춤 — 이야기 검수]
    3. `--run-id <id> --sheet`          시트만        [멈춤 — 시트 검수]
    4. `--run-id <id> --detail-pages`   페이지 그림

**2026-09-01부터 컷 대본·콘티를 건너뛴다.** 컷 대본에서 대사·컷·카메라를 다
못박으면 그림이 그것을 옮기기만 해서 결과가 평평해졌다(실측). 지금은 구체화된
장면을 그림 모델에게 그대로 주고 컷 분할까지 맡긴다(new_harness/detailart.py).
장면 하나가 페이지 하나이고, **1페이지는 표지다.** 쓰는 자리는 예전과 같은
`pages/pageNN.png` 라 둘러보기·편집실은 어느 흐름으로 만든 것인지 몰라도 된다.

"다시 만들기"는 그 단계 명령을 **한 번 더 그대로 부르는 것**이다 — 콘티는
`--pick n`을 다시 부르면 detail_prompt/storyboard_prompt 가 새로 돈다(값을
덮어씀, 실측 확인). 시트는 `run.py` 자체가 "사양·그림이 이미 있으면 다시
안 그린다"고 정해 놨으므로(`stage_sheet`), 다시 만들려면 `sheet.png`·
`sheet_spec.json` 을 먼저 지우고 같은 명령을 다시 부른다.

## 지금 안 하는 것

전문/일반 모드, 이어 그리기·이어 만들기(다음 화)는 없다. 그림 검수
(art QA — 그려진 페이지 개별 재생성)도 없다 — new_harness 는 페이지 단위
호출이라 컷 하나만 다시 그리는 개념이 없고, 페이지 전체를 다시 그리려면
비용이 pipeline.py 의 regen보다 크다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import overlay                      # 편집실 렌더링·굽기 재사용 (그대로, 안 고침)
import pipeline as classic          # write_character() 재사용 — 폼 -> character.json

HERE = Path(__file__).resolve().parent
JOBS_DIR = HERE / "jobs_nh"
NEW_HARNESS = HERE.parent / "new_harness"

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_AWAITING_PICK = "awaiting_pick"
STATUS_AWAITING_BOARD = "awaiting_board"
STATUS_AWAITING_SHEET = "awaiting_sheet"
STATUS_DONE = "done"
STATUS_ERROR = "error"
AWAITING = (STATUS_AWAITING_PICK, STATUS_AWAITING_BOARD, STATUS_AWAITING_SHEET)

# 화면에 보여줄 단계. new_harness 내부 단계 이름과 같다 — 세부 스텝(예:
# pipeline.py 의 look/seed/card...)까지는 안 쪼갠다, 신호가 그만큼 없다.
STAGES = ("story", "board", "sheet", "pages")
STAGE_LABEL = {
    "story": "이야기 설계", "board": "방향 확정",
    "sheet": "캐릭터 시트", "pages": "페이지 그림",
}

# 그림체 선택 -> new_harness 의 NH_STYLE 값(prompt/style/<이름> 파일).
# pastel·noir·shoujo 는 webtoon-harness/config.yaml 의 styles.<이름>.normal
# 을 그대로 옮겨 왔다(2026-08-31, cinematic 을 옮긴 것과 같은 방식 — 문구는
# 안 고치고 그대로). 선화·액션(lineart/action)은 랜딩 카드 자체를 없애기로
# 해서 여기도 뺐다.
STYLE_CHOICES = {
    "romance":   "romance_fantasy",
    "webtoon":   "webtoon_lock_bg",
    "frost":     "frost",
    "cinematic": "cinematic",
    "pastel":    "pastel",
    "noir":      "noir",
    "shoujo":    "shoujo",
    "game":      "game",
}
STYLE_LABEL = {
    "romance": "로맨스 판타지", "webtoon": "일반 웹툰", "frost": "세미리얼 · 성인향",
    "cinematic": "시네마틱 반실사", "pastel": "일상툰 감성", "noir": "다크 느와르",
    "shoujo": "순정 · BL", "game": "게임 원화",
}
DEFAULT_STYLE = "webtoon"                # new_harness 자체 기본(NH_STYLE)과 맞춘다

# "[페이지 3/7] 컷 2개 · 참조 2장 …" — pageart.draw() 가 찍는 줄 (pageart.py:116).
# "[장면 2/5] 참조 2장 …"          — detailart.draw() 가 찍는 줄 (디테일 직행).
RE_PAGE = re.compile(r"^\[(?:페이지|장면) (\d+)/(\d+)\]")
# "run: /.../runs/20260831T000249-10322f" — run.py:1141.
RE_RUN_ID = re.compile(r"^run: .*[/\\]([^/\\]+)\s*$")


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


@dataclass
class NHJob:
    id: str
    form: dict[str, Any]
    dir: Path
    status: str = STATUS_QUEUED
    run_id: str | None = None
    error: str | None = None
    directions: list[dict] = field(default_factory=list)
    pick: int | None = None
    note: str = ""
    style: str = DEFAULT_STYLE
    stage: str = "story"
    art_done: int = 0
    art_total: int = 0
    log: list[str] = field(default_factory=list)
    started_at: float | None = None
    finished_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    _proc: subprocess.Popen | None = field(default=None, repr=False, compare=False)
    _cancel: bool = field(default=False, repr=False, compare=False)

    # ---- 로그·상태 ---------------------------------------------------------- #

    def add_log(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            if len(self.log) > 400:
                del self.log[:100]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            art = None
            if self.art_total:
                art = {"done": self.art_done, "total": self.art_total}
            stage_i = STAGES.index(self.stage) if self.stage in STAGES else 0
            frac = (self.art_done / self.art_total) if self.art_total else 0.0
            pct = round((stage_i + frac) / len(STAGES) * 100) if self.status != "done" else 100
            out = {
                "id": self.id,
                "status": self.status,
                "run_id": self.run_id,
                "error": self.error,
                "directions": self.directions,
                "pick": self.pick,
                "style": self.style,
                "style_label": STYLE_LABEL.get(self.style, self.style),
                "stage": self.stage,
                "stage_index": stage_i,
                "stages": list(STAGES),
                "stage_label": STAGE_LABEL.get(self.stage, self.stage),
                "pct": max(0, min(100, pct)),
                "art": art,
                "log": self.log[-60:],
                "elapsed": round((self.finished_at or time.time())
                                 - self.started_at, 1) if self.started_at else 0,
            }
            # 그 검수 단계일 때만 읽는다 — 매 폴링(0.8초)마다 board.json 을
            # 여는 것은 대부분 헛일이다(pipeline.py 의 story_preview/
            # board_preview 와 같은 절약 규칙).
            if self.status == STATUS_AWAITING_BOARD and self.run_id:
                out["board_summary"] = board_summary(self.run_id)
            return out

    def save(self) -> None:
        try:
            (self.dir / "state.json").write_text(json.dumps({
                "id": self.id, "status": self.status, "run_id": self.run_id,
                "error": self.error, "form": self.form,
                "directions": self.directions, "pick": self.pick,
            }, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass

    # ---- 실행 ---------------------------------------------------------------- #

    def _env(self) -> dict[str, str]:
        env = _subprocess_env()
        # sheet.py·pageart.py 둘 다 NH_STYLE 을 같은 규칙으로 읽는다
        # (llm.env("NH_STYLE") or llm.env("PAGE_STYLE") or 기본값) — 하나만
        # 넣으면 시트와 페이지가 같은 그림체로 나온다.
        env["NH_STYLE"] = STYLE_CHOICES.get(self.style, self.style)
        return env

    def _run(self, args: list[str], on_line: Callable[[str], None]) -> int:
        display = " ".join(["python", "run.py", *args])
        self.add_log(f"$ {display}")
        with (self.dir / "log.txt").open("a", encoding="utf-8") as fh:
            fh.write(f"\n$ {display}\n")
        proc = subprocess.Popen(
            [sys.executable, "-u", "run.py", *args], cwd=str(NEW_HARNESS),
            env=self._env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        self._proc = proc
        with (self.dir / "log.txt").open("a", encoding="utf-8") as fh:
            for raw in proc.stdout:                    # type: ignore[union-attr]
                line = raw.rstrip("\n")
                fh.write(line + "\n")
                if line.strip():
                    self.add_log(line)
                    on_line(line)
        self._proc = None
        return proc.wait()

    def _stitch(self) -> tuple[bool, str]:
        result = subprocess.run(
            [sys.executable, "-u", "stitch.py", "--run-id", self.run_id],
            cwd=str(NEW_HARNESS), env=self._env(), capture_output=True,
            text=True, encoding="utf-8", errors="replace")
        out = (result.stdout or "").strip()
        if out:
            self.add_log(out)
        if result.returncode != 0:
            err = (result.stderr or "").strip()
            if err:
                self.add_log(err)
            return False, err or "이어 붙이기가 실패했습니다"
        return True, ""

    def cancel(self) -> None:
        self._cancel = True
        proc = self._proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        # 검수 대기 중이면 도는 프로세스가 없다 — 여기서 바로 끝낸다.
        if self.status in AWAITING:
            self.status = STATUS_ERROR
            self.error = "사용자가 취소했습니다"
            self.save()


def _on_rest_line(job: NHJob, line: str) -> None:
    """2·3단계 진행 중 stdout 한 줄 -> 화면에 보여줄 단계(job.stage) 갱신."""
    # 구체화·컷 대본·컷 대본 픽스·콘티는 화면에서 한 걸음("콘티")으로 묶어
    # 보여준다 — 넷 다 사람이 보는 것은 마지막 콘티 하나뿐이라, 걸음을
    # 넷으로 쪼개면 기다리는 사람에게 진행이 여러 번 되돌아가는 것처럼
    # 보인다.
    if (line.startswith("[콘티]") or line.startswith("[구체화]")
            or line.startswith("[컷 대본]") or line.startswith("[컷 검수")):
        job.stage = "board"
    elif line.startswith("[이어그리기]") or line.startswith("[디테일 직행]") \
            or line.startswith("[표지]") or line.startswith("[장면 "):
        job.stage = "pages"
    elif line.startswith("[시트]"):
        job.stage = "sheet"
    elif line.startswith("[페이지"):
        job.stage = "pages"
    m = RE_PAGE.match(line)
    if m:
        job.art_done = int(m.group(1)) - 1
        job.art_total = int(m.group(2))


def _extract_run_id(job: NHJob) -> str | None:
    for line in job.log:
        m = RE_RUN_ID.match(line)
        if m:
            return m.group(1)
    return None


def _fail(job: NHJob, message: str) -> None:
    job.status = STATUS_ERROR
    job.error = message
    job.save()


def _run_story_phase(job: NHJob) -> None:
    """1단계 — 이야기 후보 4개. 사람이 고를 때까지 여기서 멈춘다."""
    job.status = STATUS_RUNNING
    job.started_at = time.time()
    job.save()
    try:
        char_path = job.dir / "character.json"
        code = job._run(["--character", str(char_path)], lambda _line: None)
        if job._cancel:
            return _fail(job, "취소되었습니다")
        if code != 0:
            return _fail(job, "이야기 후보를 만들지 못했습니다 — 로그를 확인하세요")

        run_id = _extract_run_id(job)
        if not run_id:
            return _fail(job, "run_id 를 읽지 못했습니다")
        job.run_id = run_id

        directions_path = NEW_HARNESS / "runs" / run_id / "directions.json"
        if not directions_path.exists():
            return _fail(job, "이야기 후보 파일이 없습니다")
        directions = json.loads(directions_path.read_text(encoding="utf-8"))
        if not directions:
            return _fail(job, "이야기 후보를 하나도 못 읽었습니다 — story.md 를 확인하세요")

        job.directions = directions
        job.status = STATUS_AWAITING_PICK
        job.save()
    except Exception as exc:                            # noqa: BLE001
        _fail(job, f"{type(exc).__name__}: {exc}")


def _run_restory_phase(job: NHJob) -> None:
    """방향 고르기 화면의 "다시 만들기" — 기존 run 에서 이야기 후보 4개를
    다시 만든다. job.note 가 있으면 이번 시도에만 반영할 요청으로 같이 준다.

    구체화·콘티가 없어진 뒤로는 "다시 만들기"가 갈 곳이 여기(1단계)밖에
    없다 — 그 아래(2단계, board)는 pick.json 을 저장만 할 뿐 아무것도
    새로 만들지 않는다.
    """
    job.status = STATUS_RUNNING
    job.stage = "story"
    job.save()
    try:
        args = ["--run-id", job.run_id, "--restory"]
        if job.note.strip():
            args += ["--note", job.note.strip()]
        code = job._run(args, lambda _line: None)
        if job._cancel:
            return _fail(job, "취소되었습니다")
        if code != 0:
            return _fail(job, "이야기 후보를 다시 만들지 못했습니다 — 로그를 확인하세요")

        directions_path = NEW_HARNESS / "runs" / job.run_id / "directions.json"
        if not directions_path.exists():
            return _fail(job, "이야기 후보 파일이 없습니다")
        directions = json.loads(directions_path.read_text(encoding="utf-8"))
        if not directions:
            return _fail(job, "이야기 후보를 하나도 못 읽었습니다 — story.md 를 확인하세요")

        job.directions = directions
        job.pick = None
        job.status = STATUS_AWAITING_PICK
        job.save()
    except Exception as exc:                            # noqa: BLE001
        _fail(job, f"{type(exc).__name__}: {exc}")


def _run_board_phase(job: NHJob) -> None:
    """2단계 — 고른 방향을 pick.json 에 남기고 바로 검수로 넘어간다.

    2026-09-02부터 구체화(`--detail`)·콘티를 안 돈다 — 이어그리기 흐름은
    story 단계(방향 후보)가 이미 장면 목록·등장인물 외모까지 다 뽑아 두므로,
    여기서 더 만들 것이 없다. 호출 0회(`--pick-save`)라 이 단계는 사실상
    바로 끝난다. 함수·상태 이름(board)은 옛 흐름과 그대로 맞춰 뒀다 — 화면
    (newharness.html)이 `STATUS_AWAITING_BOARD`를 보고 검수 UI를 띄우는
    지점이 바뀌면 프론트도 같이 고쳐야 해서다.

    "다시 만들기"도 이 함수를 그대로 다시 부르지만, 다시 뽑을 것이 없어
    pick.json 을 같은 값으로 다시 쓸 뿐이다 — 이야기 자체를 바꾸려면
    방향 선택(1단계)으로 돌아가야 한다.
    """
    job.status = STATUS_RUNNING
    job.stage = "board"
    job.save()
    try:
        code = job._run(["--run-id", job.run_id, "--pick", str(job.pick), "--pick-save"],
                        lambda line: _on_rest_line(job, line))
        if job._cancel:
            return _fail(job, "취소되었습니다")
        if code != 0:
            return _fail(job, "방향을 저장하지 못했습니다 — 로그를 확인하세요")
        job.status = STATUS_AWAITING_BOARD
        job.save()
    except Exception as exc:                            # noqa: BLE001
        _fail(job, f"{type(exc).__name__}: {exc}")


def _run_sheet_phase(job: NHJob) -> None:
    """3단계 — 캐릭터 시트. 끝나면 사람이 볼 때까지 멈춘다.

    다시 만들기는 호출 전에 sheet.png·sheet_spec.json 을 지운다 — run.py 의
    stage_sheet 는 그 둘이 있으면 "이미 있습니다"로 그냥 넘어가기 때문이다.
    """
    job.status = STATUS_RUNNING
    job.stage = "sheet"
    job.save()
    try:
        args = ["--run-id", job.run_id, "--sheet"]
        if job.note.strip():
            args += ["--note", job.note.strip()]
        code = job._run(args, lambda line: _on_rest_line(job, line))
        if job._cancel:
            return _fail(job, "취소되었습니다")
        if code != 0:
            return _fail(job, "시트를 만들지 못했습니다 — 로그를 확인하세요")
        job.status = STATUS_AWAITING_SHEET
        job.save()
    except Exception as exc:                            # noqa: BLE001
        _fail(job, f"{type(exc).__name__}: {exc}")


def _run_pages_phase(job: NHJob) -> None:
    """4단계 — 페이지 그림, 그리고 이어붙이기. 끝나면 완성이다."""
    job.status = STATUS_RUNNING
    job.stage = "pages"
    job.save()
    try:
        code = job._run(["--run-id", job.run_id, "--detail-pages"],
                        lambda line: _on_rest_line(job, line))
        if job._cancel:
            return _fail(job, "취소되었습니다")
        if code != 0:
            return _fail(job, "그림을 만들지 못했습니다 — 로그를 확인하세요")

        ok, err = job._stitch()
        if not ok:
            return _fail(job, err)

        job.art_done = job.art_total
        job.status = STATUS_DONE
        job.finished_at = time.time()
        job.save()
    except Exception as exc:                            # noqa: BLE001
        _fail(job, f"{type(exc).__name__}: {exc}")


def _clear_sheet(run_id: str) -> None:
    d = run_dir(run_id)
    for name in ("sheet.png", "sheet_spec.json", "sheet_prompt.txt", "sheet_spec_prompt.txt"):
        try:
            (d / name).unlink()
        except OSError:
            pass


def scene_events(scene: dict) -> list[dict]:
    """장면 하나 -> 사건 배열. **사건 하나가 그림 한 장이다.**

    new_harness/pages.py 의 `detail_events` 와 같은 규칙이다. landing 은
    new_harness 를 import 하지 않고 run.py 를 따로 불러 쓰므로(이 파일 머리말
    참고) 읽는 쪽 규칙만 여기에 다시 적는다.

    사건 칸이 없는 옛 run 은 장면 자체가 사건 하나다 — 그때는 예전처럼
    장면당 한 장으로 보인다.
    """
    got = [e for e in (scene.get("events") or []) if isinstance(e, dict)]
    if got:
        return got
    return [dict(scene, id=1)]


def direction_summary(run_id: str) -> dict[str, Any] | None:
    """이어그리기 흐름의 검수 화면 — 구체화조차 없으므로 방향 후보 원본을 그대로 보여준다.

    2026-09-02부터 기본 흐름이다: story 단계(방향 후보) 산출물만으로 그리므로
    detail.json·board.json 이 아예 안 생긴다. 화면(newharness.html)은
    board_summary 와 같은 모양만 받으면 되니, 장면 한 줄을 "컷 하나"로
    접어 넣는다.
    """
    d = run_dir(run_id)
    try:
        pick = json.loads((d / "pick.json").read_text(encoding="utf-8"))
        directions = json.loads((d / "directions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    direction = next((x for x in directions if x.get("n") == pick.get("n")), None)
    if not direction:
        return None
    scenes = []
    for i, s in enumerate(direction.get("scenes") or [], 1):
        text = str(s).strip()
        if not text:
            continue
        scenes.append({
            "id": i, "location": "", "time": "", "summary": text,
            "cuts": [{"id": 1, "size": "full", "shot": "", "angle": "",
                      "background": "", "characters": [], "dialogue": [], "sfx": []}],
        })
    cast = [{"name": (c.get("name") or "").strip(),
             "appearance": (c.get("appearance") or "").strip()}
            for c in direction.get("cast") or [] if (c.get("name") or "").strip()]
    return {"cast": cast, "scenes": scenes, "cut_count": len(scenes),
            "engine": "direction", "plot": direction.get("plot") or ""}


def detail_summary(run_id: str) -> dict[str, Any] | None:
    """디테일 직행 흐름의 검수 화면 — 컷 대본·콘티가 없으므로 장면을 그대로 보여준다.

    화면(newharness.html)은 board_summary 와 같은 모양만 받으면 되므로 **사건
    하나를 "컷 하나"로** 접어 넣는다 — 어느 흐름으로 만든 것인지 몰라도 되게.
    사건 하나가 그림 한 장이 되므로, 검수 화면의 컷 개수가 곧 그릴 장 수다.
    """
    try:
        detail = json.loads((run_dir(run_id) / "detail.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    scenes = []
    for s in detail.get("scenes") or []:
        cuts = []
        for i, e in enumerate(scene_events(s), 1):
            learns = [(x.get("what") or "").strip()
                      for x in (e.get("learns") or []) if isinstance(x, dict)]
            cuts.append({
                "id": e.get("id") or i, "size": "full", "shot": "", "angle": "",
                "background": (e.get("detail") or "").strip(),
                "characters": [], "dialogue": [], "sfx": [],
                "learns": [x for x in learns if x],
            })
        scenes.append({
            "id": s.get("id"), "location": "", "time": "",
            "summary": (s.get("source") or "").strip(),
            "cuts": cuts,
        })
    cast = [{"name": (c.get("name") or "").strip(),
             "appearance": (c.get("appearance") or "").strip()}
            for c in detail.get("cast") or [] if (c.get("name") or "").strip()]
    return {"cast": cast, "scenes": scenes,
            "cut_count": sum(len(s["cuts"]) for s in scenes),
            "engine": "detail"}


def board_summary(run_id: str) -> dict[str, Any] | None:
    """콘티 검수 화면이 보여줄 것 — cast·장면·컷을 사람이 읽을 모양으로.

    board.json 의 원래 모양(run.parse_board 참고)을 옮긴다. 예전에는 컷마다
    대사만 뽑았는데, 그러면 검수하는 사람이 **그림에 무엇이 그려지는지를
    못 본다** — 콘티에서 확인해야 하는 것은 대사보다 "이 컷이 어떤 그림이
    되는가"(카메라·배경·누가 어떤 표정으로 무엇을 하는가)다. 그래서 그
    칸들을 같이 올린다.

    프롬프트에만 쓰이는 값(forbid·moment·framing·bubble 위치 등)은 여전히
    올리지 않는다 — 사람이 판단할 것이 아니라 그림 생성이 쓰는 값이다.
    """
    path = run_dir(run_id) / "board.json"
    try:
        board = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # 디테일 직행 흐름에는 콘티가 없다 — 그때는 구체화된 이야기를 보여준다.
        # 이어그리기 흐름(2026-09-02~)은 구체화조차 없다 — 그때는 방향 후보를
        # 그대로 보여준다.
        return detail_summary(run_id) or direction_summary(run_id)
    scenes = []
    for s in board.get("scenes") or []:
        cuts = []
        for c in s.get("cuts") or []:
            lines = [{"speaker": (d.get("speaker") or d.get("type") or "").strip(),
                      "text": (d.get("text") or "").strip()}
                     for d in (c.get("dialogue") or []) if (d.get("text") or "").strip()]
            cam = c.get("camera") or {}
            bg = c.get("background") or {}
            people = [{"name": (p.get("name") or "").strip(),
                       "expression": (p.get("expression") or "").strip(),
                       "action": (p.get("action") or "").strip()}
                      for p in (c.get("characters") or []) if (p.get("name") or "").strip()]
            sfx = [(x.get("text") or "").strip()
                   for x in (c.get("sfx") or []) if (x.get("text") or "").strip()]
            cuts.append({
                "id": c.get("id"), "size": c.get("size"),
                "shot": (cam.get("shot") or "").strip(),
                "angle": (cam.get("angle") or "").strip(),
                "background": (bg.get("desc") or "").strip(),
                "characters": people, "dialogue": lines, "sfx": sfx,
            })
        scenes.append({
            "id": s.get("id"), "location": s.get("location"),
            "time": s.get("time"), "summary": s.get("summary"), "cuts": cuts,
        })
    cast = [{"name": (c.get("name") or "").strip(),
             "appearance": (c.get("appearance") or "").strip()}
            for c in board.get("cast") or [] if (c.get("name") or "").strip()]
    total = sum(len(s["cuts"]) for s in scenes)
    return {"cast": cast, "scenes": scenes, "cut_count": total}


def _run_regen(entry: dict[str, Any]) -> None:
    """페이지 하나만 다시 그린다. run.py --page 는 파일이 이미 있으면 그냥
    넘어가므로(pageart.draw 의 "이미 있습니다"), 먼저 지워야 한다.

    다 그린 뒤에는 episode.png 도 다시 잇는다 — 안 그러면 완성본에는 옛
    페이지가 그대로 남아서, 다시 그린 게 화면에 안 보인다(stitch 는 호출
    비용이 없다, 그냥 이어붙이기만 하는 것이라 매번 다시 해도 된다).
    """
    entry["status"] = STATUS_RUNNING
    run_id, no = entry["run_id"], entry["page"]
    try:
        img = unit_image(run_id, no)
        if img:
            img.unlink()
        proc = subprocess.run(
            [sys.executable, "-u", "run.py", "--run-id", run_id, "--page", str(no)],
            cwd=str(NEW_HARNESS), env=_subprocess_env(), capture_output=True,
            text=True, encoding="utf-8", errors="replace")
        entry["log"] = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0 or not unit_image(run_id, no):
            entry["status"] = STATUS_ERROR
            entry["error"] = "다시 그리지 못했습니다 — 로그를 확인하세요"
            return
        stitch = subprocess.run(
            [sys.executable, "-u", "stitch.py", "--run-id", run_id],
            cwd=str(NEW_HARNESS), env=_subprocess_env(), capture_output=True,
            text=True, encoding="utf-8", errors="replace")
        if stitch.returncode != 0:
            # 페이지 자체는 새로 나왔으니 실패로 안 본다 — 완성본만 못 갱신됐다.
            entry["error"] = "새 페이지는 나왔지만 한 편으로 다시 잇지 못했습니다"
        entry["status"] = STATUS_DONE
    except Exception as exc:                            # noqa: BLE001
        entry["status"] = STATUS_ERROR
        entry["error"] = f"{type(exc).__name__}: {exc}"


class NHRunner:
    """job 저장소. 클래식 Runner 와 같은 방식으로 줄을 세운다 — 이미지 호출이
    여러 번 나가는 작업이라 동시에 여러 개를 돌리면 요금과 rate limit 이
    같이 터진다(landing/pipeline.py 의 Runner 와 같은 이유, 3599번 줄 근처
    주석 참고). 뒤에 온 요청은 줄을 선다.

    NHJob 은 실행이 여러 자리에서 걸린다 — 만들 때(story), 방향을 고를 때
    (board), 콘티/시트를 검수하고 승인·재시도를 누를 때마다(sheet·pages).
    각 자리 사이는 **사람이 볼 때까지** 멈춰 있어서 얼마나 걸릴지 알 수
    없다. 그래서 Runner 처럼 job_id 를 줄에 넣는 게 아니라, **이번에 돌릴
    일 하나**(callable)를 줄에 넣는다(`_enqueue`/`_requeue`) — 같은 job 이
    여러 번 줄을 설 수 있다는 뜻이다.
    """

    def __init__(self) -> None:
        self.jobs: dict[str, NHJob] = {}
        self.regens: dict[str, dict[str, Any]] = {}
        self.queue: list[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None
        JOBS_DIR.mkdir(parents=True, exist_ok=True)

    def get(self, job_id: str) -> NHJob | None:
        return self.jobs.get(job_id)

    def position(self, job_id: str) -> int:
        """이 job 이 지금 줄의 몇 번째인가 (0 = 대기 없음, 곧 돈다).

        job 이 한 번에 최대 하나의 일만 줄에 서므로(story 아니면 rest,
        둘이 겹칠 일이 없다) 이름으로 찾아도 안전하다.
        """
        with self._lock:
            for i, fn in enumerate(self.queue):
                if getattr(fn, "job_id", None) == job_id:
                    return i
            return 0

    def _enqueue(self, job_id: str, fn: Callable[[], None]) -> None:
        fn.job_id = job_id                  # position() 이 찾을 수 있게 이름표를 단다
        with self._lock:
            self.queue.append(fn)
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._drain, daemon=True)
                self._worker.start()

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self.queue:
                    self._worker = None
                    return
                fn = self.queue.pop(0)
            job = self.jobs.get(getattr(fn, "job_id", None))
            if job is not None and job._cancel:
                # 줄을 서서 기다리는 동안 취소됐다 — 아직 subprocess 를 안
                # 띄웠으니 그대로 건너뛴다. 돌리고 나서 취소로 처리하면
                # 이미 돈은 나간 뒤다.
                _fail(job, "취소되었습니다")
                continue
            fn()

    def create(self, form: dict[str, Any], photos: list[bytes]) -> NHJob:
        job_id = uuid.uuid4().hex[:12]
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        for i, raw in enumerate(photos, 1):
            (job_dir / f"photo{i}.png").write_bytes(raw)
        classic.write_character(job_dir, form)

        style = str(form.get("style") or "").strip()
        if style not in STYLE_CHOICES:
            style = DEFAULT_STYLE
        job = NHJob(id=job_id, form=form, dir=job_dir, style=style)
        self.jobs[job_id] = job
        job.save()
        self._enqueue(job_id, lambda: _run_story_phase(job))
        return job

    def pick(self, job_id: str, n: int) -> NHJob:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status != STATUS_AWAITING_PICK:
            raise ValueError("지금은 방향을 고를 수 없습니다")
        if not any(d.get("n") == n for d in job.directions):
            raise ValueError(f"방향 {n} 이 없습니다")
        job.pick = n
        self._requeue(job, _run_board_phase)
        return job

    def _require(self, job_id: str, status: str) -> NHJob:
        job = self.jobs.get(job_id)
        if not job:
            raise KeyError(job_id)
        if job.status != status:
            raise ValueError("지금은 그 조작을 할 수 없습니다")
        return job

    def _requeue(self, job: NHJob, fn: Callable[[NHJob], None]) -> None:
        """검수 단계에서 다음 단계로 넘어가거나 다시 만들 때 공통으로 쓴다.

        줄을 서는 동안에도 상태를 바꿔 둔다 — AWAITING_* 그대로 두면 줄에
        있는 동안 같은 조작(승인·재시도 버튼 연타 등)이 `_require` 를 또
        통과해 같은 job 이 두 번 줄을 선다.
        """
        job.status = STATUS_QUEUED
        job.save()
        self._enqueue(job.id, lambda: fn(job))

    def approve_board(self, job_id: str) -> NHJob:
        job = self._require(job_id, STATUS_AWAITING_BOARD)
        self._requeue(job, _run_sheet_phase)
        return job

    def retry_board(self, job_id: str, note: str = "") -> NHJob:
        # 다시 만들 게 없어진 board 단계 대신, 이야기 후보(1단계)를 다시
        # 만든다 — _run_restory_phase 의 docstring 참고.
        job = self._require(job_id, STATUS_AWAITING_BOARD)
        job.note = note or ""
        self._requeue(job, _run_restory_phase)
        return job

    def approve_sheet(self, job_id: str) -> NHJob:
        job = self._require(job_id, STATUS_AWAITING_SHEET)
        self._requeue(job, _run_pages_phase)
        return job

    def retry_sheet(self, job_id: str, note: str = "") -> NHJob:
        job = self._require(job_id, STATUS_AWAITING_SHEET)
        job.note = note or ""
        _clear_sheet(job.run_id)
        self._requeue(job, _run_sheet_phase)
        return job

    # ---- 다시 그리기(페이지 재생성) — job 과 무관하다, 완성된 뒤 둘러보기·
    # 편집실에서도 부를 수 있어야 한다 ------------------------------------- #

    def regen(self, run_id: str, page_no: int) -> str:
        if not unit_image(run_id, page_no):
            raise ValueError("그 페이지가 없습니다")
        regen_id = uuid.uuid4().hex[:12]
        entry = {"id": regen_id, "run_id": run_id, "page": page_no,
                 "status": STATUS_QUEUED, "error": None, "log": ""}
        self.regens[regen_id] = entry
        # 같은 큐를 탄다 — 이미지 호출이라 다른 job 과 동시에 돌면 안 된다.
        self._enqueue(f"regen:{regen_id}", lambda: _run_regen(entry))
        return regen_id

    def regen_status(self, regen_id: str) -> dict[str, Any]:
        entry = self.regens.get(regen_id)
        if not entry:
            raise KeyError(regen_id)
        return {k: entry[k] for k in ("id", "run_id", "page", "status", "error")}


# --------------------------------------------------------------------------- #
# run_id 로 산출물 찾기 — job 없이도(완성된 뒤 다시 열 때) 쓸 수 있게 job 을
# 안 받는다. 편집실(overlay)이 이 함수들로 밑그림을 찾는다.
# --------------------------------------------------------------------------- #

def run_dir(run_id: str) -> Path:
    return NEW_HARNESS / "runs" / run_id


def is_run(run_id: str) -> bool:
    """이 run_id 가 new_harness 것인가. serve.py 가 classic(story-harness)
    라우트와 갈림길에서 쓴다 — story-harness/runs 에 없을 때만 여기로 온다."""
    return run_dir(run_id).is_dir()


def _read_json_safe(base: Path, name: str) -> dict[str, Any]:
    try:
        return json.loads((base / name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def list_runs(limit: int = 60) -> list[dict[str, Any]]:
    """둘러보기 목록에 얹을 new_harness run — pipeline.list_runs() 와 같은
    모양으로 돌려준다(화면이 두 출처를 구분 안 해도 되게). 회차 개념이
    없으므로 늘 1화 하나뿐이다.
    """
    out: list[dict[str, Any]] = []
    root = NEW_HARNESS / "runs"
    if not root.is_dir():
        return out
    for d in sorted(root.glob("2026*"), reverse=True):
        if not d.is_dir():
            continue
        rid = d.name
        drawn = [n for n in page_numbers(rid) if unit_image(rid, n)]
        if not drawn:
            continue                       # 그림이 하나도 없으면 목록에 안 걸린다
        input_doc = _read_json_safe(d, "input.json")
        pick = _read_json_safe(d, "pick.json")
        out.append({
            "run_id": rid,
            "character": str(input_doc.get("name") or ""),
            "title": title_of(rid, pick),
            "genre": str(pick.get("genre") or input_doc.get("genre") or ""),
            "episodes": [1],
            "planned_episodes": [1],
            "next_episode": 2,             # new_harness 는 이어 만들기가 없다
            "cover_episode": 1,
            "cover_page": drawn[0],
            "page_count": len(drawn),
            "engine": "new_harness",       # 화면이 굳이 안 봐도 되지만, 구분은 남긴다
        })
        if len(out) >= limit:
            break
    return out


def result_by_run(run_id: str) -> dict[str, Any]:
    """완성본 화면(app.js 의 paintResult)이 그대로 먹는 모양.

    classic 의 _result_body() 와 같은 자리인데, new_harness 는 콘티 스키마가
    달라서(장·컷 그룹핑 대신 페이지 한 장 = 카드 한 장) 훨씬 단순하다 — 여백/폭
    개념이 없으니(stitch.py 가 그냥 이어붙임) 전부 gap 0 · width 1 이다.
    """
    d = run_dir(run_id)
    numbers = [n for n in page_numbers(run_id) if unit_image(run_id, n)]
    if not numbers:
        return {}
    input_doc = _read_json_safe(d, "input.json")
    pick = _read_json_safe(d, "pick.json")
    return {
        "run_id": run_id,
        "character": str(input_doc.get("name") or ""),
        "title": title_of(run_id, pick),
        "genre": str(pick.get("genre") or input_doc.get("genre") or ""),
        "style_label": "",
        "logline": "",
        "episode": 1,
        "pages": [{"no": n, "gap": 0, "width": 1} for n in numbers],
        "page_count": len(numbers),
        "planned_pages": len(page_numbers(run_id)),
        "preview": False,
        "cut_count": 0,
        "cuts_per_sheet": 1,
        "stage_times": [],
        "seconds": None,
        "layout_mode": "fast",
    }


TITLE_MAX = 60


def titles_path(run_id: str) -> Path:
    return run_dir(run_id) / "titles.json"


def user_title(run_id: str) -> str:
    """사람이 고쳐 둔 제목. 없으면 빈 문자열.

    classic 의 pipeline.user_title 과 같은 규칙인데, 저장 위치가 다르다 —
    저쪽은 story-harness/runs 아래를 본다. new_harness run 에는 그 폴더가
    없어서 제목을 고치면 404 가 났다(실측).
    """
    try:
        doc = json.loads(titles_path(run_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(doc.get("1") or "") if isinstance(doc, dict) else ""


def set_user_title(run_id: str, title: str) -> str:
    """제목을 고쳐 둔다. 빈 값이면 지운다(모델이 지은 이름으로 되돌아간다).

    돌려주는 것은 **앞으로 보일 이름**이다 — 지웠으면 원래 이름.
    """
    d = run_dir(run_id)
    if not d.is_dir():
        raise FileNotFoundError("그런 작품이 없습니다.")
    doc: dict[str, Any] = {}
    try:
        got = json.loads(titles_path(run_id).read_text(encoding="utf-8"))
        if isinstance(got, dict):
            doc = got
    except (OSError, ValueError):
        pass
    clean = " ".join(str(title or "").split())[:TITLE_MAX]
    if clean:
        doc["1"] = clean
    else:
        doc.pop("1", None)
    titles_path(run_id).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                   encoding="utf-8")
    return clean or str(_read_json_safe(d, "pick.json").get("title") or "1화")


def title_of(run_id: str, pick: dict[str, Any]) -> str:
    """화면에 보일 제목 — 사람이 고친 것이 있으면 그것이 이긴다."""
    return user_title(run_id) or str(pick.get("title") or "1화")


def editor_data(run_id: str, episode: int = 1) -> dict[str, Any]:
    """편집실 화면이 그대로 먹는 모양 — classic 의 pipeline.editor_data 와 같은 자리.

    편집실은 **밑그림 한 장 + 그 위에 얹는 것**만 다루므로, new_harness 의
    페이지 하나를 classic 의 "장(scene)" 하나로 그대로 넘긴다. 컷 목록은
    대사 패널이 비지 않게 장면 한 줄을 실어 주는 정도다 — 디테일 직행
    흐름은 대사를 그림 안에 그려 넣으므로 따로 얹을 대사 데이터가 없다.

    그림 크기(w·h)를 같이 주는 이유: 편집실이 얹는 것의 좌표를 퍼센트로
    다루려면 원본 크기를 알아야 한다.
    """
    numbers = [n for n in page_numbers(run_id) if unit_image(run_id, n)]
    if not numbers:
        return {}
    d = run_dir(run_id)
    input_doc = _read_json_safe(d, "input.json")
    pick = _read_json_safe(d, "pick.json")
    detail = _read_json_safe(d, "detail.json")
    # 1페이지는 표지다(detailart.draw 참고) — 사건이 2페이지부터 이어진다.
    # 그림 한 장 = 사건 하나라, 장면 경계를 넘어 편 순서가 곧 페이지 순서다.
    units = [e for s in (detail.get("scenes") or []) for e in scene_events(s)]
    if not units:
        # 이어그리기 흐름(2026-09-02~)은 detail.json 이 없다 — 방향 후보의
        # 장면 한 줄을 그대로 note 로 쓴다(있는 것만이라도 보여준다).
        directions = _read_json_safe(d, "directions.json") or []
        if isinstance(directions, list):
            direction = next((x for x in directions if x.get("n") == pick.get("n")), None)
            if direction:
                units = [{"source": s} for s in direction.get("scenes") or []]

    try:
        from PIL import Image
    except ImportError:
        Image = None

    scenes = []
    for n in numbers:
        w = h = 0
        src = unit_image(run_id, n)
        if Image and src:
            try:
                with Image.open(src) as im:
                    w, h = im.size
            except OSError:
                pass
        one = units[n - 2] if 1 < n <= len(units) + 1 else {}
        note = (one.get("source") or "").strip() if isinstance(one, dict) else ""
        scenes.append({
            "no": n,
            "image": f"/api/runs/{run_id}/page/{n}?w=1080",
            "w": w, "h": h,
            "cuts": [{"no": 1, "shot": "", "beat": "", "speaker": "",
                      "dialogue": "", "narration": "", "thought": "", "sfx": "",
                      "description": note or ("표지" if n == 1 else ""),
                      "lines": []}],
        })
    return {
        "run_id": run_id,
        "character": str(input_doc.get("name") or ""),
        "title": title_of(run_id, pick),
        "genre": str(pick.get("genre") or input_doc.get("genre") or ""),
        "episode": 1,
        "scenes": scenes,
        "page_count": len(numbers),
    }


def page_numbers(run_id: str) -> list[int]:
    """이 run 의 페이지 번호(1..N). pages.json 을 우선 보고, 없으면 실제로
    그려진 파일 수로 판단한다(진행 중에 편집실을 미리 열어도 개수가 맞게)."""
    d = run_dir(run_id)
    try:
        pages = json.loads((d / "pages.json").read_text(encoding="utf-8"))
        if pages:
            return list(range(1, len(pages) + 1))
    except (OSError, ValueError):
        pass
    files = sorted((d / "pages").glob("page*.png")) if (d / "pages").exists() else []
    return list(range(1, len(files) + 1))


def unit_image(run_id: str, no: int) -> Path | None:
    p = run_dir(run_id) / "pages" / f"page{int(no):02d}.png"
    return p if p.exists() else None


def episode_path(job: NHJob) -> Path | None:
    if not job.run_id:
        return None
    return episode_image(job.run_id)


def episode_image(run_id: str) -> Path | None:
    p = run_dir(run_id) / "episode.png"
    return p if p.exists() else None


def sheet_path(job: NHJob) -> Path | None:
    if not job.run_id:
        return None
    p = run_dir(job.run_id) / "sheet.png"
    return p if p.exists() else None


def page_path(job: NHJob, n: int) -> Path | None:
    if not job.run_id:
        return None
    return unit_image(job.run_id, n)


# --------------------------------------------------------------------------- #
# 편집실(overlay) — overlay.py 를 그대로 재사용한다. "장(scene)"을 그대로
# "페이지"로 읽는 것뿐이라 overlay.py 는 한 줄도 고치지 않았다.
# --------------------------------------------------------------------------- #

def read_overlay(run_id: str) -> dict[str, Any]:
    return overlay.load_overlay(run_dir(run_id))


def write_overlay(run_id: str, body: Any) -> dict[str, Any]:
    d = run_dir(run_id)
    if not d.exists():
        raise ValueError("그 작품을 찾지 못했습니다.")
    data = overlay.save_overlay(d, body)
    return {"ok": True, "items": overlay.count_items(data)}


def _mtime(p: Path | None) -> float:
    try:
        return p.stat().st_mtime if p else 0.0
    except OSError:
        return 0.0


def final_unit(run_id: str, no: int) -> Path | None:
    """편집실에서 얹은 것이 있으면 구운 판, 없으면 원본. pipeline.final_unit
    과 같은 규칙이다(볼 때 굽고, 밑그림·얹은 것보다 새 구운 판이 있으면 재사용)."""
    base = unit_image(run_id, no)
    if not base:
        return None
    d = run_dir(run_id)
    ov = overlay.overlay_path(d)
    if not ov.exists():
        return base
    try:
        data = overlay.load_overlay(d)
    except Exception:                                           # noqa: BLE001
        return base
    if not overlay.has_items(data, no):
        return base
    out = overlay.baked_scene_path(d, no)
    if _mtime(out) >= max(_mtime(base), _mtime(ov)):
        return out
    try:
        return overlay.bake_one(d, no, base, data)
    except Exception:                                           # noqa: BLE001
        return base


def bake_run(run_id: str, body: Any = None) -> dict[str, Any]:
    """얹은 것을 전 페이지에 굽고 한 편으로 다시 잇는다. body 에 얹은 것이
    같이 오면(편집실의 "저장하고 굽기") 먼저 저장한다."""
    d = run_dir(run_id)
    if not d.exists():
        raise ValueError("그 작품을 찾지 못했습니다.")
    data = (overlay.save_overlay(d, body)
            if isinstance(body, dict) and body.get("scenes") is not None
            else overlay.load_overlay(d))
    numbers = page_numbers(run_id)
    if not numbers:
        raise ValueError("페이지를 찾지 못했습니다.")
    res = overlay.bake(d, numbers, lambda n: unit_image(run_id, n), data)
    res["items"] = overlay.count_items(data)
    return res


def page_bounds(run_id: str) -> list[tuple[int, int, int, int]] | None:
    """이어붙인 episode.png 안에서 페이지마다 차지하는 자리 —
    watermark.stamp() 의 cut_bounds 로 넘겨서 페이지마다 표시를 찍게 한다.

    stitch.py 의 규칙과 똑같이 계산한다: 가장 넓은 페이지 폭에 맞춰 나머지는
    가운데 정렬, 늘리거나 줄이지 않고, 사이 여백도 없다(stitch.py:36-55).
    """
    numbers = [n for n in page_numbers(run_id) if unit_image(run_id, n)]
    if not numbers:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    sizes = []
    try:
        for n in numbers:
            with Image.open(unit_image(run_id, n)) as im:
                sizes.append(im.size)
    except OSError:
        return None
    width = max(w for w, _h in sizes)
    bounds: list[tuple[int, int, int, int]] = []
    y = 0
    for w, h in sizes:
        bounds.append(((width - w) // 2, y, w, h))
        y += h
    return bounds


def episode_caption(run_id: str) -> str:
    """워터마크 띠 오른쪽에 적을 한 줄 — pipeline.episode_caption() 과 같은
    자리, new_harness 는 회차 개념이 없어 늘 1화다."""
    name = str(_read_json_safe(run_dir(run_id), "input.json").get("name") or "").strip()
    return f"{name} · 1화" if name else "1화"


def final_episode(run_id: str) -> Path | None:
    """내려받기·결과 화면이 보여줄 최종본. 얹은 것이 있으면 구운 한 편.

    이미 구워 둔 판(episode_baked.png)이 있으면 원본(episode.png)이 없어도
    그것을 준다 — stitch.py 를 안 돌린 run(예: 페이지 하나만 있는 실험 run)
    이라도 편집실에서 구운 결과는 보여야 한다.
    """
    d = run_dir(run_id)
    plain = episode_image(run_id)
    baked = overlay.baked_episode_path(d)
    if not plain:
        return baked if baked.exists() else None
    ov = overlay.overlay_path(d)
    if not ov.exists():
        return plain
    try:
        data = overlay.load_overlay(d)
    except Exception:                                           # noqa: BLE001
        return plain
    numbers = page_numbers(run_id)
    if not any(overlay.has_items(data, n) for n in numbers):
        return plain
    out = overlay.baked_episode_path(d)
    newest = max([_mtime(ov)] + [_mtime(unit_image(run_id, n)) for n in numbers])
    if _mtime(out) >= newest:
        return out
    try:
        bake_run(run_id)
    except Exception:                                           # noqa: BLE001
        return plain
    return out if out.exists() else plain
