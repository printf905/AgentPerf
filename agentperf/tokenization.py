from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentperf.metrics.tokens import approximate_tokens
from agentperf.schema.trace import TokenizationMode


@dataclass(frozen=True)
class TokenizedText:
    token_ids: list[int] | None
    tokens: list[str]
    mode: TokenizationMode

    @property
    def count(self) -> int:
        if self.token_ids is not None:
            return len(self.token_ids)
        return len(self.tokens)


class TokenizerProvider(Protocol):
    def tokenize(self, text: str) -> TokenizedText:
        ...


class ApproximateTokenizerProvider:
    def tokenize(self, text: str) -> TokenizedText:
        return TokenizedText(token_ids=None, tokens=approximate_tokens(text), mode="APPROXIMATE")


class ExactTokenIdsProvider:
    def __init__(self, token_ids_by_text: dict[str, list[int]] | None = None) -> None:
        self._token_ids_by_text = token_ids_by_text or {}

    def tokenize(self, text: str) -> TokenizedText:
        token_ids = self._token_ids_by_text.get(text)
        if token_ids is None:
            return ApproximateTokenizerProvider().tokenize(text)
        return TokenizedText(token_ids=token_ids, tokens=[], mode="EXACT")

