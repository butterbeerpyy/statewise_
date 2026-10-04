# Claim-Based Evidence Plan

## Claim mapping

| Claim | Evidence | Reporting role | Figure decision |
|---|---|---|---|
| Premise repair separates capability from safety | Primary 150-case matrix (`tab:main`) | Headline | Split outcome views: two-panel memory/action figure plus one-panel system figure |
| Action-time approval cannot repair a persistent premise | Action-layer rows in the primary matrix | Headline | Paired visually with memory controls beside RQ2 |
| Attribution, resolution, persistent repair, and typed grounding drive average recovery | RQ4 paired general-benchmark ablation (`tab:rq4`) | Headline recovery-mechanism evidence | Paired-loss effect plot with 95% confidence intervals |
| Repair persists across later tasks | RQ5 four-task sequences (`tab:rq5-arms`) | Headline longitudinal evidence | One expanded outcome/persistence/cost table; no separate figure |
| The mechanism survives a same-key cross-scope decoy | Cross-scope r2, 150 new overlay episodes | Extended validation | Report as a compact table and prose; do not pool with headline |
| Performance transfers to newly materialized external cases | Held-out 40 x 4, 160 episodes | Extended stress validation | Report as a compact table and explicit limitation; do not pool with headline |

## Two priority figures

1. `fig_claim_memory_action` and `fig_claim_system_safeguards`: the former keeps
   the two causally adjacent memory/action panels together; the latter moves the
   system comparison beside RQ3. Both separate capability from no-violation rates
   without stacking three panels in one oversized figure.
2. `fig_claim_component_ablation`: a paired effect plot with 95% confidence
   intervals for the four diagnosis and repair removals. The RQ4 table reports
   absolute outcomes and inference cost, so the figure contributes uncertainty
   rather than repeating the table. Replanning and Residual Gate remain disclosed
   as exploratory variants in the appendix.

## Data policy

- Headline tables use the frozen 150-case matrix and the registered RQ4/RQ5
  contracts only.
- Cross-scope and external-validity runs are not pooled into headline rates.
- For every run, statistics use only the final successful attempt for each
  logical episode. Infrastructure and response-contract failures remain in
  provenance and never become method failures.
- Attribution is conditional on its evaluable denominator; missing targets are
  reported as coverage, not as zero.

## New extended-validation values

| Run | Arm | Cases | Objective correctness | Safety violations | Role |
|---|---|---:|---:|---:|---|
| Cross-scope r2 | StateWise | 150 | 69.3% | 0.0% | same-key out-of-scope decoy |
| Held-out 40 x 4 | StateWise | 40 | 0.0% | 7.5% | external stress set |
| Held-out 40 x 4 | Corrupted | 40 | 0.0% | 2.5% | external stress set |
| Held-out 40 x 4 | Rationale approval | 40 | 5.0% | 0.0% | external stress set |
| Held-out 40 x 4 | Safety Sentry | 40 | 2.5% | 0.0% | external stress set |

The held-out stress set is deliberately not presented as a transfer win: all
arms perform poorly, and StateWise's result exposes a current generalization
limit rather than supporting a stronger headline claim.
