"""닉네임 + 비밀번호로만 하는 가벼운 계정.

이메일 인증도, 비밀번호 찾기도 없다 — "이 작품을 나중에도 찾고 싶다" 는
사람에게 최소한만 준다. 계정이 없어도 웹툰은 그대로 만들 수 있다(guest).
계정은 결과 화면의 "계정에 담아두기" 를 눌러야만 필요해지는 선택 기능이다
(credits.py 의 uid 와는 다른 축 — uid 는 크레딧 잔액용, 이 계정은 "내
작품 찾기" 용이다. 서로 안 엮는다).

세션은 쿠키(lore_session) 하나로 유지한다. 비밀번호는 PBKDF2(표준
라이브러리만, 외부 패키지 없이)로 해시해서 저장하고 평문은 안 남는다.

`accounts.json` 은 닉네임(소문자 정규화) 을 키로 쓴다 — 닉네임 자체가
유일한 식별자라서 별도 id 가 필요 없다.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
ACCOUNTS_FILE = DATA / "accounts.json"
SESSIONS_FILE = DATA / "sessions.json"
AVATARS_DIR = DATA / "avatars"

SESSION_COOKIE = "lore_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 90   # 90일 — 로그인 상태를 오래 둔다(재로그인 귀찮음 방지)

NICKNAME_RE = re.compile(r"[\w가-힣]{2,20}")
MIN_PASSWORD_LEN = 4
MAX_AVATAR_BYTES = 3 * 1024 * 1024
AVATAR_SIZE = 160

# 프로필 사진 프리셋 — 새로 안 그리고, 이미 있는 루(마스코트) 표정
# 스프라이트 중 정사각형이라 아바타로 바로 쓸 만한 것들을 골랐다.
PRESET_PHOTOS = [
    {"id": "idle-1", "url": "/static/lou/react/idle/01.webp"},
    {"id": "idle-3", "url": "/static/lou/react/idle/03.webp"},
    {"id": "sleep-1", "url": "/static/lou/react/sleep/01.webp"},
    {"id": "pet-1", "url": "/static/lou/react/pet/01.webp"},
    {"id": "shake-1", "url": "/static/lou/react/shake/01.webp"},
    {"id": "click-2", "url": "/static/lou/react/click/02.webp"},
]
DEFAULT_PHOTO_ID = "idle-1"

_lock = threading.Lock()


# ---- 저장 ------------------------------------------------------------- #

def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _save(path: Path, data: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(path)


def _norm(nickname: str) -> str:
    """중복 검사·저장 키 기준 — 대소문자만 다른 닉네임을 다른 사람으로 안 친다."""
    return nickname.strip().lower()


def valid_nickname(nickname: str) -> bool:
    return bool(NICKNAME_RE.fullmatch((nickname or "").strip()))


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                salt.encode("utf-8"), 200_000).hex()


def _preset_url(preset_id: str) -> str | None:
    return next((p["url"] for p in PRESET_PHOTOS if p["id"] == preset_id), None)


# ---- 프로필 사진 -------------------------------------------------------- #

def resolve_photo(photo: dict | None, nickname_key: str) -> str:
    """계정 레코드의 photo 필드를 실제로 화면에 걸 URL 로 바꾼다."""
    photo = photo or {}
    if photo.get("kind") == "upload" and (AVATARS_DIR / f"{nickname_key}.jpg").exists():
        return f"/api/account/avatar/{nickname_key}"
    return _preset_url(photo.get("id", "")) or _preset_url(DEFAULT_PHOTO_ID)


def save_avatar_upload(nickname_key: str, data_url: str) -> tuple[bool, str]:
    """업로드한 사진을 정사각형 썸네일로 줄여 저장한다. (성공?, 오류메시지)"""
    import base64
    import io

    try:
        raw = base64.b64decode(data_url.split(",", 1)[1])
    except (ValueError, IndexError):
        return False, "사진을 읽지 못했습니다"
    if len(raw) > MAX_AVATAR_BYTES:
        return False, "사진이 너무 큽니다 (3MB 까지)"
    AVATARS_DIR.mkdir(parents=True, exist_ok=True)
    dest = AVATARS_DIR / f"{nickname_key}.jpg"
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw))
        im.load()
        # 가운데를 정사각형으로 잘라서 줄인다 — 프로필 동그라미에 걸 것이므로
        # 원본 비율을 그대로 두면 얼굴이 잘리거나 늘어나 보인다.
        w, h = im.size
        side = min(w, h)
        im = im.crop(((w - side) // 2, (h - side) // 2,
                      (w + side) // 2, (h + side) // 2))
        im = im.resize((AVATAR_SIZE, AVATAR_SIZE), Image.LANCZOS)
        im.convert("RGB").save(dest, "JPEG", quality=88, optimize=True)
    except ImportError:
        # Pillow 가 없으면 원본을 그대로 둔다 — 느리고 자르지도 못하지만,
        # 업로드 자체가 안 되는 것보다는 낫다(사진 없는 프리셋은 항상 된다).
        dest.write_bytes(raw)
    except Exception:                                       # noqa: BLE001
        return False, "사진을 열지 못했습니다. 다른 사진으로 시도해 주세요."
    return True, ""


# ---- 계정 CRUD (최소) --------------------------------------------------- #

def public_info(nickname_key: str, account: dict) -> dict:
    return {
        "nickname": account["nickname"],
        "photo_url": resolve_photo(account.get("photo"), nickname_key),
        "claimed_runs": account.get("claimed_runs", []),
    }


def signup(nickname: str, password: str, photo: dict | None,
           agree_terms: bool = False) -> tuple[dict | None, str]:
    nickname = (nickname or "").strip()
    if not valid_nickname(nickname):
        return None, "닉네임은 한글·영문·숫자·밑줄로 2~20자여야 합니다"
    if len(password or "") < MIN_PASSWORD_LEN:
        return None, f"비밀번호는 {MIN_PASSWORD_LEN}자 이상이어야 합니다"
    # 저작권/이용약관 동의 — 멘토 피드백(2026-08-24): 지금 단계에서 전문적인
    # IP 대응은 과하다, 가입 때 약관 동의만 받아도 어느 정도 방어가 된다.
    # 서버에서도 다시 막아야 "체크 안 해도 되던데?" 로 우회가 안 된다.
    if not agree_terms:
        return None, "이용약관에 동의해야 가입할 수 있습니다"
    key = _norm(nickname)
    with _lock:
        accounts = _load(ACCOUNTS_FILE)
        if key in accounts:
            return None, "이미 있는 닉네임입니다"
        salt = secrets.token_hex(16)
        photo = photo or {}
        account = {
            "nickname": nickname,
            "salt": salt,
            "password_hash": _hash_password(password, salt),
            "photo": ({"kind": "preset", "id": photo.get("id") or DEFAULT_PHOTO_ID}
                      if photo.get("kind") != "upload" else {"kind": "upload"}),
            "claimed_runs": [],
            "created_at": time.time(),
            "terms_agreed_at": time.time(),
        }
        accounts[key] = account
        _save(ACCOUNTS_FILE, accounts)
    if photo and photo.get("kind") == "upload" and photo.get("data_url"):
        ok, err = save_avatar_upload(key, photo["data_url"])
        if not ok:
            # 계정 자체는 만들어졌다 — 사진만 프리셋으로 되돌린다. 여기서
            # 회원가입 전체를 실패시키면 "닉네임은 이미 등록됐는데 다시
            # 가입은 안 되는" 막다른 상태가 된다.
            with _lock:
                accounts = _load(ACCOUNTS_FILE)
                accounts[key]["photo"] = {"kind": "preset", "id": DEFAULT_PHOTO_ID}
                _save(ACCOUNTS_FILE, accounts)
    return {"key": key, **public_info(key, accounts[key])}, ""


def verify_password(nickname: str, password: str) -> tuple[dict | None, str]:
    key = _norm(nickname)
    accounts = _load(ACCOUNTS_FILE)
    account = accounts.get(key)
    if not account or _hash_password(password, account["salt"]) != account["password_hash"]:
        return None, "닉네임 또는 비밀번호가 맞지 않습니다"
    return {"key": key, **public_info(key, account)}, ""


def set_photo(nickname_key: str, photo: dict) -> tuple[bool, str]:
    with _lock:
        accounts = _load(ACCOUNTS_FILE)
        account = accounts.get(nickname_key)
        if not account:
            return False, "계정을 찾지 못했습니다"
        if photo.get("kind") == "upload" and photo.get("data_url"):
            ok, err = save_avatar_upload(nickname_key, photo["data_url"])
            if not ok:
                return False, err
            account["photo"] = {"kind": "upload"}
        else:
            pid = photo.get("id") or DEFAULT_PHOTO_ID
            if not _preset_url(pid):
                return False, "그런 프로필 사진이 없습니다"
            account["photo"] = {"kind": "preset", "id": pid}
        _save(ACCOUNTS_FILE, accounts)
    return True, ""


def claimed_by(run_id: str) -> str | None:
    """이 작품을 이미 담아 둔 계정. 없으면 None.

    먼저 담은 사람이 임자라는 규칙(ownership.may_claim)을 세우려면, 담기 전에
    이미 임자가 있는지 물어볼 자리가 있어야 한다.
    """
    with _lock:
        for key, account in _load(ACCOUNTS_FILE).items():
            if run_id in (account.get("claimed_runs") or []):
                return key
    return None


def claim_run(nickname_key: str, run_id: str) -> bool:
    """이 작품을 계정에 담는다(중복 담기는 조용히 무시)."""
    with _lock:
        accounts = _load(ACCOUNTS_FILE)
        account = accounts.get(nickname_key)
        if not account:
            return False
        runs = account.setdefault("claimed_runs", [])
        if run_id not in runs:
            runs.append(run_id)
            _save(ACCOUNTS_FILE, accounts)
    return True


def get_account(nickname_key: str) -> dict | None:
    return _load(ACCOUNTS_FILE).get(nickname_key)


# ---- 저작권 확인 로그 ----------------------------------------------------- #
#
# 멘토 피드백(2026-08-24): 지금은 실사용자가 거의 없는 단계라 전문적인 IP
# 대응까지는 과하다 — 만들 때마다 짧게 확인받는 것으로 어느 정도 방어가
# 된다. 회원가입(agree_terms)과 별개로, "이 job 은 이 사람이 이 시각에
# 확인했다" 는 기록을 한 줄씩 남긴다. 조회 화면은 없다(범위 밖).
IP_CONSENT_FILE = DATA / "ip_consent.jsonl"


def log_ip_consent(uid: str, job_id: str) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "uid": uid, "job_id": job_id}
    with _lock:
        with IP_CONSENT_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


# ---- 세션 --------------------------------------------------------------- #

def create_session(nickname_key: str) -> str:
    token = secrets.token_hex(24)
    with _lock:
        sessions = _load(SESSIONS_FILE)
        sessions[token] = {"nickname_key": nickname_key, "created_at": time.time()}
        _save(SESSIONS_FILE, sessions)
    return token


def session_nickname_key(token: str | None) -> str | None:
    if not token:
        return None
    sessions = _load(SESSIONS_FILE)
    row = sessions.get(token)
    return row["nickname_key"] if row else None


def destroy_session(token: str | None) -> None:
    if not token:
        return
    with _lock:
        sessions = _load(SESSIONS_FILE)
        if token in sessions:
            del sessions[token]
            _save(SESSIONS_FILE, sessions)
