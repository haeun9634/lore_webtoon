"""크레딧 잔액 + 프리토타이핑(가짜) 결제.

계정 시스템이 없어서(로그인이 없다) 브라우저가 만든 uid(localStorage,
`app.js`의 `getUid()`)로 사람을 구분한다. 잔액은 `data/credits.json` 하나에
`{uid: {"balance": N}}` 로 저장한다.

**CRUD·환불·내역 화면은 일부러 없다** — 잔액 표시 + 소진만으로 충분한
목업이다. 결제도 실제 PG 연동이 아니라, "충전하기" 를 누르고 카드사를
고르면 그 자리에서 크레딧을 지급한다(지불 의사가 있는지 확인하는 게
목적이라 진짜로 돈을 받을 필요가 없다). 카드번호 입력 화면은 아예 없다 —
실제 결제 정보를 받는 것처럼 보이면 안 되기 때문에 카드 고르기 딱 한 걸음
앞에서 멈춘다.

몇 명이 충전하기를 눌렀는지, 몇 명이 실제로 크레딧을 썼는지는
`data/credit_events.jsonl` 한 줄씩으로 남긴다 — 조회 화면은 없고, 필요할
때 파일을 그대로 읽는다. 소진(`spend`)은 이 모듈이 아니라 부르는 쪽
(`serve.py`)이 남긴다 — `charge_success` 도 같은 자리(호출부)에서 남기는
것과 같은 자리다.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
CREDITS_FILE = DATA / "credits.json"
EVENTS_FILE = DATA / "credit_events.jsonl"

# 아래 값들은 `Lore_비용모델.xlsx`(2026-08-24, 실제 API 호출 로그 기반)의
# "크레딧설계" 시트를 그대로 옮긴 것 — 1크레딧 = 이미지 1장(재생성) 원가
# 200원에 맞춘 값이다. 임의로 지어낸 숫자가 아니므로, 시트가 갱신되면 여기도
# 같이 고친다.

# 신규 가입 지급(1회) = 캐릭터 1개(3) + 1화(8) + 재생성 1회(1) = 첫 경험 1바퀴.
# "월 무료 리필 3크레딧"은 반복 지급(스케줄러)이 필요해 최소 기능 범위 밖 —
# 넣지 않는다(가입 지급만 있다).
START_BALANCE = 12

# 웹툰 1화 생성(12컷 · 이미지 4장, 프리미엄 등급) = 8크레딧. 미리보기는
# pipeline.py 의 --cuts 1-3 로 4장 중 1장만 그리므로 딱 1/4 — 옛 목업 값
# (240/60)의 비율과 같다. 화질 등급(스탠다드 0.6배)은 미실측 추정치라 아직
# 안 넣는다(시트에도 "구조만 잡아둔 상태"라고 적혀 있다).
# **한 편 = 12크레딧, 고정. 만들 때 전액을 한 번에 받는다.**
#
#   웹툰 만들기(12C) → 일부(절반가량)를 먼저 보여줌 → 「1화 전체 보기」는
#   추가 결제 없음 — 이미 산 웹툰을 이어서 보는 것이다.
#
# 반씩(6+6) 나누는 안도 실험했지만 버렸다: 미리보기가 마음에 든 순간 결제
# 버튼을 또 눌러야 하면 구매 흐름이 거기서 끊긴다. 장당·컷당·모드별 변동가도
# 버렸다 — 화마다 값이 달라지면 공정하긴 한데 "얼마 나올지 모른다"가 몇
# 크레딧 아끼는 것보다 구매를 더 막는다. 예외가 없어야 "한 편 12크레딧"
# 한 문장이 언제나 참이다.
#
# 실비 참고: fast 는 이미지 4장쯤이라 넉넉하고, 웹툰 묶음은 10장+라 밑진다.
# 프리토타이핑 단계라 단순함을 택했다 — 실측 원가가 쌓이면 다시 본다.
CREDIT_FULL = 12
# 연출 모드 배수 — 값에 안 쓴다(위 참고). 부르는 곳 호환용으로만 남긴다.
CREDIT_WEBTOON_MULT = 1

# 시트의 "이미지 1장 재생성"(1크레딧)·"+피드백"(2크레딧) 행은 여기 안 옮겼다
# — 장(scene) 다시 그리기는 결과 화면(app.js)과 편집실 샘플(editor.js)이
# 같은 서버 엔드포인트(/scenes/<n>/regen)를 같이 쓰는데, editor.js 쪽은
# 처음부터 "샘플" 목업이라 uid 도 안 보내고 자기만의 가짜 크레딧을 따로
# 센다. 이 상태에서 서버 쪽만 실소진을 걸면 결과 화면에서는 실제로 깎이고
# 편집실 샘플에서는 안 깎이는 게 갈라져서 헷갈린다 — 최소 기능 범위에서는
# "만들기" 한 곳만 실소진으로 걷고, 다시 그리기는 그대로 둔다.

# 충전 상품 — "D. 유료 플랜" 표를 그대로 옮겼더니 크레딧당 450~550원(1크레딧
# 원가 200원에 원가율 36~44%를 곱한 값)이 나왔는데, 이건 원가를 판매가로
# 그대로 환산한 것뿐이라 "이미지 한 장에 500원대" 로 읽혀 첫인상이 확 비싸다.
# 200원이라는 원가 자체도 시트에 "스탠다드 등급 미실측 추정치" 라고 적혀
# 있어 아직 검증 전이다. 실측·재시도율 반영 후 크레딧 원가가 낮아질 걸
# 가정하고(200원 → 120원대), 그 경우의 판매가로 바꿔 뒀다 — 정식 가격이
# 아니라 프리토타이핑용 자리표시자다. 실측이 끝나면 다시 맞춘다.
# 이름은 항해 여정을 잇는다 — (승선: 무료) → 출항(막 떠남) → 항해(가는 중)
# → 탐험(가장 멀리). "승선" 은 파는 것이 아니라 하루 1회 무료로 주는 것이라
# PACKAGES 에 없다(DAILY_FREE_CREDITS 참고).
# "스타터·베이직·대용량·대형" 은 어느 AI 서비스에나 있는 용량 말이라 LORE 의
# 바다가 안 보였다 — 크레딧은 사용량이 아니라 "이야기를 만들 수 있는 자원"
# 이므로, 충전 화면에서도 같은 바다를 항해하게 한다.
# 예전엔 맨 앞에 "물결"(20C·3,900원)이 있었는데, "수면"과 물빛 이미지가
# 겹쳐 두 단계가 한 단계처럼 읽혔다 — 그 자리는 DAILY_FREE_CREDITS(아래)의
# 무료 지급으로 대체했고, 그 결과 "출항" 이 유료 첫 단계가 됐다.
# id 는 그대로 둔다 — 이미 저장된 결제 기록(ledger)이 id 로 남아 있다.
# ("starter"/물결 id 는 더 안 판다 — 지난 결제 기록에는 남아 있지만
# package() 로는 더 안 찾힌다.)
PACKAGES = [
    {"id": "basic", "label": "출항", "emoji": "🌊",
     "tagline": "캐릭터와 함께 이야기를 떠나 보세요.",
     "credits": 60, "price": 9_900, "badge": "가장 많이 골라요"},
    {"id": "bulk", "label": "항해", "emoji": "🐋",
     "tagline": "더 깊고 긴 이야기를 만들어 보세요.",
     "credits": 140, "price": 19_900},
    {"id": "mega", "label": "탐험", "emoji": "🌌",
     "tagline": "마음껏 이야기의 바다를 탐험해 보세요.",
     "credits": 300, "price": 39_900},
]

# 하루 1회 무료 지급("승선") — 예전 "물결"(3,900원에 20크레딧) 자리를 대신한다.
# 스케줄러 없이 "요청 시점에 오늘치를 이미 받았는지 확인" 만으로 충분해서
# (반복 지급 스케줄러가 필요했던 옛 "월 무료 리필" 안과 달리) 최소 기능
# 범위 안에 들어온다 — claim_daily() 가 그 확인·지급을 한 번에 한다.
DAILY_FREE_CREDITS = 20

_lock = threading.Lock()
_UID_RE = re.compile(r"[\w-]{1,64}")


def valid_uid(uid: str | None) -> bool:
    return bool(uid) and bool(_UID_RE.fullmatch(uid))


def package(package_id: str) -> dict | None:
    return next((p for p in PACKAGES if p["id"] == package_id), None)


def _load() -> dict:
    if not CREDITS_FILE.exists():
        return {}
    try:
        return json.loads(CREDITS_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _save(data: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = CREDITS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    tmp.replace(CREDITS_FILE)


def balance(uid: str) -> int:
    """잔액을 본다 — 처음 보는 uid 면 시작 잔액을 새로 만들어 준다."""
    if not valid_uid(uid):
        return 0
    with _lock:
        data = _load()
        row = data.get(uid)
        if row is None:
            data[uid] = {"balance": START_BALANCE}
            _save(data)
            return START_BALANCE
        return int(row.get("balance", 0))


def spend(uid: str, amount: int) -> tuple[bool, int]:
    """실제로 만들 때 크레딧을 뗀다. 모자라면 떼지 않고 (False, 지금 잔액)."""
    if not valid_uid(uid) or amount <= 0:
        return False, 0
    with _lock:
        data = _load()
        row = data.setdefault(uid, {"balance": START_BALANCE})
        bal = int(row.get("balance", 0))
        if bal < amount:
            return False, bal
        bal -= amount
        row["balance"] = bal
        _save(data)
        return True, bal


def charge(uid: str, package_id: str) -> tuple[dict | None, int]:
    """결제 완료 처리 — 상품의 크레딧을 그 자리에서 지급한다."""
    pkg = package(package_id)
    if not valid_uid(uid) or not pkg:
        return None, 0
    with _lock:
        data = _load()
        row = data.setdefault(uid, {"balance": START_BALANCE})
        bal = int(row.get("balance", 0)) + pkg["credits"]
        row["balance"] = bal
        _save(data)
        return pkg, bal


def daily_claim_state(uid: str) -> dict:
    """오늘 하루 무료 지급을 이미 받았는지만 본다 — 지급은 안 한다."""
    if not valid_uid(uid):
        return {"claimed": False, "balance": 0}
    data = _load()
    row = data.get(uid) or {}
    today = time.strftime("%Y-%m-%d")
    return {"claimed": row.get("daily_claim_date") == today,
            "balance": int(row.get("balance", START_BALANCE))}


def claim_daily(uid: str) -> dict:
    """하루 1회 무료 크레딧 지급 — 날짜만 보고 하루에 한 번으로 막는다.

    스케줄러 없이 요청이 들어온 시점에 "오늘치를 이미 받았는가" 만 확인하면
    되므로, 반복 지급마다 서버가 깨어 있어야 하는 방식보다 단순하다."""
    if not valid_uid(uid):
        return {"granted": False, "balance": 0}
    today = time.strftime("%Y-%m-%d")
    with _lock:
        data = _load()
        row = data.setdefault(uid, {"balance": START_BALANCE})
        if row.get("daily_claim_date") == today:
            return {"granted": False, "balance": int(row.get("balance", 0))}
        bal = int(row.get("balance", 0)) + DAILY_FREE_CREDITS
        row["balance"] = bal
        row["daily_claim_date"] = today
        _save(data)
        return {"granted": True, "balance": bal, "credits_added": DAILY_FREE_CREDITS}


def log_event(event: str, uid: str, **extra) -> None:
    """충전하기 클릭 · 결제 완료 등을 한 줄씩 남긴다.

    "몇 명이 충전 버튼을 눌렀는지" 는 이 로그를 uid 기준으로 나중에 세어
    보면 된다 — 별도 집계·조회 화면은 안 만든다(내역 기능은 범위 밖)."""
    DATA.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.time(), "event": event, "uid": uid, **extra}
    with _lock:
        with EVENTS_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def creation_cost(preview: bool = True, layout_mode: str = "fast") -> int:
    """만들기 값 — 한 편 전액. preview·layout_mode 는 받되 값을 바꾸지
    않는다: 미리보기로 시작해도 전액을 먼저 받고, 나머지 생성은 공짜다."""
    return CREDIT_FULL
