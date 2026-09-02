# refs/

레퍼런스 이미지를 두는 곳. 조건 C / D 가 여기서 파일을 읽습니다.

## turnaround.png (필수 — 조건 C, D)

캐릭터 턴어라운드 시트 1장. 정면 / 측면 / 후면이 한 장에 들어간 이미지입니다.

- 없으면 `--condition C` / `--condition D` / `--all-conditions` 는 실행 전에 중단됩니다.
- `--condition A` 는 레퍼런스가 필요 없으므로 이 파일 없이도 돕니다.
- char-harness 에서 쓰던 시트를 그대로 쓰려면:

  ```powershell
  copy C:\lore\char-harness\refs\turnaround.png C:\lore\webtoon-harness\refs\
  ```

  단, 그 시트의 캐릭터와 `config.yaml` 의 `character_appearance` 가 **같은 인물**이어야
  합니다. 다르면 텍스트와 이미지가 서로 다른 사람을 가리켜 실험이 무의미해집니다.

파일 이름을 바꾸고 싶으면 `config.yaml` 의 `conditions.C.refs` / `conditions.D.refs` 를
같이 고치세요.
