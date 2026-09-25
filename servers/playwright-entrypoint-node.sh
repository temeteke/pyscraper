#!/bin/sh
# Playwright node entrypoint (all browsers): Xvfb -> x11vnc -> noVNC -> server.
#
# DISPLAY is fixed to :99: Xvfb, x11vnc and the headed browser all share it,
# so overriding DISPLAY is not supported (it would desync the chain).
# The desktop size comes from PLAYWRIGHT_SCREEN_WIDTH/HEIGHT (default
# 1280x720, positive integers, fail fast); the browser window follows it
# via explicit launch flags (see servers/playwright_node.py). Restart the
# container to apply a new size.
# Only the final `python` is exec'd; Xvfb/x11vnc/novnc_proxy receive no
# SIGTERM on container stop and are reaped by the container runtime.
# This is acceptable for dev/test use.
set -eu

export DISPLAY=":99"

: "${PLAYWRIGHT_SCREEN_WIDTH=1280}"
: "${PLAYWRIGHT_SCREEN_HEIGHT=720}"
# NOTE: `-` (not `:-`) so an explicit empty value stays empty and fails
# below, matching playwright_node.py (empty is invalid, not the default).
case "$PLAYWRIGHT_SCREEN_WIDTH" in
    ''|*[!0-9]*|0*)
        echo "[node] invalid PLAYWRIGHT_SCREEN_WIDTH: must be a positive integer" >&2
        exit 1
        ;;
esac
case "$PLAYWRIGHT_SCREEN_HEIGHT" in
    ''|*[!0-9]*|0*)
        echo "[node] invalid PLAYWRIGHT_SCREEN_HEIGHT: must be a positive integer" >&2
        exit 1
        ;;
esac

# Headless X server for the headed browser.
# A restart reuses the container filesystem: drop a stale X11 lock left by
# the previous Xvfb so the new one can bind :99 (otherwise it exits with
# "Server is already active", leaving no display for the browser). Only
# this display's files are touched; a running Xvfb is never disturbed
# because a restarted container has a fresh process namespace.
mkdir -p /tmp/.X11-unix
rm -f /tmp/.X11-unix/X99 /tmp/.X99-lock
Xvfb :99 -screen 0 "${PLAYWRIGHT_SCREEN_WIDTH}x${PLAYWRIGHT_SCREEN_HEIGHT}x24" >/tmp/xvfb.log 2>&1 &
sleep 1

# VNC server on :5900 for the X display.
x11vnc -display :99 -forever -shared -rfbport 5900 -nopw >/tmp/x11vnc.log 2>&1 &

# noVNC gateway on :7900 (HTML + websocket proxy to :5900).
# Path is the Debian `novnc` package layout; verify with:
#   docker compose run --rm playwright-chromium ls /usr/share/novnc/utils/novnc_proxy
/usr/share/novnc/utils/novnc_proxy --listen 7900 --vnc localhost:5900 >/tmp/novnc.log 2>&1 &

exec python /app/playwright_node.py
