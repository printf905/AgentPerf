from __future__ import annotations

from dataclasses import dataclass

from agentperf.detectors.base import DetectorContext
from agentperf.metrics.tokens import compute_duplication_metrics
from agentperf.schema.findings import Finding, FindingProvenance, Severity


@dataclass(frozen=True)
class ContextDuplicationConfig:
    min_affected_calls: int = 3
    min_repeated_tokens: int = 50
    min_repeated_ratio: float = 0.25


class ContextDuplicationDetector:
    def __init__(self, config: ContextDuplicationConfig | None = None) -> None:
        self.config = config or ContextDuplicationConfig()

    def detect(self, context: DetectorContext) -> list[Finding]:
        calls = context.run.llm_calls
        metrics = compute_duplication_metrics(calls)
        if len(metrics.affected_call_ids) < self.config.min_affected_calls:
            return []
        if metrics.repeated_context_tokens < self.config.min_repeated_tokens:
            return []
        if metrics.repeated_context_ratio < self.config.min_repeated_ratio:
            return []

        severity: Severity = "HIGH" if metrics.repeated_context_ratio >= 0.5 else "MEDIUM"
        return [
            Finding(
                id="CONTEXT_DUPLICATION",
                severity=severity,
                title="Repeated prompt context across LLM calls",
                summary=(
                    "Multiple LLM calls contain exact repeated prompt components. "
                    "Repeated content may be necessary, but it is a cost and latency signal."
                ),
                evidence={
                    "llm_calls_affected": len(metrics.affected_call_ids),
                    "total_input_tokens": metrics.total_input_tokens,
                    "repeated_context_tokens": metrics.repeated_context_tokens,
                    "repeated_context_ratio": round(metrics.repeated_context_ratio, 4),
                    "largest_common_prefix_tokens": metrics.largest_common_prefix_tokens,
                    "largest_common_prefix_ratio": round(metrics.largest_common_prefix_ratio, 4),
                    "repeated_non_prefix_tokens": metrics.repeated_non_prefix_tokens,
                    "repeated_tokens_by_component": metrics.repeated_tokens_by_component,
                    "tokenization": (
                        "approximate" if metrics.approximate else "trace-provided totals"
                    ),
                },
                affected_spans=metrics.affected_call_ids,
                recommendation=(
                    "Inspect whether stable context can be reused, cached, summarized, "
                    "or moved outside repeatedly reconstructed dynamic context."
                ),
                confidence="MEDIUM",
                validation_plan=[
                    "Replay the workload after any prompt-structure change.",
                    "Compare input tokens, task quality, and end-to-end latency.",
                ],
                provenance=FindingProvenance(
                    llm_call_ids=metrics.affected_call_ids,
                    derived_metrics={
                        "total_input_tokens": metrics.total_input_tokens,
                        "repeated_context_tokens": metrics.repeated_context_tokens,
                        "repeated_context_ratio": metrics.repeated_context_ratio,
                        "largest_common_prefix_tokens": metrics.largest_common_prefix_tokens,
                        "repeated_tokens_by_component": metrics.repeated_tokens_by_component,
                    },
                    notes=[
                        "Repeated content is measured from normalized prompt components.",
                        "The detector does not infer that repeated content is unnecessary.",
                    ],
                ),
            )
        ]
