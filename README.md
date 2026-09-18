# Simplified Vending Bench

A deterministic Python vending simulation, a local FastAPI service, and a Pi-based
HTTP-only agent harness. The engine implements [plan.md](plan.md) with the proposed defaults
versioned as `1.0-proposal`. Benchmark environments last two real hours with no
simulated-day cap; smoke environments have an explicit cap.

## View runs in the browser

```sh
./scripts/view_runs.sh
```

Open **http://localhost:8080**. The viewer runs independently of the simulation
service and reads existing artifacts from `./runs`; no database or frontend build
is required. It does not modify runs or advance simulated time.

- Search runs by agent, environment, seed, or ID, and filter by completion state.
- Inspect score/profit, sales, resource use, interactive cash charts, and the last
  observed machine inventory.
- Expand action rows to see exact requests, outcomes, sales events, and input/output/total tokens.
- Inspect token totals for each simulated day, including unfinished days and estimated usage.
- Read effective configuration, model usage records, and the agent's notebook.
- Enable auto-refresh to pick up new artifacts every five seconds. A run without
  a final summary is labeled **Unfinished**, since its log alone cannot prove it
  is still running.

New runs record `start_sim_time` and `token_usage` in each action-log row, a
simulated decision time in each usage-log row, and `usage.tokens_by_day` in the
summary. Tokens are charged to the day the model made its decision, even if the
action crosses midnight. A response requesting multiple actions is charged once
to the first action; subsequent actions reference the same model call and show
zero additional tokens. Failed/empty decisions and timeouts remain in the history;
timeout reservations are labeled **estimated**. Input tokens include the full
provider-reported context, not just the action's arguments.

Scripted actions use zero tokens. Older model runs without action/day attribution
show **—** instead of invented counts. Their original run-level totals remain
visible. The new fields are picked up automatically for newly recorded runs.

A truncated run's score is loaded from its trusted pre-deletion artifact when that
file is available; otherwise the viewer shows the final score as unavailable.
The URL includes the selected run ID, so individual runs can be bookmarked.

Use `./scripts/view_runs.sh --port 8081 --runs-dir /path/to/runs` to choose another
port or artifact directory. If trusted summaries live elsewhere, add
`--service-dir /path/to/service`. After reinstalling the editable package, the
same viewer is available as `vending-view`. The viewer binds to loopback by default;
`--host 0.0.0.0` is available for container port forwarding.

## Configure, generate, and choose an environment

Edit [configs/environment.json](configs/environment.json), which explicitly lists all
simulation settings, products, suppliers, and the seed.

After installing the project dependencies, generate and run a named environment:

```sh
./scripts/generate_environment.sh configs/environment.json my-market
./scripts/list_environments.sh
./scripts/run_environment.sh my-market
```

Generation creates `environments/my-market.json`. It embeds the complete configuration,
seed, and resolved supplier quotes, and refuses to overwrite an existing name. Change
the input config and generate another name to create a different experiment. Generation
does not start the clock. Each run starts a fresh episode from the selected definition.

`run_environment.sh` starts a loopback HTTP service on an available port using the
selected saved environment (or config path), launches Pi, and stops the service when Pi
exits. No separately launched simulation server is needed. The checked-in `default` and
`smoke` environments are ready to select; for a quick run:

```sh
./scripts/run_environment.sh smoke
```

For iterative harness tuning on fresh randomized markets, keep the same scenario
parameters and regenerate with a random seed each time:

```sh
./scripts/generate_environment.sh configs/environment.json train-001 random
./scripts/run_environment.sh train-001
```

For a fair shared evaluation, use a harder fixed-seed definition so every user is
scored on identical private quotes:

```sh
./scripts/generate_environment.sh configs/environment-eval.json eval-fixed
./scripts/run_environment.sh eval-fixed
```

`scripts/run_pi_agent.sh` options can be passed through `run_environment.sh` after the
first argument. Scripts use `python3`; set `PYTHON_BIN` if your installed interpreter
has another path.

See [the configuration reference](docs/environments.md) for fields and validation rules.

## Run

Python 3.12 or newer:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
bash start_env.sh configs/environment.json
```

`start_env.sh` starts the REST service on `127.0.0.1:8000`. It accepts either a
direct `Scenario` JSON file, or an environment configuration such as
`configs/environment.json` containing `seed` and `scenario`.
For the latter, an empty `POST /env` uses the configured seed; clients can still
provide a different seed or allowed runtime override in the request body. Set
`VENDING_HOST`, `VENDING_PORT`, `VENDING_ARTIFACT_DIR`, or
`VENDING_ENVIRONMENTS_DIR` before the command to change server settings.

In another terminal, activate the same environment and run from the repository root:

```sh
./scripts/install_pi.sh
./scripts/serve_qwen_vllm.sh
./scripts/run_pi_agent.sh
python -m pytest -q
```

## Configuration and artifacts

Set `VENDING_SCENARIO=/path/to/scenario.json` to change service defaults, or leave
it unset for the benchmark scenario. `Scenario` validates tunable action durations,
fees, capacity, retention, and weekly demand multipliers. Prices, quantities, money,
and simulated minutes are integers. Each of 12 slots holds 10 units by default.

Pi sessions are saved in `runs/pi-sessions/` as JSONL traces. These traces include
model messages, tool calls, tool results, and token usage.

The service writes separate trusted artifacts under `runs/service/`, configurable
through `VENDING_ARTIFACT_DIR`. `<env_id>.json` contains the terminal or pre-deletion
score and private evaluator metadata. This is the accounting source for a run
truncated while still running; the HTTP DELETE response remains empty. A remote
runner records the artifact name for an evaluator to retrieve through local access.
Private demand records in `<env_id>.private.jsonl` carry action IDs; records beyond
`summary.committed_action_count` belong to a staged action discarded at expiry and
must be excluded. Keep this directory out of the agent context.

## HTTP contract

| Request | Behavior |
| --- | --- |
| `POST /env` with no body or `{}` | `201 {"env_id":"env_…"}` |
| `POST /env/{id}/{action}` | `200` action envelope; optional `Idempotency-Key` |
| `GET /env/{id}/status` | `200 {"state":"running\|ended\|unavailable"}` (one literal state) |
| `GET /env/{id}/result` | `409` while running; immutable public summary after termination |
| `DELETE /env/{id}` | Idempotent `204`, empty body |

Creation accepts evaluator-only `environment_name` (and optional `environment_sha256`)
to select a saved definition. These cannot be mixed with scenario overrides. Otherwise,
creation accepts `scenario_id`, `seed`, `runtime_seconds`, and
`max_days` (only for `smoke-v1`). Action schemas and durations are in
[the plan](plan.md#action-schemas-and-durations) and [models.py](src/vending/models.py).
Typed envelope documentation is also served at `/docs`.

Unknown IDs/actions return `404`; known actions after ending return `410`, or `409`
when unavailable. Unknown actions still return `404` after ending. Malformed JSON
returns `400`, invalid fields/identifiers `422`, and oversized bodies `413` (64 KiB).
Business refusals return `200` and consume time. Errors use
`{"error":{"code":"…","message":"…"}}`. A final accepted action returns `200`
with its ended state and score. Retries with the same key and payload execute once;
a conflicting payload returns `409`. Lifecycle checks precede replay.

## Design and evaluation

The default supplier pairs have exactly 20 winner, 20 loser, and 60 balanced costs, with seeded
variation and fixed patient/impatient/pushy-patient policies. Pair categories and
supplier prices reshuffle every 30 simulated days (configurable with
`scenario.supplier_reshuffle_days`), starting on day 31. Supplier types and
minimums are private. Offers deliver immediately; stocking and prices take effect
before action time advances. Five-minute PCG64 demand streams are keyed by seed,
product, and absolute tick. Demand is sampled even without stock. Multiple slots
increase capacity without multiplying demand. There is no spoilage or substitution.

Unsold stock retains FIFO acquisition costs. Score is spendable cash plus machine
cash plus inventory cost, less fee debt. Midnight pays arrears before the current
$2 fee; ten consecutive unpaid current fees end a run. Thinking/polling consumes
no simulated time. Actions stage under a per-environment lock and commit only
before the real deadline. Idle environments expire via a sweeper. Terminal engines
release live inventory/RNG resources and retain summaries for one hour by default.

[Measured smoke results](docs/calibration.md) cover nine real-HTTP episodes and the
focused acceptance tests. Full two-hour model throughput and the approximately
100,000-token target remain unmeasured. The current calibration is provisional.
This MVP is for local/test deployment and does not implement authentication,
persistence, distributed workers, or external logistics.

## Local Qwen with vLLM

The agent harness uses [Pi](https://pi.dev/) and a single
[vending-machine skill](.pi/skills/vending-machine/SKILL.md). The skill is the
only simulation-specific context supplied to Pi: it documents the public REST
API, action payloads, responses, and lifecycle rules. Pi receives only `read`
and `bash` tools, so it invokes the documented API with `curl`; there is no
Python decision loop, hidden product-selection policy, or evaluator access.

Start the simulation service and local vLLM server in separate terminals:

```sh
bash start_env.sh configs/environment.json
./scripts/serve_qwen_vllm.sh
```

Then start an interactive Pi agent:

```sh
./scripts/install_pi.sh  # once; downloads project-local Node and Pi
./scripts/run_pi_agent.sh
```

`run_pi_agent.sh` uses the project-local Pi and Node installations in `.tools/`,
the `vending-vllm/qwen3.5-2b` model in [.pi/agent/models.json](.pi/agent/models.json),
and the loopback vLLM endpoint at `http://127.0.0.1:8001/v1`. Set
`VENDING_API_URL` when the simulation service uses a different URL. Pi's session
history is its model trace; use `/export` or its session JSONL for inspection.

Pi sessions are saved in `runs/pi-sessions/`, which is ignored by Git. Each JSONL
session records model messages, tool calls, tool results, and token usage.
