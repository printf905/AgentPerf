"""AgentPerf cross-layer profiler MVP."""

from agentperf.comparison import compare_paths, compare_workloads
from agentperf.instrumentation import TraceRecorder, current_recorder, trace_run, trace_tool

__version__ = "0.2.0"

__all__ = [
    "TraceRecorder",
    "__version__",
    "compare_paths",
    "compare_workloads",
    "current_recorder",
    "trace_run",
    "trace_tool",
]
