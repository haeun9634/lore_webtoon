"""편집실에서 얹은 것 — 저장·굽기·판본. API 없음, 그림만 만든다.

두 하네스의 테스트와 같은 방식이다 (pytest 아님, 마지막 줄에 ALL PASS).

    cd landing && python test_overlay.py
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import overlay as OV
import pipeline as P

fails = []


def _raises(fn):
    try:
        fn()
    except P.Failed:
        return True
    return False


def ok(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


def img(w=400, h=500, color=(180, 180, 200)):
    from PIL import Image
    return Image.new("RGB", (w, h), color)


BUBBLE = {"type": "bubble", "variant": "normal", "text": "여기 앉아도 돼?",
          "x": 10, "y": 20, "w": 40, "size": 15, "rot": 0, "tail": "left"}

# ---------------- 브라우저에서 온 값 깎기 ----------------
#
# 여기 들어오는 것은 전부 브라우저가 보낸 값이라 무엇이든 올 수 있다. 항목
# 하나가 이상하다고 화 전체를 못 굽게 하지 않는다 — 그 항목만 버린다.

ok("깎기: 멀쩡한 항목은 그대로 통과",
   (OV.clean_item(BUBBLE) or {}).get("text") == "여기 앉아도 돼?")
ok("깎기: 모르는 type 은 버린다",
   OV.clean_item({**BUBBLE, "type": "동영상"}) is None)
ok("깎기: 글자가 비면 버린다 (그릴 것이 없다)",
   OV.clean_item({**BUBBLE, "text": "   "}) is None)
ok("깎기: 모르는 말풍선 모양은 normal 로 떨어진다",
   OV.clean_item({**BUBBLE, "variant": "폭발"})["variant"] == "normal")
ok("깎기: 좌표가 숫자가 아니어도 터지지 않는다",
   OV.clean_item({**BUBBLE, "x": "저쪽", "y": None, "w": [1]})["x"] == 20.0)
ok("깎기: 화면 밖으로 너무 멀리 나간 값은 끌어온다",
   OV.clean_item({**BUBBLE, "x": 9999})["x"] == 110.0
   and OV.clean_item({**BUBBLE, "x": -9999})["x"] == -20.0)
ok("깎기: 아주 긴 글은 잘린다 (말풍선 하나가 화를 덮지 않게)",
   len(OV.clean_item({**BUBBLE, "text": "가" * 5000})["text"]) == 400)
ok("깎기: NaN/무한대가 와도 기본값으로 떨어진다",
   OV.clean_item({**BUBBLE, "size": float("nan")})["size"] == 15.0
   and OV.clean_item({**BUBBLE, "rot": float("inf")})["rot"] == 0.0)
ok("깎기: 꼬리는 아는 값만 받는다",
   OV.clean_item({**BUBBLE, "tail": "위"})["tail"] == "left"
   and OV.clean_item({**BUBBLE, "tail": "none"})["tail"] == "none")

payload = OV.clean_payload({"scenes": {
    "1": {"ref_w": 700, "items": [BUBBLE, {"type": "나쁨"}]},
    "0": {"items": [BUBBLE]},          # 장 번호는 1부터다
    "두번째": {"items": [BUBBLE]},      # 숫자가 아니면 버린다
    "3": {"ref_w": 700, "items": []},   # 빈 장도 남는다 (지운 것과 안 연 것은 다르다)
}})
ok("깎기: 장 번호가 이상하면 버린다", sorted(payload["scenes"]) == ["1", "3"],
   sorted(payload["scenes"]))
ok("깎기: 못 쓸 항목만 빠지고 나머지는 남는다",
   len(payload["scenes"]["1"]["items"]) == 1)
ok("깎기: 얹은 것을 다 지운 장도 남는다",
   payload["scenes"]["3"]["items"] == [])
ok("세기: 얹은 것 개수를 센다", OV.count_items(payload) == 1)

# ---------------- 저장 — 브라우저가 아니라 작품 폴더에 ----------------

tmp = Path(tempfile.mkdtemp())
ok("저장: 파일이 없으면 빈 것으로 읽는다",
   OV.load_overlay(tmp) == {"scenes": {}, "gaps": {}})
OV.save_overlay(tmp, {"scenes": {"1": {"ref_w": 700, "items": [BUBBLE]}}})
ok("저장: 저장한 것이 그대로 다시 읽힌다",
   OV.load_overlay(tmp)["scenes"]["1"]["items"][0]["text"] == BUBBLE["text"])
OV.overlay_path(tmp).write_text("{ 망가진 json", encoding="utf-8")
ok("저장: 파일이 깨져도 편집실이 열린다 (빈 것으로 본다)",
   OV.load_overlay(tmp) == {"scenes": {}, "gaps": {}})

# ---- 여백 고침 — 편집실에서 장 뒤의 쉼을 바꾼다 -----------------------------
OV.save_overlay(tmp, {"scenes": {}, "gaps": {"1": 3, "2": 0, "9": 7, "x": 1}})
_g = OV.gap_overrides(OV.load_overlay(tmp))
ok("여백: 0~3 만 남고 나머지는 버린다", _g == {1: 3, 2: 0}, _g)

OV.save_overlay(tmp, {"scenes": {}})
ok("여백: 옛 파일처럼 gaps 가 없으면 아무것도 안 덮어쓴다",
   OV.gap_overrides(OV.load_overlay(tmp)) == {})

# ---- 일반/전문 모드 ---------------------------------------------------------

ok("모드: 값이 없으면 일반 (기본이 안전한 쪽)", not P.expert_mode({}))
ok("모드: 일반은 시트에서만 멈춘다",
   P.checkpoints({}) == {"sheet": True, "story": False, "board": False, "artqa": False})
ok("모드: 전문은 네 곳 모두에서 멈춘다",
   all(P.checkpoints({"expert": True}).values()))
ok("모드: 검수 강도는 전문에서만 먹는다 (일반은 늘 기본값)",
   P.art_qa_regen_max({"art_qa_regen_max": 4}) == P.ART_QA_REGEN_DEFAULT)
ok("모드: 전문이면 고른 값이 간다",
   P.art_qa_regen_max({"expert": True, "art_qa_regen_max": 4}) == 4)
ok("모드: 이상한 값이 와도 기본값으로 (실행이 안 죽는다)",
   P.art_qa_regen_max({"expert": True, "art_qa_regen_max": "넷"}) == P.ART_QA_REGEN_DEFAULT)
ok("모드: 상한을 넘겨 보내도 상한까지만",
   P.art_qa_regen_max({"expert": True, "art_qa_regen_max": 99}) == P.ART_QA_REGEN_MAX)

# ---- 시트 재생성 지시 --------------------------------------------------------
#
# 화면의 항목을 늘리면서 지시문을 안 쓰면, 그 항목은 눌러도 아무 일이 안 일어나는
# 버튼이 된다 — 고른 사람은 반영된 줄 안다. 그 사고를 여기서 막는다.
_sheet_tag_ids = {t["id"] for t in P.FEEDBACK_TAGS["sheet"]}
ok("시트 지시: 모든 항목에 지시문이 있다",
   _sheet_tag_ids <= set(P.SHEET_FIX_BY_TAG),
   f"빠진 것: {sorted(_sheet_tag_ids - set(P.SHEET_FIX_BY_TAG))}")
ok("시트 지시: 화면에 없는 지시문이 남아 있지 않다",
   set(P.SHEET_FIX_BY_TAG) <= _sheet_tag_ids,
   f"군더더기: {sorted(set(P.SHEET_FIX_BY_TAG) - _sheet_tag_ids)}")
ok("시트 지시: 아무것도 안 고르면 빈 목록 (프롬프트가 안 바뀐다)",
   P.sheet_corrections([], "") == [])
ok("시트 지시: 모르는 항목은 버린다",
   P.sheet_corrections(["없는항목"], "") == [])
ok("시트 지시: 적은 말은 요약하지 않고 그대로 싣는다",
   "망토를 안 그렸어요" in P.sheet_corrections([], "망토를 안 그렸어요")[0])
ok("시트 지시: 너무 긴 말은 상한까지만",
   len(P.sheet_corrections([], "가" * 900)[0]) <= P.FEEDBACK_TEXT_MAX + 40)

_fix_dir = Path(tempfile.mkdtemp())
(_fix_dir / "p1.json").write_text(
    '{"name": "\\ubbfc\\uc2dc\\ud558", "design_details": ["\\uac00", "\\ub098", "\\ub2e4"]}',
    encoding="utf-8")


def _fixes_now():
    import json
    return json.loads((_fix_dir / "p1.json").read_text(encoding="utf-8")).get(
        "sheet_corrections", [])


P._merge_sheet_corrections(_fix_dir, P.sheet_corrections(["hair"], ""))
P._merge_sheet_corrections(_fix_dir, P.sheet_corrections(["outfit"], ""))
ok("시트 지시: 판을 거듭해도 앞 지시가 안 사라진다 (덮어쓰지 않고 쌓는다)",
   len(_fixes_now()) == 2 and any("머리" in c for c in _fixes_now()))
P._merge_sheet_corrections(_fix_dir, P.sheet_corrections(["hair"], ""))
ok("시트 지시: 같은 말을 또 하면 중복 없이 맨 뒤로 (끝쪽이 세게 읽힌다)",
   len(_fixes_now()) == 2 and "머리" in _fixes_now()[-1])
for _i in range(P.SHEET_FIX_MAX + 4):
    P._merge_sheet_corrections(_fix_dir, [f"지시 {_i}"])
ok("시트 지시: 상한을 넘겨 쌓이지 않는다 (서로 부딪히면 앞엣것부터 흘린다)",
   len(_fixes_now()) == P.SHEET_FIX_MAX)
ok("시트 지시: design_details 는 안 건드린다 (시트 인셋 개수가 그대로)",
   __import__("json").loads(
       (_fix_dir / "p1.json").read_text(encoding="utf-8"))["design_details"]
   == ["가", "나", "다"])
P._merge_sheet_corrections(Path(tempfile.mkdtemp()), ["아무 지시"])   # p1.json 없음
ok("시트 지시: p1.json 이 없어도 안 터진다", True)
shutil.rmtree(_fix_dir, ignore_errors=True)

# ---- 공유 링크의 미리보기 태그 ----------------------------------------------
#
# 여기 들어가는 값(제목·로그라인)은 **모델이 지어낸 글**이고 그대로 HTML 에
# 박힌다. 따옴표 하나만 새어 나가도 태그가 깨지거나 남의 화면에서 스크립트가
# 돈다. 그래서 이스케이프를 테스트로 못박는다.
import serve as S                                              # noqa: E402

_share_meta = {
    "run_id": "20260823T152601-a6316e", "episode": 1,
    "title": "약속의 무게", "character": "모모",
    "genre": "로맨스 판타지", "logline": "한 줄 소개.",
    "cover_page": 1,
}
_og = S.og_tags(_share_meta, "https://lore.test")
ok("공유: 제목이 '누구 · 무엇' 으로 나온다",
   'content="모모 · 약속의 무게 — LORE"' in _og)
ok("공유: 로그라인이 설명으로 실린다", 'content="한 줄 소개."' in _og)
ok("공유: 그림 주소가 절대 주소다 (크롤러는 상대 주소를 못 푼다)",
   'content="https://lore.test/api/runs/' in _og)
ok("공유: 링크가 그 작품·그 회차를 가리킨다",
   "/works?run=20260823T152601-a6316e&amp;ep=1" in _og)
ok("공유: <title> 도 같이 바꾼다 (탭과 카드가 따로 놀지 않게)",
   "<title>모모 · 약속의 무게 — LORE</title>" in _og)

_evil = dict(_share_meta, title="<script>alert(1)</script>",
             character='"onload="evil()', logline='a & b < c > "q"')
_og_evil = S.og_tags(_evil, "https://lore.test")
ok("공유: 꺾쇠가 태그로 살아나지 않는다", "<script>" not in _og_evil)
ok("공유: 따옴표로 속성을 빠져나가지 못한다", 'onload="evil' not in _og_evil)
ok("공유: 앰퍼샌드도 실체참조로 바뀐다", "a &amp; b" in _og_evil)

_no_log = dict(_share_meta, logline="")
ok("공유: 로그라인이 없으면 장르로 대신한다 (빈 설명은 안 내보낸다)",
   'content="로맨스 판타지 웹툰"' in S.og_tags(_no_log, "https://lore.test"))
ok("공유: 장르도 없으면 기본 문구가 있다",
   'og:description" content="캐릭터'
   in S.og_tags(dict(_no_log, genre=""), "https://lore.test"))

ok("공유: 없는 작품은 미리보기를 안 만든다 (share_meta 가 None)",
   P.share_meta("없는run", 1) is None)

# ---- 사람이 고친 제목 --------------------------------------------------------
#
# 이 값은 결과 화면뿐 아니라 목록·편집실·공유 카드·내려받는 파일 이름까지
# 따라간다(episode_title 하나를 거친다). 되돌릴 수 있어야 하는 것도 함께 못박는다.
_trun = Path(tempfile.mkdtemp())
_trun_id = _trun.name


def _fake_run(tmp_root):
    """runs/<id>/ 하나를 흉내낸다 — titles.json 만 쓰고 읽는 시험이라 이것으로 족하다."""
    P.STORY = tmp_root                      # 이 시험 동안만 바꿔 끼운다
    d = tmp_root / "runs" / "t1"
    (d / "webtoon").mkdir(parents=True, exist_ok=True)
    (d / "webtoon" / "series.json").write_text(
        '{"episodes": [{"no": 1, "title": "\\ubaa8\\ub378\\uc774 \\uc9c0\\uc740 \\uc774\\ub984"}]}',
        encoding="utf-8")
    return d


_story_backup = P.STORY
_fake_run(_trun)
ok("제목: 안 고쳤으면 모델이 지은 이름", P.episode_title("t1", 1) == "모델이 지은 이름")
ok("제목: 고치면 그것이 이긴다",
   P.set_user_title("t1", 1, "내가 지은 이름") == "내가 지은 이름"
   and P.episode_title("t1", 1) == "내가 지은 이름")
ok("제목: 앞뒤 공백과 겹친 칸은 정리한다",
   P.set_user_title("t1", 1, "  겹친   칸  ") == "겹친 칸")
ok("제목: 상한을 넘으면 자른다", len(P.set_user_title("t1", 1, "가" * 300)) == P.TITLE_MAX)
ok("제목: 비우면 모델이 지은 이름으로 되돌아간다",
   P.set_user_title("t1", 1, "") == "모델이 지은 이름"
   and P.user_title("t1", 1) == "")
ok("제목: 회차마다 따로 간다",
   (P.set_user_title("t1", 1, "1화 이름"), P.user_title("t1", 2))[1] == "")
ok("제목: 없는 작품에 쓰면 Failed", _raises(lambda: P.set_user_title("없는run", 1, "x")))
P.STORY = _story_backup
shutil.rmtree(_trun, ignore_errors=True)


# ---------------- 굽기 ----------------

def one(kind, **over):
    base = {"bubble": BUBBLE,
            "sticker": {"type": "sticker", "variant": "", "text": "💦",
                        "x": 30, "y": 40, "w": 14, "size": 16, "rot": 0, "tail": "none"},
            "sfx": {"type": "sfx", "variant": "", "text": "우당탕",
                    "x": 40, "y": 60, "w": 30, "size": 18, "rot": -7, "tail": "none"}}[kind]
    return OV.clean_item({**base, **over})


plain = img()
baked, gone = OV.render_scene(plain, {"ref_w": 400, "items": [one("bubble")]})
ok("굽기: 밑그림 크기는 안 바뀐다", baked.size == plain.size, baked.size)
ok("굽기: 그림이 실제로 달라진다 (말풍선이 얹혔다)",
   list(baked.getdata()) != list(plain.convert("RGB").getdata()))
ok("굽기: 원본은 안 건드린다",
   plain.getpixel((plain.width // 2, 30)) == (180, 180, 200))

untouched, _ = OV.render_scene(plain, {"ref_w": 400, "items": []})
ok("굽기: 얹은 것이 없으면 그림이 그대로다",
   list(untouched.getdata()) == list(plain.convert("RGB").getdata()))

for v in OV.BUBBLE_VARIANTS:
    got, _ = OV.render_scene(plain, {"ref_w": 400,
                                     "items": [one("bubble", variant=v)]})
    ok(f"굽기: 말풍선 '{v}' 가 그려진다",
       list(got.getdata()) != list(plain.convert("RGB").getdata()))

rot, _ = OV.render_scene(plain, {"ref_w": 400, "items": [one("sfx")]})
ok("굽기: 효과음이 기울어져 그려진다",
   list(rot.getdata()) != list(plain.convert("RGB").getdata()))

# 해상도가 달라도 **비율**이 같아야 한다 — ref_w 가 그 다리다.
small, _ = OV.render_scene(img(400, 500), {"ref_w": 400, "items": [one("bubble")]})
big, _ = OV.render_scene(img(800, 1000), {"ref_w": 400, "items": [one("bubble")]})


def ink_ratio(im):
    px = list(im.convert("L").getdata())
    return sum(1 for v in px if v > 240) / len(px)


ok("굽기: 해상도가 두 배여도 말풍선이 차지하는 비율은 같다",
   abs(ink_ratio(small) - ink_ratio(big)) < 0.01,
   f"{ink_ratio(small):.4f} vs {ink_ratio(big):.4f}")

# 스티커는 이모지 글꼴이 없는 서버에서 빠질 수 있다. 그때도 나머지는 구워지고,
# 무엇이 빠졌는지 말해 줘야 한다 — 조용히 사라지면 아무도 모른다.
got, skipped = OV.render_scene(plain, {"ref_w": 400,
                                       "items": [one("bubble"), one("sticker")]})
ok("굽기: 스티커가 빠져도 말풍선은 구워진다",
   list(got.getdata()) != list(plain.convert("RGB").getdata()))
ok("굽기: 못 그린 것은 조용히 사라지지 않고 목록으로 나온다",
   isinstance(skipped, list))

# ---------------- 한 편으로 잇기 ----------------

work = Path(tempfile.mkdtemp())
srcs = {}
for n in (1, 2, 3):
    p = work / f"src{n}.png"
    img(300, 400, (100 + n * 30, 150, 200)).save(p)
    srcs[n] = p
OV.save_overlay(work, {"scenes": {"1": {"ref_w": 300, "items": [BUBBLE]}}})
res = OV.bake(work, [1, 2, 3], lambda n: srcs.get(n))
ok("잇기: 세 장을 전부 굽는다 (얹은 것이 없는 장도)", res["scenes"] == [1, 2, 3], res)
ok("잇기: 장마다 파일이 남는다",
   all(OV.baked_scene_path(work, n).exists() for n in (1, 2, 3)))
ok("잇기: 한 편이 세로로 이어진다",
   res["width"] == 300 and res["height"] == 1200, (res["width"], res["height"]))
ok("잇기: 원본은 그대로 남는다 (다시 구울 수 있어야 한다)",
   all(srcs[n].stat().st_size > 0 for n in (1, 2, 3)))

res2 = OV.bake(work, [1, 2, 9], lambda n: srcs.get(n))
ok("잇기: 아직 안 그려진 장은 빠지고 그 번호를 알려 준다",
   res2["scenes"] == [1, 2] and res2["missing"] == [9], res2)

try:
    OV.bake(work, [8, 9], lambda n: None)
    ok("잇기: 구울 그림이 하나도 없으면 알려 준다", False)
except OV.OverlayError as exc:
    ok("잇기: 구울 그림이 하나도 없으면 알려 준다", "먼저 웹툰을" in str(exc), str(exc))

# ---------------- 판본이 늘어나던 것 ----------------
#
# 지난 판을 눌러 보기만 해도 판본이 계속 늘었다 — v1~v3 를 번갈아 누르면
# v4·v5·v6 이 생기고, 그 셋은 v1~v3 와 픽셀 하나까지 같은 그림이었다.
# 사용자가 본 것이 그것이다 ("갑자기 v7 v8 이런 식으로 생성").

RUN = "__overlay_test__"
ep = P.episode_dir(RUN)
shutil.rmtree(ep.parent, ignore_errors=True)
(ep / "scene_S+").mkdir(parents=True)
cur = ep / "scene_S+" / "scene1_c1.png"


def versions():
    return sorted(v["version"] for v in P.scene_versions(RUN, 1))


for c in ((220, 40, 40), (40, 190, 60), (50, 90, 230)):
    P.archive_scene(RUN, 1)
    img(64, 64, c).save(cur)
made = versions()
ok("판본: 새로 그릴 때마다 하나씩 쌓인다", made == [1, 2], made)

for v in (1, 2, 1, 2, 1, 2):
    P.revert_scene(RUN, 1, v)
ok("판본: 지난 판을 눌러 봐도 늘어나지 않는다", len(versions()) <= 3, versions())
ok("판본: 되돌리면 그 그림이 실제로 걸린다",
   P.unit_image(RUN, 1).read_bytes() == P.version_path(RUN, 1, 2).read_bytes())

img(64, 64, (10, 10, 10)).save(cur)          # 처음 보는 그림
before = versions()
P.archive_scene(RUN, 1)
ok("판본: 처음 보는 그림은 새 판본으로 쌓인다", len(versions()) == len(before) + 1,
   (before, versions()))
shutil.rmtree(ep.parent, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
shutil.rmtree(work, ignore_errors=True)

# ---------------- 최종본 — 얹은 것이 보는 자리마다 따라오는가 ----------------
#
# 편집실에서 말풍선을 얹고 저장하면 작품 폴더에는 남았다. 그런데 결과 화면·
# 둘러보기·내려받기는 전부 원본 그림(unit_image)만 봐서 아무 데도 안 나왔다 —
# 저장은 되는데 보이지 않으니, 사용자 입장에서는 저장이 안 된 것과 같았다.

FRUN = "__final_test__"
fep = P.episode_dir(FRUN)
shutil.rmtree(fep.parent, ignore_errors=True)
(fep / "scene_S+").mkdir(parents=True)
for n in (1, 2):
    img(300, 400, (200, 200 - 40 * n, 180)).save(fep / "scene_S+" / f"scene{n}_c1.png")
img(300, 800, (222, 222, 222)).save(fep / "episode.png")

ok("최종본: 얹은 것이 없으면 원본 그대로다",
   P.final_unit(FRUN, 1) == P.unit_image(FRUN, 1))
ok("최종본: 얹은 것이 없으면 한 편도 원본 그대로다",
   P.final_episode(FRUN) == fep / "episode.png")

P.write_overlay(FRUN, {"scenes": {"1": {"ref_w": 300, "items": [BUBBLE]}}})
_f1 = P.final_unit(FRUN, 1)
ok("최종본: 얹은 장은 구운 그림이 나온다",
   _f1 == OV.baked_scene_path(fep, 1) and _f1.exists(), str(_f1))
ok("최종본: 안 얹은 장은 그대로 원본이다",
   P.final_unit(FRUN, 2) == P.unit_image(FRUN, 2))

# 두 번째로 물으면 다시 굽지 않는다 (볼 때마다 굽는 자리가 아니다).
_was = _f1.stat().st_mtime_ns
P.final_unit(FRUN, 1)
ok("최종본: 이미 구워져 있으면 다시 굽지 않는다",
   _f1.stat().st_mtime_ns == _was)

# 다시 그린(밑그림이 새로워진) 장은 다시 굽는다 — 옛 말풍선이 옛 그림 위에
# 남아 있으면 되돌린 것이 화면에 안 나타난다.
import os, time
os.utime(P.unit_image(FRUN, 1), (time.time() + 5, time.time() + 5))
P.final_unit(FRUN, 1)
ok("최종본: 밑그림이 새로우면 다시 굽는다",
   _f1.stat().st_mtime_ns != _was)

_fe = P.final_episode(FRUN)
ok("최종본: 얹은 것이 있으면 한 편도 구운 판이 나온다",
   _fe == OV.baked_episode_path(fep) and _fe.exists(), str(_fe))

# 여백 눈금 — 그 실행이 쓴 config 를 못 찾으면 하네스 기본값이어야 한다.
ok("여백: config 를 못 찾으면 None (기본 눈금으로 떨어진다)",
   P._run_gap_table(FRUN) is None)
ok("여백: 기본 눈금은 하네스 것과 같다",
   P._strip_gap_table()[1] == 0.07, P._strip_gap_table())

# 같은 gap_after 라도 눈금이 다르면 한 편의 높이가 달라져야 한다 — 이것이
# 기본 눈금으로 다시 구우면 원본과 어긋나던 자리다.
def _bake_h(table):
    r = OV.bake(fep, [1, 2], lambda n: P.unit_image(FRUN, n),
                {"scenes": {}}, {1: (1, "normal"), 2: (0, "normal")}, table)
    return r["height"]

_h_default = _bake_h({0: 0.0, 1: 0.07, 2: 0.26, 3: 0.62})
_h_webtoon = _bake_h({0: 0.0, 1: 0.16, 2: 0.32, 3: 0.90})
ok("여백: 눈금이 다르면 구운 한 편의 높이가 다르다",
   _h_webtoon > _h_default, (_h_default, _h_webtoon))

shutil.rmtree(fep.parent, ignore_errors=True)

print()
print(f"{'ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
