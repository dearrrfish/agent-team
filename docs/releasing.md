# Releasing

This project currently supports a source/Nix release. Repository hosting and a
canonical remote are intentionally undecided, so do not add or publish URL
metadata until that destination is chosen.

## 1. Prepare the release

- Start from a clean `main` checkout.
- Confirm `.local/dev/progress.md` has no unresolved release blocker other than
  explicitly disclosed limitations.
- Update `CHANGELOG.md` and `docs/releases/<version>.md` with the release date,
  support status, verification evidence, and known limitations.
- Keep the version synchronized in `pyproject.toml`, `flake.nix`,
  `src/agent_team/__init__.py`, and the release-note heading.

```console
rg -n '__version__|version =|agent-team v' \
  pyproject.toml flake.nix src/agent_team/__init__.py docs/releases
```

## 2. Run release gates

```console
nix flake check
nix flake check --all-systems --no-build
nix build --no-link .#packages.x86_64-linux.default
nix run . -- --version
```

The native build must pass on each architecture before removing its unverified
label. Cross-evaluation is not runtime evidence.

For documentation releases, render and inspect every Mermaid diagram. The first
run may download a large Chromium closure:

```console
nix shell nixpkgs#mermaid-cli -c \
  mmdc -i README.md -o /tmp/agent-team-readme-rendered.md
```

## 3. Review the release diff

- Confirm `git diff --check` passes and no secret, credential, `.env`, generated
  install state, or run artifact is tracked.
- Confirm the README support matrix matches native validation evidence.
- Confirm the built artifact contains the CLI entry point, license, Python
  modules, roles, target profiles, skills, and templates.
- Run the CLI from the built package in a clean temporary project if the release
  smoke check changed.

## 4. Tag the approved commit

Create an annotated signed tag only after the release commit is integrated and
all required evidence is recorded:

```console
git tag -s v0.1.0 -m "agent-team v0.1.0"
git tag --verify v0.1.0
```

Do not push the tag until a canonical remote and publication destination are
configured and reviewed. Once chosen, add `[project.urls]`, remote installation
examples, and channel-specific publication steps in a separate change.
