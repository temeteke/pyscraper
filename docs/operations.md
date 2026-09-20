# Operations Guide

This guide covers Grid/Hub-based browser operation and Docker image publishing.
For test execution strategy, see [testing.md](testing.md).

## Selenium Grid

`WebPageFirefox` and `WebPageChrome` connect to a Selenium Grid when
`SELENIUM_FIREFOX_URL` / `SELENIUM_CHROME_URL` is set. Use the `node=`
argument to route a session to the Grid node that hosts a persistent
profile (the recommended way for fixed profiles):

```python
from pyscraper import WebPageFirefox

with WebPageFirefox(
    "https://example.com",
    node="firefox-profile",
) as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

The `node` value is forwarded as the `pyscraper:node` Grid capability so
the distributor routes the session to the matching node stereotype.

Any additional extension capability can also be passed via the
`capabilities` argument for custom Grid stereotypes:

```python
with WebPageFirefox(
    "https://example.com",
    capabilities={"profile:name": "fixed-profile"},
) as web_page:
    ...
```

`node` and `capabilities` are complementary: `node` is a shortcut for
`capabilities={"pyscraper:node": "…"}` and both are merged into the
session request. If both set the same key, `node` wins.

Notes:

- Capability keys that overlap with dedicated arguments/environment
  (`page_load_strategy`, `language`, `profile`) are overridden by those
  settings. Reserved option keys such as `moz:firefoxOptions` and
  `goog:chromeOptions` must not be passed. `proxy` cannot be set via
  `capabilities`; configure it with `HTTP_PROXY`, `HTTPS_PROXY`, `NO_PROXY`
  environment variables. Unsupported capabilities are logged as warnings.
- `profile` selects the browser profile directory (Firefox uses `-profile`,
  Chrome uses `--user-data-dir`). It takes precedence over the legacy
  `SELENIUM_FIREFOX_PROFILE` / `SELENIUM_CHROME_PROFILE` environment
  variables.
- `capabilities` and `node` are ignored during local (non-Grid) execution.

## Playwright Hub

`WebPagePlaywrightChromium`, `WebPagePlaywrightFirefox`, and
`WebPagePlaywrightWebKit` wrap Playwright. All three browsers share the
same stateless remote model; persistence is client-owned via
`storage_state`.

### Background: why storage_state (and not node-owned profiles)

Selenium and Playwright persist sessions differently, so pyscraper treats
them differently on purpose:

- Selenium: the node (browser side) owns a persistent profile
  (`profile` / `user_data_dir`). A fixed Grid node keeps the profile
  volume and the client routes to it with `node=`. Persistence is closed
  on the node side.
- Playwright: `storage_state` (a JSON of cookies + localStorage) is read
  with `new_context(storage_state=...)` and written with
  `context.storage_state(path=...)`. It works for every browser and can
  be held client-side. So Playwright persistence is client-owned:
  Selenium = node-owned fixed profiles, Playwright = client-owned
  `storage_state`. The ownership is deliberately separated, never mixed.

CDP cannot provide the same for all browsers:

- `connect_over_cdp` is Chromium-only. Firefox/WebKit have no CDP, so a
  remote persistent profile cannot be built for them.
- Reusing a persistent context over CDP requires the node to expose CDP
  and the Hub to resolve `/json/version` into a websocket -- a
  Chromium-only special case inside the Hub.
- A shared default context (`contexts[0]`) cannot be owned by the
  client, complicates lifecycle flags, and cannot be shared by parallel
  sessions.

Therefore the Hub relays Playwright's standard `launch-server` (`ws://`)
for all browsers, nodes are stateless and interchangeable, persistence is
unified on `storage_state`, and the Hub stays a simple relay. This is why
remote persistence works the same way for Chromium, Firefox, and WebKit.

### Local persistence and storage_state

Local `profile=` (or its alias `user_data_dir=`; `profile` takes
precedence when both are given) launches with
`launch_persistent_context`, as before. Cookies and storage survive
across sessions:

```python
from pyscraper import WebPagePlaywrightChromium

with WebPagePlaywrightChromium("https://example.com", profile="/path/to/profile") as web_page:
    for element in web_page.get("//a"):
        print(element.text)
```

Client-owned `storage_state` works locally and remotely, for all three
browsers. Pass it to load, call `save_storage_state()` to persist --
the internal Playwright context is never exposed:

```python
with WebPagePlaywrightChromium("https://example.com", storage_state="state.json") as web_page:
    ...
    web_page.save_storage_state("state.json")  # save to file
    state = web_page.save_storage_state()  # or get the dict back
```

`context_options` passes generic options (locale, timezone, viewport,
etc.) through to context creation. If both `context_options["proxy"]`
and proxy env (`HTTPS_PROXY`/`HTTP_PROXY`) are set, the env wins.
`storage_state` is ignored with a warning for local persistent contexts
(`profile=`/`user_data_dir=`).

### Remote browsers via the Hub

Two-port Hub: `4000` = websocket relay, `4001` = HTTP node registry at
`/register`/`/nodes` (health at `/health`). `/nodes` returns
`{"nodes": [{"name", "browser", "ws_endpoint"}]}`. The Hub does not
inspect the websocket path -- any path works:

- Set `PLAYWRIGHT_CHROMIUM_URL=ws://playwright-hub:4000/ws` (and the
  `PLAYWRIGHT_FIREFOX_URL` / `PLAYWRIGHT_WEBKIT_URL` equivalents) to
  connect to the Playwright Hub (`servers/playwright_hub.py`). Only
  `ws://` (or `wss://`) URLs are accepted; `http(s)://` URLs (legacy CDP)
  are rejected with an error. When `PLAYWRIGHT_*_URL` is not set the
  browser is launched locally (no Hub).
- The `node=` argument selects a node by name (taken as-is, even if its
  browser differs -- the name is the explicit routing request, e.g. the
  Selenium `chromium-profile` stereotype is unrelated to the removed
  Playwright `chromium-profile` service); when omitted the Hub selects a
  node whose `browser` matches the client.
- Fail-closed routing: a missing header, invalid JSON, an unknown
  `node`, or no node matching the requested `browser` is rejected with
  `1011 "no node available"` instead of silently falling back to another
  browser.
- Nodes are stateless (`servers/playwright_node.py` runs
  `launch-server` headed under Xvfb for every browser with
  `PLAYWRIGHT_BROWSER` / `PLAYWRIGHT_PORT` / `PLAYWRIGHT_NODE_NAME` /
  `PLAYWRIGHT_ADVERTISE_HOST` / `PLAYWRIGHT_HUB_URL`). The node waits up
  to `60`s (`LAUNCH_WAIT_TIMEOUT`, fixed) for `launch-server` to print
  its WS endpoint, then fails fast. Proxy env
  (`HTTPS_PROXY` preferred, `NO_PROXY` as bypass) is applied both when
  the node starts and when the client creates its context.
- Remote browsers are always headed (the client's `headless` flag only
  reaches the Hub as routing metadata; nodes run headed under Xvfb for
  noVNC observability). Expect higher CPU/memory than headless operation.
- `user_data_dir`/`profile` is ignored with a warning for remote
  connections; use `storage_state=` for remote persistence.
- Remote sessions are disposable: closing the client closes the
  node-side browser. Persist with `save_storage_state()` before closing.

### Gateway

Headed Playwright browsers run under Xvfb with x11vnc + noVNC bundled in
every node image; the Selenium nodes ship their own noVNC on the same
port. A single `gateway` service (plain `nginx:alpine` with mounted
`gateway/` config, no dedicated image) is the unified entry point
at `http://localhost:8080/`:

- `/` -- tile overview: all five browsers at once (Selenium first),
  each tile a live noVNC preview plus an open/closed status badge; click
  the browser name to open its full-size view where sessions are
  opened/closed/saved.
- `/view.html?browser=<target>` -- single-browser view (`<target>` is one of
  `selenium-chrome`, `selenium-firefox`, `playwright-chromium`,
  `playwright-firefox`, `playwright-webkit`).
- `/playwright-chromium/`, `/playwright-firefox/`, `/playwright-webkit/`
  -- Playwright headed browsers (raw noVNC pages).
- `/selenium-chrome/`, `/selenium-firefox/` -- Selenium Grid nodes (raw
  noVNC pages). The desktop is always visible; the browser appears once a
  Grid session starts. Password authentication is disabled on the nodes
  (`SE_VNC_NO_PASSWORD=true`).
- `/api/playwright/*` -- proxied to the `playwright-session-manager`
  service; `/api/selenium/*` -- to the `selenium-session-manager`
  service; `/api/state-files` -- to the Playwright one (see below).

Open a session from its full-size view (optional URL), resolve
challenges manually in the tile or full-size view, then persist:

If no URL is given, the session opens on a blank page (Chrome shows
`data:,`): navigate manually inside noVNC afterwards.

- Playwright: save `storage_state` JSON into the shared state dir via
  the API (`POST /api/playwright/sessions/{id}/save`); reload it via
  `storage_state=` in client code or a later session. Client-side
  equivalent:

  ```python
  with WebPagePlaywrightChromium("https://example.com", node="chromium") as wp:
      ...  # resolve the challenge in the gateway meanwhile
      wp.save_storage_state("state.json")
  ```

  Next time, load `storage_state="state.json"` to reuse the session.
- Selenium: sessions always open on a blank page or the given URL (no
  state restore; cookie persistence is a client-code concern).

### Session managers

Two services (both FastAPI, local build only, never published)
open/close browser sessions for the gateway UI without running
pyscraper client code:

- `servers/playwright_session_manager.py` (service
  `playwright-session-manager`, via
  `Dockerfile.playwright-session-manager`): sessions open via the Hub
  relay on a dedicated owner thread per session (Playwright's sync API
  is bound to its creating thread; close/save are dispatched to that
  thread), and are kept server-side with `{target, worker}` (the worker
  owns `{target, browser, context, page, pw}`);
  close releases the node-side browser. Also serves `GET
  /api/state-files` and `POST .../save`.
- `servers/selenium_session_manager.py` (service
  `selenium-session-manager`, via
  `Dockerfile.selenium-session-manager`): sessions open via
  the Grid REST API (`/wd/hub/session`) with an optional
  `pyscraper:node` stereotype; close deletes the Grid session. Grid
  response session ids are validated (alphanumeric plus hyphens,
  Selenium Grid 4 UUID shape); anything else is rejected. Both
  managers treat a malformed entry as `500` (Selenium re-validates the
  id with the same expression on close; Playwright duck-types the
  worker with `callable()` checks).
- Close is retryable: the entry is kept server-side until close
  succeeds, and a failed close returns `{"detail": ..., "retryable": true}`
  (HTTP 502) so the UI can retry without losing the handle.
- Recovery for a stuck session: there is no `?force` escape hatch.
  Restarting the owning manager container (`docker compose restart
  playwright-session-manager` / `selenium-session-manager`) only drops
  the in-memory handle; the underlying resource is left behind and must
  be released explicitly. For Selenium, delete the orphaned session
  against the Grid (`DELETE /wd/hub/session/<id>` or the Grid UI at
  `/ui`), or restart the Grid container. For Playwright, restart the
  node container (`docker compose restart` the node service) to drop the
  leftover browser. The manager's failure logs name the affected
  manager id (and, on a gone session, the Grid id).
- Payload validation errors
  are `422` with Starlette's default `{"detail": ...}` shape (unknown
  targets, blank or unknown fields, path escapes, malformed JSON).
  Error detail messages are returned verbatim (raw backend errors
  included): the gateway runs on a closed compose network with trusted
  clients, so no fixed-message substitution, truncation, or body-size
  cap is applied to client requests. The Selenium manager still caps
  its own Grid response reads at 1 MiB (`GRID_READ_CAP`), which is a
  server-side self-protection, not a client-facing limit. See the trust
  boundary note in [architecture.md](architecture.md).
  Explicitly handled errors use the `{"detail": ...}` envelope
  (Starlette convention); uncaught exceptions fall back to Starlette's
  default plain-text `500`. Only the envelope shape is contractual, not
  the message wording. (The Hub registry is stdlib and keeps its own
  `{"error": ...}` shape; out of scope here.) Undefined method/path
  combinations are `404` (unknown path) or `405` (known path, wrong
  method). A direct `GET /api/state-files/` `307`-redirects to the
  canonical path; via the gateway the nginx alias normalizes it
  before proxying. Both managers serve auto-generated
  `/openapi.json` + `/docs`.
- State files live in `SESSION_STATE_DIR` (`/data/sessions`, backed by
  the `session-states` compose volume shared with the host), listed via
  `GET /api/state-files`. Paths are confined to the state dir (absolute
  paths escaping it are rejected with `422`). Playwright accepts either
  a bare file name (resolved under the state dir, subdirectories
  allowed but only top-level files are listed), a confined absolute server-side path, or an inline dict for
  `storage_state` open; `save` accepts paths only (a dict path is `422`).
- The gateway UI exposes Open/Close + URL only; `storage_state`
  save/load is API-only (`curl` against `/api/...` above).
- Timeouts: `PLAYWRIGHT_OPEN_TIMEOUT` (default `60`s, bounds each open
  phase -- Hub `connect` and `page.goto` separately; the opener waits up
  to `2 * OPEN_TIMEOUT + 10`s) / `PLAYWRIGHT_WORKER_TIMEOUT` (default
  `120`s for close/save replies). nginx `/api/` locations use `150`s
  (`proxy_read_timeout`); keep `proxy_read_timeout >
  2 * PLAYWRIGHT_OPEN_TIMEOUT + 10` and `> PLAYWRIGHT_WORKER_TIMEOUT`.
  On slow hosts (webkit startup), raise together, e.g. in `compose.yaml`:
  `PLAYWRIGHT_OPEN_TIMEOUT=90` / `PLAYWRIGHT_WORKER_TIMEOUT=150` with
  nginx `proxy_read_timeout 220s` (open wait `2*90+10=190`s + 30s headroom).
- Hub: `PLAYWRIGHT_NODE_CONNECT_TIMEOUT` (default `10`s for the outbound
  node websocket dial); Selenium manager: `SELENIUM_REQUEST_TIMEOUT`
  (default `30`s per Grid REST call; open issues up to 3 calls --
  create, navigate, compensating close -- so ~`90`s worst case, still
  well under the nginx `150`s above).
- Invalid numeric env values (including non-positive timeouts/ports)
  fall back to defaults with a warning on stderr (managers, Hub); the
  node fails fast with an explicit error. Lifecycle messages
  (listening, node registration) go to stdout; warnings and
  request-processing failures go to stderr, matching uvicorn's defaults
  (startup/errors on stderr, access logs on stdout). `docker logs`
  merges both streams.
- Restart policies: `gateway` and both session managers use
  `restart: unless-stopped`. The Hub and nodes have none by design --
  nodes self-register with retries and the Hub is stateless, so all
  recover without restarts.
- No authentication (closed compose network, local dev use only). The
  gateway binds `8080` on all interfaces; on shared hosts bind it to
  localhost or keep it behind a firewall.

## Docker

You can use Docker to set up the development environment and run the application.
The repository includes a `compose.yaml` file for easy setup.

### Quick start (pull prebuilt images)

Prebuilt images are published to Docker Hub and GHCR by
`.github/workflows/docker.yml` on every `vX.Y.Z` tag (e.g. `v1.2.1`), on a
weekly schedule, or manually via `workflow_dispatch` (optional `version`
input, `X.Y.Z` only, e.g. `1.2.1`; empty means the pushed tag, or the latest
release tag otherwise). Always cut tags as `vX.Y.Z`: short forms like `v1.2`
still trigger the workflow but fail the version check. On tag pushes the
pushed tag itself is built, so back-pushing an old tag rebuilds that
version rather than the latest:

| Image | Docker Hub | GHCR |
|-------|------------|------|
| App | `temeteke/pyscraper` | `ghcr.io/temeteke/pyscraper` |
| Standalone | `temeteke/pyscraper-standalone` | `ghcr.io/temeteke/pyscraper-standalone` |
| Playwright Chromium | `temeteke/pyscraper-playwright-chromium` | `ghcr.io/temeteke/pyscraper-playwright-chromium` |
| Playwright Firefox | `temeteke/pyscraper-playwright-firefox` | `ghcr.io/temeteke/pyscraper-playwright-firefox` |
| Playwright WebKit (amd64 only) | `temeteke/pyscraper-playwright-webkit` | `ghcr.io/temeteke/pyscraper-playwright-webkit` |
| Playwright Hub | `temeteke/pyscraper-playwright-hub` | `ghcr.io/temeteke/pyscraper-playwright-hub` |

Each image is tagged `latest`, `X.Y.Z`, `X.Y.Z-YYYYMMDD`, and `X.Y`.
(`X.Y` is auto-derived from the release and cannot be given as a manual
`version` input; only `X.Y.Z` is accepted.)

Tag semantics:

- `latest`, `X.Y.Z`, and `X.Y` are mutable: the weekly schedule rebuilds
  them with the latest base images, so base-image security fixes are picked
  up without cutting a new release. To update base images outside the
  schedule, cut a new `vX.Y.Z` tag (a patch bump is enough, even with no code
  changes) or run the workflow manually.
- `X.Y.Z-YYYYMMDD` is an immutable snapshot of a single build. Use it when
  byte-level reproducibility matters. Note that weekly runs keep appending
  new snapshots, so old ones should be pruned periodically (GHCR retention
  rules or manual Docker Hub cleanup).

Notes:

- `compose.yaml` references the Docker Hub images, so no login is
  needed for public pulls. Services published to registries declare
  `image:` (plus a `build:` section for local development), so
  `docker compose pull` followed by `docker compose up -d` (without
  `--build`) runs those with no local build; `docker compose build`
  rebuilds (and retags) the same names locally. The two session
  managers are local-build only (`build:` without `image:`), so `up`
  always builds them.
- The WebKit image is `linux/amd64` only (Playwright WebKit has no official
  arm64 Linux support); `compose.yaml` pins `platform: linux/amd64`
  for that service.

```sh
# Fastest: pull published images (session managers still build locally)
docker compose pull
docker compose up -d
```

### Build locally

```sh
docker compose build
docker compose up
```
