# Configuration reference

## Scopes and inheritance

`agent-team init --scope user` creates the complete, annotated configuration
at `~/.agent-team/team.toml`. It includes descriptions of supported fields and
commented target-profile and model-preset examples. Existing files are preserved
with a warning. User initialization creates no runs, templates, backups, or
Git ignore file.
Project commands reject the home directory and the user configuration tree as
project context; run them from a separate project directory.

Plain `agent-team init` creates a sparse project configuration that inherits
user settings live. For example:

```toml
schema_version = 1
inherit_user_defaults = true

[model_presets.codex.balanced.models]
fast = "my-project-model"
```

Configuration resolves in this order: packaged defaults, user configuration,
then project configuration. Tables merge recursively; scalar values and arrays
replace inherited values. Role and skill source lists are the exception for
definition loading: each scope supplies its custom source layer, so project
sources overlay user definitions instead of discarding them. A target-profile
reference selects a complete profile
rather than merging profile files. Sparse model-preset overrides then update
individual fields of that profile. A run selects which preset is used.

Changing user settings affects opted-in projects on their next command. It does
not rewrite installed native files: rerun `install --scope user --apply` with
the relevant targets to refresh shared output. A project can install its own
native files with `install --scope project` whenever needed.

`init --scope project` writes complete builtin defaults and persists
`inherit_user_defaults = false`. Existing files are never rewritten by init;
change that field in an existing config to opt out. Opt-out skips user config
reads, including malformed user files. It controls agent-team configuration
resolution, while native clients can still discover globally installed agents.

Project source and profile paths resolve relative to the project root. User
source and profile paths resolve relative to `~/.agent-team`. References must
stay inside their originating root, including after following symlinks. The
workflow run directory always resolves inside the project. Role and skill
sources retain their original scope even when project settings override other
fields.

Named role and skill definitions use whole-definition replacement:
builtin < user custom < project custom. Later custom sources in the same scope
win by ID. Builtin markers do not reload defaults after custom definitions.
Instructions and permissions are not concatenated across same-name definitions.

Unknown keys, malformed values, unsafe paths, and policy violations are errors.
Existing complete project configs remain valid and their explicit fields take
priority over user settings. Environment variables do not override workflow
policy.

### Native discovery differs from source resolution

The priority above is an agent-team source contract. Native clients have their
own discovery behavior:

- Codex combines global and increasingly specific project instruction files.
  Its skills documentation says duplicate names can both appear in selectors.
  See [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
  [skills](https://learn.chatgpt.com/docs/build-skills), and
  [subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).
- Claude Code documents project custom subagents ahead of user subagents.
  See [subagent scopes](https://code.claude.com/docs/en/sub-agents) and
  [skill locations](https://code.claude.com/docs/en/skills).
- Antigravity documents global and workspace locations for
  [agents](https://antigravity.google/docs/subagents?tab=cli) and
  [skills](https://antigravity.google/docs/skills). The reviewed sources do not
  establish a universal duplicate-name winner across these locations.

Project configuration cannot guarantee that a native loader suppresses a
same-name global skill. User setup reduces repeated installation; project
installation supplies local exceptions where the native client supports them.

### Explicit project generation

`agent-team generate gitignore,templates` populates optional project artifacts.
Either selector can be requested separately; no selector requests both.
Initialization and installation only manage their own configuration or native
output, so run generate explicitly when you want project ignore rules.

Generated rules use wildcards across hidden native roots, matching builtin
agent names and `team-*` skill directories, plus local workflow state and stock
prompt paths. Skill rules match directories such as
`.agents/skills/team-plan/SKILL.md`. Existing rules are preserved and rerunning
generation does not duplicate entries. Same-prefix authored native files can
also match these patterns; use distinct names or an explicit Git negation rule
when tracking them. Configured custom role and skill sources receive explicit
exceptions so
those directories remain trackable even when their names match native output
patterns. Target-profile sources remain trackable as well. Git ignores do not
untrack committed files.

Track `team.toml`, project instructions, and configured source definitions.
Keep authored prompts outside the four stock paths because template generation
overwrites those examples.

### Scope migration

`install --scope user` now reads only `~/.agent-team/team.toml`; it no longer
renders a project's configuration into user directories. Initialize and edit
the user config first. `install --scope project` reads effective project
configuration and supports `--run SLUG`. User installation rejects `--run`
because runs stay project-scoped. Comma-separated `--target` values install
multiple targets after preflight checks; single-target invocations still work.

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

Paths retain the defining scope as described above and cannot escape it.

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

### Partial routing overrides

Use `[roles.<id>]` in the selected scope's `team.toml` to change routing while
retaining the complete role definition:

```toml
[roles.implementer]
model_class = "balanced"
effort = "low"
```

Both fields are optional. `model_class` accepts `fast`, `balanced`, or `deep`;
`effort` accepts semantic `low`, `medium`, or `high`. These selectors use each
target's active model preset, so they apply across targets and presets. A
semantic effort value may map to a different native effort label; inspect the
result with `agent-team models show`. Targets without effort support and models
marked as effort-free continue to omit native effort.

Whole role definitions resolve from builtin, user, then project sources. Sparse
routing overrides apply afterwards, merging user and project values by field.
For example, a project class override retains an inherited user effort
override. A user routing override also applies to a project-authored replacement
role unless the project supplies its own override for that field. Instructions,
permissions, capabilities, activation, delegation, and turn limits remain in
complete authored definitions.

TOML may name builtin or loaded custom roles; an unknown role ID, unsupported
field, wrong type, or invalid semantic value is an error. Overrides do not create
roles. Existing configurations without `[roles]` retain their current routing.
Older agent-team binaries reject this new optional table; update the binary
before adding it.

Coordinator routing has separate defaults. Without an explicit coordinator
role override, it uses the preset's `coordinator_model` and
`coordinator_effort`. Setting `[roles.coordinator].model_class` selects the
preset's class mapping instead; setting `.effort` selects its semantic effort
mapping. Each field switches independently, so an effort-only override retains
the dedicated coordinator model. Explicit `deep` or `high` still changes this
routing choice even when the underlying role definition has the same value.

### Interactive role editing

```console
agent-team config roles
agent-team config roles --role implementer --dry-run
agent-team config roles --scope user --role implementer
```

Scope defaults to `project`; omitting `--role` visits all six builtin roles in
stable order. The filter accepts `coordinator`, `explorer`, `design-agent`,
`implementer`, `ops`, or `reviewer`. Custom-role overlays can be authored in TOML.
This editor needs no installed native client, model catalog, or authentication.

Menus display effective settings and their definition/override sources. Enter
retains the current state. Explicitly choosing a class or effort pins that field
in the selected scope, including values equal to an inherited default. For a
coordinator field without an override, the default keeps its dedicated preset;
choose a semantic value explicitly to switch that field.

The editor previews the diff and requires explicit `yes` before saving.
`--dry-run`, declining confirmation, end of input, or interruption leaves files
unchanged. Only the selected scope's `team.toml` is edited; role definitions,
instructions, profiles, and inherited user files remain untouched. Candidate
validation and source snapshots reject stale configuration or changed role
sources before saving. Conservative TOML editing and atomic-write recovery
follow the model-preset editor's rules.

Run the scoped reinstall command printed after saving to refresh enabled native
targets. Resetting overrides is a manual operation in this version: remove the
field from the config that defines it. Removing a project field alone retains
any inherited user value. Unsupported role-specific keys under `model_presets`
are not migrated automatically; semantic role settings belong under `[roles]`.

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

Only the listed fields change; inherited preset fields remain active. `models`
accepts `fast`, `balanced`, and
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
SLUG] [--format text|json|table]` to inspect effective role routing without network
access. Use `agent-team models fetch --target TARGET
[--format text|json|table]` to
query a live catalog. Fetch output labels its source and separates
catalog-reported per-model effort support from effort values configured in the
target profile. Codex app-server catalogs may include bundled entries and do
not prove account entitlement. Claude discovery uses the Claude Models API
when `ANTHROPIC_API_KEY` is present, so results may differ from a Claude Code
subscription. Antigravity discovery depends on the installed `agy models`
machine-output protocol. A missing client, credential, or usable catalog is
reported as unavailable rather than presented as live data.

### Interactive preset editing

Initialize the selected scope first, then run:

```console
agent-team config model-presets
agent-team config model-presets --target codex --preset balanced --dry-run
agent-team config model-presets --scope user --target codex,claude
```

`--scope` defaults to `project`. User scope reads only `~/.agent-team/team.toml`;
project scope uses effective project configuration, including opted-in user
settings. `--preset` accepts `economy`, `balanced`, or `quality`. Without it,
the command visits all three; a selected preset leaves the other two untouched.

Default targets are enabled, configured profiles with a native executable on
PATH: `codex`, `claude`, or `agy`. `--target` accepts comma-separated names and
rejects invalid, disabled, unconfigured, or uninstalled targets. No installed
enabled target is an error. Every selected target must supply a usable live
catalog before selections begin. Catalog authentication and availability follow
`models fetch`, described above; no configured-model fallback is used.

For each target and preset, select coordinator, fast, balanced, and deep models,
then coordinator effort and shared semantic low, medium, and high effort
mappings where supported. Current values are defaults only when valid in the
available choices. Effort choices respect the profile and reported model
capabilities. Missing catalog effort metadata uses explicitly labeled profile
levels. Models explicitly reporting no effort support are rejected unless the
profile already supports omitting effort for them. Targets without effort
support skip effort selection.

The command previews all file diffs before a default-negative save confirmation.
`--dry-run`, declining confirmation, end of input, and interruption leave files
unchanged. Builtin profiles write sparse `model_presets` overrides into the
selected scope's `team.toml`. A file profile within that scope updates its
`presets` settings and synchronizes existing overrides that would mask the
new values. A project inheriting a user-owned file profile receives a local
copy and a project profile reference; shared user files remain untouched. The
copy freezes the inherited profile's other settings for that project.

Edits preserve unrelated settings and comments in supported TOML layouts.
Unsupported affected layouts fail before saving; simplify those assignments to
ordinary table headers and string keys before retrying. Candidate settings are
validated, and stale files changed since preview cause an error. Writes are
atomic per file; a failure during a multi-file save attempts to restore earlier
writes and reports any restoration failure.

Saving configuration does not refresh installed native definitions. Run the
scoped reinstall command printed after saving, for example:

```console
agent-team install --scope project --target codex --apply
```

## Diagnostics

Use `agent-team validate --format text` for people or `--format json` for
automation. Diagnostics include severity, stable code, dotted path, and message.
Unresolved `REQUIRED` markers are warnings during an active run and errors once
the run claims `complete`.
