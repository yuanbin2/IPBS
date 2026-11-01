#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")"
python_bin="${PYTHON_BIN:-python3}"

if ! command -v "$python_bin" >/dev/null 2>&1; then
  echo "Python 3.12 or newer was not found." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js 20 or newer and npm are required." >&2
  exit 1
fi

if [ ! -x ".venv/bin/python" ]; then
  echo "[1/4] Creating the Python virtual environment..."
  "$python_bin" -m venv .venv
fi

echo "[2/4] Installing backend dependencies..."
.venv/bin/python -m pip install -r backend/requirements.txt

echo "[3/4] Installing and building frontend dependencies..."
npm --prefix frontend install --no-audit --no-fund
npm --prefix frontend run build

echo "[4/4] Starting backend and frontend..."
# restart.sh runs migrations, starts both servers with automatic port
# fallback and health checks (on Windows it delegates to restart-local.ps1).
exec sh ./restart.sh "$@"
