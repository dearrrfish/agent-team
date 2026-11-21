# Agent Teams role presets for DeepSeek Harness

This bundle declares all six Agent Teams role presets for DSH `0.2.2-rc.5`.
Use a profile with the agent preset registry and the base filesystem, search,
web, shell, job, skill, Team, and delegation tools, such as the base-style
DSH TUI composition. Stock Web scopes those tools and spawn to its own
presets and requires a different composition. Keep the generated directory
at a stable path when linking it as an installed bundle.

| Preset | Tool access |
| --- | --- |
| `agent-team-coordinator` | Read, write, shell, jobs, web, skills, native Team tasks, and fresh delegation to worker presets |
| `agent-team-explorer` | Read, glob, grep, and web |
| `agent-team-design-agent` | Read, glob, grep, and web |
| `agent-team-implementer` | Read, write, shell, and jobs |
| `agent-team-ops` | Read, write, shell, jobs, and web |
| `agent-team-reviewer` | Read, glob, and grep |

Host sandbox permissions and web provider readiness still govern tool access.

1. Start with a disposable DSH profile. In **Plugins**, add this local bundle
   directory. Open a fresh session and verify all six preset IDs are available.
2. To delegate from `agent-team-coordinator`, merge `spawn-binding.patch.yml`
   into the profile overrides. The example is for the base `spawn` provider.
   Keep any existing `tool-subagent` config fields and preset choices needed
   by the profile's other sessions.
3. Select `agent-team-coordinator` for the main session. Check that `subagent`
   exposes `agent_preset` with the five worker presets, and set it explicitly
   on each call. Give each child its own instance name. Verify the tool lists
   against the table before use.

Installation alone registers roles. It does not activate the separate
spawn-binding patch. The shared skills describe responsibilities. DSH and
its presets decide when to spawn. Team tasks are owned by `dsh.agentTeams`.
A Team task ID is a reference for `dsh-delivery`, which keeps its own presets,
plan approvals, receipts, and final acceptance.

To roll back, remove the optional spawn binding and uninstall this bundle in
DSH. Open a fresh session to verify the configuration. Existing run and task
records need no migration.
