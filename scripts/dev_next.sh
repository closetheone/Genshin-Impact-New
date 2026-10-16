#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-4175}"
NEXT_PORT="${NEXT_PORT:-3000}"

port_in_use() {
  python3 - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
with socket.socket() as sock:
    sock.settimeout(0.2)
    try:
        sock.connect(("127.0.0.1", port))
    except OSError:
        raise SystemExit(1)
raise SystemExit(0)
PY
}

if port_in_use "$API_PORT"; then
  echo "API port ${API_PORT} is already in use; choose another API_PORT." >&2
  exit 1
fi
if port_in_use "$NEXT_PORT"; then
  echo "Next.js port ${NEXT_PORT} is already in use; choose another NEXT_PORT." >&2
  exit 1
fi

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

if ! curl --silent --fail "http://127.0.0.1:${API_PORT}/api/status?snapshot=fixture-2026-10-10-v1&scope=opening&purpose=display" >/dev/null; then
  echo "Python API did not become ready on 127.0.0.1:${API_PORT}." >&2
  exit 1
fi

cd "$ROOT_DIR/frontend"
export PYTHON_API_URL="http://127.0.0.1:${API_PORT}"
exec npm run dev -- --hostname 127.0.0.1 --port "$NEXT_PORT"
