#!/usr/bin/env bash
# ============================================================
#  YT Deep Search — one-command dev launcher
#
#  Starts the FastAPI backend and the Next.js frontend together,
#  waits for the backend to be ready, tees their logs, and
#  stops BOTH cleanly when you press Ctrl+C.
#
#  Usage:  ./start.sh
# ============================================================

set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

BACKEND_PORT=8000
FRONTEND_PORT=3000
PYTHON="./myenv/bin/python"

# ── colors ────────────────────────────────────────────────
GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'
BLUE=$'\033[0;34m'; BOLD=$'\033[1m'; NC=$'\033[0m'
info() { echo -e "${BLUE}[start]${NC} $*"; }
warn() { echo -e "${YELLOW}[start]${NC} $*"; }
ok()   { echo -e "${GREEN}[start]${NC} $*"; }
err()  { echo -e "${RED}[start]${NC} $*"; }

# ── sanity checks ─────────────────────────────────────────
if [ ! -x "$PYTHON" ]; then
  err "Python interpreter not found at $PYTHON."
  err "Set up the myenv virtualenv first:"
  err "    python3 -m venv myenv && ./myenv/bin/pip install -r requirements.txt"
  exit 1
fi

if [ ! -d "frontend/ui/node_modules" ]; then
  warn "frontend/ui/node_modules not found. Running pnpm install..."
  ( cd frontend/ui && pnpm install ) || { err "pnpm install failed."; exit 1; }
fi

# ── clear any stale processes on our ports ───────────────
free_port() {
  local port="$1"
  local pids
  pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
  if [ -n "$pids" ]; then
    warn "Port $port is in use (pid $pids). Stopping it."
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi
}

free_port "$BACKEND_PORT"
free_port "$FRONTEND_PORT"

# ── launch backend ────────────────────────────────────────
info "Starting backend  →  http://127.0.0.1:$BACKEND_PORT"
"$PYTHON" api.py &
BACKEND_PID=$!

# ── launch frontend ───────────────────────────────────────
info "Starting frontend →  http://localhost:$FRONTEND_PORT"
(
  cd frontend/ui
  exec pnpm dev
) &
FRONTEND_PID=$!

# ── graceful shutdown on Ctrl+C / SIGTERM ────────────────
cleanup() {
  echo ""
  info "Shutting down backend and frontend..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  # Belt-and-suspenders: free the ports regardless of process trees.
  lsof -ti tcp:"$BACKEND_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
  lsof -ti tcp:"$FRONTEND_PORT" 2>/dev/null | xargs kill -9 2>/dev/null || true
  ok "Stopped. See you next time! 👋"
}
trap cleanup INT TERM

# ── wait for the backend to come up ───────────────────────
info "Waiting for backend to become ready..."
for i in $(seq 1 40); do
  if curl -s -o /dev/null -m 1 "http://127.0.0.1:$BACKEND_PORT/api/videos" 2>/dev/null; then
    ok "Backend ready (HTTP $(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$BACKEND_PORT/api/videos"))"
    break
  fi
  if [ "$i" -eq 40 ]; then
    warn "Backend did not report ready in time. Check the log output above."
  fi
  sleep 1
done

# ── launcher banner ───────────────────────────────────────
echo ""
ok "═══════════════════════════════════════════════════════"
ok "  ${BOLD}YT Deep Search is running${NC}"
ok "  Frontend: ${BOLD}http://localhost:$FRONTEND_PORT${NC}"
ok "  Backend:  ${BOLD}http://127.0.0.1:$BACKEND_PORT${NC}"
ok "  Press ${BOLD}Ctrl+C${NC} to stop both"
ok "═══════════════════════════════════════════════════════"
echo ""
info "Server logs stream below (Ctrl+C to stop)."

# ── keep the script alive until interrupted ───────────────
wait
