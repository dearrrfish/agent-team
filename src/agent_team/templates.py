from __future__ import annotations

import re
from collections.abc import Mapping
from importlib import resources

_VARIABLE = re.compile(r"\$\{([a-z][a-z0-9_]*)\}")
_REQUIRED = re.compile(r"<!--\s*REQUIRED:\s*.+?-->", re.DOTALL)


class TemplateError(ValueError):
    pass


def asset_text(*parts: str) -> str:
    return resources.files("agent_team.assets").joinpath(*parts).read_text(encoding="utf-8")


def render_template(template: str, variables: Mapping[str, str]) -> str:
    referenced = set(_VARIABLE.findall(template))
    missing = sorted(referenced - set(variables))
    if missing:
        raise TemplateError(f"missing template variables: {', '.join(missing)}")
    unknown = sorted(set(variables) - referenced)
    if unknown:
        raise TemplateError(f"unknown template variables: {', '.join(unknown)}")
    return _VARIABLE.sub(lambda match: variables[match.group(1)], template)


def required_markers(text: str) -> tuple[str, ...]:
    return tuple(match.group(0) for match in _REQUIRED.finditer(text))
