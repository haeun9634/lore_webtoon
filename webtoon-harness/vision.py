"""그려진 컷에서 **사람과 빈 자리를 찾는다** — 그림을 그린 모델에게 물어서.

## 왜 이 방법인가

말풍선을 어디에 놓을지 정하려면 두 가지를 알아야 한다: 말하는 사람이 어디
있는가(꼬리가 갈 곳), 그리고 어디가 비어 있는가(풍선이 앉을 곳).

코드는 그림을 못 읽는다. 시도해 본 것과 결과:

  · **흰 영역 찾기(연결요소 분석)** — 밝은 복도 그림에서 창문·바닥·벽이 전부
    후보로 걸렸다. 5장 중 한 장은 아예 0개를 찾았다. 그리고 찾아도 "그게
    누구의 말풍선인가"는 알 수 없다.
  · **자리를 미리 약속하기**(프롬프트로 "위쪽을 비워라") — 모델이 지키면 맞고
    안 지키면 얼굴 위에 놓인다. 보장이 아니다.

그래서 **묻는다.** 그림을 만든 것과 같은 계열의 모델이 그 그림을 보고 좌표로
답한다. 실측(1536x2752 복도 장면): 인물 6명을 전부 찾고 머리 위치를 주었으며,
옷·머리색으로 서로 구별했고, 빈 공간을 이유와 함께 짚었다.

## 화자를 어떻게 특정하는가

"6명 중 누가 하윤재인가"를 코드가 판정하지 않는다. **물어볼 때 알려 준다** —
콘티의 speaker(누가 말하는가)와 명부의 외형("연청 후드티, 짧은 흑갈색 머리")을
같이 넘기면, 모델이 그 사람을 지목해 좌표를 돌려준다.

## 결과는 파일로 남는다

호출 결과는 캐시된다(같은 그림을 두 번 묻지 않는다). 그리고 최종 배치는
사람이 고칠 수 있는 JSON 으로 나간다 — 좌표도 글자도. 고친 뒤 다시 조립할 때
API 호출은 0회다.
"""

from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import Any

LAYOUT_FILE = "layout_bubbles.json"
CACHE_FILE = "vision_cache.json"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# 물어볼 때 그림을 줄여 보낸다. 좌표는 0~1000 정규화라 원본 크기와 무관하고,
# 줄이면 토큰이 줄고 빨라진다.
PROBE_MAX = 768


class VisionError(RuntimeError):
    """좌표를 못 받았다. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


ASK = """이 웹툰 컷 이미지를 보고 JSON 으로만 답하세요.
좌표는 **0~1000 정규화**한 [ymin, xmin, ymax, xmax] 입니다.

[이 컷에 나오는 인물]
{cast}

[이 컷에서 말하는 사람]
{speaker}

{{"speaker_found": true 또는 false,
  "speaker_head": [y,x,y,x],
  "people": [{{"who": "누구인지(위 목록의 이름. 모르면 특징)", "head": [y,x,y,x]}}],
  "empty": [{{"box": [y,x,y,x], "note": "왜 비어 있는가"}}]}}

speaker_head : 말하는 사람의 **얼굴/머리** 상자. 그 사람이 화면에 없으면
               speaker_found 를 false 로 하고 speaker_head 는 빈 배열.
empty        : 말풍선을 얹어도 **얼굴이나 중요한 것을 가리지 않는** 빈 자리를
               넓은 것부터 2~4개. 하늘·벽·바닥처럼 단순한 면이 좋습니다.
               인물의 얼굴과 겹치는 자리는 절대 넣지 마세요.

다른 말 없이 JSON 만 출력하세요."""


# --------------------------------------------------------------------------- #
# 작화 사고 검수 — 실사용자 지적으로 새로 만든 것 (2026-08)
# --------------------------------------------------------------------------- #
# "덫에 걸린 생쥐의 머리가 발로 되어 있고, 새싹이 그 위에 자라나 있는 등
#  ai 생성물의 어색함이 드러난다."
#
# 이런 것은 프롬프트로 못 막는다 — 모델은 자기가 손가락을 여섯 개 그린 줄
# 모른다. 그린 다음에 **보고** 잡는 수밖에 없다. 그래서 그림을 그린 것과 같은
# 계열의 모델에게 "이 그림에 이상한 것이 있냐"고 되묻는다.
#
# ★ 기본으로 돌지 않는다. 컷마다 API 호출이 한 번씩 더 붙어서 원가가 오른다
#   (지금도 1회 생성 1,600원 vs 지불 의사 700~800원으로 역마진이다).
#   run.py --check-art 로 켤 때만 돈다.
# ★ 판정이 아니라 **제보**다. 여기서 이상하다고 한 컷을 자동으로 다시 뽑지
#   않는다. 오탐이 있을 수밖에 없고, 다시 뽑는 것은 또 돈이 드는 일이라
#   사람이 보고 정하는 편이 맞다.
INSPECT_ASK = """이 웹툰 컷 그림에 **그림 자체의 사고**가 있는지 보고 JSON 으로만 답하세요.

찾는 것 — 이미지 생성 모델이 흔히 내는 사고입니다:
- 손·발이 잘못 붙었거나 개수가 틀림 (손가락 6개, 발이 머리 자리에 붙음 등)
- 몸의 일부가 사라졌거나 두 번 그려짐, 팔다리가 몸과 안 이어짐
- 동물·사물의 구조가 말이 안 됨 (머리와 다리가 뒤바뀜 등)
- 있어야 할 곳이 아닌 데서 자라거나 솟은 것 (몸 위의 새싹, 벽을 뚫은 가구)
- 물건이 공중에 떠 있거나 손을 통과함
- 얼굴이 녹거나 눈이 짝짝이로 뭉개짐
- 글자가 글자처럼 보이지만 읽을 수 없음

찾지 않는 것 — 이것들은 사고가 아닙니다:
- 그림체·화풍·색감이 취향에 안 맞는 것
- 구도나 연출이 밋밋한 것
- 만화적 과장 (큰 눈, 과장된 표정, 데포르메)

{{"issues": [{{"box": [y,x,y,x], "what": "무엇이 어떻게 잘못됐는지 한 줄",
              "severity": "high 또는 low"}}]}}

box       : **0~1000 정규화**한 [ymin, xmin, ymax, xmax].
severity  : high = 독자가 바로 알아본다. low = 뜯어봐야 보인다.
이상이 없으면 issues 를 빈 배열로 두세요.

확신이 없으면 넣지 마세요 — 없는 것을 있다고 하는 편이 더 나쁩니다.
다른 말 없이 JSON 만 출력하세요."""


# --------------------------------------------------------------------------- #
# 그림 QA — "명백히 망한 그림"만 잡는 검수 (2026-08)
# --------------------------------------------------------------------------- #
# 위 작화 사고 검수(INSPECT_ASK)의 확장이다. 작화 사고에 더해, **그리려던 것**
# (콘티 서술)과 명백히 어긋난 것까지 본다 — 인원수가 다르다, 서술의 핵심
# 대상이 아예 없다, 밤이어야 하는데 낮이다.
#
# ★ 설계 원칙 — 검수는 "좋은 그림" 판정기가 아니라 QA 다.
#   AI 는 "틀렸다"는 찾아도 "사용자가 원하는 방향"은 모른다. 그래서 여기서는
#   객관적으로 확인 가능한 것만 잡고(인원·대상·배경), 미적 판단(구도·표정·
#   화풍·디테일)은 전부 사용자에게 넘긴다 — 그쪽은 랜덤 재생성이 아니라
#   사용자 피드백(다시 그리기)이 고치는 영역이다.
# ★ inspect_art 는 그대로 둔다 — --check-art 의 예전 동작(작화 사고만,
#   제보만)은 한 글자도 안 바뀐다. 이 함수는 art_qa 설정을 켠 실행만 쓴다.
INSPECT_QA_ASK = """이 웹툰 컷 그림을 검수하고 JSON 으로만 답하세요.

[이 컷이 그리려던 것]
{brief}

찾는 것 1 — 그림 자체의 사고 (kind: "artifact"):
- 손·발이 잘못 붙었거나 개수가 틀림 (손가락 6개, 발이 머리 자리에 붙음 등)
- 몸의 일부가 사라졌거나 두 번 그려짐, 팔다리가 몸과 안 이어짐
- 동물·사물의 구조가 말이 안 됨 (머리와 다리가 뒤바뀜 등)
- 있어야 할 곳이 아닌 데서 자라거나 솟은 것 (몸 위의 새싹, 벽을 뚫은 가구)
- 물건이 공중에 떠 있거나 손을 통과함
- 얼굴이 녹거나 눈이 짝짝이로 뭉개짐
- 글자가 글자처럼 보이지만 읽을 수 없음

찾는 것 2 — 그리려던 것과 명백히 다름 (kind: "contract"):
- 인물 수가 명백히 다름 (두 사람이 마주보는 장면인데 한 명뿐)
- 서술의 핵심 대상·소품이 아예 없음 (덫에 걸린 생쥐를 구하는 장면인데 생쥐가 없음)
- 배경·시간대가 명백히 다름 (밤 장면인데 대낮, 실내인데 벌판)

찾지 않는 것 — 이것들은 여기서 잡지 않습니다:
- 그림체·화풍·색감이 취향에 안 맞는 것
- 구도·표정·연출이 서술의 해석과 조금 다른 것 (사용자가 보고 정할 영역)
- 만화적 과장 (큰 눈, 과장된 표정, 데포르메)
- 소품의 생김새가 상상과 다른 것 (덫이 있긴 한데 모양이 다름 — 있으면 통과)

{{"issues": [{{"box": [y,x,y,x], "what": "무엇이 어떻게 잘못됐는지 한 줄",
              "severity": "high 또는 low", "kind": "artifact 또는 contract"}}]}}

box       : **0~1000 정규화**한 [ymin, xmin, ymax, xmax].
severity  : high = 독자가 바로 알아본다. low = 뜯어봐야 보인다.
            contract 는 명백할 때만 넣는 것이므로 항상 high 입니다.
확신이 없으면 넣지 마세요 — 없는 것을 있다고 하는 편이 더 나쁩니다.
다른 말 없이 JSON 만 출력하세요."""


def inspect_scene(img, brief: str, api_key: str, model: str,
                  timeout: float = 180.0) -> list[dict[str, Any]]:
    """이 컷에 명백한 사고(작화·조건 불일치)가 있는지 묻는다.

    [{box, what, severity, kind}] 로 돌려준다. kind 는 artifact(그림 자체의
    사고) 또는 contract(그리려던 것과 다름). 실패하면 VisionError — 부르는
    쪽이 잡아서 경고만 찍고 넘어간다(검수가 안 됐다고 그림을 버리지 않는다).
    """
    prompt = INSPECT_QA_ASK.format(brief=(brief or "(서술 없음)").strip()[:1200])
    raw = _ask_json(img, prompt, api_key, model, timeout, label="그림 QA")
    w, h = img.size
    out = []
    for it in raw.get("issues") or []:
        if not isinstance(it, dict):
            continue
        what = str(it.get("what") or "").strip()
        if not what:
            continue
        sev = str(it.get("severity") or "low").strip().lower()
        kind = str(it.get("kind") or "artifact").strip().lower()
        kind = "contract" if kind == "contract" else "artifact"
        out.append({
            "box": _to_px(it.get("box"), w, h),
            "what": what,
            # 조건 불일치는 정의상 "명백할 때만" 넣으라고 했으므로 high 로 민다.
            "severity": "high" if (sev == "high" or kind == "contract") else "low",
            "kind": kind,
        })
    return out


def _ask_json(img, prompt: str, api_key: str, model: str,
              timeout: float, label: str) -> dict[str, Any]:
    """그림 한 장 + 질문 → JSON 응답. inspect_art/locate 와 같은 길."""
    import requests

    body = {
        "contents": [{"role": "user", "parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/png", "data": _b64(img)}}]}],
        "generationConfig": {"temperature": 0.1},
    }
    try:
        resp = requests.post(
            ENDPOINT.format(model=model),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body, timeout=timeout)
    except Exception as exc:
        raise VisionError(f"{label} 요청 실패: {exc}") from exc
    if resp.status_code != 200:
        raise VisionError(f"{label} 요청 실패 ({resp.status_code}): {resp.text[:200]}")
    text = ""
    for cand in resp.json().get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            text += part.get("text") or ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise VisionError(f"{label} JSON 을 찾지 못했습니다: {text[:200]}")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise VisionError(f"{label} JSON 을 읽지 못했습니다: {exc}") from exc


def inspect_art(img, api_key: str, model: str,
                timeout: float = 180.0) -> list[dict[str, Any]]:
    """이 컷에 작화 사고가 있는지 묻는다. [{box, what, severity}] 로 돌려준다.

    locate() 와 같은 길을 쓴다 — 같은 엔드포인트, 같은 축소, 같은 좌표 규약.
    실패하면 VisionError 를 던진다. 부르는 쪽(run.py)이 잡아서 경고만 찍고
    넘어간다 — 검수가 안 됐다고 그림 생성을 멈출 이유는 없다.
    """
    import requests

    w, h = img.size
    body = {
        "contents": [{"role": "user", "parts": [
            {"text": INSPECT_ASK},
            {"inline_data": {"mime_type": "image/png", "data": _b64(img)}}]}],
        "generationConfig": {"temperature": 0.1},
    }
    try:
        resp = requests.post(
            ENDPOINT.format(model=model),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body, timeout=timeout)
    except Exception as exc:
        raise VisionError(f"작화 검수 요청 실패: {exc}") from exc
    if resp.status_code != 200:
        raise VisionError(f"작화 검수 요청 실패 ({resp.status_code}): {resp.text[:200]}")

    text = ""
    for cand in resp.json().get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            text += part.get("text") or ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise VisionError(f"검수 JSON 을 찾지 못했습니다: {text[:200]}")
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise VisionError(f"검수 JSON 을 읽지 못했습니다: {exc}") from exc

    out = []
    for it in raw.get("issues") or []:
        if not isinstance(it, dict):
            continue
        what = str(it.get("what") or "").strip()
        if not what:
            continue
        sev = str(it.get("severity") or "low").strip().lower()
        out.append({
            "box": _to_px(it.get("box"), w, h),
            "what": what,
            "severity": "high" if sev == "high" else "low",
        })
    return out


def _b64(img, fmt="PNG") -> str:
    small = img.copy()
    small.thumbnail((PROBE_MAX, PROBE_MAX))
    buf = io.BytesIO()
    small.convert("RGB").save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _to_px(box: Any, w: int, h: int) -> tuple[int, int, int, int] | None:
    """[ymin,xmin,ymax,xmax] (0~1000) → (x0,y0,x1,y1) 픽셀."""
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return None
    try:
        y0, x0, y1, x1 = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    px = (int(x0 * w / 1000), int(y0 * h / 1000),
          int(x1 * w / 1000), int(y1 * h / 1000))
    if px[2] <= px[0] or px[3] <= px[1]:
        return None
    return px


def cache_path(ep_dir: Path) -> Path:
    return ep_dir / CACHE_FILE


def load_cache(ep_dir: Path) -> dict[str, Any]:
    p = cache_path(ep_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(ep_dir: Path, data: dict[str, Any]) -> None:
    cache_path(ep_dir).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def locate(img, cut: dict[str, Any], cast_lines: list[str],
           api_key: str, model: str, timeout: float = 180.0) -> dict[str, Any]:
    """이 컷에서 사람과 빈 자리를 찾는다. 픽셀 좌표로 돌려준다.

    돌려주는 것:
      {"speaker_head": (x0,y0,x1,y1) 또는 None,
       "people": [{"who", "head": (x0,y0,x1,y1)}],
       "empty":  [{"box": (x0,y0,x1,y1), "note"}]}
    """
    import requests

    w, h = img.size
    speaker = str(cut.get("speaker") or "").strip()
    prompt = ASK.format(
        cast="\n".join(cast_lines) or "(알려진 인물 없음)",
        speaker=speaker or "(이 컷에는 말하는 사람이 없습니다)")
    body = {
        "contents": [{"role": "user", "parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/png", "data": _b64(img)}}]}],
        "generationConfig": {"temperature": 0.1},
    }
    try:
        resp = requests.post(
            ENDPOINT.format(model=model),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body, timeout=timeout)
    except Exception as exc:                       # 네트워크
        raise VisionError(f"좌표 요청 실패: {exc}") from exc
    if resp.status_code != 200:
        raise VisionError(f"좌표 요청 실패 ({resp.status_code}): {resp.text[:200]}")

    text = ""
    for cand in resp.json().get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            text += part.get("text") or ""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise VisionError(f"좌표 JSON 을 찾지 못했습니다: {text[:200]}")
    try:
        raw = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise VisionError(f"좌표 JSON 을 읽지 못했습니다: {exc}") from exc

    head = _to_px(raw.get("speaker_head"), w, h) if raw.get("speaker_found") else None
    people = []
    for p in raw.get("people") or []:
        if not isinstance(p, dict):
            continue
        box = _to_px(p.get("head"), w, h)
        if box:
            people.append({"who": str(p.get("who") or "").strip(), "head": box})
    empty = []
    for e in raw.get("empty") or []:
        if not isinstance(e, dict):
            continue
        box = _to_px(e.get("box"), w, h)
        if box:
            empty.append({"box": box, "note": str(e.get("note") or "").strip()})
    return {"speaker_head": head, "people": people, "empty": empty}


def cast_lines(book, sheet, second) -> list[str]:
    """모델에게 "누가 누구인지" 를 알려 줄 줄들. 외형으로 구별하게 한다.

    이름만 주면 모델이 그림 속 누가 그 이름인지 알 수 없다. 명부의 외형·옷차림을
    같이 줘야 "하늘색 후드티 쪽이 하윤재" 라고 짚을 수 있다.
    """
    out = []
    if sheet is not None and getattr(sheet, "name", ""):
        who = sheet.name
        desc = (getattr(sheet, "appearance", "") or "")[:180]
        out.append(f"- {who} (주인공): {desc}")
    if second is not None and getattr(second, "name", ""):
        desc = (getattr(second, "appearance", "") or "")[:180]
        out.append(f"- {second.name}: {desc}")
    for p in getattr(book, "people", []) or []:
        name = getattr(p, "name", "")
        if not name or any(name in line for line in out):
            continue
        bits = " / ".join(x for x in (getattr(p, "appearance", ""),
                                      getattr(p, "outfit", "")) if x)
        out.append(f"- {name}: {bits[:180]}")
    return out


# --------------------------------------------------------------------------- #
# 배치 — 찾은 좌표로 말풍선 자리를 정하고, **사람이 고칠 수 있게** 파일로 남긴다
#
# layout_bubbles.json 이 이 단계의 결과물이다. 좌표도 글자도 여기 있고, 고친 뒤
# 다시 조립하면 API 호출 0회로 반영된다. 자동 배치는 초안일 뿐이고, 사람이
# 고친 것이 언제나 이긴다 (picks.csv · bubbles.json 과 같은 길).
# --------------------------------------------------------------------------- #
BUBBLE_FIELDS = ("narration", "dialogue", "thought")

# 풍선이 차지할 최소/최대 크기 (컷 폭 대비)
MIN_BW, MAX_BW = 0.28, 0.72


def _overlaps(a, b, margin=0) -> bool:
    return not (a[2] + margin < b[0] or b[2] + margin < a[0] or
                a[3] + margin < b[1] or b[3] + margin < a[1])


def place(cut: dict[str, Any], found: dict[str, Any], size: tuple[int, int]
          ) -> list[dict[str, Any]]:
    """찾은 좌표 → 말풍선 배치 초안. [{field, kind, text, box, tail}]

    빈 자리 중에서 **화자와 가까운 것**을 고른다 — 꼬리가 길게 화면을 가로지르면
    누구 말인지 오히려 흐려진다. 이미 놓은 풍선, 그리고 모든 인물의 얼굴을
    피한다.
    """
    w, h = size
    items = [(f, str(cut.get(f) or "").strip())
             for f in BUBBLE_FIELDS if str(cut.get(f) or "").strip()]
    if not items:
        return []

    head = found.get("speaker_head")
    heads = [p["head"] for p in found.get("people") or []]
    spots = list(found.get("empty") or [])
    used: list[tuple[int, int, int, int]] = []
    out = []

    for field, text in items:
        kind = ("narration" if field == "narration" else
                "thought" if field == "thought" else
                "shout" if "!" in text else "dialogue")

        # 글자 길이로 풍선 크기를 잡는다 (대략. 실제 맞춤은 그릴 때).
        n = max(1, len(text))
        bw = int(min(MAX_BW, max(MIN_BW, 0.055 * (n ** 0.62))) * w)
        bh = int(bw * (0.34 if kind == "narration" else 0.46))

        cand = None
        # 나레이션은 화자와 무관하다 — 위쪽을 선호한다.
        anchor = ((head[0] + head[2]) // 2, (head[1] + head[3]) // 2) if head else None
        ranked = []
        for sp in spots:
            b = sp["box"]
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            area = (b[2] - b[0]) * (b[3] - b[1])
            if area < bw * bh * 0.45:
                continue
            if kind == "narration":
                score = cy                     # 위일수록 좋다
            elif anchor:
                score = ((cx - anchor[0]) ** 2 + (cy - anchor[1]) ** 2) ** 0.5
            else:
                score = cy
            ranked.append((score, b, cx, cy))
        ranked.sort(key=lambda r: r[0])

        for _s, b, cx, cy in ranked:
            box = (int(cx - bw / 2), int(cy - bh / 2),
                   int(cx + bw / 2), int(cy + bh / 2))
            box = (max(4, box[0]), max(4, box[1]),
                   min(w - 4, box[2]), min(h - 4, box[3]))
            if any(_overlaps(box, u, int(w * 0.01)) for u in used):
                continue
            if any(_overlaps(box, hd) for hd in heads):
                continue                        # 얼굴을 가리면 안 된다
            cand = box
            break

        if cand is None:
            # 빈 자리를 못 찾았다. 맨 위에 얹되 얼굴은 피해 본다.
            y = int(h * 0.04) + len(used) * (bh + int(h * 0.01))
            cand = (int(w * 0.06), y, int(w * 0.06) + bw, y + bh)
        used.append(cand)

        tail = None
        if kind != "narration" and head:
            tail = (int((head[0] + head[2]) / 2), int((head[1] + head[3]) / 2))
        out.append({"field": field, "kind": kind, "text": text,
                    "box": list(cand), "tail": list(tail) if tail else None,
                    "auto": True})
    return out


def layout_path(ep_dir: Path) -> Path:
    return ep_dir / LAYOUT_FILE


def load_layout(ep_dir: Path) -> dict[str, Any]:
    p = layout_path(ep_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_layout(ep_dir: Path, data: dict[str, Any]) -> None:
    payload = {
        "_읽는 법": "cut<번호> 마다 말풍선 목록. box 는 [x0,y0,x1,y1] 픽셀, "
                   "tail 은 꼬리가 가리킬 [x,y] (null 이면 꼬리 없음).",
        "_고치는 법": "box·tail·text 를 고쳐 저장하고 --compose 를 다시 실행하면 "
                     "API 호출 없이 반영됩니다. auto 를 false 로 두면 다음 실행이 "
                     "덮어쓰지 않습니다.",
    }
    payload.update(data)
    layout_path(ep_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
