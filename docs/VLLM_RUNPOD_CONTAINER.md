# Official vLLM Runpod Container Path

Status: prepared locally. Do not create a GPU Pod until this path is reviewed.

This path replaces the previous runtime installation flow:

```text
Runpod PyTorch template -> pip install torch/vLLM
```

with:

```text
Runpod Pod -> official pinned vLLM OpenAI-compatible container
```

The goal is to remove Python, CUDA, torch, and vLLM installation variability
before retrying M4 Phase A.

## Official Image

Use the architecture-specific CUDA 12.9 vLLM 0.26.0 image:

```text
vllm/vllm-openai:v0.26.0-x86_64-cu129-ubuntu2404
```

Docker Hub tag API verification:

```text
tag: v0.26.0-x86_64-cu129-ubuntu2404
architecture: amd64
os: linux
status: active
digest: sha256:4d08193d2fd05aadb1b5678f93ae609efb2635df67da45f3efe781c368b34dc8
last_pushed: 2026-07-25T09:04:25.176864Z
```

Official source notes:

- vLLM Docker docs identify `vllm/vllm-openai` as the official deployment image
  for OpenAI-compatible serving.
- Docker Hub lists the pinned `v0.26.0-x86_64-cu129-ubuntu2404` tag.
- The vLLM Dockerfile target for `vllm-openai` uses
  `ENTRYPOINT ["vllm", "serve"]`.

Because the image entrypoint is `vllm serve`, passing `sleep infinity` as a
normal Docker command is not sufficient for this experiment: it may become an
argument to `vllm serve` instead of replacing the entrypoint.

## Runpod Pod Creation

Current `runpodctl pod create` supports custom images and `--docker-args`, but
does not expose `dockerEntrypoint`. Runpod's Pod REST API does expose both
`dockerEntrypoint` and `dockerStartCmd`, so use the Pod API for this path.

The startup command keeps the official vLLM container alive, installs and starts
OpenSSH, and leaves a shell-controllable Pod. It does not install torch or vLLM.

Create exactly one 24GB Pod, after checking inventory and price:

```bash
curl --request POST \
  --url https://rest.runpod.io/v1/pods \
  --header "Authorization: Bearer ${RUNPOD_API_KEY}" \
  --header "Content-Type: application/json" \
  --data '{
    "name": "agentperf-m4-phase-a-vllm-container",
    "imageName": "vllm/vllm-openai:v0.26.0-x86_64-cu129-ubuntu2404",
    "cloudType": "SECURE",
    "computeType": "GPU",
    "gpuTypeIds": ["NVIDIA RTX A5000", "NVIDIA GeForce RTX 3090"],
    "gpuTypePriority": "availability",
    "gpuCount": 1,
    "allowedCudaVersions": ["13.0", "12.9"],
    "containerDiskInGb": 60,
    "volumeInGb": 160,
    "volumeMountPath": "/workspace",
    "ports": ["8888/http", "18000/http", "22/tcp"],
    "supportPublicIp": true,
    "dockerEntrypoint": ["bash", "-lc"],
    "dockerStartCmd": [
      "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends openssh-server git curl ca-certificates && mkdir -p /root/.ssh /var/run/sshd && chmod 700 /root/.ssh && if [ -n \"${PUBLIC_KEY:-}\" ]; then echo \"$PUBLIC_KEY\" >> /root/.ssh/authorized_keys; fi && chmod 600 /root/.ssh/authorized_keys || true && service ssh start && sleep infinity"
    ],
    "env": {}
  }'
```

Record the returned Pod ID, price, GPU, data center, image, and driver. Then
retrieve connection details:

```bash
runpodctl pod get <POD_ID>
```

Cost guard:

- The REST create API path is required for `dockerEntrypoint`.
- The current `runpodctl pod create --stop-after` path is not sufficient because
  it cannot override the official vLLM entrypoint.
- Immediately after creation, start a local guard as documented by Runpod's Pod
  management docs:

```bash
(sleep 4h; runpodctl pod stop <POD_ID>) &
```

Still delete the Pod after artifacts are preserved:

```bash
runpodctl pod delete <POD_ID>
runpodctl pod list
```

## Shell Access

The official vLLM image is used directly. The entrypoint is overridden to
`bash -lc` only so the Pod remains controllable and starts `sshd`.

This avoids:

- Docker-in-Docker;
- building a derivative image;
- pip-installing vLLM into a Runpod PyTorch template.

After `runpodctl pod get <POD_ID>` reports SSH details, connect with the
Runpod-provided SSH command.

## Repository Setup

On the Pod:

```bash
cd /workspace
git clone https://github.com/printf905/AgentPerf.git
cd AgentPerf
git checkout feature/model-choice-counterfactual
```

If the repo already exists:

```bash
cd /workspace/AgentPerf
git fetch origin
git checkout feature/model-choice-counterfactual
git pull --ff-only origin feature/model-choice-counterfactual
```

## Preflight

Run this before any model download:

```bash
bash scripts/remote_vllm/setup_official_container.sh
```

The script records diagnostics under:

```text
artifacts/model_choice_m4/container_preflight/
```

It runs these hard gates:

```bash
timeout 60 python3 -c "import vllm; print(vllm.__version__)"
```

```bash
python3 - <<'PY'
import torch
print(torch.__version__, torch.version.cuda)
assert torch.cuda.is_available()
print(torch.cuda.get_device_name(0))
print(torch.ones(1, device="cuda"))
PY
```

```bash
vllm --version
```

If any preflight fails or hangs, stop immediately, preserve the diagnostics, and
delete the Pod. Do not download models and do not start vLLM.

## Phase A Workflow

After preflight passes:

```bash
bash scripts/remote_vllm/run_model_choice_phase_a.sh
```

The script downloads models into `/workspace/models` and then runs the staged
Phase A protocol:

1. start only Qwen3-4B and run `strong_all`;
2. stop Qwen3-4B and verify memory release;
3. start only Qwen3-1.7B and run medium candidate role calls;
4. stop Qwen3-1.7B;
5. start only Qwen3-0.6B and run small candidate role calls;
6. stop Qwen3-0.6B;
7. restart Qwen3-4B and regenerate downstream strong continuations;
8. assemble `model_choice_comparison.json` and render the model-choice report.

The workflow preserves M4 semantics:

- one model is resident at a time;
- changed role calls are regenerated with the candidate model;
- downstream strong calls are regenerated when upstream output changes;
- deterministic local retrieval/tool results are held fixed;
- `MODEL_CHOICE_HEADROOM` can only come from replay evidence within the quality
  constraint.

## Artifacts

Expected output:

```text
artifacts/model_choice_m4/
  strong_all/
  planner_medium/
  reviewer_medium/
  synthesizer_medium/
  planner_small/
  reviewer_small/
  synthesizer_small/
  state/
  model_choice_comparison.json
  model_choice_report.txt
  model_choice_report.stdout.txt
```

Before cleanup, copy or push small artifacts and docs. Do not commit large model
weights or cache directories.

## Cleanup

After artifacts are preserved:

```bash
runpodctl pod delete <POD_ID>
runpodctl pod list
```

`runpodctl pod list` must show no running Pods before the run is considered
cleaned up.

## Sources

- vLLM Docker docs: <https://docs.vllm.ai/en/latest/deployment/docker/>
- vLLM Docker Hub tags:
  <https://hub.docker.com/r/vllm/vllm-openai/tags>
- vLLM Dockerfile:
  <https://github.com/vllm-project/vllm/blob/main/docker/Dockerfile>
- Runpod CLI Pod reference:
  <https://docs.runpod.io/runpodctl/reference/runpodctl-pod>
- Runpod Pod create API:
  <https://docs.runpod.io/api-reference/pods/POST/pods>
- Runpod SSH guide:
  <https://docs.runpod.io/pods/configuration/use-ssh>
