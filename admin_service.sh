#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env.admin" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env.admin"
  set +a
fi

disable_proxy_env() {
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
  unset http_proxy https_proxy all_proxy no_proxy
}

disable_proxy_env

: "${MEDIWRITER_HOST:=127.0.0.1}"
: "${MEDIWRITER_PORT:=8028}"
: "${MEDIWRITER_ADMIN_PID_FILE:=$ROOT/data/admin_backend.pid}"
: "${MEDIWRITER_ADMIN_LOG_FILE:=$ROOT/logs/admin_backend.log}"
: "${MEDIWRITER_ADMIN_SECRET_FILE:=$ROOT/data/admin_session_secret}"

mkdir -p "$(dirname "$MEDIWRITER_ADMIN_PID_FILE")" "$(dirname "$MEDIWRITER_ADMIN_LOG_FILE")"

ensure_secret() {
  if [[ -n "${MEDIWRITER_SESSION_SECRET:-}" ]]; then
    export MEDIWRITER_SESSION_SECRET
    return
  fi

  if [[ ! -f "$MEDIWRITER_ADMIN_SECRET_FILE" ]]; then
    umask 077
    python3 - <<'PY' > "$MEDIWRITER_ADMIN_SECRET_FILE"
import secrets
print(secrets.token_urlsafe(32))
PY
  fi
  export MEDIWRITER_SESSION_SECRET
  MEDIWRITER_SESSION_SECRET="$(<"$MEDIWRITER_ADMIN_SECRET_FILE")"
}

pid_running() {
  local pid="${1:-}"
  [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null
}

current_pid() {
  if [[ -f "$MEDIWRITER_ADMIN_PID_FILE" ]]; then
    local pid
    pid="$(<"$MEDIWRITER_ADMIN_PID_FILE")"
    if pid_running "$pid"; then
      echo "$pid"
      return 0
    fi
  fi
  return 1
}

wait_for_http() {
  local url="http://${MEDIWRITER_HOST}:${MEDIWRITER_PORT}/"
  for _ in {1..40}; do
    if curl -fsS -o /dev/null "$url" 2>/dev/null; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

start() {
  if pid="$(current_pid)"; then
    echo "MediWriter admin is already running: pid=$pid http://${MEDIWRITER_HOST}:${MEDIWRITER_PORT}/"
    return 0
  fi

  ensure_secret
  export MEDIWRITER_HOST MEDIWRITER_PORT
  nohup python3 "$ROOT/run_admin.py" >> "$MEDIWRITER_ADMIN_LOG_FILE" 2>&1 &
  local pid=$!
  echo "$pid" > "$MEDIWRITER_ADMIN_PID_FILE"

  if wait_for_http; then
    echo "MediWriter admin started: pid=$pid http://${MEDIWRITER_HOST}:${MEDIWRITER_PORT}/"
    echo "Log: $MEDIWRITER_ADMIN_LOG_FILE"
  else
    echo "MediWriter admin started but did not answer yet: pid=$pid" >&2
    echo "Check log: $MEDIWRITER_ADMIN_LOG_FILE" >&2
    return 1
  fi
}

stop() {
  if ! pid="$(current_pid)"; then
    echo "MediWriter admin is not running"
    rm -f "$MEDIWRITER_ADMIN_PID_FILE"
    return 0
  fi

  kill "$pid" 2>/dev/null || true
  for _ in {1..30}; do
    if ! pid_running "$pid"; then
      rm -f "$MEDIWRITER_ADMIN_PID_FILE"
      echo "MediWriter admin stopped"
      return 0
    fi
    sleep 0.2
  done

  kill -9 "$pid" 2>/dev/null || true
  rm -f "$MEDIWRITER_ADMIN_PID_FILE"
  echo "MediWriter admin force stopped"
}

status() {
  if pid="$(current_pid)"; then
    echo "running pid=$pid url=http://${MEDIWRITER_HOST}:${MEDIWRITER_PORT}/"
    return 0
  fi
  echo "stopped"
}

run_foreground() {
  ensure_secret
  export MEDIWRITER_HOST MEDIWRITER_PORT
  exec python3 "$ROOT/run_admin.py"
}

usage() {
  cat <<EOF
Usage: ./admin_service.sh {start|stop|restart|run|status|logs}

Commands:
  start    Start MediWriter admin in the background
  stop     Stop the background service
  restart  Stop then start
  run      Run in the foreground
  status   Show service status
  logs     Tail the service log

Environment:
  MEDIWRITER_HOST=$MEDIWRITER_HOST
  MEDIWRITER_PORT=$MEDIWRITER_PORT
EOF
}

cmd="${1:-}"
case "$cmd" in
  start)
    start
    ;;
  stop)
    stop
    ;;
  restart)
    stop
    start
    ;;
  run)
    run_foreground
    ;;
  status)
    status
    ;;
  logs)
    touch "$MEDIWRITER_ADMIN_LOG_FILE"
    tail -f "$MEDIWRITER_ADMIN_LOG_FILE"
    ;;
  *)
    usage
    exit 2
    ;;
esac
