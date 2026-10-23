If the user explicitly asks for the agent-team coordinator in the main thread,
ask whether to load the coordinator harness into this thread or spawn a dedicated
native coordinator subagent. Explain both options and wait for the choice before
spawning. Then act as the selected coordinator and use $team-coordinate. Read
.agent-team/runs/<slug>/run.toml and plan.md, plus tasks.md for team tier. For
assisted tier, record bounded task entries in run.toml and serialize writers.
Split the next wave into file-disjoint scopes and spawn implementer or ops custom
agents only where their files do not overlap. Give each worker a unique instance
name, task ID, exact files, acceptance criteria, verification commands, and
report path. Wait for all workers, then consolidate their evidence and update
the run state.

### Anti-Involution Circuit Breakers (防内卷断路器)

1. **No Recursive Planning & Recovery Loops (禁止套娃复苏)**:
   - When a test, fixture, or environment verification fails, fix it in-place within the active task or report directly to the human.
   - Do NOT create new child runs to "plan", "prepare materials for", or "review" recovery of the test harness.
   - Maximum 1 direct recovery attempt per failure before human escalation.

2. **Pragmatic Scope & Scaffolding Limits (禁止过度工程)**:
   - Test fixtures and diagnostic scaffolding must not exceed 50% of the target feature's code size.
   - Local single-user tools must not construct adversarial kernel-level defense architectures (e.g., pidfd namespaces, SCM_RIGHTS brokers, synthetic oracles). Rely on OS user isolation.

3. **Consecutive Non-Product Run Halting (零产出停机)**:
   - If two consecutive runs produce 0 lines of product code and only touch manifests, test previews, or test fixtures, halt the pipeline immediately and escalate to the human via AskHuman.

4. **Human-First Language Protocol (人话报告规范)**:
   - Strictly forbid telegraphic run-on text without spaces (e.g., no `namedT001/T002/root`, `failedspoofs`).
   - Forbid defensive boilerplate spam (do not repeat paragraphs of `no native authority granted / synthetic oracle assumption only`).
   - All reports and reviews must be concise, structured, and understandable to a human engineer:
     1. What was done (plain language summary)
     2. Verification evidence & concrete results
     3. Blockers & real tradeoffs
     4. Concrete next steps
