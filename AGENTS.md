# Project Agent Instructions

This repository dogfoods its own `agent-team` setup. All non-trivial work is
tracked via an `agent-team` run under `.agent-team/runs/<slug>/` governed by
`.agent-team/team.toml`.

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
  `balanced`, `quality`) configured in `.agent-team/team.toml`.

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
