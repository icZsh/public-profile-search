#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

tracebrief_install_script_dir="${0:A:h}"
tracebrief_install_repo_dir="${tracebrief_install_script_dir:h}"
tracebrief_agent_label="com.isaaczhu.tracebrief"
tracebrief_agent_source="$tracebrief_install_repo_dir/deploy/launchd/$tracebrief_agent_label.plist"
tracebrief_agent_target="/Users/isaaczhu/Library/LaunchAgents/$tracebrief_agent_label.plist"
tracebrief_agent_domain="gui/$(/usr/bin/id -u)"

tracebrief_assert_port_free() {
  local port_number="$1"
  local port_owner

  port_owner=$(/usr/sbin/lsof -nP -iTCP:"$port_number" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "$port_owner" ]]; then
    print -u2 -- "Port $port_number is already owned by a process outside the Tracebrief service:"
    print -u2 -r -- "$port_owner"
    print -u2 -- "Stop that process, then run this installer again."
    exit 1
  fi
}

tracebrief_assert_no_unmanaged_workers() {
  local worker_pids

  worker_pids=$(
    /usr/bin/pgrep -f \
      "$tracebrief_install_repo_dir/.venv/bin/celery.*workers.orchestrator.celery_app" \
      2>/dev/null || true
  )
  worker_pids+=$'\n'
  worker_pids+=$(
    /usr/bin/pgrep -f \
      "$tracebrief_install_repo_dir/.venv/bin/python.*workers.maintenance.outbox_dispatcher" \
      2>/dev/null || true
  )
  worker_pids=$(print -r -- "$worker_pids" | /usr/bin/sed '/^$/d' | /usr/bin/sort -u)

  if [[ -n "$worker_pids" ]]; then
    print -u2 -- "Tracebrief workers are still running outside the LaunchAgent:"
    /bin/ps -p "${(j:,:)${(f)worker_pids}}" -o pid=,ppid=,tty=,command= >&2 || true
    print -u2 -- "Stop those processes, then run this installer again."
    exit 1
  fi
}

cd "$tracebrief_install_repo_dir"

if [[ ! -f .env ]]; then
  print -u2 -- "Tracebrief requires $tracebrief_install_repo_dir/.env"
  exit 1
fi

/usr/bin/plutil -lint "$tracebrief_agent_source"
/bin/chmod 0600 .env
/bin/mkdir -p /Users/isaaczhu/Library/LaunchAgents /Users/isaaczhu/Library/Logs/Tracebrief
/bin/chmod 0700 /Users/isaaczhu/Library/Logs/Tracebrief
/usr/bin/touch \
  /Users/isaaczhu/Library/Logs/Tracebrief/tracebrief.out.log \
  /Users/isaaczhu/Library/Logs/Tracebrief/tracebrief.err.log
/bin/chmod 0600 \
  /Users/isaaczhu/Library/Logs/Tracebrief/tracebrief.out.log \
  /Users/isaaczhu/Library/Logs/Tracebrief/tracebrief.err.log

/bin/launchctl bootout "$tracebrief_agent_domain/$tracebrief_agent_label" 2>/dev/null || true
for _ in {1..45}; do
  if ! /bin/launchctl print \
    "$tracebrief_agent_domain/$tracebrief_agent_label" >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 1
done
if /bin/launchctl print \
  "$tracebrief_agent_domain/$tracebrief_agent_label" >/dev/null 2>&1; then
  print -u2 -- "The previous Tracebrief service did not finish unloading."
  exit 1
fi

for _ in {1..30}; do
  if ! /usr/sbin/lsof -nP -iTCP:3500 -sTCP:LISTEN >/dev/null 2>&1 \
    && ! /usr/sbin/lsof -nP -iTCP:8800 -sTCP:LISTEN >/dev/null 2>&1; then
    break
  fi
  /bin/sleep 1
done
tracebrief_assert_port_free 3500
tracebrief_assert_port_free 8800
tracebrief_assert_no_unmanaged_workers

/opt/homebrew/bin/npm run build:web
/usr/bin/install -m 0644 "$tracebrief_agent_source" "$tracebrief_agent_target"
/usr/bin/plutil -lint "$tracebrief_agent_target"
/bin/launchctl bootstrap "$tracebrief_agent_domain" "$tracebrief_agent_target"

for _ in {1..90}; do
  if /usr/bin/curl --fail --silent --max-time 2 \
    http://127.0.0.1:3500/api/readyz >/dev/null 2>&1 \
    && /usr/bin/curl --noproxy '*' --fail --silent --max-time 2 \
      http://isaaczhus-mac-mini.local:3500/api/readyz >/dev/null 2>&1; then
    print -r -- "Tracebrief service installed at http://isaaczhus-mac-mini.local:3500"
    exit 0
  fi
  /bin/sleep 1
done

print -u2 -- "Tracebrief did not become ready. Recent logs:"
/usr/bin/tail -n 40 /Users/isaaczhu/Library/Logs/Tracebrief/tracebrief.out.log >&2 || true
/usr/bin/tail -n 40 /Users/isaaczhu/Library/Logs/Tracebrief/tracebrief.err.log >&2 || true
/bin/launchctl bootout "$tracebrief_agent_domain/$tracebrief_agent_label" 2>/dev/null || true
exit 1
