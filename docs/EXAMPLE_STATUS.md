# Example Status

Date: 2026-08-16

Audited commit: `1efe59f`

The table distinguishes deterministic local examples from examples that are
documented but require optional frameworks, external services, GPU, or API
credentials.

| Example or fixture | Required extra | Network required | API required | GPU required | Audit result |
| --- | --- | --- | --- | --- | --- |
| `agentperf demo` | none | no | no | no | PASS: ran locally and in clean Python 3.11 / 3.12 wheel smokes. |
| `examples/artifacts/m3_raw_full` | none | no | no | no | PASS: load/analyze/report. |
| `examples/artifacts/m3_dedup_only` | none | no | no | no | PASS: load/analyze/report. |
| M3 `compare` / `check` / suite | none | no | no | no | PASS in existing tests and deep reliability corpus comparison. |
| `examples/artifacts/m17_sglang_support_triage` | none for fixture | no | no | no | PASS: stored SGLang fixture loads/analyzes/reports. |
| `examples/dogfooding/openai_agents_support_triage_compact` | none for fixture | no | no | no | PASS: stored OpenAI Agents fixture loads/analyzes/reports. |
| `examples/benchmark_suites/synthetic_replay` | none | no | no | no | PASS: stored baseline/candidate compare as ACCEPT. |
| `docs/data/m25_phase_b/strong_control/agentperf_artifact` | none for fixture | no | no | no | PASS: preserved real Phase B baseline loads/analyzes/reports. |
| `docs/data/m25_phase_b/mixed_evidence_backed/agentperf_artifact` | none for fixture | no | no | no | PASS: preserved real Phase B candidate loads/analyzes/reports. |
| `scripts/deep_reliability_local_baseline.py` | none | no | no | no | PASS: small smoke executed; full measured run recorded in `LOCAL_PERFORMANCE_BASELINE.md`. |
| `examples/external_agents/openai_agents_support_triage.py` | `agentperf[openai-agents]` | no for deterministic fixture mode | no in fixture mode | no | Existing compatibility tests cover the deterministic stored fixture. |
| LangGraph example | `agentperf[langgraph]` | no | no | no | Covered by existing LangGraph tests and release-prep smoke. |
| vLLM live scripts | vLLM/runtime | yes or local model service | no if local model | usually yes | NOT RUN in this audit; stored vLLM fixtures validate ingestion/correlation semantics. |
| SGLang live scripts | SGLang/runtime | yes or local model service | no if local model | usually yes | NOT RUN in this audit; stored SGLang fixtures validate ingestion/correlation semantics. |
| Runpod docs/scripts | Runpod tooling | yes | Runpod account/API | yes | NOT RUN; explicitly out of scope for this local audit. |

## Documentation Classification

- Executable local examples should either run without external services or state
  the required extra/service.
- Historical or GPU-backed scripts remain useful for reproducibility but are not
  part of the default local smoke path.
- Stored fixtures are the deterministic compatibility mechanism for vLLM,
  SGLang, OpenAI Agents, and M25 Phase B evidence in this audit.
