from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

TIERS = ("solo", "assisted", "team")
TARGETS = ("codex", "claude", "antigravity")
PRESETS = ("economy", "balanced", "quality")
ROLE_IDS = ("coordinator", "explorer", "design-agent", "implementer", "ops", "reviewer")


@dataclass(frozen=True)
class TierConfig:
    max_workers: int
    durable_artifacts: bool
    independent_review: bool
    write_isolation: str


@dataclass(frozen=True)
class WorkflowConfig:
    run_root: Path
    review_cycle_limit: int
    deep_discovery_default: bool
    require_worktree_decision: bool
    persist_agent_reports: bool


@dataclass(frozen=True)
class InstallConfig:
    default_scope: str
    overwrite: str
    backups: bool
    modify_native_settings: bool


@dataclass(frozen=True)
class TeamConfig:
    schema_version: int
    team_id: str
    name: str
    description: str
    default_tier: str
    default_model_preset: str
    enabled_targets: tuple[str, ...]
    role_sources: tuple[str, ...]
    skill_sources: tuple[str, ...]
    target_profiles: Mapping[str, str]
    workflow: WorkflowConfig
    tiers: Mapping[str, TierConfig]
    install: InstallConfig


@dataclass(frozen=True)
class RoleDefinition:
    role_id: str
    description: str
    instructions: str
    model_class: str
    effort: str
    write_policy: str
    delegation: bool
    max_turns: int
    report_kind: str
    capabilities: tuple[str, ...]
    use_when: str
    avoid_when: str


@dataclass(frozen=True)
class TargetPreset:
    coordinator_model: str
    coordinator_effort: str | None
    models: Mapping[str, str]
    effort: Mapping[str, str]


@dataclass(frozen=True)
class TargetProfile:
    profile_id: str
    adapter: str
    agent_destination: str
    skill_destination: str
    user_agent_destination: str
    user_skill_destination: str
    supports_effort: bool
    effort_levels: tuple[str, ...]
    supports_worktree_isolation: bool
    team_runtime: str
    models_without_effort: tuple[str, ...]
    presets: Mapping[str, TargetPreset]
