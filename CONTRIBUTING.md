# Contributing

Thanks for helping improve `agent-team`. Focused bug fixes, compatibility
evidence, documentation improvements, and well-scoped workflow changes are
welcome.

## Before starting

- Search existing issues and release notes before opening a duplicate.
- Open an issue before a large behavior, schema, or lifecycle change.
- Report vulnerabilities through the private process in [SECURITY.md](SECURITY.md),
  never through a public issue.
- Keep Codex as the supported target unless equivalent native evidence justifies
  changing an experimental adapter's status.

## Development setup

Use the repository's Nix development environment:

```console
git clone https://github.com/dearrrfish/agent-team.git
cd agent-team
nix develop
python -m agent_team --version
```

The implementation supports Python 3.11 or newer. Nix is the authoritative
package and release environment.

## Change workflow

1. Create a focused branch from `main`.
2. Preserve the public CLI, schemas, and lifecycle rules unless the proposal
   explicitly changes them.
3. Use [Conventional Commits](https://www.conventionalcommits.org/) and sign
   commits when your Git setup supports it.
4. Add or update regression coverage for behavior changes.
5. Update operator documentation and `CHANGELOG.md` when users are affected.
6. Open a pull request using the repository template.

Do not commit secrets, `.env` files, `.agent-team/install-state.json`, generated
run artifacts, or native-client credentials.

## Verification

Run the same core checks used by CI:

```console
python -m unittest discover -s tests -v
python -m compileall -q src tests
nix flake check --print-build-logs
nix flake check --all-systems --no-build
```

`nix flake check` also runs Ruff, Markdownlint, ShellCheck, and the installed
cross-target smoke test. Native-client claims require direct evidence; generated
output alone is not proof of native discovery or model-backed role selection.

## Review expectations

Pull requests should explain the user-visible outcome, identify compatibility
or migration effects, and list exact verification results. Maintainers may ask
for smaller scope, stronger tests, or target-specific evidence before merging.
