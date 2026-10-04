from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
EVAL = REPO / 'paper/fse2027/sections/evaluation.tex'
LIMITS = REPO / 'paper/fse2027/sections/limitations.tex'
APPX = REPO / 'paper/fse2027/sections/appendix.tex'

fails: list[str] = []
n = 0


def rows(name: str) -> list[dict[str, str]]:
    with (HERE / name).open(newline='', encoding='utf-8') as fh:
        return list(csv.DictReader(fh))


def want(label: str, needle: str, text: str) -> None:

    global n
    n += 1
    if needle not in text:
        fails.append('%-52s missing: %s' % (label, needle))


def main() -> int:
    lim = LIMITS.read_text(encoding='utf-8')
    ap = APPX.read_text(encoding='utf-8')


    ev = EVAL.read_text(encoding='utf-8') + '\n' + ap


    op = {r['operator']: r for r in rows('operator_matrix.csv')}
    pr = {r['operator']: r for r in rows('operator_paired.csv')}
    ic, sm = op['Implicit conflict'], op['Scope mismatch']
    want('IC corrupted', '28.6', ev)
    want('IC statewise', '90.5', ev)
    want('IC cases', 'n{=}21', ev)
    want('SM statewise', '100.0', ev)
    want('SM cases', 'n{=}10', ev)
    assert ic['Corrupted memory_obj'] == '28.6', ic
    assert ic['StateWise_obj'] == '90.5', ic
    assert sm['StateWise_obj'] == '100.0', sm
    assert ic['cases'] == '21' and sm['cases'] == '10'


    bcols = ['Corrupted memory_obj', 'No memory_obj', 'Bare approval_obj',
             'Rationale approval_obj', 'Clarification_obj', 'MemLineage_obj',
             'Safety Sentry_obj', 'Ask-or-Assume_obj']
    best_ic = max(float(ic[c]) for c in bcols)
    want('IC best baseline (%.1f)' % best_ic, '%.1f' % best_ic, ev)
    best_sm = max(float(sm[c]) for c in bcols)
    want('SM baseline tie (%.1f)' % best_sm, '%.1f' % best_sm, ev)


    p = pr['Implicit conflict']
    want('IC paired diff', p['difference'], ev)
    want('IC CI', '[%s,%s]' % (p['ci_low'], p['ci_high']), ev)


    lo = min(float(pr[k]['difference']) for k in pr)
    hi = max(float(pr[k]['difference']) for k in pr)
    assert all(float(op[k]['StateWise_obj']) > 90 for k in op), \
        'claim "exceeds 90 on all six" is false'
    want('paired range low', '%.1f' % lo, ev)
    want('paired range high', '%.1f' % hi, ev)

    big = [k for k in pr if int(pr[k]['cases']) >= 21]
    assert len(big) == 4, big
    assert all(float(pr[k]['holm_p']) < 0.05 for k in big), \
        'not all n>=21 operators survive Holm'
    small = [k for k in pr if int(pr[k]['cases']) < 21]
    assert all(abs(float(pr[k]['holm_p']) - 0.25) < 1e-9 for k in small), small
    want('underpowered p', 'p_H{=}0.25', ev)


    dep = {r['method']: r for r in rows('depth_matrix.csv')}
    sev = {r['method']: r for r in rows('severity_matrix.csv')}
    for meth in dep:
        for col in ('D2', 'D3', 'D4'):
            want('depth %s %s' % (meth, col), dep[meth][col], ev)
    for meth in sev:
        for col in ('I2_viol', 'I3_viol', 'I4_viol'):
            want('impact %s %s' % (meth, col), sev[meth][col], ev)

    for meth in dep:
        d = dep[meth]['D4_minus_D2']

        forms = ['$-%s$' % d.lstrip('-'), '$\\mathbf{-%s}$' % d.lstrip('-')] \
            if d.startswith('-') else [d]
        global n
        n += 1
        if not any(f in ev for f in forms):
            fails.append('%-52s missing: %s' % ('delta %s' % meth, forms[0]))

    want('correct depth drop', '14.4 points', ev)
    want('statewise depth drop', '3.3 points', ev)
    sent = sev['Safety Sentry']
    want('sentry impact trend', '(%s\\%%, %s\\%%, %s\\%%)' % (
        sent['I2_viol'], sent['I3_viol'], sent['I4_viol']), ev)
    sw = sev['StateWise']
    want('statewise unnec trend', '(%s\\%%, %s\\%%, %s\\%%)' % (
        sw['I2_unnec'], sw['I3_unnec'], sw['I4_unnec']), ev)
    want('correct I4 unnec', '(%s\\%%)' % sev['Correct memory']['I4_unnec'], ev)
    corr = sev['Corrupted memory']
    want('corrupted impact trend', '(%s\\%%, %s\\%%, %s\\%%)' % (
        corr['I2_viol'], corr['I3_viol'], corr['I4_viol']), ev)

    depl = [abs(float(dep[m]['D4_minus_D2'])) for m in dep
            if m not in ('Correct memory', 'StateWise')]
    want('baseline drop range', '%.1f--%.1f points' % (min(depl), max(depl)), ev)


    st = {r['arm']: r for r in rows('rq4_stratum.csv')}
    want('attrib git', st['w/o Attribution']['git'], ev)
    want('resol workspace', st['w/o Resolution']['workspace'], ev)
    want('repair workspace', st['w/o Persistent Repair']['workspace'], ev)
    full, tg = st['Full StateWise'], st['w/o Typed Grounding']
    tg_rt = float(full['runtime']) - float(tg['runtime'])
    tg_git = float(full['git']) - float(tg['git'])
    want('typed grounding runtime loss', '%.1f points' % tg_rt, ev)
    want('typed grounding git loss', 'only %.1f' % tg_git, ev)
    assert full['overall'] == '93.3', full


    at = {r['method']: r for r in rows('rq5_attention.csv')}
    sws, ss = at['StateWise'], at['Safety Sentry']
    want('sw questions', '%.2f' % float(sws['questions_per_seq']), ev)
    want('sw perms', '%.2f' % float(sws['permissions_per_seq']), ev)
    want('sw max', 'more than %s' % sws['permissions_max'], ev)
    want('sentry perms', '%.2f' % float(ss['permissions_per_seq']), ev)
    want('sentry max', 'up to %s' % ss['permissions_max'], ev)

    ratio = (float(sws['interactions_per_seq'])
             / float(at['Correct memory (oracle)']['interactions_per_seq']))
    want('oracle ratio', '%.1f times' % ratio, ev)


    total = sum(int(op[k]['cases']) for k in op)
    assert total == 150, total
    for k in op:
        share = int(op[k]['cases']) / 150 * 100
        want('appendix share %s' % k, '%.1f\\%%' % share, ap)
    want('appendix eval counts', '48, 39, 28, 21, 10, and 4 cases', ap)


    want('limits scope mismatch n', 'n{=}10', lim)
    want('limits joint n', 'n{=}4', lim)

    print('=' * 74)
    print('PAPER VERIFY: %d checks, %d failures' % (n, len(fails)))
    print('=' * 74)
    if fails:
        for f in fails:
            print('  FAIL  ' + f)
        return 1
    print('  every new number in the paper matches its CSV')
    return 0


if __name__ == '__main__':
    sys.exit(main())
