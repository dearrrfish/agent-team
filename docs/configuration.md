# Configuration reference

`agent-team init` creates `.agent-team/team.toml`. Configuration is strict:
unknown keys, invalid enums, unsafe paths, and cross-field policy violations are
errors. Resolution order is packaged target defaults, a whole project target
profile replacement, project policy, then explicit run flags. Environment
variables never override workflow policy.

`run init --model-preset PRESET` records an explicit run selection. Pass the
run to `render` or `install` with `--run SLUG` to render native agent profiles
from that selection; omitting `--run` uses `default_model_preset`.

## Project policy

Top-level fields identify the team, select `adaptive`, `solo`, `assisted`, or
`team` as the default tier, choose an `economy`, `balanced`, or `quality` model
preset, enable native targets, and declare role and skill sources.

`[workflow]` controls the contained run directory, review-cycle limit (1–3),
deep-discovery default, worktree decision gate, and worker-report persistence.
Tier tables define worker count, artifact and review requirements, and their
fixed write-isolation policy. Assisted permits 1–2 workers and team permits
2–8; both require durable artifacts. Enabling independent review for any tier
adds a required `review.md` artifact and approval gate.

`[install]` defaults to project scope, always refuses implicit overwrite,
requires backups, and cannot modify native client settings in schema v1.

Paths are relative to the project and cannot contain traversal outside it.

## Roles

A project role source is a directory containing `<role>/role.toml` and
`<role>/instructions.md`. Later sources replace earlier roles by ID, allowing a
project to override built-ins or add kebab-case custom roles. All six built-in
roles must remain available.

Role metadata selects semantic model class (`fast`, `balanced`, `deep`), effort
(`low`, `medium`, `high`), write policy (`deny`, `workspace`), capabilities,
activation guidance, turn limit, and report kind. Delegation must be false.
Read-only roles cannot request `filesystem.write`. Adapters include activation
guidance in the native description and append the portable turn, report,
capability, and no-delegation contract to native instructions. Where a target
has no hard turn-limit field, the limit remains an explicit agent instruction.

## Target profiles and model presets

Target profile references default to `builtin:codex`, `builtin:claude`, and
`builtin:antigravity`. A relative TOML path replaces the complete profile for
that target; profiles are not deep-merged.

Balanced routing is:

| Semantic role | Codex | Claude | Antigravity |
| --- | --- | --- | --- |
| Coordinator | `gpt-5.6-sol` / medium | `sonnet` / high | `pro` |
| Fast | `gpt-5.6-luna` | `haiku` | `flash` |
| Balanced | `gpt-5.6-terra` | `sonnet` | `pro` |
| Deep | `gpt-5.6-sol` | `sonnet` | `pro` |

Role effort is mapped through each preset. Claude omits effort for Haiku;
Antigravity profiles do not emit effort. Tool names and permission modes are
owned by adapters and cannot be injected through project configuration. Native
effort mappings may use `low`, `medium`, `high`, `xhigh`, `max`, or `ultra` when
the target supports that level. Adapters also emit target-specific guidance for
whether parallel writers may use worktree isolation.

## Diagnostics

Use `agent-team validate --format text` for people or `--format json` for
automation. Diagnostics include severity, stable code, dotted path, and message.
Unresolved `REQUIRED` markers are warnings during an active run and errors once
the run claims `complete`.
