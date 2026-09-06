"""Project-specific decomposition policies.

The graph owns lifecycle, safety, and integration.  An adapter owns the
project facts and architecture decisions needed to build a decomposition
program.  Keeping this boundary explicit lets a new project join the control
plane without adding another branch to the graph itself.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class ProjectAdapter(Protocol):
    name: str

    def build_program(self, root: Path, context: dict[str, object]) -> dict[str, object]: ...

    def architecture_guard(
        self,
        task: dict[str, object],
        worker: dict[str, object],
        program: dict[str, object],
    ) -> dict[str, object]: ...

    def proposal_inventory(
        self,
        program: dict[str, object],
        spec: dict[str, object],
    ) -> dict[str, object]: ...

    def contract_preflight(
        self,
        task: dict[str, object],
        program: dict[str, object],
    ) -> dict[str, object]: ...

    def default_allowed_paths(self, task_id: str, repository: str) -> list[str]: ...

    def release_inventory(self, context: dict[str, object], spec: dict[str, object]) -> dict[str, object]: ...


class GenericProjectAdapter:
    """Safe plan-only baseline for projects without custom architecture rules."""

    name = "generic"

    def build_program(self, root: Path, context: dict[str, object]) -> dict[str, object]:
        primary = str(context.get("primary_repository_id") or "primary")
        paths = context.get("repository_paths")
        repository_paths = paths if isinstance(paths, dict) else {primary: str(root / primary)}
        repositories = []
        candidates = []
        for repository_id, raw_path in repository_paths.items():
            repository_root = Path(str(raw_path))
            manifest = repository_root / "pubspec.yaml"
            if manifest.is_file():
                repositories.append({
                    "repository_id": str(repository_id),
                    "path": str(repository_root),
                    "role": "APP" if str(repository_id) == primary else "REFERENCE",
                    "pubspec": str(manifest),
                    "consumers": [],
                })
            for prefix in ("packages", "plugins", "apps"):
                parent = repository_root / prefix
                if not parent.is_dir():
                    continue
                for child in sorted(parent.iterdir()):
                    if (child / "pubspec.yaml").is_file():
                        candidates.append({
                            "package_id": f"{prefix}/{child.name}",
                            "package_type": "APP_ONLY" if prefix == "apps" else "FLUTTER_PACKAGE",
                            "target_path": f"{prefix}/{child.name}",
                            "owned_capabilities": [],
                            "dependencies": [],
                            "public_api_intent": "adapter-defined",
                            "migration_priority": 1,
                        })
        return {
            "project_id": str(context.get("project_id") or "generic-project"),
            "program_id": str(context.get("program_id") or "generic-decomposition-program"),
            "adapter": self.name,
            "primary_repository_id": primary,
            "cluster_root": str(root),
            "repositories": repositories,
            "capabilities": [],
            "package_candidates": candidates,
            "target_dependency_graph": {"nodes": [item["package_id"] for item in candidates], "edges": [], "cycles": []},
            "migration_tasks": [],
            "human_decisions": [],
            "integration_head": None,
            "execution_mode": "PLAN_ONLY",
            "status": "PLANNING_COMPLETE",
        }

    def architecture_guard(self, task, worker, program):
        repositories = worker.get("repositories")
        targets = task.get("target_units", [])
        if not isinstance(repositories, dict):
            return {"status": "REJECT", "reason": "missing_repository_results"}
        if not targets:
            return {"status": "REJECT", "reason": "merge_task_has_no_target_units"}
        changed = [path for result in repositories.values() if isinstance(result, dict) for path in result.get("changed_files", [])]
        if not changed:
            return {"status": "REJECT", "reason": "MIGRATION_NO_EFFECT"}
        return {
            "status": "PASS",
            "guard_kind": "generic_target_ownership",
            "capability_owner_after": [str(value) for value in targets],
            "changed_files": sorted(set(str(path) for path in changed)),
        }

    def proposal_inventory(self, program, spec):
        primary = str(program.get("primary_repository_id") or "primary")
        target_units = [str(value) for value in spec.get("target_units", [])]
        source_units = [str(value) for value in spec.get("source_units", [])]
        allowed = spec.get("candidate_paths") or target_units or source_units
        if not isinstance(allowed, list) or not allowed:
            return {
                "task_id": str(spec.get("task_id", "")),
                "title": str(spec.get("title", "")),
                "status": "BLOCKED_DECISION",
                "blocked_decisions": ["generic adapter requires explicit candidate_paths or units"],
                "allowed_paths_by_repository": {},
            }
        frozen = sorted(set(str(value) for value in allowed))
        return {
            "task_id": str(spec.get("task_id", "")),
            "title": str(spec.get("title", "")),
            "source_units": source_units,
            "target_units": target_units,
            "depends_on": list(spec.get("depends_on", [])),
            "allowed_operations": list(spec.get("allowed_operations", ["CREATE", "MOVE", "RENAME", "DEPENDENCY_REWRITE"])),
            "candidate_paths": frozen,
            "allowed_paths_by_repository": {primary: frozen},
            "acceptance": list(spec.get("acceptance", [])),
            "execution_instructions": list(spec.get("execution_instructions", [])),
            "evidence": ["generic adapter: paths supplied by the frozen proposal"],
            "proposal": {"status": "FROZEN", "read_only": True},
            "status": "READY",
        }

    def contract_preflight(self, task, program):
        return {"status": "PASS", "guard_kind": "generic_contract_preflight"}

    def default_allowed_paths(self, task_id, repository):
        return []

    def release_inventory(self, context, spec):
        """Safe baseline: freeze only what the spec states explicitly."""
        from agent_hub.projects.release_program import (
            artifact_entries,
            blocked_release_program,
            build_release_program,
            normalize_artifact_paths,
            valid_release_tag,
        )
        context = {**(context or {}), "adapter": self.name, "program_id": f"{(context or {}).get('project_id') or 'generic-project'}-release-program"}
        if not str((context.get("release") or {}).get("github_repo") or "").strip():
            return blocked_release_program(context, "RELEASE_NOT_CONFIGURED", "release.github_repo is not configured in workspace/projects.json; freeze the target repository slug before planning a release.")
        spec = spec if isinstance(spec, dict) else {}
        tag = str(spec.get("tag") or "")
        if not tag or not valid_release_tag(tag):
            return blocked_release_program(context, "RELEASE_SPEC_REQUIRED", "generic adapter requires an explicit semver release tag in the spec.")
        raw_artifacts = spec.get("artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            return blocked_release_program(context, "RELEASE_SPEC_REQUIRED", "generic adapter requires an explicit artifacts list; it never discovers files.")
        paths, error = normalize_artifact_paths(raw_artifacts)
        if error:
            return blocked_release_program(context, "RELEASE_ARTIFACTS_INVALID", error)
        version = str(spec.get("version") or tag.lstrip("v"))
        return build_release_program(
            context,
            version=version,
            tag=tag,
            name=str(spec.get("name") or tag),
            notes=str(spec.get("notes") or ""),
            draft=bool(spec.get("draft", (context.get("release") or {}).get("default_draft", False))),
            prerelease=bool(spec.get("prerelease", (context.get("release") or {}).get("default_prerelease", False))),
            artifacts=artifact_entries(paths),
            evidence=["generic adapter: tag and artifacts supplied explicitly by the release spec"],
        )


class FlutterForgeAdapter:
    """Compatibility adapter for the existing Flutter Forge decomposition plan."""

    name = "flutter_forge"

    def build_program(self, root, context):
        from agent_hub.projects.flutter_forge_adapter import build_program
        return build_program(root, context)

    def architecture_guard(self, task, worker, program):
        from agent_hub.projects.flutter_forge_adapter import architecture_guard
        return architecture_guard(task, worker, program)

    def proposal_inventory(self, program, spec):
        from agent_hub.projects.flutter_forge_adapter import proposal_inventory
        return proposal_inventory(program, spec)

    def contract_preflight(self, task, program):
        from agent_hub.projects.flutter_forge_adapter import file_picker_contract_preflight
        return file_picker_contract_preflight(program)

    def default_allowed_paths(self, task_id, repository):
        from agent_hub.projects.flutter_forge_adapter import default_allowed_paths
        return default_allowed_paths(task_id, repository)

    def release_inventory(self, context, spec):
        from agent_hub.projects.flutter_forge_adapter import release_inventory
        return release_inventory(context, spec)


class GcodeCoreAdapter(GenericProjectAdapter):
    name = "gcode_core"

    def build_program(self, root, context):
        from agent_hub.projects.gcode_core_adapter import enrich_program
        program = super().build_program(root, context)
        primary = str(context.get("primary_repository_id") or "gcode_core")
        path = Path((context.get("repository_paths") or {}).get(primary, root / primary))
        return enrich_program(program, path, primary)


_ADAPTERS: dict[str, ProjectAdapter] = {
    "gcode_core": GcodeCoreAdapter(),
    "flutter_forge": FlutterForgeAdapter(),
    "flutter-forge": FlutterForgeAdapter(),
    "generic": GenericProjectAdapter(),
    "generic_test": GenericProjectAdapter(),
}


def register_adapter(name: str, adapter: ProjectAdapter) -> None:
    if not name or not name.strip():
        raise ValueError("adapter name must not be empty")
    _ADAPTERS[name] = adapter


def get_adapter(name: str | None) -> ProjectAdapter:
    selected = str(name or "generic")
    try:
        return _ADAPTERS[selected]
    except KeyError as error:
        available = ", ".join(sorted(_ADAPTERS))
        raise ValueError(f"unknown project adapter: {selected}; available: {available}") from error


def list_adapters() -> list[str]:
    return sorted(_ADAPTERS)
