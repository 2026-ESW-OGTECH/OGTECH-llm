#!/usr/bin/env bash
set -euo pipefail

if command -v chromium-browser >/dev/null 2>&1; then
  CHROMIUM_BIN="chromium-browser"
elif command -v chromium >/dev/null 2>&1; then
  CHROMIUM_BIN="chromium"
else
  echo "Chromium 실행 파일을 찾지 못했습니다." >&2
  exit 1
fi

exec "${CHROMIUM_BIN}" \
  --kiosk \
  --no-first-run \
  --disable-session-crashed-bubble \
  --disable-infobars \
  --autoplay-policy=no-user-gesture-required \
  http://127.0.0.1:8790/product/
