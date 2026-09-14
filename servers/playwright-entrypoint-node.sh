#!/bin/sh
# Playwright node entrypoint (all browsers): Xvfb -> x11vnc -> noVNC -> server.
#
# DISPLAY is fixed to :99: Xvfb, x11vnc and the headed browser all share it,
# so overriding DISPLAY is not supported (it would desync the chain).
# Only the final `python` is exec'd; Xvfb/x11vnc/novnc_proxy receive no
# SIGTERM on container stop and are reaped by the container runtime.
# This is acceptable for dev/test use.
set -eu

export DISPLAY=":99"

# Headless X server for the headed browser.
Xvfb :99 -screen 0 1280x1024x24 >/tmp/xvfb.log 2>&1 &
sleep 1

# VNC server on :5900 for the X display.
x11vnc -display :99 -forever -shared -rfbport 5900 -nopw >/tmp/x11vnc.log 2>&1 &

# noVNC gateway on :7900 (HTML + websocket proxy to :5900).
# Path is the Debian `novnc` package layout; verify with:
#   docker compose run --rm playwright-chromium ls /usr/share/novnc/utils/novnc_proxy
/usr/share/novnc/utils/novnc_proxy --listen 7900 --vnc localhost:5900 >/tmp/novnc.log 2>&1 &

exec python /app/playwright_node.py
