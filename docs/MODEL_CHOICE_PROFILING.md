# M4 Model-Choice Counterfactual Profiling

Status: implementation prepared; live GPU validation must be run before any
measured result is claimed.

M4 asks whether each semantic LLM role in the real research agent needs the
strongest selected model.

The reused agent roles are:

- `planner`
- `evidence_reviewer`
- `final_synthesizer`

The experiment is offline profile-guided replay, not a learned router and not an
automatic model search.

## Model Ladder

The selected ladder is same-family Qwen3 to reduce prompt-template and tokenizer
confounding:

| Tier | Model | Scale | dtype | Context | vLLM compatibility | Relative cost weight |
| --- | --- | ---: | --- | --- | --- | ---: |
| Small | `Qwen/Qwen3-0.6B` | 0.6B-class | bfloat16 | M4 uses `--max-model-len 8192` | `Qwen3ForCausalLM` | 0.6 |
| Medium | `Qwen/Qwen3-1.7B` | 1.7B-class | bfloat16 | M4 uses `--max-model-len 8192` | `Qwen3ForCausalLM` | 1.7 |
| Strong | `Qwen/Qwen3-4B` | 4B-class | bfloat16 | M4 uses `--max-model-len 8192` | `Qwen3ForCausalLM` | 4.0 |

Sources checked before implementation:

- vLLM supported models documentation lists Qwen/Qwen3 causal LM support:
  <https://docs.vllm.ai/en/stable/models/supported_models/>
- Qwen's Hugging Face collection lists the selected Qwen3 model sizes:
  <https://huggingface.co/collections/Qwen/qwen3>

The 24GB GPU plan is to run the three small vLLM servers concurrently on
separate local ports with constrained GPU memory fractions. If that fails in
preflight, the experiment should stop and report the infrastructure blocker
rather than changing the scientific design.

## Configurations

Strong baseline:

| Role | Tier |
| --- | --- |
| Planner | Strong |
| Evidence reviewer | Strong |
| Final synthesizer | Strong |

One-role counterfactuals:

| Config | Planner | Evidence reviewer | Final synthesizer |
| --- | --- | --- | --- |
| `planner_small` | Small | Strong | Strong |
| `planner_medium` | Medium | Strong | Strong |
| `reviewer_small` | Strong | Small | Strong |
| `reviewer_medium` | Strong | Medium | Strong |
| `synthesizer_small` | Strong | Strong | Small |
| `synthesizer_medium` | Strong | Strong | Medium |

Mixed candidate:

| Config | Planner | Evidence reviewer | Final synthesizer |
| --- | --- | --- | --- |
| `mixed_evidence_backed` | Small | Medium | Strong |

The mixed candidate is a single planned candidate for validation. It is not a
claim that the configuration is optimal.

## Quality Constraint

The default objective is:

minimize relative model cost and latency subject to:

- mean score >= strong baseline - 0.05
- pass rate >= strong baseline - 0.10

The runner records the exact constraint in `model_choice_comparison.json`.

## Cost Accounting

M4 separates:

- token waste;
- model-capacity waste;
- serving latency;
- monetary cost.

The default model-choice cost is a relative token-weighted score:

```text
sum(role_input_tokens + role_output_tokens) * model_relative_cost_weight
```

This is not commercial pricing. Future runs may add a user-supplied pricing
file, but no current provider price is hardcoded.

## Local Structural Run

```bash
python scripts/run_model_choice_counterfactual.py \
  --mock-llm \
  --output-dir /tmp/agentperf_m4_mock

agentperf analyze-model-choice \
  /tmp/agentperf_m4_mock/model_choice_comparison.json
```

Mock output validates artifact shape only. It is not model-choice evidence.

## Live Run Shape

The live runner expects one OpenAI-compatible vLLM endpoint per model tier:

```bash
python scripts/run_model_choice_counterfactual.py \
  --endpoint small=http://localhost:8001/v1,agentperf-qwen3-0.6b \
  --endpoint medium=http://localhost:8002/v1,agentperf-qwen3-1.7b \
  --endpoint strong=http://localhost:8003/v1,agentperf-qwen3-4b \
  --output-dir artifacts/model_choice_m4
```

Then:

```bash
agentperf analyze-model-choice \
  artifacts/model_choice_m4/model_choice_comparison.json \
  --show-provenance
```

Do not report M4 as complete until a live vLLM run has produced replay evidence
for the baseline, one-role counterfactuals, and the mixed candidate.
