# Organizer checklist — before presenting

The deck describes the current implementation and public practice configuration.
Finalize these event decisions before treating it as binding evaluation guidance.

1. **Public rules.** Confirm cash, fees, capacity, durations, runtime, optional day
   cap, and supplier reshuffle interval. Practice settings are one hour, 365 days,
   and 30-day reshuffles. The first runtime, day, or fee-failure limit ends a run.
2. **Model and compute policy.** Announce allowed models, hardware, network access,
   and tool allowance. The Pi starter exposes only `vending`. It records usage but
   has no total token budget or model-call ceiling. Implement and calibrate any
   additional evaluation limits; a context window is not a run token budget.
3. **Submission contract.** Specify packaging, entry point, dependencies, logging,
   deadline, and delivery location. Slide 19 is a readiness checklist, not a grading
   adapter. Preserve session JSONL, configuration, and policy version.
4. **Lifecycle ownership.** The starter extension creates the episode, owns its
   environment ID, retrieves the terminal result, and deletes it. Resumption uses
   persisted controller checkpoints and public reconciliation. Define a separate
   handoff if the coordinator must create participant environments.
5. **Private test access.** Keep evaluation definitions, seeds, and private service
   artifacts outside participant-accessible filesystems. The local service has no
   authentication; deployment controls must enforce this boundary. Local practice
   scripts are not a private evaluation interface.
6. **Evaluation procedure.** Freeze and hash the selected definition. Use fresh
   episodes, multiple seeds and equal wall-time budgets for policy comparisons.
   Publish repeats, tie-breaks, and handling of interruptions or infrastructure
   failures. Use authoritative terminal results for completed-run rankings; a live
   profit estimate or last observed inventory is not a terminal result.
7. **Practice and demonstrations.** Test the commands on the event hardware with
   model weights installed. A service started with `environments/smoke.json` gives
   a short practice run. Demonstrate daily activity, storage snapshots, and final
   results without revealing private evaluation files.
8. **Artifact review.** Rebuild after content edits, run the presentation tests,
   inspect all PDF pages, and open the PPTX in the presentation application with
   DejaVu fonts installed. Confirm links and event-specific instructions.

Present slides 1–19 in about 20 minutes, then take questions. Slides 20–22 provide
REST lifecycle and payload references; the Pi model uses the structured tool.
Speaker notes cite implementation files. Controller policies are initial heuristics,
and no profitability improvement has yet been established by the presentation.
