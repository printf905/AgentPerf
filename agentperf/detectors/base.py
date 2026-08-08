from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentperf.correlation.correlator import CorrelationResult
from agentperf.schema.findings import Finding
from agentperf.schema.trace import AgentRun


@dataclass(frozen=True)
class DetectorContext:
    run: AgentRun
    correlation: CorrelationResult


class Detector(Protocol):
    def detect(self, context: DetectorContext) -> list[Finding]:
        ...

