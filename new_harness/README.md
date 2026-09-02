# new_harness

사진·설명·장르를 받아 1화 이야기 후보를 만들고, 사람이 하나 고르면 그것을
콘티로 나누고, 캐릭터 시트를 뽑는다.

```
입력 ──> 이야기 후보 4개 ──> (사람이 하나 고름) ──> 콘티 ──> 캐릭터 시트
       prompt/story_prompt              prompt/storyboard_prompt
                                                     prompt/sheet_prompt
```

이야기는 `story-harness` 를 거치지 않는다. `prompt/` 안의 프롬프트가 전부다.
`story-harness` 에서 빌려 쓰는 것은 두 가지뿐이다 — 모델 호출 계층(`llm.py`)과
시트 이미지 생성(`sheet.py`). 둘 다 **읽기만** 한다: `story-harness` 는 한 줄도
고치지 않았다.

## 입력

`landing` 이 쓰는 `character.json` 을 그대로 읽는다.

```
python3 run.py --character ../landing/jobs/<job_id>/character.json
```

명령줄로 바로 줄 수도 있다.

```
python3 run.py --name 이하은 --photo a.png --photo b.png \
               --desc "겁이 많지만 결국 뛰어드는 대학생" --genre 판타지
```

- **캐릭터 이름** — 필수
- **외관** — 사진. 여러 장 가능
- **설명** — 선택. 없으면 모델이 사진에서 읽는다
- **장르** — 선택. 없으면 후보 4개가 서로 다른 장르로 나온다

`character.json` 의 `story`(줄거리) 칸은 읽고 버린다 — `story_prompt` 가
"줄거리는 받지 않는다, 네가 새로운 이야기를 만들어야 한다" 고 못 박고 있어서,
넘기면 프롬프트와 입력이 서로 반대를 말하게 된다.

## 실행

```
python3 run.py --plan                              # 어느 단계가 어느 모델인지
python3 run.py --name ... --photo a.png            # 이야기 후보 4개
python3 run.py --run-id <id> --pick 2              # 고르고 콘티까지
python3 run.py --run-id <id> --sheet               # 캐릭터 시트
python3 run.py --name ... --photo a.png --all --pick 2   # 한 번에
```

`--pick` 을 안 주면 후보를 보여주고 번호를 물어본다.
아무 명령에나 `--dry-run` 을 붙이면 프롬프트만 쓰고 호출은 안 한다 (0원).

## 결과

`runs/<run_id>/` 에 쌓인다.

| 파일 | 내용 |
| --- | --- |
| `input.json` | 정리한 입력 |
| `story_prompt.txt` `story.md` | 이야기 단계에 보낸 것과 받은 것 |
| `directions.json` | 후보 4개를 잘라 읽은 것 |
| `pick.json` | 고른 방향 |
| `board_prompt.txt` `board_raw.txt` | 콘티 단계에 보낸 것과 받은 원문 |
| `board.json` | 콘티 — `{cast, scenes[].cuts[]}` |
| `board_issues.json` | `{integrity, directing}` — 구조가 깨진 것과 연출 참고사항을 나눠 담는다 (있을 때만) |
| `pages.json` | 컷을 이미지 생성 단위로 묶은 것 |
| `sheet_spec_prompt.txt` `sheet_spec.json` | 시트 사양 |
| `sheet_prompt.txt` `sheet.png` | 시트 이미지 프롬프트와 결과 |
| `meta.json` | 호출마다 어느 모델이 얼마나 썼는지 |

**콘티는 JSON 으로 받는다.** 이야기 후보(`story.md`)만 마크다운이다 — 사람이
읽고 고르는 것이라 형식이 느슨해도 되고, 그 프롬프트의 형식·최종 확인 목록이
마크다운으로 못 박혀 있다. 콘티는 반대로 컷마다 칸이 정해져 있어서 JSON 이
맞다.

응답 원문은 파싱 **전에** 먼저 저장한다(`board_raw.txt`). 파싱이 죽어도
그 호출에 쓴 돈이 사라지지 않는다.

## 모델 — 단계마다 다르게

`.env` 만 고치면 바뀐다. `.env.example` 을 `.env` 로 복사해서 쓴다.

```
<단계>_PROVIDER / <단계>_MODEL   >   NH_PROVIDER / NH_MODEL   >   PROVIDER
```

| 단계 | 하는 일 | 프로바이더 |
| --- | --- | --- |
| `STORY` | 이야기 후보 4개 | gemini · openai · anthropic |
| `BOARD` | 콘티 | gemini · openai · anthropic |
| `SHEET` | 시트 사양 | gemini · openai · anthropic |
| `SHEET_IMAGE` | 시트 그림 | gemini · openai |
| `PAGE_IMAGE` | 페이지 그림 | gemini · openai |

```
NH_PROVIDER=gemini

STORY_PROVIDER=openai
STORY_MODEL=gpt-5.1

SHEET_PROVIDER=anthropic
SHEET_MODEL=claude-opus-5

SHEET_IMAGE_PROVIDER=openai
```

지금 무엇으로 도는지, 그리고 **어느 줄이 이겼는지**는 `--plan` 이 보여준다.

```
$ python3 run.py --plan
  단계                      모델                       어디서
  ───────────  ───────────  ─────────────────────────  ─────────────────
  STORY        이야기 후보  openai:gpt-5.1             STORY_MODEL
  BOARD        콘티         gemini:gemini-3.5-flash    NH_PROVIDER
  SHEET        시트 사양    anthropic:claude-opus-4-6  SHEET_PROVIDER
  SHEET_IMAGE  시트 그림    openai:gpt-image-2         SHEET_IMAGE_MODEL
```

"어디서" 를 같이 찍는 이유는 ".env 를 고쳤는데 왜 그대로지" 를 혼자 알아내게
두지 않으려는 것이다 — 단계별 값이 있으면 전체 기본은 안 쓰이는데, 이름만
찍히면 어느 줄이 이겼는지 알 수 없다.

그림 단계는 `NH_MODEL` 대신 `NH_IMAGE_MODEL` 을 본다. 글 모델 이름을 그림
단계가 물려받으면 그대로 죽는다.

**API 키는 여기 안 적어도 된다.** `new_harness/.env` 를 먼저 읽고 그다음
`story-harness/.env` 를 읽는데 둘 다 "이미 있는 값은 안 덮어쓴다" 라서,
모델 선택은 여기서 하고 키는 저쪽 것을 그대로 물려받는다.

값 뒤에 주석을 붙이지 마라 — 주석까지 값으로 읽힌다(`story-harness/.env` 와
같은 파서다).

## 캐릭터 시트

`prompt/sheet_prompt` 이 사진과 설명에서 사양을 적고, `sheet.py` 가 그것을
이미지 프롬프트로 바꿔 한 장을 그린다. 영역은 다섯이다.

1. 4면도 (정면 · 3/4 · 측면 · 후면)
2. 표정 6종
3. 고정 요소 확대 (3~5개)
4. **소지품** — 인물이 늘 지니고 다니는 물건을 물건만 따로 그린다
5. 색상 칩 6개

소지품 영역이 `story-harness` 의 시트와 다른 점이다. 그래서 공통 지시도 따로
둔다 — 저쪽 `SHEET_COMMON_EN` 은 `no props` 라고 못 박고 있어서 그대로 쓰면
소지품 영역이 지워진다. 소지품이 없는 인물이면 그 영역 없이 네 영역으로 그린다
(없는 물건을 지어내게 만들지 않는다).

그리기 전에 사양을 검사한다(`sheet.gate_spec`). `appearance_en` 에 한글이
섞였거나, 고정 요소가 모자라거나, 팔레트에 hex 가 없으면 **호출 전에 멈춘다** —
사양 없이 이미지를 부르면 빈칸을 모델이 평균값으로 채우고, 그렇게 나온 시트는
"컷마다 다른 사람" 을 막지 못한다.

`sheet_spec.json` 과 `sheet.png` 는 이미 있으면 다시 안 만든다. 다시 뽑으려면
지운다.

## 사건 — 그림 한 장이 되는 단위

구체화(`prompt/detail_prompt`)는 장면을 **사건(`events`)으로 나눠서** 낸다.
사건 하나가 그림 호출 하나다.

```
scenes[]                       장면 목록 한 줄 (id · source · function)
  └─ events[]                  ★ 사건 하나 = 그림 한 장
       ├─ source               이 사건을 한 문장으로
       ├─ function             이 사건이 하는 일
       ├─ detail               실제로 벌어지는 것
       ├─ learns · guesses     이 사건에서 알게 되는 것 / 짐작하는 것
       ├─ continuity           앞 사건과 이 사건 사이
       └─ leads_to             이 사건 다음에 벌어지는 일
```

**왜 장면이 아니라 사건인가.** 장면 목록 한 줄에는 보통 일이 여러 개 들어
있다 — "깨어난다 / 시간을 본다 / 방을 나선다 / 마주친다 / 인사한다 / 일과를
시작한다 / 뜻밖의 말을 듣는다". 이것을 한 장에 다 그리게 하면 화면이
산만해지고, 그렇다고 컷을 하나씩 지정해 주면 연출을 사람이 다 짜는 것이
된다(그러면 그림이 지시를 옮기기만 해서 결과가 평평해진다 — 컷 대본 단계를
건너뛴 이유와 같다). 사건에서 끊으면 그림 모델이 **컷 수·구도·여백·대사를
스스로 정한다.**

나누는 자리는 장소가 바뀌거나, 시간이 건너뛰거나, 함께 있는 인물이
바뀌거나, 하려는 일이 바뀌는 곳이다. 그 자리가 아니면 나누지 않는다.

**이어짐(`continuity`)도 사건 단위다.** 장면 경계에서 끊기지 않는다 — 장면의
첫 사건은 앞 장면의 마지막 사건과 이어진다. 비어 있는 것은 이 화의 맨 처음
사건 하나뿐이다.

**사건 칸이 없는 옛 `detail.json` 은 장면 하나가 사건 하나로 읽힌다**
(`pages.detail_events`). 그래서 예전 run 을 다시 돌려도 장면당 한 장 그대로고,
프롬프트도 한 글자 안 바뀐다.

```python
import pages
pages.detail_events(scene)          # -> [사건, 사건]  (없으면 장면 자체 하나)
pages.flatten_events(detail["scenes"])   # -> 그림 순서대로 편 사건 배열
```

편 배열이 곧 그림 순서다 — `detailart.draw` 가 표지 한 장을 그린 뒤 이
순서대로 `pages/pageNN.png` 를 채운다(**1페이지가 표지, 2페이지부터 사건**).

## 컷을 페이지로 묶기

그림은 컷 단위로 부르지 않는다. `pages.py` 가 콘티의 컷 배열을 이미지 생성
단위로 묶는다.

```python
import pages
pages.group_pages(cuts, max_per_page=5)      # -> [[컷, 컷], [컷], ...]
pages.flatten_cuts(board["scenes"])          # 장면 -> 컷을 편다
```

- `large` · `full` 은 혼자 한 페이지를 쓴다
- `tiny` · `small` · `normal` 은 순서대로 모으고, 도중에 `large`/`full` 을
  만나면 거기서 끊는다
- 한 페이지의 최대 컷 수는 `max_per_page` (기본 5)
- **컷 순서는 안 바뀐다.** 페이지를 이어 붙이면 원래 컷 배열이 그대로 나온다

모르는 크기 값은 `normal` 로 본다 — 모델이 낸 것을 읽는 자리라 오타 하나로
멈추지 않고, 혼자 한 장을 차지하는 쪽보다 되돌리기 쉬운 실수다.

## 이미지 생성 프롬프트

페이지 하나당 호출 한 번이다. 고정 블록(`prompt/image_prompt`) + 캐릭터 시트
+ 장소 + 컷 데이터를 이어 붙인다.

```python
import pages, imageprompt
pgs   = pages.group_pages(pages.flatten_cuts(board["scenes"]))
texts = imageprompt.page_prompts(pgs,
                                 sheets=[imageprompt.sheet_line(spec)],
                                 cast=board["cast"])
```

콘티는 JSON 이지만 이미지 모델은 JSON 을 읽는 물건이 아니다. 여기서 문장으로
되돌린다.

**무엇을 빼는지가 절반이다.** 콘티에는 그림에 안 그려지는 칸이 섞여 있다 —
`note`(연출 의도 메모) · `sfx[].reason`(왜 넣었는지) · `scenes[].summary`(원본
장면 문장). 그대로 넘기면 모델이 메모를 그림으로 그린다. 그려지는 것은
`dialogue[].text` 와 `sfx[].text` 뿐이다.

말풍선 모양은 콘티의 `bubble.shape` 를 그대로 쓰고, 비어 있을 때만 `type` 으로
채운다.

| `type` | 모양이 비었을 때 |
| --- | --- |
| 말 | 둥근 타원 + 꼬리 |
| 생각 | 구름 + 꼬리 |
| 외침 | 뾰족 + 꼬리 |
| 화면밖 | 둥근 타원 + `bubble.tail` (보통 "컷 바깥") |
| 나레이션 | 네모 상자, 꼬리 없음 |
| 글 | 말풍선 아님 — `bubble.position` 에 적힌 곳을 그린다 |

효과음(`sfx`)은 말풍선을 안 거친다. 글자와 위치만 나간다.

높이 비율은 `tiny 1 · small 2 · normal 3 · large 5 · full 페이지 전체`.

**대사 글자는 한 글자도 안 바꾼다.**

`cast` 는 **그 페이지에 나오는 사람만** 적는다. 안 나오는 사람까지 적으면
모델이 그 사람을 화면에 넣는다 — 고정 블록의 "지정되지 않은 인물을 추가하지
않는다" 와 정면으로 부딪힌다.

컷 번호는 **페이지 안에서 1부터** 센다. 화면에 그려 넣는 번호라 페이지 안에서
겹치지 않는 것이 전부고, 콘티의 원래 번호를 쓰면 장면이 다른 컷이 한 페이지에
모였을 때 "컷 1" 이 두 개가 된다. 화 전체로 이어 세려면 `continuous=True`.

**컷의 무게와 이어짐**은 새 필드를 안 늘리고 `size`·`background`·`location`·
`time` 에서 그대로 끌어낸다(`pages.cut_weight` · `pages.linked`).

- `light` — `tiny`/`small` 이면서 배경이 없다시피 한(`없음`/`단색`/
  `그라데이션`) 컷. 프롬프트에 "폭을 좁게 잡는다" 힌트가 붙는다.
- `linked` — 페이지 안에서 **바로 앞 컷**과 장소·시간대·배경 종류(둘 다
  `실제공간`)가 같은 컷. "배경을 새로 그리지 않고 카메라만 움직인다" 힌트가
  붙는다. 페이지 경계는 안 넘는다 — 다른 호출이라 앞 페이지가 뭘 그렸는지
  이 프롬프트만으로는 모르기 때문이다.

**연출 지식(RAG)** 은 새로 안 만들고 story-harness/webtoon-harness 가 쓰는
저장소(`story-harness/knowledge/directing/`, 109개 청크)를 `webtoon-harness/
directing.py`(`resolve_notes`)로 그대로 빌린다 — 정확 태그 매칭이라 벡터
검색은 아니다. 콘티 단계(장면 서술)와 페이지 그림 단계(그 페이지 컷의
배경·행동·대사) 각각 자기 서술에 등장하는 태그와 겹치는 조각만 "## 연출
참고" 절로 붙는다. 하나도 안 걸리면 그 절 자체가 안 생긴다.

**페이지 사이 여백·폭**도 `webtoon-harness/strip.py`의 픽셀 계산
(`gap_px`·`width_ratio`)을 그대로 쓴다(`stitch.py`). 다만 여백 **단계**
(0~3)를 매기는 기준은 다르다 — story-harness 의 `derive_layout`은 컷의
beat·transition·render_style 로 매기는데 new_harness 콘티에는 그 필드가
없다. 대신 있는 것(이어짐·직전 페이지의 마지막 컷 크기·장소가 바뀌었는가)
으로 같은 취지를 낸다(`pages.page_gap_after`). `pages.json`이 없거나 페이지
수가 안 맞으면(옛 run 등) 예전처럼 여백 없이 가운데 정렬만 한다.

### 그리기

```
python3 run.py --run-id <id> --pages      # 페이지 그림 (페이지 하나당 호출 한 번)
python3 run.py --run-id <id> --page 3     # 3페이지만 다시
```

**컷 하나에 한 번이 아니라 페이지 하나에 한 번 부른다.** 붙은 컷을 따로
그리면 이음매에서 배경과 채색이 어긋나고, 호출 수도 컷 수만큼 늘어난다.

호출마다 참조 이미지를 붙인다. 순서가 곧 모델이 보는 순서다.

1. **캐릭터 시트**(`sheet.png`) — 이 인물이 누구인지. 매 페이지에 붙는다
2. **직전 페이지** — 방금 그린 것과 같은 손으로 그리게 한다

그래서 **순서대로** 그린다. 직전 페이지를 붙이려면 그것이 이미 있어야 하니
병렬로 못 돌린다. 이미 있는 페이지는 다시 안 그린다 — 다시 뽑으려면 그 파일을
지우거나 `--page N`.

시트가 없으면 경고하고 그냥 그린다. 시트 없이 그리면 페이지마다 다른 사람이
나오므로, `--sheet` 를 먼저 돌리는 것이 맞다 (`--all` 은 그 순서로 돈다).

페이지는 세로로 길게 그린다 (`9:16` · `1024x1536`). 이미지 모델이 받는 비율
중 가장 세로로 긴 쪽이라 더 길게는 못 준다 — 한 페이지에 컷을 많이 모을수록
각 컷이 납작해진다. `max_ratio` 를 만들어 둔 이유다.

### ⚠ 한글을 이미지 모델이 그리게 두고 있다

`prompt/image_prompt` 는 "지정된 한국어 대사를 말풍선 안에 정확히 그려 넣는다"
고 말한다. **webtoon-harness 는 이 방식을 이미 겪고 버렸다.**

> 말풍선 잘림 · 단톡방 문구 안 보임 · 효과음 깨짐은 전부 같은 원인이었습니다 —
> **한글을 이미지 모델이 그리고 있었습니다.** … 이미지 모델은 한글 UI 를 못
> 그립니다 — 글자가 아예 안 나오거나 뭉개진 획이 나왔습니다.
> (`webtoon-harness/README.md` · "글자는 이제 합성으로 갑니다")

원인은 모델이 아니라 글자 자체다 — 한글 자모는 획이 많아 작은 크기에서 반드시
깨진다. 그래서 저쪽은 **자리만 비워 그리게 하고 글자는 뷰어가 SVG 로 얹는다**
(`bubble_zone_clause` · `screen_ui_clause`, 그리고 `landing/overlay.py` 의 굽기).

new_harness 는 아직 그 길을 안 갔다. 실제로 한 판 뽑아 보고 정하면 되는데,
**깨질 것을 이미 아는 채로 뽑는 것**이라는 점은 알고 시작해야 한다. 고른다면
둘 중 하나다.

- 그대로 그리게 두고, 깨지는 정도를 눈으로 확인한다 (지금 상태)
- 프롬프트를 "말풍선 모양과 자리만 그리고 글자는 비워 둬라" 로 바꾸고,
  글자는 나중에 합성한다 (webtoon-harness 와 같은 길)

### 아직 안 정한 것

- **LD 화풍이 임시값이다.** `prompt/image_prompt` 의 `- LD:` 줄이 지금
  "한국 웹툰 스타일. 성인 기준 7~8등신." 한 줄뿐이다. 선 굵기·채색·명암·색조가
  비어 있어서 매번 다른 그림이 나온다. (`webtoon-harness/config.yaml` 의
  `styles` 에 다 쓰인 그림체가 여덟 개 있다 — 옮겨 오면 되는 자리다.)
- **한 페이지 최대 컷 수.** 지금은 개수 5개로만 끊는다. 높이 비율 합계로 끊는
  `max_ratio` 를 만들어 뒀지만 **기본은 꺼져 있다** — 얼마를 넘겨야 페이지가
  너무 길어지는지 아직 붙여 보지 않았고, 정하지 않은 값을 기본값으로 박으면
  그게 곧 기준이 된다.
- **같은 공간이 여러 페이지에 걸칠 때.** 지금은 장소를 글로 다시 적는 데까지다.
  가장 넓게 나오는 컷을 먼저 그려서 나머지 호출에 참조로 붙이는 방법 — 아직
  안 해 봤다.

## 검사

```
python3 test_parse.py
```

호출을 안 하니 돈이 안 든다. 마지막 줄에 `ALL PASS` 가 찍혀야 한다.

## 아직 안 한 것

- 콘티(`cuts.json`)를 `webtoon-harness` 로 넘겨 컷 이미지를 그리는 연결
- `landing`의 **메인 화면**(story-harness+webtoon-harness) 연결 — `landing/
  newharness_pipeline.py` + `web/newharness.html` 로 별도 실험 화면에는
  이미 연결돼 있다. 메인 라우트로 바꾸는 건 아직이다.
- 후보를 고르는 화면은 실험 화면 쪽엔 있다(`newharness.html`). 명령줄
  전용이던 것은 이제 옛말이다.
