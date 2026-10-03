# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/dearrrfish/agent-team/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.3.0
[0.2.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.2.0
[0.1.0]: https://github.com/dearrrfish/agent-team/releases/tag/v0.1.0
