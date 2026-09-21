# Participant briefing — speaker notes

22 slides total. Approximate speaking time: 20 minutes plus questions.

## 01. Build the harness. Run the business.

Welcome participants. The deliverable is an agent harness: the software that turns model decisions into reliable business actions. This briefing is based on the current implementation. Event-specific submission and model policies are still to be announced. Suggested presentation time: about 20 minutes plus questions; reference slides are optional.

Sources: README.md

## 02. You design the harness. We define the environment.

A harness is more than a prompt. It includes orchestration, memory, provider integration, and error handling. Participants should not change the test definition or the simulation to improve a score. Model eligibility, compute allowances, and the submission interface will be announced by the organizers; do not imply they have already been finalized.

Sources: src/vending/environments.py

## 03. One saved definition. A fresh episode each run.

A pre-generated environment is an initial definition, not a running checkpoint. Each episode gets a separate environment ID and starts empty. Identical definitions and seeds reproduce the market; action choices change sales opportunities. Identical action sequences reproduce the business simulation until real-time expiry intervenes. The number of official repeats, compute conditions, and tie-breaks remain organizer decisions. Freeze these before comparing submissions.

Sources: src/vending/environments.py, src/vending/registry.py, docs/environments.md

## 04. Learn from quotes and realized sales.

Observations expose the complete public catalog and initial listed quotes. Participants can discover costs by negotiating and demand by observing sales. Do not distribute the private test JSON, private service artifacts, or evaluator configuration to participant harnesses. The local MVP does not enforce this boundary through authentication or a sandbox; organizers must enforce it through deployment and file access. This operational point is expanded in the organizer checklist, not presented as an already implemented security guarantee.

Sources: src/vending/engine.py

## 05. A small business with tight operating constraints.

All numeric settings here are settings in configs/environment.json, not guaranteed hidden-test settings. Catalog size, fees, machine shape, capacity, and action costs are configurable. The engine requires a positive selling price before stocking. There is no separate logistics pipeline. Purchases and inventory transfers are all-or-nothing.

Sources: src/vending/config.py, src/vending/engine.py, configs/environment.json

## 06. There are two clocks to manage.

The practice file configures runtime_seconds=3600 and max_days=365. These are configurable, and max_days can be null. Actions apply immediate effects before advancing time; sales settle only at midnight. Status and result reads do not advance business time. The service checks a monotonic deadline and expires idle environments in a background sweep. Late actions cannot extend business time. Repeated fee failures can end the episode earlier.

Sources: configs/environment.json, src/vending/engine.py, src/vending/registry.py

## 07. Keep the operating loop moving.

Accepted offers debit spendable cash and add a storage lot immediately. Counteroffers do neither. At midnight, available spendable cash pays existing fee arrears before the current fee; partial payment creates debt. A current fee not fully paid increments the failure streak. A fully paid current fee resets it. Uncollected machine cash cannot pay the fee automatically. Multiple slots raise availability but do not multiply demand.

Sources: src/vending/engine.py

## 08. Negotiation produces structured outcomes.

Suppliers follow deterministic policies. Patient suppliers counter out-of-range offers, impatient suppliers can return no_reply, and pushy-patient suppliers may add an upsell. This deck does not disclose particular supplier types, pair minimums, or category assignments in the test. Supplier stock is unlimited, but the quantity cap and spendable cash limit purchases. A no_reply outcome is not a network timeout. Winner, loser, and balanced pair assignments and their quotes reshuffle at days 31, 61, and so on under the default 30-day interval. Supplier behavior types stay fixed. Public supplier_reshuffle events invalidate cached quotes; the controller requires search_products before buying again. Existing inventory keeps its acquisition cost.

Sources: src/vending/suppliers.py, src/vending/engine.py

## 09. Pricing trades margin against demand.

Demand is Poisson with a constant-elasticity price adjustment and a repeating day multiplier. The parameters are private. The diagram is qualitative, not a plot of hidden test demand. Product demand is independent with no substitution. Selling-price bounds are returned in the public catalog; the default range is 0.25 to 5 times reference, rounded to integer cents. Reference price is a comparison anchor, not a guarantee of the most profitable selling price.

Sources: src/vending/demand.py, src/vending/engine.py

## 10. Grow net assets, not just revenue.

All unsold units are valued at their actual acquisition cost, in storage and in machine slots. Purchasing exchanges equal cash and inventory value and does not create immediate profit. Raising retail prices does not revalue stock. Cash collection and inventory transfers preserve score. Selling recognizes revenue minus acquisition cost; completed-day fees reduce net assets. Fee debt is subtracted so failing to pay does not improve the score. The example is invented arithmetic, not a test result.

Sources: src/vending/scoring.py, src/vending/models.py, src/vending/engine.py

## 11. Business actions advance simulated time.

These costs are configurable; read observe.rules.durations. Public reads implemented as actions cost time, unlike HTTP status/result reads. Avoid repeatedly observing everything when a smaller state update is sufficient. Unknown actions and schema errors do not advance simulated time. End-day called at midnight advances a full day. All effects and incidental sales are returned in the common action envelope.

Sources: src/vending/config.py, src/vending/models.py, src/vending/engine.py

## 12. Replenish from stock. Adapt from evidence.

Targets round up and machine targets cannot exceed allocated capacity. Before enough history exists, target one slot and no storage reserve. Purchases cover only the shortfall after subtracting both machine and storage stock. Sellout quantities are lower bounds on demand. Price trials require three comparable, fully stocked days; hold for three comparable days and keep only improved average daily gross profit, otherwise revert. Exclude stockout days and restart comparisons after a supplier reshuffle. Negotiation permits two offers per supplier/product/day: 90% of listed price, then the returned counteroffer or listed price after no reply, subject to affordability and retail margin. Decisions should state quantities, expected margin, and reason. These are controller policy defaults, not universal engine rules.

Sources: .pi/lib/vending-controller.mjs, .pi/skills/vending-machine/SKILL.md

## 13. One tool. A controlled daily loop.

The extension owns the API URL and returned environment ID. The model has only the structured vending tool, with shell and file tools disabled. Create and observe are separate calls; initial selection and pricing precede replenishment. After settlement, collect positive machine cash, read machine and storage snapshots, refresh stale quotes, review pricing, then replenish or end the day. Crossed midnights and lifecycle changes are processed after every response. Rejected stocking does not advance the controller phase or alter stock. End-day remains possible when no valid affordable replenishment remains. On termination retrieve and record GET /result before deleting, without automatically creating another episode. Checkpoints are stored in Pi session entries; resume checks status and reconciles public snapshots.

Sources: .pi/extensions/vending-extension.js, .pi/lib/vending-controller.mjs, scripts/run_pi_agent.sh

## 14. Reliable execution protects your score.

The client retries an uncertain business request once with the same idempotency key (two attempts total), with a 15-second HTTP timeout. It never blindly repeats environment creation. Reusing a key with a changed payload conflicts. A terminal environment rejects later actions, including replays; retrieve its result instead. Persisted controller checkpoints support resume and snapshot reconciliation. Automatic follow-up continues normal completed turns while work remains; cancellation, provider errors, and repeated lack of progress can pause it. A resumed legacy trace without a checkpoint cannot safely reconstruct controller ownership.

Sources: .pi/lib/vending-client.mjs, .pi/extensions/vending-extension.js, src/vending/registry.py

## 15. Know which limits are actually enforced.

These values describe configs/environment.json and the current Pi starter. There is no implemented 100,000-token budget or 1,000-policy-call ceiling. A model context window is not an episode token budget. max_days is configurable and can be null; real expiry or fee failure can end an episode earlier. Organizers must define, implement, and calibrate any additional compute policy before evaluation.

Sources: configs/environment.json, scripts/run_pi_agent.sh, .pi/extensions/vending-extension.js

## 16. Distinguish recorded usage from attribution.

Pi JSONL traces preserve provider usage in model messages. The viewer aggregates input and output tokens and model-call counts, but does not attribute Pi usage to individual business actions or simulated days. Some legacy artifacts include those fields. Missing attribution should remain unavailable, not silently zero. Do not claim that current Pi implements token reservations or token-budget termination.

Sources: src/viewer/store.py, src/viewer/tokens.py

## 17. Start with one complete practice episode.

Prepare the Python environment with python3 -m pip install -e '.[test]' and install the Pi CLI with scripts/install_pi.sh. Start the service, model server, agent, and viewer in separate terminals in that order. The serving script requires locally downloaded weights and suitable GPU resources; inspect its configuration for your machine. For a shorter smoke episode, start the service with environments/smoke.json instead. The extension loads the skill and exposes only vending. Stop local service/model/viewer processes when finished. These commands are local development, not a private grading boundary.

Sources: README.md, start_env.sh, scripts/install_pi.sh, scripts/serve_qwen_vllm.sh, scripts/run_pi_agent.sh, scripts/view_runs.sh

## 18. Review the run, then improve one decision.

The viewer normalizes legacy curl records and structured vending results. Daily activity records purchases, costs, sales, and cash collection. Machine and storage displays are the last observed snapshots, with their timestamps, not guaranteed final inventory. Live profit requires enough trace history; terminal GET /result is authoritative. Unfinished means no final result was recorded and does not prove the process is alive. Pi per-action and per-day token attribution is unavailable. Use the viewer to diagnose redundant requests, fee liquidity, stockouts, and local blocks. Private evaluator data is not an additional policy tool.

Sources: src/viewer/api.py, src/viewer/store.py, README.md

## 19. Arrive with a reproducible harness.

This is a readiness checklist, not a finalized submission contract. Organizers must announce invocation, lifecycle ownership, model allowance, runtime/token policy, repeats, deadlines, and treatment of incomplete or infrastructure-failed runs. Preserve the Pi session JSONL, configuration, and policy version for auditability. Record terminal result retrieval and cleanup. Compare profitability across multiple seeds with equal wall-time budgets before claiming improvement.

Sources: README.md

## 20. REST lifecycle: create, act, retrieve, delete.

Known actions return 410 on ended environments and 409 on unavailable ones. Unknown IDs/actions are 404. Invalid JSON is 400; schema/identifier errors are 422. Domain refusals are ordinary 200 results. Status contains only state; it does not contain a score. Retrieve result before deletion. If the harness stops while running, a trusted service-side deletion snapshot supports truncated accounting; there is no post-delete result endpoint. Exactly who owns creation and deletion during the event must be specified in the organizer's test handoff. In the Pi starter, the extension owns this lifecycle and the environment ID; model calls use the vending tool rather than raw HTTP.

Sources: src/vending/api.py, src/vending/registry.py

## 21. Use the exact schemas. Money is integer cents.

Refer to src/vending/models.py for the shared typed schemas. Quantities and offer prices must be positive integers, and the configured quantity cap applies. Selling prices must respect the product's public bounds. Boolean values are not valid integer amounts. A 200 response includes action_id, state, sim_time, elapsed_minutes, result, events, metrics, and termination_reason, with score on terminal accepted actions. There is no arbitrary Python method dispatch or hidden evaluator action available to the policy. This table describes REST schemas. The Pi tool exposes a constrained subset with an action and typed payload; consult its returned permitted actions. unstock_items and wait are not exposed by the starter controller.

Sources: src/vending/models.py, src/vending/engine.py

## 22. One validated request. One logged outcome.

This is an invented interaction, not a revealed test quote. The response omits envelope fields and counteroffer terms for readability. To accept the counteroffer, submit a new make_offer action with a new idempotency key because its payload differs. Only retries of the identical original request reuse purchase-0001. Log the actual full response and preserve its incidental sales events.

Sources: src/vending/models.py, src/vending/engine.py, .pi/lib/vending-client.mjs
