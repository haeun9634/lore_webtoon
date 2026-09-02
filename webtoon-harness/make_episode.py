#!/usr/bin/env python
"""명령 하나로 웹툰 1화. 스토리 → 캐릭터 시트 → 컷 → 그림 → episode.png

지금까지 한 화를 만들려면 네 명령을 순서대로 쳐야 했다:

    python story.py --character characters/siha.json
    python story.py --charsheet --run-id <id>
    python story.py --charsheet --run-id <id> --pick
    python run.py --run-id <id> --episode 1 --mode scene -c S+ --style cinematic

문제는 순서를 외워야 한다는 것이 아니라, **어긋나면 조용히 틀린 것이 나온다**는
것이었다. 시트를 안 뽑고 컷으로 가면 지난 run 의 시트가 붙었고(제라프 사건),
그림체를 시트보다 나중에 바꾸면 시트와 컷이 다른 그림체를 가리켰다. 순서가
지식이 아니라 코드에 있어야 한다.

## 이 스크립트가 하지 않는 것

**판단을 대신하지 않는다.** 블라인드 평가(사람이 "다음 화가 궁금한가"를 답하는
자리)는 건너뛰지 않는다. 재미 판정은 이 파이프라인에서 사람만 하는 일이고,
그걸 자동으로 통과시키면 하네스 전체가 의미를 잃는다.

시트 채택도 자동으로 하지 않는다 — 후보가 1장이면 story.py 가 스스로 채택하고,
여러 장이면 멈춰서 사람에게 보낸다. 고를 것이 있을 때만 사람을 부른다.

## 이어서 돌리기

각 단계는 이미 끝난 일을 다시 하지 않는다. 중간에 실패하면 고치고 같은 명령을
다시 치면 된다 — 앞 단계는 캐시를 쓰고 실패한 지점부터 이어진다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STORY = HERE.parent / "story-harness"

# story.py/webtoon.py 의 STATUS_OK·STATUS_HUMAN 과 같은 문자열이다. 두 CLI 모두
# 게이트가 소진돼 사람 확인이 필요한 상태에서도 프로세스 종료 코드는 0 을
# 낸다(각자의 main() 이 항상 return 0) — 그래서 exit code 만으로는 못 잡고,
# 각 단계가 남긴 meta.json 의 status 를 직접 읽어야 한다.
STATUS_OK = "ok"
STATUS_HUMAN = "사람확인필요"

# 콘솔이 cp949 면 '—' 같은 문자에서 print 가 UnicodeEncodeError 로 죽는다.
# 안내 문구 하나 때문에 실행이 멈추면 안 되므로 못 찍는 글자는 대체 문자로
# 흘린다 (run.py 와 같은 처리).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):       # 파이프로 감싼 스트림 등
        pass


def run(cmd: list[str], cwd: Path) -> int:
    """한 단계 실행. 출력은 그대로 흘려보낸다 — 사람이 봐야 하는 경고가 많다."""
    print(f"\n{'=' * 78}\n$ {' '.join(cmd)}\n{'=' * 78}", flush=True)
    return subprocess.call([sys.executable, *cmd], cwd=str(cwd))


def latest_run(runs: Path) -> str | None:
    """가장 최근 run_id. --character 로 새로 만든 뒤 그 id 를 찾는 데 쓴다."""
    dirs = [d for d in runs.iterdir() if d.is_dir() and (d / "p1.json").exists()]
    return max(dirs, key=lambda d: d.stat().st_mtime).name if dirs else None


def has_sheet(runs: Path, run_id: str) -> bool:
    picks = runs / run_id / "charsheet" / "charsheet_picks.json"
    if not picks.exists():
        return False
    try:
        data = json.loads(picks.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return False
    return bool((data.get("picks") or data))


def blind_done(runs: Path, run_id: str) -> bool:
    """사람이 블라인드 평가를 했는가. 안 했으면 webtoon.py 가 스스로 멈춘다."""
    csv = runs / "blind_result.csv"
    return csv.exists() and run_id in csv.read_text(encoding="utf-8-sig", errors="ignore")


def stage_status(meta_path: Path) -> tuple[str | None, str]:
    """단계가 남긴 meta.json 의 (status, note). 없거나 못 읽으면 (None, "")."""
    if not meta_path.exists():
        return None, ""
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, ""
    return data.get("status"), data.get("note") or ""


def main() -> int:
    p = argparse.ArgumentParser(
        description="웹툰 1화를 끝까지 만든다 (스토리 → 시트 → 컷 → 그림).")
    p.add_argument("--character", help="캐릭터 JSON. 주면 스토리부터 새로 만든다")
    p.add_argument("--run-id", help="이미 있는 스토리 run 으로 이어서")
    p.add_argument("--episode", type=int, default=1)
    p.add_argument("--style", default=None,
                   help="그림체. 생략하면 config.yaml 의 style_default")
    p.add_argument("--condition", "-c", default="S+",
                   help="첨부 조건 (기본 S+ = 통합 시트 + 직전 장)")
    p.add_argument("--split", action="store_true",
                   help="시트를 3장으로 (기본은 통합 1장). 조건 C/C+/D 용")
    p.add_argument("--dry-run", action="store_true",
                   help="마지막 그림 단계를 프롬프트 확인까지만")
    args = p.parse_args()

    runs = STORY / "runs"
    if not args.character and not args.run_id:
        return p.error("--character 또는 --run-id 중 하나는 필요합니다.")

    # ---- 1. 스토리 ------------------------------------------------------- #
    run_id = args.run_id
    if args.character:
        if run(["story.py", "--character", args.character], STORY) != 0:
            print("\n[중단] 스토리 생성이 실패했습니다.")
            return 1
        run_id = latest_run(runs)
        if not run_id:
            print("\n[중단] 새로 만든 run 을 찾지 못했습니다.")
            return 1
        print(f"\n[run] {run_id}")

    if not (runs / run_id / "p1.json").exists():
        print(f"\n[중단] {runs / run_id} 에 p1.json 이 없습니다.")
        return 1

    status, note = stage_status(runs / run_id / "meta.json")
    if status == STATUS_HUMAN:
        print(f"\n{'=' * 78}")
        print("[사람이 할 차례] 스토리 단계 게이트 재시도가 소진돼 사람 확인이 필요합니다.")
        if note:
            print(f"  {note}")
        print(f"    cd {STORY}")
        print(f"    python story.py --character <카드 수정> 로 다시 만들거나,")
        print(f"    또는 이 run_id 로 그대로 진행할지 직접 판단하세요.")
        return 2
    elif status not in (None, STATUS_OK):
        print(f"\n[중단] 스토리 단계가 실패로 끝났습니다 ({status}).")
        if note:
            print(f"  {note}")
        return 1

    # ---- 2. 재미 판정 — 사람만 하는 일 ------------------------------------ #
    if not blind_done(runs, run_id):
        print(f"\n{'=' * 78}")
        print("[사람이 할 차례] 블라인드 평가가 아직입니다.")
        print("  재미 판정은 이 파이프라인에서 사람만 하는 일이라 건너뛰지 않습니다.")
        print("  재미없는 설계로 컷을 아무리 잘 뽑아도 재미없는 웹툰이 나옵니다.\n")
        print(f"    cd {STORY}")
        print(f"    python story.py --serve        # 브라우저에서 답하고 Ctrl+C")
        print(f"\n  그 다음 같은 명령을 다시 치면 여기서부터 이어집니다.")
        return 2

    # ---- 3. 캐릭터 시트 --------------------------------------------------- #
    if has_sheet(runs, run_id):
        print(f"\n[시트] 이미 채택돼 있습니다 — 건너뜁니다.")
    else:
        cmd = ["story.py", "--charsheet", "--run-id", run_id]
        if args.split:
            cmd.append("--split")
        if run(cmd, STORY) != 0:
            print("\n[중단] 캐릭터 시트 생성이 실패했습니다.")
            return 1
        if not has_sheet(runs, run_id):
            print(f"\n{'=' * 78}")
            print("[사람이 할 차례] 시트 후보가 여러 장이라 채택이 필요합니다.")
            print(f"    cd {STORY}")
            print(f"    python story.py --charsheet --run-id {run_id} --pick")
            print(f"\n  그 다음 같은 명령을 다시 치면 여기서부터 이어집니다.")
            return 2

    # ---- 4. 콘티 (컷 분해) ------------------------------------------------ #
    cuts = runs / run_id / "webtoon" / f"ep{args.episode:02d}_cuts.json"
    if cuts.exists():
        print(f"\n[콘티] {cuts.name} 이 이미 있습니다 — 건너뜁니다.")
    else:
        if run(["webtoon.py", "--run", run_id], STORY) != 0:
            print("\n[중단] 콘티 생성이 실패했습니다.")
            return 1
        # webtoon.py 의 main() 도 STATUS_HUMAN/실패에서 종료 코드는 항상 0 이라
        # (story.py 와 같은 사정) meta.json 을 따로 읽어야 한다.
        status, note = stage_status(runs / run_id / "webtoon" / "meta.json")
        if status == STATUS_HUMAN:
            print(f"\n{'=' * 78}")
            print("[사람이 할 차례] 콘티 단계 게이트 재시도가 소진돼 사람 확인이 필요합니다.")
            if note:
                print(f"  {note}")
            print(f"    cd {STORY}")
            print(f"    python webtoon.py --run {run_id} --resume  # 확인 후 이어서")
            return 2
        elif status not in (None, STATUS_OK):
            print(f"\n[중단] 콘티 단계가 실패로 끝났습니다 ({status}).")
            if note:
                print(f"  {note}")
            return 1

    # ---- 5. 그림 ---------------------------------------------------------- #
    cmd = ["run.py", "--run-id", run_id, "--episode", str(args.episode),
           "--mode", "scene", "-c", args.condition, "--yes"]
    if args.style:
        cmd += ["--style", args.style]
    if args.dry_run:
        cmd.append("--dry-run")
    code = run(cmd, HERE)
    if code != 0:
        print("\n[중단] 그림 생성이 실패했습니다.")
        return 1

    out = HERE / "outputs" / run_id / f"ep{args.episode}" / "episode.png"
    print(f"\n{'=' * 78}")
    if out.exists():
        print(f"1화 완성 -> {out}")
    else:
        print(f"끝났지만 {out.name} 이 없습니다 — 위 출력을 보세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
