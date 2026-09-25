"""Unit tests for the console image: registry rendering and packaging.

The console is a dedicated nginx image whose entrypoint validates
``console/config.yaml`` with ``console/generate.jq`` (jq; YAML via yq) and
renders the nginx config and the UI's target list from it. These tests
cover the schema/validation rules, the rendered routing for empty and
non-empty base paths (including a real ``nginx -t`` when available), the
Dockerfile/CI wiring, and the UI wiring.

The rendering tests execute the real tools (yq/jq/nginx) and are skipped
when one is missing. ``subprocess.run`` is mocked by an autouse conftest
fixture, so the module opts out with ``no_mock_ffmpeg``.
"""

import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_mock_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
CONSOLE = ROOT / "console"
CONFIG = CONSOLE / "config.yaml"
GENERATE_JQ = CONSOLE / "generate.jq"
ENTRYPOINT = CONSOLE / "entrypoint.sh"
INDEX = CONSOLE / "index.html"
VIEW = CONSOLE / "view.html"
DOCKERFILE = ROOT / "Dockerfile.console"
COMPOSE = ROOT / "compose.yaml"
WORKFLOW = ROOT / ".github" / "workflows" / "docker.yml"
TESTS_WORKFLOW = ROOT / ".github" / "workflows" / "tests.yml"
SESSION_MANAGER = ROOT / "servers" / "playwright_session_manager.py"
SELENIUM_MANAGER = ROOT / "servers" / "selenium_session_manager.py"

# Context options with one valid value per allowlisted key. Kept in sync with
# servers/playwright_session_manager.py by TestContextOptionAllowlist.
CONTEXT_SAMPLE = {
    "locale": "ja-JP",
    "timezone_id": "Asia/Tokyo",
    "viewport": {"width": 800, "height": 600},
    "user_agent": "pyscraper-test",
    "color_scheme": "dark",
    "device_scale_factor": 1.5,
    "has_touch": True,
    "is_mobile": False,
    "extra_http_headers": {"X-Test": "1"},
}

SAMPLE_CONFIG = {
    "ui": {"columns": "auto", "group_by": "framework"},
    "context_options": {
        "locale": "ja-JP",
        "timezone_id": "Asia/Tokyo",
        "viewport": {"width": 1280, "height": 1024},
    },
    "targets": [
        {
            "id": "playwright-chromium",
            "label": "Chromium (Playwright)",
            "framework": "playwright",
            "browser": "playwright-chromium",
            "context_options": {"viewport": {"width": 1440, "height": 900}},
            "storage_state": {
                "states": [
                    {"id": "chromium", "label": "Chromium", "url": "https://example.com/?q=1"},
                    {"id": "alt"},
                ]
            },
            "novnc": {"host": "playwright-chromium", "port": 7900},
        },
        {
            "id": "selenium-chrome-profile",
            "label": "Chrome (profile)",
            "framework": "selenium",
            "browser": "selenium-chrome",
            "node": "chromium-profile",
            "group": "chrome",
            "novnc": {"host": "selenium-chrome-node"},
        },
    ],
}


def _require(*tools):
    missing = [t for t in tools if shutil.which(t) is None]
    if missing:
        pytest.skip(f"missing tools: {', '.join(missing)}")


def _entry(**over):
    """A minimal valid playwright target, overridable per test."""
    target = {
        "id": "pw",
        "framework": "playwright",
        "browser": "playwright-chromium",
    }
    target.update(over)
    return target


def _registry(targets, **over):
    registry = {"targets": targets}
    registry.update(over)
    return registry


def _jq_generate(
    tmp_path,
    registry,
    resolver="127.0.0.11",
    base="",
    suffix="",
    pw="playwright-session-manager",
    se="selenium-session-manager",
    rundir="/run/console",
):
    reg = tmp_path / "config.json"
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


def _jq_array(name):
    """Extract a quoted-string array literal from generate.jq (e.g. browsers)."""
    match = re.search(rf"def {name}: \[(.*?)\];", GENERATE_JQ.read_text(), re.S)
    assert match, f"def {name} not found in generate.jq"
    return re.findall(r'"([^"]+)"', match.group(1))


def _load_sm(monkeypatch, tmp_path):
    """Load servers/playwright_session_manager.py for model validation."""
    monkeypatch.setenv("SESSION_STATE_DIR", str(tmp_path))
    spec = importlib.util.spec_from_file_location("console_session_manager", SESSION_MANAGER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_entrypoint(
    tmp_path, registry_text=None, env=None, resolv=None, base="", nginx_t_exit=0, resolv_path=None
):
    """Run the real entrypoint with every path redirected into tmp_path.

    A stub ``nginx`` on PATH records its invocation and exits 0 (except
    ``nginx -t``, whose exit code is configurable), so the whole pipeline
    (yq -> jq -> nginx -t -> exec) is exercised. ``resolv_path`` points at a
    missing file (the default writes a resolv.conf under tmp_path).
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

    config = tmp_path / "config.yaml"
    config.write_text(registry_text if registry_text is not None else CONFIG.read_text())
    if resolv_path is None:
        resolv_file = tmp_path / "resolv.conf"
        resolv_file.write_text(
            resolv if resolv is not None else "nameserver 127.0.0.11\noptions ndots:0\n"
        )
    else:
        resolv_file = Path(resolv_path)

    run_env = {k: v for k, v in os.environ.items() if not k.startswith("CONSOLE_")}
    run_env["PATH"] = str(bindir) + os.pathsep + run_env.get("PATH", "")
    run_env.update(
        {
            "CONSOLE_CONFIG_FILE": str(config),
            "CONSOLE_GENERATE_JQ": str(GENERATE_JQ),
            "CONSOLE_RUN_DIR": str(tmp_path / "run"),
            "CONSOLE_NGINX_CONF": str(tmp_path / "console.conf"),
            "CONSOLE_RESOLV_CONF": str(resolv_file),
            "CONSOLE_BASE_PATH": base,
        }
    )
    if env:
        run_env.update(env)
    proc = subprocess.run(["sh", str(ENTRYPOINT)], env=run_env, capture_output=True, text=True)
    return proc, tmp_path / "run", tmp_path / "console.conf", log


class TestGenerateValidation:
    def test_valid_sample(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_CONFIG)
        assert set(out) == {"nginx", "config"}
        assert set(out["config"]) == {"ui", "targets"}

    def test_label_and_novnc_default_to_id(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, _registry([_entry()]))
        target = out["config"]["targets"][0]
        assert target["label"] == "pw"
        assert target["node"] is None
        assert target["group"] is None
        conf = out["nginx"]
        assert "set $novnc_node pw:7900;" in conf
        assert "location /vnc/pw/ {" in conf

    def test_explicit_label_and_novnc_win(self, tmp_path):
        _require("jq")
        out = _jq_ok(
            tmp_path,
            _registry([_entry(label="PW", novnc={"host": "pw-node", "port": 7901})]),
        )
        assert out["config"]["targets"][0]["label"] == "PW"
        assert "set $novnc_node pw-node:7901;" in out["nginx"]

    def test_state_label_and_url_defaults(self, tmp_path):
        _require("jq")
        out = _jq_ok(
            tmp_path,
            _registry([_entry(storage_state={"states": [{"id": "s1"}]})]),
        )
        assert out["config"]["targets"][0]["storage_state"] == {
            "states": [{"id": "s1", "label": "s1", "url": None}]
        }

    def test_legacy_ids_normalize_to_states(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, _registry([_entry(storage_state={"ids": ["s1", "s2"]})]))
        assert out["config"]["targets"][0]["storage_state"] == {
            "states": [
                {"id": "s1", "label": "s1", "url": None},
                {"id": "s2", "label": "s2", "url": None},
            ]
        }

    def test_omitted_storage_state_is_absent(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, _registry([_entry()]))
        assert "storage_state" not in out["config"]["targets"][0]

    def test_context_options_merge_key_by_key(self, tmp_path):
        _require("jq")
        out = _jq_ok(
            tmp_path,
            _registry(
                [
                    _entry(
                        context_options={
                            "viewport": {"width": 1440, "height": 900},
                            "locale": "en-US",
                        }
                    )
                ],
                context_options={"locale": "ja-JP", "timezone_id": "Asia/Tokyo"},
            ),
        )
        assert out["config"]["targets"][0]["context_options"] == {
            "locale": "en-US",
            "timezone_id": "Asia/Tokyo",
            "viewport": {"width": 1440, "height": 900},
        }

    def test_context_options_nested_values_replace_as_a_whole(self, tmp_path):
        # The merge is shallow: a target's nested object replaces the root's
        # instead of merging with it.
        _require("jq")
        out = _jq_ok(
            tmp_path,
            _registry(
                [
                    _entry(
                        context_options={
                            "extra_http_headers": {"X-Target": "2"},
                            "viewport": {"width": 800, "height": 600},
                        }
                    )
                ],
                context_options={
                    "extra_http_headers": {"X-Root": "1"},
                    "viewport": {"width": 1280, "height": 1024},
                },
            ),
        )
        options = out["config"]["targets"][0]["context_options"]
        assert options["extra_http_headers"] == {"X-Target": "2"}
        assert options["viewport"] == {"width": 800, "height": 600}

    def test_context_options_empty_for_playwright(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, _registry([_entry()]))
        assert out["config"]["targets"][0]["context_options"] == {}

    def test_float_numbers_are_normalized(self, tmp_path):
        # jq preserves "7900.0" literals: normalize to integers so nginx and
        # the session manager's strict int fields accept them.
        _require("jq")
        out = _jq_ok(
            tmp_path,
            _registry(
                [
                    _entry(
                        context_options={"viewport": {"width": 800.0, "height": 600.0}},
                        novnc={"host": "h", "port": 7900.0},
                    )
                ],
                ui={"columns": 4.0},
            ),
        )
        assert out["config"]["ui"]["columns"] == 4
        assert out["config"]["targets"][0]["context_options"]["viewport"] == {
            "width": 800,
            "height": 600,
        }
        assert "set $novnc_node h:7900;" in out["nginx"]
        assert "7900.0" not in out["nginx"]

    def test_normalized_context_options_validate_in_api(self, tmp_path, monkeypatch):
        _require("jq")
        out = _jq_ok(
            tmp_path,
            _registry(
                [
                    _entry(
                        context_options={
                            "locale": "ja-JP",
                            "viewport": {"width": 800.0, "height": 600.0},
                            "device_scale_factor": 1.5,
                            "color_scheme": "dark",
                        }
                    )
                ]
            ),
        )
        generated = out["config"]["targets"][0]["context_options"]
        assert generated["viewport"] == {"width": 800, "height": 600}
        sm = _load_sm(monkeypatch, tmp_path)
        options = sm.ContextOptions.model_validate(generated)
        assert options.viewport.width == 800
        assert options.viewport.height == 600

    def test_accepts_every_color_scheme(self, tmp_path):
        _require("jq")
        for scheme in ("light", "dark", "no-preference"):
            out = _jq_ok(
                tmp_path,
                _registry([_entry(context_options={"color_scheme": scheme})]),
            )
            assert out["config"]["targets"][0]["context_options"]["color_scheme"] == scheme

    def test_ui_defaults(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, _registry([_entry()]))
        assert out["config"]["ui"] == {
            "columns": "auto",
            "group_by": "none",
            "tile_min_width": 560,
            "tile_aspect": "16:9",
        }

    def test_ui_columns_integer(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, _registry([_entry()], ui={"columns": 4}))
        assert out["config"]["ui"]["columns"] == 4

    @pytest.mark.parametrize("columns", [1, 12])
    def test_ui_columns_bounds_accepted(self, tmp_path, columns):
        _require("jq")
        out = _jq_ok(tmp_path, _registry([_entry()], ui={"columns": columns}))
        assert out["config"]["ui"]["columns"] == columns

    @pytest.mark.parametrize(
        "ui, expected",
        [
            ({"tile_min_width": 160}, 160),
            ({"tile_min_width": 1920}, 1920),
            ({"tile_min_width": 480.0}, 480),
            ({"tile_aspect": "4:3"}, "4:3"),
            ({"tile_aspect": "16:10"}, "16:10"),
            ({"tile_aspect": "5:4"}, "5:4"),
        ],
    )
    def test_ui_tile_options_accepted(self, tmp_path, ui, expected):
        _require("jq")
        key = next(iter(ui))
        out = _jq_ok(tmp_path, _registry([_entry()], ui=ui))
        assert out["config"]["ui"][key] == expected

    @pytest.mark.parametrize(
        "ui, message",
        [
            ({"tile_min_width": "wide"}, "ui.tile_min_width must be an integer 160-1920"),
            ({"tile_min_width": 0}, "ui.tile_min_width must be an integer 160-1920"),
            ({"tile_min_width": 159}, "ui.tile_min_width must be an integer 160-1920"),
            ({"tile_min_width": 1921}, "ui.tile_min_width must be an integer 160-1920"),
            ({"tile_min_width": 1.5}, "ui.tile_min_width must be an integer 160-1920"),
            ({"tile_aspect": "21:9"}, "ui.tile_aspect must be one of"),
            ({"tile_aspect": ""}, "ui.tile_aspect must be one of"),
            ({"tile_aspect": 16}, "ui.tile_aspect must be one of"),
        ],
    )
    def test_rejects_bad_ui_tile_options(self, tmp_path, ui, message):
        _require("jq")
        proc = _jq_generate(tmp_path, _registry([_entry()], ui=ui))
        assert proc.returncode != 0
        assert message in proc.stderr

    def test_null_label_defaults_to_id(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, _registry([_entry(label=None)]))
        assert out["config"]["targets"][0]["label"] == "pw"

    def test_rejects_bad_root_context_options(self, tmp_path):
        _require("jq")
        for bad in ({"proxy": {"server": "http://x"}}, {"storage_state": {}}, {"bogus": 1}):
            proc = _jq_generate(tmp_path, _registry([_entry()], context_options=bad))
            assert proc.returncode != 0
            assert "unknown context_options keys" in proc.stderr

    def test_rejects_duplicate_states_form_across_targets(self, tmp_path):
        _require("jq")
        first = _entry(
            id="a", browser="playwright-chromium", storage_state={"states": [{"id": "s"}]}
        )
        second = _entry(
            id="b", browser="playwright-firefox", storage_state={"states": [{"id": "s"}]}
        )
        proc = _jq_generate(tmp_path, _registry([first, second]))
        assert proc.returncode != 0
        assert "duplicate storage_state id across targets: s" in proc.stderr

    @pytest.mark.parametrize(
        "registry, message",
        [
            ([], "must be a mapping"),
            ({"targets": [{"id": "x", "bogus": 1}]}, "unknown keys"),
            ({"targets": [_entry()], "ui": {"targets": []}}, "unknown ui keys"),
            ({}, "'targets' must be an array"),
            ({"targets": "x"}, "'targets' must be an array"),
            ({"targets": []}, "must not be empty"),
            ({"targets": [_entry()], "ui": []}, "ui must be a mapping"),
            ({"targets": [_entry()], "ui": {"bogus": 1}}, "unknown ui keys"),
            ({"targets": [_entry()], "ui": {"columns": "wide"}}, "ui.columns must be"),
            ({"targets": [_entry()], "ui": {"columns": 0}}, "ui.columns must be"),
            ({"targets": [_entry()], "ui": {"columns": 13}}, "ui.columns must be"),
            ({"targets": [_entry()], "ui": {"columns": 1.5}}, "ui.columns must be"),
            ({"targets": [_entry()], "ui": {"group_by": "browser"}}, "ui.group_by must be one of"),
        ],
    )
    def test_rejects_bad_console(self, tmp_path, registry, message):
        _require("jq")
        proc = _jq_generate(tmp_path, registry)
        assert proc.returncode != 0
        assert message in proc.stderr

    @pytest.mark.parametrize(
        "target, message",
        [
            ("x", "must be a mapping"),
            ({"id": "x", "bogus": 1}, "unknown keys"),
            ({"id": 1}, "id must be a string"),
            ({"id": "X"}, "invalid id"),
            ({"id": "a" * 64}, "id too long"),
            ({"id": "x\n"}, "invalid id"),
            ({"id": "x", "label": ""}, "label must be a non-empty"),
            ({"id": "x", "label": "a\nb"}, "label must not contain newlines"),
            ({"id": "x", "label": "a" * 65}, "label too long"),
            ({"id": "x", "label": 1}, "label must be a non-empty"),
            ({"id": "x", "framework": "puppeteer"}, "unknown framework"),
            ({"id": "x", "framework": 1}, "framework must be a string"),
            ({"id": "x", "browser": "playwright-opera"}, "unknown browser"),
            ({"id": "x", "browser": 1}, "browser must be a string"),
            (
                {"id": "x", "framework": "selenium", "browser": "playwright-chromium"},
                "does not match framework",
            ),
            (
                {"id": "x", "framework": "playwright", "browser": "selenium-chrome"},
                "does not match framework",
            ),
            ({"id": "x", "node": "$(evil)"}, "node must be null"),
            ({"id": "x", "node": "n\n"}, "node must be null"),
            ({"id": "x", "group": "bad group"}, "group must be null"),
            ({"id": "x", "group": "a" * 65}, "group must be null"),
        ],
    )
    def test_rejects_bad_target(self, tmp_path, target, message):
        _require("jq")
        target = dict(_entry(), **target) if isinstance(target, dict) else target
        proc = _jq_generate(tmp_path, _registry([target]))
        assert proc.returncode != 0
        assert message in proc.stderr

    def test_rejects_duplicate_id(self, tmp_path):
        _require("jq")
        proc = _jq_generate(tmp_path, _registry([_entry(), _entry()]))
        assert proc.returncode != 0
        assert "duplicate target id" in proc.stderr

    def test_rejects_duplicate_framework_browser_node(self, tmp_path):
        _require("jq")
        first = _entry(id="a", browser="playwright-chromium", node="n")
        second = _entry(id="b", browser="playwright-chromium", node="n")
        proc = _jq_generate(tmp_path, _registry([first, second]))
        assert proc.returncode != 0
        assert "duplicate (framework, browser, node)" in proc.stderr

    def test_rejects_context_options_for_selenium(self, tmp_path):
        _require("jq")
        target = _entry(
            framework="selenium",
            browser="selenium-chrome",
            context_options={"locale": "ja-JP"},
        )
        proc = _jq_generate(tmp_path, _registry([target]))
        assert proc.returncode != 0
        assert "context_options is only supported for playwright" in proc.stderr

    @pytest.mark.parametrize(
        "context_options, message",
        [
            ({"storage_state": {"cookies": []}}, "unknown context_options keys"),
            ({"proxy": {"server": "http://x"}}, "unknown context_options keys"),
            ({"bogus": 1}, "unknown context_options keys"),
            ({"locale": 1}, "locale must be a string"),
            ({"timezone_id": 1}, "timezone_id must be a string"),
            ({"user_agent": 1}, "user_agent must be a string"),
            ({"color_scheme": "auto"}, "color_scheme must be one of"),
            ({"device_scale_factor": 0}, "device_scale_factor must be a positive number"),
            ({"device_scale_factor": "2"}, "device_scale_factor must be a positive number"),
            ({"has_touch": "yes"}, "has_touch must be a boolean"),
            ({"is_mobile": "yes"}, "is_mobile must be a boolean"),
            ({"viewport": []}, "viewport must be a mapping"),
            ({"viewport": {"width": 0, "height": 1}}, "viewport.width must be a positive integer"),
            (
                {"viewport": {"width": 1.5, "height": 1}},
                "viewport.width must be a positive integer",
            ),
            ({"viewport": {"width": 1}}, "viewport.height must be a positive integer"),
            (
                {"viewport": {"width": 1, "height": -1}},
                "viewport.height must be a positive integer",
            ),
            (
                {"viewport": {"width": 1, "height": 1, "x": 1}},
                "unknown context_options.viewport keys",
            ),
            ({"extra_http_headers": []}, "extra_http_headers must be a mapping"),
            ({"extra_http_headers": {"X": 1}}, "extra_http_headers values must be strings"),
            ({"locale": "ja-JP", "storage_state": {}}, "unknown context_options keys"),
        ],
    )
    def test_rejects_bad_context_options(self, tmp_path, context_options, message):
        _require("jq")
        proc = _jq_generate(tmp_path, _registry([_entry(context_options=context_options)]))
        assert proc.returncode != 0
        assert message in proc.stderr

    @pytest.mark.parametrize(
        "storage_state, message",
        [
            (True, "storage_state must be a mapping"),
            (False, "storage_state must be a mapping"),
            (None, "storage_state must be a mapping"),
            ("x", "storage_state must be a mapping"),
            ({"enabled": True}, "unknown storage_state keys"),
            ({"bogus": 1}, "unknown storage_state keys"),
            ({"states": [], "ids": []}, "mutually exclusive"),
            ({"states": "x"}, "storage_state.states must be an array"),
            ({"states": ["x"]}, "storage_state.states[0] must be a mapping"),
            ({"states": [{"id": "x", "bogus": 1}]}, "unknown storage_state.states[0] keys"),
            ({"states": [{"id": "X"}]}, "invalid storage_state id"),
            ({"states": [{"id": "a" * 64}]}, "storage_state id too long"),
            ({"states": [{"id": "x", "label": ""}]}, "label must be a non-empty"),
            ({"states": [{"id": "x", "label": "a\nb"}]}, "label must not contain newlines"),
            ({"states": [{"id": "x", "label": "a" * 65}]}, "label too long"),
            ({"states": [{"id": "x", "url": 1}]}, "url must be a string"),
            ({"states": [{"id": "x", "url": "ftp://x"}]}, "url must be an http(s) URL"),
            (
                {"states": [{"id": "x", "url": "https://x/a\nb"}]},
                "url must not contain control characters",
            ),
            (
                {"states": [{"id": "x", "url": "https://x/a\x00b"}]},
                "url must not contain control characters",
            ),
            ({"states": [{"id": "x", "url": "https://x/" + "a" * 2048}]}, "url too long"),
            ({"states": [{"id": "a"}, {"id": "a"}]}, "duplicate storage_state id"),
            ({"ids": "x"}, "storage_state.ids must be an array"),
            ({"ids": [1]}, "storage_state.ids must be strings"),
            ({"ids": ["A"]}, "invalid storage_state id"),
            ({"ids": ["a" * 64]}, "storage_state id too long"),
            ({"ids": ["a", "a"]}, "duplicate storage_state id"),
        ],
    )
    def test_rejects_bad_storage_state(self, tmp_path, storage_state, message):
        _require("jq")
        proc = _jq_generate(tmp_path, _registry([_entry(storage_state=storage_state)]))
        assert proc.returncode != 0
        assert message in proc.stderr

    def test_rejects_storage_state_for_selenium(self, tmp_path):
        _require("jq")
        target = _entry(
            framework="selenium",
            browser="selenium-chrome",
            storage_state={"states": [{"id": "s"}]},
        )
        proc = _jq_generate(tmp_path, _registry([target]))
        assert proc.returncode != 0
        assert "storage_state is only supported for playwright" in proc.stderr

    def test_rejects_duplicate_state_id_across_targets(self, tmp_path):
        _require("jq")
        first = _entry(id="a", browser="playwright-chromium", storage_state={"ids": ["s"]})
        second = _entry(id="b", browser="playwright-firefox", storage_state={"ids": ["s"]})
        proc = _jq_generate(tmp_path, _registry([first, second]))
        assert proc.returncode != 0
        assert "duplicate storage_state id across targets: s" in proc.stderr

    @pytest.mark.parametrize(
        "novnc, message",
        [
            ([], "novnc must be a mapping"),
            (None, "novnc must be a mapping"),
            ({"host": "h", "extra": 1}, "unknown novnc keys"),
            ({"host": "h; }"}, "novnc.host must match"),
            ({"host": "h\n"}, "novnc.host must match"),
            ({"host": 1}, "novnc.host must be a string"),
            ({"host": "h", "port": "7900"}, "novnc.port must be an integer"),
            ({"host": "h", "port": 0}, "novnc.port must be an integer"),
            ({"host": "h", "port": 65536}, "novnc.port must be an integer"),
            ({"host": "h", "port": 7900.5}, "novnc.port must be an integer"),
        ],
    )
    def test_rejects_bad_novnc(self, tmp_path, novnc, message):
        _require("jq")
        proc = _jq_generate(tmp_path, _registry([_entry(novnc=novnc)]))
        assert proc.returncode != 0
        assert message in proc.stderr


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
            ({"rundir": "/run/console\n"}, "invalid run dir"),
            ({"rundir": "/run/console; evil"}, "invalid run dir"),
            ({"rundir": "/run console"}, "invalid run dir"),
            ({"rundir": "/run/../etc"}, "invalid run dir"),
            ({"rundir": "/run/console/.."}, "invalid run dir"),
            ({"rundir": "/run/./console"}, "invalid run dir"),
            ({"rundir": "/run//console"}, "invalid run dir"),
        ],
    )
    def test_rejects_unsafe_env_args(self, tmp_path, kwargs, message):
        _require("jq")
        proc = _jq_generate(tmp_path, SAMPLE_CONFIG, **kwargs)
        assert proc.returncode != 0
        assert message in proc.stderr


class TestGenerateNginx:
    def test_base_empty_locations(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_CONFIG)
        conf = out["nginx"]
        assert conf.startswith("# Generated by console/generate.jq")
        assert "resolver 127.0.0.11 valid=10s ipv6=off;" in conf
        assert "listen 80;" in conf
        # Dual-stack: the HEALTHCHECK resolves localhost, which may be ::1.
        assert "listen [::]:80;" in conf
        assert "location = /healthz {" in conf
        assert "location /view/ {" in conf
        assert "rewrite ^/view/.*$ /view.html last;" in conf
        assert "map $http_upgrade $connection_upgrade {" in conf
        assert "proxy_set_header Connection $connection_upgrade;" in conf
        assert 'proxy_set_header Connection "upgrade";' not in conf
        assert "location = /config.json {" in conf
        assert "alias /run/console/config.json;" in conf
        assert "default_type application/json;" in conf
        assert 'add_header Cache-Control "no-store" always;' in conf
        assert "location /api/playwright/ {" in conf
        assert "rewrite ^/api/playwright/(.*) /api/playwright/$1 break;" in conf
        assert "proxy_read_timeout 150s;" in conf
        assert "location /api/selenium/ {" in conf
        assert "location /vnc/playwright-chromium/ {" in conf
        assert "location = /vnc/playwright-chromium {" in conf
        assert "return 301 /vnc/playwright-chromium/;" in conf
        assert "rewrite ^/vnc/playwright-chromium/$ /vnc.html break;" in conf
        assert "rewrite ^/vnc/playwright-chromium/(.*) /$1 break;" in conf
        assert "set $novnc_node selenium-chrome-node:7900;" in conf
        assert "proxy_read_timeout 1d;" in conf
        assert "/api/endpoints" not in conf
        # nginx runtime vars are literal (no envsubst pass).
        assert "proxy_set_header Host $host;" in conf
        assert "proxy_set_header Upgrade $http_upgrade;" in conf
        assert "location = / {" not in conf  # no root redirect at the root base

    def test_base_non_empty_locations(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_CONFIG, base="/console", suffix=".svc.internal")
        conf = out["nginx"]
        assert "location = / {" in conf
        assert "return 308 /console/;" in conf
        # "/healthz" is base-independent.
        assert "location = /healthz {" in conf
        # "<base>" without the trailing slash must redirect, not 404.
        assert "location = /console {" in conf
        assert "location /console/ {" in conf
        assert "alias /usr/share/nginx/html/;" in conf
        assert "location /console/view/ {" in conf
        assert "rewrite ^/console/view/.*$ /console/view.html last;" in conf
        assert "location = /console/config.json {" in conf
        assert "rewrite ^/console/api/playwright/(.*) /api/playwright/$1 break;" in conf
        assert "location /console/vnc/playwright-chromium/ {" in conf
        assert "location = /console/vnc/playwright-chromium {" in conf
        assert "return 301 /console/vnc/playwright-chromium/;" in conf
        assert "set $novnc_node playwright-chromium.svc.internal:7900;" in conf
        assert "rewrite ^/console/vnc/playwright-chromium/(.*) /$1 break;" in conf

    def test_config_hides_novnc_and_keeps_ui_data(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_CONFIG)
        config = out["config"]
        assert config["ui"] == {
            "columns": "auto",
            "group_by": "framework",
            "tile_min_width": 560,
            "tile_aspect": "16:9",
        }
        targets = config["targets"]
        assert [t["id"] for t in targets] == [
            "playwright-chromium",
            "selenium-chrome-profile",
        ]
        for target in targets:
            assert "novnc" not in target
            assert "host" not in target and "port" not in target
        assert targets[0]["storage_state"] == {
            "states": [
                {"id": "chromium", "label": "Chromium", "url": "https://example.com/?q=1"},
                {"id": "alt", "label": "alt", "url": None},
            ]
        }
        assert targets[0]["context_options"]["viewport"] == {"width": 1440, "height": 900}
        assert targets[1]["node"] == "chromium-profile"
        assert targets[1]["group"] == "chrome"
        assert "context_options" not in targets[1]
        assert "storage_state" not in targets[1]

    def test_explicit_upstreams(self, tmp_path):
        _require("jq")
        out = _jq_ok(tmp_path, SAMPLE_CONFIG, suffix=".svc", pw="my-pw", se="my-se")
        conf = out["nginx"]
        assert "set $pw_sessions my-pw.svc:8081;" in conf
        assert "set $se_sessions my-se.svc:8082;" in conf

    @pytest.mark.parametrize(
        "base", ["/healthz", "/view", "/vnc", "/api", "/a/b", "/vnc/playwright-chromium"]
    )
    def test_base_variants_generate(self, tmp_path, base):
        # The role-based locations must not collide with /healthz, /api/...,
        # or each other for any accepted base path. The last one pins the
        # regression: `location = <base>` and `location = <base>/vnc/<id>`
        # are always distinct strings.
        _require("jq")
        conf = _jq_ok(tmp_path, SAMPLE_CONFIG, base=base)["nginx"]
        exacts = re.findall(r"location = ([^ ]+) \{", conf)
        assert len(exacts) == len(set(exacts))

    def test_prefix_collision_ids(self, tmp_path):
        # ``a`` and ``a-b`` must not shadow each other (trailing-slash
        # locations).
        _require("jq")
        targets = [
            _entry(id="a", browser="playwright-chromium"),
            _entry(id="a-b", browser="playwright-firefox"),
        ]
        conf = _jq_ok(tmp_path, _registry(targets))["nginx"]
        assert "location /vnc/a/ {" in conf
        assert "location /vnc/a-b/ {" in conf

    def test_underscore_in_upstream_and_host(self, tmp_path):
        # Compose service names may contain underscores.
        _require("jq")
        target = _entry(novnc={"host": "my_host"})
        conf = _jq_ok(tmp_path, _registry([target]), pw="my_pw", se="my_se")["nginx"]
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
        assert rendered.startswith("# Generated by console/generate.jq")
        assert "resolver 127.0.0.11 valid=10s ipv6=off;" in rendered
        assert "nginx -t" in log.read_text()

        config = json.loads((run_dir / "config.json").read_text())
        assert config["ui"] == {
            "columns": "auto",
            "group_by": "none",
            "tile_min_width": 560,
            "tile_aspect": "16:9",
        }
        targets = config["targets"]
        assert [t["id"] for t in targets] == [
            "selenium-chrome",
            "selenium-firefox",
            "playwright-chromium",
            "playwright-firefox",
            "playwright-webkit",
        ]
        by_id = {t["id"]: t for t in targets}
        assert by_id["playwright-chromium"]["framework"] == "playwright"
        assert by_id["playwright-chromium"]["storage_state"] == {
            "states": [{"id": "chromium", "label": "chromium", "url": None}]
        }
        assert by_id["selenium-chrome"]["framework"] == "selenium"
        assert "storage_state" not in by_id["selenium-chrome"]
        assert "context_options" not in by_id["selenium-chrome"]
        assert all(t["node"] is None for t in targets)

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
                "CONSOLE_UPSTREAM_SUFFIX": ".svc.internal",
                "CONSOLE_PW_SESSION": "my-pw",
                "CONSOLE_SE_SESSION": "my-se",
            },
        )
        assert proc.returncode == 0, proc.stderr
        rendered = conf.read_text()
        assert "set $pw_sessions my-pw.svc.internal:8081;" in rendered
        assert "set $se_sessions my-se.svc.internal:8082;" in rendered
        assert "set $novnc_node selenium-chrome-node.svc.internal:7900;" in rendered

    def test_explicit_resolver_wins(self, tmp_path):
        proc, _, conf, _ = self._run(
            tmp_path, resolv=self.SEARCH_RESOLV, env={"CONSOLE_RESOLVER": "1.2.3.4"}
        )
        assert proc.returncode == 0, proc.stderr
        assert "resolver 1.2.3.4 valid=10s ipv6=off;" in conf.read_text()

    def test_base_path_prefix(self, tmp_path):
        proc, _, conf, _ = self._run(tmp_path, base="/console")
        assert proc.returncode == 0, proc.stderr
        rendered = conf.read_text()
        assert "return 308 /console/;" in rendered
        assert "location /console/view/ {" in rendered
        assert "location = /console/config.json {" in rendered

    def test_base_path_trailing_slash_normalized(self, tmp_path):
        proc, _, conf, _ = self._run(tmp_path, base="/console/")
        assert proc.returncode == 0, proc.stderr
        rendered = conf.read_text()
        assert "location /console/ {" in rendered
        assert "location /console// {" not in rendered

    def test_missing_resolv_conf_fails(self, tmp_path):
        proc, _, _, log = self._run(tmp_path, resolv_path=tmp_path / "missing-resolv.conf")
        assert proc.returncode != 0
        assert "cannot read" in proc.stderr
        assert not log.exists()

    def test_injection_in_suffix_fails(self, tmp_path):
        proc, _, _, log = self._run(
            tmp_path, env={"CONSOLE_UPSTREAM_SUFFIX": "\nproxy_pass http://evil;"}
        )
        assert proc.returncode != 0
        assert "invalid upstream suffix" in proc.stderr
        assert not log.exists()

    def test_injection_in_resolver_fails(self, tmp_path):
        proc, _, _, log = self._run(tmp_path, env={"CONSOLE_RESOLVER": "1.1.1.1; }"})
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
        assert "invalid CONSOLE_BASE_PATH" in proc.stderr
        assert not log.exists()

    def test_invalid_registry_fails(self, tmp_path):
        bad = "targets:\n  - id: X\n    framework: playwright\n    browser: playwright-chromium\n"
        proc, _, _, log = self._run(tmp_path, registry_text=bad)
        assert proc.returncode != 0
        assert "invalid id" in proc.stderr
        assert not log.exists()

    def test_bad_yaml_fails(self, tmp_path):
        proc, _, _, log = self._run(tmp_path, registry_text="targets: [")
        assert proc.returncode != 0
        assert not log.exists()

    def test_multiple_documents_rejected(self, tmp_path):
        # yq emits one JSON value per document; jq -f would process each
        # separately, so two documents would concatenate two nginx configs
        # and an invalid config.json.
        multi = (
            "targets:\n  - id: a\n    framework: playwright\n"
            "    browser: playwright-chromium\n"
            "---\n"
            "targets:\n  - id: b\n    framework: playwright\n"
            "    browser: playwright-firefox\n"
        )
        proc, run_dir, conf, log = self._run(tmp_path, registry_text=multi)
        assert proc.returncode != 0
        assert "single YAML document" in proc.stderr
        # The debug-level intermediate is written before the document check;
        # nothing generated from it may exist.
        assert (run_dir / "source.json").exists()
        assert not (run_dir / "generated.json").exists()
        assert not (run_dir / "config.json").exists()
        assert not conf.exists()
        assert not log.exists()

    def test_invalid_run_dir_creates_nothing(self, tmp_path):
        # The run dir is validated before mkdir: a rejected value must not
        # create a directory (or source.json) first.
        escaped = tmp_path / "escaped"
        proc, run_dir, _, log = self._run(
            tmp_path, env={"CONSOLE_RUN_DIR": str(tmp_path / "x" / ".." / "escaped")}
        )
        assert proc.returncode != 0
        assert "invalid CONSOLE_RUN_DIR" in proc.stderr
        assert not escaped.exists()
        assert not run_dir.exists()
        assert not log.exists()

    def test_relative_run_dir_rejected(self, tmp_path):
        proc, _, _, log = self._run(tmp_path, env={"CONSOLE_RUN_DIR": "run"})
        assert proc.returncode != 0
        assert "invalid CONSOLE_RUN_DIR" in proc.stderr
        assert not log.exists()

    def test_double_slash_run_dir_rejected_without_creating(self, tmp_path):
        # NOTE: raw string concatenation, not tmp_path / "...": pathlib
        # would normalize the double slash away.
        created = tmp_path / "run"
        proc, _, _, log = self._run(tmp_path, env={"CONSOLE_RUN_DIR": str(tmp_path) + "/run//sub"})
        assert proc.returncode != 0
        assert "invalid CONSOLE_RUN_DIR" in proc.stderr
        assert not created.exists()
        assert not log.exists()

    def test_dot_run_dir_rejected_without_creating(self, tmp_path):
        # NOTE: pathlib drops "." segments, so concatenate raw strings.
        created = tmp_path / "run"
        proc, _, _, log = self._run(
            tmp_path, env={"CONSOLE_RUN_DIR": str(tmp_path) + "/run/./sub"}
        )
        assert proc.returncode != 0
        assert "invalid CONSOLE_RUN_DIR" in proc.stderr
        assert not created.exists()
        assert not log.exists()

    @pytest.mark.parametrize("run_dir", ["/run/x\\c", "/run/x%s"])
    def test_rejected_run_dir_printed_literally(self, tmp_path, run_dir):
        # The error must print the value verbatim (old echo would truncate
        # at \c); printf keeps it in a %s argument.
        proc, _, _, log = self._run(tmp_path, env={"CONSOLE_RUN_DIR": run_dir})
        assert proc.returncode != 0
        assert run_dir in proc.stderr
        assert not log.exists()

    def test_carriage_return_run_dir_rejected_without_creating(self, tmp_path):
        # Outside generate.jq's character class: rejected by the shell check
        # before mkdir.
        created = tmp_path / "run\rdir"
        proc, _, _, log = self._run(tmp_path, env={"CONSOLE_RUN_DIR": str(created)})
        assert proc.returncode != 0
        assert "invalid CONSOLE_RUN_DIR" in proc.stderr
        assert not created.exists()
        assert not log.exists()

    def test_lone_root_run_dir_rejected(self, tmp_path):
        # "/" alone is outside /[A-Za-z0-9._/-]+ (needs 1+ chars after /).
        proc, _, _, log = self._run(tmp_path, env={"CONSOLE_RUN_DIR": "/"})
        assert proc.returncode != 0
        assert "invalid CONSOLE_RUN_DIR" in proc.stderr
        assert not log.exists()

    def test_trailing_slash_run_dir_accepted(self, tmp_path):
        # A trailing slash is inside the character class and has no
        # empty/dot segments: shell and jq both accept it. The generated
        # nginx conf then carries a harmless double slash (the kernel
        # resolves it the same), which this pins.
        run_dir = tmp_path / "run"
        proc, _, conf, log = self._run(tmp_path, env={"CONSOLE_RUN_DIR": str(run_dir) + "/"})
        assert proc.returncode == 0, proc.stderr
        assert (run_dir / "config.json").exists()
        assert f"alias {run_dir}//config.json;" in conf.read_text()
        assert "nginx -t" in log.read_text()

    @pytest.mark.parametrize(
        "run_dir, expected",
        [
            # Same character rule as generate.jq (/[A-Za-z0-9._/-]+): blank,
            # tab and newline must fail before mkdir touches the filesystem.
            ("trailing-blank ", "trailing-blank "),
            ("tab\tdir", "tab\tdir"),
            ("newline\ndir", "newline\ndir"),
        ],
    )
    def test_blank_run_dir_rejected_without_creating(self, tmp_path, run_dir, expected):
        created = tmp_path / expected
        proc, _, _, log = self._run(tmp_path, env={"CONSOLE_RUN_DIR": str(created)})
        assert proc.returncode != 0
        assert "invalid CONSOLE_RUN_DIR" in proc.stderr
        assert not created.exists()
        assert not log.exists()


class TestNginxSyntax:
    """Run the generated config through a real ``nginx -t`` when available."""

    def _nginx_t(self, tmp_path, base):
        _require("jq", "nginx")
        conf = tmp_path / "console.conf"
        conf.write_text(_jq_ok(tmp_path, SAMPLE_CONFIG, base=base)["nginx"])
        wrapper = tmp_path / "nginx.conf"
        wrapper.write_text(
            "worker_processes 1;\n"
            "error_log stderr;\n"
            f"pid {tmp_path}/nginx.pid;\n"
            "events { worker_connections 16; }\n"
            "http {\n"
            "    access_log off;\n"
            f"    include {conf};\n"
            "}\n"
        )
        return subprocess.run(
            ["nginx", "-t", "-p", str(tmp_path), "-c", str(wrapper)],
            capture_output=True,
            text=True,
        )

    @pytest.mark.parametrize("base", ["", "/console", "/healthz", "/vnc/playwright-chromium"])
    def test_generated_config_passes_nginx_t(self, tmp_path, base):
        proc = self._nginx_t(tmp_path, base)
        assert proc.returncode == 0, proc.stderr
        assert "test is successful" in proc.stderr

    def test_base_healthz_has_single_exact_location(self, tmp_path):
        # The "<base> redirect" must not duplicate the exact /healthz block.
        _require("jq")
        conf = _jq_ok(tmp_path, SAMPLE_CONFIG, base="/healthz")["nginx"]
        assert conf.count("location = /healthz {") == 1
        assert "location /healthz/ {" in conf


class TestUI:
    def test_index_uses_config_json_and_role_urls(self):
        text = INDEX.read_text()
        assert "<title>Console</title>" in text
        assert "<h1" not in text
        assert "/config.json" in text
        assert "/api/endpoints" not in text
        assert "/view/${e.id}" in text
        assert "/vnc/${e.id}/" in text
        assert "innerHTML" not in text

    def test_index_supports_columns_and_grouping(self):
        text = INDEX.read_text()
        assert "group_by" in text
        assert "groupKey" in text
        assert "gridTemplateColumns" in text

    def test_index_applies_configured_tile_geometry(self):
        # The grid min width and the iframe aspect come from ui.tile_* so
        # both are configurable; the static CSS just carries the defaults.
        text = INDEX.read_text()
        assert "tile_min_width" in text
        assert "tile_aspect" in text
        assert "aspectRatio" in text
        assert "aspect-ratio: 16 / 9" in text
        assert "minmax(${minWidth}px, 1fr)" in text

    def test_index_lazy_loads_iframes(self):
        text = INDEX.read_text()
        assert "IntersectionObserver" in text
        assert "dataset.src" in text
        # Graceful fallback when IntersectionObserver is unavailable.
        assert 'typeof IntersectionObserver === "undefined"' in text

    def test_index_rejects_malformed_session_lists(self):
        # A 200 whose body has no sessions array (or entries without a string
        # id) must render an error badge, never an unchecked "closed".
        text = INDEX.read_text()
        assert "malformed session list" in text
        assert "malformed session entry" in text
        assert "Array.isArray(data.sessions)" in text

    def test_view_reads_config_and_state_states(self):
        text = VIEW.read_text()
        assert "/config.json" in text
        assert "/api/endpoints" not in text
        assert "/api/playwright/states" in text
        assert "e.storage_state.states" in text
        assert "context_options" in text
        assert 'method: "PUT"' in text
        assert 'method: "DELETE"' in text
        assert "innerHTML" not in text

    def test_view_prefills_url_from_state(self):
        text = VIEW.read_text()
        assert "URLSearchParams" in text
        assert "REQUESTED_STATE" in text
        assert "prefillUrl" in text
        assert '$("url").value' in text
        # The select shows labels but carries ids.
        assert "s.label || s.id" in text

    def test_view_confirms_unsaved_close(self):
        text = VIEW.read_text()
        assert "State has not been saved. Close anyway?" in text
        # saved is tracked per session id, and only the page that opened the
        # session with a selected state asks.
        assert "savedFor" in text
        assert "sessionStateId" in text

    def test_view_handles_unknown_state_list(self):
        # A failed GET /states must not silently skip a saved state: the
        # list stays unknown and the fresh open is announced.
        text = VIEW.read_text()
        assert "existingIds = null" in text
        assert "existingIds === null" in text
        assert "Could not check saved state" in text
        assert "if (ids !== null) existingIds = ids" in text

    def test_view_rejects_malformed_session_lists(self):
        # Same as the index: an unchecked or malformed 200 must fail to the
        # unknown path, never to an assumed "no session".
        text = VIEW.read_text()
        assert "malformed session list" in text
        assert "malformed session entry" in text
        assert "Array.isArray(data.sessions)" in text

    def test_view_save_is_single_flight(self):
        text = VIEW.read_text()
        assert "let saving = false" in text
        assert "if (saving || closing || !sessionId) return" in text
        # The save target is captured up front so a concurrent refresh cannot
        # make a different session look saved.
        assert "const targetSessionId = sessionId;" in text
        assert "if (sessionId === targetSessionId) savedFor = targetSessionId;" in text

    def test_view_blocks_open_while_session_list_unknown(self):
        # After the first successful list, a later failure still keeps Open
        # disabled so a session opened elsewhere cannot be duplicated.
        text = VIEW.read_text()
        assert "let listUnknown = false" in text
        assert "listUnknown = true" in text
        assert "|| !!sessionId || unknown" in text

    def test_view_keeps_owned_session_closable(self):
        # An ambiguous list must not orphan the session this page opened:
        # Close stays available for the id from our own Open response.
        text = VIEW.read_text()
        assert "let ownedSessionId = null" in text
        assert "ownedSessionId = data.id" in text
        assert "const target = sessionId || ownedSessionId" in text
        assert '$("close").disabled = !ownedSessionId' in text

    def test_view_uses_id_resources_not_paths(self):
        # The UI must not fall back to the removed path-based API.
        text = VIEW.read_text()
        assert "/api/playwright/state-files" not in text
        assert "/save" not in text
        assert "savename" not in text

    def test_view_locks_state_selector_during_session(self):
        # The selected state is fixed from Open until Close, and the id
        # captured at Open (not the live DOM value) drives the session.
        text = VIEW.read_text()
        assert "setStateLocked" in text
        assert "opening" in text
        assert "const chosenStateId" in text
        assert '$("state").disabled = locked' in text
        # A configured id with no file opens fresh; Save can create it.
        assert "existingIds.includes(chosenStateId)" in text
        assert "opened fresh" in text

    def test_view_is_single_flight_and_ignores_stale_refreshes(self):
        text = VIEW.read_text()
        # Re-entrant Open is blocked and Open is disabled while in flight.
        assert "if (opening || closing || saving || sessionId) return" in text
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
        # Close is single-flight (on the session being closed) and multiple
        # matching sessions stay fail-closed instead of picking one.
        assert "if (closing || saving || !target) return" in text
        assert "multiple (" in text


class TestContextOptionAllowlist:
    """The registry allowlist and the API model must not drift apart."""

    @staticmethod
    def _model_fields():
        tree = ast.parse(SESSION_MANAGER.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "ContextOptions":
                return {
                    stmt.target.id
                    for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                }
        raise AssertionError("ContextOptions class not found")

    def test_jq_allowlist_matches_model(self):
        keys = _jq_array("context_keys")
        assert len(keys) == len(set(keys))
        assert set(keys) == self._model_fields()

    def test_jq_accepts_every_api_field(self, tmp_path):
        _require("jq")
        assert self._model_fields() == set(CONTEXT_SAMPLE)
        out = _jq_ok(tmp_path, _registry([_entry(context_options=CONTEXT_SAMPLE)]))
        assert out["config"]["targets"][0]["context_options"] == CONTEXT_SAMPLE

    @pytest.mark.parametrize("key", ["storage_state", "proxy", "bogus"])
    def test_jq_rejects_non_context_keys(self, tmp_path, key):
        _require("jq")
        proc = _jq_generate(tmp_path, _registry([_entry(context_options={key: {}})]))
        assert proc.returncode != 0
        assert "unknown context_options keys" in proc.stderr


class TestBrowserEnumSync:
    """generate.jq's browser enum must cover both session managers exactly."""

    @staticmethod
    def _playwright_browsers():
        tree = ast.parse(SESSION_MANAGER.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                getattr(target, "id", None) == "PLAYWRIGHT_BROWSERS" for target in node.targets
            ):
                return {key.value for key in node.value.keys}
        raise AssertionError("PLAYWRIGHT_BROWSERS not found")

    @staticmethod
    def _selenium_browsers():
        tree = ast.parse(SELENIUM_MANAGER.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "OpenRequest":
                for stmt in node.body:
                    if (
                        isinstance(stmt, ast.AnnAssign)
                        and getattr(stmt.target, "id", None) == "browser"
                        and isinstance(stmt.annotation, ast.Subscript)
                        and getattr(stmt.annotation.value, "id", None) == "Literal"
                    ):
                        return {elt.value for elt in stmt.annotation.slice.elts}
        raise AssertionError("selenium OpenRequest.browser Literal not found")

    def test_enums_match(self):
        expected = self._playwright_browsers() | self._selenium_browsers()
        assert set(_jq_array("browsers")) == expected


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
            "COPY console/config.yaml /etc/console/config.yaml",
            "COPY console/generate.jq /usr/share/console/generate.jq",
            "COPY console/index.html /usr/share/nginx/html/index.html",
            "COPY console/view.html /usr/share/nginx/html/view.html",
        ):
            assert line in text, line
        assert "frameworks.json" not in text
        assert "nginx.conf.template" not in text

    def test_old_mounted_config_removed(self):
        assert not (CONSOLE / "nginx.conf").exists()
        assert not (CONSOLE / "render.jq").exists()
        assert not (CONSOLE / "frameworks.json").exists()
        assert not (CONSOLE / "nginx.conf.template").exists()
        assert not (CONSOLE / "endpoints.yaml").exists()


class TestCompose:
    def test_console_uses_dedicated_image(self):
        text = COMPOSE.read_text()
        assert "image: temeteke/pyscraper-console:latest" in text
        assert "dockerfile: Dockerfile.console" in text
        assert "./gateway/nginx.conf:" not in text
        assert "pyscraper-gateway" not in text
        assert "  gateway:" not in text

    def test_session_managers_published(self):
        text = COMPOSE.read_text()
        assert "image: temeteke/pyscraper-playwright-session-manager:latest" in text
        assert "image: temeteke/pyscraper-selenium-session-manager:latest" in text


class TestWorkflow:
    def test_console_and_session_managers_published(self):
        text = WORKFLOW.read_text()
        for image, suffix in (
            ("temeteke/pyscraper-console", "console"),
            ("temeteke/pyscraper-playwright-session-manager", "playwright-session-manager"),
            ("temeteke/pyscraper-selenium-session-manager", "selenium-session-manager"),
        ):
            assert f"image: {image}" in text, image
            assert f"suffix: {suffix}" in text, suffix
        assert "temeteke/pyscraper-gateway" not in text

    def test_new_images_are_multi_arch(self):
        text = WORKFLOW.read_text()
        entries = re.findall(
            r"dockerfile: \./Dockerfile\.(console|playwright-session-manager|selenium-session-manager)\n"
            r"\s+image: [^\n]+\n"
            r"\s+suffix: [^\n]+\n"
            r"\s+platforms: ([^\n]+)",
            text,
        )
        assert {name for name, _ in entries} == {
            "console",
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
        assert ".[console]" in text

    def test_nginx_installed_for_syntax_check(self):
        text = TESTS_WORKFLOW.read_text()
        assert "apt-get install -y -qq nginx" in text
