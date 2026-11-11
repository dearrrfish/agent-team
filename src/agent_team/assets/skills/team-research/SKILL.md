---
name: team-research
description: Read-only technical research, Spike feasibility studies, and decision packs.
---

# Team research

Perform read-only technical exploration, library evaluation, API Spike
investigations, and architectural feasibility studies to produce structured
decision packs for planning.

## Research protocol

1. **Read-Only / Sandboxed Discovery (只读探索模式)**:
   - Inspect codebase facts, examine library sources, API signatures, and
     documentation without modifying product code or creating commits.
   - Keep the working tree clean. If experimental spike code is needed, use an
     isolated temporary directory or throwaway script outside tracked paths.

2. **Strict Fact vs. Assumption Separation (事实与推论严格分离)**:
   - Clearly delineate verified codebase and environment facts (exact
     signatures, platform behaviors, dependencies, exit codes) from unverified
     assumptions and theoretical inferences.
   - Distinguish platform realities (e.g. Linux vs macOS vs Windows paths and
     toolchains) from generic documentation claims.

3. **Structured Decision Pack (结构化决策包)**:
   - Deliver findings as a structured decision pack to feed into `team-plan`:
     - **Context & Objective**: Problem statement and questions investigated.
     - **Options & Tradeoff Matrix**: Viable alternatives compared by
       complexity, dependencies, performance, and maintenance risk.
     - **Platform & Boundary Constraints**: Discovered edge cases, version
       requirements, and security boundaries.
     - **Recommended Path**: Concrete choice with decisive engineering
       rationale.
   - Do not begin production implementation or modify manifests during research.
