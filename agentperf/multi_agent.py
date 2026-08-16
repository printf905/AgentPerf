from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agentperf.metrics.components import COMPONENT_ORDER, component_kind
from agentperf.metrics.tokens import call_input_tokens, token_count
from agentperf.schema.trace import AgentRun, AgentStep, parse_datetime

MULTI_AGENT_KEYS = {
    "agent_id",
    "agent_role",
    "parent_agent_id",
    "branch_id",
    "parent_branch_id",
    "branch_event",
    "handoff_from",
    "handoff_to",
}


@dataclass
class AgentAttribution:
    agent_id: str
    role: str | None = None
    parent_agent_ids: set[str] = field(default_factory=set)
    llm_calls: int = 0
    tool_calls: int = 0
    provider_input_tokens: int = 0
    provider_output_tokens: int = 0
    component_processed_tokens: int = 0
    work_duration_ms: float = 0.0
    branch_ids: set[str] = field(default_factory=set)
    finding_ids: set[str] = field(default_factory=set)


@dataclass
class BranchAttribution:
    branch_id: str
    parent_branch_id: str | None = None
    agent_id: str | None = None
    branch_event: str | None = None
    llm_calls: int = 0
    tool_calls: int = 0
    provider_input_tokens: int = 0
    provider_output_tokens: int = 0
    component_processed_tokens: int = 0
    work_duration_ms: float = 0.0
    elapsed_ms: float | None = None
    _started: list[Any] = field(default_factory=list, repr=False)
    _ended: list[Any] = field(default_factory=list, repr=False)


@dataclass
class HandoffAttribution:
    from_agent_id: str
    to_agent_id: str
    branch_id: str | None = None
    parent_branch_id: str | None = None
    context_tokens: int | None = None
    component_tokens: dict[str, int] = field(default_factory=dict)
    downstream_provider_input_tokens: int = 0


@dataclass
class FanoutAttribution:
    parent_branch_id: str
    branch_ids: list[str]
    work_duration_ms: float
    critical_path_ms: float | None


@dataclass
class MultiAgentProfile:
    has_metadata: bool
    agents: list[AgentAttribution]
    branches: list[BranchAttribution]
    handoffs: list[HandoffAttribution]
    fanouts: list[FanoutAttribution]


def profile_runs(runs: list[AgentRun]) -> MultiAgentProfile:
    agents: dict[str, AgentAttribution] = {}
    branches: dict[str, BranchAttribution] = {}
    handoffs: list[HandoffAttribution] = []
    has_metadata = False

    for run in runs:
        run_agent_id = _metadata_str(run.metadata, "agent_id")
        run_role = _metadata_str(run.metadata, "agent_role")
        if run_agent_id is not None:
            agent = agents.setdefault(run_agent_id, AgentAttribution(agent_id=run_agent_id))
            if agent.role is None and run_role is not None:
                agent.role = run_role
        for step in run.steps:
            if MULTI_AGENT_KEYS & set(step.metadata):
                has_metadata = True
            agent_id = _metadata_str(step.metadata, "agent_id") or run_agent_id
            agent_role = _metadata_str(step.metadata, "agent_role")
            if agent_role is None and agent_id == run_agent_id:
                agent_role = run_role
            branch_id = _metadata_str(step.metadata, "branch_id")
            parent_branch_id = _metadata_str(step.metadata, "parent_branch_id")
            parent_agent_id = _metadata_str(step.metadata, "parent_agent_id")
            branch_event = _metadata_str(step.metadata, "branch_event")

            if agent_id is not None:
                agent = agents.setdefault(agent_id, AgentAttribution(agent_id=agent_id))
                if agent.role is None and agent_role is not None:
                    agent.role = agent_role
                if parent_agent_id is not None and parent_agent_id != agent_id:
                    agent.parent_agent_ids.add(parent_agent_id)
                if branch_id is not None:
                    agent.branch_ids.add(branch_id)

            branch = None
            if branch_id is not None:
                branch = branches.setdefault(
                    branch_id,
                    BranchAttribution(
                        branch_id=branch_id,
                        parent_branch_id=parent_branch_id,
                        agent_id=agent_id,
                        branch_event=branch_event,
                    ),
                )
                if branch.parent_branch_id is None and parent_branch_id is not None:
                    branch.parent_branch_id = parent_branch_id
                if branch.agent_id is None and agent_id is not None:
                    branch.agent_id = agent_id
                if branch.branch_event is None and branch_event is not None:
                    branch.branch_event = branch_event
                _add_step_bounds(branch, step)

            step_metrics = _step_metrics(step)
            if agent_id is not None:
                _add_metrics_to_agent(agents[agent_id], step_metrics)
            if branch is not None:
                _add_metrics_to_branch(branch, step_metrics)

            if "handoff_from" in step.metadata and "handoff_to" in step.metadata:
                handoffs.append(_handoff_from_step(step))

    downstream_input = {agent.agent_id: agent.provider_input_tokens for agent in agents.values()}
    for handoff in handoffs:
        handoff.downstream_provider_input_tokens = downstream_input.get(handoff.to_agent_id, 0)

    finalized_branches = [_finalize_branch(branch) for branch in branches.values()]
    fanouts = _fanouts(finalized_branches)
    return MultiAgentProfile(
        has_metadata=has_metadata,
        agents=sorted(agents.values(), key=lambda item: item.agent_id),
        branches=sorted(finalized_branches, key=lambda item: item.branch_id),
        handoffs=handoffs,
        fanouts=fanouts,
    )


def profile_to_dict(profile: MultiAgentProfile) -> dict[str, Any]:
    return {
        "has_metadata": profile.has_metadata,
        "agents": [
            {
                **asdict(agent),
                "parent_agent_ids": sorted(agent.parent_agent_ids),
                "branch_ids": sorted(agent.branch_ids),
                "finding_ids": sorted(agent.finding_ids),
            }
            for agent in profile.agents
        ],
        "branches": [
            {
                key: value
                for key, value in asdict(branch).items()
                if not key.startswith("_")
            }
            for branch in profile.branches
        ],
        "handoffs": [asdict(handoff) for handoff in profile.handoffs],
        "fanouts": [asdict(fanout) for fanout in profile.fanouts],
    }


def compare_profiles(
    baseline: MultiAgentProfile,
    candidate: MultiAgentProfile,
) -> dict[str, Any]:
    baseline_agents = {agent.agent_id: agent for agent in baseline.agents}
    candidate_agents = {agent.agent_id: agent for agent in candidate.agents}
    baseline_branches = {branch.branch_id: branch for branch in baseline.branches}
    candidate_branches = {branch.branch_id: branch for branch in candidate.branches}
    agent_deltas = []
    for agent_id in sorted(set(baseline_agents) & set(candidate_agents)):
        base = baseline_agents[agent_id]
        cand = candidate_agents[agent_id]
        agent_deltas.append(
            {
                "agent_id": agent_id,
                "baseline_provider_input_tokens": base.provider_input_tokens,
                "candidate_provider_input_tokens": cand.provider_input_tokens,
                "provider_input_token_delta": cand.provider_input_tokens
                - base.provider_input_tokens,
                "baseline_component_processed_tokens": base.component_processed_tokens,
                "candidate_component_processed_tokens": cand.component_processed_tokens,
                "component_processed_token_delta": cand.component_processed_tokens
                - base.component_processed_tokens,
                "baseline_llm_calls": base.llm_calls,
                "candidate_llm_calls": cand.llm_calls,
                "llm_call_delta": cand.llm_calls - base.llm_calls,
                "baseline_tool_calls": base.tool_calls,
                "candidate_tool_calls": cand.tool_calls,
                "tool_call_delta": cand.tool_calls - base.tool_calls,
            }
        )
    return {
        "has_metadata": baseline.has_metadata or candidate.has_metadata,
        "agent_deltas": agent_deltas,
        "added_agents": sorted(set(candidate_agents) - set(baseline_agents)),
        "removed_agents": sorted(set(baseline_agents) - set(candidate_agents)),
        "added_branches": sorted(set(candidate_branches) - set(baseline_branches)),
        "removed_branches": sorted(set(baseline_branches) - set(candidate_branches)),
        "baseline_branch_count": len(baseline.branches),
        "candidate_branch_count": len(candidate.branches),
        "baseline_handoff_count": len(baseline.handoffs),
        "candidate_handoff_count": len(candidate.handoffs),
    }


def scope_for_step(step: AgentStep, run_metadata: dict[str, Any] | None = None) -> str | None:
    parts = []
    run_metadata = run_metadata or {}
    agent_id = _metadata_str(step.metadata, "agent_id") or _metadata_str(
        run_metadata, "agent_id"
    )
    branch_id = _metadata_str(step.metadata, "branch_id") or _metadata_str(
        run_metadata, "branch_id"
    )
    if agent_id is not None:
        parts.append(f"agent:{agent_id}")
    if branch_id is not None:
        parts.append(f"branch:{branch_id}")
    return " ".join(parts) if parts else None


def scope_for_call_id(run: AgentRun, call_id: str) -> str | None:
    for step in run.steps:
        if any(call.llm_call_id == call_id for call in step.llm_calls) or any(
            call.tool_call_id == call_id for call in step.tool_calls
        ):
            return scope_for_step(step, run.metadata)
    return None


def _step_metrics(step: AgentStep) -> dict[str, float | int]:
    component_tokens = 0
    provider_input_tokens = 0
    provider_output_tokens = 0
    work_duration_ms = 0.0
    for call in step.llm_calls:
        provider_input_tokens += call_input_tokens(call) or 0
        provider_output_tokens += call.output_tokens or 0
        component_tokens += sum(token_count(component.text) for component in call.prompt_components)
        latency = _metadata_float(call.metadata, "latency_ms")
        if latency is not None:
            work_duration_ms += latency
    for tool_call in step.tool_calls:
        work_duration_ms += tool_call.latency_ms or 0.0
    return {
        "llm_calls": len(step.llm_calls),
        "tool_calls": len(step.tool_calls),
        "provider_input_tokens": provider_input_tokens,
        "provider_output_tokens": provider_output_tokens,
        "component_processed_tokens": component_tokens,
        "work_duration_ms": work_duration_ms,
    }


def _add_metrics_to_agent(agent: AgentAttribution, metrics: dict[str, float | int]) -> None:
    agent.llm_calls += int(metrics["llm_calls"])
    agent.tool_calls += int(metrics["tool_calls"])
    agent.provider_input_tokens += int(metrics["provider_input_tokens"])
    agent.provider_output_tokens += int(metrics["provider_output_tokens"])
    agent.component_processed_tokens += int(metrics["component_processed_tokens"])
    agent.work_duration_ms += float(metrics["work_duration_ms"])


def _add_metrics_to_branch(branch: BranchAttribution, metrics: dict[str, float | int]) -> None:
    branch.llm_calls += int(metrics["llm_calls"])
    branch.tool_calls += int(metrics["tool_calls"])
    branch.provider_input_tokens += int(metrics["provider_input_tokens"])
    branch.provider_output_tokens += int(metrics["provider_output_tokens"])
    branch.component_processed_tokens += int(metrics["component_processed_tokens"])
    branch.work_duration_ms += float(metrics["work_duration_ms"])


def _add_step_bounds(branch: BranchAttribution, step: AgentStep) -> None:
    started = parse_datetime(step.started_at) if step.started_at else None
    ended = parse_datetime(step.ended_at) if step.ended_at else None
    if started is not None:
        branch._started.append(started)
    if ended is not None:
        branch._ended.append(ended)


def _finalize_branch(branch: BranchAttribution) -> BranchAttribution:
    if branch._started and branch._ended:
        branch.elapsed_ms = (
            max(branch._ended) - min(branch._started)
        ).total_seconds() * 1000
    return branch


def _fanouts(branches: list[BranchAttribution]) -> list[FanoutAttribution]:
    by_parent: dict[str, list[BranchAttribution]] = {}
    for branch in branches:
        if branch.parent_branch_id is not None:
            by_parent.setdefault(branch.parent_branch_id, []).append(branch)
    fanouts = []
    for parent, children in by_parent.items():
        if len(children) < 2:
            continue
        elapsed_values = [child.elapsed_ms for child in children if child.elapsed_ms is not None]
        fanouts.append(
            FanoutAttribution(
                parent_branch_id=parent,
                branch_ids=sorted(child.branch_id for child in children),
                work_duration_ms=sum(child.work_duration_ms for child in children),
                critical_path_ms=(
                    max(elapsed_values) if len(elapsed_values) == len(children) else None
                ),
            )
        )
    return sorted(fanouts, key=lambda item: item.parent_branch_id)


def _handoff_from_step(step: AgentStep) -> HandoffAttribution:
    component_tokens = _component_tokens(step.metadata.get("component_tokens"))
    return HandoffAttribution(
        from_agent_id=str(step.metadata["handoff_from"]),
        to_agent_id=str(step.metadata["handoff_to"]),
        branch_id=_metadata_str(step.metadata, "branch_id"),
        parent_branch_id=_metadata_str(step.metadata, "parent_branch_id"),
        context_tokens=_metadata_int(step.metadata, "context_tokens"),
        component_tokens=component_tokens,
    )


def _component_tokens(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    result = {kind: 0 for kind in COMPONENT_ORDER}
    for key, raw in value.items():
        try:
            count = int(raw)
        except (TypeError, ValueError):
            continue
        result[component_kind(str(key))] += count
    return {key: count for key, count in result.items() if count}


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return str(value) if value is not None else None


def _metadata_int(metadata: dict[str, Any], key: str) -> int | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_float(metadata: dict[str, Any], key: str) -> float | None:
    value = metadata.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
