"""작품을 둘러보기에 걸지 말지.

**기본은 공개다.** 둘러보기는 남이 만든 것을 구경하는 자리인데 기본이 비공개면
아무것도 안 걸려서, 처음 온 사람에게는 고장난 화면으로 보인다. 대신 만들기
마지막 걸음에서 "둘러보기에 올라간다"고 미리 말하고, 마이페이지에서 언제든
내릴 수 있게 한다.

그래서 이 파일이 들고 있는 것은 **숨긴 것의 목록뿐**이다. 공개가 기본이면
새 작품은 아무것도 안 적어도 걸리고, 파일에는 사람이 직접 내린 것만 쌓인다.
목록 전체를 들고 있다가 run 하나 늘 때마다 갱신하는 것보다 어긋날 구석이 적다.

run 폴더(story-harness/runs/…) 에는 안 적는다 — 하네스는 완성본으로 두고,
제품 사정은 제품 레이어(landing/)에만 남긴다는 이 저장소 규칙 때문이다.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
HIDDEN_FILE = DATA / "hidden_runs.json"

_lock = threading.Lock()


def _load() -> set[str]:
    try:
        raw = json.loads(HIDDEN_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    # 예전 판이나 손으로 고친 파일이 들어와도 목록 하나로만 읽는다.
    if isinstance(raw, dict):
        raw = raw.get("hidden", [])
    if not isinstance(raw, list):
        return set()
    return {str(r) for r in raw if r}


def _save(hidden: set[str]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = HIDDEN_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sorted(hidden), ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(HIDDEN_FILE)          # 쓰다 죽어도 반쪽 파일이 안 남는다


def hidden_runs() -> set[str]:
    """지금 숨겨져 있는 run_id 전부."""
    with _lock:
        return _load()


def is_public(run_id: str) -> bool:
    return str(run_id) not in hidden_runs()


def set_public(run_id: str, public: bool) -> None:
    run_id = str(run_id)
    with _lock:
        hidden = _load()
        if public:
            hidden.discard(run_id)
        else:
            hidden.add(run_id)
        _save(hidden)


def filter_public(runs: list[dict]) -> list[dict]:
    """둘러보기에 걸 것만 남긴다."""
    hidden = hidden_runs()
    return [r for r in runs if str(r.get("run_id")) not in hidden]


def mark(runs: list[dict]) -> list[dict]:
    """각 run 에 지금 공개 상태를 얹는다(마이페이지가 껐다 켰다 하는 데 쓴다)."""
    hidden = hidden_runs()
    for r in runs:
        r["public"] = str(r.get("run_id")) not in hidden
    return runs
