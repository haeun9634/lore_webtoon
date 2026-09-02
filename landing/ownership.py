"""이 작품을 누가 만들었나.

작품(run)에는 주인 표시가 없다. 하네스가 만든 폴더라 제품 사정을 적을 자리가
아니고, 게스트도 만들 수 있어서 계정과 묶이지도 않는다. 그래서 이미 남아 있는
두 기록을 이어 붙여 만든 사람을 찾는다:

    data/ip_consent.jsonl      {uid, job_id}   — 만들 때마다 남는 저작권 확인
    jobs/<job_id>/state.json   {id, run_id}    — 그 작업이 어느 run 이 됐는지

**왜 필요한가.** 「계정에 담아두기」가 run_id 만 받고 있어서, 주소만 알면 남의
작품도 자기 계정에 담을 수 있었다. 담고 나면 그 작품의 공개 여부까지 바꿀 수
있으므로(visibility.py 가 claimed_runs 를 믿는다), 남이 올린 작품을 아무나
둘러보기에서 내릴 수 있다는 뜻이었다.

**한계를 분명히 해 둔다.** uid 는 브라우저가 만들어 들고 다니는 값이라 마음먹고
꾸미면 흉내낼 수 있다. 이 파일이 막는 것은 "링크를 받은 사람이 남의 작품을
가져가는 것" 이지, 작정한 공격이 아니다. 제대로 하려면 만들 때 서버가 주인을
적어 두고 로그인으로 확인해야 하는데, 그건 계정이 선택 기능인 지금 구조에서는
할 수 없다.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
JOBS = HERE / "jobs"
CONSENT_FILE = DATA / "ip_consent.jsonl"

_lock = threading.Lock()
_cache: dict[str, str] = {}          # run_id -> uid
_cache_mtime: float = -1.0


def _job_uids() -> dict[str, str]:
    """job_id -> uid. 저작권 확인 원장에 만들 때마다 한 줄씩 쌓인다."""
    out: dict[str, str] = {}
    try:
        text = CONSENT_FILE.read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue                  # 반쪽 줄 하나가 전체를 막지 않게
        job_id, uid = row.get("job_id"), row.get("uid")
        if job_id and uid:
            out[str(job_id)] = str(uid)
    return out


def _rebuild() -> dict[str, str]:
    owners: dict[str, str] = {}
    job_uids = _job_uids()
    if not job_uids or not JOBS.is_dir():
        return owners
    for job_id, uid in job_uids.items():
        state = JOBS / job_id / "state.json"
        try:
            run_id = json.loads(state.read_text(encoding="utf-8")).get("run_id")
        except (OSError, ValueError):
            continue
        if run_id:
            owners[str(run_id)] = uid
    return owners


def creator_uid(run_id: str) -> str | None:
    """이 run 을 만든 uid. 모르면 None (원장이 지워졌거나 하네스를 직접 돌린 run)."""
    global _cache, _cache_mtime
    with _lock:
        try:
            mtime = CONSENT_FILE.stat().st_mtime
        except OSError:
            mtime = 0.0
        # 원장에 줄이 늘 때만 다시 읽는다 — 담을 때마다 job 폴더를 전부 훑으면
        # 작품이 쌓일수록 눈에 띄게 느려진다.
        if mtime != _cache_mtime:
            _cache = _rebuild()
            _cache_mtime = mtime
        return _cache.get(str(run_id))


def may_claim(run_id: str, uid: str, already_claimed_by: str | None) -> tuple[bool, str]:
    """이 사람이 이 작품을 자기 계정에 담아도 되는가.

    반환: (되는가, 안 되는 이유)
    """
    if already_claimed_by:
        # 먼저 담은 사람이 임자다. 여기를 안 막으면 남이 담아 둔 작품을
        # 가로채서 공개 여부까지 바꿀 수 있다.
        return False, "이미 다른 계정에 담긴 작품입니다"
    made_by = creator_uid(run_id)
    if made_by is None:
        # 누가 만들었는지 기록이 없는 옛 작품. 아직 아무도 안 담았으므로 통과시킨다
        # — 여기서 막으면 기록이 생기기 전에 만든 자기 작품을 못 담는다.
        return True, ""
    if uid and made_by == uid:
        return True, ""
    return False, "내가 만든 작품만 담을 수 있습니다"
