# Project Agent Instructions

This repository dogfoods its own `agent-team` setup. All non-trivial work is
tracked via an `agent-team` run under `.agent-team/runs/<slug>/` governed by
the effective configuration in `.agent-team/team.toml` and user defaults.

## Configuration and Generated Files

- For shared user setup, run `agent-team init --scope user`, then preview or
  apply `agent-team install --scope user --target codex,claude,antigravity`.
  User installation reads `~/.agent-team/team.toml`; `--apply` writes native
  agents and skills into each client's user directories.
- Plain `agent-team init` creates sparse project overrides with live
  `builtin < user < project` configuration inheritance. Explicit
  `init --scope project` creates complete builtin defaults with
  `inherit_user_defaults = false`. Existing configurations are preserved.
- `init` manages configuration only. Run
  `agent-team generate gitignore,templates` for project ignore rules and stock
  prompts; either selector can be requested separately. Installation does not
  update `.gitignore`. Keep authored prompts outside the stock template paths.
- Use `install --scope project` for local native definitions. Multiple targets
  are comma-separated; `--run <slug>` is supported only in project scope.
  Reinstall native output after changing its effective configuration.
- User source paths are relative to `~/.agent-team`; project source paths are
  relative to the project root. Named roles and skills resolve as whole
  definitions with `project > user > builtin` priority. Native discovery rules
  remain client-specific; config isolation does not hide installed user agents.
- Runs, templates, and backups remain project-scoped. Forced user replacement
  requires an initialized project for backup storage. Preserve durable run
  evidence before removing a worktree.

## Workflow Tiers and Runs

- Use `team-workflow` to select and operate the smallest adequate tier:
  - `solo`: bounded coordinator work; no worker delegation.
  - `assisted`: up to two workers (primarily read-heavy); serialized writes.
  - `team`: up to four workers; task DAG; file-disjoint or worktree isolation;
    durable artifacts and independent review are mandatory.
- Initialize runs using `agent-team run init --slug <slug> [--tier <tier>]`
  (or `python -m agent_team run init ...`).
- The run manifest (`.agent-team/runs/<slug>/run.toml`) is authoritative for
  lifecycle state, gates, task dependencies, and concurrency limits.
- Markdown artifacts in the run directory (`requirements.md`, `plan.md`,
  `tasks.md`, `decisions.md`, `review.md`, `final-report.md`) are
  authoritative for rationale, contracts, evidence, and verdicts.
- Model routing is governed by target profiles and presets (`economy`,
  `balanced`, `quality`) from effective user/project configuration. Project
  profile references and sparse preset overrides take precedence over user
  values; complete profile files replace rather than merge. Inspect routing
  with `agent-team models show --format table` before selecting a run preset.

## Roles and Delegation

- The main thread acts as `coordinator`: aligns with the user, maintains run
  artifacts, delegates bounded tasks, and integrates evidence-backed results.
- Available native roles:
  - `explorer`: read-only codebase and factual discovery.
  - `design-agent`: read-only requirements and architectural audit.
  - `implementer`: bounded code changes and test verification.
  - `ops`: Nix, packaging, CI, and operational infrastructure.
  - `reviewer`: independent, read-only lifecycle review.
- Workers never delegate recursively.
- Read-only roles in Claude Code and Antigravity lack shell tools; run required
  commands through the coordinator or an authorized writer.
- Do not silently alter public interfaces, schemas, or lifecycle rules.

## Coordination and Review

- Use `team-plan` to produce a decision-complete plan before modifying code.
- Use `team-coordinate` to dispatch bounded tasks. Provide each worker its role,
  unique instance name, task ID, owned files, no-edit boundary, acceptance
  criteria, exact verification commands, and report path.
- Respect `write_isolation`: never run concurrent writers on overlapping files.
- Persist structured worker reports to `reports/` from the run template when
  `reports_required` is true.
- Use `team-review` for mandatory review gates. The reviewer must remain
  read-only, record findings and verdicts in `review.md`, and never author fixes.
  Review cycles cannot exceed the configured limit.

## Quality Gates and Verification

Run the applicable checks before claiming completion:

- Run and project validation: `PYTHONPATH=src python3 -m agent_team validate`
- Unit tests: `PYTHONPATH=src python3 -m unittest discover -s tests`
- Linting: `ruff check src tests`
- Diff check: `git diff --check`
- Nix flake check: `nix flake check path:.`

Keep detailed design and historical execution state in
`.agent-team/runs/<slug>/` rather than this file.
