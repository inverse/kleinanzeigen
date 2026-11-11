"""Installed package version via importlib.metadata (git tags via hatch-vcs)."""

from importlib.metadata import PackageNotFoundError, version


def package_version() -> str:
    try:
        return version("kleinanzeigen")
    except PackageNotFoundError:
        return "unknown"
