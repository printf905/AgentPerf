from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from agentperf.schema.trace import LLMCall

TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def approximate_tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text)


def token_count(text: str) -> int:
    return len(approximate_tokens(text))


def call_input_tokens(call: LLMCall) -> int:
    if call.prompt_token_ids is not None:
        return len(call.prompt_token_ids)
    return call.input_tokens if call.input_tokens is not None else token_count(call.prompt_text())


def call_output_tokens(call: LLMCall) -> int:
    if call.output_token_ids is not None:
        return len(call.output_token_ids)
    return call.output_tokens if call.output_tokens is not None else 0


def common_prefix_len(left: list[str], right: list[str]) -> int:
    count = 0
    for left_token, right_token in zip(left, right, strict=False):
        if left_token != right_token:
            break
        count += 1
    return count


@dataclass(frozen=True)
class DuplicationMetrics:
    affected_call_ids: list[str]
    total_input_tokens: int
    repeated_context_tokens: int
    repeated_context_ratio: float
    largest_common_prefix_tokens: int
    largest_common_prefix_ratio: float
    repeated_non_prefix_tokens: int
    approximate: bool


def compute_duplication_metrics(calls: list[LLMCall]) -> DuplicationMetrics:
    if not calls:
        return DuplicationMetrics([], 0, 0, 0.0, 0, 0.0, 0, True)

    total_input = sum(call_input_tokens(call) for call in calls)
    approximate = any(call.tokenization_mode != "EXACT" for call in calls)

    component_counts: Counter[str] = Counter()
    component_tokens: dict[str, int] = {}
    for call in calls:
        for text in set(call.prompt_component_texts()):
            if not text:
                continue
            component_counts[text] += 1
            component_tokens[text] = token_count(text)

    repeated_context_tokens = sum(
        component_tokens[text] * (count - 1)
        for text, count in component_counts.items()
        if count > 1
    )

    sequences = [approximate_tokens(call.prompt_text()) for call in calls]
    largest_common_prefix = 0
    largest_ratio = 0.0
    affected: set[str] = set()
    for index in range(len(sequences)):
        for other_index in range(index + 1, len(sequences)):
            prefix = common_prefix_len(sequences[index], sequences[other_index])
            if prefix <= 0:
                continue
            denominator = max(1, min(len(sequences[index]), len(sequences[other_index])))
            ratio = prefix / denominator
            if prefix > largest_common_prefix:
                largest_common_prefix = prefix
                largest_ratio = ratio
            affected.add(calls[index].llm_call_id)
            affected.add(calls[other_index].llm_call_id)

    repeated_non_prefix = max(0, repeated_context_tokens - largest_common_prefix)
    ratio = repeated_context_tokens / total_input if total_input else 0.0
    return DuplicationMetrics(
        affected_call_ids=sorted(affected),
        total_input_tokens=total_input,
        repeated_context_tokens=repeated_context_tokens,
        repeated_context_ratio=ratio,
        largest_common_prefix_tokens=largest_common_prefix,
        largest_common_prefix_ratio=largest_ratio,
        repeated_non_prefix_tokens=repeated_non_prefix,
        approximate=approximate,
    )
