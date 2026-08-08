from __future__ import annotations

from dataclasses import dataclass, field

from agentperf.schema.trace import AgentRun, LLMCall, ServingRequest


@dataclass(frozen=True)
class CorrelationResult:
    llm_to_serving: dict[str, ServingRequest] = field(default_factory=dict)
    unresolved_llm_calls: list[LLMCall] = field(default_factory=list)
    unresolved_serving_requests: list[ServingRequest] = field(default_factory=list)


class TraceCorrelator:
    """Correlates only by explicit propagated identifiers."""

    def correlate(self, run: AgentRun) -> CorrelationResult:
        by_serving_id = {request.serving_request_id: request for request in run.serving_requests}
        by_llm_request_id = {
            request.llm_request_id: request
            for request in run.serving_requests
            if request.llm_request_id is not None
        }

        llm_to_serving: dict[str, ServingRequest] = {}
        used_serving_ids: set[str] = set()
        unresolved_llm: list[LLMCall] = []

        for call in run.llm_calls:
            request = None
            if call.serving_request_id:
                request = by_serving_id.get(call.serving_request_id)
            if request is None and call.llm_request_id:
                request = by_llm_request_id.get(call.llm_request_id)

            if request is None:
                unresolved_llm.append(call)
            else:
                llm_to_serving[call.llm_call_id] = request
                used_serving_ids.add(request.serving_request_id)

        unresolved_serving = [
            request
            for request in run.serving_requests
            if request.serving_request_id not in used_serving_ids
        ]
        return CorrelationResult(
            llm_to_serving=llm_to_serving,
            unresolved_llm_calls=unresolved_llm,
            unresolved_serving_requests=unresolved_serving,
        )

