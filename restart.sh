#!/usr/bin/env bash
# Git Bash on Windows uses the same restart logic as restart.bat.
# On Linux/macOS, keep the equivalent local ports and database selection.
set -euo pipefail

case "$0" in
  */*) script_dir="${0%/*}" ;;
  *) script_dir=. ;;
esac
root="$(cd "$script_dir" && pwd)"
if command -v powershell.exe >/dev/null 2>&1; then
  script_path="$(cd "$root/scripts" && pwd -W)/restart-local.ps1"
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$script_path" "$@"
  exit $?
fi

cd "$root"
python_bin="$root/.venv/bin/python"
vite_bin="$root/frontend/node_modules/vite/bin/vite.js"
run_dir="$root/.run"
backend_url=http://127.0.0.1:8001
frontend_url=http://127.0.0.1:5174

for required in "$python_bin" "$vite_bin"; do
  if [ ! -f "$required" ]; then
    echo "Missing $required. Run ./start.sh once to install dependencies." >&2
    exit 1
  fi
done
command -v node >/dev/null || { echo "Node.js is required." >&2; exit 1; }
command -v curl >/dev/null || { echo "curl is required." >&2; exit 1; }
mkdir -p "$run_dir"

export BLOG_LOCAL_MODE=true DJANGO_SETTINGS_MODULE=config.settings
export LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false
export VITE_API_PROXY_TARGET="$backend_url" VITE_API_BASE_URL= VITE_PORT=5174

echo "Preparing the existing local database: $root/backend/db.sqlite3"
"$python_bin" "$root/backend/manage.py" migrate --noinput
"$python_bin" "$root/backend/manage.py" check

stop_owned_pid() {
  local name="$1" expected="$2" file="$run_dir/$1.pid" process_id args
  [ -f "$file" ] || return 0
  process_id="$(cat "$file")"
  if [[ "$process_id" =~ ^[0-9]+$ ]] && kill -0 "$process_id" 2>/dev/null; then
    args="$(ps -p "$process_id" -o args= 2>/dev/null || true)"
    if [[ "$args" == *"$expected"* ]]; then
      kill "$process_id"
    else
      echo "Ignoring stale $name PID $process_id; its command does not belong to this checkout."
    fi
  fi
  rm -f "$file"
}

stop_owned_pid backend "$root/backend/manage.py"
stop_owned_pid frontend "$vite_bin"

"$python_bin" -c 'import socket,sys; ports=(8001,5174); sockets=[]
try:
 for port in ports:
  s=socket.socket(); s.bind(("127.0.0.1",port)); sockets.append(s)
except OSError as exc:
 print(f"Port {port} is occupied; leaving the other application untouched: {exc}",file=sys.stderr); sys.exit(1)
finally:
 for s in sockets: s.close()'

nohup "$python_bin" "$root/backend/manage.py" runserver 127.0.0.1:8001 --noreload >"$run_dir/backend.log" 2>&1 &
echo "$!" >"$run_dir/backend.pid"
(
  cd "$root/frontend"
  nohup node "$vite_bin" --host 127.0.0.1 --port 5174 --strictPort >"$run_dir/frontend.log" 2>&1 &
  echo "$!" >"$run_dir/frontend.pid"
)

ready=false
for _ in $(seq 1 30); do
  if curl -fsS "$backend_url/api/health/" >/dev/null 2>&1 &&
     curl -fsS "$frontend_url/blog" >/dev/null 2>&1 &&
     curl -fsS "$frontend_url/api/health/" >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
if [ "$ready" != true ]; then
  echo "Startup failed. Check $run_dir/backend.log and $run_dir/frontend.log" >&2
  exit 1
fi

echo "Backend: $backend_url (local SQLite: backend/db.sqlite3)"
echo "Frontend: $frontend_url/blog (login/register: $frontend_url/login)"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$frontend_url/blog" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "$frontend_url/blog" || true
fi
