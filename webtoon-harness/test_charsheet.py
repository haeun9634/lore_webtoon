"""외형 고정 문구 검증. API 없음.

머리 길이가 컷마다 짧아지던 문제를 코드로 막고 있는지 본다. 시트에는 가슴
아래까지 오는 롱웨이브인데 컷은 턱선 단발로 나왔던 일이 있었고, 원인은
프롬프트에서 실제로 지켜지는 자리(design_details)에 길이가 없었던 것이다.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import charsheet as C

fails = []


def ok(name, cond, extra=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   {extra}" if extra and not cond else ""))
    if not cond:
        fails.append(name)


# ---------------- 머리 구절 뽑기 ----------------
SIHA = ("A young woman with messy, long ash blonde wavy hair, large bright "
        "lavender eyes with faint freckles and a natural flush under her eyes, "
        "a slim build and long limbs, usually seen in black off-shoulder tops.")

ok("머리 구절: 수식어까지 함께 뽑는다 ('with' 에서 멈춘다)",
   C.hair_phrase(SIHA) == "messy, long ash blonde wavy hair",
   C.hair_phrase(SIHA))
ok("머리 구절: 눈·체형 서술을 끌고 오지 않는다",
   "eyes" not in C.hair_phrase(SIHA) and "build" not in C.hair_phrase(SIHA))
ok("머리 구절: 뒤에 붙은 길이 서술도 가져온다",
   C.hair_phrase("She has jet-black hair down to her waist, tied with a ribbon.")
   == "jet-black hair down to her waist")
ok("머리 구절: 머리 얘기가 없으면 빈 문자열",
   C.hair_phrase("A person with no notable features.") == "")
ok("머리 구절: 빈 입력에서 터지지 않는다",
   C.hair_phrase("") == "" and C.hair_phrase(None) == "")

# ---------------- 길이 → 몸의 지점 ----------------
# long/short 은 상대적인 말이라 모델이 자기 기본값(짧은 쪽)으로 당겨 간다.
# 셀 수 있는 지시(피어싱 개수)는 한 번도 틀리지 않았으므로 같은 종류로 바꾼다.
ok("길이 환산: long 은 가슴까지로 풀어 쓴다",
   "chest" in C.length_anchor("messy, long ash blonde wavy hair"))
ok("길이 환산: 긴 표현이 짧은 표현보다 먼저 잡힌다 (shoulder-length ≠ shoulder)",
   C.length_anchor("shoulder-length brown hair") == C._LENGTH_ANCHOR["shoulder-length"])
ok("길이 환산: bob 은 턱선",
   "jaw" in C.length_anchor("a neat blonde bob"))
ok("길이 환산: 길이 형용사가 없으면 덧붙이지 않는다",
   C.length_anchor("wavy ash blonde hair") == "")

# ---------------- 고정 블록 ----------------
block = C.hair_text("messy, long ash blonde wavy hair")
ok("고정 블록: 원문 구절이 그대로 들어간다", "messy, long ash blonde wavy hair" in block)
ok("고정 블록: 몸의 지점 문장이 붙는다", "middle of the chest" in block)
ok("고정 블록: 짧게 그리는 쪽을 실수로 못박는다", "LONGER rather than shorter" in block)
ok("고정 블록: 그림체 문구의 단순화와 길이를 구분해 준다",
   "never how long it is" in block)
ok("고정 블록: 비어 있으면 아무것도 넣지 않는다", C.hair_text("") == "")

# ---------------- lock_text 안에서의 자리 ----------------
sheet = C.Sheet(run_dir=None, appearance=SIHA,
                design_details="Both ears with multiple silver piercings",
                color_palette="hair: ash blonde (#CFC3B0)")
locked = C.lock_text(sheet, outfit="a black off-shoulder top")
ok("lock_text: hair 를 안 넘겨도 appearance_en 에서 스스로 뽑는다",
   "HAIR —" in locked and "middle of the chest" in locked)
ok("lock_text: 의상 고정이 머리보다 먼저 온다 (appearance 의 옷 나열을 먼저 덮는다)",
   locked.index("DEFAULT OUTFIT") < locked.index("HAIR —"))
ok("lock_text: 넘겨준 hair 가 뽑아낸 것보다 우선한다",
   "waist" in C.lock_text(sheet, hair="black hair down to her waist"))
ok("lock_text: 시트가 없어도 터지지 않는다", isinstance(C.lock_text(None, "옷"), str))

# ---------------- 경고 ----------------
# 고쳐 넣는 것과 별개로, 원본의 어느 칸이 비었는지 사람이 보게 한다.
ok("경고: 길이가 appearance 에만 있고 design_details 에 없으면 알린다",
   "design_details" in C.hair_warning(sheet, "messy, long ash blonde wavy hair"))
sheet_ok = C.Sheet(run_dir=None, appearance=SIHA,
                   design_details="Long messy ash blonde hair past the chest")
ok("경고: design_details 에 길이가 있으면 조용하다",
   C.hair_warning(sheet_ok, "messy, long ash blonde wavy hair") == "")
ok("경고: 길이 형용사 자체가 없으면 조용하다",
   C.hair_warning(sheet, "wavy ash blonde hair") == "")

# ---------------- 소지품·머리장식 경고 ----------------
# 지팡이·모자가 appearance_en 에는 있는데 design_details 에 없어 컷마다
# 디자인이 바뀌거나 사라졌던 실제 사고(1컷·2컷 지팡이 불일치, 모자 착탈).
STAFF_APPEARANCE = ("A young woman with short black hair, always seen carrying "
                     "a wooden staff and wearing a wide-brimmed hat.")
sheet_no_accessory = C.Sheet(run_dir=None, appearance=STAFF_APPEARANCE,
                              design_details="A thin scar above the left eyebrow")
ok("소지품 경고: 지팡이·모자가 appearance 에만 있으면 알린다",
   "staff" in C.accessory_warning(sheet_no_accessory, STAFF_APPEARANCE)
   and "hat" in C.accessory_warning(sheet_no_accessory, STAFF_APPEARANCE))
sheet_with_accessory = C.Sheet(
    run_dir=None, appearance=STAFF_APPEARANCE,
    design_details="Carries a gnarled wooden staff with a blue crystal tip; "
                    "wears a wide-brimmed hat with a single feather")
ok("소지품 경고: design_details 에 이미 있으면 조용하다",
   C.accessory_warning(sheet_with_accessory, STAFF_APPEARANCE) == "")
ok("소지품 경고: 소지품 단어 자체가 없으면 조용하다",
   C.accessory_warning(sheet, SIHA) == "")
ok("소지품 경고: 시트가 없으면 터지지 않는다",
   C.accessory_warning(None, STAFF_APPEARANCE) == "")
ok("소지품 경고: 빈 appearance 에서 터지지 않는다",
   C.accessory_warning(sheet_no_accessory, "") == "")

# ---------------- 나이 ----------------
# 실사용자 지적: "나이 비율에 비해 얼굴이 성숙해 보인다. 나이대를 못맞춘다."
# (18세로 적었는데 20대 중후반 얼굴이 나왔다.) 원인은 나이가 프롬프트에 아예
# 안 들어가고 있었던 것 — charsheet 가 p1.json 의 age 를 읽지 않았다.
ok("나이: 18 이면 10대 얼굴 지시가 나온다",
   "TEENAGER" in C.age_look("18"))
ok("나이: '18세' 처럼 단위가 붙어도 읽는다",
   "TEENAGER" in C.age_look("18세"))
ok("나이: 13 은 10대 초반으로 따로 잡는다",
   "EARLY TEEN" in C.age_look("13"))
ok("나이: 35 는 성인으로 잡는다",
   "thirties" in C.age_look("35"))
ok("나이: 숫자가 없으면 조용하다 (예전 run 은 그대로 돈다)",
   C.age_look("") == "" and C.age_look("청년") == "")
ok("나이: 사람 나이가 아닌 값은 무시한다",
   C.age_look("999") == "")

# 경고는 "적었는데 못 읽은" 경우에만. 안 적은 것은 정상이라 조용해야 한다.
ok("나이 경고: 숫자를 못 뽑으면 알린다",
   "age" in C.age_warning(C.Sheet(run_dir=None, age="고등학생")))
ok("나이 경고: 숫자를 읽었으면 조용하다",
   C.age_warning(C.Sheet(run_dir=None, age="18")) == "")
ok("나이 경고: 나이를 안 적었으면 조용하다",
   C.age_warning(C.Sheet(run_dir=None)) == "")
ok("나이 경고: 시트가 없으면 터지지 않는다",
   C.age_warning(None) == "")

# design_lock 에 실제로 실리는지 — 이게 안 되면 위의 것들이 다 무의미하다.
ok("나이: lock_text 에 얼굴 지시가 실린다",
   "TEENAGER" in C.lock_text(C.Sheet(run_dir=None, age="18")))
ok("나이: age 가 없으면 lock_text 가 예전과 같다",
   C.lock_text(C.Sheet(run_dir=None)) == "")

# ---------------- 세로 스크롤: 여백 눈금과 배경 이어짐 ----------------
#
# 컷 사이 여백을 몇 px 로 그릴지(strip.gap_ratio_table)와, 앞 컷에서 배경이
# 이어지는 컷을 콘티에서 읽어 오는지(storyload.vertical_link)를 본다.
# 둘 다 **없으면 예전 그대로**여야 한다 — 이미 뽑아 둔 화가 달라지면 안 된다.
import storyload as SL
import strip as ST

ok("여백 눈금: config 가 없으면 예전 값 그대로",
   ST.gap_ratio_table(None) == ST.GAP_RATIO
   and ST.gap_ratio_table({}) == ST.GAP_RATIO
   and ST.gap_ratio_table({"scene": {}}) == ST.GAP_RATIO)
ok("여백 눈금: 적어 놓은 칸만 갈아 끼운다",
   ST.gap_ratio_table({"scene": {"gap_ratio": {3: 0.9}}})
   == {**ST.GAP_RATIO, 3: 0.9})
ok("여백 눈금: 문자열 키·값도 읽는다 (YAML 이 그렇게 줄 수 있다)",
   ST.gap_ratio_table({"scene": {"gap_ratio": {"1": "0.16"}}})[1] == 0.16)
ok("여백 눈금: 읽을 수 없는 값은 건너뛴다 (오타 하나로 조립이 막히지 않는다)",
   ST.gap_ratio_table({"scene": {"gap_ratio": {"x": 1, 9: 0.1, 2: "많이"}}})
   == ST.GAP_RATIO)
ok("여백 눈금: 800px 폭에서 웹툰 눈금이 작법 범위 안에 든다",
   [ST.gap_px(800, lv, ST.WEBTOON_GAP_RATIO) for lv in (0, 1, 2, 3)]
   == [0, 128, 256, 720],
   [ST.gap_px(800, lv, ST.WEBTOON_GAP_RATIO) for lv in (0, 1, 2, 3)])
ok("여백 눈금: 표를 안 넘기면 예전 픽셀 그대로",
   [ST.gap_px(800, lv) for lv in (0, 1, 2, 3)] == [0, 56, 208, 496],
   [ST.gap_px(800, lv) for lv in (0, 1, 2, 3)])

ok("이어짐: 콘티가 보낸 vertical_link 를 그대로 읽는다",
   SL._cut_from({"cut_number": 2, "vertical_link": True}, 2).vertical_link is True)
ok("이어짐: 칸이 없는 옛 화는 안 이어진다",
   SL._cut_from({"cut_number": 2}, 2).vertical_link is False)
ok("이어짐: 값이 이상해도 터지지 않는다",
   SL._cut_from({"cut_number": 2, "vertical_link": "yes"}, 2).vertical_link is True
   and SL._cut_from({"cut_number": 2, "vertical_link": None}, 2).vertical_link is False)

# ---------------- 컷 무게 — 묶음과 지면 폭 ----------------
#
# "한 장에 3컷" 도 "한 컷에 한 장" 도 임의의 규칙이었다. 무게가 정하게 하면
# 무거운 컷은 혼자 한 장, 배경 없는 가벼운 컷만 붙은 것끼리 묶인다.
import scenegen as SG


def _c(n, weight=None):
    d = {"cut_number": n, "description": f"컷 {n}"}
    if weight:
        d["weight"] = weight
    return d


ok("무게: float 은 render_style 로 받아진다",
   SL._cut_from({"cut_number": 1, "render_style": "float"}, 1).render_style == "float")
ok("무게: 콘티가 보낸 weight 를 그대로 읽는다",
   SL._cut_from({"cut_number": 1, "weight": "light"}, 1).weight == "light")
ok("무게: 칸이 없는 옛 컷은 normal 이다",
   SL._cut_from({"cut_number": 1}, 1).weight == "normal")
ok("무게: 모르는 값은 normal 로 떨어진다",
   SL._cut_from({"cut_number": 1, "weight": "무거움"}, 1).weight == "normal")

# 묶기 — 가벼운 컷만 붙은 것끼리
g = SG.group_by_weight([_c(1), _c(2, "light"), _c(3, "light"),
                        _c(4), _c(5, "full")], 3)
ok("묶기: 무거운 컷은 혼자 한 장",
   [s.cut_numbers for s in g] == [[1], [2, 3], [4], [5]],
   [s.cut_numbers for s in g])
ok("묶기: 장 번호가 1부터 연속이다",
   [s.scene_number for s in g] == [1, 2, 3, 4], [s.scene_number for s in g])

# 상한 — 넷을 넘기면 캔버스가 길어져 인물이 작아진다
g4 = SG.group_by_weight([_c(i, "light") for i in range(1, 8)], 3)
ok("묶기: light 묶음은 상한을 넘지 않는다",
   [s.cut_numbers for s in g4] == [[1, 2, 3], [4, 5, 6], [7]],
   [s.cut_numbers for s in g4])

# 옛 화 — weight 가 없으면 컷 하나당 한 장 (컷 모드와 같다)
gold = SG.group_by_weight([_c(i) for i in range(1, 5)], 3)
ok("묶기: weight 가 없는 옛 화는 컷 하나당 한 장",
   [s.cut_numbers for s in gold] == [[1], [2], [3], [4]],
   [s.cut_numbers for s in gold])

# weight_combine_normal — 켜면 normal 도 light 처럼 묶인다 (2026-08-27)
gwc = SG.group_by_weight([_c(1), _c(2, "light"), _c(3), _c(4, "full"),
                          _c(5), _c(6)], 3, combine_normal=True)
ok("묶기(normal 합침): full 만 혼자, 나머지는 묶인다",
   [s.cut_numbers for s in gwc] == [[1, 2, 3], [4], [5, 6]],
   [s.cut_numbers for s in gwc])
ok("묶기(normal 합침): 꺼져 있으면(기본) 예전과 똑같다",
   [s.cut_numbers for s in SG.group_by_weight(
       [_c(1), _c(2, "light"), _c(3), _c(4, "full"), _c(5), _c(6)], 3)]
   == [[1], [2], [3], [4], [5], [6]])

# 지면 폭 — 가벼운 컷만 좁아진다
ok("폭: 가벼운 컷은 지면을 덜 먹는다",
   ST.width_ratio({"weight": "light"}) == ST.LIGHT_WIDTH)
ok("폭: 나머지 컷은 예전처럼 꽉 채운다",
   ST.width_ratio({"weight": "normal"}) == 1.0
   and ST.width_ratio({"weight": "full"}) == 1.0
   and ST.width_ratio({}) == 1.0)
ok("폭: light 는 size 표보다 먼저다",
   ST.width_ratio({"weight": "light", "size": "tall"}, {"tall": 1.0}) == ST.LIGHT_WIDTH)
ok("폭: config 로 값을 바꿀 수 있다",
   ST.width_ratio({"weight": "light"}, None, 0.4) == 0.4)
ok("폭: 이상한 값이 와도 터지지 않는다",
   ST.width_ratio({"weight": "light"}, None, "반쯤") == ST.LIGHT_WIDTH)

# ---------------- 이슈 #110 — 장 사이 여백·폭이 실제 조립에 안 반영됨 ----------------
#
# strip.width_ratio 가 계산한 ratio 가 stitch_strip 에서 그냥 버려지고 있었다
# (for im, gap, _ratio in items) — 컷 하나하나는 무게를 계산해 둬도 실제
# PNG 는 전부 꽉 채워 그려졌다. episode.stitch(장 모드 조립)는 여백·폭을 아예
# 받지도 않았다. 실제 픽셀로 검증한다 — 색을 칠한 이미지를 만들고, 좁아진
# 자리의 좌우가 배경색인지 직접 확인한다.
import json, tempfile, shutil
import episode as EP
from PIL import Image

_tmp = Path(tempfile.mkdtemp())


def _img(w, h, color):
    p = _tmp / f"{color}_{w}x{h}.png"
    Image.new("RGB", (w, h), color).save(p)
    return p


# strip.stitch_strip — ratio < 1.0 인 컷이 실제로 좁아지고 가운데 정렬되는가
items = [(Image.new("RGB", (800, 600), "red"), 0, 1.0),
        (Image.new("RGB", (800, 400), "green"), 0, 0.5),
        (Image.new("RGB", (800, 500), "blue"), 0, 1.0)]
sw, sh = ST.stitch_strip(items, _tmp / "strip.png")
ok("stitch_strip: 지면 폭은 ratio=1.0 인 컷이 정한다", sw == 800, sw)
sheet = Image.open(_tmp / "strip.png")
mid_y = 600 + round(400 * 0.5 * 400 / 800) // 2   # 좁아진 컷의 세로 중앙 어림
row = [sheet.getpixel((x, 600 + 10)) for x in (0, 5, 795, 799)]
ok("stitch_strip: 좁아진 컷의 좌우는 배경색(흰)이다",
   row[0] == row[1] == row[2] == row[3] == (255, 255, 255), row)
ok("stitch_strip: ratio=1.0 인 컷은 예전처럼 꽉 찬다 (첫 줄이 빨강)",
   sheet.getpixel((0, 0)) == (255, 0, 0) and sheet.getpixel((799, 0)) == (255, 0, 0))

# episode.stitch — 인자 없이 부르면 예전과 완전히 같다 (회귀 없음)
p1, p2, p3 = _img(600, 400, "red"), _img(600, 300, "green"), _img(600, 500, "blue")
w0, h0 = EP.stitch([p1, p2, p3], _tmp / "ep_old.png")
ok("episode.stitch: 인자 없이 부르면 예전처럼 여백 없이 붙는다",
   (w0, h0) == (600, 1200), (w0, h0))

# episode.stitch — gaps·ratios 를 주면 실제로 여백이 생기고 폭이 좁아진다
gap2 = ST.gap_px(600, 2, ST.WEBTOON_GAP_RATIO)
w1, h1 = EP.stitch([p1, p2, p3], _tmp / "ep_new.png",
                   gaps=[2, 0, 1], ratios=[1.0, 0.5, 1.0],
                   gap_table=ST.WEBTOON_GAP_RATIO)
p2_h = round(300 * 300 / 600)   # 폭이 절반이 되면서 세로도 같은 비율로 준다
ok("episode.stitch: gap_after=2 만큼 실제 여백이 생긴다",
   h1 == 400 + gap2 + p2_h + 0 + 500, (h1, 400 + gap2 + p2_h + 500))
sheet2 = Image.open(_tmp / "ep_new.png")
y_mid = 400 + gap2 + p2_h // 2
row2 = [sheet2.getpixel((x, y_mid)) for x in (0, 5, 594, 599)]
ok("episode.stitch: 좁아진 장의 좌우는 배경색(흰)이다",
   row2[0] == row2[1] == row2[2] == row2[3] == (255, 255, 255), row2)
ok("episode.stitch: gap_after=0 인 자리는 정말 안 벌어진다 (경계가 바로 다음 색)",
   sheet2.getpixel((300, 400 + gap2 + p2_h)) == (0, 0, 255))

shutil.rmtree(_tmp, ignore_errors=True)

# ---------------- 이슈 #111 — max_light_per_scene 캐시 무효화 안 됨 ----------------
#
# scenes.json 캐시 재사용 조건이 grouping: weight 일 때 실제로 묶음을 정하는
# max_light_per_scene 을 안 보고 있었다 — 그 값을 바꿔도 예전 묶음을 그대로
# 재사용했다.
#
# 가짜 텍스트 클라이언트로 실제 generate_scenes() 를 (dry-run 없이) 두 번
# 부른다 — dry-run 은 캐시를 절대 안 쓰므로(항상 새로 그린다) 이 버그를
# 재현하지 못한다. 진짜로 캐시 파일을 남기고, 그 파일을 다시 읽는 경로를 본다.
import types
import run as RUN
import yaml as _yaml


class _FakeClient:
    """scene_gen 텍스트 호출을 흉내낸다. 모든 컷 번호에 자리표시자 패널을 준다 —
    실제 묶음이 어떻게 나뉘든 fill_panels() 가 채울 수 있게."""
    model = "test-model"

    def describe(self):
        return "가짜 클라이언트"

    def complete(self, prompt):
        panels = [{"cut_number": i, "scene": f"패널 {i}"} for i in range(1, 8)]
        return (json.dumps({"scenes": [{"panels": panels}]}, ensure_ascii=False), {})


_ycfg = _yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8"))
_ycfg["scene"] = dict(_ycfg["scene"])
_ycfg["scene"]["grouping"] = "weight"
_ycfg["scene"]["max_light_per_scene"] = 3
_ycfg["style_suffix"] = RUN.select_style(_ycfg, "webtoon")

_cuts = []
for i in range(1, 8):
    _cuts.append(SL.Cut(cut_number=i, description=f"컷 {i}",
                        render_style="float" if i in (2, 3, 4, 5, 6) else "normal",
                        weight="light" if i in (2, 3, 4, 5, 6) else "normal",
                        gap_after=1, beat="build", size="normal"))
_ep = SL.Episode(run_id="t111", episode=1, arc_order=1, title="시험",
                 cuts=_cuts, source="w7", has_direction=True,
                 setting={"place": "시험용 장소"})
_ep_dir = Path(tempfile.mkdtemp())
_args = types.SimpleNamespace(dry_run=False, regen_prompts=False)

scenes1 = RUN.generate_scenes(_ycfg, _args, _ep, _ep_dir, lambda: _FakeClient())
ok("캐시: max_light=3 일 때 묶음이 만들어지고 캐시가 남는다",
   [len(s.cuts) for s in scenes1] == [1, 3, 2, 1] and (_ep_dir / SG.CACHE_FILE).exists(),
   [len(s.cuts) for s in scenes1])
_cache1 = json.loads((_ep_dir / SG.CACHE_FILE).read_text(encoding="utf-8"))
ok("캐시: max_light_per_scene 값 자체가 캐시 파일에 저장된다",
   _cache1.get("max_light_per_scene") == 3, _cache1.get("max_light_per_scene"))


def _no_client():
    raise AssertionError("캐시를 재사용해야 하는데 텍스트 클라이언트를 새로 불렀다")


scenes_same = RUN.generate_scenes(_ycfg, _args, _ep, _ep_dir, _no_client)
ok("캐시: 값이 그대로면 재사용한다 (텍스트 클라이언트를 다시 안 부른다)",
   [len(s.cuts) for s in scenes_same] == [1, 3, 2, 1])

_ycfg2 = dict(_ycfg); _ycfg2["scene"] = dict(_ycfg["scene"])
_ycfg2["scene"]["max_light_per_scene"] = 2      # 값을 바꿨다 — 묶음이 달라져야 한다
scenes2 = RUN.generate_scenes(_ycfg2, _args, _ep, _ep_dir, lambda: _FakeClient())
ok("캐시: max_light_per_scene 을 바꾸면 캐시를 버리고 다시 묶는다",
   [len(s.cuts) for s in scenes2] == [1, 2, 2, 1, 1], [len(s.cuts) for s in scenes2])
_cache2 = json.loads((_ep_dir / SG.CACHE_FILE).read_text(encoding="utf-8"))
ok("캐시: 갱신된 max_light_per_scene 값이 캐시 파일에도 새로 저장된다",
   _cache2.get("max_light_per_scene") == 2, _cache2.get("max_light_per_scene"))

shutil.rmtree(_ep_dir, ignore_errors=True)

# ---------------- 이슈 #112 — --sheet-only --cuts 가 episode.png 를 부분 컷으로 덮어씀 ----------------
#
# 메인 생성 경로는 --cuts 로 몇 컷만 다시 뽑아도 조립(episode.png)에는 화
# 전체(all_cuts)를 넘긴다 — 컷 하나만 다시 뽑아도 최종본이 그 한 장으로
# 덮어써지던 예전 버그의 수정이다. 그런데 --sheet-only 분기만 이 원칙이
# 빠져서, 필터된 cuts 를 write_strip 에 그대로 넘겼다. main() 을 실제로
# 불러 재현한다(가짜 조건 A 컷 이미지 5장 + --sheet-only --cuts 2-3).
import contextlib, io, sys as _sys
import run as RUN2

_repro_run = "__repro112__"
_story_root = Path("..", "story-harness", "runs", _repro_run).resolve()
shutil.rmtree(_story_root, ignore_errors=True)
(_story_root / "webtoon").mkdir(parents=True)
_repro_cuts = [{"cut_number": i, "description": f"컷 {i} 설명", "dialogue": "",
               "beat": "build", "size": "normal", "shot": "중간", "angle": "수평",
               "transition": "장면" if i == 1 else "동작", "render_style": "normal",
               "gap_after": 1, "scene_break": i % 2 == 0, "gaze": "down", "zone": "z1"}
              for i in range(1, 6)]
(_story_root / "webtoon" / "ep01_cuts.json").write_text(
    json.dumps({"cuts": _repro_cuts}, ensure_ascii=False), encoding="utf-8")
(_story_root / "p1.json").write_text(json.dumps({
    "name": "테스트", "appearance_en": "a test character", "gender": "female",
    "color_palette": {"hair": "black", "eyes": "brown", "skin": "fair",
                      "outfit_main": "gray", "outfit_sub": "white", "accent": "red"},
    "design_details": ["a red pin", "round glasses", "a blue scarf"],
}, ensure_ascii=False), encoding="utf-8")

_repro_ep_dir = Path("outputs", _repro_run, "ep1")
shutil.rmtree(_repro_ep_dir, ignore_errors=True)
(_repro_ep_dir / "A").mkdir(parents=True)
(_repro_ep_dir / "prompts.json").write_text(
    json.dumps({"cuts": _repro_cuts}, ensure_ascii=False), encoding="utf-8")
for i in range(1, 6):
    Image.new("RGB", (600, 400 + i * 10), (10 * i, 100, 200)).save(
        _repro_ep_dir / "A" / f"cut{i}_c1.png")

_saved_argv = _sys.argv
_sys.argv = ["run.py", "--run-id", _repro_run, "--episode", "1",
            "--sheet-only", "--cuts", "2-3", "--style", "webtoon"]
try:
    with contextlib.redirect_stdout(io.StringIO()):
        RUN2.main()
finally:
    _sys.argv = _saved_argv

_ep_png = Image.open(_repro_ep_dir / "episode.png")
# 필터(--cuts 2-3)대로 됐다면 컷 2개(420+430+여백 하나)만 붙어 훨씬 짧다.
# 고쳤다면 화 전체 5개(410+420+430+440+450 + 여백 4개)가 다 붙는다.
_expect_h = sum(400 + i * 10 for i in range(1, 6)) + 4 * ST.gap_px(600, 1)
ok("#112: --sheet-only --cuts 로 걸러도 episode.png 는 화 전체를 다시 잇는다",
   _ep_png.size == (600, _expect_h),
   f"실제 {_ep_png.size}, 기대 (600, {_expect_h}) — 컷 2개만 붙었다면 이 값보다 훨씬 작다")

shutil.rmtree(_story_root, ignore_errors=True)
shutil.rmtree(_repro_ep_dir, ignore_errors=True)

# ---------------- 이슈 #113 — 후보 여러 장을 대비한 하드코딩 정리 ----------------
#
# 지금은 후보를 1장만 뽑아서 `_c1` 하드코딩과 채택 로직의 결과가 같다. 후보가
# 2장 이상이 되는 순간 "사람이 고른 후보"가 아니라 "무조건 1번"이 나가게 되는
# 자리들을 미리 막는다. picks.csv 를 만들어 두고 c2 를 고른 뒤 확인한다.
import csv as _csv
import stripview as SV
import report as RP

_p113 = Path(tempfile.mkdtemp())
(_p113 / "A").mkdir()
for _k in (1, 2):
    Image.new("RGB", (300, 200), (0, 0, 0) if _k == 1 else (255, 255, 255)).save(
        _p113 / "A" / f"cut1_c{_k}.png")
with (_p113 / "picks.csv").open("w", encoding="utf-8", newline="") as _fh:
    _w = _csv.DictWriter(_fh, fieldnames=["condition", "cut_number", "candidate"])
    _w.writeheader()
    _w.writerow({"condition": "A", "cut_number": "1", "candidate": "2"})

ok("#113: picks.csv 가 채택 후보를 정확히 읽힌다",
   RP.load_picks(_p113).get(("A", 1)) == 2, RP.load_picks(_p113))

_view = SV.build(_p113, {"run_id": "r", "episode": 1, "title": "t"},
                [{"cut_number": 1, "description": "컷 1", "gap_after": 1}], "A")
_html = _view.read_text(encoding="utf-8")
ok("#113: strip.html 이 채택본(c2)을 쓴다 (예전에는 _c1 고정)",
   "cut1_c2.png" in _html and "cut1_c1.png" not in _html,
   "c2 있음" if "cut1_c2.png" in _html else "c1 이 그대로 박혀 있음")

# 채택 파일이 사라진 경우엔 조용히 c1 으로 되돌아가야 한다 (화면이 비면 안 된다)
(_p113 / "A" / "cut1_c2.png").unlink()
_view2 = SV.build(_p113, {"run_id": "r", "episode": 1, "title": "t"},
                 [{"cut_number": 1, "description": "컷 1", "gap_after": 1}], "A")
ok("#113: 채택 파일이 없으면 c1 으로 되돌아간다",
   "cut1_c1.png" in _view2.read_text(encoding="utf-8"))

shutil.rmtree(_p113, ignore_errors=True)

# 세 번째 항목(`charsheet.Sheet` 에 run_dir 이 없어서 '.' 로 떨어진다)은
# **사실이 아니었다** — run_dir 은 Sheet 의 필수 필드다. 다시 그 결론이 나지
# 않게 못 박아 둔다.
ok("#113: charsheet.Sheet 는 run_dir 을 실제로 갖는다 (이슈의 세 번째 항목은 오진)",
   C.load(Path("/tmp/__no_such_runs_root__"), "somerun").run_dir.name == "somerun")

# --------------------------------------------------------------------------- #
# 묶음: 개수가 아니라 **캔버스에 들어가는 만큼**
#
# 전에는 "한 장에 최대 4컷" 같은 숫자가 경계를 정했다. 그 숫자는 장면이 무엇을
# 하려는지와 무관하다 — impact 하나가 캔버스를 통째로 써야 하는 자리와 wide 둘이
# 나란히 들어가고도 남는 자리를 똑같이 취급한다. 지금은 컷의 size 가 정한다.

import scenegen as SG
import run as RUN

_limit = 1.0 / RUN._ratio(RUN.TALLEST_ASPECT)
_need = lambda c: 1.0 / RUN._ratio(RUN.cut_aspect(c, RUN.TALLEST_ASPECT))
_cut = lambda n, size: {"cut_number": n, "description": f"컷 {n}", "size": size}


def _shape(sizes):
    got = SG.group_by_fit([_cut(i + 1, z) for i, z in enumerate(sizes)],
                          _need, _limit)
    return [len(sc.cuts) for sc in got]


# 가로로 넓은 컷(wide=16:9)은 세로를 적게 먹으니 셋까지 한 장에 들어간다.
ok("묶음: 개수 상한이 없다 — wide 셋은 한 장",
   _shape(["wide", "wide", "wide"]) == [3],
   f"got {_shape(['wide', 'wide', 'wide'])}")

# impact(9:16)는 혼자서 캔버스의 세로를 다 쓴다 — 혼자 한 장이어야 한다.
ok("묶음: impact 는 혼자 한 장",
   _shape(["impact", "normal"]) == [1, 1],
   f"got {_shape(['impact', 'normal'])}")

# 같은 컷 수라도 size 가 다르면 장 수가 달라진다. 이게 개수 규칙과의 차이다.
ok("묶음: 컷 수가 같아도 size 가 다르면 결과가 다르다",
   _shape(["wide", "wide"]) != _shape(["tall", "tall"]),
   f"wide2={_shape(['wide', 'wide'])} tall2={_shape(['tall', 'tall'])}")

# 1개·2개·3개가 한 화 안에서 자연히 섞인다 (사용자가 말한 그 모양).
_mixed = _shape(["wide", "normal", "wide", "impact", "wide", "wide", "wide"])
ok("묶음: 한 화 안에서 1·2·3컷이 섞인다",
   len(set(_mixed)) >= 2 and sum(_mixed) == 7, f"got {_mixed}")

# 어떤 조합이든 컷을 잃거나 순서를 바꾸지 않는다.
_all = ["tall", "impact", "wide", "normal", "tall", "wide"]
_flat = [c["cut_number"]
         for sc in SG.group_by_fit([_cut(i + 1, z) for i, z in enumerate(_all)],
                                   _need, _limit)
         for c in sc.cuts]
ok("묶음: 컷을 잃지도 순서를 바꾸지도 않는다",
   _flat == [1, 2, 3, 4, 5, 6], f"got {_flat}")

# 기본은 꺼짐이어야 한다 — 옛 화를 다시 돌리면 예전과 같은 묶음이 나와야 한다.
_old = [_cut(1, "wide"), _cut(2, "tall"), _cut(3, "normal"), _cut(4, "wide")]
_ep = type("E", (), {"has_direction": True})()
_base = {"scene": {"grouping": "rhythm", "cuts_per_scene": 3,
                   "max_cuts_per_scene": 0}}
ok("묶음: fit_to_canvas 기본 꺼짐 — 옛 화는 예전 그대로 한 장",
   [len(x.cuts) for x in RUN.group_scenes(_base, _ep, _old)] == [4])

_on = {"scene": dict(_base["scene"], fit_to_canvas=True)}
ok("묶음: fit_to_canvas 를 켜야만 캔버스 기준으로 나뉜다",
   [len(x.cuts) for x in RUN.group_scenes(_on, _ep, _old)] == [1, 1, 2],
   f"got {[len(x.cuts) for x in RUN.group_scenes(_on, _ep, _old)]}")

# size 를 아무도 안 적은 옛 콘티는 켜져 있어도 예전 그대로다.
_nosize = [{"cut_number": i + 1, "description": "x"} for i in range(4)]
ok("묶음: size 가 없는 옛 콘티는 켜져 있어도 안 나뉜다",
   [len(x.cuts) for x in RUN.group_scenes(_on, _ep, _nosize)] == [4])

# 개수 상한(max_cuts_per_scene)을 명시한 예전 config 는 그대로 지켜져야 한다.
ok("묶음: group_by_break 의 상한 0 은 예전처럼 '자르지 않음'",
   [len(sc.cuts) for sc in SG.group_by_break(
       [_cut(i + 1, "normal") for i in range(5)], 0)] == [5])

print()
print(f"{'ALL PASS' if not fails else 'FAILED: ' + ', '.join(fails)}")
sys.exit(1 if fails else 0)
