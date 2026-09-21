# Vending Bench Simplified

Docker runs the environment and dashboard. vLLM and the agent run locally.
Run commands from the repository root on the Docker host.

## 1. Start train or test

Requires Docker Engine and Docker Compose v2 with `docker compose up --wait`.
No GPU or model files are needed for this step.

```bash
bash start.sh train 8000 9999
# Or:
bash start.sh test 8000 9999
```

Both ports are required: `bash start.sh train|test ENV_PORT DASHBOARD_PORT`.
The first port is for the environment API; the second is for the dashboard.
With the examples above, open http://localhost:9999 for the dashboard and
http://localhost:8000/docs for the API documentation. Choose two different free ports.

Training creates a fresh random seed for each episode with the same scenario
parameters. Testing uses fixed seed `424242`; identical actions produce
repeatable simulation behavior. Agent decisions can still vary.

Switch modes only between episodes: switching recreates the environment service
and discards active episodes. Completed results remain in `runs/`.

## 2. Serve the LLM locally

Install vLLM in your local GPU Python environment and download your model.
Edit **[configs/model.env](configs/model.env)**:

```bash
model_path="/storage/models/Qwen3.6-27B"
model_name="qwen3.6-27b"
VLLM_GPU="0"
VLLM_MAX_MODEL_LEN="262144"
VLLM_GPU_MEMORY_UTILIZATION="0.8"
```

Then run in a separate terminal:

```bash
bash scripts/serve_qwen_vllm.sh
```

The LLM serves at http://localhost:8001/v1. The script loads local model files
offline and uses Qwen tool/reasoning parsers. Lower the context length if it does
not fit in GPU memory. Other model families may need different parser options.

## 3. Run the agent locally

Install Pi and its local Node runtime once:

```bash
bash scripts/install_pi.sh
```

After the environment and LLM are ready, run in another terminal:

```bash
bash scripts/run_pi_agent.sh --print
```

The agent uses the model name from `configs/model.env` and connects to the
API at http://localhost:8000 by default. If you selected another environment
port, set `VENDING_API_URL` as shown below. Run it again for another episode. After changing
models, restart vLLM and launch a new agent. Run one agent at a time with the
default LLM configuration.

Sessions are saved in `runs/pi-sessions/`; environment results in `runs/service/`.
The Docker dashboard reads both directories.

## 4. Logs and shutdown

```bash
docker compose ps
docker compose logs -f environment
docker compose down
```

Stop local vLLM or the agent with Ctrl-C in its terminal. Docker shutdown does
not stop these local processes. Stopping the environment loses active episodes;
it does not resume them later. Completed run files persist.

To use another environment API port, pass it as the first port argument and
point the local agent at the same address:

```bash
bash start.sh train 9000 9999
VENDING_API_URL=http://127.0.0.1:9000 bash scripts/run_pi_agent.sh --print
```

## 5. Environment REST API

Use the **environment API port** you passed to `start.sh` (8000 in these examples),
not the dashboard or LLM port. Set `API_URL` below to match your chosen port.
Interactive documentation: http://localhost:8000/docs. The action route is generic
in OpenAPI; the table below lists all supported action names and request bodies.

### Create, inspect, and delete an episode

| Method | Path | JSON body | Purpose |
| --- | --- | --- | --- |
| `POST` | `/env` | `{}` | Create an episode using the server's train/test defaults; returns `201` and `{"env_id":"env_..."}`. |
| `GET` | `/env/{env_id}/status` | None | Return `running`, `ended`, or `unavailable`; does not advance simulated time. |
| `GET` | `/env/{env_id}/result` | None | Retrieve the terminal result; returns `409` while the episode is running. |
| `DELETE` | `/env/{env_id}` | None | Delete the episode; returns `204`. Retrieve its result before deletion. |

```bash
API_URL=http://127.0.0.1:8000

curl -sS -X POST "$API_URL/env" \
  -H 'Content-Type: application/json' -d '{}'

# Copy the env_id returned above:
ENV_ID=env_REPLACE_WITH_RETURNED_ID

curl -sS "$API_URL/env/$ENV_ID/status"
```

An empty creation body preserves randomized training or fixed-seed testing.
Optional creation fields are:

| Field | Accepted value |
| --- | --- |
| `seed` | Integer from 0 through 2^63−1. Overrides the server seed; 0 is deterministic. `null` is not accepted in this API request. |
| `scenario_id` | `"benchmark-v1"` or `"smoke-v1"`. If supplied without `max_days`, benchmark disables the day cap and smoke sets it to 14. |
| `runtime_seconds` | Positive integer; real-time episode lifetime, starting at creation. |
| `max_days` | Positive integer, or `null` to disable the simulated-day cap. |
| `environment_name` | Advanced: name of a custom saved definition you supply to the server. No saved presets are included. Cannot be combined with seed/scenario/runtime/day-cap overrides. |
| `environment_sha256` | Optional 64-character lowercase hexadecimal file hash; requires `environment_name`. |

For example, create a short deterministic episode for manual testing:

```bash
curl -sS -X POST "$API_URL/env" \
  -H 'Content-Type: application/json' \
  -d '{"seed":42,"runtime_seconds":600,"max_days":2}'
```

This creates a separate episode; use its returned ID for subsequent calls.

### All supported actions

Every action uses **`POST /env/{env_id}/{action}`** with a JSON body.
Use actual product, supplier, and slot IDs from `observe` or `search_products`.
The examples below use IDs present in the repository's default configs.

| Action | Example JSON body | Purpose |
| --- | --- | --- |
| `observe` | `{}` | Read catalog, supplier quotes, balances, storage, machine, purchases, and rules. |
| `search_products` | `{}` | List all products, suppliers, and quotes. Optionally filter with `{"product_id":"p01"}`. |
| `get_inventory` | `{}` | Read inventory held in storage. |
| `get_balance` | `{}` | Read spendable cash, machine cash, and fee debt. |
| `get_machine` | `{}` | Read slots, selling prices, and sales counts. |
| `make_offer` | `{"supplier_id":"s01","product_id":"p01","quantity":10,"unit_price_cents":150}` | Offer to buy units into storage; inspect the outcome for acceptance, counteroffer, rejection, or insufficient funds. |
| `set_price` | `{"product_id":"p01","unit_price_cents":150}` | Set the product's selling price within the catalog's price bounds. |
| `stock_items` | `{"slot_id":"r1s1","product_id":"p01","quantity":5}` | Move units from storage into a slot. Set a selling price first; stock and capacity must be sufficient. |
| `unstock_items` | `{"slot_id":"r1s1","quantity":1}` | Move units from a slot back into storage. |
| `collect_cash` | `{}` | Transfer machine cash into spendable cash. |
| `wait` | `{}` | Advance by the configured wait duration (300 simulated minutes in the supplied configs). No duration parameter is accepted. |
| `end_day` | `{}` | Advance to the next simulated midnight. |

Money is in integer cents. Quantities must be positive integers within the
configured `quantity_cap` (1000 in the supplied configs). Unknown fields and
unknown IDs are rejected. Valid request syntax does not guarantee a successful
purchase or stock transfer: inspect `result` in the response.

**All action calls advance simulated time**, including observations and rejected
business operations. Durations are provided by `observe` under `result.rules.durations`.
Successful HTTP responses include `state`, `action_id`, `sim_time`,
`elapsed_minutes`, `result`, `events`, `metrics`, and `termination_reason`.

Use this Bash helper with any action/body from the table:

```bash
api_action() {
  curl -sS -X POST "$API_URL/env/$ENV_ID/$1" \
    -H 'Content-Type: application/json' -d "$2"
}

api_action observe '{}'
api_action search_products '{"product_id":"p01"}'
api_action set_price '{"product_id":"p01","unit_price_cents":150}'
api_action make_offer '{"supplier_id":"s01","product_id":"p01","quantity":10,"unit_price_cents":150}'
# Continue only if the purchase succeeded and sufficient stock remains:
api_action stock_items '{"slot_id":"r1s1","product_id":"p01","quantity":5}'
api_action end_day '{}'
api_action collect_cash '{}'
```

For retryable action requests, supply an `Idempotency-Key` header (1–200
characters). While the episode is running, repeating the same key, action, and
payload returns the cached response without applying the action again. Reusing
a key for a different action or payload returns `409`.

```bash
curl -sS -X POST "$API_URL/env/$ENV_ID/collect_cash" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: collect-001' -d '{}'

# After the episode ends:
curl -sS "$API_URL/env/$ENV_ID/result"
curl -sS -X DELETE "$API_URL/env/$ENV_ID"
```

Fetch results before the configured retention period expires. Deleting a running
episode stops it early; later API requests cannot retrieve it. Typical error
statuses are `404` for an unknown environment/action, `409` for a state or
idempotency conflict, `410` for actions on an ended episode, and `422` for invalid
fields, IDs, quantities, or prices. Error bodies have the form
`{"error":{"code":"...","message":"..."}}`.
