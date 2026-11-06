"""Static Pi declarations, never plugin execution or proof of runtime availability."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from agent_team.diagnostics import Diagnostic, ValidationFailure

_NIX_STORE = Path("/nix/store")
_STANDARD = {"pi-subagents", "pi-agents-flow", "pi-web-access", "@tylerho/pi-worktree"}
_NPM = re.compile(r"npm:(?P<name>@[a-z0-9_.-]+/[a-z0-9_.-]+|[a-z0-9_.-]+)(?:@(?P<version>[^\s/]+))?$")
_TOOL_NAME = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
DEFAULT_PI_WEB_TOOLS: tuple[str, ...] = (
    "web_search",
    "fetch_content",
    "get_search_content",
    "source_check",
)
_WEB_TOOL_KEYS: tuple[tuple[str, str], ...] = (
    ("webSearch", "web_search"),
    ("fetchContent", "fetch_content"),
    ("getSearchContent", "get_search_content"),
    ("sourceCheck", "source_check"),
)


@dataclass(frozen=True)
class PiPluginStatus:
    subagent_package: str | None = None
    has_web: bool = False
    diagnostics: tuple[Diagnostic, ...] = ()
    web_tools: tuple[str, ...] = ()
    web_extension_source: str | None = None

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


def _verify_static_extension_manifest(path: Path, expected_names: set[str]) -> str | None:
    """Validate a package directory's static Pi manifest without executing code."""
    try:
        manifest = json.loads((path / "package.json").read_text(encoding="utf-8"))
        name = manifest.get("name")
        extensions = manifest.get("pi", {}).get("extensions")
        if name not in expected_names or not isinstance(extensions, list) or not extensions:
            return None
        resolved_root = path.resolve()
        for entry in extensions:
            if not isinstance(entry, str) or not entry or entry.startswith(("!", "/")):
                return None
            target = (path / entry).resolve()
            if not target.is_relative_to(resolved_root):
                return None
            if target.is_file():
                continue
            if target.is_dir() and ((target / "index.js").is_file() or (target / "index.ts").is_file()):
                continue
            return None
    except (OSError, UnicodeError, ValueError, AttributeError, TypeError, RuntimeError):
        return None
    return name


def _nix_package(source: str) -> tuple[str, str] | None:
    """Identify a direct Nix store package from its static Pi manifest."""
    path = Path(source)
    if not path.is_absolute() or path.parent != _NIX_STORE:
        return None
    name = _verify_static_extension_manifest(path, _STANDARD)
    if name is None:
        return None
    return str(path), name


def _resolve_web_package_dir(
    root: Path,
    scope: str,
    selected_sources: dict[str, str],
    diagnostics: list[Diagnostic],
) -> str | None:
    """Resolve an installed local package directory for pi-web-access if present."""
    source = selected_sources.get("pi-web-access")
    if not source:
        return None
    source_path = Path(source)
    if source_path.is_absolute() and source_path.parent == _NIX_STORE:
        candidates = [source_path]
    else:
        candidates = []
        if scope == "project":
            candidates.append(root / ".pi/npm/node_modules/pi-web-access")
        candidates.append(agent_directory() / "npm/node_modules/pi-web-access")
    for candidate in candidates:
        if not candidate.is_dir():
            continue
        if _verify_static_extension_manifest(candidate, {"pi-web-access"}) != "pi-web-access":
            diagnostics.append(Diagnostic(
                str(candidate),
                "Installed pi-web-access package manifest is missing static pi.extensions; foreground child subagentOnlyExtensions cannot be bound",
                severity="warning",
                code="pi-web-provider-unresolved",
            ))
            return None
        return str(candidate.resolve())
    diagnostics.append(Diagnostic(
        "pi-web-access",
        "Installed pi-web-access package directory was not found locally; background children rely on ambient settings, while foreground children require a local package directory for subagentOnlyExtensions",
        severity="warning",
        code="pi-web-provider-unresolved",
    ))
    return None


def _resolve_web_tools(diagnostics: list[Diagnostic]) -> tuple[str, ...]:
    """Statically inspect <agent-dir>/web-search.json to determine enabled web tools."""
    config_path = agent_directory() / "web-search.json"
    if not config_path.exists():
        return DEFAULT_PI_WEB_TOOLS
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        diagnostics.append(Diagnostic(
            str(config_path),
            f"Cannot parse web-search.json ({exc}); omitting pi-web-access tools to avoid unverified child allowlist failures",
            severity="warning",
            code="pi-web-config-invalid",
        ))
        return ()
    if not isinstance(config, dict):
        diagnostics.append(Diagnostic(
            str(config_path),
            "web-search.json must be a JSON object; omitting pi-web-access tools",
            severity="warning",
            code="pi-web-config-invalid",
        ))
        return ()
    activation = config.get("toolActivation", "eager")
    if activation == "none":
        diagnostics.append(Diagnostic(
            str(config_path),
            'web-search.json sets toolActivation="none"; pi-web-access registers no tools, so web tools are omitted',
            severity="warning",
            code="pi-web-disabled",
        ))
        return ()
    exposure = config.get("toolExposure", "direct")
    if exposure != "direct":
        diagnostics.append(Diagnostic(
            str(config_path),
            f'web-search.json sets toolExposure={exposure!r}; direct pi-web-access tools are not registered, so web tools are omitted',
            severity="warning",
            code="pi-web-unsupported",
        ))
        return ()
    web_search_cfg = config.get("webSearch")
    global_search_enabled = True
    if isinstance(web_search_cfg, dict) and isinstance(web_search_cfg.get("enabled"), bool):
        global_search_enabled = web_search_cfg["enabled"]
    tools_cfg = config.get("tools") if isinstance(config.get("tools"), dict) else {}
    names_cfg = config.get("toolNames") if isinstance(config.get("toolNames"), dict) else {}
    resolved: list[str] = []
    for key, default_name in _WEB_TOOL_KEYS:
        per_tool = tools_cfg.get(key)
        explicit = per_tool.get("enabled") if isinstance(per_tool, dict) else None
        if isinstance(explicit, bool):
            enabled = explicit
        elif key in {"webSearch", "sourceCheck"}:
            enabled = global_search_enabled
        else:
            enabled = True
        if not enabled:
            continue
        custom_name = names_cfg.get(key)
        if custom_name is not None:
            if not isinstance(custom_name, str) or not _TOOL_NAME.fullmatch(custom_name):
                diagnostics.append(Diagnostic(
                    str(config_path),
                    f"web-search.json toolNames.{key} is invalid ({custom_name!r}); omitting pi-web-access tools",
                    severity="warning",
                    code="pi-web-tool-name-invalid",
                ))
                return ()
            resolved.append(custom_name)
        else:
            resolved.append(default_name)
    if not resolved:
        diagnostics.append(Diagnostic(
            str(config_path),
            "All pi-web-access tools are disabled in web-search.json; web tools are omitted",
            severity="warning",
            code="pi-web-disabled",
        ))
    return tuple(dict.fromkeys(resolved))


def scan_pi_plugins(root: Path, scope: str = "project") -> PiPluginStatus:
    """Inspect user and optionally project settings; unknown selectors fail closed.

    Exact standard npm identities and statically verified Nix store manifests
    count with unfiltered extension declarations. Package code is never executed.
    """
    if scope not in {"project", "user"}:
        raise ValueError("scope must be project or user")
    paths = [agent_directory() / "settings.json"]
    if scope == "project":
        paths.append(root / ".pi/settings.json")
    selected: dict[str, tuple[str, bool]] = {}
    selected_sources: dict[str, str] = {}
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
            package = (f'npm:{match["name"]}', match["name"]) if match and match["name"] in _STANDARD else _nix_package(source)
            if package is None:
                diagnostics.append(Diagnostic(str(path), f"Unconfirmed custom package: {source}; use a standard npm package for static preflight", severity="warning", code="pi-custom-package"))
                continue
            identity, name = package
            allowed = filters is None
            if filters:
                diagnostics.append(Diagnostic(str(path), f"Cannot confirm extension selectors for {name}; omit extensions or use a supported unfiltered declaration", severity="warning", code="pi-selector"))
            # Project autoload:false entries narrow an existing user package;
            # they never introduce a package or re-enable disabled extensions.
            previous = selected.get(identity, (name, False))[1]
            now_allowed = previous and allowed if delta else allowed
            selected[identity] = (name, now_allowed)
            if now_allowed:
                selected_sources[name] = source
            elif not any(pkg_name == name and pkg_allowed for pkg_name, pkg_allowed in selected.values()):
                selected_sources.pop(name, None)
    if excluded:
        selected = {}
        selected_sources = {}
    enabled = {name for name, allowed in selected.values() if allowed}
    subagent = next((name for name in ("pi-subagents", "pi-agents-flow") if name in enabled), None)
    diagnostics.append(Diagnostic("pi", "Static package declarations do not prove installation or runtime availability; project trust, plugin versions, and runtime tool registration still require verification", severity="warning", code="pi-static-only"))
    isolation = (
        "The declared standard subagent plugin supports worktree:true according to the reviewed plugin contract; verify the installed version, loading, and child behavior before parallel writers rely on it"
        if subagent else
        "Child-agent worktree isolation is unconfirmed; use file-disjoint ownership"
    )
    diagnostics.append(Diagnostic("pi", isolation + ". A standalone pi-worktree session and codemode do not provide a child-agent OS sandbox", severity="warning", code="pi-isolation"))
    web_tools: tuple[str, ...] = ()
    web_extension_source: str | None = None
    if "pi-web-access" not in enabled:
        diagnostics.append(Diagnostic("pi", "Web tools omitted; declare npm:pi-web-access to enable the standard web mapping. MCP presence alone proves no web tools", severity="warning", code="pi-web-unavailable"))
    else:
        web_tools = _resolve_web_tools(diagnostics)
        if web_tools:
            web_extension_source = _resolve_web_package_dir(root, scope, selected_sources, diagnostics)
    return PiPluginStatus(
        subagent,
        bool(web_tools),
        tuple(diagnostics),
        web_tools=web_tools,
        web_extension_source=web_extension_source,
    )


def require_pi_plugins(status: PiPluginStatus, scope: str) -> None:
    """Gate preview and apply before any native target writes."""
    if scope == "user" and agent_directory() != (Path.home() / ".pi/agent").resolve():
        raise ValidationFailure([Diagnostic("PI_CODING_AGENT_DIR", "Custom Pi agent directories are supported for scanning, but user installation uses ~/.pi/agent/agents; unset the override or render and copy agents manually", code="pi-agent-directory")])
    if not status.has_subagent:
        raise ValidationFailure([*status.diagnostics, Diagnostic("pi", "Target pi requires a confirmed standard subagent declaration. Install manually: pi install npm:pi-subagents (recommended) or pi install npm:pi-agents-flow; then verify plugin loading in Pi", code="pi-missing-subagents")])
