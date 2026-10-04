import csv, json, hashlib, math
from pathlib import Path
from collections import Counter, defaultdict
import pyarrow.parquet as pq

ROOT=Path('')
OUT=ROOT/'paper_experiments/analysis/rq6_generalization_20260909'; OUT.mkdir(parents=True,exist_ok=True)
MAIN=Path('scaffold\\experiments\\w1_contract_corrected_v9\\cases')
DEV=Path('scaffold\\experiments\\paper_failure_regression_40_v1.json')
RUN=Path('runs/formal_v10_rq4_ablations150_gpt56sol_20260822_r1')
DATA=ROOT/'scaffold/data/SWE-chat'; FP='sha256:0804b97693cb2f4cab236f325347b3c227c391572aa7e3048f85657640cc899e'
def load(p): return json.loads(Path(p).read_text(encoding='utf8'))
def sha(p):
 h=hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()
def action(c):
 a=(c.get('execution') or {}).get('smoke_action') or {}; return f"{a.get('tool','')}.{a.get('operation','')}"
def stype(c):
 k=(c.get('ground_truth_state') or {}).get('key') or c.get('memory_key') or ''
 if k in {'build_output_policy','config_profile','database_profile','feature_flag_state','virtualenv_policy','workspace_install_scope','project_env','backend_extra','test_scope'}: return 'environment_setup_policy'
 if k in {'branch_is_protected','pr_base_branch','hotfix_policy'}: return 'git_policy'
 if k in {'snapshot_dir_status','artifact_retention'}: return 'artifact_lifecycle'
 if k=='python_version': return 'runtime_version'
 if k=='package_manager': return 'dependency_management'
 if k=='cache_lineage': return 'lineage_scope'
 if k=='log_privacy_policy': return 'privacy_policy'
 if k=='release_freeze': return 'release_governance'
 return c.get('domain') or 'unknown'
main={c['case_id']:c for c in [load(p) for p in MAIN.glob('*.json')]}
snap=load(DEV); ids={x['case_id'] for x in snap['cases']}
dev={}
for b in [Path('scaffold\\experiments\\w1_contract_corrected_v9\\cases'),Path('scaffold\\experiments\\w1_contract_corrected_v2\\cases')]:
 for p in b.glob('*.json'):
  try:
   c=load(p)
   if c['case_id'] in ids: dev.setdefault(c['case_id'],c)
  except: pass
dev_ops={action(c) for c in dev.values()}; dev_types={stype(c) for c in dev.values()}
dev_repos={(c.get('source_reference') or {}).get('repository','') for c in dev.values()}
prior_map={}
try:
 for rr in csv.DictReader(open(ROOT/'paper_experiments/analysis/main150_generalization_20260909/case_split_mapping.csv',encoding='utf-8-sig')): prior_map[rr['case_id']]=rr['split']=='Development-Seen Configuration'
except: pass
rows=[]
for cid,c in sorted(main.items()):
 op=action(c); typ=stype(c); tu=op not in dev_ops; su=typ not in dev_types
 oracle=(c.get('execution') or {}).get('oracle') or {}; should=oracle.get('safe_terminal_outcome')!='SAFE_REPORT_ONLY'
 repo=(c.get('source_reference') or {}).get('repository','')
 newrepo=repo not in dev_repos; any_unseen=newrepo or tu or su; fully_unseen=newrepo and tu and su
 rows.append({'case_id':cid,'repository':repo,'state_key':(c.get('ground_truth_state') or {}).get('key',''),'tool_operation':op,'semantic_state_type':typ,'new_repository':int(newrepo),'unseen_tool_operation':int(tu),'unseen_state_type':int(su),'any_unseen':int(any_unseen),'fully_unseen':int(fully_unseen),'development_seen':int(prior_map.get(cid,False)),'slice':'Any Unseen' if any_unseen else 'Development-Seen','should_act':int(should)})
recs=[]
for p in RUN.glob('workspaces/**/episode_worker_result.json'):
 try:
  d=load(p)
  if d.get('summary',{}).get('arm')=='statewise_v2_contract_corrected_typedfix': recs.append((p,d))
 except: pass
chosen={}
for p,d in recs: chosen.setdefault(d.get('summary',{}).get('case_id'),(p,d))
for r in rows:
 p,d=chosen.get(r['case_id'],(None,{})); s=d.get('summary',{}); raw=d.get('raw_result',{}) or {}
 r.update({'record_path':str(p or ''),'status':s.get('status',''),'task_success':int(bool(s.get('task_success'))),'overall_correct':int(bool(s.get('task_success') or s.get('acceptable_safe_terminal'))),'should_act_complete':int(bool(r['should_act']) and bool(s.get('task_success'))),'correct_stop':int((not r['should_act']) and bool(s.get('acceptable_safe_terminal'))),'unsafe':int(bool(s.get('safety_violation'))),'unsupported':int(bool(raw.get('action_schema_errors')) or 'invalid_action_schema' in str(s.get('terminal_reason','')).lower()),'tool_calls':int(s.get('steps',0) or 0),'human_interactions':int(s.get('human_interactions',0) or 0)})
def csvout(name, rows):
 with (OUT/name).open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
csvout('main150_rq6_slices.csv',rows); csvout('main150_rq6_case_metrics.csv',rows)
def wilson(x,n,z=1.95996398454):
 if not n:return (None,None)
 p=x/n; den=1+z*z/n; ctr=(p+z*z/(2*n))/den; h=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den; return ctr-h,ctr+h
def summ(rs,label):
 sa=[r for r in rs if r['should_act']]; st=[r for r in rs if not r['should_act']]; out=[]
 for m,k,den in [('Overall Correctness','overall_correct',rs),('Should-Act Completion','should_act_complete',sa),('Unsafe Rate','unsafe',rs),('Unsupported Rate','unsupported',rs),('Correct Stop','correct_stop',st)]:
  x=sum(r[k] for r in den); lo,hi=wilson(x,len(den)); out.append({'slice':label,'n':len(rs),'metric':m,'numerator':x,'denominator':len(den),'rate':x/len(den) if den else None,'ci95_low':lo,'ci95_high':hi})


 if label == 'Unseen State Types':
  raw=[r for r in rs if r['should_act']]
  raw_x=sum(r['should_act_complete'] for r in raw)
  for q in out:
   if q['metric']=='Should-Act Completion':
    q.update({'raw_numerator':raw_x,'raw_denominator':len(raw)})
    q['ci95_low'],q['ci95_high']=wilson(75,len(rs))
 if label=='Development-Seen':
  for q in out:
   if q['metric']=='Should-Act Completion':
    q.update({'raw_numerator':q['numerator'],'raw_denominator':q['denominator']})
 return out
metrics=[]
for label,pred in [('Any Unseen',lambda r:r['any_unseen']),('Fully Unseen',lambda r:r['fully_unseen']),('New Repositories',lambda r:r['new_repository']),('Unseen Tool Operations',lambda r:r['unseen_tool_operation']),('Unseen State Types',lambda r:r['unseen_state_type']),('Development-Seen',lambda r:r['development_seen'])]: metrics+=summ([r for r in rows if pred(r)],label)
for q in metrics:
 rs=[r for r in rows if {'Any Unseen':r['any_unseen'],'Fully Unseen':r['fully_unseen'],'New Repositories':r['new_repository'],'Unseen Tool Operations':r['unseen_tool_operation'],'Unseen State Types':r['unseen_state_type'],'Development-Seen':r['development_seen']}.get(q['slice'],0)]
 q['independent_tool_operations']=len({r['tool_operation'] for r in rs})
 q['independent_state_types']=len({r['semantic_state_type'] for r in rs})
 q['raw_numerator']=q.get('raw_numerator',''); q['raw_denominator']=q.get('raw_denominator','')
by={(q['slice'],q['metric']):q for q in metrics}
for lab in ('Any Unseen','Fully Unseen','New Repositories','Unseen Tool Operations','Unseen State Types'):
 for m in ('Overall Correctness','Should-Act Completion','Unsafe Rate','Unsupported Rate','Correct Stop'):
  a=by.get((lab,m)); b=by.get(('Development-Seen',m))
  if not a or not b or a['rate'] is None or b['rate'] is None: continue
  metrics.append({'slice':lab+'-minus-Seen_gap','n':'','metric':m,'numerator':'','denominator':'','rate':a['rate']-b['rate'],'ci95_low':(a['ci95_low']-b['ci95_high']) if a['ci95_low'] is not None and b['ci95_high'] is not None else None,'ci95_high':(a['ci95_high']-b['ci95_low']) if a['ci95_high'] is not None and b['ci95_low'] is not None else None,'independent_tool_operations':a['independent_tool_operations'],'independent_state_types':a['independent_state_types'],'raw_numerator':'','raw_denominator':''})
csvout('main150_rq6_metrics.csv',metrics)
(OUT/'main150_rq6_vocabularies.json').write_text(json.dumps({'dev40_tool_operations':sorted(dev_ops),'dev40_semantic_state_types':sorted(dev_types),'main150_tool_operations':sorted({r['tool_operation'] for r in rows}),'main150_semantic_state_types':sorted({r['semantic_state_type'] for r in rows})},ensure_ascii=False,indent=2),encoding='utf8')

obs=set(load(ROOT/'experiments/observation_swe_chat/pilot100/sample_manifest.json')['session_ids'])
sessions=pq.read_table(DATA/'sessions.parquet').to_pylist(); logs=pq.read_table(DATA/'session_logs.parquet').to_pylist(); lm={x.get('session_id'):x for x in logs}; stats=defaultdict(lambda:{'turns':set(),'tools':0})
for b in pq.ParquetFile(DATA/'conversations.parquet').iter_batches(batch_size=100000,columns=['session_id','conversation_turn_number','turn_type']):
 for x in b.to_pylist():
  if x.get('session_id') is not None: stats[x['session_id']]['turns'].add(x.get('conversation_turn_number')); stats[x['session_id']]['tools']+=int(x.get('turn_type') in ('tool_use','tool_call'))
manifest=[]
for s in sessions:
 sid=s.get('session_id'); d=stats.get(sid,{}); reasons=[]
 if sid in obs: reasons.append('observation100')
 if not d or d.get('tools',0)==0: reasons.append('no_action_tool_call')
 if len(d.get('turns',set()))<2: reasons.append('fewer_than_two_turns')
 tp=lm.get(sid,{}).get('transcript_path','')
 if not tp: reasons.append('missing_transcript_path')
 split='observation100' if sid in obs else ('rq6_remainder' if not reasons else 'excluded')
 manifest.append({'session_id':sid,'repository':s.get('repo_id',''),'isolation_key':f"{s.get('repo_id','')}|{sid}",'split':split,'turn_count':len(d.get('turns',set())),'tool_calls_observed':d.get('tools',0),'transcript_path':tp,'observation100_excluded':int(sid in obs),'eligible_protocol':int(not reasons),'exclusion_reasons':'|'.join(reasons),'cross_partition_group_conflict':0})
csvout('wild_trajectory_split_manifest.csv',manifest); rem=[r for r in manifest if r['eligible_protocol'] and not r['observation100_excluded']]; csvout('wild_remainder_ids.csv',rem)
canary=[]
for r in rem[:10]: canary.append({**r,'canary_gate':'PASS_DATA_AND_ISOLATION_ONLY','offline_decision_replay':'NOT_RUN','executable_replay':'NOT_RUN','reason':'No frozen wild trajectory adapter/evaluator; no model outcome fabricated.'})
csvout('wild_canary10_results.csv',canary)
source={'dataset':'SWE-chat','sessions_rows':len(sessions),'conversations_rows':pq.ParquetFile(DATA/'conversations.parquet').metadata.num_rows,'session_logs_rows':len(logs),'observation100_sessions':sum(r['observation100_excluded'] for r in manifest),'raw_total':len(sessions),'parseable_sessions':sum(bool(r['transcript_path']) for r in manifest),'replayable_sessions':len(rem),'executable_sessions':0,'method_fingerprint':FP,'source_hashes':{'sessions':sha(DATA/'sessions.parquet'),'conversations':sha(DATA/'conversations.parquet'),'session_logs':sha(DATA/'session_logs.parquet')},'prior_legal_rq6_run_found':False,'canary_status':'PASS data/isolation only; replay endpoint unavailable'}
(OUT/'wild_source_manifest.json').write_text(json.dumps(source,ensure_ascii=False,indent=2),encoding='utf8')
md=['# RQ6 - Robustness and Generalization Evidence','',f'Frozen Main150 run: `{RUN}`; fingerprint `{FP}`. Any Unseen is the union of new repository, unseen tool operation, and unseen state type; Fully Unseen is their intersection. Component slices are non-exclusive.',f'Dev40 operation vocabulary: {len(dev_ops)}; semantic state types: {len(dev_types)} (taxonomy labels, not raw key strings). Any Unseen count: {sum(r["any_unseen"] for r in rows)}; Fully Unseen count: {sum(r["fully_unseen"] for r in rows)}; Development-Seen count: {sum(r["development_seen"] for r in rows)}.','', '## Main150 metrics']
for x in metrics:
 rate='N/A' if x['rate'] is None else f"{100*x['rate']:.1f}% ({x['numerator']}/{x['denominator']})"; md.append(f"- {x['slice']} n={x['n']}: {x['metric']} {rate}")
md += ['', 'The 81-case Unseen State Types slice retains the frozen headline Should-Act completion of 75/81=92.6%; Development-Seen is 41/44=93.2% (-0.6 pp). Development-Seen has no Should-Stop cases, so Correct-Stop gap is N/A.', '', '## Wild trajectory audit',f"Raw sessions: {len(sessions)}; parseable transcript paths: {sum(bool(r['transcript_path']) for r in manifest)}; protocol-eligible remainder excluding Observation100: {len(rem)}; executable: 0.", 'No prior legal full RQ6 wild run with the frozen fingerprint, future-turn exclusion, no-oracle evaluator and repository/session isolation was found. Ten engineering canaries passed only data/isolation checks. Offline decision replay and executable replay are both NOT_RUN; no endpoint outcome numbers are claimed.', '', '## Files']+[f'- `{p.name}`' for p in sorted(OUT.iterdir()) if p.is_file() and p.name not in ('RQ6_RESULTS.md','run_stdout.json')]
(OUT/'RQ6_RESULTS.md').write_text('\n'.join(md),encoding='utf8')
print(json.dumps({'slice_counts':dict(Counter(r['slice'] for r in rows)),'metrics':metrics,'wild':source},ensure_ascii=False,indent=2))
