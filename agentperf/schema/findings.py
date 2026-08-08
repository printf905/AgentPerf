from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Severity = Literal["LOW", "MEDIUM", "HIGH"]
Confidence = Literal["LOW", "MEDIUM", "HIGH"]


@dataclass(frozen=True)
class FindingProvenance:
    agent_span_ids: list[str] = field(default_factory=list)
    llm_call_ids: list[str] = field(default_factory=list)
    llm_request_ids: list[str] = field(default_factory=list)
    serving_request_ids: list[str] = field(default_factory=list)
    raw_metrics: dict[str, Any] = field(default_factory=dict)
    derived_metrics: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    id: str
    severity: Severity
    title: str
    summary: str
    evidence: dict[str, Any]
    affected_spans: list[str]
    recommendation: str
    confidence: Confidence
    validation_plan: list[str] = field(default_factory=list)
    provenance: FindingProvenance = field(default_factory=FindingProvenance)
