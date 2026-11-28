#!/bin/sh
# Validate the rendered console ConfigMap with the console's own generator.
#
# Usage: check-console-config.sh <rendered-manifest.yaml>
#
# The caller must install yq and jq and run this from the repository (or make
# console/generate.jq available); the script resolves the repository root
# relative to its own location.
set -eu

rendered="${1:?usage: check-console-config.sh <rendered-manifest.yaml>}"
command -v yq >/dev/null 2>&1 || {
    echo "check-console-config: yq not found" >&2
    exit 1
}
command -v jq >/dev/null 2>&1 || {
    echo "check-console-config: jq not found" >&2
    exit 1
}

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

yq -o=json \
    'select(.kind == "ConfigMap" and .metadata.name == "console") | .data["config.yaml"] | from_yaml' \
    "$rendered" > "$tmp"

# The console Deployment env is the source of truth for values that the
# chart renders (base path, resolver, upstream suffix, session port).
# Explicit CONSOLE_* environment variables still override it for manual runs.
console_env() {
    yq -r "select(.kind == \"Deployment\" and .metadata.name == \"console\") | .spec.template.spec.containers[] | select(.name == \"console\") | .env[]? | select(.name == \"$1\") | .value" "$rendered" | head -n 1
}

# The console entrypoint strips one trailing slash before validation.
base_path="${CONSOLE_BASE_PATH:-$(console_env CONSOLE_BASE_PATH)}"
base_path="${base_path%/}"
resolver="${CONSOLE_RESOLVER:-$(console_env CONSOLE_RESOLVER)}"
suffix="${CONSOLE_UPSTREAM_SUFFIX:-$(console_env CONSOLE_UPSTREAM_SUFFIX)}"
smport="${CONSOLE_SESSION_PORT:-$(console_env CONSOLE_SESSION_PORT)}"
: "${resolver:=127.0.0.53}"
: "${suffix:=}"
: "${smport:=8000}"

jq -e -f "$repo_root/console/generate.jq" \
    --arg resolver "$resolver" \
    --arg base "$base_path" \
    --arg suffix "$suffix" \
    --arg pw "${CONSOLE_PW_SESSION:-playwright-session-manager}" \
    --arg se "${CONSOLE_SE_SESSION:-selenium-session-manager}" \
    --arg smport "$smport" \
    --arg rundir "${CONSOLE_RUN_DIR:-/run/console}" \
    "$tmp" >/dev/null
