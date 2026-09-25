# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Sections are numbered by version without dates; the release date is the Git
tag.

## [3.0.0]

This is a breaking release; see **Migration** for the changes to apply.
The `temeteke/pyscraper-gateway` image is not updated past 2.x; use
`temeteke/pyscraper-console` instead.

### Breaking changes

#### Gateway renamed to console

- The `gateway/` directory, `Dockerfile.gateway`, the
  `temeteke/pyscraper-gateway` image, and every `GATEWAY_*` environment
  variable are renamed to their `console` equivalents.
- The UI data moved from `GET /api/endpoints` to the static
  `<base>/config.json` (`{"ui", "targets"}`, `Cache-Control: no-store`).
  The endpoint is removed.
- The UI title is `Console`; the tile overview no longer renders an
  `<h1>`.

#### Registry schema (`console/config.yaml`)

- The root key `endpoints:` is renamed to `targets:`; the file is now
  `console/config.yaml` (`CONSOLE_CONFIG_FILE`).
- `ui` (`columns`, `group_by`) and root `context_options` were added.
- `storage_state` is a mapping `{states: [...]}` only; the boolean form
  and the `enabled` key are rejected. Presence enables the state
  selector. The legacy `ids` list is still accepted (temporarily) and
  normalized to states.
- `label` and `novnc` are optional (`label` defaults to the id, `novnc`
  to `{host: id, port: 7900}`).
- `browser` is a closed enum
  (`playwright-chromium|playwright-firefox|playwright-webkit|selenium-chrome|selenium-firefox`)
  and must match `framework`.
- `node` is supported for both frameworks (Hub node name for Playwright,
  `pyscraper:node` for Selenium); `group` was added for
  `ui.group_by: group`.
- `context_options` is Playwright-only and validated against an
  allowlist; `storage_state` and `proxy` are rejected.

#### Session manager API

- The deprecated path-based state APIs were removed:
  `GET /api/playwright/state-files`,
  `POST /api/playwright/sessions/{id}/save`, and the path/dict form of
  the `storage_state` open field. States are loaded with `state_id` and
  saved with `PUT /api/playwright/states/{id}`.
- `POST /api/playwright/sessions` accepts `context_options` (allowlist,
  passed to `new_context`).

#### Development environment

- The `setup.cfg` extra is renamed from `gateway` to `console`
  (`pip install -e ".[console]"`).

### Added

- `ui.columns` (responsive `auto` or 1-12 fixed columns) and
  `ui.group_by` (`none`/`framework`/`group`) for the tile overview.
- `ui.tile_min_width` (tile minimum width in px, 160-1920) and
  `ui.tile_aspect` (`4:3`/`16:9`/`16:10`/`5:4`) so tile geometry is
  configurable instead of hardcoded.
- Configurable noVNC desktop size: `PLAYWRIGHT_SCREEN_WIDTH` /
  `PLAYWRIGHT_SCREEN_HEIGHT` for Playwright nodes (Xvfb, default
  `1280`/`720`) and upstream `SCREEN_WIDTH` / `SCREEN_HEIGHT` for
  Selenium nodes (`1280`/`720` in `compose.yaml`). Browser windows follow
  the desktop (Chromium/Firefox open with the native window size;
  WebKit sizes its window from the session viewport, so a viewport-less
  WebKit session shows the 720p default window).
  Sessions opened without a viewport use the native window size instead
  of Playwright's 720p default, so a headed browser fills the VNC
  desktop. Selenium sessions are maximized via the WebDriver maximize
  command before navigation.
- Root and per-target `context_options` (locale, timezone, viewport,
  user agent, color scheme, device scale factor, touch/mobile,
  extra HTTP headers), merged key by key (nested values are replaced as a
  whole) and applied to Playwright `new_context`.
- Storage-state metadata: `states[].label` and `states[].url`. The view
  prefills the URL from the selected state, supports `?state=<id>`
  deep links, loads noVNC iframes only when a tile becomes visible, and
  asks for confirmation when closing a Playwright session whose selected
  state was never saved.
- `CONSOLE_BASE_PATH` keeps working for any path prefix (e.g.
  `/console`); `/healthz` stays at the root regardless.

### Removed

- `GET /api/endpoints` and the generated `/run/gateway/endpoints.json`.
- The deprecated path-based Playwright state APIs (see above).
- The `storage_state` boolean/`enabled` registry forms.

### Fixed

- Playwright node (firefox): ignore the `-foreground` launch default so
  the numeric `-width` argument is not opened as `http://0.0.5.0/`.
- Playwright session manager: compute the Firefox/WebKit default
  viewports from `PLAYWRIGHT_SCREEN_WIDTH/HEIGHT` (same names as the
  nodes) so viewport-less sessions fill the desktop at any configured
  size (Firefox/WebKit outer windows land exactly on the desktop);
  keep the manager value in sync with the nodes.

### Migration

| v2.1.0 | v3.0.0 |
|--------|--------|
| `gateway/` directory | `console/` |
| `Dockerfile.gateway` | `Dockerfile.console` |
| `temeteke/pyscraper-gateway` | `temeteke/pyscraper-console` |
| `GATEWAY_*` env vars | `CONSOLE_*` (see operations.md) |
| public path `/` (empty base) | `/` by default; `CONSOLE_BASE_PATH=/console` serves under `/console/` (`/` then `308`-redirects) |
| `GET /api/endpoints` -> `{endpoints: [...]}` | static `<base>/config.json` -> `{ui, targets: [...]}` |
| registry `endpoints:` | `targets:` |
| registry file `gateway/endpoints.yaml` | `console/config.yaml` |
| `storage_state: true\|false` / `{enabled, ids}` | `storage_state: {states: [...]}` (presence = enabled; `enabled`/boolean removed, `ids` accepted temporarily) |
| `novnc` required | optional (default `{host: id, port: 7900}`) |
| `label` required | optional (default `id`) |
| UI heading `PyScraper Gateway` | title `Console`, no `<h1>` |
| UI buttons Save / Close | Save / Close (Close now confirms unsaved state) |
| `GET /api/playwright/state-files`, `POST .../save` | `GET /api/playwright/states`, `PUT /api/playwright/states/{id}` |
| `pip install -e ".[gateway]"` | `pip install -e ".[console]"` |

## [2.1.0]

Backward-compatible release: storage states are addressed as id resources,
and the gateway UI selects among curated ids only.

### Added

#### State resources (Playwright session manager)

- `GET /api/playwright/states` -> `{"states": [{"id": ...}]}` lists the
  manageable `SESSION_STATE_DIR/*.json` ids (`.json` stems matching
  `^[a-z0-9-]+$`, at most 63 chars).
- `PUT /api/playwright/states/{id}` `{session_id}` creates/overwrites
  `SESSION_STATE_DIR/{id}.json` from that session;
  `DELETE /api/playwright/states/{id}` removes it. A malformed id is
  `422`, an unknown `session_id` is `404` (PUT), and a missing state is
  `404` (DELETE).
- `POST /api/playwright/sessions` accepts `state_id` to load a state
  (read as a JSON object up front, never re-opened); a state file whose
  top level is not an object is `422`; `state_id` together with
  `storage_state` is `422`. The OpenAPI schema documents the `state_id`
  pattern (`^[a-z0-9-]+$`) and 63-character limit.
- The id API manages regular files only: symlinks are rejected (`422`)
  and excluded from the listing, operations are pinned to a directory FD
  (`O_DIRECTORY | O_NOFOLLOW`) with `O_NOFOLLOW` reads and an
  `fstat`-based regular-file check, and writes are atomic (sibling temp
  file + `os.replace`) while preserving the existing file mode. State
  access cannot be redirected outside `SESSION_STATE_DIR`.

#### Registry

- `storage_state` accepts a mapping `{enabled?, ids?}` in addition to the
  v2.0.0 boolean; `/api/endpoints` always exposes the normalized
  `{enabled, ids}` shape. `ids` are the UI load/save candidates and must
  be unique across endpoints (`SESSION_STATE_DIR` is shared);
  `enabled: false` with a non-empty `ids` list is rejected at start.
- Omitting `storage_state` disables it, but an explicit
  `storage_state: null` is now a type error (previously accepted as
  disabled).

#### Gateway UI

- The Playwright view uses a single state selector (file names and the
  `.json` extension are never shown) plus a Save button: the selector
  lists the configured `storage_state.ids` (plus `(no state)`), Open
  loads the selected id when its file exists and opens fresh otherwise
  (Save can then create it), and Save writes the session to the selected
  id. With no configured ids Save is disabled. The selector is locked
  while a session is open, so the load source and save target stay the
  same id. The view starts fail-closed (Open disabled until the first
  session list succeeds), Open and Close are single-flight, stale list
  responses are ignored, an ambiguous Open result (network error, 5xx, or
  2xx without an id) stays fail-closed until a list succeeds, and an
  ambiguous endpoint state (more than one matching session) stays
  fail-closed rather than guessing.

### Deprecated

- Path-based state APIs are kept for compatibility but deprecated and
  planned for removal: `GET /api/playwright/state-files`, `POST
  /api/playwright/sessions/{id}/save` (`{path}`), and the path/dict form
  of the `storage_state` open field. Use the id resource (`states` /
  `state_id`) instead.
- The curated `storage_state.ids` restriction applies to the UI only.
  The API accepts any canonical id (`state_id`, `PUT
  /api/playwright/states/{id}`) for compatibility, but adding ids outside
  the registry is discouraged and planned for removal together with the
  path-based API.

## [2.0.0]

This is a breaking release; see **Migration** for the changes to apply.

### Breaking changes

#### Playwright v2 model

- Remote Playwright persistence moved from node-owned profiles (Chromium-only
  CDP) to client-owned `storage_state` (`storage_state=` /
  `save_storage_state()`, all browsers).
- The unimplemented `cookies_file` argument and the `node="chromium-profile"`
  Playwright service were removed (unrelated to the Selenium
  `chromium-profile` stereotype, which stays); use `node="chromium"` plus
  `storage_state` instead.
- `context_options` passes locale/timezone/viewport etc. through to context
  creation.
- `PLAYWRIGHT_*_URL` must be `ws://` (legacy CDP `http(s)://` is rejected).
- Playwright nodes are stateless `launch-server` workers: no CDP, no
  node-owned profiles.

#### Gateway is registry-driven

- The gateway renders its nginx config and the UI's endpoint list at container
  start from a single registry file (`gateway/endpoints.yaml`), replacing the
  fixed five-browser config.
- Registry entries are flat, one per exposed browser: `id`, `label`,
  `framework` (`playwright`/`selenium`), `browser`, optional `node`,
  `storage_state`, and `novnc: {host, port}`.
- Public URLs are role-based:
  - `<base>/` -- tile overview
  - `<base>/view/<id>` -- full-size view (was `<base>/view.html?browser=<target>`)
  - `<base>/vnc/<id>/` -- raw noVNC page (was `/<target>/vnc.html`)
  - `<base>/api/endpoints` -- endpoint list for the UI (was `/api/targets`)
- `GATEWAY_BASE_PATH` is supported (serve the gateway under a path prefix).
- The generated nginx config is `/etc/nginx/conf.d/gateway.conf` (the stock
  `default.conf` is removed); the UI data is `/run/gateway/endpoints.json`.
- Environment variables: added `GATEWAY_ENDPOINTS_FILE`, `GATEWAY_BASE_PATH`,
  `GATEWAY_PW_SESSION`, `GATEWAY_SE_SESSION`; removed `GATEWAY_PLAYWRIGHT_*`
  and `GATEWAY_SELENIUM_*` (noVNC hosts now come from the registry).

#### Session manager API

- The request field is `browser`; `target` is no longer accepted (renamed, no
  alias).
- List/open responses no longer include `target`.
- The Playwright state-file listing moved from `GET /api/state-files` to
  `GET /api/playwright/state-files`, and its response key from `files` to
  `state_files`.

### Added

- A configurable endpoint registry (`gateway/endpoints.yaml`) so browsers can
  be added, removed, or renamed without editing the image.
- `GATEWAY_BASE_PATH` to serve the gateway under a path prefix.
- Storage-state load/save controls in the per-browser view (Playwright entries
  with `storage_state: true`).

### Removed

- `gateway/nginx.conf` (replaced by the registry-driven generated config).
- `kubernetes/pyscraper.yml` (the gateway is configured via its registry;
  deployment manifests are environment-specific).

### Migration

| v1.x | v2.0.0 |
|------|--------|
| `gateway/nginx.conf` (mounted) | registry `gateway/endpoints.yaml` + generated config |
| `<base>/view.html?browser=<target>` | `<base>/view/<id>` |
| `/<target>/vnc.html` | `<base>/vnc/<id>/` |
| `GET /api/targets` | `GET /api/endpoints` |
| `GATEWAY_PLAYWRIGHT_*`, `GATEWAY_SELENIUM_*` | registry `novnc.host` per entry |
| `POST .../sessions {"target": ...}` | `POST .../sessions {"browser": ...}` |
| `GET /api/state-files` -> `{"files": [...]}` | `GET /api/playwright/state-files` -> `{"state_files": [...]}` |
| Playwright node-owned profiles / CDP | client-owned `storage_state` |
