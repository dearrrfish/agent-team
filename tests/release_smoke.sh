#!/usr/bin/env bash

set -euo pipefail

agent_team_bin=${1:?"usage: release_smoke.sh AGENT_TEAM_BIN SMOKE_ROOT"}
smoke_root=${2:?"usage: release_smoke.sh AGENT_TEAM_BIN SMOKE_ROOT"}

mkdir -p "${smoke_root}"
cd "${smoke_root}"

"${agent_team_bin}" --version
"${agent_team_bin}" init
"${agent_team_bin}" validate --format json
"${agent_team_bin}" run init \
  --slug release-smoke \
  --tier team \
  --model-preset balanced

for target in codex claude antigravity; do
  "${agent_team_bin}" render \
    --target "${target}" \
    --run release-smoke \
    --output "dist/${target}"
  "${agent_team_bin}" install \
    --target "${target}" \
    --run release-smoke \
    --apply
  "${agent_team_bin}" install \
    --target "${target}" \
    --run release-smoke \
    --apply | grep -q "unchanged"
done

"${agent_team_bin}" validate --format json
"${agent_team_bin}" doctor --format json

test -f .agent-team/install-state.json
test -f dist/codex/.codex/agents/coordinator.toml
test -f dist/claude/.claude/agents/coordinator.md
test -f dist/antigravity/.agents/agents/coordinator/agent.md
