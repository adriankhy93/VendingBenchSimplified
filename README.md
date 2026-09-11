# Simplified Vending Bench

A deterministic Python vending simulation, a local FastAPI service, and an HTTP-only
agent harness. The engine implements [plan.md](plan.md) with the proposed defaults
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
- Expand action rows to see exact requests, outcomes, and sales events.
- Read effective configuration, model usage records, and the agent's notebook.
- Enable auto-refresh to pick up new artifacts every five seconds. A run without
  a final summary is labeled **Unfinished**, since its log alone cannot prove it
  is still running.

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
simulation settings, products, suppliers, and the seed. A full short-run example is
[configs/environment-smoke.json](configs/environment-smoke.json).

After installing the project dependencies, generate and run a named environment:

```sh
./scripts/generate_environment.sh configs/environment.json my-market
./scripts/list_environments.sh
./scripts/run_environment.sh my-market --agent negotiating
```

Generation creates `environments/my-market.json`. It embeds the complete configuration,
seed, and resolved supplier quotes, and refuses to overwrite an existing name. Change
the input config and generate another name to create a different experiment. Generation
does not start the clock. Each run starts a fresh episode from the selected definition.

`run_environment.sh` starts a loopback HTTP service on an available port, runs the agent,
and stops the service afterward. No separately launched server is needed. The checked-in
`default` and `smoke` environments are ready to select; for a quick run:

```sh
./scripts/run_environment.sh smoke --agent listed
```

Use `--agent model --model YOUR_MODEL_ID` for the optional configured provider. Additional
runner options, such as `--config configs/harness-smoke.json`, control harness budgets and
prompts. The selected saved environment supplies the seed, scenario, runtime, and day cap;
harness defaults do not override those values. `--smoke` cannot override a saved definition.
Scripts use `python3`; set `PYTHON_BIN` if your installed interpreter has another path.

For an already running service, select the same saved name with:

```sh
python3 -m harness.runner --environment my-market --agent negotiating
```

Both processes read `./environments` by default. Use `--environments-dir PATH` on the
runner and `VENDING_ENVIRONMENTS_DIR=PATH` on the service for another location. With a
remote service, place identical copies of the selected file in both directories. A
SHA-256 check rejects mismatched files. The evaluator copy and hash are recorded in
run artifacts; private market parameters are kept out of the agent context.

See [the configuration reference](docs/environments.md) for fields and validation rules.

## Run

Python 3.12 or newer:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
uvicorn vending.api:app --host 127.0.0.1 --port 8000
```

In another terminal, activate the same environment and run from the repository root:

```sh
vending-run --smoke --agent negotiating
vending-benchmark --smoke --seeds 0 1 2
python -m pytest -q
```

`--agent idle`, `listed`, and `negotiating` require no credentials. Omit `--smoke`
for the benchmark scenario. The runner's call/token limits can truncate an episode
before the service deadline; these runs are labeled `budget_truncated`.

The optional model adapter uses Anthropic Messages with native tool calls:

```sh
python -m pip install -e '.[model]'
export ANTHROPIC_API_KEY='your-key'
vending-run --smoke --agent model --model YOUR_MODEL_ID
```

Choose an available model explicitly. No model or price is silently selected.
The adapter follows the [provider tool-use contract](https://platform.claude.com/docs/en/agents-and-tools/tool-use/overview).
SDK usage is recorded; monetary model cost is `null` unless an adapter supplies it.
No paid model run was used for the checked-in measurements.

## Configuration and artifacts

Pass `--config PATH` to either harness command for a `RunConfig` JSON object.
See [configs/harness-smoke.json](configs/harness-smoke.json) for an example.
Configuration supports prompt/Markdown instruction paths, tool allowlists, bounded
context, optional local `write_memory`, model/request timeouts, token/call budgets,
and isolated memory templates. Paths are relative to the working directory.

Set `VENDING_SCENARIO=configs/smoke.json` to change service defaults, or leave it
unset for the benchmark scenario. `Scenario` validates tunable action durations,
fees, capacity, retention, and weekly demand multipliers. Prices, quantities, money,
and simulated minutes are integers. Each of 12 slots holds 10 units by default.

Each runner creates `runs/<run_id>/` containing `config.json` (including instruction
hashes), `actions.jsonl`, `usage.jsonl`, `memory.md`, and `summary.json`. The model
receives public observations only. Seed/scenario selection stays with the evaluator.
Old action/result pairs become deterministic quote, price, and realized-sales notes;
the most recent 20 pairs remain intact. Memory is bounded and reset per run.

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
variation and fixed patient/impatient/pushy-patient policies. Supplier types and
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
