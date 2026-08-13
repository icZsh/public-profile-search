#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONUNBUFFERED=1
export HOME="/Users/isaaczhu"
export USER="isaaczhu"
export LOGNAME="isaaczhu"

tracebrief_script_dir="${0:A:h}"
tracebrief_repo_dir="${tracebrief_script_dir:h}"
tracebrief_node_bin="/opt/homebrew/bin/node"
tracebrief_docker_bin="/opt/homebrew/bin/docker"
tracebrief_colima_bin="/opt/homebrew/bin/colima"
tracebrief_child_pids=()
tracebrief_child_names=()
tracebrief_stopping=0

tracebrief_log() {
  print -r -- "$(/bin/date -u '+%Y-%m-%dT%H:%M:%SZ') [tracebrief] $*"
}

tracebrief_require_executable() {
  local executable_path="$1"
  if [[ ! -x "$executable_path" ]]; then
    tracebrief_log "Required executable is missing: $executable_path"
    exit 1
  fi
}

tracebrief_require_file() {
  local file_path="$1"
  if [[ ! -f "$file_path" ]]; then
    tracebrief_log "Required file is missing: $file_path"
    exit 1
  fi
}

tracebrief_wait_for_docker() {
  if "$tracebrief_docker_bin" info >/dev/null 2>&1; then
    return
  fi

  local docker_context
  docker_context=$("$tracebrief_docker_bin" context show 2>/dev/null || true)
  if [[ "$docker_context" == "colima" && -x "$tracebrief_colima_bin" ]]; then
    tracebrief_log "Starting Colima"
    "$tracebrief_colima_bin" start || true
  else
    tracebrief_log "Starting Docker Desktop"
    /usr/bin/open -ga Docker >/dev/null 2>&1 || true
  fi

  for _ in {1..90}; do
    if "$tracebrief_docker_bin" info >/dev/null 2>&1; then
      return
    fi
    /bin/sleep 2
  done

  tracebrief_log "Docker did not become ready"
  exit 1
}

tracebrief_wait_for_compose_service() {
  local service_name="$1"
  local container_id
  local container_status

  for _ in {1..60}; do
    container_id=$("$tracebrief_docker_bin" compose ps -q "$service_name" 2>/dev/null || true)
    if [[ -n "$container_id" ]]; then
      container_status=$(
        "$tracebrief_docker_bin" inspect \
          -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
          "$container_id" 2>/dev/null || true
      )
      if [[ "$container_status" == "healthy" || "$container_status" == "running" ]]; then
        return
      fi
    fi
    /bin/sleep 1
  done

  tracebrief_log "Compose service did not become healthy: $service_name"
  exit 1
}

tracebrief_start_child() {
  local child_name="$1"
  shift
  tracebrief_log "Starting $child_name"
  "$@" &
  tracebrief_child_pids+=("$!")
  tracebrief_child_names+=("$child_name")
}

tracebrief_cleanup() {
  if (( tracebrief_stopping )); then
    return
  fi
  tracebrief_stopping=1
  trap - TERM INT HUP EXIT

  if (( ${#tracebrief_child_pids[@]} == 0 )); then
    return
  fi

  tracebrief_log "Stopping child services"
  /bin/kill -TERM "${tracebrief_child_pids[@]}" 2>/dev/null || true

  local stop_deadline=$((SECONDS + 30))
  local child_pid
  local any_child_alive
  while (( SECONDS < stop_deadline )); do
    any_child_alive=0
    for child_pid in "${tracebrief_child_pids[@]}"; do
      if /bin/kill -0 "$child_pid" 2>/dev/null; then
        any_child_alive=1
        break
      fi
    done
    if (( ! any_child_alive )); then
      break
    fi
    /bin/sleep 1
  done

  for child_pid in "${tracebrief_child_pids[@]}"; do
    if /bin/kill -0 "$child_pid" 2>/dev/null; then
      /bin/kill -KILL "$child_pid" 2>/dev/null || true
    fi
  done
  for child_pid in "${tracebrief_child_pids[@]}"; do
    wait "$child_pid" 2>/dev/null || true
  done
}

tracebrief_shutdown() {
  tracebrief_log "Shutdown requested"
  tracebrief_cleanup
  exit 0
}

trap tracebrief_shutdown TERM INT HUP
trap tracebrief_cleanup EXIT

cd "$tracebrief_repo_dir"

tracebrief_require_executable "$tracebrief_node_bin"
tracebrief_require_executable "$tracebrief_docker_bin"
tracebrief_require_executable "$tracebrief_repo_dir/.venv/bin/alembic"
tracebrief_require_executable "$tracebrief_repo_dir/.venv/bin/celery"
tracebrief_require_executable "$tracebrief_repo_dir/.venv/bin/python"
tracebrief_require_executable "$tracebrief_repo_dir/.venv/bin/uvicorn"
tracebrief_require_file "$tracebrief_repo_dir/.env"
tracebrief_require_file "$tracebrief_repo_dir/apps/web/.next/BUILD_ID"
tracebrief_require_file "$tracebrief_repo_dir/node_modules/next/dist/bin/next"

tracebrief_wait_for_docker
tracebrief_log "Starting durable data services"
"$tracebrief_docker_bin" compose up -d postgres redis
tracebrief_wait_for_compose_service postgres
tracebrief_wait_for_compose_service redis

tracebrief_log "Applying database migrations"
"$tracebrief_repo_dir/.venv/bin/alembic" upgrade head

tracebrief_start_child api \
  "$tracebrief_repo_dir/.venv/bin/uvicorn" apps.api.app.main:app \
  --host 127.0.0.1 --port 8800

tracebrief_api_pid="${tracebrief_child_pids[-1]}"
for _ in {1..60}; do
  if ! /bin/kill -0 "$tracebrief_api_pid" 2>/dev/null; then
    tracebrief_log "API exited before becoming ready"
    exit 1
  fi
  if /usr/bin/curl --fail --silent --max-time 2 \
    http://127.0.0.1:8800/readyz >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 1
done
if ! /usr/bin/curl --fail --silent --max-time 2 \
  http://127.0.0.1:8800/readyz >/dev/null 2>&1; then
  tracebrief_log "API did not become ready"
  exit 1
fi

tracebrief_start_child fast-worker \
  "$tracebrief_repo_dir/.venv/bin/celery" \
  -A workers.orchestrator.celery_app:celery_app worker \
  -Q fast_http --concurrency=1 --loglevel=INFO --hostname=fast@%h
tracebrief_start_child maigret-worker \
  "$tracebrief_repo_dir/.venv/bin/celery" \
  -A workers.orchestrator.celery_app:celery_app worker \
  -Q maigret_scan --concurrency=1 --loglevel=INFO --hostname=maigret@%h
tracebrief_start_child professional-worker \
  "$tracebrief_repo_dir/.venv/bin/celery" \
  -A workers.orchestrator.celery_app:celery_app worker \
  -Q professional_search --concurrency=1 --loglevel=INFO --hostname=professional@%h
tracebrief_start_child synthesis-worker \
  "$tracebrief_repo_dir/.venv/bin/celery" \
  -A workers.orchestrator.celery_app:celery_app worker \
  -Q grounded_synthesis --concurrency=1 --loglevel=INFO --hostname=synthesis@%h
tracebrief_start_child dispatcher \
  "$tracebrief_repo_dir/.venv/bin/python" \
  -m workers.maintenance.outbox_dispatcher
tracebrief_start_child web \
  "$tracebrief_node_bin" "$tracebrief_repo_dir/node_modules/next/dist/bin/next" \
  start "$tracebrief_repo_dir/apps/web" --hostname 0.0.0.0 --port 3500

tracebrief_web_pid="${tracebrief_child_pids[-1]}"
for _ in {1..60}; do
  if ! /bin/kill -0 "$tracebrief_web_pid" 2>/dev/null; then
    tracebrief_log "Web server exited before becoming ready"
    exit 1
  fi
  if /usr/bin/curl --fail --silent --max-time 2 \
    http://127.0.0.1:3500/api/readyz >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 1
done
if ! /usr/bin/curl --fail --silent --max-time 2 \
  http://127.0.0.1:3500/api/readyz >/dev/null 2>&1; then
  tracebrief_log "Web server or API proxy did not become ready"
  exit 1
fi

tracebrief_log "Tracebrief is supervised at http://isaaczhus-mac-mini.local:3500"

tracebrief_unhealthy_checks=0
while true; do
  for child_index in {1..${#tracebrief_child_pids[@]}}; do
    child_pid="${tracebrief_child_pids[$child_index]}"
    if ! /bin/kill -0 "$child_pid" 2>/dev/null; then
      child_name="${tracebrief_child_names[$child_index]}"
      if wait "$child_pid"; then
        child_status=0
      else
        child_status=$?
      fi
      tracebrief_log "$child_name exited with status $child_status; restarting the stack"
      exit 1
    fi
  done

  if /usr/bin/curl --fail --silent --max-time 2 \
    http://127.0.0.1:3500/api/readyz >/dev/null 2>&1; then
    tracebrief_unhealthy_checks=0
  else
    tracebrief_unhealthy_checks=$((tracebrief_unhealthy_checks + 1))
    if (( tracebrief_unhealthy_checks >= 3 )); then
      tracebrief_log "The web server or API proxy failed three consecutive health checks"
      exit 1
    fi
  fi
  /bin/sleep 2
done
