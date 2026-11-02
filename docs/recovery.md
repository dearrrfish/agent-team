# Context-compaction recovery

`agent-team` keeps run state on disk, so a new session or a compacted context can
recover from the run directory instead of from chat history. This page covers the
read-only entry points, the optional Claude Code hooks, the state semantics they
depend on, and a validation protocol for real clients.

Nothing here makes recovery automatic on its own. The files are the source of
truth; hook output only points the model back at them.

## Read-only entry points

```console
agent-team resume                       # candidates; select automatically only when unambiguous
agent-team resume status --json         # full candidate list plus selected status
agent-team resume context --slug SLUG   # bounded recovery summary (<= 9000 chars)
agent-team resume bind --slug SLUG [--session-id ID]
```

Selection order for `resume` is: explicit `--slug`, then the session pointer,
then the project-level `current.json`, then a single active run. If several
active runs exist and no valid pointer names one, `resume` prints candidates and
exits `3` instead of guessing. Exit code `2` means bad input or an unreadable
run.

Hooks are stricter: `PreCompact` and `SessionStart` use only the per-session
pointer. They never read `current.json` and never fall back to a single active
run. A session with no per-session pointer is treated as "not managed by
agent-team" and receives no snapshot or injected context. A pointer that exists
but is invalid (wrong project, run, path, or a terminal/missing run) is reported:
`PreCompact` exits `1` (`2` with `--fail-closed`) and `SessionStart` injects a
warning. Bind a session explicitly before relying on hooks:

```console
agent-team resume bind --slug SLUG --session-id ID
```

`bind` without `--session-id` (and without `AGENT_TEAM_SESSION_ID`) writes the
project-level `current.json` used by the CLI, not a hook binding.

The summary reports run identity, baseline and current revision, workspace
fingerprints, evidence state, open gates, config drift, workers, and one concrete
next action. Required fields are never truncated; detail lines are dropped first
and a marker tells you to use `status --json`.

`resume` does not execute commands stored in a manifest and does not write to the
project. `bind` is the only resume subcommand that writes, and it writes only the
pointer file.

### Pointers

Pointers live under `.agent-team/sessions/`: `<sha256(session_id)[:16]>.json` and
`current.json`. They store the run slug, project-relative run path, project root,
timestamp, and baseline revision. The raw session id is not stored. A pointer is
ignored when its project root, session hash, run path, or run identity does not
match. `current.json` is a CLI fallback only; hooks require the per-session file.

## Evidence

`run verify` executes a check without a shell and records its exit status plus
the workspace identity observed before and after it:

```console
agent-team run verify --slug SLUG --producer coordinator -- python3 -m unittest
agent-team run verify --slug SLUG --producer coordinator --cwd tests -- ./check.sh
```

Evidence states in `resume`:

| State | Meaning |
| --- | --- |
| `bound` | Exit 0 and the workspace identity equals the current workspace |
| `stale` | Exit 0, but the workspace changed since the check ran |
| `failed` | The check exited non-zero |
| `unbound` | No record, incomplete identity, or the workspace changed during the check |

Only `bound` counts as current evidence. Old runs without records show `unbound`;
rerun the applicable checks instead of assuming they still pass. Global
`agent-team validate` never compares historical evidence with the current
workspace, so later commits do not invalidate unrelated finished runs.

Identity covers `git rev-parse HEAD`, `git diff --binary HEAD` (including staged
changes), and a hash of untracked, non-ignored files. Large, special, or
unreadable inputs are reported as `dirty-unbounded` and never count as bound.
Ignored paths do not enter the fingerprint. `agent-team`'s own state is excluded
even when it is tracked: `.agent-team/**`, `.claude/settings.local.json`,
`.codex/hooks.json`, and `.agents/hooks.json` are left out, so recording a
check, binding a session, writing a snapshot, or installing hooks cannot
invalidate the evidence it just recorded. Changes to source, configuration, and
other tracked files still do.

## Worker ownership

`run lease claim` records observed ownership for a task that is already
`running`:

```console
agent-team run lease claim --slug SLUG --task T-001 --owner coordinator --owned-path src/
agent-team run lease release --slug SLUG --task T-001 --token TOKEN
```

A lease is a record of what the coordinator last observed, not proof that a
worker is alive. `resume` classifies tasks as `released`, `not-running`,
`stale-lease`, `live_unverified`, or `unknown`. A `running` task without a valid
lease is `unknown`. For both `unknown` and `live_unverified`, do not dispatch
writes that overlap `owned_paths`; confirm ownership first. Claims are refused
when paths overlap another running task or when ownership is unknown. Release
does not change task status. `worker_closure` cannot be true while any task is
incomplete or still holds a lease.

## Config drift and reconcile

`agent-team validate` stays strict: a manifest whose policy fields disagree with
the effective configuration is an error. `resume` reads tolerantly and reports
the drift instead of failing, so recovery can still show what changed.

```console
agent-team run reconcile --slug SLUG           # preview only
agent-team run reconcile --slug SLUG --apply   # precheck, then write
```

Reconcile edits only the policy scalars, preserves comments and unrelated text,
refuses layouts it cannot edit safely, and validates the result before writing.

## Optional Claude Code hooks

```console
agent-team resume hooks --print [--target {claude,codex,antigravity}] [--scope {project,user}] [--invocation {auto,cli,interpreter}] [--command-prefix CMD]
agent-team resume hooks --install --apply [--target {claude,codex,antigravity}] [--scope {project,user}] [--invocation {auto,cli,interpreter}] [--command-prefix CMD]
agent-team resume hooks --remove --apply [--target {claude,codex,antigravity}] [--scope {project,user}]
agent-team resume hooks --status [--json]
agent-team resume hooks --reconcile [--apply]
```

`--target` defaults to `claude` and `--scope` defaults to `project`; the Codex
and Antigravity sections below cover the client-specific file formats and
contracts. `--scope user` is supported only for Antigravity.

Installation is project-only and defaults to `.claude/settings.local.json`; use
`--hooks-file` to choose another project-relative file. Preview is the default.
On apply, the previous file is backed up under `.agent-team/backups/`, the exact
groups written are recorded in `.agent-team/hooks-state.json` (or
`hooks-state-claude.json` on new installs), and only those groups are removed
later. Existing hooks, such as an AskHuman `SessionStart` hook, are preserved. If
a managed group was edited by hand, the command refuses to overwrite or remove
it; reconcile it manually.

| Event | Action |
| --- | --- |
| `PreCompact` (`manual\|auto`) | For a session already bound to a run, writes `recovery/snapshot.json` and refreshes the binding. Unbound sessions are ignored. |
| `SessionStart` (`compact`) | For a bound session, reads run files and emits `additionalContext` with the bounded summary. Unbound sessions emit nothing. |

Exit codes are deliberate:

- `precompact` fails with `1` by default, which does not block compaction. With
  `--fail-closed` it fails with `2`, which blocks compaction.
- `session-start` always exits `0`. Unbound sessions emit nothing; bad input,
  invalid pointers, or unreadable runs inject a warning that points at
  `resume status --json`.

### Invocation resolution and NixOS / Nix safety

By default (`--invocation auto`), hook generation prefers a stable `agent-team`
executable on `PATH` (such as `/etc/profiles/per-user/$USER/bin/agent-team` or
`~/.nix-profile/bin/agent-team` in NixOS / Home Manager environments) rather
than hardcoding ephemeral interpreter or package paths inside `/nix/store/`.
This prevents hooks from breaking when system generations update or after `nix
collect-garbage`.

- `--invocation auto`: Uses `agent-team` if available on `PATH`; falls back to
  `PYTHONPATH=... <sys.executable> -m agent_team` when running directly from a
  source checkout, warning if an ephemeral `/nix/store/` path would be persisted.
- `--invocation cli`: Forces `agent-team resume hook ...` in generated commands.
- `--invocation interpreter`: Forces the running Python interpreter and
  repository path (useful during local development and testing).
- `--command-prefix CMD`: Customizes the prefix completely (e.g. `direnv exec .
  agent-team` or `nix run .#agent-team --`).

After installation, Claude Code must reload settings (for example via `/hooks`
or a restart) before the new entries take effect.

### OpenAI Codex CLI hooks

```console
agent-team resume hooks --target codex --print
agent-team resume hooks --target codex --install --apply
agent-team resume hooks --target codex --remove --apply
```

`--target codex` writes `.codex/hooks.json` and records ownership in
`.agent-team/hooks-state-codex.json`; Claude Code hooks and their state remain
independent, so both targets can be installed in the same project. Codex hooks
receive the same `PreCompact`/`SessionStart` contract, and `agent-team resume
hook` accepts Codex payload field spellings (`hookEventName`, `threadId`,
`thread_id`) alongside the Claude Code ones. Codex requires the project to be
trusted (`[projects."<path>"] trust_level = "trusted"`) and each generated hook
to be trusted before it runs; `hooks/list` on the app server reports the
`currentHash` to record under `[hooks.state."<path>:<event>:<group>:<handler>"]`
as `trusted_hash`.

Validated end to end on 2026-11-01 with Codex CLI v0.164.0: a disposable project
ran `agent-team resume hooks --target codex --install --apply`, then `codex exec`
with a low auto-compact limit. `PreCompact` wrote `recovery/snapshot.json` and
bound the session, and `SessionStart` injected the recovery summary as a
developer message after compaction. Evidence:
`.agent-team/runs/codex-hooks-support/reports/codex-e2e-evidence.md`.

### Google Antigravity CLI hooks

```console
agent-team resume hooks --target antigravity --print
agent-team resume hooks --target antigravity --install --apply
agent-team resume hooks --target antigravity --remove --apply
```

`--target antigravity` writes `.agents/hooks.json` and records ownership in
`.agent-team/hooks-state-antigravity.json`. Antigravity's file format differs
from the other clients in three ways:

- Hooks are grouped under a namespace key; `agent-team` owns the `agent-team`
  namespace only, and refuses to overwrite a namespace with different content.
- `SessionStart` is a flat array of handlers with no `matcher` field.
- The hook writes a step injection to stdout rather than the Claude/Codex
  `hookSpecificOutput` object:
  `{"injectSteps": [{"systemMessage": {"systemMessage": "..."}}]}`.

Antigravity has no `PreCompact` event, so no snapshot or session binding happens
in the hook. Recovery context is injected on `SessionStart` only, and only for a
session explicitly bound with `agent-team resume bind --slug SLUG --session-id
ID`. Unbound sessions are ignored. Antigravity also launches project hook
commands with the working directory set to the `hooks.json` directory
(`<project>/.agents`), so `resume hook` resolves the project from the payload's
`workspacePaths` and requires the hook process to have been started from inside
that workspace.

#### User scope

```console
agent-team resume hooks --target antigravity --scope user --print
agent-team resume hooks --target antigravity --scope user --install --apply
agent-team resume hooks --target antigravity --scope user --remove --apply
```

`--scope user` writes Antigravity's global `~/.gemini/config/hooks.json` and
records ownership in `~/.agent-team/hooks-state-antigravity-user.json`; backups
go to `~/.agent-team/backups/`. `--hooks-file` is interpreted relative to the
user home directory in this scope. The generated handler calls the separate
`agent-team resume hook antigravity-global-session-start` action because
Antigravity runs user-scope hooks from `~/.gemini/config` rather than from the
workspace. That action resolves the project from `workspacePaths` and stays
silent when the workspace has no `.agent-team` directory or no runs, so it does
not inject warnings into unrelated projects.

User-scope hooks apply to every Antigravity workspace and load without a
per-workspace trust prompt. Use `--invocation auto` (the default) or `--invocation
cli` for global installs so the command resolves `agent-team` from `PATH`; an
interpreter prefix pointing at a source checkout would break in other projects.

The project must be trusted in Antigravity before its *project* hooks load. On
the very first launch of an untrusted project, the initial turn can run before
the trust prompt is answered and before `.agents/hooks.json` is loaded, so that
turn gets no injection; later sessions do.

Validated end to end on 2026-11-01 with Antigravity CLI `agy` in both `--print`
and interactive TUI modes:

- `--print`: the `SessionStart` handler ran with a real payload
  (`conversationId`, `workspacePaths`, `transcriptPath`), emitted `injectSteps`,
  and the model reported the injected `Run: <slug> | ...` line without reading
  any file.
- Interactive TUI (`--prompt-interactive` through a PTY, trusted project): the
  hook emitted `injectSteps`, and `transcript_full.jsonl` recorded a
  `SYSTEM_MESSAGE` step containing the recovery summary before the model's
  response.
- User scope (`~/.gemini/config/hooks.json`, temporary probe): the handler ran
  from cwd `~/.gemini/config` in a fresh untrusted workspace, confirming both
  the global discovery path and the need for the dedicated global action. The
  probe was removed afterwards.

Evidence: `.agent-team/runs/antigravity-hooks/reports/antigravity-e2e-evidence.md`
and `.agent-team/runs/antigravity-tui-validation/reports/antigravity-tui-evidence.md`.

### Hook ownership state

Every install records exactly what it wrote, so `--remove` removes only its own
groups or namespace. Those records can outlive their hooks after manual edits, a
deleted project, or a legacy filename. Inspect and reconcile them without
editing any client hook file:

```console
agent-team resume hooks --status
agent-team resume hooks --reconcile            # preview
agent-team resume hooks --reconcile --apply    # migrate and clean
```

`--status` lists every known record as `ok`, `migrate`, `remove`, `manual`, or
`error`. `--status --json` returns `{"states": [...]}` with absolute
`state_path` and `hooks_path`, plus `target`, `scope`, `status`, `legacy`, and
`detail`; `--json` is rejected for other operations. `--reconcile` previews the
actions and, with `--apply`:

- migrates the legacy `.agent-team/hooks-state.json` to
  `hooks-state-claude.json`, adding `target` and `scope`;
- removes records whose hooks file or managed block is gone, and legacy records
  superseded by `hooks-state-claude.json`.

Reconcile never edits `.claude/settings.local.json`, `.codex/hooks.json`,
`.agents/hooks.json`, or `~/.gemini/config/hooks.json`. A record marked `manual`
means the managed hooks were edited by hand; reconcile the file manually, then
reinstall or remove.

## Multi-client lifecycle hooks status

| Client | Hook support | Key events & triggers | Recovery mechanism in `agent-team` |
| --- | --- | --- | --- |
| **Claude Code** | **Supported** | `PreCompact` (`manual\|auto`), `SessionStart` (`compact`) | For a session bound to a run, automated snapshot via `PreCompact` and context injection via `SessionStart` `additionalContext`; unbound sessions are ignored. |
| **OpenAI Codex CLI** | **Supported, validated** (`.codex/hooks.json`) | `PreCompact`, `PostCompact`, `SessionStart`, `SessionEnd`, `PreToolUse` | `agent-team resume hooks --target codex` generates native hooks; hook payloads from Codex are accepted by `resume hook`. Validated with v0.164.0. |
| **Google Antigravity CLI (`agy`)** | **Supported, validated** (`.agents/hooks.json`, `~/.gemini/config/hooks.json`) | `SessionStart`, `PreInvocation`, `PostInvocation`, `PreToolUse`, `PostToolUse`, `Stop` | `agent-team resume hooks --target antigravity [--scope user]` generates a namespace-scoped `SessionStart` handler that emits `injectSteps`. No `PreCompact` equivalent, so no automatic snapshot. Validated with `agy --print` and the interactive TUI on 2026-11-01. |
| **Cursor / Windsurf / Aider** | **Not available** | None | No external command-hook protocol exposed. Recovery is explicit: run `agent-team resume` after compaction. |

Do not describe hook-based recovery as active on clients other than Claude Code,
Codex, and Antigravity until their respective hook generators are integrated and
validated end to end. Antigravity provides context injection on `SessionStart`
only: there is no `PreCompact` trigger, so the snapshot/binding step stays
explicit there.

## Troubleshooting

- **`resume` exits `3`**: several active runs. Run `resume status --json`, then
  `resume bind --slug SLUG` or pass `--slug`.
- **Hooks do nothing**: the session has no per-session binding. `current.json`
  and a single active run are not hook fallbacks. Bind with `resume bind --slug
  SLUG --session-id ID` (in Claude Code, `--session-id
  "$CLAUDE_CODE_SESSION_ID"`).
- **Hooks warn `invalid session binding`**: the per-session pointer exists but
  its project, run, path, or run identity no longer matches. Rebind the session.
- **Pointer ignored**: the warning names the pointer. Check that the project
  root, session id, run path, and run slug still match.
- **Evidence `unbound`**: the workspace changed during the check or the identity
  could not be computed. Rerun the check in a stable tree.
- **`dirty-unbounded`**: too many or too large untracked files, or a special file.
  Narrow the working tree or clean generated files, then rerun.
- **`stale-lease`**: a non-running task still holds a lease. Confirm the worker
  stopped, then release it with its token.

## Real-client validation protocol

Run this in a disposable project, not in the main checkout. Record evidence for
each step; a step that was not observed is `not run`, not passed.

1. Prepare: `agent-team init --scope project`, `agent-team run init --slug
   compact-check --tier solo`, write a minimal `requirements.md` and `plan.md`,
   then `agent-team run verify --slug compact-check --producer operator --
   true`.
2. Install hooks: `agent-team resume hooks --install --apply`; confirm the diff
   and `.agent-team/hooks-state.json`.
3. Start a fresh Claude Code session in that project; confirm the hooks are
   loaded (`/hooks`).
4. Bind: `agent-team resume bind --slug compact-check --session-id
   "$CLAUDE_CODE_SESSION_ID"`. The hook only uses this per-session pointer.
5. Trigger a manual compact (`/compact`) and record whether `PreCompact` wrote
   `recovery/snapshot.json` and refreshed the pointer.
6. After compaction, record whether `SessionStart` injected the summary: check
   that the model can state the run slug, open gates, evidence state, and next
   action without rereading the manifest.
7. Repeat with an automatic compaction in a long session, if practical.
8. Failure cases: remove the per-session pointer and confirm the hook stays
   silent; write an invalid pointer and confirm the warning path; create two
   active runs and confirm no silent selection.
9. Uninstall: `agent-team resume hooks --remove --apply`; confirm existing hooks
   and unrelated settings are unchanged.
10. Record: client version, hook file, event, exit code, whether injection
    arrived, summary accuracy, and any mismatch with this document.

Until that protocol has been executed and recorded, treat hook-based recovery as
implemented and unit-tested, not as verified end to end.

### Validation status

On 2026-10-31, steps 1, 2, 4, 5, 6, 8, and 9 of this protocol were executed in a
disposable project with a tracked run manifest, using the generated hook commands
with real stdin payloads. Results: evidence stayed `bound` after `run verify`,
hook installation, and binding; `PreCompact` wrote the snapshot and pointer and
exited 0; `SessionStart` emitted the expected context (514 characters) and
exited 0; two active runs produced `resume` exit 3, `PreCompact` exit 1, and a
`SessionStart` warning with exit 0; removal restored the original settings
byte-for-byte in structure, including a pre-existing AskHuman hook.

On 2026-11-01, a real Claude Code session in a second isolated project ran a
manual compaction with both hooks installed. The `SessionStart` injection
arrived, and the model reported the run slug, `planned` status, tier, evidence
counts (`1 bound`), open gates (`worktree`, `live_validation`), and next action
without reading any file. The reported workspace identity and revision matched
the prepared state. `PreCompact` output was not separately inspected before the
project was removed, and automatic compaction was not exercised.

Manual-compaction recovery is therefore observed end to end. Automatic
compaction and the `--fail-closed` blocking path remain unverified in a live
client.

## Compatibility and rollback

`lease` and `[[verification]]` are optional additions to schema version 1. Older
runs need no migration, but older `agent-team` versions reject runs that use the
new fields. Before rolling back, archive the evidence and remove the added
fields. `resume hooks --remove --apply` removes the hooks; deleting the resume
subcommands does not affect other commands.
