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
