from __future__ import annotations

import curses
import json
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from agent_team.config import (
    load_roles,
    load_team_config,
    resolve_target_profile,
)
from agent_team.models import TARGETS, TeamConfig
from agent_team.recovery import discover_runs
from agent_team.version import get_version
from agent_team.worktrees import list_worktrees


@dataclass
class TargetStatus:
    name: str
    is_active: bool
    executable: str | None
    version: str | None
    profile_id: str | None


@dataclass
class RoleStatus:
    role_id: str
    description: str
    runner: str | None
    is_cross_tool: bool
    write_policy: str
    report_kind: str
    max_turns: int
    model_class: str
    effort: str | None
    capabilities: list[str]


@dataclass
class PresetMapping:
    preset: str
    coordinator_model: str
    fast_model: str
    balanced_model: str
    deep_model: str


@dataclass
class RunSummary:
    slug: str
    title: str
    status: str
    tier: str
    preset: str
    created_at: str


@dataclass
class WorktreeSummary:
    path: str
    branch: str
    slug: str
    status: str
    prunable: bool


@dataclass
class TeamStatusReport:
    version: str
    root: Path
    active_target: str
    inherit_user_defaults: bool
    user_config_exists: bool
    project_config_exists: bool
    run_root: str
    worktree_root: str
    worktree_default_cleanup: str
    targets: list[TargetStatus]
    roles: list[RoleStatus]
    presets: list[PresetMapping]
    runs: list[RunSummary]
    worktrees: list[WorktreeSummary]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["root"] = str(self.root)
        return data


def detect_active_target(root: Path, config: TeamConfig, requested_target: str | None = None) -> str:
    if requested_target and requested_target in TARGETS:
        return requested_target

    # Environment variables inspection
    if os.environ.get("PI_SESSION_ID") or os.environ.get("PI_CODING_AGENT"):
        return "pi"
    if os.environ.get("CLAUDE_PROJECT_ROOT") or os.environ.get("CLAUDE_CODE"):
        return "claude"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_SESSION"):
        return "codex"

    # Directory checks in project
    for candidate in ["codex", "claude", "antigravity", "pi"]:
        if (root / f".{candidate}").is_dir():
            return candidate

    for target in config.enabled_targets:
        if target in TARGETS:
            return target

    return "codex"


def _get_target_executable_and_version(target: str) -> tuple[str | None, str | None]:
    cmd_map = {
        "codex": "codex",
        "claude": "claude",
        "antigravity": "antigravity",
        "pi": "pi",
    }
    binary = shutil.which(cmd_map.get(target, target))
    if not binary:
        return None, None

    # Version check is optional and non-blocking
    return binary, "installed"


def collect_team_status(root: Path, requested_target: str | None = None) -> TeamStatusReport:
    config = load_team_config(root)
    active_target = detect_active_target(root, config, requested_target)

    user_config_path = Path.home() / ".agent-team" / "team.toml"
    project_config_path = root / ".agent-team" / "team.toml"

    # Targets
    target_statuses: list[TargetStatus] = []
    for t in TARGETS:
        exe, ver = _get_target_executable_and_version(t)
        profile = config.target_profiles.get(t)
        target_statuses.append(
            TargetStatus(
                name=t,
                is_active=(t == active_target),
                executable=exe,
                version=ver,
                profile_id=profile,
            )
        )

    # Roles
    all_roles = load_roles(config, root)
    roles_list: list[RoleStatus] = []
    for r in all_roles:
        is_cross = bool(r.runner and r.runner != active_target)
        roles_list.append(
            RoleStatus(
                role_id=r.role_id,
                description=r.description,
                runner=r.runner,
                is_cross_tool=is_cross,
                write_policy=r.write_policy,
                report_kind=r.report_kind,
                max_turns=r.max_turns,
                model_class=r.model_class,
                effort=r.effort,
                capabilities=list(r.capabilities),
            )
        )

    # Presets mapping for active target
    profile = resolve_target_profile(config, active_target, root)
    presets_list: list[PresetMapping] = []
    if profile:
        for preset_name, tp in profile.presets.items():
            presets_list.append(
                PresetMapping(
                    preset=preset_name,
                    coordinator_model=tp.coordinator_model,
                    fast_model=tp.models.get("fast", "-"),
                    balanced_model=tp.models.get("balanced", "-"),
                    deep_model=tp.models.get("deep", "-"),
                )
            )

    # Runs
    discovered_runs = discover_runs(root, config)
    runs_list: list[RunSummary] = []
    for run in discovered_runs[:10]:
        manifest = run.manifest or {}
        runs_list.append(
            RunSummary(
                slug=run.slug,
                title=manifest.get("title", run.slug),
                status=manifest.get("status", "unknown"),
                tier=manifest.get("tier", "unknown"),
                preset=manifest.get("model_preset", "unknown"),
                created_at=manifest.get("created_at", ""),
            )
        )

    # Worktrees
    discovered_worktrees = list_worktrees(root, config.workflow.worktree_root)
    worktrees_list: list[WorktreeSummary] = []
    for wt in discovered_worktrees:
        worktrees_list.append(
            WorktreeSummary(
                path=str(wt.path),
                branch=wt.branch or "(detached)",
                slug=wt.associated_slug or "",
                status=wt.status.value,
                prunable=wt.is_prunable,
            )
        )

    return TeamStatusReport(
        version=get_version(),
        root=root,
        active_target=active_target,
        inherit_user_defaults=config.inherit_user_defaults,
        user_config_exists=user_config_path.is_file(),
        project_config_exists=project_config_path.is_file(),
        run_root=str(config.workflow.run_root),
        worktree_root=str(config.workflow.worktree_root),
        worktree_default_cleanup=config.workflow.worktree_default_cleanup,
        targets=target_statuses,
        roles=roles_list,
        presets=presets_list,
        runs=runs_list,
        worktrees=worktrees_list,
    )


# ---------------------------------------------------------------------------
# Tab Text Formatters
# ---------------------------------------------------------------------------

def _render_tab_overview(r: TeamStatusReport) -> list[str]:
    lines = [
        "== Agent Team Overview ==",
        "",
        f"Project Root:         {r.root}",
        f"Active Target:        {r.active_target}",
        f"Agent-Team Version:   v{r.version}",
        "",
        "Configuration Hierarchy:",
        f"  Inherit User Defaults: {'yes' if r.inherit_user_defaults else 'no (isolated)'}",
        f"  User Config:           {'present (~/.agent-team/team.toml)' if r.user_config_exists else 'absent'}",
        f"  Project Config:        {'present (.agent-team/team.toml)' if r.project_config_exists else 'absent'}",
        "",
        "Workflow & Worktrees:",
        f"  Runs Directory:        {r.run_root}",
        f"  Worktrees Directory:   {r.worktree_root}",
        f"  Worktree Auto-Cleanup: {r.worktree_default_cleanup}",
        "",
        "Target Clients Status:",
    ]
    for t in r.targets:
        active_mark = "*ACTIVE*" if t.is_active else "        "
        status_mark = "available" if t.executable else "missing"
        lines.append(f"  {active_mark} {t.name:<12} [{status_mark:<9}] (profile: {t.profile_id or 'none'})")
    return lines


def _render_tab_roles(r: TeamStatusReport) -> list[str]:
    lines = [
        "== Roles & Dispatch Routing ==",
        "",
        f"{'ROLE':<15} {'RUNNER':<16} {'POLICY':<10} {'REPORT':<14} {'TURNS':<6} {'MODEL CLASS':<12}",
        "-" * 78,
    ]
    for role in r.roles:
        runner_display = role.runner or f"({r.active_target})"
        if role.is_cross_tool:
            runner_display += " [CROSS]"
        lines.append(
            f"{role.role_id:<15} {runner_display:<16} {role.write_policy:<10} "
            f"{role.report_kind:<14} {role.max_turns:<6} {role.model_class:<12}"
        )
    lines.append("")
    lines.append("Note: [CROSS] indicates role is configured to execute via cross-tool dispatch.")
    return lines


def _render_tab_models(r: TeamStatusReport) -> list[str]:
    lines = [
        f"== Model Presets for Active Target ({r.active_target}) ==",
        "",
        f"{'PRESET':<12} {'COORDINATOR':<20} {'FAST':<20} {'BALANCED':<20} {'DEEP'}",
        "-" * 88,
    ]
    if not r.presets:
        lines.append("  No preset mappings resolved for this target.")
    for p in r.presets:
        lines.append(
            f"{p.preset:<12} {p.coordinator_model:<20} {p.fast_model:<20} "
            f"{p.balanced_model:<20} {p.deep_model}"
        )
    lines.append("")
    lines.append("Configured target profiles:")
    for t in r.targets:
        lines.append(f"  {t.name:<12} -> {t.profile_id or 'default'}")
    return lines


def _render_tab_worktrees(r: TeamStatusReport) -> list[str]:
    lines = [
        "== Recent Runs & Active Worktrees ==",
        "",
        "--- Recent Runs ---",
        f"{'SLUG':<24} {'STATUS':<12} {'TIER':<10} {'PRESET':<10} {'TITLE'}",
        "-" * 75,
    ]
    if not r.runs:
        lines.append("  (No runs found)")
    for run in r.runs:
        lines.append(f"{run.slug:<24} {run.status:<12} {run.tier:<10} {run.preset:<10} {run.title}")

    lines.append("")
    lines.append("--- Active Worktrees ---")
    lines.append(f"{'BRANCH':<24} {'STATUS':<14} {'SLUG':<20} {'PATH'}")
    lines.append("-" * 75)
    if not r.worktrees:
        lines.append("  (No managed worktrees)")
    for wt in r.worktrees:
        lines.append(f"{wt.branch:<24} {wt.status:<14} {wt.slug:<20} {wt.path}")
    return lines


# ---------------------------------------------------------------------------
# Output Formatters: Text & JSON
# ---------------------------------------------------------------------------

def format_text_status(report: TeamStatusReport) -> str:
    sections = [
        _render_tab_overview(report),
        [""],
        _render_tab_roles(report),
        [""],
        _render_tab_models(report),
        [""],
        _render_tab_worktrees(report),
    ]
    flattened = [line for section in sections for line in section]
    return "\n".join(flattened)


def format_json_status(report: TeamStatusReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Curses Multi-Tab Interactive TUI
# ---------------------------------------------------------------------------

def _tui_main(stdscr: curses.window, report: TeamStatusReport) -> None:
    try:
        curses.curs_set(0)
    except curses.error:
        pass

    try:
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)   # Active tab header
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)   # Top/bottom bars
        curses.init_pair(3, curses.COLOR_GREEN, -1)                  # Highlights
        curses.init_pair(4, curses.COLOR_YELLOW, -1)                 # Warnings / Notice
    except curses.error:
        pass

    tabs = ["Overview", "Roles & Runners", "Models & Presets", "Runs & Worktrees"]
    active_tab = 0
    scroll_offsets = [0, 0, 0, 0]

    tab_renderers = [
        _render_tab_overview,
        _render_tab_roles,
        _render_tab_models,
        _render_tab_worktrees,
    ]

    while True:
        max_y, max_x = stdscr.getmaxyx()
        if max_y < 6 or max_x < 30:
            stdscr.erase()
            stdscr.addstr(0, 0, "Terminal window too small.")
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q'), 27):
                break
            continue

        stdscr.erase()

        # Header bar
        header = f" agent-team status  •  Target: {report.active_target}  •  Project: {report.root.name} "
        stdscr.addnstr(0, 0, header.ljust(max_x), max_x, curses.color_pair(2) | curses.A_BOLD)

        # Tab bar
        tab_offset = 1
        for i, name in enumerate(tabs):
            tab_label = f" [{i+1}] {name} "
            if i == active_tab:
                stdscr.addnstr(1, tab_offset, tab_label, max_x - tab_offset, curses.color_pair(1) | curses.A_BOLD)
            else:
                stdscr.addnstr(1, tab_offset, tab_label, max_x - tab_offset, curses.A_DIM)
            tab_offset += len(tab_label) + 1

        stdscr.addnstr(2, 0, "─" * max_x, max_x, curses.A_DIM)

        # Content lines
        content_lines = tab_renderers[active_tab](report)
        viewport_height = max_y - 4
        scroll = scroll_offsets[active_tab]
        max_scroll = max(0, len(content_lines) - viewport_height)
        scroll = min(scroll, max_scroll)
        scroll_offsets[active_tab] = scroll

        for y in range(min(viewport_height, len(content_lines) - scroll)):
            line = content_lines[scroll + y]
            stdscr.addnstr(3 + y, 1, line, max_x - 2)

        # Footer
        footer = " [Tab / 1-4] Switch Tab   [↑/↓/j/k] Scroll   [q / Esc] Exit"
        if max_scroll > 0:
            footer += f"   (Line {scroll + 1}-{min(scroll + viewport_height, len(content_lines))}/{len(content_lines)})"
        stdscr.addnstr(max_y - 1, 0, footer.ljust(max_x), max_x, curses.color_pair(2))

        stdscr.refresh()

        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27):  # q, Q, ESC
            break
        elif key in (ord('\t'), curses.KEY_RIGHT, ord('l')):
            active_tab = (active_tab + 1) % len(tabs)
        elif key in (curses.KEY_LEFT, ord('h')):
            active_tab = (active_tab - 1) % len(tabs)
        elif ord('1') <= key <= ord('4'):
            active_tab = key - ord('1')
        elif key in (curses.KEY_DOWN, ord('j')):
            if scroll_offsets[active_tab] < max_scroll:
                scroll_offsets[active_tab] += 1
        elif key in (curses.KEY_UP, ord('k')):
            if scroll_offsets[active_tab] > 0:
                scroll_offsets[active_tab] -= 1
        elif key in (curses.KEY_NPAGE, ord(' ')):
            scroll_offsets[active_tab] = min(max_scroll, scroll_offsets[active_tab] + viewport_height)
        elif key == curses.KEY_PPAGE:
            scroll_offsets[active_tab] = max(0, scroll_offsets[active_tab] - viewport_height)
        elif key == curses.KEY_HOME:
            scroll_offsets[active_tab] = 0
        elif key == curses.KEY_END:
            scroll_offsets[active_tab] = max_scroll


def run_status_tui(report: TeamStatusReport) -> int:
    try:
        curses.wrapper(_tui_main, report)
        return 0
    except (curses.error, Exception):
        # Fall back to text if curses is unsupported or fails
        print(format_text_status(report))
        return 0
