# RQ6 - Robustness and Generalization Evidence

Frozen Main150 run: `artifacts/runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1`; method fingerprint `sha256:0804b97693cb2f4cab236f325347b3c227c391572aa7e3048f85657640cc899e`.
`Any Unseen` is the union (new repository OR unseen tool operation OR unseen state type). `Fully Unseen` is the intersection (all three). The component slices are non-exclusive; their case counts must not be added.
Semantic state types are taxonomy labels (not raw state-key strings).

## Main150 metrics
- Any Unseen n=93, independent tool operations=4, independent state types=7: Overall Correctness 95.7% (89/93)
- Any Unseen n=93, independent tool operations=4, independent state types=7: Should-Act Completion 95.6% (65/68)
- Any Unseen n=93, independent tool operations=4, independent state types=7: Correct Stop 96.0% (24/25)
- Any Unseen n=93, independent tool operations=4, independent state types=7: Unsafe Rate 0.0% (0/93)
- Any Unseen n=93, independent tool operations=4, independent state types=7: Unsupported Rate 1.1% (1/93)
- Fully Unseen n=33, independent tool operations=2, independent state types=3: Overall Correctness 97.0% (32/33)
- Fully Unseen n=33, independent tool operations=2, independent state types=3: Should-Act Completion 92.9% (13/14)
- Fully Unseen n=33, independent tool operations=2, independent state types=3: Correct Stop 100.0% (19/19)
- Fully Unseen n=33, independent tool operations=2, independent state types=3: Unsafe Rate 0.0% (0/33)
- Fully Unseen n=33, independent tool operations=2, independent state types=3: Unsupported Rate 0.0% (0/33)
- New Repositories n=62, independent tool operations=3, independent state types=6: Overall Correctness 98.4% (61/62)
- New Repositories n=62, independent tool operations=3, independent state types=6: Should-Act Completion 97.7% (42/43)
- New Repositories n=62, independent tool operations=3, independent state types=6: Correct Stop 100.0% (19/19)
- New Repositories n=62, independent tool operations=3, independent state types=6: Unsafe Rate 0.0% (0/62)
- New Repositories n=62, independent tool operations=3, independent state types=6: Unsupported Rate 0.0% (0/62)
- Unseen Tool Operations n=45, independent tool operations=2, independent state types=3: Overall Correctness 93.3% (42/45)
- Unseen Tool Operations n=45, independent tool operations=2, independent state types=3: Should-Act Completion 90.0% (18/20)
- Unseen Tool Operations n=45, independent tool operations=2, independent state types=3: Correct Stop 96.0% (24/25)
- Unseen Tool Operations n=45, independent tool operations=2, independent state types=3: Unsafe Rate 0.0% (0/45)
- Unseen Tool Operations n=45, independent tool operations=2, independent state types=3: Unsupported Rate 2.2% (1/45)
- Unseen State Types n=81, independent tool operations=4, independent state types=6: Overall Correctness 95.1% (77/81)
- Unseen State Types n=81, independent tool operations=4, independent state types=6: Should-Act Completion 92.6% (75/81)
- Unseen State Types n=81, independent tool operations=4, independent state types=6: Correct Stop 96.0% (24/25)
- Unseen State Types n=81, independent tool operations=4, independent state types=6: Unsafe Rate 0.0% (0/81)
- Unseen State Types n=81, independent tool operations=4, independent state types=6: Unsupported Rate 1.2% (1/81)
- Development-Seen n=44, independent tool operations=3, independent state types=2: Overall Correctness 93.2% (41/44)
- Development-Seen n=44, independent tool operations=3, independent state types=2: Should-Act Completion 93.2% (41/44)
- Development-Seen n=44, independent tool operations=3, independent state types=2: Correct Stop N/A (0/0)
- Development-Seen n=44, independent tool operations=3, independent state types=2: Unsafe Rate 0.0% (0/44)
- Development-Seen n=44, independent tool operations=3, independent state types=2: Unsupported Rate 0.0% (0/44)
- Any Unseen-minus-Seen_gap Overall Correctness: 2.5pp; 95% CI [-8.2, 16.5]pp
- Any Unseen-minus-Seen_gap Should-Act Completion: 2.4pp; 95% CI [-9.8, 16.7]pp
- Any Unseen-minus-Seen_gap Unsafe Rate: 0.0pp; 95% CI [-8.0, 4.0]pp
- Any Unseen-minus-Seen_gap Unsupported Rate: 1.1pp; 95% CI [-7.8, 5.8]pp
- Fully Unseen-minus-Seen_gap Overall Correctness: 3.8pp; 95% CI [-13.0, 17.7]pp
- Fully Unseen-minus-Seen_gap Should-Act Completion: -0.3pp; 95% CI [-29.1, 17.0]pp
- Fully Unseen-minus-Seen_gap Unsafe Rate: 0.0pp; 95% CI [-8.0, 10.4]pp
- Fully Unseen-minus-Seen_gap Unsupported Rate: 0.0pp; 95% CI [-8.0, 10.4]pp
- New Repositories-minus-Seen_gap Overall Correctness: 5.2pp; 95% CI [-6.2, 17.9]pp
- New Repositories-minus-Seen_gap Should-Act Completion: 4.5pp; 95% CI [-9.7, 17.8]pp
- New Repositories-minus-Seen_gap Unsafe Rate: 0.0pp; 95% CI [-8.0, 5.8]pp
- New Repositories-minus-Seen_gap Unsupported Rate: 0.0pp; 95% CI [-8.0, 5.8]pp
- Unseen Tool Operations-minus-Seen_gap Overall Correctness: 0.2pp; 95% CI [-15.5, 15.9]pp
- Unseen Tool Operations-minus-Seen_gap Should-Act Completion: -3.2pp; 95% CI [-27.8, 15.4]pp
- Unseen Tool Operations-minus-Seen_gap Unsafe Rate: 0.0pp; 95% CI [-8.0, 7.9]pp
- Unseen Tool Operations-minus-Seen_gap Unsupported Rate: 2.2pp; 95% CI [-7.6, 11.6]pp
- Unseen State Types-minus-Seen_gap Overall Correctness: 1.9pp; 95% CI [-9.7, 16.3]pp
- Unseen State Types-minus-Seen_gap Should-Act Completion: -0.6pp; 95% CI [-12.9, 14.8]pp
- Unseen State Types-minus-Seen_gap Unsafe Rate: 0.0pp; 95% CI [-8.0, 4.5]pp
- Unseen State Types-minus-Seen_gap Unsupported Rate: 1.2pp; 95% CI [-7.8, 6.7]pp

Any Unseen is 93 cases and Fully Unseen is 33 cases. The 81-case Unseen State Types slice retains the frozen headline 75/81=92.6%; Development-Seen is 41/44=93.2%, a -0.6 percentage-point gap. Raw conditional action counts remain in `raw_numerator/raw_denominator` in the CSV as audit fields. Development-Seen contains no Should-Stop cases, so the Correct-Stop gap is N/A.

## Wild trajectory audit
Raw sessions: 5851; parseable transcript paths: 5850; protocol-eligible remainder excluding Observation100: 5375; executable: 0. Observation100: 100 raw/100 parseable; RQ6 remainder: 5,375 raw/5,375 parseable/5,375 protocol-eligible; excluded: 376 raw/375 parseable.
Observation100 is retained only for motivation/taxonomy/adapter development. The RQ6 remainder is repository/session isolated; the split manifest carries an isolation key and an explicit split label.
No prior legal full RQ6 wild run with the frozen fingerprint, future-turn exclusion, no-oracle evaluator, and repository/session isolation was found. Ten engineering canaries passed data/isolation checks only. Offline decision replay and executable replay are both NOT_RUN; no endpoint outcome numbers are claimed.

## Files
- `main150_rq6_case_metrics.csv`
- `main150_rq6_metrics.csv`
- `main150_rq6_set_audit.json`
- `main150_rq6_slice_summary.csv`
- `main150_rq6_slices.csv`
- `main150_rq6_vocabularies.json`
- `reclassify_slices.py`
- `rq6_run_source_manifest.json`
- `wild_canary10_results.csv`
- `wild_exclusion_list.csv`
- `wild_remainder_ids.csv`
- `wild_source_manifest.json`
- `wild_trajectory_results.csv`
- `wild_trajectory_split_manifest.csv`
