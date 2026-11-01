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

Selection order is: explicit `--slug`, then the session pointer, then the
project-level `current.json`, then a single active run. If several active runs
exist and no valid pointer names one, `resume` prints candidates and exits `3`
instead of guessing. Exit code `2` means bad input or an unreadable run.

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
match.

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
even when it is tracked: `.agent-team/**` and `.claude/settings.local.json` are
left out, so recording a check, binding a session, writing a snapshot, or
installing hooks cannot invalidate the evidence it just recorded. Changes to
source, configuration, and other tracked files still do.

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
agent-team resume hooks --print
agent-team resume hooks --install --apply
agent-team resume hooks --remove --apply
```

Installation is project-only and defaults to `.claude/settings.local.json`; use
`--hooks-file` to choose another project-relative file. Preview is the default.
On apply, the previous file is backed up under `.agent-team/backups/`, the exact
groups written are recorded in `.agent-team/hooks-state.json`, and only those
groups are removed later. Existing hooks, such as an AskHuman `SessionStart`
hook, are preserved. If a managed group was edited by hand, the command refuses
to overwrite or remove it; reconcile it manually.

| Event | Action |
| --- | --- |
| `PreCompact` (`manual\|auto`) | Writes `recovery/snapshot.json` and binds the session to the selected run |
| `SessionStart` (`compact`) | Reads run files and emits `additionalContext` with the bounded summary |

Exit codes are deliberate:

- `precompact` fails with `1` by default, which does not block compaction. With
  `--fail-closed` it fails with `2`, which blocks compaction.
- `session-start` always exits `0`, including for bad input, no candidate, or
  multiple candidates; it injects a warning and tells the operator to check
  `resume status --json`.

Hook commands run through the interpreter and package path that generated them,
so a stale executable earlier on `PATH` is not used. After installation, Claude
Code must reload settings (for example via `/hooks` or a restart) before the new
entries take effect.

## Clients without hooks

Codex and Antigravity have no verified equivalent trigger. Recovery there is
explicit: run `agent-team resume` after compaction and follow the printed next
action. Do not describe hook-based recovery as available on those clients.

## Troubleshooting

- **`resume` exits `3`**: several active runs. Run `resume status --json`, then
  `resume bind --slug SLUG` or pass `--slug`.
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
4. Bind: `agent-team resume bind --slug compact-check`.
5. Trigger a manual compact (`/compact`) and record whether `PreCompact` wrote
   `recovery/snapshot.json` and refreshed the pointer.
6. After compaction, record whether `SessionStart` injected the summary: check
   that the model can state the run slug, open gates, evidence state, and next
   action without rereading the manifest.
7. Repeat with an automatic compaction in a long session, if practical.
8. Failure cases: remove the pointer and confirm the warning path; create two
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
