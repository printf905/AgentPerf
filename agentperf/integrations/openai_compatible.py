from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from agentperf.schema.trace import AgentRun


class OpenAICompatibleRequestRecorder:
    """Capture OpenAI-compatible HTTP responses without changing model behavior."""

    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    async def capture_response(self, response: Any) -> None:
        url = str(getattr(getattr(response, "request", None), "url", ""))
        if "/chat/completions" not in url and "/completions" not in url:
            return

        await response.aread()
        request_body = _json_body(getattr(getattr(response, "request", None), "content", b""))
        response_body = _json_body(getattr(response, "content", b""))
        request_id = _optional_str(request_body.get("request_id"))
        response_id = _optional_str(response_body.get("id"))
        if request_id is None and response_id is None:
            return

        self.records.append(
            {
                "client_request_id": request_id or response_id,
                "request_id": response_id or request_id,
                "response": response_body,
                "metadata": {
                    "openai_compatible_path": url,
                    "http_status_code": getattr(response, "status_code", None),
                    "traceparent": _optional_str(
                        getattr(getattr(response, "request", None), "headers", {}).get(
                            "traceparent"
                        )
                    ),
                },
            }
        )

    def http_client(self, **kwargs: Any) -> Any:
        import httpx

        return httpx.AsyncClient(event_hooks={"response": [self.capture_response]}, **kwargs)


def build_vllm_recording_from_agent_run(
    *,
    agent_run: AgentRun,
    captured_records: list[dict[str, Any]],
    model: str,
    environment: dict[str, Any],
) -> dict[str, Any]:
    """Join AgentPerf agent spans to captured serving responses by explicit request ID."""

    captured_by_request_id = {
        str(record["client_request_id"]): record
        for record in captured_records
        if record.get("client_request_id") is not None
    }
    records: list[dict[str, Any]] = []
    missing_request_ids: list[str] = []
    for call in agent_run.llm_calls:
        if call.llm_request_id is None:
            missing_request_ids.append(call.llm_call_id)
            continue
        captured = captured_by_request_id.get(call.llm_request_id)
        if captured is None:
            missing_request_ids.append(call.llm_request_id)
            continue
        records.append(
            {
                **captured,
                "llm_call_id": call.llm_call_id,
                "agent_step_id": call.agent_step_id,
                "trace_id": call.trace_id,
                "span_id": call.span_id,
                "parent_span_id": call.parent_span_id,
                "model": call.model or model,
                "prompt_components": [asdict(component) for component in call.prompt_components],
                "metadata": {
                    **dict(captured.get("metadata") or {}),
                    "agent_span_id": call.span_id,
                    "agent_step_id": call.agent_step_id,
                    "explicit_request_correlation": True,
                },
            }
        )

    return {
        "agent_run_id": agent_run.agent_run_id,
        "name": agent_run.name or "OpenAI Agents SDK + vLLM cross-layer run",
        "model": model,
        "environment": {
            **environment,
            "correlation_mechanism": "explicit_request_id_body",
            "missing_correlations": missing_request_ids,
        },
        "records": records,
        "tool_calls": [asdict(tool_call) for tool_call in agent_run.tool_calls],
    }


def correlation_summary(recording: dict[str, Any], expected_llm_calls: int) -> dict[str, Any]:
    records = [record for record in recording.get("records", []) if isinstance(record, dict)]
    correlated = sum(
        1
        for record in records
        if record.get("client_request_id")
        and record.get("request_id")
        and record.get("llm_call_id")
    )
    missing = list(
        item
        for item in (recording.get("environment", {}) or {}).get("missing_correlations", [])
    )
    return {
        "expected_llm_calls": expected_llm_calls,
        "correlated_serving_requests": correlated,
        "missing_correlations": missing,
        "correlation_success_rate": (
            correlated / expected_llm_calls if expected_llm_calls else 0.0
        ),
    }


def _json_body(content: Any) -> dict[str, Any]:
    if not content:
        return {}
    if isinstance(content, str):
        text = content
    elif isinstance(content, bytes | bytearray):
        text = bytes(content).decode("utf-8", errors="replace")
    else:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)
