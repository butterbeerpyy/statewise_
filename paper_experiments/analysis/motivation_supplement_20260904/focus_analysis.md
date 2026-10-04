# Detailed B Analysis: StateWise vs. Live Refresh

This is a paired, case-level secondary analysis of the frozen 150-case corrupted-state run. Git state is a domain; scope mismatch and stale value are corruption operators. These strata overlap, so their counts and effects are not additive. The three subgroup tests are exploratory; Holm-adjusted p-values are supplied to make that limitation explicit.

| Stratum | n | StateWise | Refresh | Difference | SW only / Refresh only | 95% paired bootstrap CI | Exact p | Holm p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| all_cases | 150 | 133/150 (88.7%) | 125/150 (83.3%) | +5.3 pp | 12 / 4 | [+0.0, +10.7] | 0.0768 | -- |
| git_state | 31 | 15/31 (48.4%) | 8/31 (25.8%) | +22.6 pp | 10 / 3 | [+0.0, +45.2] | 0.0923 | 0.1846 |
| scope_mismatch | 10 | 10/10 (100.0%) | 8/10 (80.0%) | +20.0 pp | 2 / 0 | [+0.0, +50.0] | 0.5000 | 0.5000 |
| stale_value | 48 | 43/48 (89.6%) | 37/48 (77.1%) | +12.5 pp | 6 / 0 | [+4.2, +22.9] | 0.0312 | 0.0938 |
| focus_union | 76 | 60/76 (78.9%) | 52/76 (68.4%) | +10.5 pp | 11 / 3 | [+1.3, +19.7] | 0.0574 | -- |
| none_of_three | 74 | 73/74 (98.6%) | 73/74 (98.6%) | +0.0 pp | 1 / 1 | [-4.1, +4.1] | 1.0000 | -- |

## Discordant pairs

Across all cases, StateWise alone was correct in 12 cases and Refresh alone in 4. The exact case list, terminal reasons, initial/final actions, call counts, step counts, and evidence paths are in `focus_discordant_cases.csv`.

## Supporting files

- `focus_strata_paired.csv`: outcomes, Wilson intervals, paired bootstrap intervals, exact and adjusted tests, costs.
- `focus_discordant_cases.csv`: every outcome-changing pair with trace identifiers and fixture paths.
- `focus_overlap_matrix.csv`: pairwise overlap among the three focus strata.
- `focus_membership_patterns.csv`: mutually exclusive overlap patterns.
