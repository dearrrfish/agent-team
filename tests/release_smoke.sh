#!/usr/bin/env bash

set -euo pipefail

agent_team_bin=${1:?"usage: release_smoke.sh AGENT_TEAM_BIN SMOKE_ROOT"}
smoke_root=${2:?"usage: release_smoke.sh AGENT_TEAM_BIN SMOKE_ROOT"}

if [[ "${AGENT_TEAM_SMOKE_ISOLATED:-}" != "1" ]]; then
  mkdir -p "${smoke_root}/home" "${smoke_root}/project"
  exec env HOME="${smoke_root}/home" AGENT_TEAM_SMOKE_ISOLATED=1 \
    bash "$0" "${agent_team_bin}" "${smoke_root}"
fi
cd "${smoke_root}/project"

"${agent_team_bin}" --version
"${agent_team_bin}" init --scope user
"${agent_team_bin}" install --scope user --target codex,claude,antigravity --apply
"${agent_team_bin}" install --scope user --target codex,claude,antigravity --apply | grep -q "unchanged"
test ! -e "${HOME}/.agent-team/runs"
test ! -e "${HOME}/.agent-team/templates"
test ! -e "${HOME}/.agent-team/backups"
"${agent_team_bin}" init
"${agent_team_bin}" generate
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
