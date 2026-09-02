#!/usr/bin/env bash
# 처음 한 번만. .venv 를 만들고 필요한 것을 깝니다.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"

python3 -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" install --upgrade pip
# 랜딩(Pillow) + 하네스(requests·PyYAML) + 프로바이더 SDK
"$HERE/.venv/bin/pip" install Pillow requests PyYAML openai google-genai anthropic

echo
echo "완료. 이제 ./start.sh 로 띄우세요."
