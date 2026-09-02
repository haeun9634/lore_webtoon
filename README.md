# lore_webtoon

`Lore/haeun` 에서 **실제로 돌고 있는 경로만** 옮겨 온 것입니다. 사진 한 장과
캐릭터 몇 줄로 웹툰 한 화를 만듭니다.

```bash
./setup.sh      # 처음 한 번 (.venv 생성 + 설치)
./start.sh      # http://127.0.0.1:8800/nh 가 열립니다
```

---

## 실제 흐름 — `/nh` (new_harness)

화면은 `landing/web/newharness.html`, 서버 연결은 `landing/newharness_pipeline.py`,
생성은 `new_harness/run.py` 입니다.

```
사진 + 캐릭터 입력
   ↓  run.py --character <character.json>            [생성 호출 있음]
이야기 후보 4개              ← 사람이 하나 고른다
   ↓  run.py --run-id <id> --pick <n> --pick-save    [호출 0회]
   ↓  구체화·콘티·컷 대본을 **안 돈다** — pick.json 만 기록하고 지나간다
   ↓  run.py --run-id <id> --sheet                   [생성 호출 있음]
캐릭터 시트                  ← [멈춤] 시트 검수 (이대로 진행 / 다시 만들기)
   ↓  run.py --run-id <id> --detail-pages            [생성 호출 있음]
페이지 그림                  → 1페이지가 표지, 장면 하나가 페이지 하나
```

**고른 방향에서 바로 그림으로 갑니다.** 구체화(`--detail`)·콘티·컷 대본은 안
돕니다 — 대사·컷·카메라를 미리 못박으면 그림이 그것을 옮기기만 해서 결과가
평평해졌기 때문입니다(커밋 `cbaab84`·`f73b038`). 이야기 후보 단계가 이미 장면
목록과 등장인물 외모까지 뽑아 두므로 `--detail-pages` 가 그걸 그대로 받아
컷 분할까지 그림 모델에게 맡깁니다 (`new_harness/detailart.py`).

`--all` 을 안 쓰고 나눠 부르는 이유: `--all` 은 이어 하는 중이라도 이야기 후보
4개를 다시 뽑습니다.

### 코드에 남아 있는 `awaiting_board`

`pick` 직후 `STATUS_AWAITING_BOARD` 로 한 번 더 멈추는 자리가 코드에는 아직
있습니다(`_run_board_phase` → `newharness.html` 의 `#boardApproval`). 다만 그
단계는 **생성 호출이 0회**라 새로 만드는 것이 없고, 검수 화면에 방금 고른 방향을
그대로 다시 보여줍니다(`board_summary()` → `direction_summary()`). 함수·상태
이름이 `board` 인 것은 옛 흐름과 맞춰 둔 것입니다.

> 실제로 돌리면 **시트 검수만 뜬다**고 확인됨. 코드상 남아 있는 위 자리와
> 어긋나므로, 화면에서 board 검수를 실제로 만나는지 한 번 더 볼 것.

### 이 흐름이 쓰는 API

| 메서드 | 주소 | 무엇 |
| --- | --- | --- |
| POST | `/api/nh/create` | 캐릭터·사진을 받아 작업 시작 → 이야기 후보 4개 |
| GET | `/api/nh/jobs/<id>` | 진행 상태 폴링 (0.8초마다) |
| POST | `/api/nh/jobs/<id>/pick` | 후보 하나 고르기 |
| POST | `/api/nh/jobs/<id>/board-decision` | approve / retry. **retry 는 이야기 후보를 다시 뽑는다** (`_run_restory_phase`) |
| POST | `/api/nh/jobs/<id>/sheet-decision` | 시트 검수 — approve / retry (retry 는 `sheet.png`·`sheet_spec.json` 을 지우고 다시) |
| GET | `/api/nh/jobs/<id>/sheet.png` | 캐릭터 시트 그림 |
| GET | `/api/nh/jobs/<id>/episode.png` | 한 편으로 이어 붙인 것 |
| GET | `/api/nh/runs/<run>/pages` | 페이지 번호 목록 |
| GET | `/api/nh/runs/<run>/page/<n>` | 페이지 그림 (`?w=` 로 축소) |
| POST | `/api/nh/runs/<run>/page/<n>/regen` | 그 페이지만 다시 그리기 |
| GET/POST | `/api/nh/runs/<run>/overlay` | 편집실 — 얹은 말풍선·스티커 |
| POST | `/api/nh/runs/<run>/bake` | 얹은 것을 그림에 굽기 |

상태는 서버가 들고 브라우저는 폴링만 합니다. 새로고침해도, 창을 닫았다 열어도
같은 화면으로 돌아옵니다 — 10분 걸리는 일에서는 편의가 아니라 필수입니다.

---

## 화면

| 주소 | 무엇 |
| --- | --- |
| `/nh` | **실제 흐름.** 사진 → 이야기 4개 → 검수 → 그림 |
| `/works` | 만든 것 전부. `?run=<id>` 로 특정 작품 |
| `/works?run=<id>` | 공유 링크가 닿는 자리 (Open Graph 태그를 서버가 실어 보냄) |
| `/editor` | 편집실 — 그림 위에 말풍선·스티커를 얹고 굽는다 |
| `/demo` · `/demo/result` | 목업. 실제 생성 없이 화면만 |
| `/` · `/result` | 옛 제품 화면 (story-harness + webtoon-harness 경로) |

---

## 폴더

```
landing/                 서버와 화면
  serve.py               표준 라이브러리 HTTP 서버. 설치할 것 없음
  newharness_pipeline.py new_harness 연결 — 지금 쓰는 경로
  pipeline.py            옛 5단계 경로 (write_character() 를 nh 가 재사용)
  overlay.py             편집실 렌더링·굽기 (두 경로가 같이 씀)
  credits.py accounts.py visibility.py ownership.py watermark.py
  web/                   화면 전부 + 예시 사진(samples) + 마스코트(lou)
new_harness/             지금 쓰는 생성 파이프라인
  run.py                 이야기·시트·그림을 한 파일에서
  detailart.py           구체화 장면 → 그림 (컷 분할까지 모델에게)
  prompt/ input/ ref/    프롬프트와 참조 자료
  runs/                  결과물 (예시 5개 들어 있음)
story-harness/           옛 경로 + **API 키(.env) 를 여기서 물려받는다**
webtoon-harness/         옛 경로
```

`new_harness/llm.py` 가 `new_harness/.env` 를 먼저 읽고 없는 값은
`story-harness/.env` 에서 물려받습니다 — 모델 선택은 앞쪽, **API 키는 뒤쪽**에
있습니다. 그래서 `story-harness` 폴더가 옛 경로를 안 써도 필요합니다
(`llm.py` 가 `import story` 도 합니다).

## 들어 있는 예시 결과물

`new_harness/runs/` 에 실제로 그려진 5개가 들어 있습니다.

| run | 캐릭터 | 제목 | 페이지 |
| --- | --- | --- | --- |
| `20260831T194100-c6c00b` | 하은 | 반복된 아침, 마법사의 외딴방 | 6 |
| `20260831T194100-c6c00b-bgtest` | 하은 | (배경 실험본) | 2 |
| `20260831T121734-c17371` | 윤도경 | 오늘은 쉬는 날 | 3 |
| `20260829T222230-9aa58a` | 모모 | 불길한 첫만남, 분홍빛 검심 | 11 |
| `20260829T195833-da85ca` | 박하은 | 게이트 이면의 관찰자 | 8 |

`/works` 목록에는 위 둘만 보입니다 — 나머지 셋은 원본에서 숨김 처리된
상태(`landing/data/hidden_runs.json`)가 그대로 따라왔습니다. 마이페이지에서
켜거나 그 파일에서 지우면 목록에 나옵니다. 숨겨져 있어도
`/works?run=<id>` 로 직접 열면 그대로 보입니다.

## 주의

- **API 키가 `story-harness/.env` 에 들어 있습니다.** `.gitignore` 로 막아 뒀지만
  커밋 전에 확인하세요.
- `/nh` 에서 「이야기 후보 만들기」를 누르면 **실제 이미지 생성 호출이 나갑니다
  (과금).** 화면만 보려면 `/demo` 나 `/works` 를 쓰세요.
- 서버는 반드시 `./start.sh` (= `.venv` 의 파이썬)로 띄웁니다. 하네스를 하위
  프로세스로 부를 때 `sys.executable` 을 그대로 쓰기 때문에, 시스템 파이썬으로
  띄우면 화면은 뜨지만 만들기를 누르는 순간 패키지가 없다고 멈춥니다.
