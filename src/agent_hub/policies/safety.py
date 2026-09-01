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

# The release_hosting graph is the single, explicit exception to
# ``forbid_release``.  It may publish installer packages to GitHub Releases,
# but only through the narrow lane validated below: the GitHub CLI ``gh``,
# release subcommands in the allowlist, and a ``--repo`` value pinned to the
# repository frozen by the project release configuration.  Push, merge,
# release delete/edit, and every non-release command stay forbidden.
RELEASE_LANE_ALLOWED_ACTIONS = frozenset({"create", "upload", "view", "list"})

_REPO_FLAGS = frozenset({"--repo", "-R"})


def _reject(reason: str, command: list[str]) -> dict[str, object]:
    return {"status": "REJECT", "reason": reason, "command": command}


def validate_release_command(argv: list[str], frozen_repo: str) -> dict[str, object]:
    """Validate one release-lane command before the graph may execute it.

    Returns a verdict dict.  Only ``PASS`` commands may run; everything else is
    denied by default.  The lane covers exactly:
      * ``gh auth status``                         (preflight)
      * ``gh repo view <frozen_repo>``             (preflight)
      * ``gh release create|upload|view|list ...`` (publish / verify / resume)
    """

    command = [str(part) for part in argv]
    frozen = str(frozen_repo or "").strip()
    if len(command) < 2 or command[0] != "gh":
        return _reject("release_lane_requires_gh_cli", command)
    if not frozen:
        return _reject("release_repo_not_frozen", command)
    rest = command[1:]
    if rest[:2] == ["auth", "status"] and len(rest) == 2:
        return {"status": "PASS", "lane": "auth_preflight", "command": command}
    if rest[:2] == ["repo", "view"] and len(rest) == 3:
        if rest[2] != frozen:
            return _reject("release_repo_mismatch", command)
        return {"status": "PASS", "lane": "repo_preflight", "command": command}
    if rest[0] != "release":
        return _reject("release_lane_forbids_non_release_commands", command)
    if len(rest) < 2 or rest[1] not in RELEASE_LANE_ALLOWED_ACTIONS:
        return _reject("release_action_forbidden", command)
    for index, part in enumerate(command):
        if part in _REPO_FLAGS:
            value = command[index + 1] if index + 1 < len(command) else ""
            if value != frozen:
                return _reject("release_repo_mismatch", command)
    return {"status": "PASS", "lane": f"release_{rest[1]}", "command": command}
