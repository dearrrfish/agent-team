# Agent Teams role presets for DeepSeek Harness

This bundle declares all six Agent Teams role presets for DSH `0.2.2-rc.5`.
Use a profile with the agent preset registry and the base filesystem, search,
web, shell, job, skill, Team, and delegation tools, such as the base-style
DSH TUI composition. Stock Web scopes those tools and spawn to its own
presets and requires a different composition. Keep the generated directory
at a stable path when linking it as an installed bundle.

| Preset | Tool access |
| --- | --- |
| `agent-team-coordinator` | Read, `read_image`, write, shell, jobs, web, skills, `ask_user_question`, native Team tasks, optional `delivery_*` coordinator tools, and fresh delegation to worker presets |
| `agent-team-explorer` | Read, `read_image`, glob, grep, and web |
| `agent-team-design-agent` | Read, `read_image`, glob, grep, and web |
| `agent-team-implementer` | Read, `read_image`, write, shell, and jobs |
| `agent-team-ops` | Read, `read_image`, write, shell, jobs, and web |
| `agent-team-reviewer` | Read, `read_image`, glob, and grep |

Host sandbox permissions, attachment storage, model image support, and web
provider readiness still govern tool access. `role-policy` allows non-child
`delivery_*` tools on `agent-team-coordinator` by default (`allowDeliveryTools`,
`extraTools`, and `extraToolPrefixes` can customize per-role access) while
keeping `delivery_list`, `delivery_mkdir`, `delivery_read`, `delivery_write`,
and `delivery_review_evidence` restricted to `dsh-delivery` child presets.

1. Start with a disposable DSH profile. In **Plugins**, add the absolute path
   of this local bundle directory. Open a fresh session and verify all six
   preset IDs are available.
2. Select `agent-team-coordinator` for the main session. The preset mounts its
   filesystem, shell, web, skill, question, and delegation tools. Structured
   questions require the Host `userQuestions` service and a client answerer.
   The coordinator manages the shared task board when native Team mode is enabled.
3. Check that `subagent` exposes `agent_preset` with the five worker presets,
   and set it explicitly on each call. Give each child its own instance name.
   Verify that the coordinator can send and receive a structured question and
   that the read-only roles expose no file mutation tools. The coordinator loads
   installed skills through the `skill` tool, including
   `dsh-delivery-feedback`; `/dsh-delivery-feedback` also works as a direct
   invocation.

The shared skills describe responsibilities. DSH and its presets decide when
to spawn. Team tasks are owned by `dsh.agentTeams`. A Team task ID is a
reference for `dsh-delivery`, which keeps its own presets, plan approvals,
receipts, and final acceptance. Saving a feedback report writes outside the
workspace, so the coordinator asks for that one command's approval when the
host sandbox requires it.

To roll back, uninstall this bundle in DSH. Open a fresh session to verify the
configuration. Existing run and task
records need no migration.
