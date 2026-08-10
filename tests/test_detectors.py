from __future__ import annotations

from pathlib import Path

from agentperf.analyzer import analyze_path, analyze_run
from agentperf.correlation.correlator import TraceCorrelator
from agentperf.detectors.base import DetectorContext
from agentperf.detectors.context_duplication import ContextDuplicationDetector
from agentperf.detectors.prefix_cache import PrefixCacheOpportunityDetector
from agentperf.schema.trace import AgentRun, parse_agentperf_trace

ROOT = Path(__file__).resolve().parents[1]


def ids(path: str) -> list[str]:
    return [finding.id for finding in analyze_path(ROOT / path).findings]


def test_context_duplication_detector() -> None:
    report = analyze_path(ROOT / "examples/traces/context_duplication.json")
    findings = [finding.id for finding in report.findings]

    assert findings == ["CONTEXT_DUPLICATION"]
    assert report.findings[0].evidence["materiality"] == "OBSERVATION"
    assert report.findings[0].severity == "LOW"


def test_prefix_cache_opportunity_detector() -> None:
    findings = ids("examples/traces/prefix_cache_failure.json")

    assert "CACHEABILITY_HEADROOM" in findings
    assert "PREFILL_PATH_DOMINANCE" in findings


def test_prefill_bottleneck_detector() -> None:
    findings = ids("examples/traces/prefill_bottleneck.json")

    assert findings == ["MATERIAL_PREFILL_BOTTLENECK"]


def test_cross_detector_interaction_on_multi_problem_trace() -> None:
    report = analyze_path(ROOT / "examples/traces/multi_problem_agent.json")

    assert [finding.id for finding in report.findings] == [
        "CONTEXT_DUPLICATION",
        "CACHEABILITY_HEADROOM",
        "PREFILL_PATH_DOMINANCE",
    ]
    prefix = next(
        finding
        for finding in report.findings
        if finding.id == "CACHEABILITY_HEADROOM"
    )
    assert prefix.evidence["affected_requests"] == 3


def test_healthy_workload_produces_no_findings() -> None:
    assert ids("examples/traces/healthy_agent.json") == []


def test_large_context_with_healthy_cache_is_false_positive_control() -> None:
    assert ids("examples/traces/large_context_cache_healthy.json") == []


def test_missing_serving_telemetry_does_not_crash() -> None:
    report = analyze_path(ROOT / "examples/traces/context_duplication.json")

    assert report.correlation.llm_to_serving == {}
    assert [finding.id for finding in report.findings] == ["CONTEXT_DUPLICATION"]


def test_uncorrelated_serving_spans_do_not_create_prefix_cache_finding() -> None:
    run = parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "run-1",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "llm_request_id": "req-a",
                                "prompt": {"system": _prompt(80), "user": "one"},
                            },
                            {
                                "llm_call_id": "llm-2",
                                "llm_request_id": "req-b",
                                "prompt": {"system": _prompt(80), "user": "two"},
                            },
                        ],
                    }
                ],
            },
            "serving_requests": [
                _serving("srv-1", "req-x", hit=10, miss=500),
                _serving("srv-2", "req-y", hit=10, miss=500),
            ],
        }
    )
    context = DetectorContext(run=run, correlation=TraceCorrelator().correlate(run))

    assert PrefixCacheOpportunityDetector().detect(context) == []


def test_prefix_boundary_59_percent_does_not_fire() -> None:
    run = _boundary_run(shared_tokens=59, total_tokens=100)

    assert "MATERIAL_PREFIX_CACHE_OPPORTUNITY" not in [
        finding.id for finding in analyze_run(run).findings
    ]


def test_prefix_boundary_61_percent_fires() -> None:
    run = _boundary_run(shared_tokens=61, total_tokens=100)

    assert "CACHEABILITY_HEADROOM" in [
        finding.id for finding in analyze_run(run).findings
    ]


def test_repeated_non_prefix_content_can_create_prefix_cache_opportunity() -> None:
    run = _dynamic_prefix_run(hit=0, miss=8200, ttft=260)
    report = analyze_run(run)

    prefix = next(
        finding
        for finding in report.findings
        if finding.id == "MATERIAL_PREFIX_CACHE_OPPORTUNITY"
    )
    assert prefix.evidence["shared_prefix_tokens"] < 5
    assert prefix.evidence["repeated_non_prefix_tokens"] > 8000
    assert prefix.evidence["actual_prefix_cache_hit_ratio"] == 0.0


def test_repeated_non_prefix_content_is_not_treated_as_cached_tokens() -> None:
    run = _dynamic_prefix_run(hit=0, miss=8200, ttft=260)
    report = analyze_run(run)
    prefix = next(
        finding
        for finding in report.findings
        if finding.id == "MATERIAL_PREFIX_CACHE_OPPORTUNITY"
    )

    assert prefix.provenance.raw_metrics["prefix_cache_hit_tokens"] == 0


def test_low_absolute_prefill_path_dominance_is_not_material_bottleneck() -> None:
    run = _dynamic_prefix_run(hit=8000, miss=120, ttft=16, queue=0)
    findings = analyze_run(run).findings

    assert "MATERIAL_PREFILL_BOTTLENECK" not in [finding.id for finding in findings]
    dominance = next(
        finding for finding in findings if finding.id == "PREFILL_PATH_DOMINANCE"
    )
    assert dominance.severity == "LOW"
    assert dominance.evidence["ttft_p95_ms"] == 16.0


def test_low_absolute_prefix_cache_signal_is_headroom_not_material() -> None:
    run = _dynamic_prefix_run(hit=0, miss=8200, ttft=18, queue=0)
    findings = analyze_run(run).findings

    assert "MATERIAL_PREFIX_CACHE_OPPORTUNITY" not in [
        finding.id for finding in findings
    ]
    headroom = next(
        finding for finding in findings if finding.id == "CACHEABILITY_HEADROOM"
    )
    assert headroom.severity == "LOW"
    assert headroom.evidence["ttft_p95_ms"] == 18.0


def test_context_duplication_boundary_is_intentional() -> None:
    run = parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "run-1",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "prompt": {"system": _prompt(20), "user": "a"},
                            },
                            {
                                "llm_call_id": "llm-2",
                                "prompt": {"system": _prompt(20), "user": "b"},
                            },
                            {
                                "llm_call_id": "llm-3",
                                "prompt": {"system": _prompt(20), "user": "c"},
                            },
                        ],
                    }
                ],
            }
        }
    )
    context = DetectorContext(run=run, correlation=TraceCorrelator().correlate(run))

    assert ContextDuplicationDetector().detect(context) == []


def _boundary_run(shared_tokens: int, total_tokens: int) -> AgentRun:
    shared = _prompt(shared_tokens)
    unique_count = total_tokens - shared_tokens
    return parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": f"boundary-{shared_tokens}",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "llm_request_id": "req-1",
                                "serving_request_id": "srv-1",
                                "prompt": {
                                    "system": shared,
                                    "user": _prompt(unique_count, prefix="a"),
                                },
                            },
                            {
                                "llm_call_id": "llm-2",
                                "llm_request_id": "req-2",
                                "serving_request_id": "srv-2",
                                "prompt": {
                                    "system": shared,
                                    "user": _prompt(unique_count, prefix="b"),
                                },
                            },
                        ],
                    }
                ],
            },
            "serving_requests": [
                _serving("srv-1", "req-1", hit=20, miss=480),
                _serving("srv-2", "req-2", hit=20, miss=480),
            ],
        }
    )


def _dynamic_prefix_run(
    *,
    hit: int,
    miss: int,
    ttft: float,
    queue: float = 20,
) -> AgentRun:
    stable = _prompt(8200, prefix="stable")
    return parse_agentperf_trace(
        {
            "agent_run": {
                "agent_run_id": "dynamic-prefix-real-semantics",
                "steps": [
                    {
                        "agent_step_id": "step-1",
                        "llm_calls": [
                            {
                                "llm_call_id": "llm-1",
                                "llm_request_id": "req-1",
                                "serving_request_id": "srv-1",
                                "prompt": [
                                    {"name": "dynamic_request", "text": "case alpha"},
                                    {"name": "stable_context", "text": stable},
                                ],
                            },
                            {
                                "llm_call_id": "llm-2",
                                "llm_request_id": "req-2",
                                "serving_request_id": "srv-2",
                                "prompt": [
                                    {"name": "dynamic_request", "text": "case beta"},
                                    {"name": "stable_context", "text": stable},
                                ],
                            },
                            {
                                "llm_call_id": "llm-3",
                                "llm_request_id": "req-3",
                                "serving_request_id": "srv-3",
                                "prompt": [
                                    {"name": "dynamic_request", "text": "case gamma"},
                                    {"name": "stable_context", "text": stable},
                                ],
                            },
                        ],
                    }
                ],
            },
            "serving_requests": [
                _serving("srv-1", "req-1", hit=hit, miss=miss, ttft=ttft, queue=queue),
                _serving("srv-2", "req-2", hit=hit, miss=miss, ttft=ttft, queue=queue),
                _serving("srv-3", "req-3", hit=hit, miss=miss, ttft=ttft, queue=queue),
            ],
        }
    )


def _serving(
    serving_id: str,
    request_id: str,
    hit: int,
    miss: int,
    ttft: float = 900,
    queue: float = 20,
) -> dict[str, object]:
    return {
        "serving_request_id": serving_id,
        "llm_request_id": request_id,
        "queue_latency_ms": queue,
        "prefill_latency_ms": ttft,
        "decode_latency_ms": 120,
        "ttft_ms": ttft,
        "input_tokens": hit + miss,
        "output_tokens": 80,
        "prefix_cache_hit_tokens": hit,
        "prefix_cache_miss_tokens": miss,
    }


def _prompt(count: int, prefix: str = "s") -> str:
    return " ".join(f"{prefix}{index}" for index in range(count))
