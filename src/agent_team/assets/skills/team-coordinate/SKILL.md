---
name: team-coordinate
description: Coordinate bounded native subagents and integrate evidence-backed results.
---

# Team coordination

Keep user decisions in the coordinator. Dispatch only bounded independent work,
track dependencies and write ownership, require structured reports, and verify
results before integration. Stop dispatch when coordination costs exceed the
remaining task value.

## Native role selection

- Name the native custom-agent role explicitly when dispatching: `explorer`,
  `design-agent`, `implementer`, `ops`, or `reviewer`. Keep the instance or task
  name separate from the role name.
- Let the selected native agent profile own its model, reasoning effort,
  permissions, and durable role instructions. Do not repeat or override those
  settings unless the user explicitly requests a one-off override.
- For project-scoped Codex agents, confirm the project is trusted and start a
  fresh Codex session after installation. If the requested role is unavailable,
  stop and report the discovery problem; do not silently spawn a generic agent.

## Worker prompt contract

Give every worker:

- its native role and unique instance name;
- the run artifact path and task or wave ID;
- exact owned files plus an explicit no-edit boundary;
- acceptance criteria and exact verification commands;
- the required report path or structured return fields;
- notice of concurrent peers and whether the coordinator will wait for all of
  them before consolidation.
