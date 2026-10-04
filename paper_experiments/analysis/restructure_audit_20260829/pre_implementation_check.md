# Pre-implementation check against `problem.tex` (2026-08-29)

Paper still untouched. Two scope mismatches and one column decision need your
call before I edit.

## The RQs as actually stated (`sections/problem.tex:58-86`)

| RQ | Stated question (verbatim scope) |
|---|---|
| RQ1 | whether changing **only one persistent record**, task and fixture fixed, **causally** reduces correctness or safety |
| RQ2 | whether **approval, rationale review, or clarification** can recover the task once the faulty premise has become an action |
| RQ3 | whether StateWise improves correctness and safe completion over **memory-, action-, and system-level** safeguards |
| RQ4 | removes the state-diagnosis and repair mechanisms **one at a time** |
| RQ5 | whether **one scoped correction is reused by later planner contexts**, unit = four-task sequence |

## Mismatch 1 — Safety Sentry sits in Table 2, but RQ2 excludes it

Your Table 2 lists `Corrupted / Bare Approval / Rationale Approval /
Clarification / Safety Sentry`. But `problem.tex` scopes RQ2 to exactly
"approval, rationale review, or clarification" — Safety Sentry is a
**system-level** safeguard, which `problem.tex` assigns to RQ3. The current
paper agrees: §RQ2 covers the three action-layer arms, §RQ3 covers Safety Sentry,
MemLineage, Ask-or-Assume.

Putting Safety Sentry in Table 2 would contradict the RQ definition one section
earlier. Two clean options:

- **(a) keep RQ2 = 4 columns** — Corrupted, Bare, Rationale, Clarification. Safety
  Sentry appears in Figure 3 with the other system arms. Matches `problem.tex` as
  written.
- **(b) widen RQ2 in `problem.tex`** to "action-level supervision including
  action-time routers". That edits the RQ prose, which you told me not to do.

I recommend **(a)** and will use it unless you say otherwise.

## Mismatch 2 — RQ1 needs StateWise absent, and that is fine

Your Table 1 is 3 columns (Correct / Corrupted / No Memory) with no StateWise.
That is correct per `problem.tex` — RQ1 is purely causal, StateWise enters at RQ3.
Flagging only because the *current* `tab:main` does include a StateWise row, so
removing it is a real change, not a reformat. The 42.0 pp corruption cost and the
"corrupted is more dangerous than no memory" reading both survive.

## Column decision — Table 4 "T1 Safe Recovery" is not uniformly definable

Checked all eight arms. A **repair-based** T1 column is structurally N/A for six
of eight: zero repair events at T1 for Correct Memory, Corrupted, No Memory,
MemLineage, Safety Sentry, Ask-or-Assume. Only StateWise (31/32) and Oracle
StateWise (32/32) have it. So a repair-flavoured column would be a wall of dashes
— exactly what you said to avoid.

Uniform substitute that every arm can produce: **T1 task success AND no
violation**. Values: 30/32, 0/32, 0/32, 0/32, 0/32, 3/32, 30/32, 29/32. I will use
this and name it **T1 Safe Task** (not "Safe Recovery", which implies repair).

Your named fallback, All Safe Tasks n/128, also works (118/1/0/1/2/9/120/118) but
duplicates T2–T4; the T1 split is more informative because it separates the
triggering task from the persistence window.

## Table 4 recalc — complete, no N/A cells

Per-**sequence** denominators (32 for every arm) rather than per-successful-sequence:

| Method | T1 Safe Task | T2–T4 Safe | All-Future Safe | Inter/Seq | kTok/Seq |
|---|---|---|---|---:|---:|
| Correct Memory | 30/32 (93.8%) | 88/96 (91.7%) | 28/32 (87.5%) | 0.38 | 8.2 |
| Corrupted Memory | 0/32 (0.0%) | 1/96 (1.0%) | 0/32 (0.0%) | 0.00 | 8.8 |
| No Memory | 0/32 (0.0%) | 0/96 (0.0%) | 0/32 (0.0%) | 0.00 | 6.7 |
| MemLineage | 0/32 (0.0%) | 1/96 (1.0%) | 0/32 (0.0%) | 0.00 | 8.6 |
| Safety Sentry | 0/32 (0.0%) | 2/96 (2.1%) | 0/32 (0.0%) | 8.44 | 51.6 |
| Ask-or-Assume | 3/32 (9.4%) | 6/96 (6.2%) | 1/32 (3.1%) | 0.38 | 19.6 |
| Oracle StateWise | 30/32 (93.8%) | 90/96 (93.8%) | 30/32 (93.8%) | 0.47 | 20.4 |
| **StateWise** | 29/32 (90.6%) | 89/96 (92.7%) | 29/32 (90.6%) | 1.41 | 48.3 |

Using per-sequence removes every dash. The per-successful-sequence figures (1.55
StateWise, 12.00 Ask-or-Assume) move to the RQ5 prose, where the n=1 denominator
caveat can be stated.

Note 6.2% not 6.3% for Ask-or-Assume T2–T4: 6/96 = 6.25%, which rounds to 6.2 at
one decimal (banker's rounding on the exact value). The old 6.3% came from a
different rounding path. I will use 6.2%.

## Still awaiting your two earlier confirmations

1. **Holm family = 6** (all executed removals) — reproduces your 2.47e-9 anchor;
   4-family would give 8.23e-10.
2. **Column name "Interactions / Safe Completion"** — 0.31 / 0.68 hold only under
   this definition; pure questions would be 0.18 / 0.28.

## What I will do once you confirm

1. Table 1 (RQ1, 3 metrics x 3 conditions), Table 2 (RQ2, 3 metrics x 4 arms),
   Figure 3 (RQ3 two panels, 10 arms), Table 3 (RQ4, 5 rows), Table 4 (RQ5, 8 rows).
2. Delete/merge: current `tab:main` Panel A+B, `tab:rq2`, `tab:rq3` Panel A+B,
   `tab:difficulty`, `tab:attention`, `fig:claim-memory-action`,
   `fig:claim-system-safeguards`, `fig:operator-robustness`, `fig:rq4-stratum`.
   Net main-text floats: 9 tables + 6 figures → 4 tables + 3 figures.
3. Appendix: 7-arm RQ4, operator/domain matrix, gate sensitivity, unusable-answer
   conditions, pass^k controls, full per-arm costs, question-log sensitivity.
4. Leave Abstract / Introduction / Conclusion alone.
5. Compile, run both verification suites, report pages/errors/undefined/overfull.
6. No commit, no push.
