# DeepSeek Harness coexistence

Agent Teams skills supply guidance for planning, coordination, and review in
DeepSeek Harness (DSH). DSH and its presets select and spawn agents.
`dsh.agentTeams` manages shared tasks. `dsh-delivery` manages the single-task
plan, execution receipts, review, and final acceptance. A Team task ID is
only a reference for delivery.

## Enable compatibility

Compatibility is off by default. To enable the DSH templates for a project,
add this to `.agent-team/team.toml`:

```toml
[compatibility]
dsh = true
```

Preview and apply the update with the same target you already install for:

```bash
agent-team install --scope project --target codex --diff
agent-team install --scope project --target codex --apply
```

For a user installation, put the setting in `~/.agent-team/team.toml` and use
`--scope user`. A project can opt out of inherited compatibility with
`dsh = false`. The setting controls rendering for the selected scope, including
when preparing files from a shell outside DSH. Enabling it adds DSH guidance to
agents and installs the compatible skills and their CLI workflow references.
The supported target list stays the same.

Managed files update in place. Edited or unmanaged files follow the installer's
existing `--force` and backup rules. To restore standard agents and skills,
set `dsh = false` and reinstall. Unused CLI workflow references remain on disk
as stale managed files. A project skill can take precedence over the user copy
in DSH. Refresh the applicable scope and verify the loaded source in a fresh
session.

## Detect the current host

`agent-team status --format json` reports `host` and `host_source` separately
from the CLI's `active_target`. A DSH shell supplies `DSH_SHELL=1` and a
nonempty `DSH_SESSION_ID`. Partial DSH markers report an unknown host. The
report does not include the session ID. Client installation paths and
`--target` do not change the host result.

With compatibility enabled for the project, `agent-team dispatch` rejects
execution in a detected DSH session before it loads a run or starts a runner.
`--dry-run` still previews an explicit CLI
run. The shell markers protect against accidental dispatch and can be
inherited by nested shells. Native DSH delegation belongs to the host.

## Deploy role presets

Generate an installable local bundle at an explicit output path:

```bash
agent-team dsh scaffold --output ./dsh-role-presets
```

Open the generated `README.md` for the deployment steps. The tested runtime
version is DSH `0.2.2-rc.5` with the base-style tool composition used by DSH
TUI. Stock Web requires its own composition. Start in an
isolated profile. The bundle declares `agent-team-coordinator`,
`agent-team-explorer`, `agent-team-design-agent`, `agent-team-implementer`,
`agent-team-ops`, and `agent-team-reviewer`. Choose the coordinator in the main
session. It mounts its own tools, including the `skill` tool for installed
skills such as `dsh-delivery-feedback`, and delegates through the native fresh
spawn tool with the five worker presets. Each child has a separate instance
name, and the coordinator requires an explicit worker preset on each call.

The `team.toml` flag controls native client files. Preset deployment is a
separate step in DSH. To upgrade an earlier bundle, install the new bundle
directory in DSH and start a fresh session.
