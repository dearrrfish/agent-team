from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Diagnostic:
    path: str
    message: str
    severity: str = "error"
    code: str = "invalid"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


class ValidationFailure(Exception):
    def __init__(self, diagnostics: Iterable[Diagnostic]):
        self.diagnostics = tuple(diagnostics)
        super().__init__("; ".join(f"{item.path}: {item.message}" for item in self.diagnostics))


def render_diagnostics(diagnostics: Iterable[Diagnostic], output_format: str) -> str:
    items = tuple(diagnostics)
    if output_format == "json":
        return json.dumps(
            {
                "ok": not any(item.severity == "error" for item in items),
                "diagnostics": [item.as_dict() for item in items],
            },
            indent=2,
            sort_keys=True,
        )
    if not items:
        return "OK"
    return "\n".join(
        f"{item.severity.upper()} [{item.code}] {item.path}: {item.message}"
        for item in items
    )
