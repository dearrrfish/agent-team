# agent-team

[![CI](https://github.com/dearrrfish/agent-team/actions/workflows/ci.yml/badge.svg)](https://github.com/dearrrfish/agent-team/actions/workflows/ci.yml)

`agent-team` generates portable, role-based agent teams for Codex, with
experimental adapters for Claude Code, Antigravity CLI, and opt-in Pi. It gives
each client the same workflow contract while rendering the native agent and
skill files that
client expects.

The project is designed for coding work that benefits from explicit ownership:
a coordinator plans and integrates, bounded workers execute independent tasks,
and a read-only reviewer checks the result. Adaptive workflow tiers keep that
coordination overhead out of small changes.

> [!NOTE]
> `agent-team` is a generator, validator, and installer—not a cross-client
> orchestrator. Codex, Claude Code, and Antigravity run their native
> subagents; Pi requires a separately installed subagent extension.

Linux users can run or install via Nix flakes. macOS users can install via
Homebrew (`brew install dearrrfish/agent-team/agent-team`) or use the
documented repository-source workflow below. There is no PyPI release or
Darwin Nix package.

## What it provides

- Six target-neutral roles: `coordinator`, `explorer`, `design-agent`,
  `implementer`, `ops`, and `reviewer`.
- Three workload tiers: lightweight `solo`, bounded `assisted`, and reviewed
  `team` execution.
- Cost/quality routing through `economy`, `balanced`, and `quality` model
  presets for every adapter.
- Durable requirements, plans, task DAGs, decisions, worker reports, reviews,
  and final reports when the selected tier requires them.
- Strict TOML, lifecycle, task dependency, report, review, and template
  validation.
- Deterministic rendering plus preview-first installation with ownership hashes,
  drift detection, atomic writes, and backups.

## Pi opt-in

Pi is disabled by default. Add it to `enabled_targets` in the selected scope's
`team.toml`; its builtin profile is already available:

```toml
enabled_targets = ["codex", "claude", "antigravity", "pi"]

[target_profiles]
pi = "builtin:pi"
```

Install a subagent extension yourself, then preview agent generation:

```bash
pi install npm:pi-subagents
# Alternative: pi install npm:pi-agents-flow
agent-team install --scope project --target pi
agent-team install --scope project --target pi --apply
```

`agent-team` never installs plugins or modifies Pi settings. Both preview and
apply require a recognized static subagent declaration before any target writes.
This does not prove that a plugin is installed or usable at runtime. Project
trust, plugin versions, model availability, and native loading still need
verification. See [Pi configuration and limitations](docs/configuration.md#pi-opt-in-target)
for resource filtering, custom directories, tools, and isolation limits.

## Agent-team topology and ideology

The topology scales outward only when the task benefits from delegation. The
user retains product decisions, the coordinator remains the single integration
authority, and workers receive bounded roles rather than sharing ownership of
the whole task.

```mermaid
flowchart TB
    U["User<br/>intent · decisions · approval"] --> C["Coordinator<br/>align · plan · delegate · integrate"]
    C --> T{"Smallest adequate tier"}

    subgraph SOLO["solo · coordinator only"]
        S["Bounded implementation<br/>no worker delegation"]
    end

    subgraph ASSISTED["assisted · bounded help"]
        AC["Coordinator<br/>integration owner"]
        AR["Explorer / design-agent<br/>read-only evidence"]
        AW["Implementer / ops<br/>at most one active writer"]
        AC --> AR
        AC --> AW
        AR --> AC
        AW --> AC
    end

    subgraph TEAM["team · independent work streams"]
        TC["Coordinator<br/>task DAG · ownership · waves"]
        TR["Explorer / design-agent<br/>read-only discovery"]
        TW1["Implementer<br/>disjoint files or worktree"]
        TW2["Ops<br/>disjoint files or worktree"]
        RV["Reviewer<br/>independent · read-only"]
        TC --> TR
        TC --> TW1
        TC --> TW2
        TR --> TC
        TW1 --> TC
        TW2 --> TC
        TC --> RV
        RV -->|"changes requested · cycle remains"| TC
    end

    T -->|"solo"| S
    T -->|"assisted"| AC
    T -->|"team"| TC

    D[("Durable run artifacts<br/>requirements · plan · tasks · reports · review")]
    AC -.->|"state and reports"| D
    TC -.->|"state and reports"| D
    D -.->|"evidence"| RV

    S --> V["Validation and live verification"]
    AC --> V
    RV -->|"approved"| V
    V --> O["Integrated, evidence-backed result"]

    classDef authority fill:#dbeafe,stroke:#2563eb,color:#172554;
    classDef readonly fill:#ecfdf5,stroke:#059669,color:#022c22;
    classDef writer fill:#fff7ed,stroke:#ea580c,color:#431407;
    classDef review fill:#f5f3ff,stroke:#7c3aed,color:#2e1065;
    class U,C,AC,TC authority;
    class AR,TR readonly;
    class S,AW,TW1,TW2 writer;
    class RV review;
```

This structure encodes seven operating principles:

1. **User authority:** material product, scope, and risk decisions stay with the
   user.
2. **Coordinator ownership:** one main-thread coordinator owns delegation,
   integration, state transitions, and completion.
3. **Minimum sufficient team:** `solo` is the baseline; `assisted` and `team`
   must earn their coordination cost.
4. **Bounded delegation:** every worker receives one role, an exact scope,
   acceptance criteria, verification commands, and a reporting contract.
5. **Safe concurrency:** read-only work can overlap; writers are serialized in
   `assisted` and isolated by files or worktrees in `team`.
6. **Durable evidence:** plans, decisions, task state, reports, and review
   survive agent or session boundaries when the tier requires them.
7. **Independent closure:** team work passes through a reviewer who does not
   author fixes, followed by coordinator-owned verification and integration.

## Requirements

- Python 3.11 or newer
- Git
- At least one enabled native client for actually running the generated team

Linux/Nix users also need Nix with flakes enabled for the packaged execution
and development paths. macOS users can install via Homebrew or use Homebrew
for Python and Git with the documented source-install workflow.

Rendering and validation do not require native clients to be installed.
`agent-team doctor` reports missing clients as warnings.

## Support status

| Target | Generate, install, and validate | Native discovery | Model-backed role selection | v0.1 status |
| --- | --- | --- | --- | --- |
| Codex | Verified | Verified | Verified | Supported |
| Claude Code | Verified | Verified | Blocked on subscription/login validation | Experimental |
| Antigravity CLI | Verified | No strict discovery interface found | Not verified | Experimental |
| Pi (opt-in) | Fixture-tested static generation and preflight | Plugin-dependent; not verified | Not verified | Experimental |

The Codex adapter has selected generated custom roles and applied their model,
effort, and instructions in native runs. Claude Code has discovered all six
generated roles, but its model-backed check requires an authenticated
subscription. Antigravity generation and installation pass, but its CLI does
not currently expose a strict machine-readable agent listing; an invalid-agent
probe fell back to the default agent instead of failing.

These labels describe native compatibility evidence, not template completeness.
The three original adapters are covered by deterministic render, install, validation,
and idempotence tests. Observed client versions are recorded in the project
progress notes and are not declared compatibility bounds.

## Quick start

### Linux/Nix

Run directly from GitHub:

```console
nix run github:dearrrfish/agent-team -- --version
```

Or install it into your Nix profile:

```console
nix profile install github:dearrrfish/agent-team
agent-team --version
```

For development, clone the repository, enter its shell, and invoke the package
as a Python module:

```console
git clone https://github.com/dearrrfish/agent-team.git
cd agent-team
nix develop
python -m agent_team --version
```

You can prefix any command with `nix run github:dearrrfish/agent-team --`
instead of installing it. The remaining examples assume the profile
installation and use the shorter `agent-team` command.

### macOS: Homebrew and source installation

#### Option A: Install with Homebrew (recommended)

Install [Homebrew and complete its shell setup](https://docs.brew.sh/Installation)
if you have not already done so. Then install directly from the repository:

```console
brew install dearrrfish/agent-team/agent-team
agent-team --version
```

Or tap the repository first:

```console
brew tap dearrrfish/agent-team
brew install agent-team
agent-team --version
```

#### Option B: Documented source installation

Alternatively, install from the canonical repository in an isolated Python
environment:

```console
brew install python git
brew --version
python3 --version
git --version
```

Continue only when `python3 --version` reports Python 3.11 or newer. Then
install from the canonical repository in an isolated environment:

```console
git clone https://github.com/dearrrfish/agent-team.git
cd agent-team
python3 -m venv .venv
source .venv/bin/activate
python -m pip install .
agent-team --version
```

In a new shell, return to the checkout and run `source .venv/bin/activate`
before using `agent-team`. If Homebrew is unavailable, its shell setup is
inactive, Python is older than 3.11, or Git is missing, correct that
prerequisite before installing. If `agent-team` is not found, reactivate the
environment, reinstall the local checkout, and repeat the version check.

Automated macOS-host tests are out of scope for this repository.
Separately labeled manual macOS runs and feedback may inform final review
cycles; contradictory feedback should result in a documentation correction,
not a claim of packaged or continuously tested macOS support.

### Use the CLI

Set up personal configuration and native agents once:

```console
agent-team init --scope user
agent-team install --scope user --target codex,claude,antigravity
agent-team install --scope user --target codex,claude,antigravity --apply
```

User initialization creates `~/.agent-team/team.toml` with field descriptions
and commented customization examples. Review it before installation. An
existing configuration is preserved. Native agents and skills are installed
into each client's user directories; installation previews unless `--apply`
is present.

Then run commands in any project directory directly:

```console
cd /path/to/project
agent-team validate
agent-team doctor
```

When `.agent-team/team.toml` is absent, `agent-team` automatically inherits
configuration from parent directories upward or falls back to user settings in
`~/.agent-team/team.toml`. Running local `init` is optional.

To create project-specific overrides:

```console
agent-team init
```

Plain `init` creates a small `.agent-team/team.toml` that inherits user settings
live. Add only project-specific overrides. Existing project files remain
unchanged. Global native agents and skills are available according to the
client's discovery rules. After changing shared routing or definitions, rerun
the user installation to refresh native output.

To initialize a project with builtin defaults and disable user configuration
inheritance, use `agent-team init --scope project`. This persists
`inherit_user_defaults = false`; it cannot hide agents already installed in
the native client's user directories.

Generate optional project conveniences explicitly:

```console
agent-team generate gitignore,templates
```

`generate` accepts either selector separately and defaults to both when no
selector is supplied. It refreshes stock configuration and scaffolding
templates beneath `.agent-team/templates/` (`profile/`, `role/`, `review/`)
and adds generic ignore rules for local output and state. Operational
workflow rules, pragmatic review guidelines, and anti-involution circuit breakers
live natively in installed skills (`team-workflow`, `team-plan`, `team-coordinate`,
`team-review`, `team-debug`, `team-research`, `team-docs`, and `team-ops`).
Initialization and installation do not update `.gitignore`.

Install local native definitions whenever a project needs its own routing:

```console
agent-team install --scope project --target codex
agent-team install --scope project --target codex --apply
```

Commit `.agent-team/team.toml`, project instructions such as `AGENTS.md`, and
custom role, skill, and target-profile sources. Keep generated native files,
stock prompts, runs, and backups local. Source resolution follows
builtin < user < project; native same-name discovery rules vary by client.
See [Configuration reference](docs/configuration.md) for sparse overrides and
scope behavior.

Generation and validation work without a native client; `doctor` reports a
missing client as a warning. Running generated agents requires an installed,
authenticated native client.

For work that needs durable coordination, initialize a run and bind its model
preset to the installed agents:

```console
agent-team run init \
  --slug replace-parser \
  --title "Replace parser" \
  --tier team \
  --model-preset balanced

agent-team install --target codex --run replace-parser
agent-team install --target codex --run replace-parser --apply
```

Complete the generated files under `.agent-team/runs/replace-parser/`, then
start a fresh native-client session and explicitly name the role you want it to
use. For example, in Codex:

```text
I want the agent-team coordinator for replace-parser. Ask whether to load its
harness into this main thread or spawn a dedicated native coordinator subagent,
then use $team-plan. Read
.agent-team/runs/replace-parser/, complete the requirements and plan artifacts,
add the task breakdown required by the selected tier, and propose the first
implementation wave before editing product code.
```

Project-scoped Codex agents are loaded only for trusted projects. Trust the
project and start a fresh Codex session after installation; if a named role is
unavailable, diagnose discovery instead of silently substituting a generic
agent.

For detailed lifecycle, trust, install ownership, drift, backup, and stale-path
rules, see [Workflow operations](docs/workflow.md). The preview/apply commands
above retain the same behavior on the documented macOS source workflow; macOS
does not use the Linux-only Nix package path.

## Choose a workflow tier

| Tier | Configured worker limit | Durable state | Write policy | Independent review |
| --- | ---: | --- | --- | --- |
| `solo` | 0 | Not required | Coordinator only | No |
| `assisted` | 1–2 | Required | Writers serialized | Optional |
| `team` | 2–8 (4 by default) | Required | File-disjoint or isolated worktrees | Required |

The default `adaptive` selection counts repository files after excluding common
generated and dependency directories:

- Up to 25 files: `solo`
- 26–200 files: `assisted`
- More than 200 files: `team`

An explicit `--tier` always wins. Use `team` only when the work can be divided
into genuinely independent scopes and review is worth the added coordination.

## Roles

| Role | Responsibility | Writes? |
| --- | --- | --- |
| `coordinator` | User alignment, delegation, integration, and completion | Yes |
| `explorer` | Repository mapping and factual research | No |
| `design-agent` | Requirements and architecture audit | No |
| `implementer` | Bounded product-code changes and verification | Yes |
| `ops` | Nix, CI, infrastructure, deployment, and operational checks | Yes |
| `reviewer` | Independent correctness and risk verdict | No |

Only the coordinator delegates. Worker agents cannot create their own agent
trees, and reviewer is part of the run lifecycle rather than a task-DAG worker.

## CLI

```text
agent-team init [--scope user|project]
agent-team generate [gitignore,templates]
agent-team config roles [--scope project|user]
                        [--target TARGET[,TARGET...]]
                        [--role coordinator|explorer|design-agent|implementer|ops|reviewer]
                        [--dry-run]
agent-team config model-presets [--scope project|user]
                                [--target TARGET[,TARGET...]]
                                [--preset economy|balanced|quality] [--dry-run]
agent-team validate [--format text|json]
agent-team run init --slug SLUG [--title TITLE]
                    [--tier adaptive|solo|assisted|team]
                    [--model-preset economy|balanced|quality]
agent-team resume [status] [--slug SLUG] [--json] [--session-id ID]
agent-team resume context [--slug SLUG] [--session-id ID]
agent-team models show [--target codex|claude|antigravity|pi]
                       [--model-preset economy|balanced|quality | --run SLUG]
                       [--format text|json|table]
agent-team models fetch --target codex|claude|antigravity|pi
                        [--format text|json|table] [--timeout SECONDS]
agent-team render --target codex|claude|antigravity|pi
                  [--run SLUG] --output PATH
agent-team install --target TARGET[,TARGET...]
                   [--scope project|user] [--run SLUG]
                   [--apply] [--force]
agent-team worktree list [--slug SLUG] [--format table|json]
agent-team worktree clean [--slug SLUG] [--dry-run] [--force]
                          [--discard-changes] [--no-sync]
agent-team dispatch --slug SLUG [--role ROLE] [--task TASK]
                    [--runner codex|claude|antigravity|pi]
                    [--model MODEL] [--instruction INSTRUCTION]
                    [--worktree] [--dry-run] [--timeout SECONDS]
                    [--format text|json]
agent-team doctor [--format text|json]
```

`resume`、`resume status` 和 `resume context` 提供上下文压缩后的只读恢复入口。
命令从有效配置的 run 目录发现候选，读取已有会话指针；无有效指针且有多个活动 run
时返回退出码 3，使用 `--slug` 明确选择。`status --json` 输出完整候选及诊断，
`context` 输出不超过 9000 字符的摘要。配置漂移会被报告；未知 worker 需要先对账再
恢复写入。使用 `resume bind --slug SLUG [--session-id ID]` 显式绑定活动 run；省略 session ID
且没有 `AGENT_TEAM_SESSION_ID` 时绑定项目默认指针。`current.json` 只供 CLI 回退使用；
`PreCompact`/`SessionStart` hook 只认 `--session-id` 写入的会话指针，未绑定会话会被忽略。
旧 run 的验证证据显示为 `unbound`，继续前应重跑适用检查。

可选 Claude compact hooks：

```text
agent-team resume hooks --print
agent-team resume hooks --install [--fail-closed] [--apply]
agent-team resume hooks --remove [--apply]
```

默认仅预览写入 `.claude/settings.local.json` 的差异；`--apply` 才写入并备份原文件。
只管理记录在 `.agent-team/hooks-state-claude.json` 的精确条目，保留其它已有 hooks。
`PreCompact` 保存快照，默认失败不阻止压缩；`--fail-closed` 时失败以退出码 2
阻止。`SessionStart(compact)` 注入有界恢复摘要，异常时仍成功启动并提示人工核对。
Hooks 仅对已通过 `resume bind --session-id` 显式绑定的会话生效，未绑定会话被完全忽略。

`run lease claim --slug SLUG --task T-001 --owner NAME --owned-path src/` 为已处于
`running` 状态的任务记录所有权并返回 token；使用 `run lease release --slug SLUG
--task T-001 --token TOKEN` 释放，不会自动更改任务状态。lease 仅表示观察到的所有权，
不能证明 worker 存活。存在未知所有权或重叠路径时拒绝认领。

`run verify --slug SLUG --producer NAME -- COMMAND ARGS` 执行检查并保存退出码与
工作区身份，可用 `--cwd` 指定项目内相对目录。失败检查显示为 `failed`，工作区改变
后旧证据显示为 `stale`；执行期间变化或身份未知显示为 `unbound`。
`run reconcile --slug SLUG` 预览有效策略差异，`--apply` 在完整预检后应用。
新增 lease 和 `[[verification]]` 为可选字段；使用后旧版本可能拒绝该 run，回滚前应
先归档证据并移除新增字段。全局 validate 不比较历史 run 与当前工作区身份。

Use `render` when you want to inspect or package the generated files separately.
It refuses to overwrite different output. Use `install` to target native
discovery paths; it is always a preview unless `--apply` is present.

Passing `--run SLUG` to `render` or `install` applies the model preset recorded
in that run. Without it, the command uses `default_model_preset` from
`.agent-team/team.toml`.

`models show` lists the effective model and effort for each role without
network access. `models fetch` queries a live catalog when the installed
client or provider supports it and labels the source and effort provenance;
catalog entries do not prove account entitlement.

`config model-presets` walks through live model and effort choices, previews
the configuration diff, and asks before saving. It defaults to project scope,
all installed enabled targets, and all three presets. Use `--preset balanced`
to change only balanced routing, or `--dry-run` to preview without saving.
See [interactive preset editing](docs/configuration.md#interactive-preset-editing)
for scope and profile behavior. Reinstall the affected targets after saving.

`config roles` edits semantic routing through `[roles.<id>.targets.<target>]`
blocks. Use `--target codex --role implementer` to change only that target and
role. Omitting `--target` visits all enabled targets; omitting `--role` visits
all builtin roles. It works without installed clients or a live catalog.
See [partial routing overrides](docs/configuration.md#partial-routing-overrides)
for inheritance and coordinator behavior.

## Generated native files

| Target | Project agents | Project skills | User agents | User skills |
| --- | --- | --- | --- | --- |
| Codex | `.codex/agents/` | `.agents/skills/` | `~/.codex/agents/` | `~/.agents/skills/` |
| Claude Code | `.claude/agents/` | `.claude/skills/` | `~/.claude/agents/` | `~/.claude/skills/` |
| Antigravity | `.agents/agents/` | `.agents/skills/` | `~/.gemini/config/agents/` | `~/.gemini/antigravity-cli/skills/` |
| Pi | `.pi/agents/` | `.agents/skills/` | `~/.pi/agent/agents/` | `~/.agents/skills/` |

Each adapter owns native file syntax, tool names, permissions, model fields, and
effort fields. The portable role definitions remain client-independent.

## Run artifacts

Durable runs live under `.agent-team/runs/<slug>/`. Depending on tier and
configuration, a run contains:

- `run.toml` — authoritative lifecycle, gates, task state, concurrency ceiling,
  write isolation, model preset, and review counters
- `requirements.md`, `plan.md`, and optional `design.md`
- `tasks.md` for team-tier execution
- append-only `decisions.md` for deep discovery
- `reports/agent-report-template.md` and per-task worker reports
- `review.md` and `final-report.md`

Unresolved `<!-- REQUIRED: ... -->` markers are warnings while work is active
and become errors when a run claims completion. Team completion also requires
closed tasks, required reports, successful live verification, all lifecycle
gates, and an approved review. Review/fix cycles are capped by project policy.

See [Workflow operations](docs/workflow.md) for state transitions, task
dependencies, report identity, review counters, deep discovery, and complete
coordination prompts. See [context-compaction recovery](docs/recovery.md) for
the read-only recovery entry points, evidence and lease semantics, optional
Claude hooks, and the real-client validation protocol.

## Safe installation

The installer records managed paths and SHA-256 hashes in
`.agent-team/install-state.json`.

- Preview is the default; `--apply` is required to write files.
- Unmanaged destination files and locally modified managed files are refused.
- `--force` permits replacement only with a timestamped backup when backups are
  enabled.
- Writes are atomic, and all destination conflicts are checked before changes
  begin.
- The installer never edits native client settings or enables experimental
  features.
- Managed paths absent from current output are reported as `stale` and retained.
  Version 1 does not prune them automatically because targets can share skill
  paths.

Inspect stale files manually and remove them only after confirming that no
other installed target still owns or uses them.

## Configuration and customization

`.agent-team/team.toml` selects enabled targets, tier policy, model preset,
review limits, deep-discovery behavior, role and skill sources, and install
scope. Parsing is strict: unknown keys, unsafe paths, invalid enum values, and
cross-field policy violations fail validation.

Projects may bind role routing to targets with `[roles.<id>.targets.<target>]`,
replace a complete target profile, add sparse `model_presets` overrides in
`team.toml`, or add and override roles from project-relative
source directories. Built-in target profiles deliberately map
semantic classes (`fast`, `balanced`, and `deep`) rather than embedding native
model names in role definitions.

See [Configuration reference](docs/configuration.md) for the schema, source
layout, precedence rules, target-specific model routing, and adapter safety
constraints.

## Development

See [Contributing](CONTRIBUTING.md) for the development workflow, verification
expectations, and pull request guidance. Security issues follow the private
process in [Security Policy](SECURITY.md).

Run the test suite and checks from the repository root:

```console
nix develop
python -m unittest discover -s tests -v
python -m compileall -q src tests
nix flake check
```

`nix flake check` is the core release gate. It builds the package, runs the unit
suite, Ruff, ShellCheck, and Markdownlint, and exercises the installed executable
through initialization and all-target render/install/idempotence smoke tests.

Before a documentation release, optionally inspect the browser-rendered diagram
layout. This downloads a large Chromium closure on first use:

```console
nix shell nixpkgs#mermaid-cli -c \
  mmdc -i README.md -o /tmp/agent-team-readme-rendered.md
```

The flake currently declares `x86_64-linux` and `aarch64-linux` outputs. The
implementation has been exercised on `x86_64-linux`; `aarch64-linux` still
needs native verification.

## Releases

- [Changelog](CHANGELOG.md)
- [v0.4.0 release notes](docs/releases/v0.4.0.md)
- [v0.3.0 release notes](docs/releases/v0.3.0.md)
- [v0.2.0 release notes](docs/releases/v0.2.0.md)
- [v0.1.0 release notes](docs/releases/v0.1.0.md)
- [Release process](docs/releasing.md)

## Inspiration

The project began as a portable, workload-adaptive interpretation of AWS's
[sample Codex agent team](https://github.com/aws-samples/sample-codex-agent-team),
without its AWS-specific infrastructure assumptions.

## License

[MIT](LICENSE)
