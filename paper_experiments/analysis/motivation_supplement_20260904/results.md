# Motivation experiments A/B/C — final handoff

## Executive result

- **A, real trajectories:** 100/100 sampled SWE-chat sessions were annotated.
  The model marked 60 complete causal chains; a deterministic audit retained 40
  candidates with valid evidence references, chronology, and an observed
  consequence. These 40 contain 18 user corrections, 17 task failures, and 5
  unsafe/wrong-scope mutations. This establishes observed existence, but remains
  a single-model pilot rather than a population prevalence estimate.
  The planned 400-session scale-up was not launched because the independent-
  annotator acceptance gate is unmet.
- **B, StateWise versus complete Live Refresh:** on 150 corrupted-state cases,
  StateWise reaches 133/150 (88.7%) correct outcomes and Live Refresh 125/150
  (83.3%), both with 0 unsafe actions. The paired gap is +5.3 pp (12/4
  discordant pairs, bootstrap 95% CI [0.0, 10.7], exact McNemar p=0.0768).
  This is directional, not decisive. Refresh costs 1.82 calls/episode against
  16.59 for StateWise.
- **C, mostly-correct state:** StateWise reaches 132/150 (88.0%), complete Live
  Refresh 127/150 (84.7%), and the base agent 106/150 (70.7%), all with 0 unsafe
  actions. StateWise versus base is +17.3 pp (CI [10.7, 24.7], p=6.16e-6);
  StateWise versus Refresh is +3.3 pp (CI [-1.3, 8.0], p=0.267). StateWise
  writes persistent state in 108/150 episodes, but 99/108 writes preserve the
  exact semantic value and refresh metadata/provenance.

## Final B/C table

Percentages are over 150 episodes except Should-Act, whose denominator is 105.
Interactions combine state questions and permission prompts.

| State | Method | Overall | Should-Act | Unsafe | Repair | Interactions/Ep. | Calls/Ep. |
|---|---|---:|---:|---:|---:|---:|---:|
| Corrupted | Base agent | 36.7 | 11.4 | 42.7 | 0.0 | 0.01 | 2.05 |
| Corrupted | Live Refresh | 83.3 | 78.1 | 0.0 | 0.0 | 0.01 | 1.82 |
| Corrupted | StateWise | 88.7 | 84.8 | 0.0 | 72.7 | 0.04 | 16.59 |
| Mostly correct | Base agent | 70.7 | 58.1 | 0.0 | 0.0 | 0.00 | 3.75 |
| Mostly correct | Live Refresh | 84.7 | 78.1 | 0.0 | 0.0 | 0.00 | 2.73 |
| Mostly correct | StateWise | 88.0 | 82.9 | 0.0 | 72.0 | 0.03 | 17.61 |

## What is and is not supported

1. **Supported:** persistent operational-state failure chains occur in sampled
   real coding trajectories. The audit contains exact source-turn evidence and
   several unambiguous wrong-target mutations.
2. **Supported:** controlled state corruption is strongly damaging, and both a
   complete live refresh and StateWise recover most of that damage.
3. **Not established:** StateWise is universally or significantly better than
   complete Live Refresh on the 150-case cross-sectional pool. The direction is
   positive, but p=0.0768 and Refresh is much cheaper.
4. **Supported:** with semantically correct target values, StateWise improves
   significantly over the untreated base agent.
5. **Not established:** that mostly-correct gain is uniquely due to persistent
   repair. Complete Refresh captures most of it, and extra inference is not
   compute-matched.
6. **Supported by the existing longitudinal RQ5:** a scoped repair can be reused
   after the triggering episode. This remains the clearest empirical property
   that a stateless refresh cannot supply.

## Data provenance

- A frozen sample: `experiments/observation_swe_chat/pilot100/sample_manifest.json`
- A labels: `experiments/observation_swe_chat/model_annotations/annotation_codex.csv`
- A audit: `experiments/observation_swe_chat/audit/audit_summary.json`
- A exact positive evidence: `experiments/observation_swe_chat/audit/positive_evidence.json`
- Frozen B/C StateWise and base cells:
  `artifacts/runs/mostly_correct_formal150_api_02_gpt56sol_20260903_r1`
- Corrected Live Refresh main run:
  `artifacts/runs/mostly_correct_refresh_fixed150_api_02_gpt56sol_20260903_r1`
- Five-cell API recovery source (four cases, both arms, 8/8 complete):
  `artifacts/runs/mostly_correct_refresh_fixed_recovery4_api_02_gpt56sol_20260904_r1`
- Merged per-episode data: `per_episode.csv`
- Aggregate metrics: `metrics.csv`
- Paired statistics: `paired_contrasts.csv`
- Domain/operator slices: `stratified_statewise_vs_refresh.csv`
- Corruption-mixture sensitivity: `mixed_workload.csv`
- Machine-readable run mapping: `results.json`

The five replaced cells all failed with api_02's transient `unknown provider
for model gpt-5.6-sol` response and had no evaluable method outcome. The recovery
run is complete and pairing-valid. No successful original Refresh cell was
replaced.

## Paper outputs

- New chapter: `paper/fse2027/sections/motivation.tex`
- Figure source: `paper/fse2027/figures/fig_motivation_evidence.pdf`
- Raster preview: `paper/fse2027/figures/fig_motivation_evidence.png`
