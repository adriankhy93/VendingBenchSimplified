# Organizer checklist — before presenting

The deck is ready for a participant briefing. It intentionally labels current
numeric defaults and unconfirmed event policies. Finalize the items below before
turning the briefing into binding evaluation instructions.

1. **Public test rules.** Confirm starting cash, fees, machine capacity, runtime,
   token budget, policy-call limits, and any exposed configuration changes. Slides
   5, 6, 11, and 14 currently show repository defaults. Keep benchmark runs free of a
   simulated-day cap unless you explicitly change the event specification.
2. **Model and compute policy.** Announce allowed providers/models, credentials,
   compute resources, network access, tool allowance, and whether model choice is
   itself part of the competition. The deck does not select a mandatory model.
3. **Submission contract.** Specify the repository/archive/container format, exact
   entry point, dependencies, configuration, logging fields, deadline, and delivery
   location. Slide 18 is a readiness checklist, not an implemented grading adapter.
4. **Test handoff and lifecycle ownership.** Decide whether the coordinator creates
   the environment and passes an ID, or a trusted runner creates it. Specify who
   polls status, retrieves the result, and deletes the environment. The current
   starter runner owns its own creation and cleanup; it does not expose a CLI for
   attaching a participant submission to a coordinator-created ID.
5. **Protect the test definition.** Keep the saved test JSON, seed, private service
   events, and evaluator artifacts outside participant-accessible filesystems.
   The current service is a local MVP without authentication. A deployment boundary
   and orchestration controls are needed to enforce a private test. Do not use the
   local saved-environment convenience command as if it enforced that boundary:
   it reads the saved definition into the runner's evaluator metadata.
6. **Evaluation procedure.** Freeze the chosen definition and record its hash.
   Start fresh independent episodes. Publish repeat counts, infrastructure conditions,
   treatment of budget-truncated runs and unavailable environments, and tie-breaks.
   The engine provides a score; the repository does not define an official event
   leaderboard policy. If truncated scores are used, obtain trusted pre-deletion
   summaries rather than treating a last public snapshot as a final score.
7. **Release a separate practice environment.** The included `smoke` definition is
   suitable for verifying a complete development loop. Do not disclose the private
   test definition as part of the participant briefing or a live dashboard demo.
8. **Verify the event budget on the intended model.** Current defaults of two hours,
   approximately 100,000 input-plus-output tokens, and 1,000 policy calls are not
   backed by a full-duration paid-model calibration. Token reservations can stop a
   run early. Test the final limits and explain what counts toward them.

Suggested presentation: slides 1–18 in about 20 minutes, then questions. Slides
19–21 provide endpoint and schema references for implementation discussions.
Presenter notes cite repository implementation files for each claim.
