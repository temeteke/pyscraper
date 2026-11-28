# Kubernetes Guide

The Helm chart in `charts/pyscraper` deploys the whole Grid/Hub stack:

- Selenium Grid hub and Selenium browser nodes
- Playwright hub and Playwright browser nodes
- Playwright and Selenium session managers
- The browser console

There is no separate Selenium chart and no chart dependency. Selenium and
Playwright nodes are defined together in the `nodes` map.

## Versions

The chart source has a base `version` / `appVersion` in `Chart.yaml`, but the
release workflow overrides both with the pushed tag:

```sh
helm package charts/pyscraper -d dist \
  --version "$VERSION" --app-version "$VERSION"
```

Images are grouped by component: `images.console`, `images.playwright.*`, and
`images.selenium.*`. Every image entry has `registry`, `repository`, and
`tag`. An empty tag on a pyscraper image uses the packaged `appVersion`, so
those images follow a `vX.Y.Z` release. Upstream Selenium images have explicit
independent tags (for example `4.52.0`).

The source `Chart.yaml` therefore stays at the previous release version; the
tag is the release version. The release workflow validates the packaged chart
before building images.

## Install

After the chart is published to GHCR:

```sh
helm install pyscraper oci://ghcr.io/temeteke/charts/pyscraper \
  --version <version> \
  --namespace pyscraper --create-namespace
```

If the GHCR package is private, run `helm registry login ghcr.io` first. The
chart uses fixed resource names for the hub, session managers, and nodes, so
install one release per namespace. Do not install a second release with the
same fixed names in the same namespace.

Installing directly from the source tree (`helm install pyscraper
./charts/pyscraper`) resolves empty pyscraper image tags to `Chart.yaml`
`appVersion`, which is the previous release. The source templates may be newer
than those images. Use a packaged chart, or set the pyscraper `images.*.tag`
values explicitly, when testing unreleased chart changes.

## Common values

The default values deploy the default Selenium and Playwright nodes, both
hubs, both session managers, and the console. No values are required for a
first install. The console remains a ClusterIP Service until Ingress is
enabled.

A small production-oriented example:

```yaml
global:
  clusterDomain: cluster.local
  timezone: Asia/Tokyo
  imagePullSecrets:
    - name: ghcr-pull

console:
  ingress:
    enabled: true
    className: nginx
    host: pyscraper.example.com
    path: /
    pathType: Prefix
    tls:
      - secretName: pyscraper-tls
        hosts:
          - pyscraper.example.com
  contextOptions:
    locale: en-US
    timezone_id: Asia/Tokyo

nodes:
  selenium-chrome:
    resources:
      requests:
        cpu: 500m
        memory: 1Gi
      limits:
        cpu: "2"
        memory: 4Gi
```

The console has no built-in authentication; add an auth proxy or
NetworkPolicy in front of the Ingress.

Keep the default nodes unless you need persistent Selenium profiles. To
enable a profile node, use an fsGroup-capable storage class; profile nodes
run one replica and one session:

```yaml
nodes:
  selenium-chrome-profile:
    enabled: true
    persistence:
      storageClassName: standard
  selenium-firefox-profile:
    enabled: true
    persistence:
      storageClassName: standard
```

Playwright storage states are opt-in:

```yaml
playwright:
  sessionManager:
    persistence:
      enabled: true
      size: 1Gi
      storageClassName: standard
```

Proxy, language, and per-node options are described in their sections.
`console.upstreamSuffix` and `console.resolver` are normally left empty.

## Browser nodes

`nodes` is the single place to choose which browsers run. The map key is the
node identity: it is used as the Deployment/Service name, the PVC base name,
and the console target id. Use a DNS-1035 label for the key; the chart does not
check the format or length, so Kubernetes reports invalid names when the
release is applied.

The default keys are `selenium-chrome`, `selenium-chrome-profile`,
`selenium-firefox`, `selenium-firefox-profile`, `playwright-chromium`,
`playwright-firefox`, and `playwright-webkit`.

```yaml
nodes:
  selenium-firefox:
    framework: selenium
    browser: firefox
    node: default
    persistence:
      enabled: false

  selenium-firefox-user-a:
    framework: selenium
    browser: firefox
    node: user-a
    maxSessions: 1
    persistence:
      enabled: true
      size: 16Gi
      mountPath: /tmp/firefox-user-a
    podSecurityContext:
      fsGroup: 1201
      fsGroupChangePolicy: OnRootMismatch

  playwright-chromium:
    framework: playwright
    browser: chromium
```

Fields:

| Field | Meaning |
|---|---|
| `enabled` | Deploy this node (default true) |
| `framework` | `selenium` or `playwright` |
| `browser` | Selenium: `chrome` / `firefox`; Playwright: `chromium` / `firefox` / `webkit` |
| `node` | Selenium `pyscraper:node`; default the map key; `^[A-Za-z0-9._-]+$` |
| `maxSessions` | Selenium sessions per node; default 4. Persistent nodes require 1 |
| `screen` | Xvfb size; default 1280x720 |
| `shm.sizeLimit` | `/dev/shm` size; default 2Gi |
| `readinessProbe.initialDelaySeconds` / `timeoutSeconds` | Playwright only; default 60 seconds (the stock Firefox/WebKit nodes set 90/120) and 3 seconds |
| `registration.intervalSeconds` | Playwright only; default 10 seconds; keep `playwright.hub.registration.nodeTTLSeconds` at least 3x this value |
| `persistence.enabled` | Selenium only: create a PVC; the node must use `maxSessions: 1` and set `podSecurityContext.fsGroup` |
| `persistence.mountPath` | Selenium profile path; default `/tmp/<key>-profile` |
| `persistence.size` / `accessMode` / `storageClassName` | PVC settings |
| `persistence.keep` | Keep the PVC on uninstall (default true) |
| `nodeSelector` / `resources` | Standard pod settings |
| `podSecurityContext` / `securityContext` | Optional pod/container security context. Persistent Selenium nodes require `podSecurityContext.fsGroup` (1201 for the stock images). |
| `console` | Console target overrides (`label`, `group`, `contextOptions`, `storageState`); `group` defaults to the browser, `contextOptions`/`storageState` are Playwright-only, and `storageState` is a boolean |

Browser nodes and hubs are not scaled with `replicas`; they run with one
replica. Add another node for capacity, and use `enabled: false` to remove a
node. With the console enabled, each additional Selenium node also needs a
distinct `node` value; otherwise the routing tuple is a duplicate and the
chart fails rendering.

The chart rejects reserved chart resource names (`console`, `selenium-hub`,
`playwright-hub`, `selenium-session-manager`, `playwright-session-manager`,
`playwright-session-states`) and duplicate `(framework, browser, node)`
routing tuples when the console is enabled. Key format/length, console
labels/groups, and context option values are not checked by Helm; Kubernetes
rejects invalid resource names. The console validates its registry at startup;
the session managers validate browser/node/context options when handling a
request. The console has no built-in authentication. The console targets the
node's Service, so multiple Pods behind one target would make noVNC and Grid
routing inconsistent.

### Selenium profiles

The stock `selenium-chrome-profile` and `selenium-firefox-profile` nodes are
disabled by default. Enable them when a persistent profile is needed.

When a Selenium node has `persistence.enabled: true`, the chart mounts the PVC
and adds the profile argument to the node stereotype automatically:

- Chrome: `--user-data-dir=<mountPath>`
- Firefox: `-profile <mountPath>`

The console routes by `pyscraper:node`, so console sessions use the PVC. When
connecting a pyscraper client to a chart-managed persistent node, do **not**
also set `profile=` / `user_data_dir=` / `SELENIUM_CHROME_PROFILE` /
`SELENIUM_FIREFOX_PROFILE`; the node already supplies it. Use separate nodes
for separate profiles.

Profile arguments are applied through the node stereotype; Grid merges them
into the session capabilities (verified with the stock 4.52.0 images). The
console session manager intentionally rejects profile arguments and relies on
the node stereotype.

Persistent Selenium nodes require a storage class that supports `fsGroup`.
The chart sets `podSecurityContext.fsGroup: 1201` and
`fsGroupChangePolicy: OnRootMismatch` on the default profile nodes. `1201` is
the GID of the stock image's `seluser`; override it for a custom image.
`hostPath` / local-path storage ignores `fsGroup`, so persistent profiles are
not supported there. There is no Helm root init container fallback; Compose
uses a one-shot `profile-volumes-init` instead.

### Playwright

Playwright browser nodes are stateless. Persistence is `storage_state` JSON,
stored by the Playwright session manager, not a browser profile PVC:

```yaml
playwright:
  sessionManager:
    screen:
      width: 1280
      height: 720
    persistence:
      enabled: true
      size: 1Gi
```

The Playwright session manager's `screen` size is used for Firefox/WebKit
default viewport calculations. Keep it equal to the `screen` size of every
Playwright node; per-node overrides that do not match the manager are not
synchronized automatically.

The console automatically creates one `storage_state` candidate per
Playwright node unless `console.storageState: false` is set on that node.
With the default `playwright.sessionManager.persistence.enabled: false`,
saved states live in the session manager container and are lost on Pod
restart.

A pyscraper client's `node=` is the map key (for example
`playwright-chromium`), not the browser name. Compose uses the shorter
`chromium` / `firefox` / `webkit` names.

## Hubs and session managers

```yaml
selenium:
  hub:
    enabled: true
  sessionManager:
    enabled: true
playwright:
  hub:
    enabled: true
  sessionManager:
    enabled: true
```

Disabling a hub while its nodes are still enabled fails at render time. Hubs
run at one replica because Grid/Hub session state is in memory. Session
managers and browser nodes are also deployed with one replica and
`strategy: Recreate`. Playwright nodes re-register every
`registration.intervalSeconds` (default 10); the Hub prunes them after
`playwright.hub.registration.nodeTTLSeconds` (default 30), so keep the TTL at
least 3x the interval. Both hubs accept
`readinessProbe.initialDelaySeconds` / `timeoutSeconds`; defaults are 5/5
(Selenium) and 5/3 (Playwright).

If you disable a hub but keep its session manager, point `hubUrl` / `hubWs`
at an external hub or disable the manager. Otherwise the manager starts but
sessions fail when opened.

If you disable a session manager, also disable its nodes or the console;
otherwise console target API calls fail.

The session managers listen on 8000 inside their Pods. Their Services expose
port 80, so the console uses `<service>:80`; the container port is an
implementation detail.

### Browser language

Language is not set by default. The Selenium session-manager maps are keyed by
the Selenium node value (`pyscraper:node`), not the chart node key. To use the
same language for every console browser:

```yaml
selenium:
  sessionManager:
    chromeOptions:
      default:
        args:
          - --lang=en-US
      chrome-profile:
        args:
          - --lang=en-US
    firefoxOptions:
      default:
        prefs:
          intl.accept_languages: en-US
      firefox-profile:
        prefs:
          intl.accept_languages: en-US

console:
  contextOptions:
    locale: en-US
```

The `chrome-profile` / `firefox-profile` entries apply when those stock
profile nodes are enabled. To vary the language by node, change the entry for
that `pyscraper:node` value. For Playwright, a per-node
`console.contextOptions.locale` overrides the root locale.

These settings apply to sessions opened through the console/session manager.
A `WebPage*` client connects to Grid directly and must set its own language
(`language=` for Selenium Firefox and Chrome,
`context_options={"locale": ...}` for Playwright).

## Console

The console is deployed with the chart and can be exposed through an optional
Ingress. It has **no built-in authentication**; when enabled, put it behind a
trusted network only, and add TLS / NetworkPolicy (or your own auth proxy) as
appropriate:

```yaml
console:
  enabled: true
  ingress:
    enabled: true
    host: pyscraper.example.com
    path: /
    tls: []
```

`ingress.host` is optional; when empty the rule matches all hosts. Set it for
a host-based Ingress. `ingress.path` defaults to `/`. The chart passes host,
path, and `pathType` through without validation; Kubernetes applies the
Ingress API rules. `console.basePath` is empty or `/segment[/segment...]`.

The target list is generated from `nodes`; per-node `console.label` and
`console.group` override the generated target fields. The target id is the
map key. `console.contextOptions` adds Playwright target overrides, merged
shallowly with the root context options (nested values are replaced as a
whole). The console checks a `viewport` override: only `width` and `height`
are allowed, both positive integers. Each target uses the node's Service name
for noVNC and the Selenium `pyscraper:node` or Playwright node name for
routing.

The console requires at least one enabled node. If every node is disabled,
also set `console.enabled: false`; otherwise the console exits at startup
because its target list is empty.

`console.ui` maps directly to the console's native `ui` block and keeps its
snake_case keys (`group_by`, `tile_min_width`, `tile_aspect`). Unset keys use
the console defaults; the default `group_by` is `none`. Nested
`console.contextOptions` keys use Playwright's native names (for example
`timezone_id` and `color_scheme`).

`nodes.<key>.console.storageState` is a boolean. It defaults to `true`, which
creates one state per Playwright target using the target id and label; `false`
disables the state selector for that node. Custom state ids, labels, and URL
prefill are not exposed by the chart.

To serve the console under a path prefix, set both values consistently:

```yaml
console:
  basePath: /console
  ingress:
    path: /console
```

`console.ui`, `console.contextOptions`, and per-node `console.contextOptions`
map to the console configuration. The session-manager upstreams use the fixed
Service names `playwright-session-manager` and `selenium-session-manager` on
port 80; the containers listen on 8000.

### Console DNS and upstreams

The console nginx config uses variables for the session-manager and noVNC
upstreams. nginx resolves those variables through its own `resolver`, not the
container's libc resolver, so it does not apply the `search` domains from
`/etc/resolv.conf`.

The entrypoint uses the first `nameserver` in `/etc/resolv.conf` (or
`console.resolver`). The chart sets `CONSOLE_UPSTREAM_SUFFIX` to
`.<namespace>.svc.<global.clusterDomain>` so the generated names are FQDNs:

```nginx
set $pw_sessions playwright-session-manager.pyscraper.svc.cluster.local;
set $novnc_node selenium-chrome.pyscraper.svc.cluster.local:7900;
```

`console.upstreamSuffix` and `console.resolver` are advanced overrides; leave
them empty for a standard cluster. Set `global.clusterDomain` when the cluster
domain is not `cluster.local`, or `console.upstreamSuffix` when DNS uses a
different name shape. Include the leading dot in `console.upstreamSuffix`.

If the console UI loads but `/api/*` or `/vnc/*` fails, check:

```sh
kubectl exec deploy/console -- env | grep CONSOLE
kubectl exec deploy/console -- cat /etc/nginx/conf.d/console.conf
kubectl logs deploy/console
```

## Global settings

`global.clusterDomain` defaults to `cluster.local` and is used for the
console's Service FQDN suffix. Set it to the cluster's DNS domain (without a
leading dot) when it is not `cluster.local`.

`global.timezone` is empty by default: no `TZ` env is emitted and the
container image default applies. Set a valid IANA timezone name to apply one
timezone to all application containers. `global.imagePullSecrets` is applied
to every Pod.

## Proxy

Proxy is configured directly in values; no ConfigMap is required:

```yaml
global:
  proxy:
    httpProxy: http://proxy.example:3128
    httpsProxy: http://proxy.example:3128
    noProxy: localhost,127.0.0.1,.svc,.cluster.local
```

All three are optional, but setting any proxy value requires `httpProxy` and
`httpsProxy`; `noProxy` may be empty. The chart renders six proxy env vars on
Selenium and Playwright browser nodes. The Selenium session manager receives
`FIXED_CHROME_EGRESS` from `httpsProxy`; the hubs, console, and Playwright
session manager do not get proxy env.

`selenium.sessionManager.chromeOptions` and `firefoxOptions` are maps keyed by
the Selenium node value. To proxy Chrome, add a `default` entry (and a
`chrome-profile` entry when that node is enabled):

```yaml
selenium:
  sessionManager:
    chromeOptions:
      default:
        args:
          - --proxy-server=$(FIXED_CHROME_EGRESS)
```

Grid control traffic bypasses proxy environment variables.

Proxy URLs are rendered into the Deployment env and are visible to anyone who
can read it. Do not put credentials in values; authenticated proxy support is
not included in the chart yet. The console's Selenium session manager passes
Chrome launch options and Firefox prefs, but does not configure a browser
proxy for them. Add `--proxy-server=...` to `chromeOptions`; for Firefox, set
the relevant `network.proxy.*` prefs in `firefoxOptions` or use a pyscraper
client.

## Persistence and retention

Selenium profile PVCs and the Playwright session-state PVC are kept on
`helm uninstall` by default (`persistence.keep: true`). Delete them manually
when you want to discard the data. Set `keep: false` to let Helm delete the
PVC instead. A retained PVC can conflict with a later reinstall; delete it or
reuse the same release intentionally.

`persistence.storageClassName: ""` omits the field and uses the cluster
default class. Set an explicit class when needed. Docker Compose mounts
`chrome-profile`, `firefox-profile`, and `session-states` volumes by default
for local development. The Helm chart keeps profile and session-state PVCs
opt-in because they need a storage class and, for Selenium profiles, fsGroup
support.

## Images and registries

The default registry is Docker Hub. The pyscraper images are also published to
GHCR by the release workflow. Images are grouped by component (`console`,
`playwright`, `selenium`). Each image entry has `registry` (the registry host;
empty means Docker Hub), `repository` (includes the namespace), and `tag`.

For the GHCR copies, set `registry: ghcr.io` on each pyscraper image
(`images.console`, the `images.playwright.*` entries, and
`images.selenium.sessionManager`). The repositories already contain
`temeteke/`, so do not put the username in the registry.

Mirrors are configured per image. For example, a Selenium mirror at
`ghcr.io/temeteke/selenium/hub` uses:

```yaml
images:
  selenium:
    hub:
      registry: ghcr.io
      repository: temeteke/selenium/hub
      tag: "4.52.0"
```

Use the same shape for `images.selenium.chrome` and `.firefox`.
`imagePullSecrets` can be set under `global` for a private mirror.

## Architecture and security

Selenium and Playwright hub/browser images are multi-arch except WebKit, which
is amd64-only and has a default `kubernetes.io/arch: amd64` node selector.
Other nodes have an empty selector and can run on arm64.

Chrome may need a seccomp profile on clusters that default to
`RuntimeDefault`. Expose `securityContext` / `podSecurityContext` per node and
set a scoped profile (or an equivalent policy) when Chrome sessions fail with
`DevToolsActivePort file doesn't exist`. Docker Compose uses
`seccomp:unconfined` for its local Chrome nodes; the Helm chart leaves seccomp
unset by default and expects a scoped profile in production. Persistent
Selenium profiles rely on `podSecurityContext.fsGroup` (1201 for the stock
images) instead of a Helm root init container, so they work in restricted Pod
Security namespaces when the storage class honors `fsGroup`. `hostPath` /
local-path storage does not.

## Render-time validation

`templates/validate.yaml` is intentionally small. It fails rendering only for
values that would otherwise break silently:

- reserved node names
- duplicate `(framework, browser, node)` console routing tuples
- a hub disabled while nodes of that framework are enabled
- `framework` / `browser` enums, and framework-specific fields
  (`console.contextOptions` / `console.storageState` only for Playwright;
  `node` and `persistence.enabled: true` only for Selenium)
- persistent Selenium nodes: `maxSessions: 1` and a positive
  `podSecurityContext.fsGroup`
- positive `maxSessions` and Selenium `screen.width/height` (0 would silently
  fall back to a default)
- boolean `console.storageState`
- `global.proxy`: setting any proxy value requires `httpProxy` and `httpsProxy`

It produces no Kubernetes resources; it is a render-time guard.

### Validation policy

Everything else is left to the component that consumes it. DNS label format
and length, image fields, Ingress host/path/pathType, probe and registration
numbers, hub URLs, and `chromeOptions` / `firefoxOptions` shape surface as
apply, Pod, startup, or first-session errors. Console labels/groups and
`contextOptions` are passed through; the console validates context options
when it starts. Null sub-maps are normalized only to keep template rendering
safe.

## Chart development

These commands require Helm; CI pins Helm `v4.3.2`.

```sh
helm lint charts/pyscraper
helm template pyscraper charts/pyscraper -n pyscraper > /tmp/rendered.yaml
sh scripts/check-console-config.sh /tmp/rendered.yaml
helm package charts/pyscraper -d /tmp/dist \
  --version 0.0.0 --app-version 0.0.0
```

`scripts/check-console-config.sh` requires `yq` and `jq`. Helm templates are
excluded from the pre-commit `check-yaml` hook because they are Go templates.
PR CI intentionally runs only `helm lint`, `helm package`, `helm template`,
and the console config check; it does not maintain a large expected-failure
matrix. Render-time validation belongs in `templates/validate.yaml`.

## Release

Releases are tag-driven. A `vX.Y.Z` tag push runs
`.github/workflows/release.yml`:

1. `validate_release` packages the chart with the tag version, validates the
   packaged Chart.yaml and image tags, and runs the console config check when
   the console is enabled — all before any image build.
2. Image builds publish only the immutable `X.Y.Z` tags.
3. `move_channels` aliases `latest` / `X.Y` after all images publish.
4. `publish_charts` pushes the chart to GHCR.

The release commit must add a `## [X.Y.Z]` section to `CHANGELOG.md`; the
`validate_release` job fails without it. No manual chart version bump is
needed: the tag overrides `Chart.yaml`. If Selenium images change, update the
`tag` of `images.selenium.hub`, `.chrome`, and `.firefox` in the release
commit.

If only the chart job fails, use **Re-run failed jobs** to avoid rebuilding
images. Published chart versions are immutable; fix a chart by cutting the
next patch tag. After the first push, set the GHCR chart package to public if
anonymous pulls are required.
