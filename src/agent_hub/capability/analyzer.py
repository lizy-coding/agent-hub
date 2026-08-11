"""Evidence-driven ownership, coupling, overlap, and extraction assessment."""
from pathlib import Path
from agent_hub.context.resolver import ContextResolver
from agent_hub.projects import api as registry_api
from agent_hub.schemas.models import CapabilityAnalysis, CapabilityNode, ContextPackage, CouplingProfile, ExtractionAssessment, WorkspaceCapabilityMatch
from agent_hub.tools.path_guard import is_allowed_business_path
from agent_hub.workspace.config import WorkspaceConfig

class CapabilityAnalyzer:
    def __init__(self, config: WorkspaceConfig): self.config=config; self.resolver=ContextResolver(config)
    def _text(self, context: ContextPackage) -> dict[str,str]:
        result={}
        for item in context.files:
            path=Path(item.absolute_path)
            if is_allowed_business_path(path,self.config):
                try: result[item.absolute_path]=path.read_text(encoding='utf-8')[:12000]
                except (OSError,UnicodeDecodeError): pass
        return result
    def analyze_coupling(self, text: str) -> CouplingProfile:
        low=text.lower()
        return CouplingProfile(ui="HIGH" if any(x in low for x in ('widget','build(','custompaint')) else "NONE", application_state="HIGH" if any(x in low for x in ('provider','riverpod','bloc','navigator','router','controller')) else "LOW" if 'state' in low else "NONE", platform="HIGH" if any(x in low for x in ('methodchannel','ffi','platform')) else "NONE", external_contract="MEDIUM" if any(x in low for x in ('abstract class','interface','service')) else "NONE")
    def classify_ownership(self, text: str, coupling: CouplingProfile) -> str:
        low=text.lower()
        if coupling.platform == 'HIGH': return 'platform_plugin'
        if 'adapter' in low: return 'adapter'
        if coupling.application_state == 'HIGH': return 'application_orchestration'
        if coupling.ui == 'HIGH' and coupling.application_state == 'NONE': return 'ui_only'
        if any(x in low for x in ('parser','algorithm','model','transform')) and coupling.ui == 'NONE': return 'shared_core'
        return 'unknown'
    def match_workspace_capabilities(self, node: CapabilityNode, context: ContextPackage):
        matches=[]
        for edge in node.dependencies:
            target=registry_api.get_development_unit(self.config, edge.target)
            if target and target.repo_id != node.target_repo:
                matches.append(WorkspaceCapabilityMatch(source_capability_id=node.capability_id,target_repo=target.repo_id,target_unit=target.unit_id,match_type='existing_unit_strong_match',matched_contracts=[],matched_symbols=[],evidence_refs=[edge.evidence.path],confidence='HIGH'))
            elif target:
                matches.append(WorkspaceCapabilityMatch(source_capability_id=node.capability_id,target_repo=target.repo_id,target_unit=target.unit_id,match_type='existing_unit_partial_overlap',matched_contracts=[],matched_symbols=[],evidence_refs=[edge.evidence.path],confidence='MEDIUM'))
        return matches
    def assess_extraction(self,node:CapabilityNode,matches):
        strong=next((m for m in matches if m.match_type=='existing_unit_strong_match'),None)
        if node.ownership=='application_orchestration': decision='KEEP_IN_APPLICATION'; target=None
        elif strong: decision='MOVE_TO_EXISTING_UNIT'; target=strong
        elif node.ownership=='shared_core' and node.coupling.ui in ('NONE','LOW') and node.coupling.application_state in ('NONE','LOW'): decision='NEW_SHARED_CORE_CANDIDATE'; target=None
        elif node.ownership=='platform_plugin': decision='NEW_PLUGIN_CANDIDATE'; target=None
        elif node.ownership=='adapter': decision='ADAPTER_ONLY'; target=None
        else: decision='NOT_ENOUGH_EVIDENCE'; target=None
        return ExtractionAssessment(capability_id=node.capability_id,decision=decision,target_repo=target.target_repo if target else None,target_unit=target.target_unit if target else None,reasons=[f'ownership={node.ownership}'],blockers=node.unknowns,evidence_refs=node.evidence_refs,confidence=node.confidence)
    def analyze_capabilities(self, requirement:str, target_repository:str) -> CapabilityAnalysis:
        context=self.resolver.resolve_context(requirement,target_repository)
        text_by_file=self._text(context); nodes=[]
        for candidate in context.candidates:
            if candidate.classification=='unknown': continue
            unit_files=[f for f in context.files if f.unit_id==candidate.id]
            unit_text='\n'.join(text_by_file.get(f.absolute_path,'') for f in unit_files)
            coupling=self.analyze_coupling(unit_text); ownership=self.classify_ownership(unit_text,coupling)
            unknowns=[] if ownership!='unknown' else ['Insufficient bounded source evidence for ownership.']
            deps=[d for d in context.dependencies if d.source==candidate.id or d.target==candidate.id]
            confidence='HIGH' if candidate.confidence=='HIGH' and ownership!='unknown' and unit_files else 'MEDIUM' if unit_files else 'LOW'
            nodes.append(CapabilityNode(capability_id=f'capability:{candidate.id}',label='evidence_cluster',target_repo=target_repository,development_units=[candidate.id],files=[f.relative_path for f in unit_files],symbols=[s.name for s in context.symbols if any(s.file==f.absolute_path for f in unit_files)],responsibilities=['bounded evidence cluster'],ownership=ownership,coupling=coupling,dependencies=deps,evidence_refs=candidate.evidence_refs,confidence=confidence,unknowns=unknowns))
        matches=[m for n in nodes for m in self.match_workspace_capabilities(n,context)]
        assessments=[self.assess_extraction(n,[m for m in matches if m.source_capability_id==n.capability_id]) for n in nodes]
        unknowns=list(context.unknowns[i].reason for i in range(len(context.unknowns)))+[u for n in nodes for u in n.unknowns]
        return CapabilityAnalysis(requirement=requirement,target_repository=target_repository,context_ref={'confidence':context.confidence,'metrics':context.metrics},capabilities=nodes,workspace_matches=matches,extraction_assessments=assessments,keep_in_application=[a.capability_id for a in assessments if a.decision=='KEEP_IN_APPLICATION'],extraction_candidates=[a.capability_id for a in assessments if a.decision not in ('KEEP_IN_APPLICATION','NOT_ENOUGH_EVIDENCE')],unknowns=unknowns,evidence_summary={'context_evidence':context.metrics.get('evidence_count',0),'capability_nodes':len(nodes)},metrics={'bounded_files_read':len(text_by_file),'capabilities':len(nodes),'matches':len(matches)})
    def explain_capability(self, node:CapabilityNode): return node.model_dump()
    def validate_capability_analysis(self, analysis:CapabilityAnalysis):
        errors=[]
        for node in analysis.capabilities:
            if not node.evidence_refs: errors.append(f'missing evidence: {node.capability_id}')
            if node.confidence=='HIGH' and node.ownership=='unknown': errors.append(f'untraceable high ownership: {node.capability_id}')
        return errors
