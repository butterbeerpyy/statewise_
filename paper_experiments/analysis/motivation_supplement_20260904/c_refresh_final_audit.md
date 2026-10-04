# Corrected Live Refresh validity audit

This closes the seven questions raised after the invalid first C endpoint. The
audited implementation is the exact code fingerprinted by the corrected run.

1. **Does Refresh read the live correct value?** Yes for fixture-observable
   state. It reads fixture files, Git status, each registered state-verifier
   fixture, and package existence across the fixture environments. The earlier
   implementation omitted the last two categories; that endpoint is quarantined.
2. **Does the planner receive the observations?** Yes. The complete observation
   array is stored under `live_refresh.final_replan_observation` and passed as
   `observation=` to `planner.propose_action`.
3. **May the planner replan?** Yes. Every corrected episode starts with one
   explicit `live_refresh_replan`, and the ordinary continuation can replan after
   subsequent action observations.
4. **Does Refresh overwrite user-owned facts?** No. It performs no persistent
   write (`repair_performed=false`, initial and final memory unchanged). This
   also means it cannot carry a correction to later episodes.
5. **Does the correct fixture match correct memory?** Yes. The primary
   `correct_state.value` equals `ground_truth_state.value` in 150/150 cases. The
   condition is semantic-value correct, although freshness metadata is often
   expired under StateWise's validity contract.
6. **Was prior unsafe behavior a scope error or baseline bug?** Baseline bug.
   The old baseline missed package-existence evidence and then reinstalled an
   already-present protected package. The corrected 300-cell Refresh matrix has
   0 unsafe actions in both conditions.
7. **Are evidence access and action budget fair?** For machine-observable fixture
   state, Refresh now receives the equivalent read-only evidence. Both methods
   retain an eight-step task-action budget; preparatory read-only probes do not
   consume it. Calls are intentionally not forced equal: StateWise performs
   attribution and validation and therefore costs much more. Refresh cannot ask
   for user-owned facts, which is a method-boundary difference rather than hidden
   tool access.

## Recovery and tests

- Corrected main run: 295 successful cells, 5 provider failures.
- Provider failure: `400 unknown provider for model gpt-5.6-sol`, incorrectly
  categorized by the manager as non-retryable; each failed after one attempt.
- Recovery: 8/8 cells complete for the four affected cases. Only the five
  missing cells are merged into the analysis.
- Focused tests: `14 passed` for
  `test_live_refresh_conditions.py` and `test_action_runtime_contract.py` in the
  `nightly` conda environment.

## Evidence

- Implementation:
  `scaffold\statewise\experiments\live_refresh_baseline.py`
- Corrected manifest:
  `artifacts/runs/mostly_correct_refresh_fixed150_api_02_gpt56sol_20260903_r1\manifest.json`
- Recovery manifest:
  `artifacts/runs/mostly_correct_refresh_fixed_recovery4_api_02_gpt56sol_20260904_r1\manifest.json`
- Merged analysis: `results.json` and `per_episode.csv` in this directory.

