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
- Display size: the noVNC desktop is the Xvfb screen, sized by
  `PLAYWRIGHT_SCREEN_WIDTH` / `PLAYWRIGHT_SCREEN_HEIGHT` (default
  `1280`/`720`, positive integers, fail fast; restart the node to
  apply, e.g. `1920`/`1080`). The default matches the default 16:9
  console tiles, so tiles show the desktop without side bars. The
  browser window follows the desktop: Chromium opens with
  the native window size (the manager passes `no_viewport` unless an
  emulated viewport is configured); Firefox and WebKit get a
  reduced-height default viewport computed from the desktop size so
  their outer windows land on the desktop. `--start-maximized` is
  deliberately not used anywhere
  because bare Xvfb has no window manager to honor it.
  This is the window size, not the page size: use `context_options`
  `viewport` (per console target or per client call) for the rendered
  page size.
- Remote browsers are always headed (the client's `headless` flag only
  reaches the Hub as routing metadata; nodes run headed under Xvfb for
  noVNC observability). Expect higher CPU/memory than headless operation.
- `user_data_dir`/`profile` is ignored with a warning for remote
  connections; use `storage_state=` for remote persistence.
- Remote sessions are disposable: closing the client closes the
  node-side browser. Persist with `save_storage_state()` before closing.

### Console

Headed Playwright browsers run under Xvfb with x11vnc + noVNC bundled in
every node image; the Selenium nodes ship their own noVNC on the same
port. A single `console` service (dedicated `Dockerfile.console` image,
published as `temeteke/pyscraper-console`) is the unified entry point
at `http://localhost:8080/`. The console is registry-driven: at start
`console/entrypoint.sh` reads the target registry (`console/config.yaml`),
validates it, and renders the nginx config and the UI's target list from
it, resolving the DNS resolver from `/etc/resolv.conf` so the same image
adapts to its runtime environment (see
[Console configuration](#console-configuration)):

- `/` -- tile overview: one tile per registry target, laid out by
  `ui.group_by` (`none`, `framework`, or `group`), each a noVNC preview
  (connected only when the tile becomes visible) plus an open/closed
  status badge; click the browser name to open its full-size view where
  sessions are opened/closed/saved. `ui.columns` picks a responsive grid
  (`auto`) or a fixed column count.
- `/view/<id>` -- full-size view (`<id>` is the target id, e.g.
  `selenium-chrome` or `playwright-chromium`).
- `/vnc/<id>/` -- raw noVNC page for that target. The default registry maps
  the five compose browsers (`playwright-chromium`, `playwright-firefox`,
  `playwright-webkit`, `selenium-chrome`, `selenium-firefox`). The
  Selenium desktop is always visible; the browser appears once a Grid
  session starts. Password authentication is disabled on the nodes
  (`SE_VNC_NO_PASSWORD=true`). Selenium desktop size comes from
  `SCREEN_WIDTH` / `SCREEN_HEIGHT` (`1280`/`720` in `compose.yaml` to
  match the default 16:9 console tiles). The trailing slash matters (noVNC resolves
  its assets relative to the page URL); `/vnc/<id>` without it is
  `301`-redirected to `/vnc/<id>/` by an explicit generated exact location.
  `/view` is not a route.
- `/config.json` -- the registry-derived target list the UI reads
  (`Cache-Control: no-store`; see below).
- `/api/playwright/*` -- proxied to the `playwright-session-manager`
  service (including `/api/playwright/states`); `/api/selenium/*` --
  to the `selenium-session-manager` service.

All paths sit under `CONSOLE_BASE_PATH` when it is set (empty by default,
i.e. the root; set it to e.g. `/console` to serve under a prefix, and `/`
then `308`-redirects there). `/healthz` stays at the root regardless, so
health checks do not depend on the base path.

Open a session from its full-size view (URL optional; selecting a state
prefills it), resolve challenges manually in the tile or full-size view,
then persist:

If no URL is given, the session opens on a blank page (Chrome shows
`data:,`): navigate manually inside noVNC afterwards.

- Playwright: the view offers a state selector plus a **Save** button
  when the target defines `storage_state`. The selector lists the
  configured `storage_state.states` (label shown, defaulting to the id;
  plus `(no state)`) and defaults to the first state; `?state=<id>`
  preselects one (an unknown id is ignored) and prefills the URL from
  that state. Open loads the selected id when its file exists and opens
  fresh otherwise (a state with no file yet can be created by Save; the
  view notes the fresh open). Save writes the current session to the
  selected id via `PUT /api/playwright/states/{id}`, and the selector is
  locked while a session is open so the load source and save target stay
  the same id. Closing a session opened with a selected state that was
  never saved asks for confirmation. Reload a saved state via `state_id=`
  in the API or `storage_state=` in client code. Client-side equivalent:

  ```python
  with WebPagePlaywrightChromium("https://example.com", node="chromium") as wp:
      ...  # resolve the challenge in the console meanwhile
      wp.save_storage_state("state.json")
  ```

  Next time, load `storage_state="state.json"` to reuse the session.
- Selenium: sessions always open on a blank page or the given URL (no
  state restore; cookie persistence is a client-code concern).

### Session managers

Two services (both FastAPI, published as
`temeteke/pyscraper-playwright-session-manager` and
`temeteke/pyscraper-selenium-session-manager`) open/close browser
sessions for the console UI without running
pyscraper client code:

- `servers/playwright_session_manager.py` (service
  `playwright-session-manager`, via
  `Dockerfile.playwright-session-manager`): sessions open via the Hub
  relay on a dedicated owner thread per session (Playwright's sync API
  is bound to its creating thread; close/save are dispatched to that
  thread), and are kept server-side with `{browser, node, worker}` (the
  worker owns `{browser, node, playwright_browser, context, page, pw}`);
  close releases the node-side browser. States are exposed as an id
  resource: `GET /api/playwright/states` lists
  `{"states": [{"id": ...}]}` (the `.json` stems in `SESSION_STATE_DIR`
  matching `^[a-z0-9-]+$`), `PUT /api/playwright/states/{id}`
  `{session_id}` creates/overwrites `SESSION_STATE_DIR/{id}.json` from
  that session, and `DELETE /api/playwright/states/{id}` removes it. A
  session loads a state with `POST /api/playwright/sessions
  {"state_id": "<id>"}`; an unknown id is `404` and a malformed id `422`.
  `context_options` on open accepts the registry allowlist
  (`locale`, `timezone_id`, `viewport`, `user_agent`, `color_scheme`,
  `device_scale_factor`, `has_touch`, `is_mobile`,
  `extra_http_headers`) and passes it to `new_context`; `storage_state`
  and `proxy` are rejected (`422`), as are unknown keys and
  stringly-typed values. When no `viewport`/`device_scale_factor`/
  `is_mobile` is given, the manager additionally passes
  `no_viewport` for Chromium so the session opens with the native
  window size instead of Playwright's 720p default (which would resize
  the headed window and leave the rest of the VNC desktop black).
  Firefox and WebKit instead get an explicit reduced-height default
  viewport computed from `PLAYWRIGHT_SCREEN_WIDTH/HEIGHT` (their launch
  size flags only size the startup window or don't exist, and their
  no-viewport fallbacks are smaller than the desktop), so a
  viewport-less session fills the desktop at any configured size. Keep
  the manager value in sync with the nodes; an explicitly emulated
  session resizes the window by design.
- `servers/selenium_session_manager.py` (service
  `selenium-session-manager`, via
  `Dockerfile.selenium-session-manager`): sessions open via
  the Grid REST API (`/wd/hub/session`) with an optional
  `pyscraper:node` stereotype; the window is maximized
  (`POST /session/{id}/window/maximize`) before the optional URL
  navigation so noVNC shows a full window. Maximize is best effort: a
  rejecting driver only leaves a warning in the manager log and the
  session continues unmaximized. A failed navigation still aborts the
  open with a compensating close; close deletes the
  Grid session. Grid
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
- Request/response field names: the browser target is `browser` (renamed
  from `target` in v2.0.0; `target` is no longer accepted). Both managers
  echo the request `node` in list/open responses.
- Payload validation errors
  are `422` with Starlette's default `{"detail": ...}` shape (unknown
  browsers, blank or unknown fields, malformed JSON).
  Error detail messages are returned verbatim (raw backend errors
  included): the console runs on a closed compose network with trusted
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
  method). Both managers serve auto-generated `/openapi.json` + `/docs`.
- State files live in `SESSION_STATE_DIR` (`/data/sessions`, backed by
  the `session-states` compose volume shared with the host). The id
  resource is the supported interface: `GET /api/playwright/states`
  lists `{"states": [{"id": ...}]}` (only regular `.json` stems matching
  `^[a-z0-9-]+$`, at most 63 chars), `PUT
  /api/playwright/states/{id}` `{"session_id": ...}`
  creates/overwrites `{id}.json`, and `DELETE
  /api/playwright/states/{id}` removes it. Ids are resource names, not
  file names: the pattern excludes separators, and the id API manages
  regular files only -- a symlink is rejected (`422`) and excluded from
  the listing, so a link can never redirect a read or write outside the
  state dir. Operations are pinned to a directory FD opened once
  (`O_DIRECTORY | O_NOFOLLOW`), reads use `O_NOFOLLOW` plus an
  `fstat`-based regular-file check, and writes are atomic (sibling temp
  file + `os.replace`) while preserving the existing file mode. A path
  swapped after validation is therefore a hard error, not an escape. Ids
  are validated verbatim (no whitespace trimming): a padded or
  newline-bearing id is `422`. Loading a missing id is `404`; a state
  file whose JSON top level is not an object is `422`.
- **Curated selection is a UI property, not an API one.** The UI can
  only load/save the ids listed in the target's
  `storage_state.states`. The API accepts any canonical id: `state_id`
  on open and `PUT /api/playwright/states/{id}` are not
  registry-restricted. This compatibility allowance is intentionally
  narrower than the UI, and adding ids that are not in the registry is
  discouraged.
- `storage_state.states[].id` must be unique across targets because they
  share `SESSION_STATE_DIR`; this only prevents duplicate configuration
  entries. It is **not** an exclusivity or single-writer guarantee:
  different sessions can still PUT the same id.
- The console UI exposes Open/Close + URL, and (for Playwright targets
  with `storage_state`) a state selector plus Save driven by
  `storage_state.states`; the selector is locked while a session is open
  (the id chosen at Open is both the load source and the save target),
  and all of it goes through the same API (`curl` against `/api/...`
  above also works). The view starts fail-closed (Open disabled until the
  first session list succeeds) and keeps Open disabled whenever the
  latest session list fetch failed, so a session opened elsewhere cannot
  be duplicated. A 200 whose body has no `sessions` array (or entries
  without string `id`s) is treated the same as a fetch failure. Open,
  Close and Save are single-flight, a stale
  list response cannot unlock the UI, an Open result that is ambiguous
  (network error, 5xx, or a 2xx without an id) stays fail-closed until a
  list succeeds, and if more than one matching session exists the view
  stays fail-closed rather than guessing which one to act on. The one
  exception is Close for the session this page opened: its id came from
  its own Open response, so it stays available for cleanup even while the
  list is ambiguous.
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
  (default `30`s per Grid REST call; open issues up to 4 calls --
  create, maximize, navigate, compensating close -- so ~`120`s worst
  case, still well under the nginx `150`s above).
- Invalid numeric env values (including non-positive timeouts/ports)
  fall back to defaults with a warning on stderr (managers, Hub); the
  node fails fast with an explicit error. Lifecycle messages
  (listening, node registration) go to stdout; warnings and
  request-processing failures go to stderr, matching uvicorn's defaults
  (startup/errors on stderr, access logs on stdout). `docker logs`
  merges both streams.
- Restart policies: `console` and both session managers use
  `restart: unless-stopped`. The Hub and nodes have none by design --
  nodes self-register with retries and the Hub is stateless, so all
  recover without restarts.
- No authentication (closed compose network, local dev use only). The
  console binds `8080` on all interfaces; on shared hosts bind it to
  localhost or keep it behind a firewall.

### Console configuration

The console is registry-driven and not tied to a specific network setup.
At start `console/entrypoint.sh` reads the target registry, validates it,
and renders the nginx config and the UI's target list from it, and reads
`/etc/resolv.conf` to pick the nginx `resolver`, so the same image adapts
to the environment the container runs in (Docker's embedded DNS, an
internal resolver, etc.). Upstreams are addressed by short service name by
default; set `CONSOLE_UPSTREAM_SUFFIX` when short names do not resolve and
a domain suffix must be appended.

The registry lives at `/etc/console/config.yaml` (YAML; `/etc/console/`
holds only this file, so a directory mount is safe). Override the path with
`CONSOLE_CONFIG_FILE`:

```yaml
ui:
  columns: auto          # auto (responsive) | 1-12 (fixed columns)
  group_by: none         # none | framework | group
  tile_min_width: 560    # tile minimum width in px (integer 160-1920)
  tile_aspect: "16:9"    # 4:3 | 16:9 | 16:10 | 5:4

context_options:         # optional Playwright defaults (root level)
  locale: ja-JP
  timezone_id: Asia/Tokyo
  viewport: { width: 1280, height: 1024 }

targets:
  - id: selenium-chrome              # URL/UI key (unique, ^[a-z0-9-]+$, <=63 chars)
    label: Chrome (Selenium)         # shown in the UI (default: id)
    framework: selenium              # playwright | selenium
    browser: selenium-chrome         # known enum, must match framework
    # node: chromium-profile         # optional node routing
    # group: chrome                  # optional (ui.group_by: group)
    novnc:
      host: selenium-chrome-node     # noVNC upstream (without the suffix; default: id)
      port: 7900                     # default 7900

  - id: playwright-chromium
    label: Chromium (Playwright)
    framework: playwright
    browser: playwright-chromium
    context_options:                 # key-wise override of the root defaults
      viewport: { width: 1440, height: 900 }
    storage_state:                   # presence enables the state selector
      states:
        - id: chromium               # ^[a-z0-9-]+$, <=63, unique across targets
          label: Chromium            # default: id
          url: https://example.com/?q=1   # optional URL prefill
```

The console validates the registry at start (unique ids and
`(framework, browser, node)` tuples, known browser enum, label/host/port
shape, context options, ...) and refuses to start on any problem, printing
the offending target and reason. `framework` selects the session manager
and the `/api/<framework>/` namespace; `browser` is the target passed to it
(and re-validated by the manager). The default registry wires the five
compose browsers; Selenium profile nodes are not enabled by default (see
the example in `console/config.yaml`).

`ui.columns` is `auto` (a responsive grid whose tile minimum width comes
from `ui.tile_min_width`) or an integer 1-12; `ui.group_by` is `none`,
`framework`, or `group` (targets without a group fall back to their
framework); `ui.tile_min_width` is an integer 160-1920 (px, default 560);
`ui.tile_aspect` is one of `4:3`, `16:9`, `16:10`, `5:4` (default `16:9`).
All four are optional. Remote desktops are 5:4/4:3, so 16:9 tiles show side
letterbox bars; the noVNC stream itself always scales to fit.

`context_options` is Playwright-only and optional. Allowed keys: `locale`,
`timezone_id`, `viewport` (`{width, height}` positive integers),
`user_agent`, `color_scheme` (`light`/`dark`/`no-preference`),
`device_scale_factor` (positive number), `has_touch`, `is_mobile`, and
`extra_http_headers` (string-to-string mapping). Root values are merged
into each Playwright target key by key (target wins); nested values are
replaced as a whole (a target `viewport` or `extra_http_headers` does not
merge with the root one). The resolved value is exposed in
`<base>/config.json` and sent to the session manager on open. The console
has no authentication, so `config.json` is public to anyone who can reach
it: never put secrets in `states[].url` or in
`context_options.extra_http_headers` (for example `Authorization` or
`Cookie`). `storage_state` and `proxy` are rejected: persistence and proxy
routing are not context options.

`storage_state` is Playwright-only and optional; **presence enables** it
(booleans and an `enabled` key are rejected). `states[].id` must match
`^[a-z0-9-]+$` with at most 63 chars and be unique across **all** targets
(the state dir is shared); `label` defaults to the id; `url` is an
optional `http(s)` prefill (at most 2048 chars) shown in the view. The
legacy `storage_state.ids: [id, ...]` list is accepted and normalized to
states without labels or URLs.

Environment variables:

| Variable | Default | Purpose |
|----------|---------|---------|
| `CONSOLE_CONFIG_FILE` | `/etc/console/config.yaml` | target registry (YAML) |
| `CONSOLE_BASE_PATH` | empty (root) | serve the console under a path prefix (e.g. `/console`); `/` then `308`-redirects to it |
| `CONSOLE_RESOLVER` | first `nameserver` in `/etc/resolv.conf` | nginx `resolver` |
| `CONSOLE_UPSTREAM_SUFFIX` | empty (short service names) | FQDN suffix appended to the registry noVNC hosts and the session-manager names |
| `CONSOLE_PW_SESSION` | `playwright-session-manager` | `/api/playwright/*` (incl. `states`) |
| `CONSOLE_SE_SESSION` | `selenium-session-manager` | `/api/selenium/*` |

Advanced/test-only overrides (all paths stay inside the container):
`CONSOLE_GENERATE_JQ` (`/usr/share/console/generate.jq`), `CONSOLE_RUN_DIR`
(`/run/console`), `CONSOLE_NGINX_CONF` (`/etc/nginx/conf.d/console.conf`),
and `CONSOLE_RESOLV_CONF` (`/etc/resolv.conf`). The run dir must be
`/[A-Za-z0-9._/-]+` without empty, `.` or `..` segments and is rejected
before anything is created; the config file must hold exactly one YAML
document, which is rejected before `generated.json`, the nginx config, or
`config.json` is written (the debug-level intermediate `source.json` is
written beforehand).

An explicit `CONSOLE_UPSTREAM_SUFFIX` is applied verbatim (for example
`.example.internal`), so a deployment can pin the exact FQDN suffix it
needs. It is never derived from `/etc/resolv.conf` search domains, which
would break short service names on Docker's embedded DNS.
`CONSOLE_PW_SESSION`, `CONSOLE_SE_SESSION`, and registry `novnc.host`
values must match `[A-Za-z0-9._-]+` and be resolvable by the environment's
DNS (underscores are accepted for compose service names, but strict DNS
resolvers may reject them).

The generated files are implementation details:
`/etc/nginx/conf.d/console.conf` (the full server config, replacing the
stock `default.conf`) and `/run/console/config.json` (served at
`<base>/config.json`). The generated server listens on both IPv4 and IPv6
(`listen [::]:80;`) so the image's `localhost` healthcheck also works
where `localhost` resolves to `::1`. The intermediate
`/run/console/source.json`
(yq output) and `/run/console/generated.json` (jq output) are kept for
debugging. When the platform mounts the root filesystem read-only, mount
writable volumes (e.g. `emptyDir`) at `/etc/nginx/conf.d`,
`/run/console`, `/var/cache/nginx`, and `/var/run`. Changing the registry
requires a restart (`docker compose restart console`); nginx is not
reloaded in place.

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
| Console | `temeteke/pyscraper-console` | `ghcr.io/temeteke/pyscraper-console` |
| Playwright session manager | `temeteke/pyscraper-playwright-session-manager` | `ghcr.io/temeteke/pyscraper-playwright-session-manager` |
| Selenium session manager | `temeteke/pyscraper-selenium-session-manager` | `ghcr.io/temeteke/pyscraper-selenium-session-manager` |

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
  needed for public pulls. Every service published to a registry
  (including the console and both session managers) declares `image:`
  plus a `build:` section for local development, so
  `docker compose pull` followed by `docker compose up -d` (without
  `--build`) runs all of them with no local build; `docker compose build`
  rebuilds (and retags) the same names locally.
- The WebKit image is `linux/amd64` only (Playwright WebKit has no official
  arm64 Linux support); `compose.yaml` pins `platform: linux/amd64`
  for that service.

```sh
# Fastest: pull published images, no local build
docker compose pull
docker compose up -d
```

### Build locally

```sh
docker compose build
docker compose up
```
