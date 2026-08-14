from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass

from agentperf.metrics.components import component_kind
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
    repeated_tokens_by_component: dict[str, int]
    approximate: bool


def compute_duplication_metrics(calls: list[LLMCall]) -> DuplicationMetrics:
    if not calls:
        return DuplicationMetrics([], 0, 0, 0.0, 0, 0.0, 0, {}, True)

    total_input = sum(call_input_tokens(call) for call in calls)
    approximate = any(call.tokenization_mode != "EXACT" for call in calls)

    component_counts: Counter[str] = Counter()
    component_tokens: dict[str, int] = {}
    component_kinds: dict[str, str] = {}
    for call in calls:
        seen_texts: set[str] = set()
        for component in call.prompt_components:
            text = component.text
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            component_counts[text] += 1
            component_tokens[text] = token_count(text)
            component_kinds[text] = component_kind(component.name)

    repeated_context_tokens = sum(
        component_tokens[text] * (count - 1)
        for text, count in component_counts.items()
        if count > 1
    )
    repeated_by_component: defaultdict[str, int] = defaultdict(int)
    for text, count in component_counts.items():
        if count > 1:
            repeated_by_component[component_kinds[text]] += component_tokens[text] * (
                count - 1
            )

    sequences = [
        (call.llm_call_id, approximate_tokens(call.prompt_text()))
        for call in calls
    ]
    largest_common_prefix = 0
    largest_ratio = 0.0
    affected: set[str] = set()
    by_first_token: defaultdict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for call_id, sequence in sequences:
        if sequence:
            by_first_token[sequence[0]].append((call_id, sequence))

    for group in by_first_token.values():
        if len(group) < 2:
            continue
        affected.update(call_id for call_id, _ in group)
        ordered = sorted(group, key=lambda item: item[1])
        for (_, sequence), (_, other_sequence) in zip(ordered, ordered[1:], strict=False):
            prefix = common_prefix_len(sequence, other_sequence)
            if prefix <= 0:
                continue
            denominator = max(1, min(len(sequence), len(other_sequence)))
            ratio = prefix / denominator
            if prefix > largest_common_prefix:
                largest_common_prefix = prefix
                largest_ratio = ratio

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
        repeated_tokens_by_component=dict(sorted(repeated_by_component.items())),
        approximate=approximate,
    )
