# Changelog

All notable changes to this project are documented in this file. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Sections are numbered by version without dates; the release date is the Git
tag.

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
