from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from agentperf.detectors.base import DetectorContext
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import (
    mean_prefill_fraction,
    prefill_or_path_label,
    prefill_or_path_latency_ms,
)
from agentperf.metrics.tokens import (
    approximate_tokens,
    common_prefix_len,
    compute_duplication_metrics,
)
from agentperf.schema.findings import Finding, FindingProvenance
from agentperf.schema.trace import LLMCall, ServingRequest


@dataclass(frozen=True)
class PrefixCacheOpportunityConfig:
    min_affected_requests: int = 2
    min_shared_prefix_ratio: float = 0.60
    min_repeated_non_prefix_ratio: float = 0.50
    max_actual_cache_hit_ratio: float = 0.35
    min_prefill_fraction_of_ttft: float = 0.50
    min_shared_prefix_tokens: int = 50


@dataclass(frozen=True)
class PrefixGroup:
    call_ids: list[str]
    request_ids: list[str]
    shared_prefix_tokens: int
    shared_prefix_ratio: float
    repeated_non_prefix_tokens: int
    repeated_non_prefix_ratio: float
    avg_input_tokens: float
    requests: list[ServingRequest]


class PrefixCacheOpportunityDetector:
    def __init__(self, config: PrefixCacheOpportunityConfig | None = None) -> None:
        self.config = config or PrefixCacheOpportunityConfig()

    def detect(self, context: DetectorContext) -> list[Finding]:
        group = self._best_group(context)
        if group is None:
            return []

        hit_ratio = prefix_cache_hit_ratio(group.requests)
        prefill_fraction = mean_prefill_fraction(group.requests)
        if hit_ratio is None or prefill_fraction is None:
            return []
        if hit_ratio > self.config.max_actual_cache_hit_ratio:
            return []
        if prefill_fraction < self.config.min_prefill_fraction_of_ttft:
            return []
        latency_semantics = prefill_or_path_label(group.requests)
        prefill_fraction_key = (
            "prefill_path_proxy_fraction_of_ttft"
            if latency_semantics == "prefill_path_proxy"
            else "prefill_fraction_of_ttft"
        )

        return [
            Finding(
                id="PREFIX_CACHE_OPPORTUNITY",
                severity="HIGH",
                title=_title(group),
                summary=(
                    "Correlated requests contain substantial repeated stable content, but "
                    "serving telemetry reports low actual prefix-cache reuse while the "
                    "prefill path contributes materially to TTFT."
                ),
                evidence={
                    "affected_requests": len(group.request_ids),
                    "average_input_tokens": round(group.avg_input_tokens, 1),
                    "shared_prefix_tokens": group.shared_prefix_tokens,
                    "shared_prefix_ratio": round(group.shared_prefix_ratio, 4),
                    "repeated_non_prefix_tokens": group.repeated_non_prefix_tokens,
                    "repeated_non_prefix_ratio": round(
                        group.repeated_non_prefix_ratio, 4
                    ),
                    "actual_prefix_cache_hit_ratio": round(hit_ratio, 4),
                    prefill_fraction_key: round(prefill_fraction, 4),
                    "latency_semantics": latency_semantics,
                },
                affected_spans=group.call_ids + group.request_ids,
                recommendation=(
                    "Evaluate whether stable instructions, tool schemas, and other shared "
                    "context can be organized into a consistent cacheable prefix."
                ),
                confidence="HIGH",
                validation_plan=[
                    "Replay the same workload after the prompt-structure change.",
                    (
                        "Compare prefix-cache hit ratio, TTFT P50/P95, prefill-path "
                        "latency, total token processing, and task quality."
                    ),
                ],
                provenance=FindingProvenance(
                    llm_call_ids=group.call_ids,
                    llm_request_ids=[
                        request.llm_request_id
                        for request in group.requests
                        if request.llm_request_id is not None
                    ],
                    serving_request_ids=group.request_ids,
                    raw_metrics={
                        "prefix_cache_hit_tokens": sum(
                            request.prefix_cache_hit_tokens or 0
                            for request in group.requests
                        ),
                        "prefix_cache_miss_tokens": sum(
                            request.prefix_cache_miss_tokens or 0
                            for request in group.requests
                        ),
                        "prefill_latency_ms": [
                            request.prefill_latency_ms for request in group.requests
                        ],
                        "prefill_path_latency_ms": [
                            prefill_or_path_latency_ms(request) for request in group.requests
                        ],
                        "ttft_ms": [request.ttft_ms for request in group.requests],
                    },
                    derived_metrics={
                        "shared_prefix_tokens": group.shared_prefix_tokens,
                        "shared_prefix_ratio": group.shared_prefix_ratio,
                        "repeated_non_prefix_tokens": group.repeated_non_prefix_tokens,
                        "repeated_non_prefix_ratio": group.repeated_non_prefix_ratio,
                        "actual_prefix_cache_hit_ratio": hit_ratio,
                        prefill_fraction_key: prefill_fraction,
                        "latency_semantics": latency_semantics,
                    },
                    notes=[
                        "Correlation is based on explicit request identifiers only.",
                        (
                            "Shared prefix is exact token/text prefix over normalized prompts; "
                            "repeated non-prefix content is evidence of theoretical cacheability "
                            "only when actual prefix-cache reuse is low."
                        ),
                        (
                            "Latency semantics are labeled as true prefill when available, "
                            "otherwise as a prefill-path proxy."
                        ),
                    ],
                ),
            )
        ]

    def _best_group(self, context: DetectorContext) -> PrefixGroup | None:
        pairs: list[tuple[LLMCall, ServingRequest, list[str]]] = []
        for call in context.run.llm_calls:
            request = context.correlation.llm_to_serving.get(call.llm_call_id)
            if request is not None:
                pairs.append((call, request, approximate_tokens(call.prompt_text())))

        if len(pairs) < self.config.min_affected_requests:
            return None

        best: PrefixGroup | None = None
        for index, (call, request, sequence) in enumerate(pairs):
            group_calls = [call]
            group_requests = [request]
            shared_prefix = len(sequence)
            for other_call, other_request, other_sequence in pairs[index + 1 :]:
                prefix = common_prefix_len(sequence, other_sequence)
                denominator = max(1, min(len(sequence), len(other_sequence)))
                ratio = prefix / denominator
                if (
                    prefix >= self.config.min_shared_prefix_tokens
                    and ratio >= self.config.min_shared_prefix_ratio
                ):
                    group_calls.append(other_call)
                    group_requests.append(other_request)
                    shared_prefix = min(shared_prefix, prefix)

            if len(group_calls) < self.config.min_affected_requests:
                continue

            input_lengths = [len(approximate_tokens(call.prompt_text())) for call in group_calls]
            avg_input = mean(input_lengths)
            ratio = shared_prefix / max(1, min(input_lengths))
            if ratio < self.config.min_shared_prefix_ratio:
                continue

            candidate = PrefixGroup(
                call_ids=[call.llm_call_id for call in group_calls],
                request_ids=[request.serving_request_id for request in group_requests],
                shared_prefix_tokens=shared_prefix,
                shared_prefix_ratio=ratio,
                repeated_non_prefix_tokens=0,
                repeated_non_prefix_ratio=0.0,
                avg_input_tokens=avg_input,
                requests=group_requests,
            )
            if best is None or (
                len(candidate.call_ids),
                candidate.shared_prefix_tokens,
            ) > (
                len(best.call_ids),
                best.shared_prefix_tokens,
            ):
                best = candidate

        non_prefix_candidate = self._non_prefix_group(pairs)
        if non_prefix_candidate is not None and (
            best is None
            or non_prefix_candidate.repeated_non_prefix_tokens
            > best.shared_prefix_tokens
        ):
            return non_prefix_candidate
        return best

    def _non_prefix_group(
        self,
        pairs: list[tuple[LLMCall, ServingRequest, list[str]]],
    ) -> PrefixGroup | None:
        calls = [call for call, _, _ in pairs]
        metrics = compute_duplication_metrics(calls)
        if metrics.repeated_non_prefix_tokens < self.config.min_shared_prefix_tokens:
            return None
        repeated_ratio = (
            metrics.repeated_non_prefix_tokens / metrics.total_input_tokens
            if metrics.total_input_tokens
            else 0.0
        )
        if repeated_ratio < self.config.min_repeated_non_prefix_ratio:
            return None

        requests = [request for _, request, _ in pairs]
        input_lengths = [len(sequence) for _, _, sequence in pairs]
        return PrefixGroup(
            call_ids=[call.llm_call_id for call in calls],
            request_ids=[request.serving_request_id for request in requests],
            shared_prefix_tokens=metrics.largest_common_prefix_tokens,
            shared_prefix_ratio=metrics.largest_common_prefix_ratio,
            repeated_non_prefix_tokens=metrics.repeated_non_prefix_tokens,
            repeated_non_prefix_ratio=repeated_ratio,
            avg_input_tokens=mean(input_lengths),
            requests=requests,
        )


def _title(group: PrefixGroup) -> str:
    if group.shared_prefix_ratio >= group.repeated_non_prefix_ratio:
        return "Large shared prefix with low prefix-cache reuse"
    return "Repeated stable content is not cacheable as a prefix"
