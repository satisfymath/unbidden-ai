"""Unbidden: a proactive engineering agent on Meta models."""

from __future__ import annotations


def _version() -> str:
    """The installed distribution's version; for a source checkout without metadata, what pyproject.toml says."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("unbidden-ai")
    except PackageNotFoundError:
        pass
    import tomllib
    from pathlib import Path

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    try:
        return str(tomllib.loads(pyproject.read_text())["project"]["version"])
    except (OSError, KeyError, ValueError):
        return "0.0.0+unknown"


__version__ = _version()
