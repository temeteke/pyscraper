#!/bin/sh
# Render the console nginx config and UI target list from the console
# configuration at container start, so the same image adapts to its runtime
# environment.
#
# Pipeline:
#   config.yaml --yq--> JSON --jq(generate.jq)--> {nginx, config}
#     -> /etc/nginx/conf.d/console.conf   (nginx config)
#     -> /run/console/config.json         (served at <base>/config.json)
#   nginx -t (fail fast) -> exec nginx
#
# Only the config file is user-facing; the image-owned generate.jq and the
# generated files are implementation details. All paths are overridable so
# tests can run the real logic against a temporary directory.
set -eu

: "${CONSOLE_CONFIG_FILE:=/etc/console/config.yaml}"
: "${CONSOLE_GENERATE_JQ:=/usr/share/console/generate.jq}"
: "${CONSOLE_RUN_DIR:=/run/console}"
: "${CONSOLE_NGINX_CONF:=/etc/nginx/conf.d/console.conf}"
: "${CONSOLE_RESOLV_CONF:=/etc/resolv.conf}"
export CONSOLE_CONFIG_FILE CONSOLE_GENERATE_JQ CONSOLE_RUN_DIR
export CONSOLE_NGINX_CONF CONSOLE_RESOLV_CONF

# Resolver: explicit CONSOLE_RESOLVER, else the first nameserver.
if [ -z "${CONSOLE_RESOLVER:-}" ]; then
    if [ ! -r "$CONSOLE_RESOLV_CONF" ]; then
        echo "[console] cannot read $CONSOLE_RESOLV_CONF" \
            "(set CONSOLE_RESOLVER or CONSOLE_RESOLV_CONF)" >&2
        exit 1
    fi
    CONSOLE_RESOLVER=$(awk '/^[[:space:]]*nameserver/ {print $2; exit}' "$CONSOLE_RESOLV_CONF")
fi
: "${CONSOLE_RESOLVER:=127.0.0.1}"
export CONSOLE_RESOLVER

# Upstream FQDN suffix. Explicit only: short service names are resolved by
# the environment's DNS (e.g. Docker's embedded 127.0.0.11); deriving a
# suffix from /etc/resolv.conf search would break them.
: "${CONSOLE_UPSTREAM_SUFFIX:=}"
export CONSOLE_UPSTREAM_SUFFIX

# Session-manager upstreams (override to match your Services).
: "${CONSOLE_PW_SESSION:=playwright-session-manager}"
: "${CONSOLE_SE_SESSION:=selenium-session-manager}"
export CONSOLE_PW_SESSION CONSOLE_SE_SESSION

# Base path: empty (root) or /segment[/segment...]. Normalize a trailing
# slash, then reject anything else (dots, double slashes, metacharacters).
: "${CONSOLE_BASE_PATH:=}"
CONSOLE_BASE_PATH=${CONSOLE_BASE_PATH%/}
if ! printf '%s\n' "$CONSOLE_BASE_PATH" | grep -qE '^(/[A-Za-z0-9-]+)*$'; then
    echo "[console] invalid CONSOLE_BASE_PATH: ${CONSOLE_BASE_PATH:-<empty>}" \
        "(want empty or /segment[/segment...])" >&2
    exit 1
fi
export CONSOLE_BASE_PATH

# Run dir: the same rule generate.jq enforces (/[A-Za-z0-9._/-]+), checked
# in the shell before mkdir so an invalid value never creates anything.
# (command substitution strips trailing newlines, so a value with a newline
# is caught by the inequality before grep matches one line at a time.)
cleaned=$(printf '%s' "$CONSOLE_RUN_DIR" | tr -d '\n')
if [ "$cleaned" != "$CONSOLE_RUN_DIR" ] \
    || ! printf '%s\n' "$cleaned" | LC_ALL=C grep -qE '^/[A-Za-z0-9._/-]+$'; then
    printf '[console] invalid CONSOLE_RUN_DIR: %s (want /[A-Za-z0-9._/-]+, no empty, %s segments)\n' \
        "$CONSOLE_RUN_DIR" "'.' or '..'" >&2
    exit 1
fi
if printf '%s\n' "$CONSOLE_RUN_DIR" | LC_ALL=C grep -qE '//|(^|/)\.\.?(/|$)'; then
    printf "[console] invalid CONSOLE_RUN_DIR: %s (no empty, '.' or '..' segments)\n" \
        "$CONSOLE_RUN_DIR" >&2
    exit 1
fi

mkdir -p "$CONSOLE_RUN_DIR"

# Config -> JSON. The intermediate file makes a yq failure abort the script
# (set -e) instead of feeding jq empty input.
yq -o=json '.' "$CONSOLE_CONFIG_FILE" > "$CONSOLE_RUN_DIR/source.json"

# Exactly one YAML document: yq emits a JSON stream for multi-document input
# and jq -f would process each value separately, so two documents would
# concatenate two nginx configs and two JSON objects.
docs=$(jq -s 'length' "$CONSOLE_RUN_DIR/source.json")
if [ "$docs" != "1" ]; then
    echo "[console] invalid $CONSOLE_CONFIG_FILE: expected a single YAML document (got $docs)" >&2
    exit 1
fi

# Validate and render. jq exits non-zero with the first problem on stderr.
# jq strings do not expand $host/$1, so no envsubst is needed (or wanted).
jq -e -f "$CONSOLE_GENERATE_JQ" \
    --arg resolver "$CONSOLE_RESOLVER" \
    --arg base "$CONSOLE_BASE_PATH" \
    --arg suffix "$CONSOLE_UPSTREAM_SUFFIX" \
    --arg pw "$CONSOLE_PW_SESSION" \
    --arg se "$CONSOLE_SE_SESSION" \
    --arg rundir "$CONSOLE_RUN_DIR" \
    "$CONSOLE_RUN_DIR/source.json" > "$CONSOLE_RUN_DIR/generated.json"
jq -r '.nginx'  "$CONSOLE_RUN_DIR/generated.json" > "$CONSOLE_NGINX_CONF"
jq -c '.config' "$CONSOLE_RUN_DIR/generated.json" > "$CONSOLE_RUN_DIR/config.json"

nginx -t
exec nginx -g 'daemon off;'
