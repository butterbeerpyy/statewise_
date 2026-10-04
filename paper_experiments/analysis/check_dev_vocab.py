import json,glob,collections
snap=json.load(open('scaffold\\experiments\\paper_failure_regression_40_v1.json',encoding='utf8')); ids={x['case_id'] for x in snap['cases']}
for b in ['scaffold\\experiments\\w1_contract_corrected_v2\\cases','scaffold\\experiments\\w1_contract_corrected_v9\\cases']:
 cs=[]
 for f in glob.glob(b+'\\*.json'):
  c=json.load(open(f,encoding='utf8'))
  if c.get('case_id') in ids: cs.append(c)
 print(b,len(cs)); print(collections.Counter((c.get('execution',{}).get('smoke_action') or {}).get('tool')+'.'+(c.get('execution',{}).get('smoke_action') or {}).get('operation') for c in cs)); print(collections.Counter(c.get('domain') for c in cs))
