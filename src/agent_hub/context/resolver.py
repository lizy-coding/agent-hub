"""Evidence-driven, bounded Context Resolver built on the Registry public API."""

import re
import os
from dataclasses import dataclass
from pathlib import Path

from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import ContextCandidate, ContextFile, ContextPackage, ContextRule, ContextSymbol, ContextUnknown, DevelopmentUnit
from agent_hub.tools.path_guard import is_allowed_business_path, is_within
from agent_hub.workspace.config import WorkspaceConfig

EXCLUDED = {".git", "build", ".dart_tool", "node_modules", "generated", ".venv", ".langgraph_api"}
SOURCE_SUFFIXES = {".dart", ".py", ".c", ".cc", ".cpp", ".h", ".hpp"}


@dataclass(frozen=True)
class ContextLimits:
    max_candidate_repositories: int = 6
    max_files: int = 40
    max_symbols: int = 80
    max_dependency_depth: int = 2


STOP_TERMS = {"workspace", "current", "analysis", "capability", "package", "plugin", "existing", "related", "between", "with", "native", "flutter", "application", "and", "app", "the", "for", "from", "into", "to", "of", "in", "on", "an", "is", "are", "this", "that", "it", "as", "be", "by", "or", "all"}
SEMANTIC_QUERY_TERMS = {"controller", "service", "adapter", "router", "route", "parser", "model", "render", "widget", "channel", "ffi", "pipeline", "state"}

# Domain terms translate query intent; evidence still requires a real token in
# the selected text. These aliases do not choose files or imply support.
DOMAIN_QUERY_ALIASES = {
    "主题": ("theme",), "令牌": ("token", "tokens"), "颜色": ("color",),
    "深色": ("dark",), "浅色": ("light",), "蓝牙": ("bluetooth", "ble"),
    "低功耗": ("ble",), "连接": ("connect", "connection"),
    "解析": ("parse", "parser"), "模型": ("model",), "轨迹": ("toolpath",),
    "渲染": ("render", "rendering"), "绘制": ("draw", "render", "rendering"),
    "命令行": ("cli", "command"), "标准输出": ("stdout",), "标准错误": ("stderr",),
    "规则": ("rule", "rules"), "指南": ("agents", "guide"), "契约": ("contract",),
    "验证": ("validate", "validation"), "测试": ("test",),
    "发布": ("release", "deploy", "deployment"), "构建": ("build",),
    "安装": ("install", "installer"), "流水线": ("pipeline", "workflow"),
    "窗口": ("window",), "路由": ("route", "router"), "表格": ("table",),
    "弹窗": ("popup", "dialog"),
    "扫描": ("scan", "scanner"), "输出": ("output",), "错误输出": ("stderr",),
    "严重程度": ("severity",), "退出码": ("exit",), "超时": ("timeout",),
    "编辑器": ("editor", "ide"), "适配": ("adapter",), "缓存": ("cache",),
    "几何": ("geometry",), "缓冲": ("buffer",), "画布": ("canvas", "surface"),
    "播放": ("playback",), "进度": ("progress",), "同步": ("sync",),
    "持久化": ("persist", "persisted", "persistence"), "坐标": ("coordinate",),
    "绝对": ("absolute",), "相对": ("relative",), "释放": ("dispose",),
    "监听器": ("listener", "listeners"), "会话": ("session",), "注册表": ("registry",),
    "生命周期": ("lifecycle",), "资源": ("resource", "resources"), "元数据": ("metadata",),
    "默认": ("default",), "选项": ("option", "options"), "执行": ("execute",),
    "版本": ("version",), "运行时": ("runtime",), "验收": ("acceptance",),
    "苹果桌面": ("macos",), "安卓": ("android",), "微软桌面": ("windows",),
}


def identifier_terms(text: str) -> set[str]:
    """Tokenize text and split language identifiers without substring matches."""
    result = set()
    for identifier in re.findall(r"[A-Za-z][A-Za-z0-9_]*", text):
        result.add(identifier.lower())
        for segment in identifier.split("_"):
            # Handles camelCase, PascalCase, and acronym prefixes (BLESession).
            result.update(part.lower() for part in re.findall(r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+", segment) if len(part) >= 2 and not part.isdigit())
    return result


def terms(requirement: str) -> list[str]:
    found = []
    for identifier in re.findall(r"[A-Za-z][A-Za-z0-9_]*", requirement):
        found.append(identifier.lower())
        found.extend(sorted(identifier_terms(identifier) - {identifier.lower()}))
    for phrase, aliases in DOMAIN_QUERY_ALIASES.items():
        if phrase in requirement:
            found.extend(aliases)
    return [term for term in dict.fromkeys(found) if len(term) >= 2 and term not in STOP_TERMS]


def first_matching_term(line: str, query_terms: list[str]) -> str | None:
    tokens = identifier_terms(line)
    return next((term for term in query_terms if term in tokens), None)


def validate_source_texts(source_texts: dict[str, str] | None, candidate_paths: list[str], selected_paths: list[str]) -> None:
    """Require a closed text snapshot of selected, explicit repo-relative files."""
    if source_texts is None:
        return
    if not isinstance(source_texts, dict):
        raise ValueError("source_texts must be a repository-relative text mapping")
    candidates = {Path(value).as_posix() for value in candidate_paths}
    for key, value in source_texts.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("source_texts keys and values must be strings")
        path = Path(key)
        if path.is_absolute() or ".." in path.parts or key != path.as_posix() or key not in candidates:
            raise ValueError(f"source_texts key is not an explicit repository-relative candidate: {key}")
    missing = set(selected_paths) - source_texts.keys()
    if missing:
        raise ValueError(f"source_texts lacks selected candidates: {', '.join(sorted(missing))}")


class RepositorySearcher:
    def __init__(self, config: WorkspaceConfig):
        self.config = config
        self.repositories = {repo.repo_id: repo for repo in registry_api.list_repositories(config)}
        self.units_by_repo: dict[str, list[DevelopmentUnit]] = {}
        for unit in registry_api.list_development_units(config):
            self.units_by_repo.setdefault(unit.repo_id, []).append(unit)

    def _source_files(self, base: Path):
        for current, directories, files in os.walk(base):
            current_path = Path(current)
            directories[:] = [
                name for name in directories
                if name not in EXCLUDED and not (current_path / name).is_symlink()
            ]
            for name in files:
                path = current_path / name
                if path.suffix in SOURCE_SUFFIXES and not path.is_symlink():
                    yield path
    def _owns_path(self, unit: DevelopmentUnit, path: Path) -> bool:
        """Keep parent repository scans from attributing nested units to itself."""
        repo = self.repositories.get(unit.repo_id)
        if not repo: return False
        base = (repo.path / unit.relative_path).resolve()
        for other in self.units_by_repo.get(unit.repo_id, []):
            if other.repo_id != unit.repo_id or other.unit_id == unit.unit_id or other.relative_path == ".":
                continue
            nested = (repo.path / other.relative_path).resolve()
            if is_within(nested, base) and is_within(path, nested):
                return False
        return True
    def search_symbols(self, unit: DevelopmentUnit, term_list: list[str], max_results: int):
        return self._search(unit, term_list, max_results, "symbol")
    def search_callsites(self, unit: DevelopmentUnit, term_list: list[str], max_results: int):
        return self._search(unit, term_list, max_results, "callsite")
    def _search(self, unit, term_list, max_results, kind):
        repo = self.repositories.get(unit.repo_id)
        if not repo: return []
        base = (repo.path / unit.relative_path).resolve()
        matches = []
        for path in self._source_files(base):
            if not is_allowed_business_path(path, self.config) or not self._owns_path(unit, path): continue
            try: lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError): continue
            for line_number, line in enumerate(lines, 1):
                for term in term_list:
                    exact = re.search(rf"\b{re.escape(term)}\b", line, re.IGNORECASE)
                    if not exact: continue
                    if kind == "callsite" and not ("import " in line or "package:" in line or re.search(rf"\b{re.escape(term)}\s*\(", line, re.I)): continue
                    matches.append((path, line_number, term, kind))
                    break
                if len(matches) >= max_results: break
        # Source evidence is a more direct implementation signal than mentions in
        # documentation, generated metadata, or tests.  This is ordering only:
        # every selected result still has an exact textual evidence reference.
        return sorted(matches, key=lambda item: (item[0].suffix not in SOURCE_SUFFIXES, str(item[0]), item[1]))[:max_results]
    def semantic_anchors(self, unit: DevelopmentUnit, max_results: int, preferred_terms: list[str]):
        """Return bounded source anchors independent of a requirement's wording."""
        repo=self.repositories.get(unit.repo_id)
        if not repo: return []
        patterns=(r'abstract class ',r'implements ',r'class \w+Controller',r'GoRouter\s*\(',r'MethodChannel',r'class \w*(Parser|Model)',r'(StatelessWidget|StatefulWidget)')
        found=[]
        for path in self._source_files(repo.path/unit.relative_path):
            if path.suffix != '.dart' or not is_allowed_business_path(path,self.config) or not self._owns_path(unit,path): continue
            try: text=path.read_text(encoding='utf-8')
            except (OSError,UnicodeDecodeError): continue
            for number,line in enumerate(text.splitlines(),1):
                if any(re.search(pattern,line) for pattern in patterns):
                    score=sum(term in line.lower() or term in path.name.lower() for term in preferred_terms)
                    found.append((score,path,number,'semantic_anchor','anchor')); break
        return [(path,number,term,kind) for _,path,number,term,kind in sorted(found,key=lambda item:(-item[0],str(item[1])))[:max_results]]


AGENT_RULE_NAMES = {"AGENTS.md", "AGENTS.override.md"}


def ancestor_agent_rules(root: Path, path: Path) -> list[Path]:
    """Stat exact ancestor guide names, root first; overrides mask AGENTS.md.

    This does not read guides or enumerate directories. Unsafe source paths
    produce no candidates. A symlink override remains the active candidate so
    callers reject it explicitly instead of falling back to weaker guidance.
    """
    root = root.resolve()
    path = path if path.is_absolute() else root / path
    if ".." in path.parts or not (path == root or root in path.parents):
        return []
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent == root or root in parent.parents):
        return []
    directory = path if path.is_dir() else path.parent
    directories = [directory, *[parent for parent in directory.parents if parent == root or root in parent.parents]]
    result = []
    for directory in reversed(directories):
        override = directory / "AGENTS.override.md"
        guide = directory / "AGENTS.md"
        try:
            override_present = override.exists() or override.is_symlink()
        except OSError:
            # An unreadable override cannot prove that ordinary guidance is
            # active. Keep its exact path for the caller's unknown record.
            result.append(override)
            continue
        if override_present:
            result.append(override)
        else:
            try:
                guide_present = guide.exists() or guide.is_symlink()
            except OSError:
                guide_present = True
            if guide_present:
                result.append(guide)
    return result


class RuleResolver:
    def __init__(self, config: WorkspaceConfig): self.config = config

    def resolve_rules_for_path(self, path_or_unit: str | Path, *, selected_paths: set[Path] | None = None, readable_paths: set[Path] | None = None, unknowns: list[ContextUnknown] | None = None) -> list[ContextRule]:
        unit = registry_api.get_development_unit(self.config, str(path_or_unit))
        if unit:
            repo = registry_api.get_repository(self.config, unit.repo_id)
            path = repo.path / unit.relative_path if repo else None
            applies_to = unit.unit_id
        else:
            path = Path(path_or_unit)
            if not path.is_absolute():
                path = self.config.workspace_root / path
            matches = [item for item in registry_api.list_repositories(self.config) if path == item.path or item.path in path.parents]
            repo = max(matches, key=lambda item: len(item.path.parts)) if matches else None
            applies_to = f"{repo.repo_id}:{path.relative_to(repo.path).as_posix()}" if repo else str(path_or_unit)
        if repo is None or path is None or not is_allowed_business_path(path, self.config):
            return []
        if ".." in path.parts or not is_within(path, repo.path) or path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent == repo.path or repo.path in parent.parents):
            return []
        active = ancestor_agent_rules(repo.path, path)
        rules = []

        def safe(guide):
            try:
                available = is_within(guide, repo.path) and is_allowed_business_path(guide, self.config) and guide.is_file() and not guide.is_symlink() and not any(parent.is_symlink() for parent in guide.parents if parent == repo.path or repo.path in parent.parents)
            except OSError:
                available = False
            if not available and unknowns is not None:
                unknowns.append(ContextUnknown(subject=guide.relative_to(self.config.workspace_root).as_posix(), reason=f"Applicable rule path is missing, unsafe, or not a regular file for {applies_to}.", required_evidence="An existing in-repository rule file without symlinks."))
            return available

        def readable(guide):
            if readable_paths is not None:
                available = guide.resolve() in readable_paths
            else:
                try:
                    guide.read_text(encoding="utf-8")
                    available = True
                except (OSError, UnicodeDecodeError):
                    available = False
            if not available and unknowns is not None:
                unknowns.append(ContextUnknown(subject=guide.relative_to(self.config.workspace_root).as_posix(), reason=f"Applicable guide could not be read for {applies_to}.", required_evidence="Readable UTF-8 rule content in the explicit intake."))
            return available

        for guide in active:
            if not safe(guide):
                continue
            if selected_paths is not None and guide not in selected_paths:
                if unknowns is not None:
                    unknowns.append(ContextUnknown(subject=guide.relative_to(self.config.workspace_root).as_posix(), reason=f"Applicable ancestor guide is not selected for {applies_to}.", required_evidence=f"Include {guide.relative_to(repo.path).as_posix()} in explicit candidate_paths within the file budget."))
                continue
            if not readable(guide):
                continue
            rules.append(ContextRule(path=guide.relative_to(self.config.workspace_root).as_posix(), scope=guide.parent.relative_to(self.config.workspace_root).as_posix(), applies_to=applies_to, provenance="filesystem_agent_override" if guide.name == "AGENTS.override.md" else "filesystem_agent_ancestor"))
        owner = unit or registry_api.find_unit_by_path(self.config, path)
        for cached in registry_api.get_rule_files(self.config, owner.unit_id if owner else path):
            if Path(cached.path).name in AGENT_RULE_NAMES:
                continue
            guide = self.config.workspace_root / cached.path
            scope = self.config.workspace_root / cached.scope
            if not is_within(guide, repo.path) or not is_within(scope, repo.path) or not is_within(path, scope):
                continue
            if not safe(guide):
                continue
            if selected_paths is not None and guide.resolve() not in selected_paths:
                if unknowns is not None:
                    unknowns.append(ContextUnknown(subject=guide.relative_to(self.config.workspace_root).as_posix(), reason=f"Applicable cached rule is not selected for {applies_to}.", required_evidence=f"Include {guide.relative_to(repo.path).as_posix()} in explicit candidate_paths within the file budget."))
                continue
            if not readable(guide):
                continue
            rules.append(ContextRule(path=cached.path, scope=cached.scope, applies_to=applies_to, provenance=cached.provenance))
        return list({rule.path: rule for rule in rules}.values())


class EvidenceScorer:
    def score(self, *, dependency_count: int, symbol_count: int, callsite_count: int, rule_count: int, file_count: int, name_only: bool, unknown: bool) -> str:
        points = dependency_count * 2 + (2 if symbol_count or callsite_count else 0) + (1 if rule_count else 0) + (1 if file_count else 0) - (2 if unknown else 0)
        if name_only: return "LOW"
        return "HIGH" if points >= 5 else "MEDIUM" if points >= 2 else "LOW" if points >= 0 else "BLOCKED"


class ContextResolver:
    def __init__(self, config: WorkspaceConfig):
        self.config, self.searcher, self.rules, self.scorer = config, RepositorySearcher(config), RuleResolver(config), EvidenceScorer()
    def search_symbols(self, unit_id: str, query: str):
        unit = registry_api.get_development_unit(self.config, unit_id)
        return [] if not unit else self.searcher.search_symbols(unit, terms(query), 80)
    def search_callsites(self, unit_id: str, query: str):
        unit = registry_api.get_development_unit(self.config, unit_id)
        return [] if not unit else self.searcher.search_callsites(unit, terms(query), 80)
    def resolve_rules_for_path(self, path_or_unit: str): return self.rules.resolve_rules_for_path(path_or_unit)
    def explain_candidate(self, candidate: ContextCandidate) -> dict: return candidate.model_dump()
    def resolve_context(self, requirement: str, target_repository: str | None = None, limits: ContextLimits | None = None, *, candidate_paths: list[str] | None = None, source_texts: dict[str, str] | None = None) -> ContextPackage:
        """Resolve evidence, optionally from a closed explicit text snapshot.

        Snapshot keys are normalized repository-relative candidate paths. Every
        selected file must have text; no source is reopened in snapshot mode.
        """
        if candidate_paths is not None:
            return self._resolve_bounded_context(requirement, target_repository, limits or ContextLimits(), candidate_paths, source_texts)
        if source_texts is not None:
            raise ValueError("source_texts requires explicit candidate_paths")
        limits = limits or ContextLimits(); term_list = terms(requirement); repositories = registry_api.list_repositories(self.config)
        if target_repository:
            selected_repos = [repo for repo in repositories if repo.repo_id == target_repository]
        else:
            selected_repos = repositories[:limits.max_candidate_repositories]
        units = [unit for repo in selected_repos for unit in repo.development_units]
        # Root application units are composition boundaries; process them before
        # nested packages so the bounded file budget cannot hide their anchors.
        units.sort(key=lambda unit: (unit.relative_path != ".", len(unit.relative_path)))
        # Registry-backed neighborhood expansion never turns a neighbor into a required change.
        seen = {unit.unit_id for unit in units}
        frontier = list(units)
        for _ in range(limits.max_dependency_depth):
            next_frontier = []
            for unit in frontier:
                for edge in registry_api.get_dependencies(self.config, unit.unit_id) + registry_api.get_dependents(self.config, unit.unit_id):
                    neighbor_id = edge.target if edge.source == unit.unit_id else edge.source
                    neighbor = registry_api.get_development_unit(self.config, neighbor_id)
                    if neighbor and neighbor.unit_id not in seen:
                        seen.add(neighbor.unit_id); units.append(neighbor); next_frontier.append(neighbor)
            frontier = next_frontier
        candidates, files, symbols, rules, dependencies, unknowns = [], [], [], [], [], []
        searched_files = 0
        # Reserve a small, per-unit share of the file budget for direct semantic
        # definitions.  Broad lexical matches elsewhere must not hide a controller,
        # router root, contract implementation, or widget composition anchor.
        reserved_anchors = {}
        for unit in units:
            probe_symbols = self.searcher.search_symbols(unit, term_list, 1)
            probe_calls = self.searcher.search_callsites(unit, term_list, 1)
            hits = self.searcher.semantic_anchors(unit, 4, term_list) if (probe_symbols or probe_calls or set(term_list) & SEMANTIC_QUERY_TERMS) else []
            reserved_anchors[unit.unit_id] = hits
            for path, line, term, kind in hits:
                if len(files) >= limits.max_files: break
                if str(path) in {item.absolute_path for item in files}: continue
                symbols.append(ContextSymbol(name=term, kind=kind, file=str(path), line=line, evidence_refs=[f"{path.relative_to(self.config.workspace_root)}:{line}"]))
                files.append(ContextFile(absolute_path=str(path), relative_path=str(path.relative_to(self.config.workspace_root)), repo_id=unit.repo_id, unit_id=unit.unit_id, relevance=kind, evidence_refs=[f"{path.relative_to(self.config.workspace_root)}:{line}"]))
        for unit in units:
            deps = registry_api.get_dependencies(self.config, unit.unit_id) + registry_api.get_dependents(self.config, unit.unit_id)
            symbol_hits = self.searcher.search_symbols(unit, term_list, limits.max_symbols - len(symbols))
            call_hits = self.searcher.search_callsites(unit, term_list, limits.max_symbols - len(symbols))
            anchor_hits = reserved_anchors[unit.unit_id]
            name_only = not symbol_hits and not call_hits and not deps
            unit_rules = self.rules.resolve_rules_for_path(unit.unit_id)
            classification = "required" if symbol_hits or call_hits else "context_only" if deps else "unknown"
            confidence = self.scorer.score(dependency_count=len(deps), symbol_count=len(symbol_hits), callsite_count=len(call_hits), rule_count=len(unit_rules), file_count=len(symbol_hits)+len(call_hits), name_only=name_only, unknown=classification == "unknown")
            refs = [f"{path.relative_to(self.config.workspace_root)}:{line}" for path, line, _, _ in symbol_hits + call_hits]
            candidates.append(ContextCandidate(id=unit.unit_id, classification=classification, confidence=confidence, reasons=["exact lexical evidence" if refs else "registry dependency evidence" if deps else "no supported evidence"], evidence_refs=refs + [edge.evidence.path for edge in deps]))
            for path, line, term, kind in anchor_hits + symbol_hits + call_hits:
                if len(symbols) < limits.max_symbols: symbols.append(ContextSymbol(name=term, kind=kind, file=str(path), line=line, evidence_refs=[f"{path.relative_to(self.config.workspace_root)}:{line}"]))
                if len(files) < limits.max_files and str(path) not in {item.absolute_path for item in files}:
                    repo = registry_api.get_repository(self.config, unit.repo_id); files.append(ContextFile(absolute_path=str(path), relative_path=str(path.relative_to(self.config.workspace_root)), repo_id=unit.repo_id, unit_id=unit.unit_id, relevance=kind, evidence_refs=[f"{path.relative_to(self.config.workspace_root)}:{line}"]))
            for manifest in unit.manifests:
                manifest_path = self.config.workspace_root / manifest
                if len(files) < limits.max_files and any(term in manifest.lower() for term in term_list) and str(manifest_path) not in {item.absolute_path for item in files}:
                    files.append(ContextFile(absolute_path=str(manifest_path), relative_path=manifest, repo_id=unit.repo_id, unit_id=unit.unit_id, relevance="file_path_match", evidence_refs=[manifest]))
            rules.extend(unit_rules); dependencies.extend(deps)
            if classification == "unknown": unknowns.append(ContextUnknown(subject=unit.unit_id, reason="No exact symbol, callsite, or registry dependency evidence matched the requirement.", required_evidence="Exact source/import/callsite or manifest dependency evidence."))
            searched_files += len(unit.manifests)
        candidates = sorted(candidates, key=lambda item: ({"required": 0, "context_only": 1, "unknown": 2}[item.classification], {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "BLOCKED": 3}[item.confidence]))
        candidates = candidates[:limits.max_candidate_repositories * 10]
        unique_deps = {f"{edge.source}>{edge.target}>{edge.kind}": edge for edge in dependencies}
        unique_rules = {f"{rule.path}:{rule.applies_to}": rule for rule in rules}
        unique_symbols = {(item.file, item.line, item.name, item.kind): item for item in symbols}
        package = ContextPackage(request={"requirement": requirement, "optional_target_repository": target_repository}, scope={"repositories": sorted({registry_api.get_development_unit(self.config, unit.unit_id).repo_id for unit in units}), "development_units": [unit.unit_id for unit in units]}, candidates=candidates, files=files[:limits.max_files], symbols=list(unique_symbols.values())[:limits.max_symbols], rules=list(unique_rules.values()), dependencies=list(unique_deps.values()), unknowns=unknowns, confidence="HIGH" if any(item.confidence == "HIGH" for item in candidates) else "MEDIUM" if any(item.confidence == "MEDIUM" for item in candidates) else "LOW", metrics={"searched_repositories": len(selected_repos), "searched_files": searched_files, "selected_files": len(files[:limits.max_files]), "evidence_count": len(unique_symbols)+len(unique_deps), "context_size_estimate": len(files)+len(unique_symbols)+len(unique_deps)+len(unique_rules)})
        return package

    def _resolve_bounded_context(self, requirement: str, target_repository: str | None, limits: ContextLimits, candidate_paths: list[str], source_texts: dict[str, str] | None = None) -> ContextPackage:
        """Resolve only explicit repository-relative files, without discovery.

        An empty list is an empty intake. Registry relationships remain context
        metadata and never expand the source files read by this mode.
        """
        if not target_repository:
            raise ValueError("bounded context requires target_repository")
        repo = registry_api.get_repository(self.config, target_repository)
        if repo is None or not is_allowed_business_path(repo.path, self.config):
            raise ValueError(f"unknown or out-of-bound repository: {target_repository}")
        if min(limits.max_files, limits.max_symbols) < 0:
            raise ValueError("context limits must be nonnegative")
        repo_root = repo.path.resolve()
        paths: list[tuple[Path, DevelopmentUnit]] = []
        for value in candidate_paths:
            if not isinstance(value, str):
                raise ValueError("candidate paths must be repository-relative strings")
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"candidate must be repository-relative: {value}")
            path = repo.path / relative
            if path.is_symlink() or any(parent.is_symlink() for parent in path.parents if is_within(parent, repo_root)):
                raise ValueError(f"symlink candidate is not allowed: {value}")
            resolved = path.resolve()
            if not is_within(resolved, repo_root) or not is_allowed_business_path(resolved, self.config):
                raise ValueError(f"candidate outside repository boundary: {value}")
            if not resolved.is_file():
                raise ValueError(f"candidate must be an existing file: {value}")
            unit = registry_api.find_unit_by_path(self.config, resolved)
            if unit is None or unit.repo_id != target_repository:
                raise ValueError(f"candidate has no registered development unit: {value}")
            if resolved not in {item[0] for item in paths}:
                paths.append((resolved, unit))
        selected = paths[:limits.max_files]
        validate_source_texts(source_texts, candidate_paths, [path.relative_to(repo_root).as_posix() for path, _ in selected])
        if source_texts is not None:
            source_texts = dict(source_texts)
        selected_paths = {path for path, _ in selected}
        unit_map = {unit.unit_id: unit for _, unit in selected}
        term_list = terms(requirement)
        files, symbols, candidates, rules, dependencies, unknowns = [], [], [], [], [], []
        read_files = 0
        readable_paths = set()
        refs_by_unit: dict[str, list[str]] = {unit_id: [] for unit_id in unit_map}
        matches_by_file = []
        for path, unit in selected:
            relative = path.relative_to(self.config.workspace_root).as_posix()
            refs = [relative]
            try:
                text = source_texts[path.relative_to(repo_root).as_posix()] if source_texts is not None else path.read_text(encoding="utf-8")
                lines = text.splitlines()
                read_files += 1
                readable_paths.add(path)
            except (OSError, UnicodeDecodeError):
                unknowns.append(ContextUnknown(subject=relative, reason="Explicit candidate could not be read as text.", required_evidence="Readable source or control document."))
                lines = []
            file_matches = []
            for number, line in enumerate(lines, 1):
                term = first_matching_term(line, term_list)
                if term:
                    file_matches.append((number, term))
                    # No file can consume more than the total package budget;
                    # one match suffices to retain relevance when it is zero.
                    if len(file_matches) >= max(1, limits.max_symbols):
                        break
            relevance = "explicit_candidate_query_match" if file_matches else "explicit_candidate_no_query_match" if path in readable_paths else "explicit_candidate_unreadable"
            file = ContextFile(absolute_path=str(path), relative_path=relative, repo_id=unit.repo_id, unit_id=unit.unit_id, relevance=relevance, evidence_refs=refs)
            files.append(file)
            if file_matches:
                matches_by_file.append((path, unit, file, file_matches))
        # Selected implementation, script, and configuration evidence gets the
        # first opportunity. Round robin then prevents any large file or guide
        # from spending the entire symbol budget before other matching files.
        def evidence_priority(item):
            path, _, file, _ = item
            path_terms = identifier_terms(path.relative_to(repo_root).as_posix())
            document = path.suffix.lower() in {".md", ".rst"}
            return document, -len(set(term_list) & path_terms), file.relative_path

        matches_by_file.sort(key=evidence_priority)
        for index in range(max((len(item[3]) for item in matches_by_file), default=0)):
            if len(symbols) >= limits.max_symbols:
                break
            for path, _, file, file_matches in matches_by_file:
                if index >= len(file_matches):
                    continue
                number, term = file_matches[index]
                ref = f"{file.relative_path}:{number}"
                file.evidence_refs.append(ref)
                symbols.append(ContextSymbol(name=term, kind="symbol", file=str(path), line=number, evidence_refs=[ref]))
                if len(symbols) >= limits.max_symbols:
                    break
        for file in files:
            refs_by_unit[file.unit_id].extend(file.evidence_refs)
        for unit_id, unit in unit_map.items():
            refs = refs_by_unit[unit_id]
            candidates.append(ContextCandidate(id=unit_id, classification="context_only", confidence="MEDIUM", reasons=["explicit bounded file intake"], evidence_refs=refs))
            dependencies.extend(registry_api.get_dependencies(self.config, unit_id) + registry_api.get_dependents(self.config, unit_id))
        rule_unknowns = []
        for path, _ in selected:
            rules.extend(self.rules.resolve_rules_for_path(path, selected_paths=selected_paths, readable_paths=readable_paths, unknowns=rule_unknowns))
        unknowns.extend(rule_unknowns)
        unique_rules = {f"{rule.path}:{rule.applies_to}": rule for rule in rules}
        unique_deps = {f"{edge.source}>{edge.target}>{edge.kind}": edge for edge in dependencies}
        return ContextPackage(
            request={"requirement": requirement, "optional_target_repository": target_repository, "candidate_paths": candidate_paths},
            scope={"repositories": [target_repository], "development_units": list(unit_map)},
            candidates=candidates, files=files, symbols=symbols, rules=list(unique_rules.values()), dependencies=list(unique_deps.values()), unknowns=unknowns,
            confidence="MEDIUM" if files else "LOW",
            metrics={"searched_repositories": 1, "searched_files": read_files, "selected_files": len(files), "candidate_files": len(paths), "evidence_count": len(symbols) + len(unique_deps), "context_size_estimate": len(files) + len(symbols) + len(unique_deps) + len(unique_rules), "rule_files": len({rule.path for rule in rules}), "rule_target_files": len({rule.applies_to for rule in rules}), "missing_rule_candidates": len({item.subject for item in rule_unknowns if "not selected" in item.reason})},
        )
    def validate_context_package(self, package: ContextPackage) -> list[str]:
        errors=[]
        for file in package.files:
            if not is_allowed_business_path(Path(file.absolute_path), self.config): errors.append(f"out-of-bound file: {file.absolute_path}")
        for dependency in package.dependencies:
            if not dependency.evidence.path: errors.append(f"dependency lacks evidence: {dependency.source}")
        return errors
