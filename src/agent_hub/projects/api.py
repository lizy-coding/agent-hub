"""Stable functions for Graph and future Context Resolver consumers."""
from pathlib import Path
from agent_hub.projects.workspace_registry import WorkspaceRegistry
from agent_hub.workspace.config import WorkspaceConfig
def _registry(config: WorkspaceConfig) -> WorkspaceRegistry: return WorkspaceRegistry(config)
def get_workspace(config): return _registry(config).get_workspace()
def list_repositories(config): return _registry(config).list_repositories()
def get_repository(config, repo_id): return _registry(config).get_repository(repo_id)
def list_development_units(config): return _registry(config).list_development_units()
def get_development_unit(config, unit_id): return _registry(config).get_development_unit(unit_id)
def find_unit_by_path(config, path): return _registry(config).find_unit_by_path(Path(path))
def get_dependencies(config, identifier): return _registry(config).get_dependencies(identifier)
def get_dependents(config, identifier): return _registry(config).get_dependents(identifier)
def get_rule_files(config, value): return _registry(config).get_rule_files(value)
def get_validation_commands(config, identifier): return _registry(config).get_validation_commands(identifier)
def refresh(config): return _registry(config).refresh()
def validate_registry(config): return _registry(config).validate_registry()
