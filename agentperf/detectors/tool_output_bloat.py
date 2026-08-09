from __future__ import annotations

from dataclasses import dataclass

from agentperf.detectors.base import DetectorContext
from agentperf.metrics.attribution import tool_reinjections
from agentperf.schema.findings import Finding, FindingProvenance, Severity


@dataclass(frozen=True)
class ToolOutputBloatConfig:
    min_raw_output_tokens: int = 500
    min_reinjected_calls: int = 2
    min_cumulative_processed_tokens: int = 1500
    min_share_of_run_input_tokens: float = 0.05


class ToolOutputBloatDetector:
    def __init__(self, config: ToolOutputBloatConfig | None = None) -> None:
        self.config = config or ToolOutputBloatConfig()

    def detect(self, context: DetectorContext) -> list[Finding]:
        candidates = []
        for reinjection in tool_reinjections(context.run):
            if reinjection.raw_output_tokens < self.config.min_raw_output_tokens:
                continue
            if len(reinjection.reinjected_calls) < self.config.min_reinjected_calls:
                continue
            if (
                reinjection.cumulative_processed_tokens
                < self.config.min_cumulative_processed_tokens
            ):
                continue
            if (
                reinjection.share_of_run_input_tokens
                < self.config.min_share_of_run_input_tokens
            ):
                continue
            candidates.append(reinjection)

        if not candidates:
            return []

        candidates.sort(
            key=lambda item: (
                item.share_of_run_input_tokens,
                item.cumulative_processed_tokens,
            ),
            reverse=True,
        )
        primary = candidates[0]
        severity: Severity = (
            "HIGH" if primary.share_of_run_input_tokens >= 0.30 else "MEDIUM"
        )
        return [
            Finding(
                id="TOOL_OUTPUT_BLOAT",
                severity=severity,
                title="Large tool output is repeatedly reinjected",
                summary=(
                    "A tool output contributes disproportionately to downstream LLM "
                    "input-token processing because the harness carries it forward into "
                    "multiple later prompts."
                ),
                evidence={
                    "tool_call_id": primary.tool_call_id,
                    "tool_name": primary.tool_name,
                    "raw_tool_output_tokens": primary.raw_output_tokens,
                    "downstream_reinjections": len(primary.reinjected_calls),
                    "cumulative_downstream_processed_tokens": (
                        primary.cumulative_processed_tokens
                    ),
                    "share_of_run_input_tokens": round(
                        primary.share_of_run_input_tokens,
                        4,
                    ),
                    "affected_llm_calls": len(primary.reinjected_calls),
                },
                affected_spans=[primary.tool_call_id] + primary.reinjected_calls,
                recommendation=(
                    "Evaluate summarizing, truncating, deduplicating, or storing the full "
                    "tool result out-of-band while passing only the relevant compact "
                    "representation forward."
                ),
                confidence="HIGH",
                validation_plan=[
                    "Replay the same task set after changing tool-result carry-forward.",
                    (
                        "Compare processed input tokens, tool-result processed tokens, "
                        "latency, and rule-based task correctness."
                    ),
                ],
                provenance=FindingProvenance(
                    agent_span_ids=[primary.tool_call_id],
                    llm_call_ids=primary.reinjected_calls,
                    raw_metrics={
                        "raw_tool_output_tokens": primary.raw_output_tokens,
                    },
                    derived_metrics={
                        "cumulative_downstream_processed_tokens": (
                            primary.cumulative_processed_tokens
                        ),
                        "share_of_run_input_tokens": primary.share_of_run_input_tokens,
                        "downstream_reinjections": len(primary.reinjected_calls),
                    },
                    notes=[
                        "Tool-output bloat is measured from explicit prompt-component provenance.",
                        (
                            "The detector does not infer that the full tool output is "
                            "semantically useless."
                        ),
                    ],
                ),
            )
        ]
