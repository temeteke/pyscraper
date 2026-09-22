# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Sections are numbered by version without dates; the release date is the Git
tag.

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
