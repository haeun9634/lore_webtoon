# -*- coding: utf-8 -*-
"""design-reference 의 그림을 기다리는 화면용으로 가져온다.

두 가지를 만든다.

1. `stage/` — 단계 그림. 지금 루가 무슨 일을 하고 있는지 보여주는 큰 그림
   여섯 장(이야기 → 캐릭터 → 콘티 → 그림 → 검수 → 완성)을 순서대로 쓴다.
2. `react/` — 만졌을 때 나오는 반응 컷.

기다리는 화면의 루는 128~180px 로 뜨는데 원본은 한 장에 70KB 쯤 된다.
그대로 쓰면 로딩 화면이 로딩을 기다리게 되므로, 여기서 **골라서 줄여** 온다.

- 그림체를 하나로 맞춘다: 시트1·시트2 판만 쓴다(러프 스케치 판은 안 쓴다).
- 사람 손이 그려진 컷은 뺀다 — 화면에는 사용자 손가락이 이미 있다.
- 긴 변 320px 로 줄이고 webp 로 굽는다 — png 로 두면 38컷에 2MB 가 넘는다
  (로딩 화면이 로딩을 기다리게 된다). webp 는 Safari 14+ 부터 다 된다.
- **모든 컷을 같은 정사각 판형에 얹는다.** 원본은 흐름마다 판형이 달라서,
  화면에서 object-fit 으로 받으면 반응이 바뀔 때마다 루가 커졌다 작아졌다
  한다. 가장 큰 컷에 맞춰 투명 여백으로 채우면 그 흔들림이 없어지고, 컷끼리의
  실제 크기 차이(작게 웅크린 컷 등)는 그대로 남는다.

    python _sync_react.py
"""
import json
import shutil
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[2] / "design-reference" / "interaction"
OUT = HERE / "react"
MAX_SIDE = 320

STAGE_SRC = HERE.parents[2] / "design-reference" / "loading"
STAGE_OUT = HERE / "stage"
STAGE_SIDE = 480          # 화면에서 320px 까지 쓰니 2배 화면을 덮는다

# 파이프라인 단계 key -> 단계 그림. 순서가 곧 만드는 순서다.
STAGE_PICK = {
    "story": "loading_1_story.png",
    "sheet": "loading_2_character.png",
    "board": "loading_3_storyboard.png",
    "art":   "loading_4_drawing.png",
    "bind":  "loading_5_qa.png",
    "done":  "loading_6_complete.png",
}

# 반응 이름 -> 원본에서 가져올 파일들 (순서가 그대로 재생 순서가 된다)
PICK = {
    "idle":       [f"idle/seq1/{n:02d}.png" for n in range(1, 6)],
    # 잠드는 흐름과 깨는 흐름은 나눈다 — 한 덩어리로 두면 가만히 두기만 해도
    # 루가 혼자 깜짝 놀라며 깬다. 깨는 컷은 자는 루를 눌렀을 때만 쓴다.
    "sleep":      [f"idle/seq2/{n:02d}.png" for n in (1, 2, 3)],
    "wake":       [f"idle/seq2/{n:02d}.png" for n in (4, 5)],
    "click": ["click/random/multiclick_seq1_02.png",
              "click/random/idle_seq1_03.png",
              "click/random/pet_seq1_04.png",
              "click/random/drag_seq1_05.png",
              "click/random/shake_seq2_02.png"],
    "multiclick": [f"multiclick/seq1/{n:02d}.png" for n in range(1, 6)],
    "pet":        [f"pet/seq1/{n:02d}.png" for n in (1, 3, 4, 5)],   # 02 는 손이 나온다
    "longpress":  [f"longpress/seq1/{n:02d}.png" for n in range(1, 6)],
    "shake":      [f"shake/seq2/{n:02d}.png" for n in range(1, 7)],
    "drag":       [f"drag/seq1/{n:02d}.png" for n in (3, 4, 5)],     # 01·02 는 손이 나온다

    # _alt — 가끔(낮은 확률로, lou-play.js 의 ALT_CHANCE) 대신 쓰는 다른 판.
    # 그림체가 같은 시트끼리만 alt 로 묶는다 — 시트3(러프 스케치)은 선이 흐려서
    # 완성 채색 판과 한 화면에서 번갈아 나오면 튄다(README 알려진 한계 참고).
    # longpress 는 다른 판 자체가 없어서 alt 없음.
    "shake_alt":      [f"shake/seq1/{n:02d}.png" for n in range(1, 6)],        # 시트1 — 시트2(shake)와 그림체 같음
    "drag_alt":       [f"drag/seq2/{n:02d}.png" for n in range(1, 4)],         # 손 나오는 컷도 그대로 둔다
    "multiclick_alt": [f"multiclick/seq2/{n:02d}.png" for n in range(1, 6)],   # 손 나오는 컷도 그대로 둔다
    "pet_alt":        [f"pet/seq2/{n:02d}.png" for n in (1, 2, 3, 4, 5)],  # 06 만 뺀다 — 낙서(전화번호로 보이는 글자)가 그림에 그대로 박혀 있어서(품질 문제, 손 때문 아님)
}

# 반응마다 루가 하는 말. 컷 수와 길이가 같으면 컷을 따라가고,
# 아니면 그중 하나를 아무거나 고른다.
SAY = {
    "click": ["앗! 지금 바빠요!", "네? 부르셨어요?", "히힛, 간지러워요",
              "저 열심히 그리는 중이에요!", "우왓, 깜짝이야!"],
    # 1번 컷(평온)은 실제로 안 뜬다 — 두 번째 누름부터 이 흐름이 시작된다
    "multiclick": ["…?", "어?", "자꾸 누르시네요…", "화났어요! 흥!", "흥, 삐졌어요."],
    "pet": ["헤헤~ 기분 좋아요", "조금만 더 해주세요…", "행복해요…", "이대로 잘래요…"],
    "longpress": ["누르고 계시네요?", "…", "졸려요…", "zzz", "어… 있었어요?"],
    "drag": ["따라갈게요!", "우와아~ 빨라요!", "재밌어요!"],
    "shake": ["으악! 흔들지 마세요!", "어지러워요…", "빙글빙글…",
              "눈이 핑 돌아요…", "그만…", "머리가 어질…"],
    "wake": ["앗! 깜짝이야", "어… 있었어요?"],
    "idle": [], "sleep": [],
}
SAY["shake_alt"] = SAY["shake"]
SAY["drag_alt"] = SAY["drag"]
SAY["multiclick_alt"] = SAY["multiclick"]
SAY["pet_alt"] = SAY["pet"]


def sync_stages():
    if STAGE_OUT.exists():
        shutil.rmtree(STAGE_OUT)
    STAGE_OUT.mkdir(parents=True)
    total = 0
    for key, name in STAGE_PICK.items():
        im = Image.open(STAGE_SRC / name).convert("RGB")
        k = min(1.0, STAGE_SIDE / max(im.size))
        if k < 1:
            im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
        out = STAGE_OUT / f"{key}.webp"
        im.save(out, format="WEBP", quality=84, method=6)
        total += out.stat().st_size
    print(f"단계 그림 {len(STAGE_PICK)}장 / {total/1024:.0f}KB -> {STAGE_OUT}")


def main():
    sync_stages()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # 먼저 전부 읽어 공통 판형을 정한다 — 가장 큰 컷의 긴 변이 곧 한 변이 된다
    loaded = {k: [Image.open(SRC / rel).convert("RGBA") for rel in files]
              for k, files in PICK.items()}
    side = max(max(im.size) for ims in loaded.values() for im in ims)
    scale = min(1.0, MAX_SIDE / side)
    box = round(side * scale)

    manifest = {}
    total = 0
    for kind, ims in loaded.items():
        d = OUT / kind
        d.mkdir()
        names = []
        for i, im in enumerate(ims, 1):
            if scale < 1:
                im = im.resize((round(im.width * scale), round(im.height * scale)),
                               Image.LANCZOS)
            canvas = Image.new("RGBA", (box, box), (0, 0, 0, 0))
            canvas.paste(im, ((box - im.width) // 2, (box - im.height) // 2))
            name = f"{i:02d}.webp"
            canvas.save(d / name, format="WEBP", quality=82, method=6)
            names.append(name)
            total += (d / name).stat().st_size
        manifest[kind] = {"frames": names, "say": SAY.get(kind, [])}
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n = sum(len(v["frames"]) for v in manifest.values())
    print(f"{n}컷 / {box}x{box} / {total/1024:.0f}KB -> {OUT}")


if __name__ == "__main__":
    main()
