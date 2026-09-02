"""이미지 호출의 토큰·비용을 기록한다.

**단가 숫자는 새로 만들지 않는다.** `webtoon-harness/config.yaml` 의
`pricing.rates` (2026-08-26, 각 사 공식 요금표 출처가 이미 달려 있다)를
그대로 읽어 쓴다 — 컷 쪽과 다른 값이 나오면 안 되기 때문이다.

단가표에 없는 모델은 `story.charsheet_unit_cost` 의 장당 고정 어림값으로
떨어진다. 어느 쪽으로 계산했는지는 `cost_basis`("tokens" / "flat")에 남는다 —
`STYLE_FINDINGS.md` 를 쓸 때는 `cost_basis == "tokens"` 인 것만 써야
어림값이 실측처럼 섞이지 않는다 (`CLAUDE.md` 참고).
"""

from __future__ import annotations

from pathlib import Path

import yaml

from llm import story

HERE = Path(__file__).resolve().parent
WEBTOON_CONFIG = HERE.parent / "webtoon-harness" / "config.yaml"

TOKEN_KEYS = ("tokens_in", "tokens_out", "tokens_thought", "tokens_cached",
              "tokens_total", "tokens_in_text", "tokens_in_image",
              "tokens_out_image")

_pricing_cache: dict | None = None


def _pricing() -> dict:
    """webtoon-harness/config.yaml 의 pricing 절. 못 읽으면 빈 표(0원 표시 방지 X —
    그냥 flat 어림값으로 떨어진다)."""
    global _pricing_cache
    if _pricing_cache is None:
        try:
            data = yaml.safe_load(WEBTOON_CONFIG.read_text(encoding="utf-8")) or {}
        except Exception:
            data = {}
        _pricing_cache = data.get("pricing") or {}
    return _pricing_cache


def usd_to_krw() -> float:
    return float(_pricing().get("usd_to_krw") or 0.0)


def rate_for(model: str) -> dict:
    """`pricing.rates` 에서 이 모델의 100만 토큰당 단가. 없으면 빈 표.

    이름은 앞부분만 맞으면 된다(-preview, 날짜 꼬리표 무시) — webtoon-harness
    run.py 의 rate_for 와 같은 규칙이다.
    """
    table = _pricing().get("rates") or {}
    if not isinstance(table, dict) or not model:
        return {}
    best, best_len = {}, -1
    for key, row in table.items():
        name = str(key).strip()
        if (isinstance(row, dict) and name and model.startswith(name)
                and len(name) > best_len):
            best = {k: float(v) for k, v in row.items()
                    if isinstance(v, (int, float))}
            best_len = len(name)
    return best


def _num(d: dict | None, key: str) -> int | None:
    v = (d or {}).get(key)
    return int(v) if isinstance(v, (int, float)) else None


def _modality_tokens(details, modality: str) -> int | None:
    for row in details or []:
        if isinstance(row, dict) and row.get("modality") == modality:
            return _num(row, "tokenCount")
    return None


def token_fields(usage) -> dict:
    """API 가 돌려준 usage(dict) -> 표준 토큰 칸. openai 이미지 API 는
    snake_case(input_tokens), Gemini 는 PascalCase(promptTokenCount)라 있는
    키로 가른다 — 두 스키마가 이름을 공유하지 않는다.
    """
    if not isinstance(usage, dict):
        return {k: None for k in TOKEN_KEYS}

    if "input_tokens" in usage or "output_tokens" in usage:
        details = usage.get("input_tokens_details") or {}
        return {
            "tokens_in": _num(usage, "input_tokens"),
            "tokens_out": _num(usage, "output_tokens"),
            "tokens_thought": None,
            "tokens_cached": _num(details, "cached_tokens"),
            "tokens_total": _num(usage, "total_tokens"),
            "tokens_in_text": _num(details, "text_tokens"),
            "tokens_in_image": _num(details, "image_tokens"),
            "tokens_out_image": _num(usage, "output_tokens"),
        }

    if "promptTokenCount" in usage or "totalTokenCount" in usage:
        prompt_d = usage.get("promptTokensDetails")
        cand_d = usage.get("candidatesTokensDetails")
        return {
            "tokens_in": _num(usage, "promptTokenCount"),
            "tokens_out": _num(usage, "candidatesTokenCount"),
            "tokens_thought": _num(usage, "thoughtsTokenCount"),
            "tokens_cached": _num(usage, "cachedContentTokenCount"),
            "tokens_total": _num(usage, "totalTokenCount"),
            "tokens_in_text": _modality_tokens(prompt_d, "TEXT"),
            "tokens_in_image": _modality_tokens(prompt_d, "IMAGE"),
            "tokens_out_image": _modality_tokens(cand_d, "IMAGE"),
        }

    return {k: None for k in TOKEN_KEYS}


def call_cost(provider: str, model: str, quality: str,
              tokens: dict) -> tuple[float | None, str]:
    """(USD, 근거). 단가표 + 실제 토큰이 있으면 토큰으로, 없으면 장당
    고정 어림값(story.charsheet_unit_cost)으로 — 예전부터 쓰던 값이라
    비교가 끊기지 않는다.
    """
    rate = rate_for(model)
    if rate and tokens.get("tokens_total") is not None:
        in_img = tokens.get("tokens_in_image") or 0
        in_total = tokens.get("tokens_in") or 0
        in_text = max(in_total - in_img, 0) if "input_image" in rate else in_total
        out_img = tokens.get("tokens_out_image") or 0
        out_total = tokens.get("tokens_out") or 0
        out_text = max(out_total - out_img, 0) if "output_image" in rate else out_total
        usd = (
            in_text * rate.get("input", 0.0)
            + (in_img * rate["input_image"] if "input_image" in rate else 0.0)
            + out_text * rate.get("output", 0.0)
            + (out_img * rate["output_image"] if "output_image" in rate else 0.0)
        ) / 1_000_000
        return usd, "tokens"

    unit, _reason = story.charsheet_unit_cost(provider, quality)
    return (unit or None), "flat"


def cost_fields(provider: str, model: str, quality: str, usage) -> dict:
    """호출 하나의 토큰 + 비용 전부. `meta["cost"]` 로 그대로 들어간다."""
    tokens = token_fields(usage)
    usd, basis = call_cost(provider, model, quality, tokens)
    krw = usd_to_krw()
    out = dict(tokens)
    out["cost_basis"] = basis
    out["total"] = round(usd, 6) if usd is not None else None
    out["total_krw"] = round(usd * krw) if (usd is not None and krw) else None
    return out
