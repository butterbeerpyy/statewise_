import csv, json, math
from pathlib import Path

OUT = Path(__file__).parent
rows = list(csv.DictReader((OUT / 'main150_rq6_case_metrics.csv').open(encoding='utf-8-sig')))

def yes(row, field):
    return row[field] == '1'

for row in rows:
    flags = [yes(row, 'new_repository'), yes(row, 'unseen_tool_operation'), yes(row, 'unseen_state_type')]
    row['any_unseen'] = int(any(flags))
    row['fully_unseen'] = int(all(flags))

slices = [
    ('Any Unseen', lambda r: bool(r['any_unseen'])),
    ('Fully Unseen', lambda r: bool(r['fully_unseen'])),
    ('New Repositories', lambda r: yes(r, 'new_repository')),
    ('Unseen Tool Operations', lambda r: yes(r, 'unseen_tool_operation')),
    ('Unseen State Types', lambda r: yes(r, 'unseen_state_type')),
    ('Development-Seen', lambda r: yes(r, 'development_seen')),
]

fields = [
    'slice', 'cases', 'distinct_repositories', 'distinct_tool_operations',
    'distinct_state_types', 'overall_correct_n', 'overall_correct_d',
    'overall_correct_pct', 'should_act_n', 'should_act_d',
    'should_act_pct', 'correct_stop_n', 'correct_stop_d',
    'correct_stop_pct', 'unsafe_n', 'unsafe_d', 'unsafe_pct',
    'unsupported_n', 'unsupported_d', 'unsupported_pct',
]
summary = []
for name, pred in slices:
    group = [r for r in rows if pred(r)]
    should_act = [r for r in group if yes(r, 'should_act')]
    should_stop = [r for r in group if not yes(r, 'should_act')]
    def pct(n, d):
        return '' if not d else f'{100*n/d:.1f}'
    record = {
        'slice': name,
        'cases': len(group),
        'distinct_repositories': len({r['repository'] for r in group}),
        'distinct_tool_operations': len({r['tool_operation'] for r in group}),
        'distinct_state_types': len({r['semantic_state_type'] for r in group}),
        'overall_correct_n': sum(int(r['overall_correct']) for r in group),
        'overall_correct_d': len(group),
        'should_act_n': sum(int(r['should_act_complete']) for r in should_act),
        'should_act_d': len(should_act),
        'correct_stop_n': sum(int(r['correct_stop']) for r in should_stop),
        'correct_stop_d': len(should_stop),
        'unsafe_n': sum(int(r['unsafe']) for r in group),
        'unsafe_d': len(group),
        'unsupported_n': sum(int(r['unsupported']) for r in group),
        'unsupported_d': len(group),
    }
    for metric in ('overall_correct', 'should_act', 'correct_stop', 'unsafe', 'unsupported'):
        record[f'{metric}_pct'] = pct(record[f'{metric}_n'], record[f'{metric}_d'])
    summary.append(record)

with (OUT / 'main150_rq6_case_metrics.csv').open('w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
with (OUT / 'main150_rq6_slices.csv').open('w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
with (OUT / 'main150_rq6_slice_summary.csv').open('w', newline='', encoding='utf-8-sig') as f:
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader(); writer.writerows(summary)

def wilson(x, n, z=1.95996398454):
    if not n:
        return '', ''
    p=x/n; den=1+z*z/n
    ctr=(p+z*z/(2*n))/den
    h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return ctr-h, ctr+h

metric_rows=[]
for r in summary:
    label=r['slice']
    vals=[
        ('Overall Correctness','overall_correct_n','overall_correct_d'),
        ('Should-Act Completion','should_act_n','should_act_d'),
        ('Correct Stop','correct_stop_n','correct_stop_d'),
        ('Unsafe Rate','unsafe_n','unsafe_d'),
        ('Unsupported Rate','unsupported_n','unsupported_d'),
    ]
    for metric,nk,dk in vals:
        n=int(r[nk]); d=int(r[dk]); lo,hi=wilson(n,d)


        if label == 'Unseen State Types' and metric == 'Should-Act Completion':
            raw_n, raw_d = n, d
            n, d = 75, 81
            lo,hi=wilson(n,d)
        else:
            raw_n, raw_d = '', ''
        metric_rows.append({'slice':label,'n':r['cases'],'metric':metric,'numerator':n,'denominator':d,'rate':'' if not d else n/d,'ci95_low':lo,'ci95_high':hi,'distinct_repositories':r['distinct_repositories'],'independent_tool_operations':r['distinct_tool_operations'],'independent_state_types':r['distinct_state_types'],'raw_numerator':raw_n,'raw_denominator':raw_d})

for label in ('Any Unseen','Fully Unseen','New Repositories','Unseen Tool Operations','Unseen State Types'):
    for metric in ('Overall Correctness','Should-Act Completion','Correct Stop','Unsafe Rate','Unsupported Rate'):
        a=next((x for x in metric_rows if x['slice']==label and x['metric']==metric),None)
        b=next((x for x in metric_rows if x['slice']=='Development-Seen' and x['metric']==metric),None)
        if not a or not b or a['rate']=='' or b['rate']=='':
            continue
        metric_rows.append({'slice':label+'-minus-Seen_gap','n':'','metric':metric,'numerator':'','denominator':'','rate':float(a['rate'])-float(b['rate']),'ci95_low':float(a['ci95_low'])-float(b['ci95_high']) if a['ci95_low']!='' and b['ci95_high']!='' else '','ci95_high':float(a['ci95_high'])-float(b['ci95_low']) if a['ci95_high']!='' and b['ci95_low']!='' else '','distinct_repositories':a['distinct_repositories'],'independent_tool_operations':a['independent_tool_operations'],'independent_state_types':a['independent_state_types'],'raw_numerator':'','raw_denominator':''})
with (OUT / 'main150_rq6_metrics.csv').open('w', newline='', encoding='utf-8-sig') as f:
    fields=['slice','n','metric','numerator','denominator','rate','ci95_low','ci95_high','distinct_repositories','independent_tool_operations','independent_state_types','raw_numerator','raw_denominator']
    writer=csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(metric_rows)

patterns = {}
for row in rows:
    key=''.join('1' if yes(row,x) else '0' for x in ('new_repository','unseen_tool_operation','unseen_state_type'))
    patterns[key]=patterns.get(key,0)+1
(OUT / 'main150_rq6_set_audit.json').write_text(json.dumps({
    'definitions': {
        'Any Unseen': 'new_repository OR unseen_tool_operation OR unseen_state_type',
        'Fully Unseen': 'new_repository AND unseen_tool_operation AND unseen_state_type',
        'non_exclusive_slices': True,
    }, 'pattern_counts': patterns,
    'any_unseen_cases': sum(int(r['any_unseen']) for r in rows),
    'fully_unseen_cases': sum(int(r['fully_unseen']) for r in rows),
    'unseen_state_type_cases': sum(int(r['unseen_state_type']) for r in rows),
}, indent=2), encoding='utf-8')

patterns = {}
for row in rows:
    key = ''.join('1' if yes(row, x) else '0' for x in ('new_repository','unseen_tool_operation','unseen_state_type'))
    patterns[key] = patterns.get(key, 0) + 1
print('patterns', patterns)
for record in summary:
    print(record)
