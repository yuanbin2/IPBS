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
  echo "[1/5] Creating the Python virtual environment..."
  "$python_bin" -m venv .venv
fi

echo "[2/5] Installing backend dependencies..."
.venv/bin/python -m pip install -r backend/requirements.txt

echo "[3/5] Installing and building frontend dependencies..."
npm --prefix frontend install --no-audit --no-fund
npm --prefix frontend run build

export BLOG_LOCAL_MODE=true
export LANGSMITH_TRACING=false
export LANGCHAIN_TRACING_V2=false

echo "[4/5] Preparing the local SQLite database..."
.venv/bin/python backend/manage.py migrate --noinput

echo "[5/5] Starting the project at http://127.0.0.1:8000/ ..."
exec .venv/bin/python backend/manage.py runserver 127.0.0.1:8000 --noreload
