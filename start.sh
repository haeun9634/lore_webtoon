#!/usr/bin/env bash
# LORE 랜딩페이지 서버 — new_harness 흐름
#
#   ./start.sh              http://127.0.0.1:8800/nh
#   ./start.sh 9000         포트 지정
#
# 서버는 반드시 이 venv 의 파이썬으로 띄운다. 하네스를 하위 프로세스로 부를 때
# sys.executable 을 그대로 쓰기 때문에, 시스템 파이썬으로 띄우면 화면은 뜨지만
# 만들기를 누르는 순간 "openai 패키지가 없습니다" 로 멈춘다.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${1:-8800}"

if [ ! -x "$HERE/.venv/bin/python" ]; then
  echo "[중단] .venv 가 없습니다. 먼저 ./setup.sh 를 한 번 돌리세요."
  exit 1
fi

# 실제로 쓰는 화면은 /nh 다 (new_harness 흐름). serve.py --open 은 옛 제품
# 화면인 / 를 열기 때문에, 여기서 직접 연다.
( sleep 1.2; open "http://127.0.0.1:$PORT/nh" 2>/dev/null || true ) &

cd "$HERE/landing"
exec "$HERE/.venv/bin/python" serve.py --port "$PORT"
