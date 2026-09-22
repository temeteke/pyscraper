"""Unit tests for the gateway image: registry rendering and packaging.

The gateway is a dedicated nginx image whose entrypoint validates
``gateway/endpoints.yaml`` with ``gateway/generate.jq`` (jq; YAML via yq) and
renders the nginx config and the UI's endpoint list from it. These tests
cover the schema/validation rules, the rendered routing for empty and
non-empty base paths, the Dockerfile/CI wiring, and the UI wiring.

The rendering tests execute the real tools (yq/jq) and are skipped when one
is missing. ``subprocess.run`` is mocked by an autouse conftest fixture, so
the module opts out with ``no_mock_ffmpeg``.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_mock_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
GATEWAY = ROOT / "gateway"
ENDPOINTS = GATEWAY / "endpoints.yaml"
GENERATE_JQ = GATEWAY / "generate.jq"
ENTRYPOINT = GATEWAY / "entrypoint.sh"
INDEX = GATEWAY / "index.html"
VIEW = GATEWAY / "view.html"
DOCKERFILE = ROOT / "Dockerfile.gateway"
COMPOSE = ROOT / "compose.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "docker.yml"
TESTS_WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"

SAMPLE_REGISTRY = {
    "endpoints": [
        {
            "id": "playwright-chromium",
            "label": "Chromium (Playwright)",
            "framework": "playwright",
            "browser": "playwright-chromium",
            "storage_state": {"ids": ["chromium"]},
            "novnc": {"host": "playwright-chromium", "port": 7900},
        },
        {
            "id": "selenium-chrome-profile",
            "label": "Chrome (profile)",
            "framework": "selenium",
            "browser": "selenium-chrome",
            "node": "chromium-profile",
            "novnc": {"host": "selenium-chrome-node"},
        },
    ]
}


def _require(*tools):
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        pytest.skip(f"missing tools: {', '.join(missing)}")


def _jq_generate(
    tmp_path,
    registry,
    resolver="127.0.0.11",
    base="",
    suffix="",
    pw="playwright-session-manager",
    se="selenium-session-manager",
    rundir="/run/gateway",
):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps(registry))
    return subprocess.run(
        [
            "jq",
            "-e",
            "-f",
            str(GENERATE_JQ),
            "--arg",
            "resolver",
            resolver,
            "--arg",
            "base",
            base,
            "--arg",
            "suffix",
            suffix,
            "--arg",
            "pw",
            pw,
            "--arg",
            "se",
            se,
            "--arg",
            "rundir",
            rundir,
            str(reg),
        ],
        capture_output=True,
        text=True,
    )


def _jq_ok(tmp_path, registry, **kwargs):
    proc = _jq_generate(tmp_path, registry, **kwargs)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _run_entrypoint(tmp_path, registry_text=None, env=None, resolv=None, base="", nginx_t_exit=0):
    """Run the real entrypoint with every path redirected into tmp_path.

    A stub ``nginx`` on PATH records its invocation and exits 0 (except
    ``nginx -t``, whose exit code is configurable), so the whole pipeline
    (yq -> jq -> nginx -t -> exec) is exercised.
    """
    _require("yq", "jq")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "nginx.log"
    nginx = bindir / "nginx"
    nginx.write_text(
        f'#!/bin/sh\necho "nginx $*" >> "{log}"\n'
        f'if [ "$1" = "-t" ]; then exit {nginx_t_exit}; fi\nexit 0\n'
    )
    nginx.chmod(0o755)

    endpoints = tmp_path / "endpoints.yaml"
    endpoints.write_text(registry_text if registry_text is not None else ENDPOINTS.read_text())
    resolv_file = tmp_path / "resolv.conf"
    resolv_file.write_text(
        resolv if resolv is not None else "nameserver 127.0.0.11\noptions ndots:0\n"
    )

    run_env = {k: v for k, v in os.environ.items() if not k.startswith("GATEWAY_")}
    run_env["PATH"] = str(bindir) + os.pathsep + run_env.get("PATH", "")
    run_env.update(
        {
            "GATEWAY_ENDPOINTS_FILE": str(endpoints),
            "GATEWAY_GENERATE_JQ": str(GENERATE_JQ),
            "GATEWAY_RUN_DIR": str(tmp_path / "run"),
            "GATEWAY_NGINX_CONF": str(tmp_path / "default.conf"),
            "GATEWAY_RESOLV_CONF": str(resolv_file),
            "GATEWAY_BASE_PATH": base,
        }
    )
    if env:
        run_env.update(env)
    proc = subprocess.run(["sh", str(ENTRYPOINT)], env=run_env, capture_output=True, text=True)
    return proc, tmp_path / "run", tmp_path / "default.conf", log


class TestGenerateValidation:
    def test_valid_sample(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_REGISTRY)
        assert set(out) == {"nginx", "endpoints"}

    def test_arbitrary_browser_is_accepted(self, tmp_path):
        # browser validity is delegated to the session manager; the gateway
        # only requires a non-empty string.
        _require("jq")
        reg = {"endpoints": [dict(SAMPLE_REGISTRY["endpoints"][0], browser="custom-browser")]}
        _jq_ok(tmp_path, reg)

    @pytest.mark.parametrize(
        "registry, message",
        [
            ({"endpoints": []}, "must not be empty"),
            ({"endpoints": "x"}, "must be an array"),
            ({"endpoints": [{"id": "x", "bogus": 1}]}, "unknown keys"),
            (
                {
                    "endpoints": [
                        {
                            "id": "X",
                            "label": "x",
                            "framework": "playwright",
                            "browser": "b",
                            "novnc": {"host": "h"},
                        }
                    ]
                },
                "invalid id",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "a" * 64,
                            "label": "x",
                            "framework": "playwright",
                            "browser": "b",
                            "novnc": {"host": "h"},
                        }
                    ]
                },
                "id too long",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "x",
                            "label": "",
                            "framework": "playwright",
                            "browser": "b",
                            "novnc": {"host": "h"},
                        }
                    ]
                },
                "label must be a non-empty",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "x",
                            "label": "x",
                            "framework": "puppeteer",
                            "browser": "b",
                            "novnc": {"host": "h"},
                        }
                    ]
                },
                "unknown framework",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "x",
                            "label": "x",
                            "framework": "playwright",
                            "browser": "",
                            "novnc": {"host": "h"},
                        }
                    ]
                },
                "browser must be a non-empty",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "x",
                            "label": "x",
                            "framework": "selenium",
                            "browser": "selenium-chrome",
                            "storage_state": True,
                            "novnc": {"host": "h"},
                        }
                    ]
                },
                "only supported for playwright",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "x",
                            "label": "x",
                            "framework": "playwright",
                            "browser": "b",
                            "novnc": {"host": "h; }"},
                        }
                    ]
                },
                "novnc.host must match",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "x",
                            "label": "x",
                            "framework": "playwright",
                            "browser": "b",
                            "novnc": {"host": "h", "port": "7900"},
                        }
                    ]
                },
                "novnc.port must be an integer",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "x",
                            "label": "x",
                            "framework": "playwright",
                            "browser": "b",
                            "node": "$(evil)",
                            "novnc": {"host": "h"},
                        }
                    ]
                },
                "node must be null",
            ),
            (
                {
                    "endpoints": [
                        {
                            "id": "x",
                            "label": "x",
                            "framework": "playwright",
                            "browser": "b",
                            "novnc": {"host": "h", "extra": 1},
                        }
                    ]
                },
                "unknown novnc keys",
            ),
        ],
    )
    def test_rejects_bad_registry(self, tmp_path, registry, message):
        _require("jq")
        proc = _jq_generate(tmp_path, registry)
        assert proc.returncode != 0
        assert message in proc.stderr

    def test_rejects_duplicate_id(self, tmp_path):
        _require("jq")
        entry = SAMPLE_REGISTRY["endpoints"][0]
        reg = {"endpoints": [entry, dict(entry, label="other")]}
        proc = _jq_generate(tmp_path, reg)
        assert proc.returncode != 0
        assert "duplicate endpoint id" in proc.stderr

    def test_rejects_endpoint_id_trailing_newline(self, tmp_path):
        # jq's ``$`` matches before a trailing newline; the id anchor must
        # reject it so no newline can reach the nginx config.
        _require("jq")
        entry = {
            "id": "evil\n",
            "label": "x",
            "framework": "playwright",
            "browser": "b",
            "novnc": {"host": "h"},
        }
        proc = _jq_generate(tmp_path, {"endpoints": [entry]})
        assert proc.returncode != 0
        assert "invalid id" in proc.stderr

    def test_rejects_node_trailing_newline(self, tmp_path):
        _require("jq")
        entry = {
            "id": "x",
            "label": "x",
            "framework": "playwright",
            "browser": "b",
            "node": "n\n",
            "novnc": {"host": "h"},
        }
        proc = _jq_generate(tmp_path, {"endpoints": [entry]})
        assert proc.returncode != 0
        assert "node must be null" in proc.stderr

    def test_rejects_novnc_host_trailing_newline(self, tmp_path):
        _require("jq")
        entry = {
            "id": "x",
            "label": "x",
            "framework": "playwright",
            "browser": "b",
            "novnc": {"host": "h\n"},
        }
        proc = _jq_generate(tmp_path, {"endpoints": [entry]})
        assert proc.returncode != 0
        assert "novnc.host must match" in proc.stderr

    def test_rejects_duplicate_framework_browser_node(self, tmp_path):
        _require("jq")
        entry = SAMPLE_REGISTRY["endpoints"][1]
        reg = {"endpoints": [entry, dict(entry, id="other")]}
        proc = _jq_generate(tmp_path, reg)
        assert proc.returncode != 0
        assert "duplicate (framework, browser, node)" in proc.stderr


class TestGenerateStorageState:
    def _entry(self, **over):
        entry = {
            "id": "pw",
            "label": "pw",
            "framework": "playwright",
            "browser": "b",
            "novnc": {"host": "h"},
        }
        entry.update(over)
        return entry

    def _ss(self, tmp_path, endpoint):
        _require("jq")
        out = _jq_ok(tmp_path, {"endpoints": [endpoint]})
        return out["endpoints"]["endpoints"][0]["storage_state"]

    def test_bool_true_normalizes(self, tmp_path):
        assert self._ss(tmp_path, self._entry(storage_state=True)) == {
            "enabled": True,
            "ids": [],
        }

    def test_bool_false_normalizes(self, tmp_path):
        assert self._ss(tmp_path, self._entry(storage_state=False)) == {
            "enabled": False,
            "ids": [],
        }

    def test_omitted_normalizes(self, tmp_path):
        assert self._ss(tmp_path, self._entry()) == {"enabled": False, "ids": []}

    def test_mapping_defaults_enabled_true(self, tmp_path):
        assert self._ss(tmp_path, self._entry(storage_state={"ids": ["a"]})) == {
            "enabled": True,
            "ids": ["a"],
        }

    def test_mapping_enabled_false(self, tmp_path):
        assert self._ss(tmp_path, self._entry(storage_state={"enabled": False})) == {
            "enabled": False,
            "ids": [],
        }

    def test_selenium_disabled_mapping_accepted(self, tmp_path):
        entry = self._entry(
            framework="selenium",
            browser="selenium-chrome",
            storage_state={"enabled": False},
        )
        assert self._ss(tmp_path, entry) == {"enabled": False, "ids": []}

    def test_accepts_max_length_state_id(self, tmp_path):
        state_id = "a" * 63
        assert self._ss(tmp_path, self._entry(storage_state={"ids": [state_id]})) == {
            "enabled": True,
            "ids": [state_id],
        }

    def test_endpoints_always_exposes_object(self, tmp_path):
        # v2.0.0 boolean form is normalized to the {enabled, ids} shape.
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_REGISTRY)
        for entry in out["endpoints"]["endpoints"]:
            assert isinstance(entry["storage_state"], dict)
            assert set(entry["storage_state"]) == {"enabled", "ids"}

    @pytest.mark.parametrize(
        "storage_state, message",
        [
            ("x", "must be a boolean or mapping"),
            ({"enabled": "yes"}, "enabled must be a boolean"),
            ({"ids": "a"}, "ids must be an array"),
            ({"ids": [1]}, "ids must be strings"),
            ({"ids": ["A"]}, "invalid storage_state id"),
            ({"ids": ["a\n"]}, "invalid storage_state id"),
            ({"ids": ["a" * 64]}, "storage_state id too long"),
            ({"ids": ["a", "a"]}, "duplicate storage_state id"),
            ({"enabled": False, "ids": ["a"]}, "enabled is false but ids is not empty"),
            ({"bogus": 1}, "unknown storage_state keys"),
            (None, "must be a boolean or mapping"),
        ],
    )
    def test_rejects_bad_storage_state(self, tmp_path, storage_state, message):
        _require("jq")
        proc = _jq_generate(tmp_path, {"endpoints": [self._entry(storage_state=storage_state)]})
        assert proc.returncode != 0
        assert message in proc.stderr

    def test_rejects_enabled_for_selenium(self, tmp_path):
        _require("jq")
        entry = self._entry(
            framework="selenium",
            browser="selenium-chrome",
            storage_state={"enabled": True},
        )
        proc = _jq_generate(tmp_path, {"endpoints": [entry]})
        assert proc.returncode != 0
        assert "only supported for playwright" in proc.stderr

    def test_rejects_duplicate_state_id_across_endpoints(self, tmp_path):
        _require("jq")
        reg = {
            "endpoints": [
                self._entry(id="a", browser="b1", storage_state={"ids": ["s"]}),
                self._entry(id="b", browser="b2", storage_state={"ids": ["s"]}),
            ]
        }
        proc = _jq_generate(tmp_path, reg)
        assert proc.returncode != 0
        assert "duplicate storage_state id across endpoints" in proc.stderr


class TestGenerateArgs:
    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"resolver": ""}, "invalid resolver"),
            ({"resolver": "8.8.8.8; }"}, "invalid resolver"),
            ({"resolver": "8.8.8.8#x"}, "invalid resolver"),
            ({"resolver": '"8.8.8.8"'}, "invalid resolver"),
            ({"resolver": "1.1.1.1\n"}, "invalid resolver"),
            ({"base": "/bad path"}, "invalid base path"),
            ({"base": "/a/../b"}, "invalid base path"),
            ({"suffix": "\n"}, "invalid upstream suffix"),
            ({"suffix": "x; }"}, "invalid upstream suffix"),
            ({"suffix": "svc.internal"}, "invalid upstream suffix"),
            ({"pw": "a\nb"}, "invalid playwright session upstream"),
            ({"se": "a;b"}, "invalid selenium session upstream"),
            ({"rundir": "relative"}, "invalid run dir"),
            ({"rundir": "/run/gateway\n"}, "invalid run dir"),
            ({"rundir": "/run/gateway; evil"}, "invalid run dir"),
            ({"rundir": "/run gateway"}, "invalid run dir"),
        ],
    )
    def test_rejects_unsafe_env_args(self, tmp_path, kwargs, message):
        _require("jq")
        proc = _jq_generate(tmp_path, SAMPLE_REGISTRY, **kwargs)
        assert proc.returncode != 0
        assert message in proc.stderr


class TestGenerateNginx:
    def test_base_empty_locations(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_REGISTRY)
        conf = out["nginx"]
        assert conf.startswith("# Generated by gateway/generate.jq")
        assert "resolver 127.0.0.11 valid=10s ipv6=off;" in conf
        assert "location = /healthz {" in conf
        assert "location /view/ {" in conf
        assert "rewrite ^/view/.*$ /view.html last;" in conf
        assert "map $http_upgrade $connection_upgrade {" in conf
        assert "proxy_set_header Connection $connection_upgrade;" in conf
        assert 'proxy_set_header Connection "upgrade";' not in conf
        assert "location = /api/endpoints {" in conf
        assert "alias /run/gateway/endpoints.json;" in conf
        assert 'add_header Cache-Control "no-store" always;' in conf
        assert "location /api/playwright/ {" in conf
        assert "rewrite ^/api/playwright/(.*) /api/playwright/$1 break;" in conf
        assert "location /api/selenium/ {" in conf
        assert "location /vnc/playwright-chromium/ {" in conf
        assert "rewrite ^/vnc/playwright-chromium/$ /vnc.html break;" in conf
        assert "rewrite ^/vnc/playwright-chromium/(.*) /$1 break;" in conf
        assert "set $novnc_node selenium-chrome-node:7900;" in conf
        # nginx runtime vars are literal (no envsubst pass).
        assert "proxy_set_header Host $host;" in conf
        assert "proxy_set_header Upgrade $http_upgrade;" in conf
        assert "location = / {" not in conf  # no root redirect at the root base

    def test_base_non_empty_locations(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_REGISTRY, base="/gateway", suffix=".svc.internal")
        conf = out["nginx"]
        assert "location = / {" in conf
        assert "return 308 /gateway/;" in conf
        assert "location /gateway/ {" in conf
        assert "alias /usr/share/nginx/html/;" in conf
        assert "location /gateway/view/ {" in conf
        assert "rewrite ^/gateway/view/.*$ /gateway/view.html last;" in conf
        assert "location = /gateway/api/endpoints {" in conf
        assert "rewrite ^/gateway/api/playwright/(.*) /api/playwright/$1 break;" in conf
        assert "location /gateway/vnc/playwright-chromium/ {" in conf
        assert "set $novnc_node playwright-chromium.svc.internal:7900;" in conf
        assert "rewrite ^/gateway/vnc/playwright-chromium/(.*) /$1 break;" in conf

    def test_endpoints_hides_novnc_upstream(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_REGISTRY)
        endpoints = out["endpoints"]["endpoints"]
        assert [e["id"] for e in endpoints] == [
            "playwright-chromium",
            "selenium-chrome-profile",
        ]
        for entry in endpoints:
            assert set(entry) == {
                "id",
                "label",
                "framework",
                "browser",
                "node",
                "storage_state",
            }
            assert "host" not in entry and "port" not in entry
        assert endpoints[0]["storage_state"] == {"enabled": True, "ids": ["chromium"]}
        assert endpoints[1]["node"] == "chromium-profile"

    def test_explicit_upstreams(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_REGISTRY, suffix=".svc", pw="my-pw", se="my-se")
        conf = out["nginx"]
        assert "set $pw_sessions my-pw.svc:8081;" in conf
        assert "set $se_sessions my-se.svc:8082;" in conf

    @pytest.mark.parametrize("base", ["/healthz", "/view", "/vnc", "/api", "/a/b"])
    def test_base_variants_generate(self, tmp_path, base):
        # The role-based locations must not collide with /healthz, /api/...,
        # or each other for any accepted base path.
        _require("jq")
        _jq_ok(tmp_path, SAMPLE_REGISTRY, base=base)

    def test_prefix_collision_ids(self, tmp_path):
        # ``a`` and ``a-b`` must not shadow each other (trailing-slash
        # locations).
        _require("jq")
        reg = {
            "endpoints": [
                {
                    "id": "a",
                    "label": "a",
                    "framework": "playwright",
                    "browser": "b1",
                    "novnc": {"host": "h1"},
                },
                {
                    "id": "a-b",
                    "label": "a-b",
                    "framework": "playwright",
                    "browser": "b2",
                    "novnc": {"host": "h2"},
                },
            ]
        }
        conf = _jq_ok(tmp_path, reg)["nginx"]
        assert "location /vnc/a/ {" in conf
        assert "location /vnc/a-b/ {" in conf

    def test_underscore_in_upstream_and_host(self, tmp_path):
        # Compose service names may contain underscores.
        _require("jq")
        reg = {"endpoints": [dict(SAMPLE_REGISTRY["endpoints"][0], novnc={"host": "my_host"})]}
        conf = _jq_ok(tmp_path, reg, pw="my_pw", se="my_se")["nginx"]
        assert "set $pw_sessions my_pw:8081;" in conf
        assert "set $se_sessions my_se:8082;" in conf
        assert "set $novnc_node my_host:7900;" in conf


class TestEntrypoint:
    COMPOSE_RESOLV = "nameserver 127.0.0.11\noptions ndots:0\n"
    SEARCH_RESOLV = "nameserver 10.96.0.10\nsearch svc.internal example.com\noptions ndots:5\n"

    def _run(self, tmp_path, **kwargs):
        return _run_entrypoint(tmp_path, **kwargs)

    def test_renders_defaults(self, tmp_path):
        proc, run_dir, conf, log = self._run(tmp_path)
        assert proc.returncode == 0, proc.stderr
        rendered = conf.read_text()
        assert rendered.startswith("# Generated by gateway/generate.jq")
        assert "resolver 127.0.0.11 valid=10s ipv6=off;" in rendered
        assert "nginx -t" in log.read_text()

        endpoints = json.loads((run_dir / "endpoints.json").read_text())
        entries = endpoints["endpoints"]
        assert [e["id"] for e in entries] == [
            "playwright-chromium",
            "playwright-firefox",
            "playwright-webkit",
            "selenium-chrome",
            "selenium-firefox",
        ]
        by_id = {e["id"]: e for e in entries}
        assert by_id["playwright-chromium"]["framework"] == "playwright"
        assert by_id["playwright-chromium"]["storage_state"] == {
            "enabled": True,
            "ids": ["chromium"],
        }
        assert by_id["playwright-firefox"]["storage_state"] == {
            "enabled": True,
            "ids": ["firefox"],
        }
        assert by_id["selenium-chrome"]["framework"] == "selenium"
        assert by_id["selenium-chrome"]["storage_state"] == {"enabled": False, "ids": []}
        assert all(e["node"] is None for e in entries)

    def test_search_domain_is_not_applied_implicitly(self, tmp_path):
        # A Docker daemon with dns-search set puts a search domain in the
        # container's resolv.conf, but Docker's embedded DNS still resolves
        # short service names only. The suffix must stay empty unless it is
        # requested explicitly, or compose name resolution would break.
        proc, _, conf, _ = self._run(tmp_path, resolv=self.SEARCH_RESOLV)
        assert proc.returncode == 0, proc.stderr
        rendered = conf.read_text()
        assert "set $pw_sessions playwright-session-manager:8081;" in rendered
        assert "set $novnc_node selenium-chrome-node:7900;" in rendered

    def test_explicit_suffix_and_upstreams(self, tmp_path):
        proc, _, conf, _ = self._run(
            tmp_path,
            env={
                "GATEWAY_UPSTREAM_SUFFIX": ".svc.internal",
                "GATEWAY_PW_SESSION": "my-pw",
                "GATEWAY_SE_SESSION": "my-se",
            },
        )
        assert proc.returncode == 0, proc.stderr
        rendered = conf.read_text()
        assert "set $pw_sessions my-pw.svc.internal:8081;" in rendered
        assert "set $se_sessions my-se.svc.internal:8082;" in rendered
        assert "set $novnc_node playwright-chromium.svc.internal:7900;" in rendered

    def test_explicit_resolver_wins(self, tmp_path):
        proc, _, conf, _ = self._run(
            tmp_path, resolv=self.SEARCH_RESOLV, env={"GATEWAY_RESOLVER": "1.2.3.4"}
        )
        assert proc.returncode == 0, proc.stderr
        assert "resolver 1.2.3.4 valid=10s ipv6=off;" in conf.read_text()

    def test_base_path_prefix(self, tmp_path):
        proc, _, conf, _ = self._run(tmp_path, base="/gateway")
        assert proc.returncode == 0, proc.stderr
        rendered = conf.read_text()
        assert "return 308 /gateway/;" in rendered
        assert "location /gateway/view/ {" in rendered
        assert "location = /gateway/api/endpoints {" in rendered

    def test_injection_in_suffix_fails(self, tmp_path):
        proc, _, _, log = self._run(
            tmp_path, env={"GATEWAY_UPSTREAM_SUFFIX": "\nproxy_pass http://evil;"}
        )
        assert proc.returncode != 0
        assert "invalid upstream suffix" in proc.stderr
        assert not log.exists()

    def test_injection_in_resolver_fails(self, tmp_path):
        proc, _, _, log = self._run(tmp_path, env={"GATEWAY_RESOLVER": "1.1.1.1; }"})
        assert proc.returncode != 0
        assert "invalid resolver" in proc.stderr
        assert not log.exists()

    def test_nginx_t_failure_aborts_before_exec(self, tmp_path):
        proc, _, _, log = self._run(tmp_path, nginx_t_exit=1)
        assert proc.returncode != 0
        text = log.read_text()
        assert "nginx -t" in text
        assert "daemon off" not in text

    def test_invalid_base_path_fails(self, tmp_path):
        proc, _, _, log = self._run(tmp_path, base="/gate way")
        assert proc.returncode != 0
        assert "invalid GATEWAY_BASE_PATH" in proc.stderr
        assert not log.exists()

    def test_invalid_registry_fails(self, tmp_path):
        bad = "endpoints:\n  - id: X\n    label: x\n    framework: playwright\n    browser: b\n    novnc: {host: h}\n"
        proc, _, _, log = self._run(tmp_path, registry_text=bad)
        assert proc.returncode != 0
        assert "invalid id" in proc.stderr
        assert not log.exists()

    def test_bad_yaml_fails(self, tmp_path):
        proc, _, _, log = self._run(tmp_path, registry_text="endpoints: [")
        assert proc.returncode != 0
        assert not log.exists()


class TestUI:
    def test_index_uses_role_based_urls(self):
        text = INDEX.read_text()
        assert "/api/endpoints" in text
        assert "/view/${e.id}" in text
        assert "/vnc/${e.id}/" in text
        assert "innerHTML" not in text

    def test_view_derives_base_and_id_from_path(self):
        text = VIEW.read_text()
        assert "/api/endpoints" in text
        assert "/api/playwright/states" in text
        assert "e.storage_state.ids" in text
        assert 'method: "PUT"' in text
        assert "/view/" in text
        assert "/vnc/${e.id}/" in text
        assert "innerHTML" not in text

    def test_view_has_single_state_selector(self):
        # One selector serves both load and save; there is no separate
        # save-state control and no free-text file name.
        text = VIEW.read_text()
        assert text.count('id="state"') == 1
        assert 'id="savestate"' not in text
        assert 'title="Save session state to the selected state"' in text
        assert ">Save</button>" in text
        assert "Save state</button>" not in text

    def test_view_uses_id_resources_not_paths(self):
        # The UI must not fall back to the deprecated path-based API.
        text = VIEW.read_text()
        assert "/api/playwright/state-files" not in text
        assert "/save" not in text
        assert "savename" not in text

    def test_view_locks_state_selector_during_session(self):
        # The single selector is fixed from Open until Close, and the id
        # captured at Open (not the live DOM value) drives the session.
        text = VIEW.read_text()
        assert "setStateLocked" in text
        assert "opening" in text
        assert "const chosenStateId" in text
        assert '$("state").disabled = locked' in text
        # A curated id with no file opens fresh; Save can create it.
        assert "existingIds.includes(chosenStateId)" in text
        assert "opened fresh" in text

    def test_view_is_single_flight_and_ignores_stale_refreshes(self):
        text = VIEW.read_text()
        # Re-entrant Open is blocked and Open is disabled while in flight.
        assert "if (opening || sessionId) return" in text
        # A generation counter drops out-of-order session list responses,
        # and Open invalidates in-flight polls.
        assert "refreshSeq" in text
        # The POST response id is trusted so the lock survives a failed
        # follow-up list call; a 2xx without a usable id fails closed.
        assert "sessionKnown = true" in text
        assert "sessionKnown = false" in text
        assert "!data.id" in text
        # Start and ambiguous outcomes fail closed; confirmed outcomes apply
        # immediately without waiting for the next list GET.
        assert "applyUnknownSession()" in text
        assert "applySession()" in text
        assert "res.status >= 400 && res.status < 500" in text
        # Close is single-flight and multiple matching sessions stay
        # fail-closed instead of picking one arbitrarily.
        assert "if (closing || !sessionId) return" in text
        assert "multiple (" in text


class TestDockerfile:
    def test_base_and_entrypoint(self):
        text = DOCKERFILE.read_text()
        assert "FROM nginx:alpine" in text
        assert "apk add --no-cache jq yq-go" in text
        assert "RUN rm -f /etc/nginx/conf.d/default.conf" in text
        assert 'ENTRYPOINT ["/entrypoint.sh"]' in text
        assert "EXPOSE 80" in text
        assert "chmod +x /entrypoint.sh" in text
        assert "HEALTHCHECK" in text
        assert "/healthz" in text

    def test_copies_registry_generator_and_ui(self):
        text = DOCKERFILE.read_text()
        for line in (
            "COPY gateway/endpoints.yaml /etc/gateway/endpoints.yaml",
            "COPY gateway/generate.jq /usr/share/gateway/generate.jq",
            "COPY gateway/index.html /usr/share/nginx/html/index.html",
            "COPY gateway/view.html /usr/share/nginx/html/view.html",
        ):
            assert line in text, line
        assert "frameworks.json" not in text
        assert "nginx.conf.template" not in text

    def test_old_mounted_config_removed(self):
        assert not (GATEWAY / "nginx.conf").exists()
        assert not (GATEWAY / "render.jq").exists()
        assert not (GATEWAY / "frameworks.json").exists()
        assert not (GATEWAY / "nginx.conf.template").exists()


class TestCompose:
    def test_gateway_uses_dedicated_image(self):
        text = COMPOSE.read_text()
        assert "image: temeteke/pyscraper-gateway:latest" in text
        assert "dockerfile: Dockerfile.gateway" in text
        assert "./gateway/nginx.conf:" not in text

    def test_session_managers_published(self):
        text = COMPOSE.read_text()
        assert "image: temeteke/pyscraper-playwright-session-manager:latest" in text
        assert "image: temeteke/pyscraper-selenium-session-manager:latest" in text


class TestWorkflow:
    def test_gateway_and_session_managers_published(self):
        text = WORKFLOW.read_text()
        for image, suffix in (
            ("temeteke/pyscraper-gateway", "gateway"),
            ("temeteke/pyscraper-playwright-session-manager", "playwright-session-manager"),
            ("temeteke/pyscraper-selenium-session-manager", "selenium-session-manager"),
        ):
            assert f"image: {image}" in text, image
            assert f"suffix: {suffix}" in text, suffix

    def test_new_images_are_multi_arch(self):
        text = WORKFLOW.read_text()
        entries = re.findall(
            r"dockerfile: \./Dockerfile\.(gateway|playwright-session-manager|selenium-session-manager)\n"
            r"\s+image: [^\n]+\n"
            r"\s+suffix: [^\n]+\n"
            r"\s+platforms: ([^\n]+)",
            text,
        )
        assert {name for name, _ in entries} == {
            "gateway",
            "playwright-session-manager",
            "selenium-session-manager",
        }
        assert all(platforms.strip() == "linux/amd64,linux/arm64" for _, platforms in entries)


class TestTestsWorkflow:
    def test_yq_pinned_and_checksum_verified(self):
        text = TESTS_WORKFLOW.read_text()
        assert "YQ_VERSION=v4.53.3" in text
        assert "sha256sum -c -" in text
        assert "yq_linux_amd64" in text
