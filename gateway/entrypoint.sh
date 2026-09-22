#!/bin/sh
# Render the gateway nginx config and UI endpoint list from the endpoint
# registry at container start, so the same image adapts to its runtime
# environment.
#
# Pipeline:
#   registry.yaml --yq--> JSON --jq(generate.jq)--> {nginx, endpoints}
#     -> /etc/nginx/conf.d/gateway.conf   (nginx config)
#     -> /run/gateway/endpoints.json      (served at <base>/api/endpoints)
#   nginx -t (fail fast) -> exec nginx
#
# Only the registry is user-facing; the image-owned generate.jq and the
# generated files are implementation details. All paths are overridable so
# tests can run the real logic against a temporary directory.
set -eu

: "${GATEWAY_ENDPOINTS_FILE:=/etc/gateway/endpoints.yaml}"
: "${GATEWAY_GENERATE_JQ:=/usr/share/gateway/generate.jq}"
: "${GATEWAY_RUN_DIR:=/run/gateway}"
: "${GATEWAY_NGINX_CONF:=/etc/nginx/conf.d/gateway.conf}"
: "${GATEWAY_RESOLV_CONF:=/etc/resolv.conf}"
export GATEWAY_ENDPOINTS_FILE GATEWAY_GENERATE_JQ GATEWAY_RUN_DIR
export GATEWAY_NGINX_CONF GATEWAY_RESOLV_CONF

# Resolver: explicit GATEWAY_RESOLVER, else the first nameserver.
if [ -z "${GATEWAY_RESOLVER:-}" ]; then
    GATEWAY_RESOLVER=$(awk '/^[[:space:]]*nameserver/ {print $2; exit}' "$GATEWAY_RESOLV_CONF")
fi
: "${GATEWAY_RESOLVER:=127.0.0.1}"
export GATEWAY_RESOLVER

# Upstream FQDN suffix. Explicit only: short service names are resolved by
# the environment's DNS (e.g. Docker's embedded 127.0.0.11); deriving a
# suffix from /etc/resolv.conf search would break them.
: "${GATEWAY_UPSTREAM_SUFFIX:=}"
export GATEWAY_UPSTREAM_SUFFIX

# Session-manager upstreams (override to match your Services).
: "${GATEWAY_PW_SESSION:=playwright-session-manager}"
: "${GATEWAY_SE_SESSION:=selenium-session-manager}"
export GATEWAY_PW_SESSION GATEWAY_SE_SESSION

# Base path: empty (root) or /segment[/segment...]. Normalize a trailing
# slash, then reject anything else (dots, double slashes, metacharacters).
: "${GATEWAY_BASE_PATH:=}"
GATEWAY_BASE_PATH=${GATEWAY_BASE_PATH%/}
if ! printf '%s\n' "$GATEWAY_BASE_PATH" | grep -qE '^(/[A-Za-z0-9-]+)*$'; then
    echo "[gateway] invalid GATEWAY_BASE_PATH: ${GATEWAY_BASE_PATH:-<empty>}" \
        "(want empty or /segment[/segment...])" >&2
    exit 1
fi
export GATEWAY_BASE_PATH

mkdir -p "$GATEWAY_RUN_DIR"

# Registry -> JSON. The intermediate file makes a yq failure abort the script
# (set -e) instead of feeding jq empty input.
yq -o=json '.' "$GATEWAY_ENDPOINTS_FILE" > "$GATEWAY_RUN_DIR/source.json"

# Validate and render. jq exits non-zero with the first problem on stderr.
# jq strings do not expand $host/$1, so no envsubst is needed (or wanted).
jq -e -f "$GATEWAY_GENERATE_JQ" \
    --arg resolver "$GATEWAY_RESOLVER" \
    --arg base "$GATEWAY_BASE_PATH" \
    --arg suffix "$GATEWAY_UPSTREAM_SUFFIX" \
    --arg pw "$GATEWAY_PW_SESSION" \
    --arg se "$GATEWAY_SE_SESSION" \
    --arg rundir "$GATEWAY_RUN_DIR" \
    "$GATEWAY_RUN_DIR/source.json" > "$GATEWAY_RUN_DIR/generated.json"
jq -r '.nginx'     "$GATEWAY_RUN_DIR/generated.json" > "$GATEWAY_NGINX_CONF"
jq -c '.endpoints' "$GATEWAY_RUN_DIR/generated.json" > "$GATEWAY_RUN_DIR/endpoints.json"

nginx -t
exec nginx -g 'daemon off;'
