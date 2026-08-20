#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MAP_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${SAFEAID_PYTHON:-${MAP_DIR}/.venv/bin/python}"
STM32_PORT="${SAFEAID_STM32_PORT:-/dev/ttyACM0}"
STM32_BAUD="${SAFEAID_STM32_BAUD:-115200}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python 가상환경을 찾지 못했습니다: ${PYTHON_BIN}" >&2
  exit 1
fi

if [[ ! -e "${STM32_PORT}" ]]; then
  echo "경고: STM32 직렬 장치를 아직 찾지 못했습니다: ${STM32_PORT}" >&2
  echo "서버를 저하 상태로 시작합니다. GpsService가 2초 간격으로 연결을 재시도합니다." >&2
  echo "연결 뒤에는 SAFEAID_STM32_PORT의 /dev/serial/by-id/... 경로를 권장합니다." >&2
fi

exec "${PYTHON_BIN}" "${MAP_DIR}/app.py" \
  --host 127.0.0.1 \
  --port 8790 \
  --gps-mode stm32 \
  --gps-port "${STM32_PORT}" \
  --gps-baud "${STM32_BAUD}"
