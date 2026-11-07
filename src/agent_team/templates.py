from __future__ import annotations

import re
from collections.abc import Mapping
from importlib import resources

_VARIABLE_NAME = re.compile(r"[a-z][a-z0-9_]*")
_PLACEHOLDER = re.compile(r"\$\{(.*?)\}", re.DOTALL)
_REQUIRED = re.compile(r"<!--\s*REQUIRED:\s*.+?-->", re.DOTALL)


class TemplateError(ValueError):
    pass


def asset_text(*parts: str) -> str:
    return resources.files("agent_team.assets").joinpath(*parts).read_text(encoding="utf-8")


def load_prompt_templates() -> dict[str, str]:
    prompts_dir = resources.files("agent_team.assets").joinpath("templates", "prompts")
    templates: dict[str, str] = {}
    for entry in sorted(prompts_dir.iterdir(), key=lambda item: item.name):
        if entry.is_file() and entry.name.endswith(".md"):
            templates[entry.name] = entry.read_text(encoding="utf-8")
    return templates


def render_template(template: str, variables: Mapping[str, str]) -> str:
    matches = tuple(_PLACEHOLDER.finditer(template))
    invalid = sorted({match.group(1) for match in matches if not _VARIABLE_NAME.fullmatch(match.group(1))})
    unmatched_start = "${" in _PLACEHOLDER.sub("", template)
    if invalid or unmatched_start:
        details = ", ".join(repr(name) for name in invalid) if invalid else "unclosed placeholder"
        raise TemplateError(f"invalid template variable syntax: {details}")
    referenced = {match.group(1) for match in matches}
    missing = sorted(referenced - set(variables))
    if missing:
        raise TemplateError(f"missing template variables: {', '.join(missing)}")
    unknown = sorted(set(variables) - referenced)
    if unknown:
        raise TemplateError(f"unknown template variables: {', '.join(unknown)}")
    return _PLACEHOLDER.sub(lambda match: variables[match.group(1)], template)


def required_markers(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _REQUIRED.finditer(text))


def generate_annotated_profile(target: str) -> str:
    raw = asset_text("definitions", "targets", f"{target}.toml")
    header = f"""# ==============================================================================
# Agent Team Target Profile Template: {target}
# ==============================================================================
#
# This file defines the full configuration for the '{target}' target adapter,
# including destination directories, feature flags, and model presets.
#
# HOW TO USE:
# 1. Copy this template to your project or user configuration directory:
#      cp .agent-team/templates/profiles/{target}.toml.example targets/{target}.toml
# 2. Modify the presets or options below to fit your workflow.
# 3. Reference this custom profile in your team.toml:
#      [target_profiles]
#      {target} = "targets/{target}.toml"
#
# ------------------------------------------------------------------------------

"""
    return header + raw


def generate_annotated_role(role_id: str) -> str:
    raw = asset_text("definitions", "roles", role_id, "role.toml")
    header = f"""# ==============================================================================
# Agent Team Role Definition Template: {role_id}
# ==============================================================================
#
# This file defines the behavior, capabilities, model class, and effort for the
# '{role_id}' role.
#
# HOW TO USE:
# 1. Copy this folder (role.toml.example and instructions.md.example) to your custom
#    role sources directory:
#      mkdir -p custom_roles/{role_id}
#      cp .agent-team/templates/roles/{role_id}/role.toml.example custom_roles/{role_id}/role.toml
#      cp .agent-team/templates/roles/{role_id}/instructions.md.example custom_roles/{role_id}/instructions.md
# 2. Add your custom role source directory to team.toml:
#      role_sources = ["custom_roles", "builtin:roles"]
#
# ------------------------------------------------------------------------------
# Available model_class options: "fast", "balanced", "deep"
# Available effort options: "low", "medium", "high"
#
# Target-specific routing overrides can also be added here, for example:
# [targets.codex]
# model_class = "deep"
# effort = "high"
#
# ------------------------------------------------------------------------------

"""
    return header + raw


def load_example_templates() -> dict[str, str]:
    from agent_team.models import ROLE_IDS, TARGETS

    examples: dict[str, str] = {}
    for target in TARGETS:
        content = generate_annotated_profile(target)
        examples[f"profiles/{target}.toml.example"] = content
        examples[f"profile/{target}.toml.example"] = content

    for role_id in ROLE_IDS:
        toml_content = generate_annotated_role(role_id)
        md_content = asset_text("definitions", "roles", role_id, "instructions.md")
        examples[f"roles/{role_id}/role.toml.example"] = toml_content
        examples[f"roles/{role_id}/instructions.md.example"] = md_content
        examples[f"role/{role_id}/role.toml.example"] = toml_content
        examples[f"role/{role_id}/instructions.md.example"] = md_content

    return examples
