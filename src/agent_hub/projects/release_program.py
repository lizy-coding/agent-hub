"""Pure release-program construction and artifact path validation."""
from __future__ import annotations

import re
from pathlib import Path


def valid_release_tag(tag: str) -> bool:
    return bool(re.fullmatch(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", tag))


def is_publishable_artifact(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in {".apk", ".aab", ".dmg", ".exe", ".msix", ".zip", ".ipa", ".gz"}


def is_flutter_forge_android_arm64(path: Path) -> bool:
    """Accept only the arm64 APK; an AAB is architecture-neutral."""
    name = path.name.lower()
    return path.suffix.lower() == ".aab" or (path.suffix.lower() == ".apk" and "arm64-v8a" in name)


def normalize_artifact_paths(raw: list[object]) -> tuple[list[str], str | None]:
    paths: list[str] = []
    for item in raw:
        value = str(item.get("path") if isinstance(item, dict) else item)
        path = Path(value)
        if not value or path.is_absolute() or ".." in path.parts:
            return [], f"artifact path is not repository-relative: {value}"
        paths.append(path.as_posix())
    if len(set(paths)) != len(paths):
        return [], "artifact paths must be unique"
    return paths, None


def artifact_entries(paths: list[str], checksums: dict[str, str] | None = None) -> list[dict[str, object]]:
    checksums = checksums or {}
    return [{"path": path, "asset_name": Path(path).name, "sha256": checksums.get(Path(path).name, ""), "status": "PENDING"} for path in paths]


def release_context(context: dict[str, object]) -> dict[str, object]:
    return dict(context.get("release") or {})


def blocked_release_program(context: dict[str, object], status: str, reason: str) -> dict[str, object]:
    return {"project_id": context.get("project_id"), "program_id": context.get("program_id"), "adapter": context.get("adapter"), "status": "PROGRAM_BLOCKED", "execution_blocker": {"status": status, "reason": reason}, "release": {}}


def build_release_program(context: dict[str, object], *, version: str, tag: str, name: str, notes: str, draft: bool, prerelease: bool, artifacts: list[dict[str, object]], evidence: list[str]) -> dict[str, object]:
    release_config = context.get("release") or {}
    return {"project_id": context.get("project_id"), "program_id": context.get("program_id"), "adapter": context.get("adapter"), "primary_repository_id": context.get("primary_repository_id", "flutter_forge"), "cluster_root": context.get("cluster_root"), "github_repo": release_config.get("github_repo") if isinstance(release_config, dict) else None, "status": "READY", "execution_mode": "PLAN_ONLY", "evidence": evidence, "build_matrix": dict(release_config.get("build_matrix") or {}) if isinstance(release_config, dict) else {}, "release": {"version": version, "tag": tag, "name": name, "notes": notes, "draft": draft, "prerelease": prerelease, "artifacts": artifacts}}
