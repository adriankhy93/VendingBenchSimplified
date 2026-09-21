# Agent guide to Vending Bench

This is a self-contained operating guide for an LLM agent managing a vending
machine. Your task is to finish one assigned episode, maximize its final score,
and report the result. Use public observations to choose products, negotiate
purchases, set selling prices, stock the machine, and manage cash.

## 1. What to do first

Determine which interface you have:

- **Pi with the `vending` tool:** call `{"action":"create","payload":{}}`.
  Follow `controller.permitted_actions` after every response. The tool manages
  the API address, environment ID, retries, and checkpoints. Do not use shell,
  direct HTTP, or other tools to bypass its controller.
- **A custom agent with REST access:** obtain the environment API base URL from
  the operator, call `POST /env` with `{}`, save the returned `env_id`, then call
  `POST /env/{env_id}/observe` with `{}`. The complete REST contract is below.

If resuming an existing episode, reuse its ID and checkpoint. Check its status
before taking further actions. Do not create a replacement episode to escape
losses, errors, termination, or an uncertain request outcome. A new episode is a
separate run and should be started only when the operator requests one.

For benchmark participation, use the assigned interface and public responses.
Do not read server source, scenario files, evaluator artifacts, hidden demand
logs, seeds, or supplier private parameters to make trading decisions. The setup
section is for the operator preparing the run, not an additional tool allowance
for an agent already operating through Pi.

## 2. Operator setup and service addresses

Docker runs only the environment and dashboard. vLLM and Pi run locally.
From the repository root on the Docker host:

```bash
# Requires Docker Compose with support for `up --wait`.
bash start.sh train 8000 9999
# Or select test mode:
bash start.sh test 8000 9999
```

Both port arguments are required: **environment API first, dashboard second**.
The example exposes the API at `http://127.0.0.1:8000` and the dashboard at
`http://localhost:9999`. REST documentation is at `http://localhost:8000/docs`.
No LLM, GPU, or model installation is needed to start these Docker services.

Training uses a fresh random seed for each created episode while retaining its
scenario parameters. Testing uses a fixed seed. The same actions reproduce the
simulation under the same seed/configuration; LLM decisions and wall-clock
termination can still differ. Train and test also have different scenario
parameters. Do not assume only their seeds differ.

To run the bundled local agent, install vLLM in a suitable GPU Python environment
and download model weights. Edit `configs/model.env` to set `model_path`,
`model_name`, `VLLM_GPU`, `VLLM_MAX_MODEL_LEN`, and
`VLLM_GPU_MEMORY_UTILIZATION`. Both local launchers read this file.

```bash
# Once: install Pi and its local Node runtime.
bash scripts/install_pi.sh

# Keep vLLM running in one terminal.
bash scripts/serve_qwen_vllm.sh

# Once vLLM is ready, start one episode in another terminal.
VENDING_API_URL=http://127.0.0.1:8000 bash scripts/run_pi_agent.sh --print
```

vLLM defaults to `http://127.0.0.1:8001/v1`. For a different local LLM port, set
`VLLM_PORT` for the serving script and `VLLM_API_URL` for the agent script, e.g.
`VLLM_API_URL=http://127.0.0.1:9001/v1`. Model files must already exist; serving is
offline. The supplied parser options target Qwen models. Start one agent at a time
with the default single-sequence vLLM setup.

Changing the API port requires changing `VENDING_API_URL` for the local agent.
Changing a model requires restarting vLLM and starting a new agent. Switching
train/test recreates the environment service: do it between episodes. A server
restart loses active episodes; recorded files are not resumable server checkpoints.

## 3. Objective and accounting

All monetary values are **integer cents**. For example, `150` means $1.50.

```text
inventory_value = acquisition cost of unsold units in storage AND machine
score_cents = cash_cents + machine_cash_cents + inventory_value - fee_debt_cents
net_profit_cents = score_cents - starting_cash_cents
```

Purchasing inventory exchanges cash for assets at acquisition cost; it does not
create profit by itself. Raising a selling price does not revalue unsold inventory.
Selling generates profit only after accounting for the sold units' purchase costs.
Fees reduce value. Collecting machine cash changes its location, not total assets,
but makes it available for purchases and fee payments.

The episode starts with empty storage and machine slots, no selling prices, and
no machine cash or fee debt. Starting spendable cash is configured by the operator.
Observe the actual run before budgeting.

Maintain enough **spendable cash** for purchases and fees. Machine cash cannot
pay fees until collected. Existing debt is paid from spendable cash before the
new fee is assessed at settlement. Partial fee payments leave debt. Consecutive
failures to pay the full current fee can terminate the episode.

## 4. Time, settlement, and markets

There are two clocks:

- **Real time:** the episode lifetime starts at creation and includes inference,
  tool latency, and idle time. `observe.result.rules` includes `runtime_seconds`
  and `deadline_utc`. An idle environment can expire without another action.
- **Simulated time:** successful action processing advances time by its configured
  duration. A day has 1,440 minutes. `sim_time.day` starts at 1 and
  `sim_time.minute_of_day` runs from 0 through 1,439.

The current engine settles customer demand and sales **at midnight**, then pays
arrears and the daily fee. Sales use the product price and machine inventory at
that settlement. Units in storage are not available for sale. More slots holding
the same product increase capacity, not demand. Demand varies; a sellout only
reveals a lower bound on demand.

An action applies its business operation before advancing simulated time. Thus
stocking just before a midnight crossing can make those units available for that
settlement. Read actions return the state after their time advance. Any action,
including a read or a rejected business operation, can cross midnight and end the
episode. Invalid requests rejected at validation do not advance simulated time.

`end_day` advances to the next midnight, even if the current time is already
midnight. `wait` advances a fixed configured duration; it accepts no duration field.
Calling status or result does not advance simulated time, although real time
continues to pass. Avoid excessive polling or repeating expensive observations.

Check every response's `state`, `sim_time`, and `events` before executing the next
planned action. A `day` event reports the completed day's product-level sales,
fees, failure streak, and balances. A `sales` event reports sold quantity for a
product. Use `get_machine` to learn each slot's remaining contents; product-level
sales do not identify the slot that sold.

Markets periodically reshuffle. `observe.result.rules.supplier_reshuffle_days`
provides the interval; `supplier_reshuffle` events announce a new market. Refresh
quotes with `search_products` before purchasing again. Old bargains and
counteroffers may no longer apply. Existing inventory retains its acquisition
cost; existing selling prices are not automatically updated.

The supplied configs currently use a 365-day cap, with a one-hour real lifetime
for train and two hours for test. Termination occurs at the first applicable
limit or the missed-fee failure condition. Treat runtime observations and the
operator's assigned configuration as authoritative, rather than hardcoding these
example limits into a policy.

## 5. REST lifecycle

Send JSON objects with `Content-Type: application/json`. The API has no token
requirement in the current local setup. Use the environment API port, not the
vLLM or dashboard port.

| Method | Path | Body | Meaning |
| --- | --- | --- | --- |
| `POST` | `/env` | `{}` | Create one episode; returns HTTP 201 and `{"env_id":"env_..."}`. |
| `GET` | `/env/{env_id}/status` | None | Return `{"state":"running"}`, `ended`, or `unavailable`. |
| `GET` | `/env/{env_id}/result` | None | Return the terminal summary; HTTP 409 while still running. |
| `DELETE` | `/env/{env_id}` | None | Delete the episode; HTTP 204, including repeated deletion. |

Use `{}` when creating a benchmark episode so it inherits the assigned train/test
configuration. Evaluator-only overrides exist, but a participant should not change
its seed, budget, or scenario to improve its score.

For operators writing harnesses, the optional creation fields are:

| Field | Valid value |
| --- | --- |
| `seed` | Integer 0 through 2^63−1; 0 is deterministic. API creation rejects `null`. |
| `runtime_seconds` | Positive integer real-time lifetime. |
| `max_days` | Positive integer, or `null` to disable the simulated-day cap. |
| `scenario_id` | `"benchmark-v1"` or `"smoke-v1"`. If supplied without `max_days`, benchmark disables the day cap and smoke uses 14 days. |
| `environment_name` | Custom saved definition supplied by the operator; none are bundled. Cannot be combined with the overrides above. |
| `environment_sha256` | Optional 64-character lowercase hexadecimal hash; requires `environment_name`. |

The `null` seed in the training server's config means randomize; this does **not**
mean `{"seed":null}` is valid in a creation request. Omit the seed in that request.

## 6. Complete REST action reference

All actions use **`POST /env/{env_id}/{action}`**. Bodies below are schema-valid
examples for the supplied catalog; discover IDs from public observations instead
of assuming them. The duration column lists the current supplied defaults in
simulated minutes. Read actual values from `observe.result.rules.durations`.

| Action | JSON body example | Minutes | Effect or result |
| --- | --- | --- | --- |
| `observe` | `{}` | 5 | Catalog, quotes, balances, slots, prices, storage, purchases, rules. |
| `search_products` | `{}` | 25 | Full catalog and quotes; optionally use `{"product_id":"p01"}` to filter products and quotes. |
| `get_inventory` | `{}` | 5 | Storage inventory under `result.storage`. |
| `get_balance` | `{}` | 5 | Spendable cash, machine cash, and fee debt. |
| `get_machine` | `{}` | 5 | Slots, selling prices, cumulative and current-day product sales. |
| `make_offer` | `{"supplier_id":"s01","product_id":"p01","quantity":10,"unit_price_cents":150}` | 75 | Attempt to buy units into storage at the offered unit price. |
| `set_price` | `{"product_id":"p01","unit_price_cents":150}` | 25 | Set one product's selling price across all its slots. |
| `stock_items` | `{"slot_id":"r1s1","product_id":"p01","quantity":5}` | 75 | Move storage units into a machine slot. |
| `unstock_items` | `{"slot_id":"r1s1","quantity":1}` | 75 | Move slot units back into storage. |
| `collect_cash` | `{}` | 5 | Move machine cash into spendable cash. |
| `wait` | `{}` | 300 | Advance simulated time. |
| `end_day` | `{}` | To next midnight | Settle the day by advancing to midnight. |

Constraints and outcomes:

- Unknown fields are rejected. IDs must be known products, suppliers, or slots.
  Integer fields require integers, not strings, booleans, or fractional numbers.
  Request bodies are limited to 65,536 bytes.
- Quantity must be positive and no larger than `rules.quantity_cap`. Slot capacity
  and available inventory impose additional business constraints.
- `set_price` must stay inside the product's public `min_price_cents` and
  `max_price_cents`. The reference price is a baseline, not a guaranteed cost or
  optimal selling price.
- `make_offer` can return `accepted`, `counteroffer`, `no_reply`, or
  `insufficient_funds`. An accepted purchase adds storage inventory and deducts
  spendable cash. A counteroffer is not a purchase: submit a new offer if desired.
  An `upsell` is an optional suggestion, not an automatic order. Above-listed
  offers are not guaranteed to be accepted; do not overpay to force acceptance.
- Stock only after setting a selling price and buying sufficient inventory.
  A slot cannot mix products or exceed capacity. A business rejection has
  `result.outcome="rejected"`, with reasons such as `price_required`,
  `slot_product_mismatch`, `slot_full`, or `insufficient_stock`.
- Successful moves report `moved_quantity`, `slot_quantity`, and
  `storage_quantity`. FIFO lots preserve purchase costs through storage,
  stocking, unstocking, and sales. A slot emptied by sales or unstocking becomes
  unassigned and can later hold a different product.
- HTTP 200 means the request was processed, not that a trade was accepted.
  Always inspect the business result.

Action responses contain:

```text
state               running | ended | unavailable
action_id          unique action identifier within this episode
sim_time           {day, minute_of_day}
elapsed_minutes    actual simulated time consumed
result             action-specific data
events             sales, day settlement, and supplier reshuffle events
metrics            balances and aggregate units sold
termination_reason null while running; reason on termination
score              included when an action ends the episode
```

REST response fields are at the top level. With Pi, this entire response is nested under the
tool result's `response` field.

## 7. Copyable REST examples

These examples are for direct REST clients, not for bypassing Pi's controller.
They require Bash and curl. Keep the same environment ID throughout the episode.

```bash
API_URL=http://127.0.0.1:8000  # Match ENV_PORT from start.sh.

curl -sS -X POST "$API_URL/env" \
  -H 'Content-Type: application/json' -d '{}'

# Replace this with the env_id returned above.
ENV_ID=env_REPLACE_WITH_RETURNED_ID

api_action() {
  curl -sS -X POST "$API_URL/env/$ENV_ID/$1" \
    -H 'Content-Type: application/json' -d "$2"
}

api_action observe '{}'
api_action search_products '{"product_id":"p01"}'
```

After choosing valid IDs and a price from the observation:

```bash
api_action set_price '{"product_id":"p01","unit_price_cents":150}'
api_action make_offer '{"supplier_id":"s01","product_id":"p01","quantity":10,"unit_price_cents":100}'
# Inspect the offer outcome. Do not stock unless inventory was actually acquired.
api_action get_inventory '{}'
# Only if at least 5 units remain in storage and the slot has room:
api_action stock_items '{"slot_id":"r1s1","product_id":"p01","quantity":5}'
```

These prices illustrate request syntax; they are not promises of acceptance or
profit. Continue using fresh public state. Once the episode ends:

```bash
curl -sS "$API_URL/env/$ENV_ID/result"
# Save the response before deleting.
curl -sS -X DELETE "$API_URL/env/$ENV_ID"
```

## 8. Pi's structured tool and controller

The tool input is exactly:

```json
{"action":"create","payload":{}}
```

Subsequent inputs use the same envelope. Lifecycle actions are named `create`,
`status`, `result`, and `delete`; the extension selects their REST methods.
Do not include an environment ID or URL in the payload.

A normal tool output includes `request`, `response`, `http_status`, and
`controller`. The controller exposes `phase`, `env_id`, `day`, `balances`, selected
product inventory targets, `permitted_actions`, and `quantity_note`.

Each permitted candidate is an executable shape such as:

```json
{"action":"stock_items","payload":{"slot_id":"r1s1","product_id":"p01","quantity":5}}
```

Choose a returned candidate. All fields must match, except that a purchase/stock
quantity can be a smaller positive integer up to the listed maximum. In the
`retry` phase, match the entire pending payload exactly, including quantity.
Never invent a price, product, or action outside the current candidates.

A blocked request returns `blocked: true`, a message, and the current controller
view; it makes no HTTP call. Correct the request using that view instead of
repeating the blocked request. Each permitted tool invocation makes at most one
HTTP request.

The controller intentionally allows fewer choices than the raw REST API.
For example, `wait`, `unstock_items`, and `get_balance` are raw REST actions but
are not exposed by the bundled `vending` tool. The raw API's validity does not
make an action available in a given controller phase.

Normal progression:

1. Create, observe, select and price an initial assortment.
2. Use existing storage, buy bounded shortages, and stock allocated slots.
3. Select `end_day` when offered.
4. After any midnight crossing, collect positive machine cash, get machine and
   storage snapshots, and refresh stale supplier quotes.
5. Review permitted price experiments and replenish. Repeat until terminal.
6. Retrieve `result`, then `delete`, then stop at `done`.

A midnight crossing can interrupt any phase. Follow the newly returned controller
view immediately. On `halted`, stop and report the reason and known environment
ID; do not work around the halt or create a replacement.

## 9. Trading policy and working memory

The bundled controller enforces the following bounded baseline. For a direct
REST agent these are useful starting heuristics, not extra server restrictions
or a guarantee of optimal profit.

- Select up to four products initially, using public margins and diversity, with
  one slot per product. Finish one product's setup before adding another when
  practical. Initial prices are approximately 150% of reference, raised as needed
  to exceed the cheapest listed cost and kept within public price bounds.
- Preserve spendable cash equal to fee debt plus three daily fees. Buy only a
  measured shortfall, subtracting both storage and machine inventory from target
  stock. Use available storage before buying more.
- Before three days of history at the current price, target one slot of machine
  stock and no storage reserve. With enough history, target about 1.5 mean days
  of sales in the machine and one mean day in storage, rounded up and bounded by
  capacity. Two consecutive sellouts can justify another slot and higher target.
- Try 90% of the current listed price first. A second offer may accept a
  counteroffer or use the listed price after no reply. Allow at most two offers
  per supplier/product/day in the controller. Prefer low costs, but account for
  the 75-minute cost of another negotiation. Do not buy at or above retail.
- Evaluate a selling price over three comparable, fully stocked, non-sellout days
  using gross profit, not just revenue or units sold. Run at most one experiment:
  change price by at most 10%, hold for three comparable days, and retain it only
  if mean daily gross profit improves. Otherwise revert when directed. Buying or
  stocking ends the controller's price-review opportunity for that day.
- Refresh supplier quotes after a reshuffle and reset comparisons affected by
  the market change. Do not repeatedly tweak prices in reaction to one quiet day.
- Advance the day when offered. Filling every slot and spending all cash are not
  objectives. Unsold units count as assets, but cannot pay fees.

Track the following using public observations or the controller's checkpoint:

```text
Episode: ID, lifecycle, day/minute, deadline, last confirmed action ID
Cash: spendable cash, machine cash, debt, planned fee reserve
Per product: reference/bounds, retail price, latest quotes and market age
Inventory: storage lots, per-slot contents/capacity, acquisition costs
History: daily sales, sellouts, price held, observed gross profit
Plan: shortage, affordable offer, next stock movement, price experiment
Recovery: pending action/payload/idempotency key, attempts, uncertain outcome
```

Treat confirmed observations as authoritative. Do not count counteroffers as
purchases, assume a rejected stock operation succeeded, or infer empty slots from
aggregate sales alone. Give a brief reason for substantive choices; avoid long
narration that consumes the real-time budget.

## 10. Errors, retries, and resumption

API error bodies have the form:

```json
{"error":{"code":"invalid_action","message":"Invalid action fields, identifiers, quantity, or price"}}
```

| HTTP status | Interpretation and response |
| --- | --- |
| `400` | Malformed JSON; correct the request. |
| `404` | Unknown action, unknown/deleted/expired environment, or missing saved definition. Inspect the error code; do not silently create a replacement. |
| `409` | Result requested while running, environment unavailable, idempotency conflict, or saved-definition mismatch. Inspect the code and reconcile state. |
| `410` | Episode ended; retrieve its result instead of issuing more business actions. |
| `413` | Request body too large; reduce the body. |
| `422` | Invalid fields, IDs, quantity, price, configuration, or idempotency key. Fix the request; unchanged retries will not help. |
| `500` | Internal error; the environment can become unavailable. Check status and retrieve any available terminal summary. |

For direct REST action retries, supply an `Idempotency-Key` header of 1–200
characters. Save the key, action, and payload **before** sending. A retry while
the episode is running must use exactly the same key/action/payload; the server
returns the saved response rather than applying the action twice. Use a new key
for each new logical action. Reusing a key with a different action or payload
returns 409. Replay records are episode-local and are cleared at termination;
a terminal action is not replayable after the episode ends.

`POST /env` does not implement idempotent creation. An uncertain create cannot
safely be resolved by posting again, even with the same header. Report the
uncertainty instead of creating duplicate episodes. The API has no list-all-
episodes endpoint for recovering a lost creation response.

A timeout does not prove that an action failed. The server may have committed it
before the response was lost. Do not retry under a new key or update inventory
based only on an attempted request.

Pi persists the pending request and key, offers one exact retry after a transport
error, and halts after a second uncertain attempt. An uncertain create halts
immediately. On resume it checks status and reconciles public snapshots before
trading. Follow these recovery actions as offered. A halted or stalled run should
be reported as incomplete, not represented as a completed benchmark.

Pi normally prompts the model to continue until the controller is finished.
Manual cancellation and provider failures are respected. Three continuation
prompts without API progress pause the run. Printing tool-call JSON as prose is
not a tool invocation and does not operate the environment.

## 11. Completion and reporting

Termination reasons include `real_deadline`, `simulated_day_cap`, `smoke_day_cap`,
`missed_fees`, and `internal_error` for an unavailable environment. Deleting a
running episode records an incomplete `deleted_while_running` run.

When state becomes `ended` or `unavailable`, stop business actions and retrieve
`GET /env/{env_id}/result`. The terminal summary includes:

- `state`, `complete`, `termination_reason`, and `scenario_version`.
- `score`, including net assets and net profit in cents.
- `simulated_minutes`, `completed_days`, and `wall_duration_seconds`.
- `committed_action_count` and metrics for revenue, cost of goods sold, fees,
  purchases, sold units, action counts, and invalid calls.

Save the public result before deleting the episode. Results expire after the
configured retention period (one hour in the supplied configs). Once deleted,
the result endpoint is no longer available. Do not create another episode as part
of terminal cleanup.

Report the environment ID, completion status, termination reason, days completed,
final score, net profit, and any unresolved error. Do not equate HTTP success,
model connectivity, or a partial profitable run with completing the benchmark.
If you did not obtain a terminal result, say so explicitly.

For operators, Pi traces are in `runs/pi-sessions/` and evaluator records in
`runs/service/`; the dashboard reads both. Evaluator records include private
information and are not trading inputs for the participant agent. Inspect the
public terminal result for the agent's final report.

To stop services after the run:

```bash
docker compose down
# Stop local vLLM with Ctrl-C in its terminal.
```

## 12. Pre-action checklist

Before each decision, check: Is the episode still running? Did time cross midnight?
Are quotes current? Is cash reserved for fees? Was the previous trade actually
accepted? Is stock in storage or already in the machine? Is the slot compatible
and within capacity? Does the candidate preserve a positive margin? Is an outcome
uncertain and awaiting exact retry? With Pi, is this exact action currently
permitted?

Then make one action, read its response, update your plan, and continue until
result retrieval and cleanup are complete or the controller explicitly halts.
