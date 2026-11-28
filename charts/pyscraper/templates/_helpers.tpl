{{/*
Build an image reference from a values.images entry with registry, repository,
and tag. An empty registry means Docker Hub. An empty tag uses the chart
appVersion, which the release workflow sets to the release tag.
Call with:
  include "pyscraper.image" (dict "root" . "image" .Values.images.console)
*/}}
{{- define "pyscraper.image" -}}
{{- $registry := .image.registry -}}
{{- $repository := .image.repository -}}
{{- $tag := default .root.Chart.AppVersion .image.tag -}}
{{- if $registry -}}
{{- printf "%s/%s:%s" $registry $repository $tag -}}
{{- else -}}
{{- printf "%s:%s" $repository $tag -}}
{{- end -}}
{{- end -}}

{{/*
The six proxy environment variables, rendered only when at least one proxy
value is set. HTTP_PROXY/HTTPS_PROXY/NO_PROXY reuse the lowercase values.
*/}}
{{- define "pyscraper.proxyEnv" -}}
{{- $proxy := default (dict) .Values.global.proxy -}}
{{- if or $proxy.httpProxy $proxy.httpsProxy $proxy.noProxy -}}
- name: http_proxy
  value: {{ $proxy.httpProxy | quote }}
- name: HTTP_PROXY
  value: "$(http_proxy)"
- name: https_proxy
  value: {{ $proxy.httpsProxy | quote }}
- name: HTTPS_PROXY
  value: "$(https_proxy)"
- name: no_proxy
  value: {{ $proxy.noProxy | quote }}
- name: NO_PROXY
  value: "$(no_proxy)"
{{- end }}
{{- end -}}

{{/* TZ from global.timezone, rendered only when the value is set. */}}
{{- define "pyscraper.timezoneEnv" -}}
{{- with .Values.global.timezone -}}
- name: TZ
  value: {{ . | quote }}
{{- end }}
{{- end -}}

{{/*
Console configuration. The same content is used for the ConfigMap and the
Deployment checksum annotation so changing nodes/UI/context options rolls
the console Pod (the file is mounted with subPath).
*/}}
{{- define "pyscraper.consoleConfig" -}}
{{- $targets := list -}}
{{- range $key, $node := .Values.nodes -}}
{{- $node := default (dict) $node -}}
{{- $enabled := dig "enabled" true $node -}}
{{- if or (kindIs "invalid" $enabled) $enabled -}}
{{- $framework := dig "framework" "" $node -}}
{{- $browser := dig "browser" "" $node -}}
{{- $name := $key -}}
{{- $console := default (dict) (dig "console" (dict) $node) -}}
{{- $id := $key -}}
{{- $label := default $key (dig "label" "" $console) -}}
{{- $group := default $browser (dig "group" "" $console) -}}
{{- $target := dict "id" $id "label" $label "framework" $framework "browser" (printf "%s-%s" $framework $browser) "group" $group -}}
{{- if eq $framework "selenium" -}}
{{- $_ := set $target "node" (default $key (dig "node" "" $node)) -}}
{{- else -}}
{{- $_ := set $target "node" $name -}}
{{- $co := dig "contextOptions" (dict) $console -}}
{{- if and (hasKey $console "contextOptions") (not (kindIs "invalid" $co)) -}}
{{- $_ := set $target "context_options" $co -}}
{{- end -}}
{{- $ss := dig "storageState" true $console -}}
{{- if not (kindIs "bool" $ss) -}}
{{- fail (printf "nodes.%s.console.storageState must be a boolean" $key) -}}
{{- end -}}
{{- if $ss -}}
{{- $_ := set $target "storage_state" (dict "states" (list (dict "id" $id "label" $label))) -}}
{{- end -}}
{{- end -}}
{{- $_ := set $target "novnc" (dict "host" $name "port" 7900) -}}
{{- $targets = append $targets $target -}}
{{- end -}}
{{- end -}}
{{- dict "ui" (default (dict) .Values.console.ui) "context_options" (default (dict) .Values.console.contextOptions) "targets" $targets | toYaml -}}
{{- end -}}
