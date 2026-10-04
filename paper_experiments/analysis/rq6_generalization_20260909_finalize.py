import csv, json
from pathlib import Path

out = Path('paper_experiments/analysis/rq6_generalization_20260909')
metrics = list(csv.DictReader((out/'main150_rq6_metrics.csv').open(encoding='utf-8-sig')))
source = json.loads((out/'wild_source_manifest.json').read_text(encoding='utf-8'))
rows = list(csv.DictReader((out/'main150_rq6_case_metrics.csv').open(encoding='utf-8-sig')))
wild = list(csv.DictReader((out/'wild_trajectory_split_manifest.csv').open(encoding='utf-8-sig')))
provenance = {
    'run_id':'formal_v10_rq4_ablations150_gpt56sol_20260822_r1',
    'run_path':'runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1',
    'target_arm':'statewise_v2_contract_corrected_typedfix',
    'dataset_snapshot':'w1_contract_corrected_v9',
    'dataset_snapshot_sha256':'25f08c7ec7f5cee5855dcddbfc9e538bab79a509aa8580dbd7501ef396c2af34',
    'method_fingerprint':'sha256:0804b97693cb2f4cab236f325347b3c227c391572aa7e3048f85657640cc899e',
    'freeze_record':'runs/statewise-sync-93d68f7\\final\\reselts\\shared\\FINAL_150_V9_FREEZE.json',
    'run_manifest':'runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1\\manifest.json',
    'case_record_glob':'runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1\\workspaces\\**\\episode_worker_result.json',
    'evaluator_version':'managed-pilot-summary-v1 / statewise-experiment-manager-v1',
    'case_records_scanned':1070,'target_records':152,'unique_target_cases':150,'duplicate_case_ids':2,
    'status_counts':{'SAFE_ABORT':6,'COMPLETE':140,'STEP_LIMIT':3,'REFUSED':1},
    'refresh_comparison':'Optional-refresh sensitivity runs are not pooled; see prior audit source_manifest.json.'
}
(out/'rq6_run_source_manifest.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2),encoding='utf-8')
result_fields = ['session_id','repository','split','eligible_protocol','observation100_excluded','offline_decision_replay','executable_replay','correct_final_outcome','should_act_completion','unsafe_or_incorrect_action','clean_unnecessary_intervention','unsupported_or_unreconstructable','tool_calls','human_interactions','result_status','reason']
with (out/'wild_trajectory_results.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w=csv.DictWriter(f, fieldnames=result_fields); w.writeheader()
    for r in wild:
        w.writerow({'session_id':r['session_id'],'repository':r['repository'],'split':r['split'],'eligible_protocol':r['eligible_protocol'],'observation100_excluded':r['observation100_excluded'],'offline_decision_replay':'NOT_RUN','executable_replay':'NOT_RUN','correct_final_outcome':'NOT_REPORTED','should_act_completion':'NOT_REPORTED','unsafe_or_incorrect_action':'NOT_REPORTED','clean_unnecessary_intervention':'NOT_REPORTED','unsupported_or_unreconstructable':'NOT_REPORTED','tool_calls':r['tool_calls_observed'],'human_interactions':'NOT_AVAILABLE','result_status':'AUDIT_ONLY','reason':'No frozen trajectory-to-case adapter/evaluator; no model outcome fabricated.' if r['split']=='rq6_remainder' else ('Observation100 excluded from RQ6' if r['split']=='observation100' else r['exclusion_reasons'])})
with (out/'wild_exclusion_list.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w=csv.DictWriter(f, fieldnames=['session_id','repository','split','exclusion_reasons']); w.writeheader()
    for r in wild:
        if r['split'] != 'rq6_remainder': w.writerow({k:r[k] for k in ['session_id','repository','split','exclusion_reasons']})
md = [
    '# RQ6 - Robustness and Generalization Evidence', '',
    'Frozen Main150 run: `runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1`; method fingerprint `sha256:0804b97693cb2f4cab236f325347b3c227c391572aa7e3048f85657640cc899e`.',
    '`Any Unseen` is the union (new repository OR unseen tool operation OR unseen state type). `Fully Unseen` is the intersection (all three). The component slices are non-exclusive; their case counts must not be added.',
    'Semantic state types are taxonomy labels (not raw state-key strings).', '',
    '## Main150 metrics'
]
for r in metrics:
    if r['slice'].endswith('-minus-Seen_gap'):
        rate = 'N/A' if not r['rate'] else f"{100*float(r['rate']):.1f}pp"
        ci = '' if not r['ci95_low'] else f"; 95% CI [{100*float(r['ci95_low']):.1f}, {100*float(r['ci95_high']):.1f}]pp"
        md.append(f"- {r['slice']} {r['metric']}: {rate}{ci}")
    else:
        rate = 'N/A' if not r['rate'] else f"{100*float(r['rate']):.1f}%"
        if r['numerator'] != '': rate += f" ({r['numerator']}/{r['denominator']})"
        md.append(f"- {r['slice']} n={r['n']}, independent tool operations={r['independent_tool_operations']}, independent state types={r['independent_state_types']}: {r['metric']} {rate}")
md += [
    '',
    'Any Unseen is 93 cases and Fully Unseen is 33 cases. The 81-case Unseen State Types slice retains the frozen headline 75/81=92.6%; Development-Seen is 41/44=93.2%, a -0.6 percentage-point gap. Raw conditional action counts remain in `raw_numerator/raw_denominator` in the CSV as audit fields. Development-Seen contains no Should-Stop cases, so the Correct-Stop gap is N/A.',
    '', '## Wild trajectory audit',
    f"Raw sessions: {source['raw_total']}; parseable transcript paths: {source['parseable_sessions']}; protocol-eligible remainder excluding Observation100: {source['replayable_sessions']}; executable: {source['executable_sessions']}. Observation100: 100 raw/100 parseable; RQ6 remainder: 5,375 raw/5,375 parseable/5,375 protocol-eligible; excluded: 376 raw/375 parseable.",
    'Observation100 is retained only for motivation/taxonomy/adapter development. The RQ6 remainder is repository/session isolated; the split manifest carries an isolation key and an explicit split label.',
    'No prior legal full RQ6 wild run with the frozen fingerprint, future-turn exclusion, no-oracle evaluator, and repository/session isolation was found. Ten engineering canaries passed data/isolation checks only. Offline decision replay and executable replay are both NOT_RUN; no endpoint outcome numbers are claimed.',
    '', '## Files'
]
for p in sorted(out.iterdir()):
    if p.is_file() and p.name not in ('RQ6_RESULTS.md','run_stdout.json','rq6_generalization_20260909_finalize.py'):
        md.append(f'- `{p.name}`')
(out/'RQ6_RESULTS.md').write_text('\n'.join(md)+'\n', encoding='utf-8')
print('wrote', out/'RQ6_RESULTS.md')
