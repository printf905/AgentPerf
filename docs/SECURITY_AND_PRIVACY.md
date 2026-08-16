# AgentPerf Security and Privacy Boundary

AgentPerf is a local profiler. It is not an encryption system, hosted trace
service, secret scanner, or data-loss-prevention product.

## What AgentPerf Stores

AgentPerf artifacts preserve the evidence users record:

- normalized agent traces;
- prompt components;
- LLM/tool metadata;
- task quality results;
- environment metadata;
- findings, recommendations, and replay comparisons;
- optional serving telemetry.

If a user records raw prompt text, tool output, request metadata, or local paths,
that data may exist in the artifact files. Treat artifacts as potentially
sensitive project data.

## Raw Artifact Policy

Raw artifacts are intended to be faithful evidence. AgentPerf does not silently
delete captured trace fields from artifact JSON because doing so could corrupt
profiling, replay, and reproducibility semantics.

Users should avoid recording secrets in:

- prompt components;
- tool input/output;
- metadata;
- environment fields;
- exported framework spans;
- serving telemetry bundles.

## HTML Rendering Policy

Single-run and comparison HTML reports are safer presentation layers. By
default they:

- avoid full raw prompt and tool payload dumps;
- show IDs, token counts, bounded metadata, and provenance;
- HTML-escape rendered values;
- redact secret-like metadata keys;
- redact secret-like metadata values in the rendered report and embedded report
  data.

Examples of redacted keys or values include:

- `api_key`
- `runpod_api_key`
- `authorization`
- `bearer_token`
- `hf_token`
- `password`
- `private_key`
- strings containing `OPENAI_API_KEY=...`
- strings containing `Authorization: Bearer ...`
- local private-looking paths such as `/user/private/path`

The renderer redaction boundary is intentionally conservative, but it is not a
complete secret-detection engine.

## Terminal, JSON, and Markdown Output

Terminal reports and Markdown CI summaries primarily show aggregate metrics,
findings, quality status, policy checks, and task identifiers. They should not
be treated as a guarantee that no sensitive identifier can appear, because users
control task IDs, artifact IDs, metadata, and some names.

Machine-readable JSON comparison output preserves the existing comparison
contract. It is not redacted in the same way as standalone HTML, because JSON is
often used for local automation and regression gates.

## Recommended Handling

- Keep artifacts in the same trust boundary as source code and experiment logs.
- Do not upload artifacts containing private prompts, tool outputs, credentials,
  or raw server logs to public CI artifacts.
- Use sanitized artifacts for public docs and regression fixtures.
- Review generated HTML before sharing outside a trusted team.
- Do not rely on AgentPerf to detect or remove every possible secret format.

## Non-Goals

AgentPerf does not currently provide:

- encryption at rest;
- hosted access controls;
- a remote artifact registry;
- policy-based DLP;
- automatic prompt redaction before artifact persistence;
- full filesystem path anonymization;
- credential rotation or revocation.
