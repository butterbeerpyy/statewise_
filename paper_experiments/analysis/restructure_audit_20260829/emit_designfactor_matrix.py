from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
AXES = HERE.parent / 'new_axes_20260827'
OUT = HERE / 'latex'
OUT.mkdir(exist_ok=True)

OPS = ['Wrong value', 'Stale value', 'Over-generalization',
       'Joint policy collapse', 'Implicit conflict', 'Scope mismatch']
OP_SHORT = {'Wrong value': 'Wrong', 'Stale value': 'Stale',
            'Over-generalization': 'Over-gen.',
            'Joint policy collapse': 'Joint', 'Implicit conflict': 'Implicit',
            'Scope mismatch': 'Scope'}
ROWS = ['Correct memory', 'Corrupted memory', 'No memory', 'Bare approval',
        'Rationale approval', 'Clarification', 'MemLineage', 'Safety Sentry',
        'Ask-or-Assume', 'StateWise']


def main() -> None:
    op = pd.read_csv(AXES / 'operator_matrix.csv').set_index('operator')
    depth = pd.read_csv(AXES / 'depth_matrix.csv').set_index('method')
    sev = pd.read_csv(AXES / 'severity_matrix.csv').set_index('method')

    counts = {name: int(op.loc[name, 'cases']) for name in OPS}
    lines = [
        '\\begin{table*}[t]',
        '  \\caption{Objective correctness and safety conditioned on the frozen'
        ' case-design factors. \\emph{Operator} is the corruption that produced',
        '  the stale record and \\emph{depth} the number of inference steps'
        ' between that record and the action argument it determines, both'
        ' correctness;',
        '  \\emph{impact} reports the safety-violation rate by designed severity.'
        ' $\\Delta$ is $D4$ minus $D2$, so a value near zero means the arm is',
        '  insensitive to inference distance. All entries are percentages.}',
        '  \\label{tab:designfactor-matrix}',
        '  \\centering\\footnotesize',
        '  \\begin{tabular*}{\\textwidth}'
        '{@{\\extracolsep{\\fill}}l' + 'r' * len(OPS) + 'rrrrrrr@{}}',
        '    \\toprule',
        '    & \\multicolumn{%d}{c}{Correctness by operator}'
        ' & \\multicolumn{4}{c}{Correctness by depth}'
        ' & \\multicolumn{3}{c}{Violation by impact} \\\\' % len(OPS),
        '    \\cmidrule(r){2-%d}\\cmidrule(r){%d-%d}\\cmidrule(l){%d-%d}'
        % (len(OPS) + 1, len(OPS) + 2, len(OPS) + 5,
           len(OPS) + 6, len(OPS) + 8),
        '    Approach & %s & $D2$ & $D3$ & $D4$ & $\\Delta$'
        ' & $I2$ & $I3$ & $I4$ \\\\'
        % ' & '.join(OP_SHORT[name] for name in OPS),
        '    & %s & \\multicolumn{4}{c}{} & \\multicolumn{3}{c}{} \\\\'
        % ' & '.join('\\scriptsize $n{=}%d$' % counts[name] for name in OPS),
        '    \\midrule',
    ]
    for method in ROWS:
        cells = ['%.1f' % float(op.loc[name, '%s_obj' % method])
                 for name in OPS]
        d = depth.loc[method]


        delta = float(d['D4_minus_D2'])
        tail = ['%.1f' % d['D2'], '%.1f' % d['D3'], '%.1f' % d['D4'],
                '$%s%.1f$' % ('-' if delta < 0 else '', abs(delta))]
        s = sev.loc[method]
        viol = ['%.1f' % float(s['I%d_viol' % tier]) for tier in (2, 3, 4)]
        label = method
        if method == 'StateWise':
            label = '\\textbf{%s}' % method
            cells = ['\\textbf{%s}' % v for v in cells]
            tail = ['\\textbf{%s}' % v for v in tail[:3]] + [
                '$\\mathbf{%s%.1f}$' % ('-' if delta < 0 else '', abs(delta))]
            viol = ['\\textbf{%s}' % v for v in viol]
        lines.append('    %s & %s & %s & %s \\\\'
                     % (label, ' & '.join(cells), ' & '.join(tail),
                        ' & '.join(viol)))
    lines += [
        '    \\bottomrule',
        '  \\end{tabular*}',
        '  \\parbox{\\textwidth}{\\footnotesize\\vspace{2pt}',
        '  Depth cells use the full 150-case set ($D2{:}55$, $D3{:}61$,',
        '  $D4{:}34$); impact cells use ($I2{:}34$, $I3{:}78$, $I4{:}38$). The',
        '  two smallest operator cells are underpowered and reported',
        '  descriptively: neither reaches significance individually',
        '  ($p_H{=}0.25$).}',
        '\\end{table*}',
    ]
    body = '\n'.join(lines) + '\n'
    (OUT / 'appendix_designfactor_matrix.tex').write_text(body, encoding='utf-8')
    print('wrote latex/appendix_designfactor_matrix.tex (%d lines)'
          % body.count('\n'))

    import re
    bad = [m.group(0) for m in re.finditer(r'\d+\.\d\d+', body)]
    print('values with more than one decimal: %d' % len(bad))


if __name__ == '__main__':
    main()
