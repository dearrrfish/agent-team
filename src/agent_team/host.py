from __future__ import annotations

import os
from collections.abc import Mapping


def detect_host(environment: Mapping[str, str] | None = None) -> tuple[str, str]:
    env = os.environ if environment is None else environment
    if env.get("DSH_SHELL") == "1" and env.get("DSH_SESSION_ID", "").strip():
        return "dsh", "dsh-shell-session"
    if any(env.get(key) for key in (
        "DSH_SHELL", "DSH_SESSION_ID", "DSH_PROFILE", "DSH_PROFILE_DIR", "DSH_INSTALL_DIR",
    )):
        return "unknown", "incomplete-dsh-environment"
    return "unknown", "none"
