"""컷마다 누가 나오는가 — 주인공 시트를 붙일 컷과 붙이면 안 되는 컷을 가른다.

이 하네스는 처음에 "등장인물 1명"을 전제로 만들어졌다. 외형 문구도 턴어라운드
시트도 모든 컷에 똑같이 붙었다. 그런데 w7 컷에는 여러 인물이 나온다:

    컷 6  엘리시아(황후)가 단상 중앙으로 걸어나온다
    컷 7  황후 엘리시아의 옆모습

여기에 주인공의 appearance_en 과 턴어라운드를 붙이면 황후가 주인공 얼굴로
그려진다. 컷을 다시 뽑는 비용이 아니라, 다시 뽑아도 같은 잘못이 반복된다는
것이 문제다.

## 어떻게 가르는가

셋을 이 순서로 본다. 앞의 것이 있으면 뒤는 보지 않는다.

  1. cast.json      사람이 고친 것. 언제나 최우선이다.
  2. prompts.json   생성 때 텍스트 LLM 이 판단해 남긴 값 (있으면)
  3. 이름 대조      컷 서술에 주인공 이름이 나오는가 (예비 경로)

3번은 따옴표 안을 먼저 지우고 본다. 이름이 불리는 것과 그 사람이 화면에 있는
것은 다르기 때문이다 — 컷 7 이 정확히 그렇다. 황후가 '제라프' 라고 부르지만
화면에 있는 것은 황후다.

자동 판별을 믿으라는 것이 아니다. 첫 실행에서 cast.json 초안을 만들어 두고,
--dry-run 이 컷별 판정을 표로 찍는다. 사람이 그 표를 보고 틀린 줄만 고치면
된다 — API 호출 없이, 0원으로.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CAST_FILE = "cast.json"

# 따옴표 안은 대사이거나 인용된 이름이다. 화면에 그 사람이 있다는 뜻이 아니다.
QUOTED = re.compile(r"[‘’“”'\"]([^‘’“”'\"]*)"
                    r"[‘’“”'\"]")
CUT_KEY_RE = re.compile(r"^(?:cut)?\s*(\d+)$", re.IGNORECASE)


class CastError(RuntimeError):
    """cast.json 을 읽을 수 없음. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


def cast_path(ep_dir: Path) -> Path:
    return ep_dir / CAST_FILE


HANGUL_NAME = re.compile(r"^[가-힣]{3,4}$")

# 괄호 안의 머리말. 이름이 아니라 이름표라서 대조 키가 되면 안 된다.
NAME_LABELS = {"활동명", "헌터명", "예명", "가명", "별명", "이명", "본명", "코드명"}


def name_keys(full_name: str) -> list[str]:
    """대조에 쓸 이름 조각. "제라프 알베리온" → ["제라프 알베리온", "제라프", "알베리온"].

    성까지 다 쓰는 컷은 드물다. 서술에는 보통 이름만 나온다.

    한국 이름은 띄어쓰기가 없어서 쪼갤 자리가 없다 — "민시하" 는 한 덩어리다.
    그런데 서술에는 성을 뗀 "시하가", "시하는" 으로 나온다. 그래서 3~4자
    한글 이름은 **성을 뗀 형태**도 키로 넣는다.

    이걸 안 하면 주인공이 0컷에 나온 것으로 판정되고, 캐릭터 시트가 한 컷에도
    붙지 않는다 (실제로 13컷 전부에 안 붙었다). 못 붙이는 쪽의 손해가
    가끔 잘못 붙이는 쪽보다 훨씬 크다.

    괄호 안의 활동명("민시하 (활동명: 시하)")도 따로 키가 된다 — story-harness
    의 P1 카드가 그 형식을 쓴다.
    """
    name = str(full_name or "").strip()
    if not name:
        return []
    keys = [name]

    def add(part: str) -> None:
        part = part.strip(" ·,/()[]{}")
        # 한 글자는 넣지 않는다 — 아무 문장에나 걸린다.
        # 머리말도 넣지 않는다 — "활동명" 이 이름이 되면 안 된다.
        if len(part) >= 2 and part not in keys and part not in NAME_LABELS:
            keys.append(part)

    # 괄호 안(활동명·헌터명)을 먼저 떼어 낸다.
    for inside in re.findall(r"[（(\[]([^）)\]]+)[）)\]]", name):
        for piece in re.split(r"[:：]", inside):
            add(piece)
    outside = re.sub(r"[（(\[][^）)\]]*[）)\]]", " ", name)

    parts = [p for p in re.split(r"[\s·,/]+", outside) if p.strip()]
    for part in parts:
        add(part)
    # 성 떼기는 **띄어쓰기가 없는 한 덩어리 이름**에만 한다.
    # "제라프 알베리온" 처럼 이미 나뉜 이름은 쪼갤 자리가 있으므로 건드리지
    # 않는다 — 거기서 앞 글자를 떼면 "라프", "리온" 같은 조각이 생겨서
    # 엉뚱한 낱말에 걸린다.
    if len(parts) == 1 and HANGUL_NAME.match(parts[0]):
        one = parts[0]
        add(one[1:])                 # 성 1자 + 이름 2~3자
        if len(one) == 4:
            add(one[2:])             # 복성 2자 + 이름 2자
    return keys


def guess(description: str, keys: list[str]) -> bool:
    """이 컷 서술에 주인공이 (화면에) 있는가. 따옴표 안은 빼고 본다."""
    if not keys:
        return True          # 이름을 모르면 가를 수 없다 — 예전처럼 전부 붙인다
    text = QUOTED.sub(" ", str(description or ""))
    return any(k in text for k in keys)


def from_cuts(cuts: list[dict[str, Any]], keys: list[str]) -> dict[int, bool]:
    """이름 대조로 만든 판정 (예비 경로)."""
    return {int(c["cut_number"]): guess(c.get("description") or "", keys) for c in cuts}


def from_prompts(cuts: list[dict[str, Any]]) -> dict[int, bool]:
    """prompts.json 에 LLM 이 남긴 판정. 없으면 빈 dict."""
    out: dict[int, bool] = {}
    for c in cuts:
        v = c.get("main_present")
        if isinstance(v, bool):
            out[int(c["cut_number"])] = v
    return out


def load_file(ep_dir: Path, numbers: list[int]) -> tuple[dict[int, bool], list[str], bool]:
    """cast.json → {cut_number: 주인공이 나오는가}. (판정, 경고, 파일이 있었는가)"""
    path = cast_path(ep_dir)
    if not path.exists():
        return {}, [], False
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise CastError(f"{CAST_FILE} 을 읽을 수 없습니다: {exc}") from exc
    if not isinstance(raw, dict):
        raise CastError(f"{CAST_FILE} 의 최상위는 객체여야 합니다: "
                        f'{{"cut1": false, "cut2": true, ...}}')

    warnings: list[str] = []
    out: dict[int, bool] = {}
    for key, value in raw.items():
        if str(key).startswith("_"):        # 주석용 키
            continue
        m = CUT_KEY_RE.match(str(key).strip())
        if not m:
            warnings.append(f'{CAST_FILE}: 컷 키를 알 수 없습니다 → "{key}" '
                            f'(예: "cut3" 또는 "3")')
            continue
        n = int(m.group(1))
        if n not in numbers:
            warnings.append(f"{CAST_FILE}: 컷 {n} 은 이 화에 없습니다 "
                            f"(컷 {min(numbers)}~{max(numbers)}).")
            continue
        if isinstance(value, bool):
            out[n] = value
        elif isinstance(value, list):
            # ["제라프", "엘리시아"] 처럼 등장인물을 적어 둔 형태도 받는다.
            # 빈 목록이면 "주인공 없음" 이다.
            out[n] = bool(value)
        else:
            warnings.append(f"{CAST_FILE}: 컷 {n} 의 값은 true/false 여야 합니다 "
                            f'(지금: {json.dumps(value, ensure_ascii=False)}).')
    return out, warnings, True


def resolve(ep_dir: Path, cuts: list[dict[str, Any]],
            main_name: str) -> tuple[dict[int, bool], dict[int, str]]:
    """최종 판정과 각 컷을 어디서 정했는지. (present, source)

    source 는 화면에 표로 찍어 사람이 확인할 값이다. 자동 판별이 틀렸을 때
    어느 줄을 고쳐야 하는지 바로 보이게 하려는 것이다.
    """
    numbers = [int(c["cut_number"]) for c in cuts]
    keys = name_keys(main_name)

    fallback = from_cuts(cuts, keys)
    llm = from_prompts(cuts)
    manual, warnings, _ = load_file(ep_dir, numbers)

    del warnings                            # 경고는 warnings_for() 로 따로 찍는다
    present: dict[int, bool] = {}
    source: dict[int, str] = {}
    for n in numbers:
        if n in manual:
            present[n], source[n] = manual[n], CAST_FILE
        elif n in llm:
            present[n], source[n] = llm[n], "prompts.json"
        else:
            present[n], source[n] = fallback[n], "이름 대조"
    return present, source


def warnings_for(ep_dir: Path, cuts: list[dict[str, Any]]) -> list[str]:
    numbers = [int(c["cut_number"]) for c in cuts]
    _, warns, _ = load_file(ep_dir, numbers)
    return warns


def write_draft(ep_dir: Path, cuts: list[dict[str, Any]], present: dict[int, bool],
                main_name: str) -> tuple[Path, bool]:
    """cast.json 초안을 만든다. 이미 있으면 절대 덮지 않는다 (사람이 고친 것이다).

    빈 파일을 주고 채우라고 하면 12줄을 손으로 적어야 한다. 자동 판정을 적어 두고
    틀린 줄만 고치게 한다 — 판정 근거(컷 서술 앞머리)도 같이 적어 둔다.
    """
    path = cast_path(ep_dir)
    if path.exists():
        return path, False
    ep_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "{",
        f'  "_읽는 법": "true = 이 컷에 {main_name} 이(가) 화면에 나온다. '
        f'false = 나오지 않는다.",',
        '  "_왜": "false 인 컷에는 주인공 외형·디자인 문구·캐릭터 시트를 붙이지 '
        '않습니다. 다른 인물이 주인공 얼굴로 그려지는 것을 막습니다.",',
        '  "_고치는 법": "값만 true/false 로 바꿔 저장하면 다음 실행부터 그대로 '
        '쓰입니다. API 호출은 없습니다.",',
    ]
    # JSON 에 주석을 달 수 없으므로 컷 서술은 옆에 못 적는다. 어느 컷인지는
    # --dry-run 이 찍는 표에서 보고 여기서는 값만 고친다.
    items = [f'  "cut{n}": {"true" if present[n] else "false"}' for n in sorted(present)]
    lines.append(",\n".join(items))
    lines.append("}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, True


def table(cuts: list[dict[str, Any]], present: dict[int, bool],
          source: dict[int, str], main_name: str) -> str:
    """컷별 판정을 사람이 훑어볼 표로. --dry-run 이 이걸 찍는다."""
    rows = [f"      컷  주인공({main_name})  판정 근거  서술",
            "      " + "-" * 68]
    for c in cuts:
        n = int(c["cut_number"])
        mark = "O" if present.get(n) else "."
        desc = str(c.get("description") or "").strip().replace("\n", " ")
        rows.append(f"      {n:>2}  {mark:^12}  {source.get(n, ''):<9}  {desc[:38]}")
    off = [n for n in sorted(present) if not present[n]]
    rows.append("      " + "-" * 68)
    rows.append(f"      주인공 없는 컷 {len(off)}개"
                + (f": {', '.join(str(n) for n in off)}" if off else "")
                + " — 외형·디자인 문구·시트를 붙이지 않습니다.")
    return "\n".join(rows)
