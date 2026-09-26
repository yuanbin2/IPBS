#!/usr/bin/env bash
# 智能个人博客系统 - 一键重启（Git Bash 版；Windows 亦可双击 restart.bat）
set -eu

cd "$(dirname "$0")"

BACKEND_PORT=8001
FRONTEND_PORT=5174

echo "============================================================"
echo "  智能个人博客系统 - 一键重启"
echo "  Backend : http://127.0.0.1:${BACKEND_PORT}"
echo "  Frontend: http://127.0.0.1:${FRONTEND_PORT}"
echo "============================================================"
echo

kill_port() {
  local port="$1"
  local pids
  pids=$(netstat -ano | grep -E ":${port} .*LISTENING" | awk '{print $NF}' | sort -u || true)
  for pid in $pids; do
    taskkill //F //PID "$pid" >/dev/null 2>&1 && echo "  - killed PID ${pid} on port ${port}"
  done
}

echo "[1/5] Stopping old dev servers ..."
# 清理目标端口及旧端口（5173/8888）上的残留进程
for port in "${BACKEND_PORT}" "${FRONTEND_PORT}" 5173 8888; do
  kill_port "${port}"
done
sleep 2
echo

echo "[2/5] Starting backend on 127.0.0.1:${BACKEND_PORT} ..."
export BLOG_LOCAL_MODE=true
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
cmd //c start "Blog Backend :${BACKEND_PORT}" cmd /c ".venv\\Scripts\\python.exe backend\\manage.py runserver 127.0.0.1:${BACKEND_PORT} --noreload"
echo

echo "[3/5] Starting frontend on 127.0.0.1:${FRONTEND_PORT} ..."
export VITE_API_PROXY_TARGET="http://127.0.0.1:${BACKEND_PORT}"
export VITE_PORT="${FRONTEND_PORT}"
cmd //c start "Blog Frontend :${FRONTEND_PORT}" cmd /c "npm --prefix frontend run dev"
echo

echo "[4/5] Waiting for services to come up ..."
sleep 10

echo "[5/5] Health check ..."
curl -s -o /dev/null -w "  backend  /api/health/ -> %{http_code}\n" "http://127.0.0.1:${BACKEND_PORT}/api/health/" || true
curl -s -o /dev/null -w "  frontend /           -> %{http_code}\n" "http://127.0.0.1:${FRONTEND_PORT}/" || true
echo
echo "Done! Open http://127.0.0.1:${FRONTEND_PORT} in your browser."
