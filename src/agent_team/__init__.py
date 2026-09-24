"""Portable native agent-team workflow generator."""

from agent_team.version import __base_version__, get_commit_hash, get_version

__version__ = get_version()

__all__ = ["__base_version__", "__version__", "get_commit_hash", "get_version"]
