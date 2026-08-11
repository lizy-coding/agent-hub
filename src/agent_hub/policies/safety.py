"""Deny-by-default policy used by all bootstrap checks."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyPolicy:
    """Static guardrails; this host intentionally exposes no shell executor."""

    business_repositories_read_only: bool = True
    allow_unrestricted_shell: bool = False
    forbid_git_push: bool = True
    forbid_git_merge: bool = True
    forbid_release: bool = True
    forbid_repository_deletion: bool = True


DEFAULT_SAFETY_POLICY = SafetyPolicy()
