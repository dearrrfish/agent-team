"""Static Pi declarations, never plugin execution or proof of runtime availability."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from agent_team.diagnostics import Diagnostic, ValidationFailure

_STANDARD = {"pi-subagents", "pi-agents-flow", "pi-web-access", "@tylerho/pi-worktree"}
_NPM = re.compile(r"npm:(?P<name>@[a-z0-9_.-]+/[a-z0-9_.-]+|[a-z0-9_.-]+)(?:@(?P<version>[^\s/]+))?$")


@dataclass(frozen=True)
class PiPluginStatus:
    subagent_package: str | None = None
    has_web: bool = False
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def has_worktree(self) -> bool:
        """Standard subagent plugins declare worktree:true; runtime is unverified."""
        return self.subagent_package in {"pi-subagents", "pi-agents-flow"}

    @property
    def has_subagent(self) -> bool:
        return self.subagent_package is not None


def agent_directory() -> Path:
    """Honor Pi's agent-directory override for discovery, without writing it."""
    return Path(os.environ.get("PI_CODING_AGENT_DIR", str(Path.home() / ".pi/agent"))).expanduser().resolve()


def _settings(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ValidationFailure([Diagnostic(str(path), f"Cannot read Pi settings: {exc}", code="pi-settings")]) from exc
    if not isinstance(value, dict):
        raise ValidationFailure([Diagnostic(str(path), "Pi settings must be an object", code="pi-settings")])
    for field in ("packages", "extensions"):
        if field in value and not isinstance(value[field], list):
            raise ValidationFailure([Diagnostic(str(path), f"{field} must be an array", code="pi-settings")])
    if any(not isinstance(item, str) for item in value.get("extensions", [])):
        raise ValidationFailure([Diagnostic(str(path), "extensions must contain strings", code="pi-settings")])
    return value


def scan_pi_plugins(root: Path, scope: str = "project") -> PiPluginStatus:
    """Inspect user and optionally project settings; unknown selectors fail closed.

    Only exact standard npm identities with unfiltered extension declarations
    count. Local code and custom packages are reported, never inferred by name.
    """
    if scope not in {"project", "user"}:
        raise ValueError("scope must be project or user")
    paths = [agent_directory() / "settings.json"]
    if scope == "project":
        paths.append(root / ".pi/settings.json")
    selected: dict[str, bool] = {}
    diagnostics: list[Diagnostic] = []
    excluded = False
    for path in paths:
        settings = _settings(path)
        for extension in settings.get("extensions", []):
            if extension.startswith(("!", "-")) and not extension[1:].startswith("builtin:"):
                excluded = True
                diagnostics.append(Diagnostic(str(path), "Extension exclusions cannot be resolved statically; plugin capabilities are unconfirmed", severity="warning", code="pi-selector"))
            elif not extension.lstrip("+-").startswith("builtin:"):
                diagnostics.append(Diagnostic(str(path), "Local/custom extensions are not executed or accepted as capability evidence", severity="warning", code="pi-custom-extension"))
        for entry in settings.get("packages", []):
            if isinstance(entry, str):
                source, filters, delta = entry, None, False
            elif isinstance(entry, dict) and isinstance(entry.get("source"), str):
                source = entry["source"]
                filters = entry.get("extensions")
                delta = entry.get("autoload", True) is False
                if "autoload" in entry and not isinstance(entry["autoload"], bool):
                    raise ValidationFailure([Diagnostic(str(path), "autoload must be boolean", code="pi-settings")])
                for field in ("extensions", "skills", "prompts", "themes"):
                    if field in entry and (not isinstance(entry[field], list) or any(not isinstance(x, str) for x in entry[field])):
                        raise ValidationFailure([Diagnostic(str(path), f"package {field} must contain strings", code="pi-settings")])
            else:
                raise ValidationFailure([Diagnostic(str(path), "packages must contain strings or objects with a source", code="pi-settings")])
            match = _NPM.fullmatch(source)
            if match is None or match["name"] not in _STANDARD:
                diagnostics.append(Diagnostic(str(path), f"Unconfirmed custom package: {source}; use a standard npm package for static preflight", severity="warning", code="pi-custom-package"))
                continue
            name = match["name"]
            allowed = filters is None
            if filters:
                diagnostics.append(Diagnostic(str(path), f"Cannot confirm extension selectors for {name}; omit extensions or use a supported unfiltered declaration", severity="warning", code="pi-selector"))
            # Project autoload:false entries narrow an existing user package;
            # they never introduce a package or re-enable disabled extensions.
            selected[name] = selected.get(name, False) and allowed if delta else allowed
    if excluded:
        selected = {}
    subagent = next((name for name in ("pi-subagents", "pi-agents-flow") if selected.get(name)), None)
    diagnostics.append(Diagnostic("pi", "Static package declarations do not prove installation or runtime availability; project trust, plugin versions, and runtime tool registration still require verification", severity="warning", code="pi-static-only"))
    isolation = (
        "The declared standard subagent plugin supports worktree:true according to the reviewed plugin contract; verify the installed version, loading, and child behavior before parallel writers rely on it"
        if subagent else
        "Child-agent worktree isolation is unconfirmed; use file-disjoint ownership"
    )
    diagnostics.append(Diagnostic("pi", isolation + ". A standalone pi-worktree session and codemode do not provide a child-agent OS sandbox", severity="warning", code="pi-isolation"))
    if not selected.get("pi-web-access"):
        diagnostics.append(Diagnostic("pi", "Web tools omitted; declare npm:pi-web-access to enable the standard web mapping. MCP presence alone proves no web tools", severity="warning", code="pi-web-unavailable"))
    return PiPluginStatus(subagent, bool(selected.get("pi-web-access")), tuple(diagnostics))


def require_pi_plugins(status: PiPluginStatus, scope: str) -> None:
    """Gate preview and apply before any native target writes."""
    if scope == "user" and agent_directory() != (Path.home() / ".pi/agent").resolve():
        raise ValidationFailure([Diagnostic("PI_CODING_AGENT_DIR", "Custom Pi agent directories are supported for scanning, but user installation uses ~/.pi/agent/agents; unset the override or render and copy agents manually", code="pi-agent-directory")])
    if not status.has_subagent:
        raise ValidationFailure([*status.diagnostics, Diagnostic("pi", "Target pi requires a confirmed standard subagent declaration. Install manually: pi install npm:pi-subagents (recommended) or pi install npm:pi-agents-flow; then verify plugin loading in Pi", code="pi-missing-subagents")])
