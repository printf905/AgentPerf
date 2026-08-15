from __future__ import annotations

from dataclasses import dataclass
from statistics import mean

from agentperf.detectors.base import DetectorContext
from agentperf.metrics.cache import prefix_cache_hit_ratio
from agentperf.metrics.latency import (
    mean_prefill_fraction,
    percentile,
    prefill_or_path_label,
    prefill_or_path_latency_ms,
)
from agentperf.metrics.tokens import (
    approximate_tokens,
    compute_duplication_metrics,
)
from agentperf.schema.findings import Finding, FindingProvenance, Severity
from agentperf.schema.trace import LLMCall, ServingRequest


@dataclass(frozen=True)
class PrefixCacheOpportunityConfig:
    min_affected_requests: int = 2
    min_shared_prefix_ratio: float = 0.60
    min_repeated_non_prefix_ratio: float = 0.50
    max_actual_cache_hit_ratio: float = 0.35
    min_prefill_fraction_of_ttft: float = 0.50
    min_shared_prefix_tokens: int = 50
    material_ttft_p95_ms: float = 100.0
    material_uncached_input_p95_tokens: int = 1000


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


@dataclass
class _PrefixNode:
    children: dict[str, _PrefixNode]
    count: int = 0
    min_length: int | None = None

    def child(self, token: str) -> _PrefixNode:
        node = self.children.get(token)
        if node is None:
            node = _PrefixNode(children={})
            self.children[token] = node
        return node


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
        ttft_values = [
            float(request.ttft_ms)
            for request in group.requests
            if request.ttft_ms is not None
        ]
        uncached_input_tokens = [
            request.prefix_cache_miss_tokens
            if request.prefix_cache_miss_tokens is not None
            else request.input_tokens
            for request in group.requests
            if request.input_tokens is not None or request.prefix_cache_miss_tokens is not None
        ]
        ttft_p95 = percentile(ttft_values, 0.95)
        uncached_p95 = percentile(
            [float(value or 0) for value in uncached_input_tokens],
            0.95,
        )
        is_material = (
            ttft_p95 is not None
            and uncached_p95 is not None
            and ttft_p95 >= self.config.material_ttft_p95_ms
            and uncached_p95 >= self.config.material_uncached_input_p95_tokens
        )
        ttft_material = (
            ttft_p95 is not None and ttft_p95 >= self.config.material_ttft_p95_ms
        )
        uncached_input_material = (
            uncached_p95 is not None
            and uncached_p95 >= self.config.material_uncached_input_p95_tokens
        )
        finding_id = (
            "MATERIAL_PREFIX_CACHE_OPPORTUNITY"
            if is_material
            else "CACHEABILITY_HEADROOM"
        )
        severity: Severity = "HIGH" if is_material else "LOW"
        recommendation = (
            "Evaluate whether stable instructions, tool schemas, and other shared "
            "context can be organized into a consistent cacheable prefix."
            if is_material
            else (
                "Treat this as cacheability headroom, not an urgent optimization. "
                "Prioritize it when both TTFT and serving uncached-token volume are "
                "material, or when independent serving-cost evidence makes it "
                "important."
            )
        )
        summary = (
            "Correlated requests contain substantial repeated stable content, but "
            "serving telemetry reports low actual prefix-cache reuse while the "
            "prefill path contributes materially to TTFT."
            if is_material
            else (
                "Correlated requests contain cacheable agent-trace structure and low "
                "serving prefix-cache reuse, but AgentPerf only labels this material "
                "when both TTFT and serving uncached-token volume cross their "
                "materiality thresholds."
            )
        )

        return [
            Finding(
                id=finding_id,
                severity=severity,
                title=_title(group),
                summary=summary,
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
                    "ttft_p95_ms": round(ttft_p95, 1) if ttft_p95 is not None else None,
                    "uncached_input_p95_tokens": (
                        round(uncached_p95) if uncached_p95 is not None else None
                    ),
                    "materiality_threshold_ttft_p95_ms": (
                        self.config.material_ttft_p95_ms
                    ),
                    "materiality_threshold_uncached_input_p95_tokens": (
                        self.config.material_uncached_input_p95_tokens
                    ),
                    "materiality_ttft_p95_met": ttft_material,
                    "materiality_uncached_input_p95_met": uncached_input_material,
                    "materiality_evaluation": {
                        "overall": "MATERIAL" if is_material else "HEADROOM",
                        "rule": (
                            "material when low cache reuse is accompanied by TTFT P95 "
                            "and serving uncached prompt P95 crossing configured thresholds"
                        ),
                        "gates": [
                            {
                                "name": "TTFT gate",
                                "observed": round(ttft_p95, 1) if ttft_p95 is not None else None,
                                "threshold": self.config.material_ttft_p95_ms,
                                "unit": "ms",
                                "result": "EXCEEDED" if ttft_material else "NOT_EXCEEDED",
                                "source_layer": "serving_backend",
                            },
                            {
                                "name": "Serving uncached prompt-volume gate",
                                "observed": (
                                    int(round(uncached_p95))
                                    if uncached_p95 is not None
                                    else None
                                ),
                                "threshold": self.config.material_uncached_input_p95_tokens,
                                "unit": "tokens",
                                "result": (
                                    "EXCEEDED" if uncached_input_material else "NOT_EXCEEDED"
                                ),
                                "source_layer": "serving_backend",
                            },
                        ],
                        "reason": (
                            "Cacheability headroom is present, but available evidence "
                            "does not establish material serving cost under the configured "
                            "TTFT and uncached-token rule."
                            if not is_material
                            else "Both materiality gates are exceeded."
                        ),
                    },
                },
                affected_spans=group.call_ids + group.request_ids,
                recommendation=recommendation,
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
                            request.prefill_path_latency_ms for request in group.requests
                        ],
                        "selected_prefill_or_path_latency_ms": [
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
                        "ttft_p95_ms": ttft_p95,
                        "uncached_input_p95_tokens": uncached_p95,
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
                        (
                            "Material prefix-cache opportunity requires low cache reuse plus "
                            "material TTFT and uncached-token evidence; otherwise AgentPerf "
                            "reports cacheability headroom."
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

        best = self._best_prefix_group(pairs)

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

    def _best_prefix_group(
        self,
        pairs: list[tuple[LLMCall, ServingRequest, list[str]]],
    ) -> PrefixGroup | None:
        candidate = self._best_prefix_candidate_from_trie(pairs)
        if candidate is None:
            return None
        prefix_tokens, shared_prefix, ratio = candidate
        group = [
            (call, request, sequence)
            for call, request, sequence in pairs
            if sequence[:shared_prefix] == prefix_tokens
        ]
        if len(group) < self.config.min_affected_requests:
            return None
        return PrefixGroup(
            call_ids=[call.llm_call_id for call, _, _ in group],
            request_ids=[request.serving_request_id for _, request, _ in group],
            shared_prefix_tokens=shared_prefix,
            shared_prefix_ratio=ratio,
            repeated_non_prefix_tokens=0,
            repeated_non_prefix_ratio=0.0,
            avg_input_tokens=mean(len(sequence) for _, _, sequence in group),
            requests=[request for _, request, _ in group],
        )

    def _best_prefix_candidate_from_trie(
        self,
        pairs: list[tuple[LLMCall, ServingRequest, list[str]]],
    ) -> tuple[list[str], int, float] | None:
        root = _PrefixNode(children={})
        for _, _, sequence in pairs:
            node = root
            sequence_len = len(sequence)
            for token in sequence:
                node = node.child(token)
                node.count += 1
                node.min_length = (
                    sequence_len
                    if node.min_length is None
                    else min(node.min_length, sequence_len)
                )

        best_tokens: list[str] | None = None
        best_count = 0
        best_prefix_len = 0
        best_ratio = 0.0
        stack: list[tuple[_PrefixNode, list[str]]] = [
            (child, [token]) for token, child in root.children.items()
        ]
        while stack:
            node, tokens = stack.pop()
            prefix_len = len(tokens)
            min_length = node.min_length or 0
            ratio = prefix_len / max(1, min_length)
            if (
                node.count >= self.config.min_affected_requests
                and prefix_len >= self.config.min_shared_prefix_tokens
                and ratio >= self.config.min_shared_prefix_ratio
                and (node.count, prefix_len) > (best_count, best_prefix_len)
            ):
                best_tokens = tokens
                best_count = node.count
                best_prefix_len = prefix_len
                best_ratio = ratio
            for token, child in node.children.items():
                stack.append((child, [*tokens, token]))

        if best_tokens is None:
            return None
        return best_tokens, best_prefix_len, best_ratio


def _title(group: PrefixGroup) -> str:
    if group.shared_prefix_ratio >= group.repeated_non_prefix_ratio:
        return "Large shared prefix with low prefix-cache reuse"
    return "Repeated stable content is not cacheable as a prefix"
