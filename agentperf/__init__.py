"""AgentPerf cross-layer profiler."""

from agentperf.artifacts import ExperimentArtifact, load_artifact
from agentperf.benchmark_suites import BenchmarkSuite, check_suite, load_suite, validate_suite
from agentperf.comparison import compare_paths, compare_workloads
from agentperf.experiments import ExperimentSession, QualityResult
from agentperf.instrumentation import (
    TraceRecorder,
    current_recorder,
    record_handoff,
    trace_llm,
    trace_run,
    trace_tool,
)
from agentperf.regression import evaluate_regression_policy, load_regression_policy

__version__ = "0.4.0"

__all__ = [
    "ExperimentArtifact",
    "ExperimentSession",
    "QualityResult",
    "BenchmarkSuite",
    "TraceRecorder",
    "__version__",
    "check_suite",
    "compare_paths",
    "compare_workloads",
    "current_recorder",
    "evaluate_regression_policy",
    "load_artifact",
    "load_suite",
    "load_regression_policy",
    "record_handoff",
    "trace_run",
    "trace_llm",
    "trace_tool",
    "validate_suite",
]
