# Simplified vending machine simulation: implementation plan

## 1. Purpose and source requirements

Build a small, reproducible environment that tests an agent's ability to source and negotiate products, then price and operate a vending machine profitably. Source: [Vending Bench - simplified.pptx](<Vending Bench - simplified.pptx>), particularly slides 2–11, plus the supplied Environment API contract. This document specifies future implementation; no simulation is implemented yet.

The deck requires:

- Approximately 1–2 hours of compute and roughly 100,000 tokens per agent run, compared with the original benchmark's much larger budget.
- $500 starting spendable cash, a $2 daily fee, and early termination after 10 consecutive days on which the agent cannot pay that fee.
- One machine with four rows and three slots per row; 10 products and 10 suppliers.
- Actions that consume simulated time; automatic day completion at 24 hours and an explicit end-day action.
- Product demand sampled from a Poisson distribution, adjusted for price and day.
- Patient, impatient, and pushy-patient suppliers; immediate replies, delivery, stocking, and cash transfer without a separate logistics pipeline.
- Scoring from spendable cash, machine cash, and unsold inventory value; tracking sales and tool use.
- A configurable harness supporting prompts, tools, context management, memory, and Markdown instructions.

The REST contract requires creation, action dispatch, lifecycle status, deletion, and a predetermined runtime after which actions are rejected.

## 2. Open questions and proposed defaults

The user has confirmed the category split, runtime interpretation, slot capacity, and inventory valuation below. Other choices remain proposed implementation defaults. Keep settings in versioned configuration so experiments can be reproduced.

| Topic | Ambiguity | Decision or proposed default |
|---|---|---|
| Product categories | Slide 8 totals 120% and classifies supplier–product pairs; slides 10/12 total 100% and classify products. Balanced cost is approximately 95% of reference on slide 8 but equal to reference on slides 10/12. | **Confirmed:** 20 winner, 20 loser, and 60 balanced supplier–product pairs out of 100. **Proposed:** minimum costs center on 80%, 120%, and 95% of reference, respectively, with small pair-level variation. |
| Runtime | Real elapsed compute time and simulated business duration are not distinguished. | **Confirmed:** two-hour real-time runtime with as many simulated business days as possible; no business-day cap in benchmark runs. Fee-failure termination still applies. The deadline starts at creation; harness resource limits are separate. |
| Capacity and valuation | Slots may mean individual units or stacks; unsold inventory valuation is unspecified. | **Confirmed:** each slot holds 10 units of one product (120 units total). Value all unsold units at actual acquisition cost. |
| Sales timing | Deck gives daily demand but does not say when sales occur. | Simulate sales in fixed five-minute intervals to make stocking and pricing time matter. |
| Action durations | The deck lists 5, 25, 75 minutes, and 5 hours without assigning them. | Use the action-duration table below; treat assignments as tunable. |
| Fees when insolvent | Debt, partial payment, and eligibility of uncollected machine cash are unspecified. | Collect from spendable cash only; assess debt for any unpaid fee; pay arrears before the current fee. Machine cash requires collection. |
| Stack and language | No implementation stack is prescribed. | Python engine, FastAPI with typed request/response models, NumPy demand sampling, pytest, and a small HTTP client harness. Pin versions during implementation. |

Additional choices below are explicit MVP design decisions. They can be reviewed without blocking creation of this plan. Before freezing benchmark version 1, confirm the remaining proposed defaults, demand calibration, provider/model, and available compute. A two-hour run is a target to measure, not a performance claim.

## 3. Scope and architecture

Implement a single service process with multiple isolated environments held in memory. Use a per-environment lock to serialize actions, expiry, and deletion. Keep the simulation engine independent of HTTP and of any model provider. Do not require a database, browser UI, real email, external suppliers, or LLM-powered supplier responses.

Suggested layout:

```text
src/vending/
  config.py           # Versioned scenario settings and validation
  models.py           # Products, quotes, slots, lots, ledgers, lifecycle
  engine.py           # Actions, time advancement, fees, terminal rules
  demand.py           # Seeded demand and day multipliers
  suppliers.py        # Deterministic negotiation policies
  scoring.py          # Asset valuation and metrics
  registry.py         # Environment ownership, locking, expiry, cleanup
  api.py              # REST routing and error translation
src/harness/
  client.py           # Environment HTTP client, retry handling
  runner.py           # Episode loop and resource budgets
  agents.py           # Scripted baselines and model adapter interface
  context.py          # History truncation and memory
configs/              # Smoke and benchmark scenarios
prompts/              # Agent instructions and optional Markdown memory template
tests/                # Engine, lifecycle, API, and harness tests
runs/                 # Ignored generated artifacts
```

An environment stores identifiers, scenario version, seed, lifecycle state and reason, monotonic deadline, simulated time, balances, fee debt, missed-fee streak, storage lots, machine slots, product prices, supplier offers, RNG state, and metrics. Money uses integer cents; quantities and simulated minutes are integers. Inventory retains purchase-cost lots through transfers and sales using FIFO accounting. Financial totals must never rely on floating-point currency arithmetic.

Public observations expose product names and reference prices, listed supplier quotes, the agent's transactions, inventory, prices, balances, and realized sales. Supplier minimums, category labels, elasticity, latent demand, random seeds, and future demand remain evaluator-only. An agent must learn from quotes and sales, not access private engine state.

## 4. Products, suppliers, and negotiation

Create 10 products from a checked-in fixture with IDs, names, reference prices, base daily demand, and elasticity. Initial calibration proposal: reference prices $1–$5, base demand 5–15 units/day, elasticity 1.5–2.5. Fix the fixture and scenario version for comparisons.

Assign exactly 20/20/60 winner/loser/balanced labels across the 100 supplier–product pairs using a seeded shuffle. A product can therefore be a good deal at one supplier and a bad deal at another; do not assign an intrinsic winner/loser label to the product. For each pair, set the minimum to reference price times its pair category factor times a seeded multiplier in [0.98, 1.02], rounded to cents. Set the maximum/listed price to 1.25 times the minimum, rounded up. Validate minimum <= maximum. Supplier types are fixed per scenario, initially four patient, three impatient, and three pushy-patient. Supplier stock is unlimited; purchases are limited by the agent's cash and a configured request quantity cap.

Start with the complete vendor list and confirmed listed-price quotes available in the initial observation. Search returns the same catalog, optionally filtered by product; no external search or email is involved.

`make_offer` takes one supplier, one product, a quantity, and unit price:

- Patient: accept an offer in the inclusive [minimum, maximum] interval; otherwise return a counteroffer at `clamp(offer, minimum, maximum)`.
- Impatient: accept within that interval; otherwise return `no_reply` as a normal immediate result, not an HTTP timeout.
- Pushy-patient: use the patient rule and append one structured suggestion for another product at its listed price. Suggestions never cause automatic purchases.

An accepted offer atomically debits spendable cash and delivers a purchase lot to storage. A counteroffer returns its unit price and terms but moves no money or goods; the agent submits a new offer to accept it. A listed quote can similarly be purchased by offering its quoted price. Quote terms are fixed for the episode. An in-range offer that the agent cannot fund returns `insufficient_funds` without buying anything. There are no quantity discounts, shipping charges, credit purchases, or partial fills in the MVP.

These simple policies make negotiation inexpensive and reproducible, but patient suppliers reveal their minimum after a low offer. Measure whether sourcing still distinguishes agents before adding more complex negotiation.

## 5. Inventory, pricing, and sales

Slots have stable IDs `r1s1` through `r4s3`. Each holds a single product and up to the configured capacity. Multiple slots may hold the same product, but price is shared per product. Additional slots increase stock availability, not demand. Stock from storage into an empty slot or one already holding that product. An explicit unstock action returns units to storage so the agent can change the assortment without waiting for sell-through. Storage is unlimited and products do not spoil in the MVP.

Require a positive selling price before stocking. Proposed price bounds are 0.25–5 times the product reference price, rounded to valid cents. Bounds keep the constant-elasticity demand model numerically bounded; expose them to the agent.

Slide 6 specifies:

```text
D_i,t ~ Poisson(lambda_i,t)
lambda_i,t = base_demand_i * (reference_price_i / selling_price_i)^elasticity_i
             * day_multiplier(t)
```

Use a fixed seven-day multiplier fixture initially `[1.0, 1.0, 1.0, 1.0, 1.1, 1.2, 0.8]`. For each five-minute tick, sample demand with mean `lambda_i,t * 5 / 1440`. At a fixed price this sums to the deck's daily Poisson demand. Sell at most the available quantity, consume slots in stable ID order, record FIFO cost of goods sold, and place revenue in machine cash. Unmet demand is lost, not backlogged. Products have independent demand and no substitution.

Use randomness keyed by scenario seed, product, and absolute tick, including for out-of-stock products, so splitting the same wait into different actions does not change the demand stream. Pin the RNG algorithm and dependency versions for reproducibility. Store demand only in evaluator logs; return actual sales to the agent.

## 6. Time, fees, and lifecycle

Real time and simulated time serve different purposes. Real time limits environment availability; simulated time advances only through actions. Thinking, status polling, and HTTP latency do not create simulated sales. Use an injectable monotonic clock for real deadlines and tests; report UTC timestamps only as informational metadata.

For each action, acquire the environment lock, check the real deadline, validate the request, and apply valid business effects at the current simulated time. Then advance by its duration in five-minute ticks, resolving sales and midnight boundaries. Return the resulting observation. The duration represents time until the agent can act again; immediate delivery and stocking therefore remain immediate. Domain rejections such as insufficient stock consume the attempted action's duration but change no inventory or money. Malformed requests and unknown actions do not advance time. End-day advances only to the next midnight.

At each midnight, resolve the last tick's sales, use spendable cash to repay existing fee debt, assess the $2 fee, and pay as much as possible. Add any unpaid portion to debt. Increment the consecutive-failure count if the current fee was not fully paid; otherwise reset it. End immediately on the tenth consecutive failure. Fee debt is an explicit extension of the slides and is subtracted from scoring to avoid rewarding nonpayment.

Stop simulated advancement at an early terminal event, even if the action's requested duration extends beyond it. Benchmark scenarios have no simulated-day horizon. An optional day cap is permitted only for explicitly labeled smoke tests. Return `200` for that final accepted action with an ended observation. Assess fees for completed days only. Do not fast-forward unplayed simulated days when the real deadline expires.

Lifecycle transitions are one-way:

- `running -> ended`: real deadline or ten missed fees (also the optional day cap in smoke tests).
- `running -> unavailable`: unrecoverable internal error or eviction.
- Deletion removes the environment from the registry and releases its live resources.

Enforce expiry on every request and with a lightweight periodic sweeper so idle instances expire. Recheck the deadline before committing an action: if real expiry occurred during processing, discard the staged action, freeze the last committed state, and return `410`. Serialize terminal snapshot creation so scoring happens once. Ended environments retain a small immutable summary until deletion or configured retention expiry. Unavailable environments retain an error reason and last committed summary if possible; infrastructure failure is not reported as a valid completed score.

## 7. REST API specification

### Lifecycle endpoints

| Method and path | Request | Response |
|---|---|---|
| `POST /env` | Empty body or `{}` uses the server's scenario. Optional evaluator-only configuration: `scenario_id`, `seed`, `runtime_seconds`; optional `max_days` only in smoke-test scenarios, null for benchmark runs. | `201`, exactly `{"env_id":"env_abc123"}`; opaque unique ID. |
| `POST /env/{env_id}/{action}` | Action-specific JSON below. | `200` with the common action envelope. |
| `GET /env/{env_id}/status` | None. | `200`, exactly `{"state":"running"}`, `{"state":"ended"}`, or `{"state":"unavailable"}`. No simulated-time cost. |
| `DELETE /env/{env_id}` | None. | `204`, empty body. Proposed idempotent behavior: repeated deletion also returns `204`. |

Unknown IDs on status or action requests return `404`. Unknown actions on known environments return `404`, including after termination. Known actions on ended environments return `410`; known actions on unavailable environments return `409`. Invalid JSON returns `400`; schema errors or invalid business identifiers return `422`. Domain refusals are normal `200` action outcomes so the agent can respond to them. Unexpected engine faults mark the environment unavailable and return `500` for the triggering request; subsequent known actions return `409`.

Errors use `{"error":{"code":"environment_ended","message":"..."}}`. Enforce body size and quantity limits; reject negative/fractional quantities, noninteger cent amounts, nonfinite numbers, and unknown fields. Use an explicit dispatch allowlist, not dynamic attribute invocation.

### Action schemas and durations

Fields below are required unless marked optional. Empty requests use `{}`. All prices and balances are cents.

| Action | Payload | Result fields | Minutes |
|---|---|---|---:|
| `observe` | `{}` | Public catalog with initial quotes, rules, storage, slots, prices, balances, sales totals; useful for initialization/recovery | 5 |
| `search_products` | Optional `product_id` | Products and all matching supplier IDs and listed unit prices | 25 |
| `make_offer` | `supplier_id`, `product_id`, `quantity`, `unit_price_cents` | `outcome`: `accepted`, `counteroffer`, `no_reply`, or `insufficient_funds`; accepted purchase ID/total or counteroffer terms; optional upsell | 75 |
| `get_inventory` | `{}` | Storage quantities and acquisition costs per product | 5 |
| `get_balance` | `{}` | Spendable cash, machine cash, fee debt | 5 |
| `get_machine` | `{}` | Slots, capacities, quantities, product prices, cumulative and current-day realized sales | 5 |
| `set_price` | `product_id`, `unit_price_cents` | Applied product price | 25 |
| `stock_items` | `slot_id`, `product_id`, `quantity` | Moved quantity, resulting slot and storage quantity | 75 |
| `unstock_items` | `slot_id`, `quantity` | Moved quantity, resulting slot and storage quantity | 75 |
| `collect_cash` | `{}` | All machine cash transferred to spendable cash | 5 |
| `wait` | `{}` | Sales and day summaries for elapsed interval | 300 |
| `end_day` | `{}` | Completed day's sales, fees, balances, and failure streak | Until next midnight |

The extra pricing and cash-collection actions implement capabilities mentioned in the deck but absent from its tool list. `observe`, `unstock_items`, and `wait` are proposed usability additions. Stocking, unstocking, and purchasing are all-or-nothing. A business refusal uses `outcome: "rejected"` and a stable `reason` such as `insufficient_stock` or `slot_full`.

Example request: `POST /env/env_abc123/make_offer`:

```json
{"supplier_id":"s01","product_id":"p01","quantity":10,"unit_price_cents":80}
```

Common action response envelope, illustrated without incidental sales:

```json
{
  "action_id": "act_0001",
  "state": "running",
  "sim_time": {"day": 1, "minute_of_day": 75},
  "elapsed_minutes": 75,
  "result": {"outcome":"accepted","purchase_id":"buy_0001","total_cents":800},
  "events": [],
  "metrics": {"cash_cents":49200,"machine_cash_cents":0,"fee_debt_cents":0,"units_sold":0},
  "termination_reason": null
}
```

Return compact aggregated sales per product and completed-day summaries in `events`, not one event per unit. Days are one-indexed; minute-of-day is 0–1439. Terminal responses additionally include the final score breakdown. Initial observation includes time costs, capacity, deadline, absence of a benchmark day cap, bounds, and scoring rules.

Support an optional `Idempotency-Key` header for action requests. Store a payload fingerprint and response per key for the environment lifetime. While running, an identical retry returns the stored response without mutation or time cost; reuse with a different payload returns `409`. Lifecycle checks precede replay: all known actions after termination are rejected, including retries. Keep mutation and idempotency recording atomic.

### Terminal results without weakening the lifecycle contract

The four required endpoints cannot retrieve a final score after real expiry: status has only a state, and all POST actions must be rejected. Proposed small extension: `GET /env/{env_id}/result`, returning `409` while running, `200` with an immutable terminal summary after ending, and `404` after deletion. For unavailable instances return an explicitly incomplete diagnostic summary. This read consumes no simulated time and exposes no hidden parameters.

If extra routes are disallowed, the evaluator must read the service's terminal artifact through a trusted local interface. A remote harness using only the four required endpoints cannot reliably obtain a score after idle expiry. Do not add a post-terminal `get_result` action or overload the required status body to conceal this gap.

## 8. Accounting and evaluation

With the confirmed acquisition-cost valuation and proposed unpaid-fee accounting:

```text
inventory_value = sum(remaining units in storage and machine * actual unit purchase cost)
gross_assets = spendable_cash + machine_cash + inventory_value
score = gross_assets - unpaid_fee_debt
net_profit = score - 50000 cents
```

Without debt, this is the deck's score. Moving stock or collecting cash leaves score unchanged. Purchasing at any price exchanges equal cash and inventory value and cannot generate immediate profit; selling recognizes revenue minus purchase cost. Changing the selling price does not revalue unsold stock. Never value stock at an agent-selected retail price.

Track final score and breakdown, net profit, revenue, cost of goods sold, fees assessed/paid/unpaid, units sold per product, stockouts (evaluator-only latent demand), purchases, negotiated discounts, action counts/types, invalid calls, simulated days, wall duration, token use, model cost when available, and termination reason. Report score and cash separately: inventory value is not spendable liquidity. Preserve a last-valid snapshot for failures and mark those runs incomplete.

## 9. Simple agent harness specification

The harness is a separate process using HTTP for all agent-visible interactions. The runner owns creation, status polling, result retrieval, and cleanup; the model only selects vending actions. Keep evaluator configuration and hidden fixture data out of model context.

Configuration includes service URL, scenario/seed, agent type, optional provider/model, prompt and Markdown instruction paths, context policy, tool allowlist, 100,000 total input-plus-output token budget, 7,200-second environment runtime, a runner watchdog slightly longer than the environment deadline, allowing final result retrieval and cleanup, maximum model calls (initially 1,000), request timeout (initially 30 seconds), and artifact directory. Record the effective configuration and hashes. Count context-summary calls toward the same token budget. Scripted agents need no model credentials.

Provide a small provider-neutral adapter: input is messages and tool schemas; output is a structured action name/payload plus usage metadata. Use the same typed action schemas as the server. Allow exactly one environment action in flight. If a provider returns multiple calls, process them serially and stop immediately on termination. The first implementation needs only one selected model-provider adapter; no agent framework is required.

Episode loop:

1. Create an environment and record its ID; call `observe` for initial public information.
2. Present business objective, rules, remaining harness budget, public observation, and available tool schemas to the policy.
3. Obtain and locally validate one action, execute it, record request/response and usage, and append the tool result to context.
4. Check terminal state and budgets after every response. Poll status around long model calls. Limit each model/request timeout to the remaining runner budget.
5. On `409`/`410`, query status and stop if terminal. On `404` for an unknown action, feed a corrective error back to the agent; unknown environment ID ends the run as failed. Retry transient transport errors at most twice with the same idempotency key; never invent a new key for an ambiguous purchase response.
6. Stop on an ended/unavailable environment, token budget, runner deadline, maximum calls, or repeated invalid actions (initially five consecutive). Record the precise reason. Reserve estimated input and maximum output tokens before dispatch to avoid knowingly exceeding the token budget.
7. Retrieve the terminal summary before deletion. If the harness stops while the environment is running, save the latest public snapshot and mark the episode budget-truncated, not naturally completed. DELETE freezes a trusted evaluator snapshot before resource release; use that artifact for truncated-run accounting. Always attempt deletion in `finally`, including on interruption.

Default context policy: preserve instructions, a bounded structured notebook of discovered quotes/prices and observations, and the most recent 20 action/result pairs. Compact older history into deterministic summaries from logged public observations; optional model summaries are a configurable experiment. Keep tool-call/result pairs intact. Favor compact observations and summaries to allow more business days within the two-hour window; never impose a hidden day cap. The roughly 100k-token deck target remains a proposed harness cap: if reached before two hours, report a budget-truncated run. Calibrate model and context settings so this cap does not routinely prevent using the runtime; increasing the cap is a benchmark configuration decision. An optional local `write_memory` harness tool updates a bounded Markdown notebook without advancing environment time; it still consumes model tokens. Memory files are isolated per run and reset between episodes. Prompt, memory, and context-policy variants must be recorded because they affect results.

Provide three test policies:

- **Idle:** repeatedly end the day; verifies fees and termination without model calls.
- **Listed-price baseline:** search, choose products using public reference/listed-price margins, purchase small affordable batches, price at a fixed reference-price multiplier within bounds, stock, collect cash daily, and replenish using observed sales. No hidden categories or demand parameters.
- **Negotiating baseline:** same policy, but submit a low positive offer and use returned counters or listed quotes. Compare with the listed-price policy to test whether negotiation helps.

Output one run directory with `config.json`, `actions.jsonl`, `usage.jsonl`, public `memory.md`, and `summary.json`; service-side private events live separately. Include scenario version, seed in evaluator metadata only, agent/model settings, budget counts, score breakdown, termination/completion classification, and errors. Do not log credentials. Use repeated, fixed seed suites for comparisons; report means, spread, completion rates, and resource use. Only compare matching scenario/budget settings and distinguish incomplete runs.

## 10. Implementation milestones and acceptance checks

1. **Resolve and freeze configuration.** Record the confirmed user decisions and resolve the remaining defaults and result-retrieval approach. Create validated product/supplier fixtures and a versioned scenario. Document every default exposed to the agent.
2. **Build the pure engine.** Implement money/inventory accounting, supplier policies, pricing, fixed-tick sales, time advancement, fees, and termination. Verify deterministic replay for identical seed/action sequences.
3. **Expose REST lifecycle and actions.** Add isolated registry, locks, deadlines, typed schemas, error mapping, idempotency, sweeper, terminal summaries, and deletion.
4. **Implement the scripted harness.** Complete an HTTP-only episode with each baseline and generate readable artifacts before connecting a model.
5. **Add one model adapter and context controls.** Verify budgets, valid tool routing, truncation, memory isolation, and cleanup using a fake provider first.
6. **Calibrate and benchmark.** Run smoke scenarios and then a fixed multi-seed suite on target compute. Tune demand and action costs against the confirmed capacity, and measure simulated days achieved in the two-hour window. Freeze the version after verifying meaningful sourcing/pricing tradeoffs and measured run costs.

Required tests and completion criteria:

| Area | Evidence required |
|---|---|
| API contract | Creation is `201`; exact status states; deletion is empty `204`; unknown IDs/actions `404`; ended actions `410`; unavailable actions `409`. |
| Expiry | Fake-clock tests expire idle instances and requests at the exact deadline; no post-deadline commits; final result remains readable until cleanup. |
| Time | Midnight crossed once or multiple times charges each completed day once; end-day at midnight advances a full day; advancement stops at the tenth missed fee (or an explicit smoke-test day cap); benchmark scenarios continue beyond day 30. |
| Suppliers | Boundary acceptance, clamp counters, no-reply, upsell without purchase, insufficient funds, and immediate delivery. |
| Conservation | Purchases, transfers, cash collection, FIFO sales, and fee debt reconcile exactly; no negative cash/stock; no inventory double counting or retail-price score inflation. |
| Demand | Same seed/actions replay exactly; action partitioning preserves demand; higher price lowers expected demand; stock bounds sales; duplicate slots do not duplicate demand. Use fixed fixtures and statistically justified tolerances rather than flaky single-draw comparisons. |
| Concurrency | Duplicate purchase retry charges once; competing actions cannot overspend/overfill; deletion/action/expiry races have a single consistent outcome. |
| Harness | Fake provider covers malformed actions, empty responses, timeouts, retries, token exhaustion, terminal rejection, result retrieval, and cleanup. Scripted full episodes run without credentials. |
| Isolation | Independent environments do not share money, RNG state, inventory, or memory; agent responses/logs do not expose hidden evaluator parameters. |
| Performance | Measure elapsed time, peak memory, action latency, and model usage on target hardware; demonstrate the intended full run within two hours and approximately 100k tokens, or revise defaults with recorded evidence. |

Defer persistence/restart recovery, distributed workers, authentication beyond local/test deployment, supplier LLMs, email threads, delayed logistics, spoilage, competing machines, and cross-product demand substitution. Revisit only after the small environment and harness produce useful, reproducible tests of both target capabilities.
