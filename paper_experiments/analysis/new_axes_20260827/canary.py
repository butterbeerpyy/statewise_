from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
PRIMARY = REPO / 'paper_experiments/results/shared/permission_matched_v10_all_arms_20260819.xlsx'
RQ4 = REPO / 'paper_experiments/results/rq4/rq4_results.xlsx'
RQ5 = REPO / 'paper_experiments/results/rq5/rq5_results.xlsx'
CASES = REPO.parent / 'statewise/scaffold/experiments/w1_contract_corrected_v9/cases'

FULL = 'statewise_v2_contract_corrected_typedfix'

failures: list[str] = []
checks = 0


def check(label: str, got: float | int, want: float | int, tol: float = 0.05) -> None:

    global checks
    checks += 1
    if got is None or abs(float(got) - float(want)) > tol:
        failures.append('%-58s got %-10s want %s' % (label, round(float(got), 3)
                                                     if got is not None else None, want))


def stratum_of(case_id: str, domain: str) -> str:

    if 'core_repo_state_environment_dependency' in case_id:
        return 'runtime'
    if domain == 'git_state':
        return 'git'
    return 'workspace'


def load_primary() -> pd.DataFrame:
    ep = pd.ExcelFile(PRIMARY).parse('Combined_Episodes')
    ep['stratum'] = [stratum_of(str(c), str(d))
                     for c, d in zip(ep.case_id, ep.domain)]
    return ep


def pct(series) -> float:
    return float(series.mean()) * 100


def main() -> int:
    global checks
    ep = load_primary()
    if ep.shape[0] != 1500:
        print('FATAL: expected 1500 primary episodes, got %d' % ep.shape[0])
        return 1
    if ep.arm.nunique() != 10:
        print('FATAL: expected 10 arms, got %d' % ep.arm.nunique())
        return 1

    act = ep[ep.expected_behavior == 'SHOULD_ACT']
    stop = ep[ep.expected_behavior == 'SHOULD_STOP']

    def obj(arm: str) -> float:
        return pct(ep[ep.arm == arm].behaviorally_correct)

    def comp(arm: str) -> float:
        return pct(act[act.arm == arm].action_completed)

    def viol(arm: str) -> float:
        return pct(ep[ep.arm == arm].safety_violation)

    def unnec(arm: str) -> float:
        return float(ep[ep.arm == arm].unnecessary_mutation_rate.mean()) * 100

    def strat(arm: str, s: str) -> float:
        sub = ep[(ep.arm == arm) & (ep.stratum == s)]
        return pct(sub.behaviorally_correct)

    def calls(arm: str) -> float:
        return float(ep[ep.arm == arm].api_calls.mean())


    for arm, o, c, v, u in [
        ('correct', 80.7, 76.8, 0.0, 18.7),
        ('corrupted', 38.7, 27.2, 42.7, 62.7),
        ('no_memory', 45.3, 35.2, 9.3, 24.7),
        (FULL, 95.3, 94.4, 0.0, 16.2),
    ]:
        check('T1A %s obj' % arm, obj(arm), o)
        check('T1A %s comp' % arm, comp(arm), c)
        check('T1A %s viol' % arm, viol(arm), v)
        check('T1A %s unnec' % arm, unnec(arm), u, tol=0.11)


    for arm, rt, ws, git in [
        ('correct', 74.3, 86.9, 71.0),
        ('corrupted', 0.0, 50.0, 51.6),
        ('no_memory', 2.9, 51.2, 77.4),
        (FULL, 100.0, 96.4, 87.1),
    ]:
        check('T1B %s runtime' % arm, strat(arm, 'runtime'), rt)
        check('T1B %s workspace' % arm, strat(arm, 'workspace'), ws)
        check('T1B %s git' % arm, strat(arm, 'git'), git)


    for arm, o, c, v, u in [
        ('bare_approval', 36.0, 23.2, 0.0, 12.0),
        ('rationale_approval', 40.7, 29.6, 0.0, 14.0),
        ('generic_clarification', 31.3, 18.4, 38.0, 49.3),
    ]:
        check('T2 %s obj' % arm, obj(arm), o)
        check('T2 %s comp' % arm, comp(arm), c)
        check('T2 %s viol' % arm, viol(arm), v)
        check('T2 %s unnec' % arm, unnec(arm), u, tol=0.11)


    for arm, o, v, u, k in [
        ('corrupted', 38.7, 42.7, 62.7, 2.1),
        ('memlineage_trust', 39.3, 23.3, 41.3, 3.4),
        ('safety_sentry', 38.7, 8.7, 22.7, 8.1),
        ('ask_or_assume', 33.3, 42.7, 52.7, 3.9),
        (FULL, 95.3, 0.0, 16.2, 17.2),
    ]:
        check('T3A %s obj' % arm, obj(arm), o)
        check('T3A %s viol' % arm, viol(arm), v)
        check('T3A %s unnec' % arm, unnec(arm), u, tol=0.11)
        check('T3A %s calls' % arm, calls(arm), k)


    for arm, rt, ws, git in [
        ('memlineage_trust', 0.0, 47.6, 61.3),
        ('safety_sentry', 0.0, 48.8, 54.8),
        ('ask_or_assume', 0.0, 36.9, 61.3),
    ]:
        check('T3B %s runtime' % arm, strat(arm, 'runtime'), rt)
        check('T3B %s workspace' % arm, strat(arm, 'workspace'), ws)
        check('T3B %s git' % arm, strat(arm, 'git'), git)


    check('prose bare runtime', strat('bare_approval', 'runtime'), 0.0)
    check('prose rationale runtime', strat('rationale_approval', 'runtime'), 2.9)
    check('prose clarif runtime', strat('generic_clarification', 'runtime'), 0.0)
    check('prose bare workspace', strat('bare_approval', 'workspace'), 45.2)
    check('prose rationale workspace', strat('rationale_approval', 'workspace'), 48.8)
    check('prose clarif workspace', strat('generic_clarification', 'workspace'), 36.9)


    envd = ep[ep.domain == 'environment_state']
    for arm, want in [('safety_sentry', 17.6), ('memlineage_trust', 44.6),
                      ('ask_or_assume', 86.5), ('corrupted', 86.5)]:
        check('prose env viol %s' % arm, pct(envd[envd.arm == arm].safety_violation),
              want)


    pt4 = pd.ExcelFile(RQ4).parse('Paper_Table').set_index('method')
    ep4 = pd.ExcelFile(RQ4).parse('Episode_Data')


    for method, o in [('w/o Attribution', 32.0), ('w/o Resolution', 8.0),
                      ('w/o Repair', 15.3), ('w/o Typed Grounding', 64.0)]:
        check('RQ4 workbook %s obj' % method,
              float(pt4.loc[method, 'objective_correctness']) * 100, o)
    order = ['w/o Resolution', 'w/o Repair', 'w/o Attribution',
             'w/o Typed Grounding']
    got_order = (pt4.loc[order, 'objective_correctness']
                 .sort_values().index.tolist())
    if got_order != order:
        failures.append('RQ4 ablation severity ordering changed: %s' % got_order)
    checks += 1


    seq = pd.ExcelFile(RQ5).parse('Sequence_Data')
    seq = seq[seq.primary_in_scope == True]
    td = pd.ExcelFile(RQ5).parse('Task_Data')

    def strict(arm: str) -> float:
        s = seq[seq.arm == arm]
        ok = (s.future_task_success_rate >= 1.0) & (s.cumulative_safety_violations == 0)
        return float(ok.mean()) * 100

    def futcomp(arm: str) -> float:
        return pct(td[(td.arm == arm) & (td.task_index > 1)].task_success)

    for arm, st, fc in [(FULL, 90.6, 92.7), ('correct', 87.5, 91.7),
                        ('memlineage_trust', 0.0, 1.0),
                        ('safety_sentry', 0.0, 2.1),
                        ('ask_or_assume', 3.1, 6.3)]:
        check('T5 %s strict' % arm, strict(arm), st, tol=0.2)
        check('T5 %s future comp' % arm, futcomp(arm), fc, tol=0.2)


    check('T5 statewise t1 repair',
          pct(seq[seq.arm == FULL].t1_repaired_contract_satisfied), 96.9, tol=0.2)
    check('T5 statewise reuse', pct(td[(td.arm == FULL) & (td.task_index > 1)]
                                    .state_reuse), 97.9, tol=0.2)


    for pos, want in [(1, 90.6), (2, 90.6), (3, 93.8), (4, 93.8)]:
        check('T5 statewise T%d comp' % pos,
              pct(td[(td.arm == FULL) & (td.task_index == pos)].task_success), want,
              tol=0.2)


    prov = pd.ExcelFile(RQ5).parse('Run_Provenance')
    for arm, k, tok in [(FULL, 11.1, 12083), ('correct', 1.6, 2043),
                        ('memlineage_trust', 1.3, 2161),
                        ('safety_sentry', 8.8, 12900),
                        ('ask_or_assume', 3.4, 4906)]:
        p = prov[prov.arm == arm]
        ntask = len(td[td.arm == arm])
        check('T5 %s calls/task' % arm, p.calls.sum() / ntask, k, tol=0.1)
        check('T5 %s tokens/task' % arm, p.total_tokens.sum() / ntask, tok, tol=12)


    files = sorted(CASES.glob('*.json'))
    check('case count', len(files), 150, tol=0)
    ops: dict[str, int] = {}
    missing = 0
    for f in files:
        d = json.loads(f.read_text(encoding='utf-8'))
        op = d.get('corruption_operator')
        diff = d.get('difficulty') or {}
        if not op or not all(diff.get(k) for k in
                             ('observability', 'causal_depth', 'impact',
                              'persistence')):
            missing += 1
        ops[op] = ops.get(op, 0) + 1
    check('cases missing design fields', missing, 0, tol=0)
    for op, n in [('STALE_VALUE', 48), ('WRONG_VALUE', 39),
                  ('OVER_GENERALIZATION', 28), ('IMPLICIT_CONFLICT', 21),
                  ('SCOPE_MISMATCH', 10), ('JOINT_POLICY_COLLAPSE', 4)]:
        check('operator count %s' % op, ops.get(op, 0), n, tol=0)


    for op, share in [('STALE_VALUE', 32.0), ('WRONG_VALUE', 26.0),
                      ('OVER_GENERALIZATION', 18.7), ('IMPLICIT_CONFLICT', 14.0),
                      ('SCOPE_MISMATCH', 6.7), ('JOINT_POLICY_COLLAPSE', 2.7)]:
        check('operator share %s' % op, ops[op] / 150 * 100, share, tol=0.1)

    print('=' * 78)
    print('CANARY: %d checks, %d failures' % (checks, len(failures)))
    print('=' * 78)
    if failures:
        for f in failures:
            print('  FAIL  ' + f)
        return 1
    print('  all recomputed values match the paper')
    return 0


if __name__ == '__main__':
    sys.exit(main())
