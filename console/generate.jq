# generate.jq -- validate the console target registry and render the nginx
# config and the UI's target list from it.
#
# Usage (see console/entrypoint.sh):
#   jq -e -f generate.jq \
#     --arg resolver "$CONSOLE_RESOLVER" \
#     --arg base "$CONSOLE_BASE_PATH" \
#     --arg suffix "$CONSOLE_UPSTREAM_SUFFIX" \
#     --arg pw "$CONSOLE_PW_SESSION" \
#     --arg se "$CONSOLE_SE_SESSION" \
#     --arg rundir "$CONSOLE_RUN_DIR" \
#     config.json
#
# Input : the registry as JSON ({"ui": ..., "context_options": ...,
#         "targets": [...]}).
# Output: {"nginx": "<console.conf>",
#          "config": {"ui": ..., "targets": [...]}}
#
# Validation is fail-closed: the first problem calls error() (non-zero exit,
# message on stderr) and no output is produced. Per-target messages name the
# offending target (index and/or id); registry-wide messages (duplicate
# ids/tuples/state ids) name the offending value. The noVNC upstream is never
# exposed in "config" (the browser only needs the session-manager API).

def fail($m): error($m);

def has_newline: test("[\\n\\r]");
def has_control_char: test("[\u0000-\u001f\u007f]");

def frameworks: ["playwright", "selenium"];
def browsers: [
  "playwright-chromium", "playwright-firefox", "playwright-webkit",
  "selenium-chrome", "selenium-firefox"
];
def color_schemes: ["light", "dark", "no-preference"];
def context_keys: [
  "locale", "timezone_id", "viewport", "user_agent", "color_scheme",
  "device_scale_factor", "has_touch", "is_mobile", "extra_http_headers"
];
def ui_group_bys: ["none", "framework", "group"];
def ui_tile_aspects: ["4:3", "16:9", "16:10", "5:4"];

def require_string($where; $field):
  if has($field) and ((.[$field] | type) != "string")
  then fail("\($where): context_options.\($field) must be a string")
  else . end;

# Validate a context_options mapping (Playwright only, storage_state/proxy
# and unknown keys are rejected). Returns the object unchanged.
def norm_context($where):
  if type != "object" then fail("\($where): context_options must be a mapping") else . end
  | (keys_unsorted - context_keys) as $unk
  | if ($unk | length) > 0 then fail("\($where): unknown context_options keys: \($unk | join(", "))") else . end
  | require_string($where; "locale")
  | require_string($where; "timezone_id")
  | require_string($where; "user_agent")
  | if has("color_scheme") then
      (.color_scheme) as $cs
      | if ($cs | type) != "string" or (color_schemes | index($cs)) == null
        then fail("\($where): context_options.color_scheme must be one of: \(color_schemes | join(", "))")
        else . end
    else . end
  | if has("device_scale_factor") then
      (.device_scale_factor) as $dsf
      | if ($dsf | type) != "number" or $dsf <= 0
        then fail("\($where): context_options.device_scale_factor must be a positive number")
        else . end
    else . end
  | if has("has_touch") and ((.has_touch | type) != "boolean")
    then fail("\($where): context_options.has_touch must be a boolean")
    else . end
  | if has("is_mobile") and ((.is_mobile | type) != "boolean")
    then fail("\($where): context_options.is_mobile must be a boolean")
    else . end
  | if has("viewport") then
      (.viewport) as $vp
      | if ($vp | type) != "object" then fail("\($where): context_options.viewport must be a mapping") else . end
      | ($vp | keys_unsorted - ["width", "height"]) as $vunk
      | if ($vunk | length) > 0 then fail("\($where): unknown context_options.viewport keys: \($vunk | join(", "))") else . end
      | ($vp.width) as $w
      | ($vp.height) as $h
      | if ($w | type) != "number" or ($w | floor) != $w or $w <= 0
        then fail("\($where): context_options.viewport.width must be a positive integer")
        elif ($h | type) != "number" or ($h | floor) != $h or $h <= 0
        then fail("\($where): context_options.viewport.height must be a positive integer")
        else . end
      # Normalize to integers: jq keeps "800.0" literals, which the
      # session manager's strict int fields would reject.
      | .viewport = {width: ($w | floor), height: ($h | floor)}
    else . end
  | if has("extra_http_headers") then
      (.extra_http_headers) as $headers
      | if ($headers | type) != "object"
        then fail("\($where): context_options.extra_http_headers must be a mapping")
        else . end
      | if ($headers | to_entries | map((.value | type) != "string") | any)
        then fail("\($where): context_options.extra_http_headers values must be strings")
        else . end
    else . end;

# Normalize one storage_state.states[] entry to {id, label, url}.
def norm_state($where; $j):
  if type != "object" then fail("\($where): storage_state.states[\($j)] must be a mapping") else . end
  | (keys_unsorted - ["id", "label", "url"]) as $unk
  | if ($unk | length) > 0 then fail("\($where): unknown storage_state.states[\($j)] keys: \($unk | join(", "))") else . end
  | (.id) as $id
  | if ($id | type) != "string" then fail("\($where): storage_state.states[\($j)].id must be a string")
    elif ($id | test("\\A[a-z0-9-]+\\z") | not) then fail("\($where): invalid storage_state id \($id) (want ^[a-z0-9-]+$)")
    elif ($id | length) > 63 then fail("\($where): storage_state id too long (max 63)")
    else . end
  | (if (has("label") and (.label != null)) then .label else $id end) as $label
  | if ($label | type) != "string" or ($label | length) == 0
    then fail("\($where): storage_state.states[\($j)].label must be a non-empty string")
    elif ($label | has_newline) then fail("\($where): storage_state.states[\($j)].label must not contain newlines")
    elif ($label | length) > 64 then fail("\($where): storage_state.states[\($j)].label too long (max 64)")
    else . end
  | (if has("url") then .url else null end) as $url
  | if $url == null then .
    elif ($url | type) != "string" then fail("\($where): storage_state.states[\($j)].url must be a string")
    elif ($url | has_control_char) then fail("\($where): storage_state.states[\($j)].url must not contain control characters")
    elif ($url | test("^https?://") | not) then fail("\($where): storage_state.states[\($j)].url must be an http(s) URL")
    elif ($url | length) > 2048 then fail("\($where): storage_state.states[\($j)].url too long (max 2048)")
    else . end
  | {id: $id, label: $label, url: $url};

# Normalize storage_state to {states: [{id, label, url}]}. Presence enables
# it. The legacy v2.x ``ids`` list is accepted and expanded to states with
# the id as label and no url. An explicit ``enabled`` key is rejected.
def norm_ss($where; $framework):
  if $framework != "playwright" then fail("\($where): storage_state is only supported for playwright") else . end
  | if type != "object" then fail("\($where): storage_state must be a mapping {states: [...]}") else . end
  | (keys_unsorted - ["states", "ids"]) as $unk
  | if ($unk | length) > 0 then fail("\($where): unknown storage_state keys: \($unk | join(", "))") else . end
  | if has("states") and has("ids")
    then fail("\($where): storage_state.states and storage_state.ids are mutually exclusive")
    else . end
  | if has("ids") then
      (.ids) as $ids
      | if ($ids | type) != "array" then fail("\($where): storage_state.ids must be an array") else . end
      | if ($ids | map(type != "string") | any) then fail("\($where): storage_state.ids must be strings") else . end
      | if ($ids | map(test("\\A[a-z0-9-]+\\z") | not) | any)
        then fail("\($where): invalid storage_state id (want ^[a-z0-9-]+$)")
        else . end
      | if ($ids | map(length > 63) | any) then fail("\($where): storage_state id too long (max 63)") else . end
      | if ($ids | length) != ($ids | unique | length) then fail("\($where): duplicate storage_state id") else . end
      | {states: ($ids | map({id: ., label: ., url: null}))}
    else
      (if has("states") then .states else [] end) as $states
      | if ($states | type) != "array" then fail("\($where): storage_state.states must be an array") else . end
      | {states: [$states | to_entries[] | .key as $j | .value | norm_state($where; $j)]}
    end;

# Validate one target and return its normalized form (including the resolved
# noVNC upstream and the merged Playwright context options).
def norm_target($i; $root_co):
  if type != "object" then fail("targets[\($i)]: must be a mapping") else . end
  | (keys_unsorted - ["id", "label", "framework", "browser", "node", "group", "context_options", "storage_state", "novnc"]) as $unk
  | if ($unk | length) > 0 then fail("targets[\($i)]: unknown keys: \($unk | join(", "))") else . end
  | (.id) as $id
  | if ($id | type) != "string" then fail("targets[\($i)]: id must be a string")
    elif ($id | test("\\A[a-z0-9-]+\\z") | not) then fail("targets[\($i)]: invalid id \($id) (want ^[a-z0-9-]+$)")
    elif ($id | length) > 63 then fail("targets[\($i)]: id too long (max 63)")
    else . end
  | (if (has("label") and (.label != null)) then .label else $id end) as $label
  | if ($label | type) != "string" or ($label | length) == 0
    then fail("targets[\($i)] (\($id)): label must be a non-empty string")
    elif ($label | has_newline) then fail("targets[\($i)] (\($id)): label must not contain newlines")
    elif ($label | length) > 64 then fail("targets[\($i)] (\($id)): label too long (max 64)")
    else . end
  | (.framework) as $framework
  | if ($framework | type) != "string" then fail("targets[\($i)] (\($id)): framework must be a string")
    elif (frameworks | index($framework)) == null
    then fail("targets[\($i)] (\($id)): unknown framework \($framework) (known: \(frameworks | join(", ")))")
    else . end
  | (.browser) as $browser
  | if ($browser | type) != "string" then fail("targets[\($i)] (\($id)): browser must be a string")
    elif (browsers | index($browser)) == null
    then fail("targets[\($i)] (\($id)): unknown browser \($browser) (known: \(browsers | join(", ")))")
    else . end
  | if (($browser | startswith("playwright-")) and $framework != "playwright")
      or (($browser | startswith("selenium-")) and $framework != "selenium")
    then fail("targets[\($i)] (\($id)): browser \($browser) does not match framework \($framework)")
    else . end
  | (if has("node") then .node else null end) as $node
  | if ($node != null) and (($node | type) != "string" or ($node | test("\\A[A-Za-z0-9._-]+\\z") | not))
    then fail("targets[\($i)] (\($id)): node must be null or match ^[A-Za-z0-9._-]+$")
    else . end
  | (if has("group") then .group else null end) as $group
  | if ($group != null) and (($group | type) != "string" or ($group | test("\\A[A-Za-z0-9._-]+\\z") | not) or ($group | length) > 64)
    then fail("targets[\($i)] (\($id)): group must be null or match ^[A-Za-z0-9._-]+$ (max 64)")
    else . end
  | if $framework != "playwright" and has("context_options")
    then fail("targets[\($i)] (\($id)): context_options is only supported for playwright")
    else . end
  | (if has("context_options") then (.context_options | norm_context("targets[\($i)] (\($id))")) else {} end) as $tco
  | (if has("storage_state") then (.storage_state | norm_ss("targets[\($i)] (\($id))"; $framework)) else null end) as $ss
  | (if has("novnc") then .novnc else {} end) as $nraw
  | if ($nraw | type) != "object" then fail("targets[\($i)] (\($id)): novnc must be a mapping") else . end
  | ($nraw | keys_unsorted - ["host", "port"]) as $nunk
  | if ($nunk | length) > 0 then fail("targets[\($i)] (\($id)): unknown novnc keys: \($nunk | join(", "))") else . end
  | (if ($nraw | has("host")) then $nraw.host else $id end) as $host
  | if ($host | type) != "string" then fail("targets[\($i)] (\($id)): novnc.host must be a string")
    elif ($host | test("\\A[A-Za-z0-9._-]+\\z") | not) then fail("targets[\($i)] (\($id)): novnc.host must match ^[A-Za-z0-9._-]+$")
    else . end
  | (if ($nraw | has("port")) then $nraw.port else 7900 end) as $port
  | if ($port | type) != "number" then fail("targets[\($i)] (\($id)): novnc.port must be an integer 1-65535")
    elif (($port | floor) != $port) or ($port < 1) or ($port > 65535)
    then fail("targets[\($i)] (\($id)): novnc.port must be an integer 1-65535")
    else . end
  | {
      id: $id, label: $label, framework: $framework, browser: $browser,
      node: $node, group: $group,
      context_options: (if $framework == "playwright" then ($root_co + $tco) else null end),
      storage_state: $ss,
      host: $host, port: ($port | floor)
    };

# The public (config.json) shape: no noVNC upstream.
def public_target:
  {id, label, framework, browser, node, group}
  + (if .context_options != null then {context_options} else {} end)
  + (if .storage_state != null then {storage_state} else {} end);

# Validate the env-derived arguments. Rejects nginx metacharacters before any
# value reaches a directive. The base path is also checked in the entrypoint
# for an early message; this keeps a direct jq invocation fail-closed too.
def validate_args($resolver; $b; $sfx; $pw; $se; $rundir):
  if ($resolver | has_newline) then fail("invalid resolver: \($resolver)")
  elif ($resolver | test("^[A-Za-z0-9.:\\[\\]]+$") | not) then fail("invalid resolver: \($resolver)")
  elif ($b | has_newline) then fail("invalid base path: \($b)")
  elif ($b | test("^(/[A-Za-z0-9-]+)*$") | not) then fail("invalid base path: \($b)")
  elif ($sfx | has_newline) then fail("invalid upstream suffix: \($sfx)")
  elif ($sfx | test("^$|^\\.[A-Za-z0-9._-]+$") | not) then fail("invalid upstream suffix: \($sfx)")
  elif ($pw | has_newline) then fail("invalid playwright session upstream: \($pw)")
  elif ($pw | test("^[A-Za-z0-9._-]+$") | not) then fail("invalid playwright session upstream: \($pw)")
  elif ($se | has_newline) then fail("invalid selenium session upstream: \($se)")
  elif ($se | test("^[A-Za-z0-9._-]+$") | not) then fail("invalid selenium session upstream: \($se)")
  elif ($rundir | test("\\A/[A-Za-z0-9._/-]+\\z") | not) then fail("invalid run dir: \($rundir)")
  elif ($rundir | test("(^|/)\\.\\.?(/|$)")) then fail("invalid run dir: \($rundir)")
  elif ($rundir | contains("//")) then fail("invalid run dir: \($rundir)")
  else . end;

def header:
  "# Generated by console/generate.jq from the console configuration.\n" +
  "# Do not edit: it is overwritten at container start.\n";

def root_redir($b):
  if $b == "" then empty
  else ([
    "    location = / {\n        return 308 \($b)/;\n    }",
    # Without this, "<base>" (no trailing slash) misses the alias location
    # and 404s. Skip when it would collide with the exact /healthz location.
    (if $b == "/healthz" then empty
     else "    location = \($b) {\n        return 308 \($b)/;\n    }" end)
  ] | join("\n"))
  end;

def ui_loc($b):
  if $b == "" then empty
  else "    location \($b)/ {\n        alias /usr/share/nginx/html/;\n        index index.html;\n    }"
  end;

# One shared location for every full-size view; the browser URL is kept and
# view.html derives the id from location.pathname.
def view_loc($b):
  "    location \($b)/view/ {\n        rewrite ^\($b)/view/.*$ \($b)/view.html last;\n    }";

def config_loc($b; $rundir):
  "    location = \($b)/config.json {\n        alias \($rundir)/config.json;\n        default_type application/json;\n        add_header Cache-Control \"no-store\" always;\n    }";

def api_loc($b; $pw; $se; $sfx):
  (
    "    location \($b)/api/playwright/ {\n        set $pw_sessions \($pw)\($sfx):8081;\n        rewrite ^\($b)/api/playwright/(.*) /api/playwright/$1 break;\n        proxy_pass http://$pw_sessions;\n        proxy_http_version 1.1;\n        proxy_set_header Host $host;\n        proxy_read_timeout 150s;\n    }",
    "    location \($b)/api/selenium/ {\n        set $se_sessions \($se)\($sfx):8082;\n        rewrite ^\($b)/api/selenium/(.*) /api/selenium/$1 break;\n        proxy_pass http://$se_sessions;\n        proxy_http_version 1.1;\n        proxy_set_header Host $host;\n        proxy_read_timeout 150s;\n    }"
  );

# noVNC without the trailing slash redirects explicitly: the prefix location
# alone would leave the result to nginx's auto-redirect rules, which vary
# between alias/proxy setups.
def vnc_redirect_loc($b; $e):
  "    location = \($b)/vnc/\($e.id) {\n        return 301 \($b)/vnc/\($e.id)/;\n    }";

# Raw noVNC per target. The first rewrite serves the noVNC page for the
# directory root; the second forwards assets and the websocket path.
def novnc_loc($b; $sfx; $e):
  "    location \($b)/vnc/\($e.id)/ {\n        set $novnc_node \($e.host)\($sfx):\($e.port);\n        rewrite ^\($b)/vnc/\($e.id)/$ /vnc.html break;\n        rewrite ^\($b)/vnc/\($e.id)/(.*) /$1 break;\n        proxy_pass http://$novnc_node;\n        proxy_http_version 1.1;\n        proxy_set_header Upgrade $http_upgrade;\n        proxy_set_header Connection $connection_upgrade;\n        proxy_set_header Host $host;\n        proxy_read_timeout 1d;\n    }";

. as $root
| validate_args($resolver; $base; $suffix; $pw; $se; $rundir)
| if ($root | type) != "object" then fail("console: must be a mapping") else . end
| ($root | keys_unsorted - ["ui", "context_options", "targets"]) as $runk
| if ($runk | length) > 0 then fail("console: unknown keys: \($runk | join(", "))") else . end
| ($root.targets) as $targets
| if ($targets | type) != "array" then fail("console: 'targets' must be an array")
  elif ($targets | length) == 0 then fail("console: 'targets' must not be empty")
  else . end
| (if ($root | has("ui")) then $root.ui else {} end) as $ui_raw
| if ($ui_raw | type) != "object" then fail("console: ui must be a mapping") else . end
| ($ui_raw | keys_unsorted - ["columns", "group_by", "tile_min_width", "tile_aspect"]) as $uunk
| if ($uunk | length) > 0 then fail("console: unknown ui keys: \($uunk | join(", "))") else . end
| (if ($ui_raw | has("columns")) then $ui_raw.columns else "auto" end) as $columns
| if ($columns | type) == "string" then
    (if $columns != "auto" then fail("console: ui.columns must be \"auto\" or an integer 1-12") else . end)
  elif ($columns | type) == "number" then
    (if (($columns | floor) != $columns) or $columns < 1 or $columns > 12
      then fail("console: ui.columns must be \"auto\" or an integer 1-12") else . end)
  else fail("console: ui.columns must be \"auto\" or an integer 1-12") end
| (if ($ui_raw | has("group_by")) then $ui_raw.group_by else "none" end) as $group_by
| if ($group_by | type) != "string" or (ui_group_bys | index($group_by)) == null
  then fail("console: ui.group_by must be one of: \(ui_group_bys | join(", "))")
  else . end
| (if ($ui_raw | has("tile_min_width")) then $ui_raw.tile_min_width else 560 end) as $tile_min_width
| if ($tile_min_width | type) != "number"
    or (($tile_min_width | floor) != $tile_min_width)
    or $tile_min_width < 160 or $tile_min_width > 1920
  then fail("console: ui.tile_min_width must be an integer 160-1920")
  else . end
| (if ($ui_raw | has("tile_aspect")) then $ui_raw.tile_aspect else "16:9" end) as $tile_aspect
| if ($tile_aspect | type) != "string" or (ui_tile_aspects | index($tile_aspect)) == null
  then fail("console: ui.tile_aspect must be one of: \(ui_tile_aspects | join(", "))")
  else . end
| (if ($root | has("context_options")) then ($root.context_options | norm_context("console")) else {} end) as $root_co
| [ $targets | to_entries[] | .key as $i | .value | norm_target($i; $root_co) ] as $T
| ($T | map(.id)) as $ids
| ($ids | group_by(.) | map(select(length > 1) | .[0])) as $dup_ids
| if ($dup_ids | length) > 0
  then fail("console: duplicate target id: \($dup_ids | join(", "))")
  else . end
| ($T | map([.framework, .browser, .node])) as $uniq
| ($uniq | group_by(.) | map(select(length > 1) | .[0])) as $dup_tuples
| if ($dup_tuples | length) > 0
  then fail("console: duplicate (framework, browser, node): \($dup_tuples | map(tojson) | join(", "))")
  else . end
| ($T | map(.storage_state.states // []) | add) as $states
| ($states | map(.id)) as $state_ids
| ($state_ids | group_by(.) | map(select(length > 1) | .[0])) as $dup_states
| if ($dup_states | length) > 0
  then fail("console: duplicate storage_state id across targets: \($dup_states | join(", "))")
  else . end
| {
    nginx: (
      header
      + "resolver \($resolver) valid=10s ipv6=off;\n\n"
      + "map $http_upgrade $connection_upgrade {\n    default upgrade;\n    ''      close;\n}\n\n"
      + "server {\n"
      + "    listen 80;\n"
      + "    listen [::]:80;\n"
      + "    root /usr/share/nginx/html;\n"
      + "    index index.html;\n\n"
      + "    location = /healthz {\n        access_log off;\n        return 200 \"ok\\n\";\n    }\n\n"
      + ([
          root_redir($base),
          ui_loc($base),
          view_loc($base),
          config_loc($base; $rundir),
          api_loc($base; $pw; $se; $suffix),
          ($T[] | vnc_redirect_loc($base; .)),
          ($T[] | novnc_loc($base; $suffix; .))
        ] | join("\n"))
      + "\n}\n"
    ),
    config: {
      ui: {
        columns: (if ($columns | type) == "number" then ($columns | floor) else $columns end),
        group_by: $group_by,
        tile_min_width: ($tile_min_width | floor),
        tile_aspect: $tile_aspect
      },
      targets: [ $T[] | public_target ]
    }
  }
