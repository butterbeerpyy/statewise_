# Questions deliberately left for author review

These points cannot be made stronger without changing the evidence or claim.

1. **A annotation gate:** the observation pilot lacks a second independent
   annotator. The 40/100 structurally valid candidate count may be used as
   descriptive motivation, but the frozen protocol does not permit a formal
   population prevalence claim until agreement/adjudication is complete. The
   planned 400-session formal annotation was therefore not launched: scaling a
   failed agreement gate would spend API budget without repairing validity.
2. **A construct breadth:** some candidates concern operational assumptions
   reused within one long session rather than durable memory recovered across
   sessions. Decide whether the paper's construct explicitly includes this
   trajectory-persistent state or whether a narrower manual adjudication is
   required.
3. **B headline:** StateWise's +5.3 pp advantage over complete Live Refresh is
   not conventionally significant (p=0.0768), while Refresh is about 9x cheaper
   in model calls. The paper now states this negative boundary rather than
   claiming decisive superiority.
4. **B temporal pairing:** StateWise/control cells are frozen from the earlier
   formal run; corrected Refresh was executed later against the same cases,
   model name, action contract, and evaluator. A simultaneous all-arm rerun
   would remove provider-time variation but was intentionally not launched
   because B was frozen.
5. **C naming:** the target value is correct in all 150 cases, but freshness and
   provenance are not fully valid. “Mostly correct” is accurate; “clean” is not.
6. **C write metric:** 99/108 writes are exact-value metadata/provenance refreshes.
   If the paper later claims a low false-intervention rate, it needs separate
   semantic-repair and metadata-refresh metrics.
7. **Cost/fairness:** action budgets are matched at eight steps, as requested;
   model calls are not. Any claim that gains come from the mechanism rather than
   additional inference requires a compute-matched comparison.
