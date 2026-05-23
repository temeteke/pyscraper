import subprocess
import os
import json
import re
import threading
import time

BROWSER = os.environ.get("PLAYWRIGHT_BROWSER", "chromium")
PORT = int(os.environ.get("PLAYWRIGHT_PORT", "3000"))


def _start_chrome_cdp():
    internal_port = PORT + 1000
    cache_dir = os.path.expanduser("~/.cache/ms-playwright")
    chromes = sorted(
        d for d in os.listdir(cache_dir)
        if d.startswith("chromium-") and os.path.isdir(os.path.join(cache_dir, d))
    )
    if not chromes:
        raise RuntimeError("Chromium not found")
    chrome_bin = os.path.join(cache_dir, chromes[-1], "chrome-linux64", "chrome")
    subprocess.Popen(
        [
            chrome_bin,
            "--headless",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--remote-debugging-port={internal_port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.Popen(
        [
            "socat",
            f"TCP-LISTEN:{PORT},fork,reuseaddr",
            f"TCP:127.0.0.1:{internal_port}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _start_via_launch_server(browser_name):
    config = {"port": PORT, "headless": True, "host": "0.0.0.0"}
    config_path = f"/tmp/playwright_config_{browser_name}.json"
    with open(config_path, "w") as f:
        json.dump(config, f)
    proc = subprocess.Popen(
        [
            "python", "-m", "playwright", "launch-server",
            "--browser", browser_name,
            "--config", config_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    def _log_ws():
        for line in iter(proc.stdout.readline, b""):
            decoded = line.decode(errors="replace").strip()
            m = re.search(r"(ws://\S+)", decoded)
            if m:
                print(f"WS_ENDPOINT={m.group(1)}", flush=True)
            else:
                print(decoded, flush=True)
    threading.Thread(target=_log_ws, daemon=True).start()


if BROWSER == "chromium":
    _start_chrome_cdp()
else:
    _start_via_launch_server(BROWSER)

print(f"{BROWSER.upper()}_URL=http://localhost:{PORT}", flush=True)

while True:
    time.sleep(120)
