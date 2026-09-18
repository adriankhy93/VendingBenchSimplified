# Qwen through Pi and vLLM

Tested with `/storage/models/Qwen3.5-2B`, vLLM 0.29.0, and one H200.
The server runs locally without a hosted-model API key. Install vLLM in your GPU
Python environment separately; it is not a dependency of the simulation service.

Install Pi once, then start the model and simulation servers in separate terminals:

```bash
./scripts/install_pi.sh
./scripts/serve_qwen_vllm.sh
bash start_env.sh configs/environment.json
```

Wait for both servers to start, then launch Pi:

```bash
./scripts/run_pi_agent.sh
```

Pi reads only `.pi/skills/vending-machine/SKILL.md` for simulation-specific
instructions and calls the public API through `curl`. Its session JSONL traces are
saved in `runs/pi-sessions/`. To use a non-default API URL, set
`VENDING_API_URL` before launching Pi.

The launch script defaults to GPU 1, 10% GPU memory utilization, a 16,384-token
context, one concurrent sequence, text-only inference, and eager execution.
Override these settings when needed:

```bash
VLLM_GPU=0 VLLM_PORT=8002 VLLM_GPU_MEMORY_UTILIZATION=0.20 \
  ./scripts/serve_qwen_vllm.sh
VENDING_API_URL=http://127.0.0.1:8000 ./scripts/run_pi_agent.sh
```

`QWEN_MODEL_PATH`, `VLLM_MAX_MODEL_LEN`, `VLLM_BIN`, and `VENDING_MODEL_CACHE`
are also configurable. Extra script arguments pass through to vLLM. The server
binds to loopback and uses offline model loading. Stop it with Ctrl-C when finished.

Pi's project-local model definition is `.pi/agent/models.json`. It selects the
`vending-vllm/qwen3.5-2b` OpenAI-compatible endpoint with the configured
temperature, top-p, top-k, and presence penalty. Pi provides only `read` and
`bash` tools to the agent. It runs from an empty agent workspace and receives no
project context files; the Pi skill is its sole vending-specific capability.

Pi reports provider token usage in its session JSONL. Local inference has no
reported USD cost. A successful connection does not imply a profitable or
completed episode.

The server's tool parser follows the [Qwen model instructions](https://huggingface.co/Qwen/Qwen3.5-2B)
and [vLLM tool-calling protocol](https://docs.vllm.ai/en/latest/features/tool_calling/).
The results below are historical measurements from the retired custom Python
harness and are retained for comparison only. See
[measured results](qwen-vllm-results.json).

## Observed behavior (2026-09-11)

The initial 100,000-token run made six decisions and used 76,476 tokens before
conservative budget reservation stopped it. It mostly inspected the environment
and made no purchases. The original diagnostic configuration then made 62
decisions in 79.3 seconds, using 475,601 input and 3,644 output tokens (479,245
total). It bought ten water units but repeatedly attempted stocking before setting
a price. All 60 stocking attempts were refused with `price_required`.

That second run stopped at the token budget during day 4, with three completed
days, zero sales, and pre-deletion assets of $494 ($6 below the initial assets).
It is **budget-truncated**, not a completed evaluation or evidence of competitive
performance. This failure motivated the recovery and memory changes documented in harness.md. No scripted agent substituted for model decisions.

Inspect the second run at
http://localhost:8080/#459dc533ece845ee929b573ba6351ce5 while its local artifacts
are present. The compact results file is committed; detailed run logs are ignored
by Git. Adapter tests cover native tool history, token accounting, malformed
arguments, and timeout behavior. The full regression suite passed: 63 tests.

## Recovery harness validation

With the updated harness, run `a54f4901c4694cb5b998c92f49431c25` made 44
model decisions and used 311,958 tokens. Repeated unaffordable purchases triggered
five local `loop_blocked` responses and the run stopped with
`repeated_invalid_actions`, without advancing simulated time for blocked calls.
Qwen did not use the available memory tools in this run. The harness capabilities
are tested, but profitable trading and effective agent-written memory remain
unproven. See [validation metrics](harness-recovery-result.json).

The full regression suite now passes 71 tests, including Markdown path confinement,
on-demand reads, compact context, refusal variants and recovery after setting a price.
