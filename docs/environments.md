# Environment configuration

`configs/environment.json` is the complete editable input. Its two top-level fields
are `seed` and `scenario`. Unspecified scenario fields retain their defaults, but the
checked-in input spells them out so experiments can be reviewed. Unknown fields,
invalid IDs, invalid quantities, and inconsistent limits are rejected before generation.

| Field in `scenario` | Meaning |
| --- | --- |
| `scenario_id`, `version` | Benchmark/smoke mode and experiment version label. Use a distinct version when tuning settings. |
| `runtime_seconds`, `max_days` | Real lifetime and optional simulated-day cap. A cap is permitted only with `scenario_id: "smoke-v1"`. |
| `starting_cash_cents` | Spendable cash at the start of each episode. |
| `daily_fee_cents`, `failure_limit` | Daily fee (zero allowed) and consecutive missed fees before termination. |
| `machine_rows`, `slots_per_row`, `slot_capacity` | Machine shape and units per slot. IDs are generated as `r1s1`, `r1s2`, etc. |
| `quantity_cap` | Maximum units in a purchase, stock, or unstock request. |
| `retention_seconds` | How long the service keeps a terminal result. |
| `tick_minutes` | Demand sampling interval. Must divide a 1,440-minute day. |
| `durations` | Minutes for each action, divisible by the tick interval. `end_day: 0` is the sentinel for advancing to the next midnight; other values must be positive. |
| `day_multipliers` | Repeating demand cycle, starting on day one. Any nonempty length; zero disables demand on that cycle day. |
| `min_price_percent`, `max_price_percent` | Selling-price bounds as integer percentages of reference. The lower bound rounds up and the upper bound down to cents. |
| `products` | List of `{id, name, reference_price_cents, base_demand, elasticity}`. Change its length to change the number of products. |
| `suppliers` | List of `{id, kind}`. Kinds are `patient`, `impatient`, and `pushy-patient`. Change the list to change supplier counts and type distribution. |
| `category_weights` | Relative weights for `winner`, `loser`, and `balanced` supplier/product pairs. |
| `category_cost_percent` | Minimum acquisition cost for each category, as a percentage of reference before random variation. |
| `cost_variation_min_ppm`, `cost_variation_max_ppm` | Inclusive random cost multiplier bounds, in parts per million. `980000`–`1020000` means 0.98–1.02. |
| `listed_price_percent` | Listed cost as a percentage of minimum, rounded up to cents; at least 100. |
| `supplier_reshuffle_days` | Positive integer interval, default 30. Regenerates pair categories and prices at the start of days 31, 61, etc. |
| `supplier_quotes` | Optional explicit quote overrides, described below. |

For the service started with `bash start_env.sh configs/environment.json`, set
`scenario.runtime_seconds` in that file. It is currently `3600` (one real hour).
The timer starts when `POST /env` creates each environment, not when the service
starts, and includes time spent waiting for the agent. At the deadline, new actions
return HTTP 410; actions still executing are discarded instead of committed. Idle
environments are finalized by the background sweep (every second). The terminal
result is available from `GET /env/{env_id}/result` with termination reason
`real_deadline` until retention expires. Restart the service and create a new
environment to apply a changed configuration. Saved environments use their own
`scenario.runtime_seconds` value.

`seed` is an integer from 0 through 2^63−1. Monetary inputs are integer cents;
percentages and variation inputs are integers, so currency calculations remain exact.
Product demand/elasticity and cycle multipliers accept finite numbers. Catalogs must
be nonempty with unique IDs. With one product, pushy suppliers omit the suggestion
because there is no alternative product.

Weights allocate all `number_of_products × number_of_suppliers` pairs using largest
remainders, breaking ties in winner/loser/balanced order, then a seeded shuffle. Thus
20/20/60 yields exactly those counts for 100 pairs and scales to other catalog sizes.
At least one weight must be positive. Generated minimum costs round to the nearest
cent, with a one-cent floor.

Every `supplier_reshuffle_days` completed days, a running environment reshuffles
pair categories and regenerates minimum and listed prices. Category counts follow
the same weights in every generated period; individual pairs may retain their
category by chance. The seed and period determine the market independently of
how time is advanced. Supplier policies, selling prices, and inventory acquisition
costs remain unchanged. Actions use the market at their start; observations and
search results show the market after time advances. A public `supplier_reshuffle`
event announces the new day without revealing private categories or minimums.
No reshuffle occurs after the environment ends.

To set specific supplier prices instead of generating them, put entries in
`scenario.supplier_quotes`, for example:

```json
[
  {
    "supplier_id": "s01",
    "product_id": "p01",
    "category": "winner",
    "minimum_cents": 70,
    "listed_cents": 95
  }
]
```

You can override any subset of pairs; the rest are generated normally. Overrides
must reference existing IDs and have `0 < minimum_cents <= listed_cents`. Overrides
can change the initial category distribution. Overrides apply only to the initial
30-day period (or configured interval); later periods use `category_weights` and
`category_cost_percent` with seeded variation. Generation writes every resolved pair
into the saved definition, so its prices are inspectable and independent of future
fixture edits. The saved file is evaluator data and includes private market parameters.

The saved format is `{format_version: 1, name, seed, scenario}`. Files live at
`environments/<name>.json`; names accept letters, digits, hyphens, and underscores.
Generated files are reusable initial definitions, not checkpoints: inventory starts
empty, machine cash and debt start at zero, and each run gets a new ID and deadline.
Business rules such as FIFO accounting, acquisition-cost valuation, Poisson demand,
and supplier negotiation policies are simulation semantics, rather than numeric
configuration switches. A day remains 1,440 minutes.

`POST /env` can select one with `{"environment_name":"my-market"}`. An optional
`environment_sha256` verifies the exact file. Scenario/seed/runtime overrides alongside
a saved name return `422`; a missing saved name returns `404`; a hash mismatch returns
`409`. Running episodes hold their own configuration and are unaffected by later file
edits. Run artifacts record the selected name, hash, effective definition, and budgets.
For comparisons across different seeds, generate separate names; the existing seed-suite
command continues to operate on unsaved scenarios.

Service transport settings (host, port, request-body limit) and harness settings
(model, prompt, tokens, timeouts) are separate from the simulated environment. The
`run_environment.sh` script manages the service and accepts ordinary harness arguments.
