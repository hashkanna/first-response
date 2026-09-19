#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv/bin/python ]]; then
  printf '%s\n' 'Install Python dependencies first: uv venv .venv --python 3.11 && uv pip install --python .venv/bin/python -r requirements.txt' >&2
  exit 1
fi
if [[ ! -x web/node_modules/.bin/vite ]]; then
  printf '%s\n' 'Install web dependencies first: npm --prefix web ci' >&2
  exit 1
fi
war_room_port="${WAR_ROOM_PORT:-8000}"
if [[ ! "$war_room_port" =~ ^[0-9]{1,5}$ ]] || (( 10#$war_room_port < 1 || 10#$war_room_port > 65535 )); then
  printf '%s\n' 'WAR_ROOM_PORT must be an integer between 1 and 65535.' >&2
  exit 1
fi
# Fail before starting either process if its loopback port is occupied. Never stop
# another project or quietly direct this UI at an unrelated server.
.venv/bin/python - "$war_room_port" <<'PY'
import socket
import sys
hub_port = int(sys.argv[1])
if hub_port == 5173:
    raise SystemExit('WAR_ROOM_PORT must differ from the frontend port 5173.')
for name, port in [('Hub', hub_port), ('Frontend', 5173)]:
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            hint = 'Choose another hub port, for example WAR_ROOM_PORT=8001 ./scripts/dev.sh.' if name == 'Hub' else 'Use your existing frontend or stop only the frontend process you own.'
            raise SystemExit(f'{name} cannot bind to 127.0.0.1:{port}: {exc}. {hint}') from None
PY
hub_pid=''
web_pid=''
cleanup() {
  [[ -z "$hub_pid" ]] || kill "$hub_pid" 2>/dev/null || true
  [[ -z "$web_pid" ]] || kill "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
.venv/bin/python -m uvicorn core.hub:app --host 127.0.0.1 --port "$war_room_port" &
hub_pid=$!
(
  cd web
  # A process environment variable takes precedence over Vite .env files and
  # keeps the launched browser app paired with this exact backend port.
  export VITE_HUB_URL="http://127.0.0.1:${war_room_port}"
  exec ./node_modules/.bin/vite --host 127.0.0.1
) &
web_pid=$!
printf 'First Response: http://127.0.0.1:5173  |  API docs: http://127.0.0.1:%s/docs\n' "$war_room_port"
while kill -0 "$hub_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
exit 1
