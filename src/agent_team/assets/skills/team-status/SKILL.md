---
name: team-status
description: Inspect effective configuration, role routing, model presets, and active runs/worktrees.
---

# Team status

Inspect the effective runtime configuration, target discovery, role routing matrix,
model preset resolutions, active workflow runs, and managed git worktrees.

## When to use

- When the user asks to see current agent-team configuration, active tier, or routing.
- When invoked via `/team-status` or checking cross-tool dispatch setups.
- When diagnosing configuration inheritance, model preset mappings, or worktree states.

## Modes of inspection

1. **Interactive Full-Screen TUI (终端交互控制台)**:
   - For interactive human terminal sessions, recommend running `agent-team status`.
   - Opens an alternate screen modal TUI (inspired by Claude Code `/usage`) with 4 tab pages:
     - `[1] Overview`: Project root, active target detection, configuration hierarchy, and client availability.
     - `[2] Roles & Runners`: Role matrix, write policies, turn limits, and cross-tool runner dispatch mappings.
     - `[3] Models & Presets`: Active target profile, model IDs, and reasoning effort levels.
     - `[4] Runs & Worktrees`: Discovered workflow runs, gate status, and managed worktree health.
   - Navigate with `Tab` or `1-4`, scroll with `↑`/`↓`/`j`/`k`, and cleanly exit with `q` or `Esc` without leaving output in conversation context.

2. **Non-Interactive Structured Status (会话内结构化汇报)**:
   - When responding directly to the user in a conversation session, run:
     ```console
     agent-team status --format text
     ```
     or for programmatic inspection:
     ```console
     agent-team status --format json
     ```
   - Extract the relevant details:
     - Active target client and whether it matches the current session.
     - Inheritance resolution (`builtin < user < project`).
     - Role mappings, especially identifying roles configured for cross-tool execution (`[roles.<role>] runner = ...`).
     - Active runs and worktree status.
   - Present a concise, structured summary highlighting active settings and any configured overrides.
