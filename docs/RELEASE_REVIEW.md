# Release Review

Date: 2026-08-09

Scope: public-release and external-reader polish pass. This review does not add
new detectors, rerun GPU experiments, or claim missing M4 Phase B results.

## AI Infrastructure Engineer View

### Is the problem obvious within 30 seconds?

Mostly yes after the README rewrite. The first screen now says AgentPerf
connects agent traces with inference-server telemetry to explain token,
cacheability, first-token, and model-capacity waste.

Remaining concern: the repository contains many experiment documents. The README
now includes a documentation index so a reader does not have to infer which docs
are canonical.

### Are the real results obvious within 60 seconds?

Yes. The README now puts real vLLM results near the top:

- M2 prefix/cacheability result with cached-token ratio and
  scheduled-to-first-token P95.
- M3 real-agent context-waste result with quality, token, and latency tradeoff.
- M4 Phase A role-sensitivity result with Phase B explicitly pending.

### Is synthetic vs real clearly distinguished?

Yes. The README now separates:

- synthetic fixtures;
- recorded vLLM-shaped fixtures;
- real measured Runpod/vLLM experiments.

The synthetic CLI example is clearly labeled as not benchmark evidence.

### Is AgentPerf differentiated from Langfuse, Phoenix, ThunderAgent, and vLLM?

Yes. The README and `docs/LANDSCAPE.md` now make the distinction:

- observability tools show agent/application traces;
- vLLM/SGLang expose serving telemetry;
- ThunderAgent focuses on runtime/scheduling optimization;
- AgentPerf focuses on developer-facing cross-layer profiling, diagnosis, and
  replay validation.

The positioning avoids claiming AgentPerf invented agent-aware KV optimization.

### Are the strongest claims defensible?

Mostly yes. The strongest claims are tied to documented real runs:

- M2: controlled prompt-layout replay on vLLM/A5000.
- M3: quality-constrained context-carry replay on vLLM/RTX 3090.
- M4: Phase A counterfactual role sensitivity only.

Wording now avoids:

- turning the controlled M2 prefix/cacheability result into a speedup headline;
- pure GPU prefill claims;
- general benchmark claims;
- validated mixed routing claims.

### Is M4 incompleteness obvious?

Yes. The README says "Phase A validated, Phase B pending" and explicitly says
the proposed mixed route is not end-to-end validated. `docs/MODEL_CHOICE_RESULTS.md`
also records the blocked Phase B attempts.

### Is the README too long?

It is substantial but acceptable for an infrastructure project whose credibility
depends on experiment status and limitations. The most important reader path is
near the top: problem, real results, architecture, status matrix, quick start.

Potential future improvement: add a shorter docs landing page if README grows
again.

### Is the architecture understandable?

Yes. The README now includes one ASCII diagram showing the agent/harness layer,
the serving layer, and AgentPerf's normalization/correlation/detector pipeline.
Detailed schema and architecture docs remain linked.

### What would make me star or contribute?

- The project has concrete real vLLM results rather than only synthetic traces.
- It treats materiality and quality constraints seriously.
- It records failed experiments and environment blockers rather than hiding
  them.
- The trace schema and detector semantics are small enough to inspect.
- vLLM integration is a clear starting point for contributors.

### What still feels toy-like?

- Workloads are small and controlled.
- Only one serving backend has real validation.
- Quality evaluation is task-specific and local-corpus based.
- The real experiment path still depends on Runpod/vLLM environment details.
- There is no production ingestion pipeline, dashboard, or large-scale trace
  corpus.
- M4 Phase B mixed routing is not complete.

## Potential Contributor View

Strengths:

- Clear quick start without GPU.
- Tests cover trace parsing, correlation, detectors, vLLM ingestion, token
  attribution, and model-choice schemas.
- Docs are honest about what is implemented versus validated.

Concerns:

- There are many remote execution scripts and artifact docs. A contributor may
  need guidance on which scripts are current for each milestone.
- Runpod-specific scripts are useful but not a general deployment story.
- No contribution map exists for backend adapters beyond vLLM.

High-value contributor tasks after release:

- add one documented SGLang telemetry mapping;
- add more recorded real vLLM fixtures from different versions;
- improve reproducibility packaging for vLLM runs without requiring ad hoc Pod
  debugging;
- add more local-corpus tasks and evaluator checks.

## Interviewer View

Technical depth is visible in:

- explicit cross-layer correlation;
- measurement semantics and proxy labeling;
- detector materiality calibration from real data;
- quality-constrained optimization after a failed aggressive compaction attempt;
- replay-backed model-choice profiling that does not overclaim Phase B.

The strongest interview story is not "I built another tracing tool." It is:

```text
I built a profiler that connects agent prompt structure to model-server
behavior, then used real vLLM replay to show when prompt layout, tool-output
carry-forward, and model role choice are or are not worth changing.
```

## Repo Hygiene Review

Checks performed:

- reviewed `.gitignore`;
- checked for large non-git files;
- checked for likely credential patterns;
- checked tracked Runpod artifacts;
- reviewed release tags;
- reviewed README claims against result docs.

Findings:

- `.venv/`, caches, model weights, logs, and `artifacts/` are ignored by
  default.
- Two small diagnostic/result bundles under `artifacts/runpod/` are intentionally
  force-tracked.
- No likely API keys, Hugging Face tokens, GitHub tokens, Runpod API keys, or
  private key files were found by the targeted scan.
- Runpod Pod IDs and prices are documented as experiment metadata. They are not
  credentials.
- Current git tag is `v0.1.0`; no new release tag was created during this pass.

Untracked local files left untouched:

- `FINAL_REVIEW_TO_SEND.md`
- `REVIEW_EXTERNAL_READER.md`
- `REVIEW_TO_SEND.md`

## Release Recommendation

Do not tag a release before PR #6 is reviewed and merged.

Recommended version after merge:

- `v0.4.0` if the release is described as "real vLLM prefix/cacheability,
  quality-constrained context-waste profiling, and experimental model-choice
  Phase A."
- Avoid wording that implies M4 Phase B or end-to-end mixed routing is complete.

If the project owner wants a more conservative public release, use `v0.3.x` for
M2/M3 only and leave M4 Phase A as unreleased documentation on the branch.

## GitHub Presentation

Recommended repository description:

```text
Cross-layer profiler for agentic LLM workloads, correlating agent traces with
vLLM serving telemetry to diagnose token, cacheability, latency, and model-role
waste.
```

Short tagline:

```text
Find where agent tokens and first-token latency actually go.
```

Suggested topics:

- `llm`
- `agents`
- `ai-infrastructure`
- `observability`
- `profiling`
- `vllm`
- `opentelemetry`
- `inference`

Do not add badges unless the backing CI/service exists.

## Final External-Reader Verdict

The repository is credible for broader public sharing after PR #6 is reviewed,
provided the README's limits stay intact. The two completed stories are strong
enough to explain why the project matters. The main weakness is not product
scope; it is reproducibility friction around live GPU/vLLM experiments and the
unfinished M4 Phase B replay.
