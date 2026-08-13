# Persistent local Tracebrief service

Tracebrief runs as a macOS LaunchAgent at
`http://isaaczhus-mac-mini.local:3500`. The agent supervises the production
Next.js server, loopback-only API, four Celery workers, and the outbox dispatcher.
Postgres and Redis run in Docker with restart policies; Postgres keeps reports in
its named volume and Redis uses AOF for in-flight broker messages. Both data ports
bind only to loopback; port 3500 is the sole LAN-facing service port.

Browser API requests use the same-origin `/api` path. Next.js proxies those
requests to `127.0.0.1:8800`, so the `.local` URL also works from another device
on the same trusted LAN.

The service logs to `~/Library/Logs/Tracebrief` with owner-only permissions. As
part of normal Mac maintenance, rotate or archive those two log files if the
always-on Celery INFO output becomes large.

Install or redeploy after application changes:

```bash
./scripts/install-tracebrief-service.sh
```

Redeploys briefly stop the running web process before rebuilding so it never
serves a partially replaced `.next` directory. The browser bundle uses the
checked-in local prototype token/user defaults; changing those values requires
matching `NEXT_PUBLIC_` values in the web app's build environment.

Inspect service state and logs:

```bash
launchctl print gui/$(id -u)/com.isaaczhu.tracebrief
tail -f ~/Library/Logs/Tracebrief/tracebrief.out.log
tail -f ~/Library/Logs/Tracebrief/tracebrief.err.log
```

Stop and disable it:

```bash
launchctl bootout gui/$(id -u)/com.isaaczhu.tracebrief
```

Port 3500 is deliberately reachable on the local network. This prototype uses a
browser-visible local token, so do not expose or forward the port to the internet.
