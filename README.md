# StateWise

Research code for diagnosing and repairing persistent operational state before agent actions.

## Layout

- `scaffold/statewise/`: method, agents, memory, runtime, evaluation and experiment management.
- `scaffold/runners/`: command-line experiment and audit entry points.
- `scaffold/cases/`, `scaffold/fixtures/`, `scaffold/experiments/`: controlled cases, runtime fixtures and frozen experiment definitions.
- `scaffold/tests/`: regression tests.
- `scaffold/local/`: environment-based API configuration with three anonymous profiles.
- `dataset_design/`: benchmark construction tools and controlled metadata.
- `paper_experiments/`: supplementary analysis, plotting and longitudinal scripts.
- `paper_experiments/results/`: anonymized historical result workbooks with numeric cells preserved.
- `artifacts/runs/`: historical run metadata, episode indexes, and per-episode audit bundles.
- `artifacts/datasets/`: historical dataset snapshots identified by their original manifest hashes.
- `artifacts/source_versions/`: 30 sanitized historical source files whose original hashes match recorded run fingerprints; coverage is partial.
- `.env.example`: empty credentials and anonymous endpoint placeholders.

## Setup

Python 3.11 is required. Run commands from this directory.

```text
conda env create -f environment.yml
conda run -n statewise python -m unittest discover -s scaffold/tests -p "test_*.py"
conda run -n statewise python -m scaffold.runners.run_test --quiet
conda run -n statewise python -m scaffold.runners.run_lightweight --arm all --no-save
```

The synthetic benchmark contains environment actions named `nightly`; these are fixture names, independent of the host environment used to run the artifact.

## API configuration

The default is deterministic fake mode and makes no live API requests. Live mode supports OpenAI-compatible chat completion endpoints. Set environment variables in the shell; `.env.example` documents them but is not automatically loaded.

PowerShell example:

```powershell
$env:STATECLARIFY_FAKE_API = 'false'
$env:OPENAI_API_KEY = '<your-key>'
$env:OPENAI_BASE_URL = '<your-compatible-endpoint>/v1'
$env:STATECLARIFY_MODEL = '<your-model>'
conda run -n statewise python -m scaffold.runners.run_real --case case_env_nightly --trials 1 --quiet
```

For named profiles `api_01`, `api_02`, and `api_03`, set `STATEWISE_API_01_KEY`, `STATEWISE_API_01_BASE_URL`, and `STATEWISE_API_01_MODEL`, using the corresponding number for each profile. Set the human simulator variables separately if needed. Endpoint placeholders use the reserved `.invalid` domain and must be replaced for live requests. Real credentials and private endpoint addresses are absent from this artifact.

## Research evidence and repackaging

The artifact supplies source code, controlled case definitions, 11 historical workbooks, 65 run manifests, 5,718 episode audit bundles, and six historical dataset snapshots. Refer to `artifact_coverage.json` for exact coverage. Human conversation trajectories, annotator identities, external repository clones, full manuscript sources, presentations, unrelated personal workbooks, host execution logs, and Git history are excluded.

The current source corrects unintended StateWise state-binding gates in untreated baselines. Generic clarification may complete a task after a transient answer while its persistent memory stays unchanged. Ordinary action schema and intrinsic risk checks remain in place. The StateWise untrusted-binding guard is unchanged. Run metadata now records the baseline builder hash, and the managed runner performs actual freeze verification.

Historical outcomes are retained exactly as outcomes of their recorded runs. The revised baselines have not been rerun against the live paper benchmark. Historical measurement fingerprints omit the baseline builder, and some recorded source file versions cannot be recovered; `historical_source_coverage.json` identifies these gaps. Current source validation must not be used to certify historical baseline fairness or unchanged paper percentages. Historical workspace paths in traces describe runtime provenance; workspace clones are not bundled.

Run `conda run -n statewise python verify_paper_artifacts.py` to check selected historical paper anchors against supplied data. This checks data consistency, independently of running an agent. `paper_table_checks.json` records the checks. `data_availability_review.md` explains the publication claim and version limitations.

Python comments and docstrings were removed, including Python code embedded in JSON fixtures. File names use lowercase snake_case; standard repository metadata names retain their conventional spelling. Personal paths and repository identifiers were replaced consistently. API client logic and model identifiers are retained; provider account configurations were replaced with anonymous environment-based profiles.

Release checksums describe the repackaged files. The method freeze manifests are explicitly marked as anonymous repackaging, and their previous fingerprint is retained only as historical provenance. They do not assert byte-for-byte identity with an earlier experimental run. Refer to `audit_report.json` for validation and exclusions, and `release_manifest.json` for file integrity.

## License

The project code is released under MIT with anonymous copyright attribution. Public upstream references in benchmark provenance remain attributed to their original projects and retain their applicable licenses. External source repositories are not bundled.

## Release status

This directory is a prepared public source release. It contains no prior Git history or remote configuration. Its code and historical evidence are derived from the reviewed artifact; experimental results have not been rerun for this public packaging. Credentials remain environment based. Historical source coverage and validation limits are documented above.

Only the contents of this directory belong in the new repository. A fresh initial commit should be used rather than importing an existing repository history. The separate interactive website handoff is not part of this code release.
