from __future__ import annotations

from dataclasses import dataclass, field

from agentperf.schema.findings import Finding


@dataclass(frozen=True)
class InvestigationEvidence:
    label: str
    value: str
    relationship: str
    strength: str


@dataclass(frozen=True)
class Investigation:
    id: str
    title: str
    summary: str
    facts: list[InvestigationEvidence] = field(default_factory=list)
    interpretation: list[str] = field(default_factory=list)
    assessment: str = ""
    recommended_experiment: list[str] = field(default_factory=list)
    related_finding_ids: list[str] = field(default_factory=list)


def build_investigations(findings: list[Finding]) -> list[Investigation]:
    by_id = {finding.id: finding for finding in findings}
    investigations: list[Investigation] = []
    repeated = by_id.get("CONTEXT_DUPLICATION")
    cache = by_id.get("CACHEABILITY_HEADROOM") or by_id.get("MATERIAL_PREFIX_CACHE_OPPORTUNITY")
    prefill = by_id.get("PREFILL_PATH_DOMINANCE") or by_id.get("MATERIAL_PREFILL_BOTTLENECK")
    if repeated and cache and prefill:
        investigations.append(_context_cache_investigation(repeated, cache, prefill))
    return investigations


def _context_cache_investigation(
    repeated: Finding,
    cache: Finding,
    prefill: Finding,
) -> Investigation:
    cache_material = cache.id == "MATERIAL_PREFIX_CACHE_OPPORTUNITY"
    prefill_material = prefill.id == "MATERIAL_PREFILL_BOTTLENECK"
    facts = [
        InvestigationEvidence(
            label="Repeated agent context",
            value=_tokens_ratio(
                repeated.evidence.get("repeated_context_tokens"),
                repeated.evidence.get("repeated_context_ratio"),
            ),
            relationship="upstream_signal",
            strength="observed",
        ),
        InvestigationEvidence(
            label="Repeated component",
            value=_largest_component(repeated.evidence.get("repeated_tokens_by_component")),
            relationship="agent_evidence",
            strength="observed",
        ),
        InvestigationEvidence(
            label="Shared prefix structure",
            value=_ratio(cache.evidence.get("shared_prefix_ratio")),
            relationship="prompt_structure_evidence",
            strength="observed",
        ),
        InvestigationEvidence(
            label="Observed prefix-cache reuse",
            value=_ratio(cache.evidence.get("actual_prefix_cache_hit_ratio")),
            relationship="serving_evidence",
            strength="observed",
        ),
        InvestigationEvidence(
            label="TTFT attributed to prefill path",
            value=_ratio(
                prefill.evidence.get("prefill_fraction_of_ttft_avg")
                or prefill.evidence.get("prefill_path_proxy_fraction_of_ttft_avg")
            ),
            relationship="latency_attribution",
            strength="observed",
        ),
        InvestigationEvidence(
            label="Serving uncached prompt P95",
            value=f"{prefill.evidence.get('p95_uncached_input_tokens', 'unknown')} tokens",
            relationship="materiality_gate",
            strength=(
                "exceeded"
                if prefill.evidence.get("materiality_uncached_input_p95_met") is True
                else "not_exceeded"
            ),
        ),
    ]
    interpretation = [
        "These findings are related evidence, not a causal proof.",
        "Repeated agent context and shared-prefix structure can create cacheability headroom.",
        "Serving telemetry is needed to decide whether that headroom is operationally material.",
    ]
    if cache_material and prefill_material:
        assessment = (
            "Context/cache evidence and serving materiality gates indicate a material "
            "bottleneck."
        )
    elif cache_material or prefill_material:
        assessment = (
            "Some materiality evidence is present, but review each finding's gates before "
            "treating the chain as a proven bottleneck."
        )
    else:
        assessment = (
            "Cacheability and prefill-path headroom are observed, but a context-driven "
            "operational bottleneck is not proven under current materiality rules."
        )
    return Investigation(
        id="repeated_context_cacheability",
        title="Repeated static context and cacheability",
        summary=(
            "Agent-level repeated context, shared prompt-prefix structure, serving cache "
            "reuse, and first-token-path evidence are part of one investigation."
        ),
        facts=facts,
        interpretation=interpretation,
        assessment=assessment,
        recommended_experiment=[
            (
                "Preserve semantic content while restructuring stable prompt context "
                "into a consistent prefix."
            ),
            "Replay the same workload.",
            "Compare prefix-cache hit ratio, TTFT, processed tokens, and task quality.",
        ],
        related_finding_ids=[repeated.id, cache.id, prefill.id],
    )


def _tokens_ratio(tokens: object, ratio: object) -> str:
    text = f"{tokens} tokens" if tokens is not None else "unknown tokens"
    if isinstance(ratio, int | float):
        text += f" ({float(ratio):.1%})"
    return text


def _ratio(value: object) -> str:
    if isinstance(value, int | float):
        return f"{float(value):.1%}"
    return "unknown"


def _largest_component(value: object) -> str:
    if not isinstance(value, dict) or not value:
        return "unknown"
    component, tokens = max(value.items(), key=lambda item: int(item[1]))
    return f"{component}: {tokens} tokens"
