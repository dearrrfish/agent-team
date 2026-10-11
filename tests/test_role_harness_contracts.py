from __future__ import annotations

import json
import re
import tempfile
import tomllib
import unittest
from dataclasses import replace
from pathlib import Path, PurePosixPath

from agent_team.adapters import render_target
from agent_team.config import DEFAULT_TEAM_TOML, load_builtin_roles, parse_team_config
from agent_team.models import PRESETS, TARGETS, TeamConfig
from agent_team.runs import init_run, validate_run
from agent_team.templates import asset_text, render_template


def completed_template(content: str) -> str:
    return re.sub(r"<!--\s*REQUIRED:.*?-->", "None", content, flags=re.DOTALL)


def agent_content(
    output: dict[PurePosixPath, str], target: str, role: str,
) -> tuple[dict, str]:
    suffix = f"/{role}/agent.md" if target == "antigravity" else f"/{role}.md"
    if target == "codex":
        suffix = f"/{role}.toml"
    content = next(value for path, value in output.items() if str(path).endswith(suffix))
    if target == "codex":
        header = tomllib.loads(content)
        return header, header["developer_instructions"]
    frontmatter, _, instructions = content.removeprefix("---\n").partition("\n---\n")
    header = dict(line.split(": ", 1) for line in frontmatter.splitlines())
    return header, instructions


class RoleHarnessContractsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = parse_team_config(tomllib.loads(DEFAULT_TEAM_TOML), self.root)

    def reviewed_run(self, verdict: str, slug: str) -> tuple[Path, TeamConfig]:
        config = replace(self.config, tiers={
            **self.config.tiers,
            "solo": replace(self.config.tiers["solo"], independent_review=True),
        })
        run = init_run(self.root, config, slug, None, "solo", "balanced")
        manifest = run / "run.toml"
        content = manifest.read_text().replace('status = "discovery"', 'status = "reviewing"')
        content = content.replace("used = 0", "used = 1")
        content = content.replace('verdict = "pending"', f'verdict = "{verdict}"')
        content = content.replace('worktree_decision = "pending"',
                                  'worktree_decision = "current-checkout"')
        for gate in ("requirements", "plan", "worktree"):
            content = content.replace(f"{gate} = false", f"{gate} = true")
        manifest.write_text(content)
        for name in ("requirements.md", "plan.md", "review.md"):
            path = run / name
            content = completed_template(path.read_text())
            if name == "review.md":
                content = content.replace("- Verdict: pending", f"- Verdict: {verdict}")
            path.write_text(content)
        return manifest, config

    def test_generated_review_verdicts_persist_without_normalization(self) -> None:
        sources = [asset_text("templates", "prompts", "review.md")]
        for target in TARGETS:
            for preset in PRESETS:
                output = render_target(target, self.config, self.root, preset)
                _, instructions = agent_content(output, target, "reviewer")
                sources.append(instructions)
        for index, source in enumerate(sources):
            match = re.search(
                r"\b(approve(?:d)?),\s+(changes-requested),\s+or\s+(blocked)\b",
                source.replace("`", ""),
            )
            self.assertIsNotNone(match)
            for verdict in match.groups():
                with self.subTest(source=index, verdict=verdict):
                    manifest, config = self.reviewed_run(verdict, f"review-{index}-{verdict}")
                    errors = [item for item in validate_run(manifest, config)
                              if item.severity == "error"]
                    self.assertEqual([], errors)

    def test_legacy_approve_cannot_satisfy_review_contract(self) -> None:
        manifest, config = self.reviewed_run("approve", "legacy-verdict")
        self.assertTrue(any(item.code == "enum" and item.path.endswith("review.verdict")
                            for item in validate_run(manifest, config)))

    def test_readonly_report_template_remains_schema_compatible(self) -> None:
        run = init_run(self.root, self.config, "readonly-report", None, "assisted", "balanced")
        report = render_template(asset_text("templates", "workflow", "agent-report.md.tpl"), {
            "slug": "readonly-report", "updated_at": "2026-10-11T00:00:00Z",
            "task_id": "T-001", "role": "explorer",
        })
        (run / "reports" / "T-001-explorer.md").write_text(completed_template(report))
        manifest = run / "run.toml"
        with manifest.open("a") as handle:
            handle.write('''\n[[tasks]]
id = "T-001"
group = "TG-01"
role = "explorer"
instance = "map-entrypoint"
status = "complete"
deps = []
report = "reports/T-001-explorer.md"
''')
        errors = [item for item in validate_run(manifest, self.config) if item.severity == "error"]
        self.assertEqual([], errors)
        readonly = [role for role in load_builtin_roles() if role.write_policy == "deny"]
        for target in TARGETS:
            output = render_target(target, self.config, self.root)
            for role in readonly:
                with self.subTest(target=target, role=role.role_id):
                    header, instructions = agent_content(output, target, role.role_id)
                    self.assertIn("do not write report files", instructions)
                    if target == "codex":
                        self.assertEqual("read-only", header["sandbox_mode"])
                    elif target == "claude":
                        self.assertEqual("plan", header["permissionMode"])
                        self.assertEqual(role.max_turns, int(header["maxTurns"]))
                        self.assertTrue({"Write", "Edit", "Bash", "Agent"}.isdisjoint(
                            header["tools"].split(", ")))
                    else:
                        self.assertTrue({"write_to_file", "replace_file_content", "run_command",
                                         "invoke_subagent"}.isdisjoint(json.loads(header["tools"])))

    def test_custom_role_gets_budget_and_partial_handoff_contract(self) -> None:
        source = self.root / "roles" / "researcher"
        source.mkdir(parents=True)
        metadata = asset_text("definitions", "roles", "explorer", "role.toml")
        source.joinpath("role.toml").write_text(
            metadata.replace('id = "explorer"', 'id = "researcher"')
            .replace("max_turns = 16", "max_turns = 2"))
        source.joinpath("instructions.md").write_text("Return authorized research.\n")
        config = replace(self.config, role_sources=("builtin:roles", "roles"))
        for target in TARGETS:
            with self.subTest(target=target):
                output = render_target(target, config, self.root)
                header, instructions = agent_content(output, target, "researcher")
                self.assertIn("at most 2 turns", instructions)
                self.assertIn("return partial results", instructions)
                self.assertIn("do not write report files", instructions)
                self.assertNotIn("Finish within", instructions)
                if target == "claude":
                    self.assertEqual(2, int(header["maxTurns"]))


if __name__ == "__main__":
    unittest.main()
