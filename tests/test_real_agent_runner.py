from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_main() -> Callable[[list[str]], int]:
    spec = importlib.util.spec_from_file_location(
        "run_real_agent_context_waste",
        ROOT / "scripts" / "run_real_agent_context_waste.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_real_agent_context_waste"] = module
    spec.loader.exec_module(module)
    return module.main  # type: ignore[no-any-return]


def test_real_agent_runner_mock_baseline_and_optimized(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_dir = tmp_path / "agent"
    main = _load_main()

    code = main(
        [
            "--model",
            "mock-agent",
            "--mock-llm",
            "--output-dir",
            str(output_dir),
        ]
    )

    comparison = json.loads((output_dir / "comparison.json").read_text(encoding="utf-8"))
    baseline = comparison["baseline"]
    optimized = comparison["optimized"]

    assert code == 0
    assert baseline["llm_calls"] == 30
    assert baseline["tool_calls"] == 20
    assert baseline["processed_tokens_by_component"]["tool_result"] > optimized[
        "processed_tokens_by_component"
    ]["tool_result"]
    assert "TOOL_OUTPUT_BLOAT" in baseline["detectors_fired"]
    assert "TOOL_OUTPUT_BLOAT" not in optimized["detectors_fired"]
    assert baseline["correctness"]["mean_score"] == optimized["correctness"]["mean_score"]
