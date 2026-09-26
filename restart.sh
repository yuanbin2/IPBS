#!/usr/bin/env bash
# 智能个人博客系统 - 一键重启（Git Bash 版）
# 后端: http://127.0.0.1:8001  前端: http://127.0.0.1:5174
set -u

cd "$(dirname "$0")"

BACKEND_PORT=8001
FRONTEND_PORT=5174
BACKEND_URL="http://127.0.0.1:${BACKEND_PORT}"
FRONTEND_URL="http://127.0.0.1:${FRONTEND_PORT}"

echo "============================================================"
echo "  智能个人博客系统 - 一键重启"
echo "  Backend : ${BACKEND_URL}"
echo "  Frontend: ${FRONTEND_URL}"
echo "============================================================"
echo

echo "[1/4] Stopping old dev servers ..."
powershell -NoProfile -Command "
  Get-NetTCPConnection -LocalPort ${BACKEND_PORT},${FRONTEND_PORT},5173,8888,8000 -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique |
    ForEach-Object { try { Stop-Process -Id \$_ -Force -ErrorAction Stop; Write-Host \"   killed PID \$_\" } catch {} }
" 2>/dev/null || true
sleep 2
echo

echo "[2/4] Starting backend on ${BACKEND_URL} ..."
export BLOG_LOCAL_MODE=true
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false
# 用 cmd start 起独立窗口，避免随本脚本退出而被回收
cmd //c start "Blog Backend" ".venv\\Scripts\\python.exe" backend\\manage.py runserver 127.0.0.1:${BACKEND_PORT} --noreload
echo

echo "[3/4] Starting frontend on ${FRONTEND_URL} ..."
export VITE_API_PROXY_TARGET="${BACKEND_URL}"
export VITE_PORT="${FRONTEND_PORT}"
cmd //c start "Blog Frontend" npm --prefix frontend run dev
echo

echo "[4/4] Health check (up to 40s) ..."
for i in $(seq 1 13); do
  sleep 3
  code=$(curl -s -o /dev/null -w "%{http_code}" "${BACKEND_URL}/api/health/" 2>/dev/null || echo "000")
  if [ "$code" = "200" ]; then break; fi
done
curl -s -o /dev/null -w "   backend  -> %{http_code}\n" "${BACKEND_URL}/api/health/" 2>/dev/null || echo "   backend  -> no answer"
curl -s -o /dev/null -w "   frontend -> %{http_code}\n" "${FRONTEND_URL}/" 2>/dev/null || echo "   frontend -> no answer"
echo
echo "Done! Open ${FRONTEND_URL} in your browser."
