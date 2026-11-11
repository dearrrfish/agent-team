---
name: team-docs
description: Document synchronization, contract verification, and architecture decision records.
---

# Team docs

Maintain user-facing documentation, architecture decision records (ADRs), and
API contract specifications synchronized with code changes.

## Documentation protocol

1. **Contract Change Synchronization (契约变更强制联动)**:
   - When public interfaces, CLI commands, configuration options, data schemas,
     or error semantics change, synchronously update user-facing documentation
     (`README.md`, `docs/`, manpages, and help text).
   - Ensure CLI `--help` text, usage examples, and manual pages describe the
     current effective behavior and options.

2. **Runnable Command & Example Verification (示例可执行性实测)**:
   - Every shell command, CLI invocation, code snippet, and configuration
     sample in documentation must be verified by actual execution in the
     target environment.
   - Do not document unverified hypothetical commands or broken relative paths.
   - Verify that links, file references, and cross-references resolve
     correctly.

3. **Architecture Decision Records (ADR 规范)**:
   - Record significant architectural, data model, or workflow decisions in
     `decisions.md` (for active runs) or `docs/adr/`.
   - Include Status, Context, Decision, Consequences, and Alternatives
     Considered.
   - Ensure the rationale explains "why X over Y", making decisions durable
     and auditable.

4. **Release Notes & Migration Guides**:
   - Provide clear, structured release notes categorizing changes into
     Features, Fixes, Breaking Changes, and Internal Refactoring.
   - For breaking changes, document migration steps with concrete
     before-and-after examples.
