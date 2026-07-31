from __future__ import annotations


class BriefSpecError(Exception):
    """Base error for expected BriefSpec failures."""


class ContractError(BriefSpecError):
    """A brief does not satisfy its presentation contract."""


class InstallConflict(BriefSpecError):
    """Installation would overwrite data not owned by BriefSpec."""


class HostUnavailable(BriefSpecError):
    """A requested host executable or integration surface is unavailable."""
