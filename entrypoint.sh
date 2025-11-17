#!/usr/bin/env sh
set -eu

LG_HOST="${RS__SERVER__HOST:-0.0.0.0}"
LG_PORT="${RS__SERVER__PORT:-2024}"

# Start LangGraph Server
langgraph dev --host ${LG_HOST} --port ${LG_PORT} &
LG_PID=$!

# Start A2A server (python-a2a) on a different port
# Assumes a2a_server.py reads ports from CONFIG/ENV
python -u a2a_server.py &
A2A_PID=$!

terminate() {
  echo "entrypoint: terminating children..."
  kill "$LG_PID" "$A2A_PID" 2>/dev/null || true
  wait "$LG_PID" "$A2A_PID" 2>/dev/null || true
  exit 0
}

trap terminate INT TERM

# Wait for either child to exit, then stop the other and exit with the same code
while :; do
  if ! kill -0 "$LG_PID" 2>/dev/null; then
    wait "$LG_PID" || CODE=$?
    CODE=${CODE:-0}
    echo "entrypoint: LangGraph exited with $CODE"
    kill "$A2A_PID" 2>/dev/null || true
    wait "$A2A_PID" 2>/dev/null || true
    exit "$CODE"
  fi
  if ! kill -0 "$A2A_PID" 2>/dev/null; then
    wait "$A2A_PID" || CODE=$?
    CODE=${CODE:-0}
    echo "entrypoint: A2A exited with $CODE"
    kill "$LG_PID" 2>/dev/null || true
    wait "$LG_PID" 2>/dev/null || true
    exit "$CODE"
  fi
  sleep 1
done