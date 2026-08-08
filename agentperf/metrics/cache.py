from __future__ import annotations

from agentperf.schema.trace import ServingRequest


def prefix_cache_hit_ratio(requests: list[ServingRequest]) -> float | None:
    hits = sum(request.prefix_cache_hit_tokens or 0 for request in requests)
    misses = sum(request.prefix_cache_miss_tokens or 0 for request in requests)
    total = hits + misses
    if total == 0:
        return None
    return hits / total


def request_prefix_cache_hit_ratio(request: ServingRequest) -> float | None:
    hits = request.prefix_cache_hit_tokens or 0
    misses = request.prefix_cache_miss_tokens or 0
    total = hits + misses
    if total == 0:
        return None
    return hits / total

