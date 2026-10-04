# B/C baseline matrices

These are the outcome-only values inserted into `paper/fse2027/sections/evaluation.tex`.
Cost, latency, token, call, and interaction fields are intentionally not reported
in the manuscript table.

## B: corrupted target record

| Method | n | Overall | Should-Act | Unsafe |
|---|---:|---:|---:|---:|
| Base agent | 150 | 36.7 | 11.4 | 42.7 |
| Ask-or-Assume | 150 | 37.3 | 10.5 | 42.0 |
| CRITIC-style correction | 150 | 48.0 | 27.6 | 28.0 |
| MemLineage-style gate | 150 | 33.3 | 7.6 | 22.7 |
| Safety Sentry-style router | 148 | 32.4 | 3.9 | 4.7 |
| **StateWise** | 150 | **88.7** | **84.8** | **0.0** |

## C: semantically correct target record

| Method | n | Overall | Should-Act | Unsafe |
|---|---:|---:|---:|---:|
| Base agent | 150 | 70.7 | 58.1 | 0.0 |
| Ask-or-Assume | 150 | 80.7 | 73.3 | 0.0 |
| CRITIC-style correction | 149 | 50.3 | 29.8 | 27.5 |
| MemLineage-style gate | 150 | 42.0 | 17.1 | 12.7 |
| Safety Sentry-style router | 150 | 42.7 | 18.1 | 12.0 |
| **StateWise** | 150 | **88.0** | **82.9** | **0.0** |

Safety Sentry-B has two provider failures and CRITIC-C has one. Their reported
denominators are therefore 148 and 149; no missing request is imputed as failure.
The companion matrix contains 105 action-required cases. After attrition, the
corresponding conditional denominators are 103 for Safety Sentry-B and 104 for
CRITIC-C.
