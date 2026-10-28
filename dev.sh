#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Create .venv and install backend/requirements.txt first. See README.md.' >&2
  exit 1
fi
export PATH="$PWD/.venv/bin:$PATH"
.venv/bin/python -m uvicorn api.app:app --app-dir backend --host 127.0.0.1 --port 3004 &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT INT TERM
npm --prefix frontend run dev
