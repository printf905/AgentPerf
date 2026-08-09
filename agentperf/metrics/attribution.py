from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from agentperf.metrics.components import COMPONENT_ORDER, component_kind
from agentperf.metrics.tokens import call_input_tokens, token_count
from agentperf.schema.trace import AgentRun, LLMCall, PromptComponent


@dataclass(frozen=True)
class ComponentTokenAttribution:
    processed_tokens_by_component: dict[str, int]
    unique_tokens_by_component: dict[str, int]
    total_processed_tokens: int
    total_unique_tokens: int
    trace_input_tokens: int
    approximate: bool


@dataclass(frozen=True)
class ContextGrowthRow:
    step_index: int
    agent_step_id: str
    llm_call_id: str
    input_tokens: int
    history_tokens: int
    tool_result_tokens: int
    retrieved_context_tokens: int


@dataclass(frozen=True)
class ToolReinjection:
    tool_call_id: str
    tool_name: str
    raw_output_tokens: int
    reinjected_calls: list[str] = field(default_factory=list)
    cumulative_processed_tokens: int = 0
    share_of_run_input_tokens: float = 0.0


def component_token_attribution(run: AgentRun) -> ComponentTokenAttribution:
    processed: defaultdict[str, int] = defaultdict(int)
    unique_texts: defaultdict[str, set[str]] = defaultdict(set)
    trace_input_tokens = sum(call_input_tokens(call) for call in run.llm_calls)

    for call in run.llm_calls:
        for component in call.prompt_components:
            kind = component_kind(component.name)
            tokens = token_count(component.text)
            processed[kind] += tokens
            if component.text:
                unique_texts[kind].add(component.text)

    unique = {
        kind: sum(token_count(text) for text in texts)
        for kind, texts in unique_texts.items()
    }
    return ComponentTokenAttribution(
        processed_tokens_by_component=_ordered_nonzero(processed),
        unique_tokens_by_component=_ordered_nonzero(unique),
        total_processed_tokens=sum(processed.values()),
        total_unique_tokens=sum(unique.values()),
        trace_input_tokens=trace_input_tokens,
        approximate=any(call.tokenization_mode != "EXACT" for call in run.llm_calls),
    )


def context_growth_rows(run: AgentRun) -> list[ContextGrowthRow]:
    rows: list[ContextGrowthRow] = []
    step_index = 0
    for step in run.steps:
        for call in step.llm_calls:
            step_index += 1
            by_kind = _component_tokens_by_kind(call)
            rows.append(
                ContextGrowthRow(
                    step_index=step_index,
                    agent_step_id=step.agent_step_id,
                    llm_call_id=call.llm_call_id,
                    input_tokens=call_input_tokens(call),
                    history_tokens=by_kind.get("history", 0),
                    tool_result_tokens=by_kind.get("tool_result", 0),
                    retrieved_context_tokens=by_kind.get("retrieved_context", 0),
                )
            )
    return rows


def tool_reinjections(run: AgentRun) -> list[ToolReinjection]:
    tool_outputs = {
        tool.tool_call_id: (
            tool.name,
            _tool_output_tokens(tool.output),
        )
        for tool in run.tool_calls
    }
    reinjected_calls: defaultdict[str, set[str]] = defaultdict(set)
    processed_tokens: defaultdict[str, int] = defaultdict(int)

    for call in run.llm_calls:
        for component in call.prompt_components:
            source_ids = source_tool_call_ids(component)
            if not source_ids:
                continue
            tokens = token_count(component.text)
            for tool_call_id in source_ids:
                if tool_call_id not in tool_outputs:
                    continue
                reinjected_calls[tool_call_id].add(call.llm_call_id)
                processed_tokens[tool_call_id] += tokens

    total_input = sum(call_input_tokens(call) for call in run.llm_calls)
    return [
        ToolReinjection(
            tool_call_id=tool_call_id,
            tool_name=name,
            raw_output_tokens=raw_tokens,
            reinjected_calls=sorted(reinjected_calls.get(tool_call_id, set())),
            cumulative_processed_tokens=processed_tokens.get(tool_call_id, 0),
            share_of_run_input_tokens=(
                processed_tokens.get(tool_call_id, 0) / total_input if total_input else 0.0
            ),
        )
        for tool_call_id, (name, raw_tokens) in tool_outputs.items()
    ]


def source_tool_call_ids(component: PromptComponent) -> list[str]:
    raw = (
        component.metadata.get("source_tool_call_ids")
        or component.metadata.get("tool_call_ids")
        or component.metadata.get("tool_call_id")
    )
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return [str(raw)]


def _component_tokens_by_kind(call: LLMCall) -> dict[str, int]:
    tokens: defaultdict[str, int] = defaultdict(int)
    for component in call.prompt_components:
        tokens[component_kind(component.name)] += token_count(component.text)
    return dict(tokens)


def _tool_output_tokens(output: object) -> int:
    if output is None:
        return 0
    if isinstance(output, str):
        return token_count(output)
    return token_count(str(output))


def _ordered_nonzero(values: dict[str, int]) -> dict[str, int]:
    ordered: dict[str, int] = {}
    for kind in COMPONENT_ORDER:
        value = values.get(kind, 0)
        if value:
            ordered[kind] = value
    for kind, value in sorted(values.items()):
        if kind not in ordered and value:
            ordered[kind] = value
    return ordered
