# Configuration reference

`agent-team init` creates `.agent-team/team.toml`, upserts common workflow
prompt templates under `.agent-team/templates/prompts`, and ignores the four
stock prompt files and local state. A successful project-scoped `install
--apply` adds exact ignore rules for its managed native agents and skills.
Preview and user-scope installs leave the project's `.gitignore` unchanged.
Configuration is strict:
unknown keys, invalid enums, unsafe paths, and cross-field policy violations are
errors. Resolution order is packaged target defaults, a whole project target
profile replacement, sparse project model-preset overrides, then explicit run
preset selection. Environment
variables never override workflow policy.

Track `team.toml`, project instructions, and any configured custom role,
skill, or target-profile sources. Keep authored prompts outside the four stock
prompt paths because `init` overwrites those examples. Native directories can
also contain hand-written files, so neither `init` nor `install` adds blanket
`.agents/`, `.codex/`, or `.claude/` ignores. Existing project ignore rules
are preserved. Git ignores do not untrack files that are already committed.

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
activation guidance, turn limit, and report kind. The coordinator must delegate;
all worker roles must not. Only reviewer uses the `review-cycle` report contract;
every other role uses `agent-report`. Read-only roles cannot request
`filesystem.write`.
Adapters include activation guidance in the native description and append the
portable turn, report, capability, and delegation contract to native
instructions. Claude also receives native `maxTurns`; targets without a hard
turn-limit field retain the limit as an explicit agent instruction.
Claude and Antigravity omit shell tools from roles with `write_policy = "deny"`:
their command tools can write workspace files, and their per-agent execution
modes do not guarantee a non-mutating shell under every parent configuration.
The coordinator or a write-isolated worker must run commands for those roles.

## Target profiles and model presets

Target profile references default to `builtin:codex`, `builtin:claude`, and
`builtin:antigravity`. A relative TOML path replaces the complete profile for
that target; profiles are not deep-merged. Profiles declare separate project
and user destinations because some native clients use different global layouts.

For a small routing change, add a sparse `model_presets` table in
`.agent-team/team.toml`:

```toml
[model_presets.codex.balanced]
coordinator_model = "my-codex-model"
coordinator_effort = "high"

[model_presets.codex.balanced.models]
fast = "my-fast-model"

[model_presets.codex.balanced.effort]
high = "xhigh"
```

Only the listed fields change. `models` accepts `fast`, `balanced`, and
`deep`; `effort` accepts semantic `low`, `medium`, and `high` keys whose
values must be supported by that target. The override is applied after loading
the selected target profile, including a custom complete profile. Targets
without native effort support reject effort overrides. A run's preset selection
chooses which effective table is rendered; it does not bypass project overrides.

Balanced routing is:

| Semantic role | Codex | Claude | Antigravity |
| --- | --- | --- | --- |
| Coordinator | `gpt-6-sol` / medium | `sonnet` / high | `pro` |
| Fast | `gpt-6-luna` | `haiku` | `flash` |
| Balanced | `gpt-5.6-terra` | `sonnet` | `pro` |
| Deep | `gpt-6-sol` | `sonnet` | `pro` |

Role effort is mapped through each preset. Claude omits effort for Haiku;
Antigravity profiles do not emit effort. Tool names and permission modes are
owned by adapters and cannot be injected through project configuration. Native
effort mappings may use `low`, `medium`, `high`, `xhigh`, `max`, or `ultra` when
the target's explicit `effort_levels` allow that level. Adapters also emit
target-specific guidance for whether parallel writers may use worktree
isolation.

Use `agent-team models show [--target TARGET] [--model-preset PRESET | --run
SLUG] [--format text|json]` to inspect effective role routing without network
access. Use `agent-team models fetch --target TARGET [--format text|json]` to
query a live catalog. Fetch output labels its source and separates
catalog-reported per-model effort support from effort values configured in the
target profile. Codex app-server catalogs may include bundled entries and do
not prove account entitlement. Claude discovery uses the Claude Models API
when `ANTHROPIC_API_KEY` is present, so results may differ from a Claude Code
subscription. Antigravity discovery depends on the installed `agy models`
machine-output protocol. A missing client, credential, or usable catalog is
reported as unavailable rather than presented as live data.

## Diagnostics

Use `agent-team validate --format text` for people or `--format json` for
automation. Diagnostics include severity, stable code, dotted path, and message.
Unresolved `REQUIRED` markers are warnings during an active run and errors once
the run claims `complete`.
