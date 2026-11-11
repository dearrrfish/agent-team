# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.0] - 2026-11-11

### Added

- Four new standard workflow skills:
  - `team-debug`: Reproduce-first methodology, evidence-based hypothesis
    testing, test scaffolding volume limit (<= 50%), and original failure input
    regression verification.
  - `team-research`: Read-only/sandboxed discovery, strict fact versus inference
    demarcation, and structured decision packs.
  - `team-docs`: Contract change synchronization, runnable command and example
    verification in real environments, and architecture decision records
    (ADRs).
  - `team-ops`: Nix and flake integrity gates, drift and installation
    management, platform/CI verification, and clean workspace hygiene.
- Main-thread coordinator activation choices and anti-involution circuit
  breakers (no recursive planning, scaffolding volume cap <= 50%, consecutive
  non-product run halting) embedded in standard skills (`team-plan`,
  `team-coordinate`, `team-review`).

### Changed

- Converged workflow prompts into native skills: `agent-team generate templates`
  focuses purely on configuration and scaffolding examples (`profile/`,
  `role/`, `review/`) and stops generating redundant stock prompt files.
- Normalized generated template directories to singular form (`profile/`,
  `role/`, `review/`), removing historical duplicate plural forms (`profiles/`,
  `roles/`, `prompts/`).
- Updated Homebrew formula with verified archive digests and strict lag bounds.

## [0.5.1] - 2026-11-02

### Fixed

- Resolved Ruff import sorting and syntax checks in `checkPhase` to allow clean
  Nix builds and profile upgrades.
- Added explicit `[tool.ruff]` configuration to `pyproject.toml`.

## [0.5.0] - 2026-11-02

### Added

- Opt-in `pi` target support with zero-vendoring plugin preflight and pure
  Agent Markdown rendering across all standard roles and workflow skills.
- Graduated plugin installation gates for `pi`: hard blocking when subagent
  runners (`pi-subagents` or `pi-agents-flow`) are missing, and explicit
  warnings with safe strategy fallbacks when sandboxing or worktree isolation
  is unavailable.
- Development-only isolated RPC validation harness (`tools/pi_validation.py`)
  exercising the standard Pi `--mode rpc` protocol in disposable execution fixtures.
- Cross-client hook support for Codex and Antigravity with active session binding
  and state reconcile (`agent-team resume hooks`).
- Structured JSON output for hook status queries (`resume hooks --status --json`).
- Compact recovery entry points and evidence state checking (`agent-team resume`).
- Hierarchical configuration inheritance without explicit project initialization
  (`init` no longer strictly required for parent folder inheritance).
- Anti-involution circuit breakers and human-first reporting rules embedded in
  stock agent templates.

### Changed

- Default installation targets remain `codex,claude,antigravity`; `pi` is fully
  supported as an opt-in installation target.
- Documentation clarified for hook state paths, session binding requirements,
  and multi-target recovery flows.

### Fixed

- Hook injection filtered strictly to runs bound to the active session ID,
  preventing cross-session prompt pollution.

## [0.4.1] - 2026-10-13

### Changed

- Role harnesses clarify coordinator authority, report ownership, task-based
  tier choice, execution budgets, partial handoff, and revision-bound evidence.
- Design-agent distinguishes architecture proposals from independent audits;
  ops follows the project's existing operational toolchain.
- Coordination and review guidance accounts for coordinator writes, shared
  runtime resources, failed workers, recurring findings, and invalidated evidence.

### Fixed

- Reviewer instructions and stock review prompts use the validator's `approved`
  verdict, and read-only workers return reports for coordinator persistence.

## [0.4.0] - 2026-10-05

### Added

- Target-bound `[roles.<id>.targets.<target>]` routing overrides and optional
  comma-separated `config roles --target` selection, with per-target rendering
  and model inspection. Existing global fields remain fallback values.
- Interactive `config model-presets` for user/project routing, with installed
  target detection, live model/effort menus, `--preset` selection, diff previews,
  `--dry-run`, confirmed scoped saves, and reinstall guidance.
- Partial `[roles.<id>]` model-class and effort overrides with per-field
  inheritance, plus `config roles` for editing builtin role routing without
  installed clients or catalog access.
- Explicit coordinator role overrides select semantic mappings independently
  for model and effort; omitted fields retain dedicated coordinator presets.
- Configuration edits preserve unrelated TOML settings/comments, validate
  candidates, detect changed sources, and recover interrupted replacements.
- User configuration initialization with `init --scope user`, annotated schema
  fields, and complete commented target-profile and model-preset examples.
- Live `builtin < user < project` configuration inheritance, sparse project
  overrides, scoped custom role/skill resolution, and isolated project setup
  with `init --scope project`.
- Explicit `generate gitignore,templates` for optional project artifacts,
  generic native-output ignore patterns, and authored-source exceptions.
- Comma-separated installation targets with complete destination preflight,
  including symlink aliases, file/directory conflicts, and ownership state.
- Effective model routing and live catalog inspection, sparse preset overrides,
  and opt-in `--format table` output for `models show` and `models fetch`.

### Changed

- `init` creates configuration only; template and Git ignore generation move to
  `generate`. Installation no longer updates `.gitignore`.
- `install --scope user` reads user configuration instead of project routing;
  initialize user configuration first. Project runs remain project-scoped.
- User-install replacement backups remain in the invoking project, while
  ownership metadata stays beside the user configuration.

### Fixed

- Complete `init --help` descriptions of scope, inheritance, and setup examples.
- User configuration discovery no longer captures projects beneath HOME, and
  project-only commands reject the user configuration as execution context.
- Generated wildcard ignores preserve configured authored role, skill, and
  target-profile sources.

## [0.3.0] - 2026-09-25

### Added

- Enhanced `agent-team init` to upsert common workflow prompt templates
  (`plan.md`, `coordinate.md`, `review.md`, `discovery.md`) in
  `.agent-team/templates/prompts` and ensure required `.gitignore` entries
  (`.worktrees/`, `.agent-team/runs/`, `.agent-team/backups/`,
  `.agent-team/install-state.json`) are present.
- Homebrew formula (`Formula/agent-team.rb`) enabling native installation via
  `brew install dearrrfish/agent-team/agent-team`.

## [0.2.0] - 2026-09-25

### Added

- Local Git commit hash appended to installed package version using PEP 440 local
  version format (`agent-team 0.2.0+<commit>`) across Nix builds, source distributions,
  and checkout runs.
- macOS installation and operational documentation guide.
- SHA-pinned GitHub Actions release checks and contributor, security, conduct,
  issue, pull request, and ownership guidance for the public repository.
- Native agent-team workflow dogfooding instructions in `AGENTS.md`.

### Changed

- Updated default Codex target presets to `gpt-6-sol` (economy, balanced) and
  `gpt-6-luna` (quality).

### Fixed

- Aligned Claude Code native agent tool specifications with client formatting.

## [0.1.0] - 2026-09-18

### Added

- Portable native agent and skill generation for Codex, Claude Code, and
  Antigravity CLI.
- Coordinator, explorer, design-agent, implementer, ops, and reviewer roles with
  explicit delegation, write, capability, turn, and report boundaries.
- Adaptive `solo`, `assisted`, and `team` workflow tiers with enforced worker
  ceilings and write-isolation policies.
- Durable requirements, design, plan, task, decision, worker-report, review, and
  final-report artifacts with strict lifecycle validation.
- Economy, balanced, and quality model-routing presets owned by target profiles.
- Deterministic rendering and preview-first project or user installation with
  ownership hashes, atomic writes, drift refusal, and forced-replacement backups.
- Nix package, app, development shell, unit/Ruff gate, ShellCheck, and installed
  cross-target release smoke coverage.
- Operator documentation, common coordination prompts, support status, and an
  agent-team topology diagram.
- Canonical GitHub project metadata and remote Nix run/install instructions.

### Compatibility

- Codex native role discovery and model-backed selection are verified.
- Claude Code and Antigravity adapters are experimental pending complete
  model-backed native validation.
- `x86_64-linux` is built and tested. `aarch64-linux` outputs evaluate but still
  require native build and runtime verification.

### Safety

- The installer never modifies native client settings or enables experimental
  features.
- Stale managed files are reported and retained instead of being pruned without
  shared-ownership evidence.
- Claude Code and Antigravity read-only roles omit shell access because those
  clients cannot guarantee a non-mutating command boundary in every parent mode.

[Unreleased]: https://github.com/dearrrfish/agent-team/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.6.0
[0.5.1]: https://github.com/dearrrfish/agent-team/releases/tag/v0.5.1
[0.5.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.5.0
[0.4.1]: https://github.com/dearrrfish/agent-team/releases/tag/v0.4.1
[0.4.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.4.0
[0.3.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.3.0
[0.2.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.2.0
[0.1.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.1.0
