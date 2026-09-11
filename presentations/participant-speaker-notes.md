# Participant briefing — speaker notes

21 slides: 18-slide core briefing plus 3 reference slides. Approximate speaking time: 20 minutes plus questions.

## 01. Build the harness. Run the business.

Welcome participants. The deliverable is an agent harness: the software that turns model decisions into reliable business actions. This briefing is based on the current implementation. Event-specific submission and model policies are still to be announced. Suggested presentation time: about 20 minutes plus questions; reference slides are optional.

Sources: README.md, plan.md sections 1, 9

## 02. You design the harness. We fix the market.

A harness is more than a prompt. It includes orchestration, memory, provider integration, and error handling. Participants should not change the test definition or the simulation to improve a score. Model eligibility, compute allowances, and the submission interface will be announced by the organizers; do not imply they have already been finalized.

Sources: src/harness/runner.py, src/vending/environments.py

## 03. One saved definition. A fresh episode each run.

A pre-generated environment is an initial definition, not a running checkpoint. Each episode gets a separate environment ID and starts empty. Identical definitions and seeds reproduce the market; action choices change sales opportunities. Identical action sequences reproduce the business simulation until real-time expiry intervenes. The number of official repeats, compute conditions, and tie-breaks remain organizer decisions. Freeze these before comparing submissions.

Sources: src/vending/environments.py, src/vending/registry.py, docs/environments.md

## 04. Learn from quotes and realized sales.

Observations expose the complete public catalog and initial listed quotes. Participants can discover costs by negotiating and demand by observing sales. Do not distribute the private test JSON, private service artifacts, or evaluator configuration to participant harnesses. The local MVP does not enforce this boundary through authentication or a sandbox; organizers must enforce it through deployment and file access. This operational point is expanded in the organizer checklist, not presented as an already implemented security guarantee.

Sources: src/vending/engine.py: catalog and observe, plan.md sections 3, 9

## 05. A small business with tight operating constraints.

All numeric settings here are current defaults, not guaranteed hidden-test settings. Catalog size, fees, machine shape, capacity, and action costs are configurable. The engine requires a positive selling price before stocking. There is no separate logistics pipeline. Purchases and inventory transfers are all-or-nothing.

Sources: src/vending/config.py, src/vending/engine.py

## 06. There are two clocks to manage.

The default demand tick is five minutes. An action applies its immediate effects first, then advances time and resolves sales. Status/result reads do not advance business time. The separate harness watchdog is slightly longer than the environment runtime to allow cleanup. Do not confuse that grace period with extra business time. The environment may terminate earlier after repeated fee failures.

Sources: src/vending/engine.py: execute and advance, src/vending/registry.py, src/harness/runner.py

## 07. Keep the operating loop moving.

Accepted offers debit spendable cash and add a storage lot immediately. Counteroffers do neither. At midnight, available spendable cash pays existing fee arrears before the current fee; partial payment creates debt. A current fee not fully paid increments the failure streak. A fully paid current fee resets it. Uncollected machine cash cannot pay the fee automatically. Multiple slots raise availability but do not multiply demand.

Sources: src/vending/engine.py: apply and advance

## 08. Negotiation produces structured outcomes.

Suppliers follow deterministic policies. Patient suppliers counter out-of-range offers, impatient suppliers can return no_reply, and pushy-patient suppliers may add an upsell. This deck does not disclose particular supplier types, pair minimums, or category assignments in the test. Supplier stock is unlimited, but the quantity cap and spendable cash limit purchases. A no_reply outcome is not a network timeout.

Sources: src/vending/suppliers.py, src/vending/engine.py: make_offer

## 09. Pricing trades margin against demand.

Demand is Poisson with a constant-elasticity price adjustment and a repeating day multiplier. The parameters are private. The diagram is qualitative, not a plot of hidden test demand. Product demand is independent with no substitution. Selling-price bounds are returned in the public catalog; the default range is 0.25 to 5 times reference, rounded to integer cents. Reference price is a comparison anchor, not a guarantee of the most profitable selling price.

Sources: src/vending/demand.py, src/vending/engine.py: bounds and advance

## 10. Grow net assets, not just revenue.

All unsold units are valued at their actual acquisition cost, in storage and in machine slots. Purchasing exchanges equal cash and inventory value and does not create immediate profit. Raising retail prices does not revalue stock. Cash collection and inventory transfers preserve score. Selling recognizes revenue minus acquisition cost; completed-day fees reduce net assets. Fee debt is subtracted so failing to pay does not improve the score. The example is invented arithmetic, not a test result.

Sources: src/vending/scoring.py, src/vending/models.py: FIFO transfer, src/vending/engine.py

## 11. Every tool call has an operating cost.

These costs are configurable; read observe.rules.durations. Public reads implemented as actions cost time, unlike HTTP status/result reads. Avoid repeatedly observing everything when a smaller state update is sufficient. Unknown actions and schema errors do not advance simulated time. End-day called at midnight advances a full day. All effects and incidental sales are returned in the common action envelope.

Sources: src/vending/config.py: DURATIONS, src/vending/models.py: ACTIONS, src/vending/engine.py

## 12. Build a loop that stays useful under pressure.

The starter provides an HTTP client, three scripted policies, bounded deterministic context summaries, isolated Markdown memory, a runner, and an optional model adapter. Teams can redesign the harness rather than inherit every starter choice. Keep at most one environment action in flight. If a provider returns multiple tool calls, process them serially and stop on termination. A local memory write uses model tokens but no simulated minutes. Remember the model is a policy component inside a controlled execution loop.

Sources: src/harness/runner.py, src/harness/context.py, src/harness/agents.py

## 13. Reliable execution protects your score.

An identical action and payload with the same idempotency key replays while the environment is running, without a second purchase or time advance. A changed payload conflicts. After termination, known actions are rejected even for a replay key. Unknown actions remain 404. For 409, distinguish idempotency conflicts from unavailable lifecycle state by inspecting the error code and status. The current client retries transport errors at most twice; creation has no idempotency contract and should not be blindly retried. Timeout/expiry can occur during inference, so do not assume a tool call remains eligible after a long model response.

Sources: src/harness/client.py, src/harness/watchdog.py, src/vending/registry.py

## 14. Plan for three separate resource limits.

The starter uses a conservative UTF-8 byte-based input reservation plus overhead. It can stop early instead of knowingly exceeding the budget. The 1,000 ceiling counts policy calls, not necessarily environment actions; the initialization observe is separate. The 100,000 target and two-hour duration have not been calibrated through a paid full-duration model run. Do not present them as a measured performance guarantee or a finalized event rule. Full-run score and incomplete/truncated diagnostics should remain distinguishable.

Sources: src/harness/runner.py: RunConfig and run, docs/calibration.md

## 15. Measure tokens where decisions happen.

An action that crosses midnight retains its model cost on the day inference began. Invalid/empty responses, local memory writes, and failures still count toward token usage. A call which is never executed after a stop is logged as a no-action record so totals reconcile. The new action fields are start_sim_time and token_usage, with model_call and attribution. Usage records carry simulated decision time; summary.usage.tokens_by_day stores daily totals. Input token usage includes provider-reported cached input where available.

Sources: src/harness/usage.py, src/harness/runner.py, src/viewer/tokens.py

## 16. Start with one complete practice episode.

Run these commands from the repository root with a Python environment activated. Use python3 -m venv .venv first if appropriate. The test extra contains pytest, not the optional model SDK. Idle, listed, and negotiating policies need no model credentials. Teams implementing their own harness can reuse typed action schemas and the HTTP client. Private test definitions should remain with the evaluator; the saved-environment convenience command reads local definition files and is a development workflow, not an isolated grading boundary.

Sources: README.md, scripts/run_environment.sh, scripts/view_runs.sh, pyproject.toml

## 17. Review the run, then improve one decision.

Use the dashboard to find one concrete failure mode: redundant observations, unfunded purchases, too little fee liquidity, slow decisions, or context growing faster than useful progress. The machine display is the last observed snapshot, not a reconstructed final inventory. Unfinished means no final summary was written and does not prove the process is still alive. Truncated scores can come from trusted pre-deletion snapshots and remain explicitly incomplete. A human may inspect practice configuration, but the test evaluator view is not an extra tool for participant policies.

Sources: src/viewer/api.py, src/viewer/store.py, README.md

## 18. Arrive with a reproducible harness.

This is a recommended readiness checklist, not a finalized submission contract. Organizers must announce the invocation protocol, lifecycle ownership, model allowance, runtime/token enforcement, test repeats, deadline, and treatment of truncated or infrastructure-failed runs. The supplied runner writes config.json, actions.jsonl, usage.jsonl, memory.md, and summary.json; participant harnesses should preserve equivalent auditability under the final contract. Close the core briefing by inviting questions about the environment interface and the harness boundary.

Sources: plan.md section 9, src/harness/runner.py, README.md

## 19. Create or receive an ID, act, then retrieve results.

Known actions return 410 on ended environments and 409 on unavailable ones. Unknown IDs/actions are 404. Invalid JSON is 400; schema/identifier errors are 422. Domain refusals are ordinary 200 results. Status contains only state; it does not contain a score. Retrieve result before deletion. If the harness stops while running, a trusted service-side deletion snapshot supports truncated accounting; there is no post-delete result endpoint. Exactly who owns creation and deletion during the event must be specified in the organizer's test handoff.

Sources: src/vending/api.py, src/vending/registry.py

## 20. Use the exact schemas. Money is integer cents.

Refer to src/vending/models.py for the shared typed schemas. Quantities and offer prices must be positive integers, and the configured quantity cap applies. Selling prices must respect the product's public bounds. Boolean values are not valid integer amounts. A 200 response includes action_id, state, sim_time, elapsed_minutes, result, events, metrics, and termination_reason, with score on terminal accepted actions. There is no arbitrary Python method dispatch or hidden evaluator action available to the policy.

Sources: src/vending/models.py, src/vending/engine.py: validate

## 21. One validated request. One logged outcome.

This is an invented interaction, not a revealed test quote. The response omits envelope fields and counteroffer terms for readability. To accept the counteroffer, submit a new make_offer action with a new idempotency key because its payload differs. Only retries of the identical original request reuse purchase-0001. Log the actual full response and preserve its incidental sales events.

Sources: src/vending/models.py, src/vending/engine.py, src/harness/client.py
