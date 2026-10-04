# Data availability review

The earlier code-only export did not support the stated availability claim. This release includes each of the five named artifact categories: workbooks, run manifests, case definitions, episode audit bundles, and source code. This public release directory has not yet been pushed to its new repository or checked through a public URL.

## Supplied evidence

| Category | Location | Coverage |
| --- | --- | --- |
| Source code | `scaffold/`, `paper_experiments/`, `dataset_design/` | Revised runnable code; partial matching historical file versions in `artifacts/source_versions/` |
| Workbooks | `paper_experiments/results/` | 11 workbooks; numeric cells preserved, author properties/comments/hyperlinks removed |
| Run manifests | `artifacts/runs/*/manifest.json` | 65 historical runs; original hashes and scientific fingerprints retained as historical provenance |
| Case definitions | `scaffold/experiments/`, `artifacts/datasets/` | Current controlled definitions and six historical snapshot groups |
| Episode audits | `artifacts/runs/*/episodes/` | 5,718 stored episodes or sequences, including attempts and observed outcomes; indexes link files and release hashes |

Recovered local copies of a previously missing recovery run are included. Earlier audit notes are historical snapshots and do not imply that their missing-log finding has been recomputed under the recovered pool. Published interaction estimates based on the earlier pool remain historical; revised estimates require a separate analysis.

## Version and claim limits

The paper's primary historical percentages (80.7% correct memory, 38.7% corrupted memory, 45.3% no memory, 31.3% clarification) match the included workbook. The locked Full StateWise count is 140/150. These are data-consistency checks, not validation of the revised baseline's model performance.

The baseline builder was not recorded in measurement fingerprints for these selected historical runs. The new code removes a hidden StateWise state-binding gate from untreated controls. The two deterministic failures were reproduced in the saved pre-review implementation; the available fingerprints do not establish whether that same implementation produced the paper's historical results. A separate experiment is required before claiming that the revised implementation reproduces those published baseline comparisons. Some explicitly recorded historical source file versions are also unavailable. These gaps are listed in `historical_source_coverage.json`; no source version was invented to fill a gap.

The source manifest recovered from an adjacent manuscript version verifies all eight listed original inputs. The current manuscript has no equivalent source manifest. Table text and selected numerical anchors are checked separately; this release does not assert that every figure, appendix result, observational study, or bootstrap interval can be regenerated from the current source.

This is a separate public release prepared after the anonymous submission. Files being available locally does not establish that the new public repository contains them. Verify the uploaded repository's workbook, manifest, case, and episode links before asserting repository availability. The submitted anonymous package and manuscript are not changed by this preparation.

The appendix's old `final/reselts/rq1--rq5` location also needs updating: normalized workbooks are under `paper_experiments/results/`, while run manifests and audit bundles are under `artifacts/runs/`. The current manuscript's seven table snapshots and their related evidence mappings are supplied in `artifacts/paper_tables/` and `table_source_manifest.json`.

## Availability wording after uploading and checking the public repository

> Anonymized source code, case definitions, historical result workbooks, run manifests, and available per-episode audit records for the controlled experiments are provided in the artifact repository. Version provenance, evidence coverage, and limitations are documented in the artifact.

This wording describes availability. It does not establish historical baseline equivalence or validate the revised implementation's empirical performance. The static checks do not establish that the manuscript's numerical results are incorrect; applicability of the pre-review implementation to the historical runs remains unresolved.
