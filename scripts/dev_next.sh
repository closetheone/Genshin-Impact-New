#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-4175}"
NEXT_PORT="${NEXT_PORT:-3000}"

cleanup() {
  if [[ -n "${API_PID:-}" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$ROOT_DIR"
python3 scripts/serve_prototype.py --port "$API_PORT" &
API_PID=$!

for _ in {1..30}; do
  if curl --silent --fail "http://127.0.0.1:${API_PORT}/api/status?snapshot=fixture-2026-10-10-v1&scope=opening&purpose=display" >/dev/null; then
    break
  fi
  sleep 0.2
done

cd "$ROOT_DIR/frontend"
exec npm run dev -- --hostname 127.0.0.1 --port "$NEXT_PORT"
