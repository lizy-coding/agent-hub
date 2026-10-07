"""Extraction decisions shared by analysis, evaluation, and planning callers."""

from enum import Enum


class ExtractionDecision(str, Enum):
    KEEP_IN_APPLICATION = "KEEP_IN_APPLICATION"
    ADAPTER_ONLY = "ADAPTER_ONLY"
    NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"
    UNKNOWN = "UNKNOWN"
    EXTEND_EXISTING_UNIT = "EXTEND_EXISTING_UNIT"
    MOVE_TO_EXISTING_UNIT = "MOVE_TO_EXISTING_UNIT"
    NEW_SHARED_CORE_CANDIDATE = "NEW_SHARED_CORE_CANDIDATE"
    NEW_PLUGIN_CANDIDATE = "NEW_PLUGIN_CANDIDATE"


ACTIONABLE_DECISIONS = frozenset({
    ExtractionDecision.EXTEND_EXISTING_UNIT.value,
    ExtractionDecision.MOVE_TO_EXISTING_UNIT.value,
    ExtractionDecision.NEW_SHARED_CORE_CANDIDATE.value,
    ExtractionDecision.NEW_PLUGIN_CANDIDATE.value,
})
