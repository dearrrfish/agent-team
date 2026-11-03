from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import tomllib
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_team.adapters import render_target
from agent_team.cli import _doctor, _install
from agent_team.config import (
    DEFAULT_TEAM_TOML,
    load_team_config,
    parse_team_config,
    resolve_target_profile,
)
from agent_team.config_editor import select_targets
from agent_team.diagnostics import ValidationFailure
from agent_team.models import TARGETS
from agent_team.pi_plugins import PiPluginStatus, require_pi_plugins, scan_pi_plugins


class PiSupportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.project = self.root / "project"
        self.home.mkdir()
        (self.project / ".agent-team").mkdir(parents=True)
        (self.project / ".agent-team/team.toml").write_text(
            'enabled_targets = ["codex", "pi"]\n', encoding="utf-8")
        for mocked in (patch("pathlib.Path.home", return_value=self.home),
                       patch.dict(os.environ, {"HOME": str(self.home)}, clear=True)):
            mocked.start()
            self.addCleanup(mocked.stop)

    def settings(self, packages, *, project=False, extensions=None):
        path = self.project / ".pi/settings.json" if project else self.home / ".pi/agent/settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {"packages": packages}
        if extensions is not None:
            value["extensions"] = extensions
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def test_opt_in_and_offline_render(self):
        config = parse_team_config(tomllib.loads(DEFAULT_TEAM_TOML), self.project)
        self.assertEqual(config.enabled_targets, ("codex", "claude", "antigravity"))
        self.assertIn("pi", TARGETS)
        config = replace(config, enabled_targets=("pi",))
        with patch("agent_team.pi_plugins.scan_pi_plugins", side_effect=AssertionError("render must not scan")):
            output = render_target("pi", config, self.project)
            self.assertEqual(output, render_target("pi", config, self.project))
        explorer = output[Path(".pi/agents/explorer.md")]
        self.assertIn('model: "openai/', explorer)
        self.assertIn(':medium"', explorer)
        tools = explorer.split("tools: ")[1].splitlines()[0].split(", ")
        self.assertFalse({"bash", "write", "edit", "web_search", "fetch_url"}.intersection(tools))
        self.assertIn("MCP tools may remain available", explorer)
        self.assertIn("worktree isolation is unconfirmed", explorer)
        self.assertIn("max", resolve_target_profile(config, "pi", self.project).effort_levels)
        self.assertTrue(any(str(path).startswith(".agents/skills/") for path in output))

    def test_render_maps_only_confirmed_standard_web_and_subagent_tools(self):
        config = load_team_config(self.project)
        status = PiPluginStatus("pi-subagents", True)
        output = render_target("pi", config, self.project, pi_status=status)
        for path, content in output.items():
            if str(path).startswith(".pi/agents/"):
                tools = content.split("tools: ")[1].splitlines()[0].split(", ")
                if path.stem in {"explorer", "design-agent", "reviewer"}:
                    self.assertFalse({"bash", "edit", "write"}.intersection(tools))
        coordinator = output[Path(".pi/agents/coordinator.md")]
        self.assertIn("subagent", coordinator.split("tools: ")[1].splitlines()[0])
        explorer = output[Path(".pi/agents/explorer.md")]
        self.assertIn("web_search, fetch_url", explorer)
        self.assertIn("supports `worktree: true`", explorer)
        self.assertIn("only after verifying", explorer)

    def test_flow_has_conditional_worktree_but_no_guessed_delegation_tool(self):
        config = load_team_config(self.project)
        output = render_target("pi", config, self.project,
                               pi_status=PiPluginStatus("pi-agents-flow"))
        coordinator = output[Path(".pi/agents/coordinator.md")]
        self.assertNotIn("subagent", coordinator.split("tools: ")[1].splitlines()[0])
        self.assertIn("configure the coordinator allowlist manually", coordinator)
        self.assertIn("supports `worktree: true`", coordinator)

    def test_exact_npm_identity_and_versions(self):
        for source in ("npm:pi-subagents", "npm:pi-subagents@1.2.3", "npm:pi-agents-flow@latest"):
            with self.subTest(source=source):
                self.settings([source, "npm:pi-web-access@2.0.0"])
                status = scan_pi_plugins(self.project)
                self.assertTrue(status.has_subagent)
                self.assertTrue(status.has_worktree)
                self.assertTrue(status.has_web)
        self.settings(["npm:pi-subagents-malicious", "npm:@other/pi-subagents", "./pi-subagents.ts", "npm:some-mcp"])
        status = scan_pi_plugins(self.project)
        self.assertFalse(status.has_subagent)
        self.assertFalse(status.has_web)
        self.assertFalse(status.has_worktree)
        self.assertTrue(any(d.code == "pi-custom-package" for d in status.diagnostics))

    def test_project_replacement_and_resource_filters(self):
        self.settings(["npm:pi-subagents@1", "npm:pi-web-access"])
        self.settings([{"source": "npm:pi-subagents@2", "extensions": []}], project=True)
        self.assertFalse(scan_pi_plugins(self.project).has_subagent)
        self.assertTrue(scan_pi_plugins(self.project, "user").has_subagent)
        for filters in (["extensions/*.ts"], ["!extensions/subagent.ts"], ["+index.ts"], ["-index.ts"]):
            self.settings([{"source": "npm:pi-subagents", "extensions": filters}], project=True)
            status = scan_pi_plugins(self.project)
            self.assertFalse(status.has_subagent)
            self.assertTrue(any(d.code == "pi-selector" for d in status.diagnostics))
        self.settings([{"source": "npm:pi-subagents", "skills": []}], project=True)
        self.assertTrue(scan_pi_plugins(self.project).has_subagent)

    def test_autoload_delta_never_introduces_or_reenables(self):
        self.settings([{"source": "npm:pi-subagents", "autoload": False}], project=True)
        self.assertFalse(scan_pi_plugins(self.project).has_subagent)
        self.settings(["npm:pi-subagents"])
        self.assertTrue(scan_pi_plugins(self.project).has_subagent)
        self.settings([{"source": "npm:pi-subagents", "autoload": False, "extensions": []}], project=True)
        self.assertFalse(scan_pi_plugins(self.project).has_subagent)
        self.settings([{"source": "npm:pi-subagents", "extensions": []}])
        self.settings([{"source": "npm:pi-subagents", "autoload": False}], project=True)
        self.assertFalse(scan_pi_plugins(self.project).has_subagent)

    def test_local_resources_and_exclusions_fail_closed(self):
        local = self.project / "subagent.ts"
        local.write_text('throw new Error("must not execute")', encoding="utf-8")
        self.settings([str(local)], extensions=[str(local)])
        self.assertFalse(scan_pi_plugins(self.project).has_subagent)
        self.settings(["npm:pi-subagents"], extensions=["!**/subagent.ts"])
        self.assertFalse(scan_pi_plugins(self.project).has_subagent)
        self.settings(["npm:pi-subagents"], extensions=["-builtin:mcp"])
        self.assertTrue(scan_pi_plugins(self.project).has_subagent)

    def test_invalid_settings_fail_with_actionable_diagnostic(self):
        path = self.settings([])
        for value in ('{', '[]', '{"packages": false}', '{"packages": [null]}',
                      '{"packages": [{"source": "npm:pi-subagents", "extensions": false}]}',
                      '{"extensions": [42]}'):
            path.write_text(value, encoding="utf-8")
            with self.subTest(value=value), self.assertRaises(ValidationFailure) as error:
                scan_pi_plugins(self.project)
            self.assertEqual(error.exception.diagnostics[0].code, "pi-settings")

    def test_install_gate_precedes_all_target_writes_including_preview(self):
        for apply in (False, True):
            args = argparse.Namespace(target="codex,pi", scope="project", run_slug=None,
                                      apply=apply, force=False)
            with self.subTest(apply=apply), self.assertRaises(ValidationFailure) as error:
                _install(self.project, args)
            self.assertIn("pi-missing-subagents", [d.code for d in error.exception.diagnostics])
            self.assertIn("pi install npm:pi-subagents", str(error.exception))
            for name in (".codex", ".agents", ".pi", ".agent-team/install-state.json"):
                self.assertFalse((self.project / name).exists())

    def test_install_uses_scanned_status_without_changing_settings(self):
        path = self.settings(["npm:pi-subagents", "npm:pi-web-access"])
        before = path.read_bytes()
        args = argparse.Namespace(target="codex,pi", scope="project", run_slug=None,
                                  apply=True, force=False)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(_install(self.project, args), 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertTrue((self.project / ".codex/agents/explorer.toml").is_file())
        self.assertIn("web_search, fetch_url", (self.project / ".pi/agents/explorer.md").read_text())

    def test_custom_agent_directory_scan_and_user_install_refusal(self):
        custom = self.root / "custom agent"
        custom.mkdir()
        (custom / "settings.json").write_text('{"packages": ["npm:pi-subagents"]}', encoding="utf-8")
        with patch.dict(os.environ, {"PI_CODING_AGENT_DIR": str(custom)}):
            status = scan_pi_plugins(self.project)
            self.assertTrue(status.has_subagent)
            with self.assertRaises(ValidationFailure) as error:
                require_pi_plugins(status, "user")
            self.assertEqual(error.exception.diagnostics[0].code, "pi-agent-directory")

    def test_config_editor_selects_pi_only_when_opted_in_and_installed(self):
        config = load_team_config(self.project)
        with patch("agent_team.config_editor.shutil.which", side_effect=lambda name: "/bin/pi" if name == "pi" else None):
            self.assertEqual(select_targets(config, None), ("pi",))
            self.assertEqual(select_targets(config, "pi"), ("pi",))
            with self.assertRaises(ValidationFailure):
                select_targets(replace(config, enabled_targets=("codex",)), "pi")

    def test_user_install_ignores_project_plugin_and_uses_native_user_paths(self):
        user = self.home / ".agent-team"
        user.mkdir()
        (user / "team.toml").write_text('enabled_targets = ["pi"]\n', encoding="utf-8")
        self.settings(["npm:pi-subagents"], project=True)
        args = argparse.Namespace(target="pi", scope="user", run_slug=None,
                                  apply=True, force=False)
        with self.assertRaises(ValidationFailure):
            _install(self.project, args)
        self.assertFalse((self.home / ".pi/agent/agents").exists())
        self.settings(["npm:pi-subagents"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(_install(self.project, args), 0)
        self.assertTrue((self.home / ".pi/agent/agents/coordinator.md").is_file())
        self.assertTrue((self.home / ".agents/skills/team-workflow/SKILL.md").is_file())

    def test_doctor_reports_pi_version_and_plugin_limitations(self):
        self.settings(["npm:pi-subagents"])
        version = __import__("subprocess").CompletedProcess(["pi", "--version"], 0, "1.4.0\n", "")
        with patch("agent_team.cli._collect_validation", return_value=[]), patch(
            "agent_team.cli.shutil.which", side_effect=lambda name: f"/bin/{name}"
        ), patch("agent_team.cli.subprocess.run", return_value=version) as run, redirect_stdout(io.StringIO()) as out:
            self.assertEqual(_doctor(self.project, "json"), 0)
        self.assertIn(["/bin/pi", "--version"], [call.args[0] for call in run.call_args_list])
        self.assertIn("pi-static-only", out.getvalue())


if __name__ == "__main__":
    unittest.main()
