"""Bind a new download to the exact acknowledged body reused under an Owner grant."""
from pathlib import Path
from public_source_seed import read_object,ReuseJournal,canonical,build_seed,SeedError

def reused_body_context(run,manifest,norm,body):
 context=manifest.get('source_continuation')
 if not isinstance(context,dict) or context.get('kind')!='wb-replies-v1' or manifest['request'].get('platform')!='wb' or context.get('new_content_quota') is not False:raise ValueError('continuation_media_denied')
 seed=read_object(Path(run)/'public-source-seed.json')[0]
 if seed.get('seed_sha256')!=context.get('seed_sha256') or seed.get('seed_sha256')!=context.get('proof',{}).get('seed_sha256') or seed.get('account_context')!=context.get('account_context') or seed.get('source_run_id')!=__import__('source_continuation_chain').seed_source(context):raise ValueError('continuation_media_denied')
 rebuilt=build_seed(Path(run).parent/seed['source_run_id'],seed['account_context'],seed['source_pins'])
 if canonical(rebuilt)!=canonical(seed) or canonical(body)!=canonical(seed['topic']['normalized_record']):raise ValueError('continuation_media_denied')
 rows=[r for r in norm.get('source_reuse',[]) if r.get('kind')=='topic' and r.get('entity_id')==seed['content_id']]
 if len(rows)!=1:raise ValueError('continuation_media_denied')
 evidence=rows[0];journal=ReuseJournal(Path(run),seed,existing_only=True);journal.split_records([])
 metadata=journal.lookup('topic',seed['content_id'],evidence.get('readback_observation_sha256'))
 if metadata is None or canonical({**metadata,'readback_run_id':Path(run).name})!=canonical(evidence):raise ValueError('continuation_media_denied')
 return context
