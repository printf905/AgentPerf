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


def test_real_agent_runner_mock_context_strategies(tmp_path) -> None:  # type: ignore[no-untyped-def]
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
    strategies = comparison["strategies"]
    baseline = strategies["raw_full"]
    aggressive = strategies["aggressive_compact"]
    top_k = strategies["top_k_2"]

    assert code == 0
    assert baseline["llm_calls"] == 30
    assert baseline["tool_calls"] == 20
    assert baseline["processed_tokens_by_component"]["tool_result"] > aggressive[
        "processed_tokens_by_component"
    ]["tool_result"]
    assert baseline["processed_tokens_by_component"]["tool_result"] > top_k[
        "processed_tokens_by_component"
    ]["tool_result"]
    assert "TOOL_OUTPUT_BLOAT" in baseline["detectors_fired"]
    assert "TOOL_OUTPUT_BLOAT" not in aggressive["detectors_fired"]
    assert baseline["correctness"]["mean_score"] == aggressive["correctness"]["mean_score"]
    assert comparison["pareto"]
    quality_constraint = comparison["quality_constraint"]
    assert quality_constraint["baseline_strategy"] == "raw_full"
    assert quality_constraint["mean_score_tolerance"] == 0.05
    assert quality_constraint["pass_rate_tolerance"] == 0.10
    assert quality_constraint["selected_strategy"] is not None
    assert quality_constraint["eligible_strategies"]

    raw_recording = json.loads(
        (output_dir / "top_k_2" / "raw" / "recording.json").read_text(
            encoding="utf-8"
        )
    )
    metadata = next(
        component["metadata"]
        for record in raw_recording["records"]
        for component in record["prompt_components"]
        if component["name"] == "tool_results"
    )
    assert metadata["carry_strategy"] == "top_k_2"
    assert metadata["evidence_items"][0]["source_document_id"]
    assert metadata["evidence_items"][0]["passage_id"]
    assert metadata["evidence_items"][0]["retrieval_score"] >= 0
    assert metadata["original_token_count"] >= metadata["carried_forward_token_count"]
