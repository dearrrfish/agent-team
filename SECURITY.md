# Security Policy

## Supported versions

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Earlier or unreleased snapshots | No |

Security fixes are applied to the latest supported release line. This policy may
change when another maintained release line exists.

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability. Use GitHub's
[private vulnerability reporting](https://github.com/dearrrfish/agent-team/security/advisories/new)
to send the maintainers:

- the affected version or commit;
- the impact and realistic attack scenario;
- minimal reproduction steps or a proof of concept;
- any suggested mitigation; and
- whether the report is subject to a disclosure deadline.

Remove unrelated credentials and personal data. Maintainers will acknowledge and
triage reports as soon as practical, coordinate fixes and disclosure through the
private advisory, and credit reporters who request attribution.

## Scope

Security-relevant areas include path containment, native profile generation,
template substitution, installation ownership and backup behavior, unintended
file writes, and exposure of credentials through generated output or logs.
Missing product features, unsupported native-client behavior, and ordinary bugs
without a security impact belong in the public issue tracker.
