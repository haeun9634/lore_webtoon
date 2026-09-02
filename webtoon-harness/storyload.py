"""스토리 하네스 산출물 → 컷 목록.

주 경로: runs/<run_id>/webtoon/ep{NN}_cuts.json (W7 완주 산출물)
  실제 구조 (20260803T223106-38684d 기준):
    { "arc_order", "episode_order", "cuts": [
        {"cut_number", "description", "dialogue", "reader_only"} ...],
      "engine_cut_refs", "stinger_cut_number",
      "_absolute_episode", "_arc_order" }
  주의: episode_order 는 신뢰할 수 없다 (arc2 에 order 5, arc3 에 order 10 이 있다).
        화 번호는 _absolute_episode / 파일명만 믿는다.

예비 경로: W7 산출물이 없는 run 은 arc{n}_episodes.json 의 화 summary 를
  텍스트 LLM 으로 컷 분해한다 (run.py 가 prompts/cut_split.txt 로 호출).

연출: **컷 파일 안에 같이 들어온다** (W7 통합판).
  cuts[] 의 각 항목에 size / beat / render_style / gap_after / gaze / scene_break.
  스토리 하네스가 7.5단계를 7단계로 흡수했다 — 컷의 크기와 내용은 같이 정해져야
  하기 때문이다(impact 컷에 설명을 욱여넣으면 둘 다 죽는다).

  옛 판: runs/<run_id>/webtoon/ep{NN}_direction.json 이 있으면 그것이 이긴다.
  { "direction": [{"cut_number", "beat", "gap_after", "gaze", "scene_break"} ...] }
  7.5단계로 뽑아 둔 run 이 아직 남아 있어서 둘 다 받는다.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CUT_FILE_RE = re.compile(r"^ep(\d+)_cuts\.json$")

BEATS = ("setup", "build", "turn", "release", "hold")
GAZES = ("down", "toward-next", "at-viewer", "away")
SIZES = ("wide", "normal", "tall", "impact")
# 컷이 지면을 먹는 무게. 콘티가 계산해서 보내는 값이라 여기서는 받기만 한다.
WEIGHTS = ("full", "normal", "light")
# 한 화 안에서 그림체가 바뀐다. 진지한 컷은 정식 작화, 분위기 푸는 컷은 SD.
# bleed(통컷)·breakout(칸 밖으로)은 그림체가 아니라 **칸을 어떻게 쓰는가**지만,
# 컷 하나에 붙는 배타적 선택이라 콘티(W7)가 같은 필드에 담아 보낸다.
# 여기 목록에 없으면 _one_of 가 조용히 "normal" 로 깎는다 — 실제로 그랬다.
RENDER_STYLES = ("normal", "sd", "emphasis", "bleed", "breakout", "float")
# 구도와 말풍선 자리. story-harness 의 COMPOSITIONS / BUBBLE_ZONES 와 같은 목록이다 —
# 한쪽이 값을 늘리면 여기도 같이 늘려야 한다 (RENDER_STYLES 와 같은 주의).
COMPOSITIONS = ("none", "over-the-shoulder", "two-shot", "silhouette",
                "reflection", "frame-in-frame")
BUBBLE_ZONES = ("top", "bottom", "left", "right", "center", "none")
# 말하는 사람이 화면 어느 쪽인가 — 말풍선 꼬리를 붙일 곳.
SPEAKER_SIDES = ("left", "right", "center", "offscreen")
# 카메라 세 축. 콘티가 낱말로 정해서 보내면 여기서 영어 샷 용어로 옮긴다.
SHOTS = ("원경", "전신", "중간", "바스트", "클로즈업", "익스트림", "인서트")
ANGLES = ("수평", "부감", "앙각", "수직", "기울임")


SPEECH_KINDS = ("narration", "dialogue", "thought")


def _speech_rows(raw) -> list:
    """cuts[].lines 를 정리해 읽는다. 모르는 줄은 조용히 버린다."""
    out = []
    for row in (raw or []):
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        kind = str(row.get("kind") or "dialogue").strip().lower()
        if not text or kind not in SPEECH_KINDS:
            continue
        out.append({"kind": kind, "text": text,
                    "speaker": str(row.get("speaker") or "").strip(),
                    "side": _one_of(row.get("side"), SPEAKER_SIDES, "")})
    return out


def speech_lines(cut) -> list:
    """이 컷의 말 목록. 새 형식(lines)이 있으면 그것, 없으면 옛 세 칸에서 만든다.

    story-harness 의 같은 이름 함수와 **같은 규칙**이다. 두 하네스가 다르게 읽으면
    콘티에 적힌 말과 그림에 그려지는 말이 어긋난다.
    """
    rows = list(getattr(cut, "lines", None) or [])
    if rows:
        return rows
    speaker = str(getattr(cut, "speaker", "") or "").strip()
    side = str(getattr(cut, "speaker_side", "") or "").strip().lower()
    out = []
    for kind in SPEECH_KINDS:
        text = str(getattr(cut, kind, "") or "").strip()
        if not text:
            continue
        out.append({"kind": kind, "text": text,
                    "speaker": "" if kind == "narration" else speaker,
                    "side": "" if kind == "narration" else side})
    return out


@dataclass
class Cut:
    cut_number: int
    description: str
    dialogue: str = ""
    reader_only: bool = False
    # ---- 텍스트. 말풍선만으로 굴러가지 않는다.
    narration: str = ""       # 나레이션 상자
    thought: str = ""         # 속마음 (구름 풍선)
    sfx: str = ""             # 효과음. 그림 위 레터링
    # 한 컷에 말이 여러 줄 들어갈 수 있다 — 두 사람이 주고받는 칸.
    # [{"kind": narration|dialogue|thought, "text", "speaker", "side"} ...]
    # 옛 run 은 이 칸이 비어 있고, speech_lines() 가 위의 세 칸에서 만들어 준다.
    lines: list = field(default_factory=list)
    # ---- 연출. 컷 파일에 같이 실려 온다. 없으면 기본값.
    beat: str = ""            # setup | build | turn | release | hold
    gap_after: int = 1        # 0=붙임 1=보통 2=길게 3=낙차용
    gaze: str = ""            # down | toward-next | at-viewer | away
    scene_break: bool = False
    # 이 컷은 **앞 컷과 같은 배경이 위에서 아래로 이어지는가.** 콘티(W7.5)가
    # 여백 0 · 같은 zone 자리에서 계산해 보낸다. 무대는 그대로 두고 카메라만
    # 아래로 내리는 자리라, 켜 두면 두 컷이 한 공간의 위/아래로 읽힌다.
    # 옛 run 에는 이 칸이 없다 — 없으면 False 라 예전과 똑같이 굴러간다.
    vertical_link: bool = False
    # 이 컷이 지면을 얼마나 먹는가 — full | normal | light. 콘티(W7.5)가
    # render_style 과 size 에서 계산해 보낸다. light 는 배경이 없는 컷이라
    # 여럿이 한 캔버스를 나눠 써도 격자가 안 생긴다.
    # 옛 run 에는 이 칸이 없다 — 없으면 "normal" 이라 예전과 똑같이 굴러간다.
    weight: str = "normal"
    size: str = ""            # wide | normal | tall | impact
    render_style: str = "normal"   # normal | sd | emphasis | bleed | breakout
    # ---- 카메라. 예전에는 콘티가 서술 첫머리에 낱말로 적어 보냈는데, 그 자리에
    # size 값을 적는 컷이 절반을 넘어서 필드로 분리됐다. 여기서 영어로 옮긴다.
    shot: str = ""            # 원경 | 전신 | 중간 | 바스트 | 클로즈업 | 익스트림 | 인서트
    angle: str = ""           # 수평 | 부감 | 앙각 | 수직 | 기울임
    speaker: str = ""         # 이 컷에서 말하는 사람 — 말풍선 꼬리를 누구에게 붙일지
    # 존 — 배경 자산을 재사용할 구역 id (story-harness series.json.zones 의 키).
    # 비어 있으면(예전 run) 배경 자산 첨부를 건너뛴다 — 텍스트 서술만으로 굴러가던
    # 예전 방식 그대로다.
    zone: str = ""
    # ---- 화면에 누가 있고 어떻게 보이는가. 예전에는 전부 산문에서 짐작했다.
    # 인물 이름을 산문에서 찾던 cast.py 의 예비 경로를 이 필드가 대신한다 —
    # 이름이 불리기만 하는 컷과 그 사람이 실제로 있는 컷이 구분된다.
    characters_in_frame: list = field(default_factory=list)
    # 의도("몰래 촬영한다")는 그려지지 않는다. 구도를 지정해야 그려진다.
    composition: str = "none"
    composition_note: str = ""
    # 휴대폰·모니터 화면 안에 글자로 보이는 것. 말풍선이 아니라 UI 로 그려진다.
    screen_text: str = ""
    # 말풍선이 놓일 자리 — 그림을 그릴 때 여기를 비워 둔다.
    bubble_zone: str = "none"
    # 말하는 사람이 화면 어느 쪽에 있는가. 비어 있으면(옛 run) 꼬리를
    # 그리지 않는다 — 짐작해서 그리면 엉뚱한 사람을 가리킨다.
    speaker_side: str = ""

    @property
    def directed(self) -> bool:
        return bool(self.beat)


@dataclass
class Episode:
    run_id: str
    episode: int              # 절대 화 번호 (1부터)
    arc_order: int | None
    title: str
    cuts: list[Cut]
    source: str               # "w7" | "cut_split"
    summary: str = ""         # cut_split 용 원본 summary (w7 이면 참고용)
    has_direction: bool = False   # ep{NN}_direction.json 을 읽었는지
    # 무대 — 장소·시간대·날씨·광원. 스토리 단계(5단계)가 이미 정한 값이다.
    # 안 넘기면 그림 쪽 LLM 이 패널마다 새로 정해서, 같은 화 안에서 낮이었다
    # 밤이 되고 비가 왔다 갠다. **무엇을 그릴지 정하는 것은 콘티의 일**이고
    # 그림의 일은 그리는 것이다.
    setting: dict = field(default_factory=dict)
    # 장면 — 콘티가 컷보다 먼저 정한 것. what(무슨 장면인가) · mood(어떤 공기인가) ·
    # last_cut(어디까지). **mood 가 이 파이프라인에서 가장 중요한 한 줄이다** —
    # 컷 서술은 "무엇이 보이는가" 만 말하고, "어떤 공기로 그릴 것인가" 는 여기에만
    # 있다. 안 넘기면 그림 쪽은 컷마다 톤을 새로 정한다.
    scenes: list = field(default_factory=list)
    # 화면 묶음 — 9단계(페이지 편집)가 정한 것. [{"cuts":[1,2,3],"base":3,"why":…}]
    # 비어 있으면(9단계가 없거나 실패한 옛 run) 하네스가 자기 규칙으로 묶는다.
    pages: list = field(default_factory=list)


class LoadError(RuntimeError):
    """run/화 를 읽을 수 없음. run.py 가 사람이 읽을 메시지로 바꿔 출력한다."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise LoadError(f"JSON 을 읽을 수 없습니다: {path} ({exc})") from exc


def run_dir(runs_root: Path, run_id: str) -> Path:
    d = runs_root / run_id
    if not d.is_dir():
        available = sorted(p.name for p in runs_root.iterdir() if p.is_dir()) if runs_root.is_dir() else []
        hint = ("\n  사용 가능한 run: " + ", ".join(available[-10:])) if available else ""
        raise LoadError(f"run 폴더가 없습니다: {d}{hint}")
    return d


def cut_files(webtoon_dir: Path) -> dict[int, Path]:
    """{절대 화 번호: 컷 파일} — 파일명 번호 기준."""
    out: dict[int, Path] = {}
    if not webtoon_dir.is_dir():
        return out
    for p in sorted(webtoon_dir.glob("ep*_cuts.json")):
        m = CUT_FILE_RE.match(p.name)
        if m:
            out[int(m.group(1))] = p
    return out


def _arc_episode_entry(webtoon_dir: Path, arc_order: int, ep_file: Path,
                       files: dict[int, Path]) -> dict[str, Any] | None:
    """arc{n}_episodes.json 에서 이 화에 해당하는 항목을 찾는다 (제목/summary 용).

    episode_order 가 범위를 벗어나면(실제 데이터에 그런 화가 있다) arc 안에서의
    파일 순서로 대신 찾는다. 실패하면 None — 제목은 장식이므로 없어도 진행한다.
    """
    arc_path = webtoon_dir / f"arc{arc_order}_episodes.json"
    if not arc_path.exists():
        return None
    episodes = (_read_json(arc_path) or {}).get("episodes") or []
    if not episodes:
        return None

    order = _read_json(ep_file).get("episode_order")
    if isinstance(order, int) and 1 <= order <= len(episodes):
        return episodes[order - 1]

    same_arc = sorted(
        n for n, p in files.items()
        if (_read_json(p).get("_arc_order") or _read_json(p).get("arc_order")) == arc_order
    )
    this_ep = int(CUT_FILE_RE.match(ep_file.name).group(1))  # type: ignore[union-attr]
    if this_ep in same_arc:
        idx = same_arc.index(this_ep)
        if idx < len(episodes):
            return episodes[idx]
    return None


def load_w7_episode(runs_root: Path, run_id: str, episode: int) -> Episode:
    rd = run_dir(runs_root, run_id)
    webtoon_dir = rd / "webtoon"
    files = cut_files(webtoon_dir)
    if not files:
        raise LoadError(
            f"W7 컷 산출물이 없습니다: {webtoon_dir}\\ep*_cuts.json\n"
            f"  이 run 은 예비 경로(summary 기반 컷 분해)로만 돌릴 수 있습니다: --cut-split"
        )
    if episode not in files:
        raise LoadError(
            f"{run_id} 에 {episode}화 컷 파일이 없습니다. "
            f"있는 화: {', '.join(str(n) for n in sorted(files))}"
        )

    ep_path = files[episode]
    data = _read_json(ep_path)
    raw_cuts = data.get("cuts") or []
    if not raw_cuts:
        raise LoadError(f"{ep_path.name} 에 cuts 가 비어 있습니다.")

    cuts = [_cut_from(c, i) for i, c in enumerate(raw_cuts, 1)]
    empty = [c.cut_number for c in cuts if not c.description]
    if empty:
        raise LoadError(f"{ep_path.name} 의 컷 {empty} 에 description 이 없습니다.")

    # 컷에 이미 연출이 실려 있으면 그것으로 충분하다. 옛 판의 direction 파일이
    # 남아 있으면 그쪽이 이긴다 (그 run 은 7.5단계로 뽑은 것이다).
    has_direction = any(c.beat for c in cuts)
    has_direction = apply_direction(webtoon_dir, episode, cuts) or has_direction

    arc_order = data.get("_arc_order") or data.get("arc_order")
    entry = _arc_episode_entry(webtoon_dir, arc_order, ep_path, files) if arc_order else None
    return Episode(
        run_id=run_id,
        episode=episode,
        arc_order=arc_order,
        title=str((entry or {}).get("title") or f"{episode}화"),
        cuts=cuts,
        source="w7",
        summary=str((entry or {}).get("summary") or ""),
        has_direction=has_direction,
        setting=(entry or {}).get("setting") or {},
        scenes=[sc for sc in (data.get("scenes") or []) if isinstance(sc, dict)],
        pages=[pg for pg in (data.get("pages") or []) if isinstance(pg, dict)],
    )


def _one_of(value: Any, allowed: tuple, fallback: str) -> str:
    v = str(value or "").strip().lower()
    return v if v in allowed else fallback


def _mirror_legacy(cut: Cut) -> Cut:
    """lines 만 있는 컷의 옛 칸을 채운다 (종류별 첫 줄).

    옛 칸만 보는 코드가 아직 많다 — 뷰어의 캡션, 컨택트 시트, 리뷰 화면. 그쪽을
    한꺼번에 고치는 대신 여기서 한 번 맞춰 준다. 반대 방향(옛 칸 -> lines)은
    speech_lines() 가 즉석에서 만든다.
    """
    if not cut.lines:
        return cut
    for kind in SPEECH_KINDS:
        if not str(getattr(cut, kind, "") or "").strip():
            first = next((r for r in cut.lines if r["kind"] == kind), None)
            setattr(cut, kind, first["text"] if first else "")
    talker = next((r for r in cut.lines if r["kind"] in ("dialogue", "thought")), None)
    if talker:
        cut.speaker = cut.speaker or talker["speaker"]
        cut.speaker_side = cut.speaker_side or talker["side"]
    return cut


def _cut_from(c: dict, i: int) -> Cut:
    """컷 한 항목 → Cut. 연출이 같이 실려 있으면 그대로 받는다.

    모르는 값은 조용히 기본값으로 떨어뜨린다. 여기서 세우면 스토리 하네스가
    필드를 하나 늘릴 때마다 컷을 못 읽게 되는데, 그림을 그리는 데 필요한 것은
    description 뿐이고 나머지는 있으면 좋은 것이다.
    """
    return _mirror_legacy(Cut(
        cut_number=int(c.get("cut_number") or i),
        description=str(c.get("description") or "").strip(),
        dialogue=str(c.get("dialogue") or "").strip(),
        narration=str(c.get("narration") or "").strip(),
        thought=str(c.get("thought") or "").strip(),
        sfx=str(c.get("sfx") or "").strip(),
        reader_only=bool(c.get("reader_only")),
        beat=_one_of(c.get("beat"), BEATS, ""),
        gap_after=(c.get("gap_after")
                   if isinstance(c.get("gap_after"), int)
                   and not isinstance(c.get("gap_after"), bool)
                   and 0 <= c.get("gap_after") <= 3 else 1),
        gaze=_one_of(c.get("gaze"), GAZES, ""),
        scene_break=bool(c.get("scene_break")),
        vertical_link=bool(c.get("vertical_link")),
        weight=_one_of(c.get("weight"), WEIGHTS, "normal"),
        size=_one_of(c.get("size"), SIZES, ""),
        render_style=_one_of(c.get("render_style"), RENDER_STYLES, "normal"),
        shot=_one_of(c.get("shot"), SHOTS, ""),
        angle=_one_of(c.get("angle"), ANGLES, ""),
        speaker=str(c.get("speaker") or "").strip(),
        lines=_speech_rows(c.get("lines")),
        zone=str(c.get("zone") or "").strip(),
        characters_in_frame=[str(x).strip() for x in (c.get("characters_in_frame") or [])
                             if str(x or "").strip()],
        composition=_one_of(c.get("composition"), COMPOSITIONS, "none"),
        composition_note=str(c.get("composition_note") or "").strip(),
        screen_text=str(c.get("screen_text") or "").strip(),
        bubble_zone=_one_of(c.get("bubble_zone"), BUBBLE_ZONES, "none"),
        speaker_side=_one_of(c.get("speaker_side"), SPEAKER_SIDES, ""),
    ))


def direction_path(webtoon_dir: Path, episode: int) -> Path:
    return webtoon_dir / f"ep{episode:02d}_direction.json"


def apply_direction(webtoon_dir: Path, episode: int, cuts: list[Cut]) -> bool:
    """ep{NN}_direction.json 을 컷에 얹는다. 없으면 False (컷은 그대로 쓴다).

    컷 번호가 맞지 않으면 LoadError 다. 연출이 다른 화의 것이면 여백이 엉뚱한 데
    붙고, 그건 조용히 넘어가면 안 되는 종류의 어긋남이다.
    """
    path = direction_path(webtoon_dir, episode)
    if not path.exists():
        return False

    items = (_read_json(path) or {}).get("direction") or []
    by_num = {}
    for d in items:
        if not isinstance(d, dict):
            continue
        try:
            by_num[int(d["cut_number"])] = d
        except (KeyError, TypeError, ValueError):
            continue

    missing = [c.cut_number for c in cuts if c.cut_number not in by_num]
    if missing:
        raise LoadError(
            f"{path.name} 에 컷 {missing} 의 연출이 없습니다.\n"
            f"  연출과 컷이 다른 판입니다. 스토리 하네스에서 다시 뽑으세요:\n"
            f"  python webtoon.py --run <run_id> --direction-only --episode {episode}")

    for c in cuts:
        d = by_num[c.cut_number]
        beat = str(d.get("beat") or "").strip().lower()
        gaze = str(d.get("gaze") or "").strip().lower()
        gap = d.get("gap_after")
        c.beat = beat if beat in BEATS else "build"
        c.gaze = gaze if gaze in GAZES else "down"
        c.gap_after = gap if isinstance(gap, int) and 0 <= gap <= 3 else 1
        c.scene_break = bool(d.get("scene_break"))

    if cuts:
        cuts[-1].scene_break = True    # 화는 마지막 컷에서 끝난다
    return True


def load_summary(runs_root: Path, run_id: str, episode: int) -> Episode:
    """예비 경로 1단계: 컷 분해에 쓸 화 summary 를 가져온다 (cuts 는 비어 있다)."""
    rd = run_dir(runs_root, run_id)
    webtoon_dir = rd / "webtoon"
    arc_paths = sorted(webtoon_dir.glob("arc*_episodes.json")) if webtoon_dir.is_dir() else []
    if not arc_paths:
        raise LoadError(
            f"화 summary 도 없습니다: {webtoon_dir}\\arc*_episodes.json\n"
            f"  이 하네스는 스토리 하네스의 W6 이상 산출물이 필요합니다."
        )

    flat: list[tuple[int, dict[str, Any]]] = []
    for ap in arc_paths:
        arc = _read_json(ap) or {}
        for ep in arc.get("episodes") or []:
            flat.append((int(arc.get("arc_order") or 0), ep))
    if not 1 <= episode <= len(flat):
        raise LoadError(f"{run_id} 의 화 범위는 1~{len(flat)} 입니다 (요청: {episode}).")

    arc_order, entry = flat[episode - 1]
    summary = str(entry.get("summary") or "").strip()
    if not summary:
        raise LoadError(f"{episode}화 summary 가 비어 있습니다.")
    return Episode(
        run_id=run_id, episode=episode, arc_order=arc_order,
        title=str(entry.get("title") or f"{episode}화"),
        cuts=[], source="cut_split", summary=summary,
        setting=entry.get("setting") or {},
    )


def available_episodes(runs_root: Path, run_id: str) -> list[int]:
    try:
        return sorted(cut_files(run_dir(runs_root, run_id) / "webtoon"))
    except LoadError:
        return []
