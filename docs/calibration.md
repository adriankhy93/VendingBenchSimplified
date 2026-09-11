# Calibration evidence

Measured on 2026-09-11 using Python 3.12.3, NumPy 2.2.6, a local Uvicorn process,
and actual HTTP requests. Scenario `smoke-v1`, version `1.0-proposal`, seeds 0/1/2,
14 simulated days, 120-second deadline per episode, 1,000-call ceiling. These are
smoke results, not a two-hour model benchmark. All nine episodes reached their
explicit smoke cap. Scripted policies consumed no model tokens.

| Policy | Mean final score | Population standard deviation | Total wall seconds (3 runs) |
| --- | ---: | ---: | ---: |
| Idle | $472.00 | $0.00 | 2.18 |
| Listed price | $1,010.09 | $19.53 | 4.31 |
| Negotiating | $1,137.89 | $33.52 | 4.61 |

Negotiation improved all three matched-seed scores; the mean improvement was
$127.81. This supports retaining inexpensive supplier policies for the MVP, but
three seeds and two fixed policies do not establish robust benchmark difficulty.
The selling baseline uses 1.5 times public reference prices and replenishes from
observations; it sees neither latent demand nor private supplier categories.

Mean HTTP action latency was about 5.5–6.0 ms for operating policies and 48–51 ms
for idle end-day actions, which simulate a whole day. Maximum observed action
latency was 63 ms. Service peak RSS was 72,952 KiB; the measurement runner's peak
RSS was 115,388 KiB. Measurements include startup imports and local machine load,
and are not portable performance guarantees. Raw configuration, per-seed results,
and resource values are in [smoke-results.json](smoke-results.json).

The acceptance suite covers deterministic replay, action partitioning, a fixed-seed
Poisson calibration with six-standard-deviation tolerance, duplicate-slot demand,
FIFO transfers, cash conservation, fees/arrears, continuation beyond day 30,
provider usage and native tool pairs, bounded context, inference watchdogs,
retry idempotency, exact deadline rollback, races, terminal retrieval, and cleanup.

Before freezing a benchmark release, select a model and run fixed-seed two-hour
experiments on the intended compute. Measure actual input/output tokens, cost,
simulated days, and budget truncation rates; the conservative byte-based input
reservation can stop early under a 100,000-token cap. Tune context size, call limits,
and any changed budgets explicitly and record them in run configuration. Also
compare multiple pricing policies and larger seed suites. No paid model cost or
full-duration throughput claim is made from these smoke measurements.
