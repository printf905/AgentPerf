from __future__ import annotations

COMPONENT_ORDER = (
    "system",
    "user",
    "history",
    "tool_schema",
    "tool_result",
    "retrieved_context",
    "other",
)


def component_kind(name: str) -> str:
    normalized = name.lower().replace("-", "_")
    if normalized in {"system", "system_instructions", "instructions"}:
        return "system"
    if normalized in {"user", "task", "dynamic_request"}:
        return "user"
    if normalized in {"history", "conversation_history", "memory"}:
        return "history"
    if normalized in {"tool_schema", "tool_schemas", "tools"}:
        return "tool_schema"
    if normalized in {"tool_result", "tool_results", "observation", "observations"}:
        return "tool_result"
    if normalized in {"retrieved_context", "retrieval", "search_results"}:
        return "retrieved_context"
    return "other"
