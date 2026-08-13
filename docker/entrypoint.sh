#!/usr/bin/env bash
# Container entrypoint: bring up a virtual X display, then hand PID 1 to the app
# so `docker stop` delivers SIGTERM straight to Flask/SocketIO.
set -euo pipefail

APP_HOST="${GROK_REGISTER_HOST:-0.0.0.0}"
APP_PORT="${GROK_REGISTER_PORT:-5000}"
DISPLAY_NUM="${DISPLAY:-:99}"
SCREEN_GEOMETRY="${GROK_REGISTER_SCREEN:-1365x900x24}"

# The bind-mounted data/ directory holds the SQLite DB, exports and diagnostics.
# A host directory created by Docker itself is root-owned, which would fail
# later with a confusing sqlite error — check it up front instead.
if ! mkdir -p /app/data 2>/dev/null || [ ! -w /app/data ]; then
    echo "ERROR: /app/data is not writable by uid $(id -u)." >&2
    echo "       Fix the bind mount on the host, e.g.:" >&2
    echo "         mkdir -p ./data && sudo chown -R 1000:1000 ./data" >&2
    exit 1
fi

# Headful Chrome inside Xvfb is the verified baseline; core/browser.py refuses
# to start on Linux without DISPLAY.
if [ ! -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ]; then
    Xvfb "${DISPLAY_NUM}" -screen 0 "${SCREEN_GEOMETRY}" -nolisten tcp -ac >/dev/null 2>&1 &
    for _ in $(seq 1 60); do
        [ -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ] && break
        sleep 0.25
    done
    if [ ! -e "/tmp/.X11-unix/X${DISPLAY_NUM#:}" ]; then
        echo "ERROR: Xvfb failed to start on display ${DISPLAY_NUM}" >&2
        exit 1
    fi
fi
export DISPLAY="${DISPLAY_NUM}"

# Allow `docker compose run <service> <command>` to override the app entirely.
if [ "$#" -gt 0 ] && [ "${1#-}" = "$1" ]; then
    exec "$@"
fi

# --allow-remote is required because the container must bind 0.0.0.0 to be
# reachable through the published port.
exec python app.py --host "${APP_HOST}" --port "${APP_PORT}" --allow-remote "$@"
