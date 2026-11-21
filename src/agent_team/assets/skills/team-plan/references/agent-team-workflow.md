# Agent Teams planning


If the user explicitly asks for the agent-team coordinator in the main thread,
ask whether to load the coordinator harness into this thread or spawn a dedicated
native coordinator subagent. Explain both options and wait for the choice before
spawning.

When design help is needed, explicitly assign `proposal` or `audit` mode to
design-agent; audit is the default. Use a fresh instance to independently audit
a proposal produced by another instance. Artifact-only audits establish document
consistency and completeness, not unverified repository or runtime facts.
Supply named explorer evidence or obtain it before accepting those assumptions.
Do not delegate implementation while material decisions remain open.

### Lean planning rules (精简规划原则)

- Keep plans focused on user value and working software. Do not subdivide
  straightforward tasks into dozens of micro-runs.
- Disallow planning runs whose sole purpose is to plan or preview another test
  harness.
- Set clear acceptance criteria based on runnable end-to-end behavior, not
  formalistic document gates.
